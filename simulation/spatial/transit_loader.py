"""
simulation/spatial/transit_loader.py

This module provides functionality to load transit network data for UK cities using the 
TransitLand API. It supports fetching live data, caching results, and building a graph 
representation of transit stops and routes.

The purpose is to pivot away from GTFS ZIP dependence and use a hybrid architecture. This 
allows for more dynamic updates and potentially richer data access, while still
maintaining compatibility with existing systems.

3 tier RTD_SIM Transit Architecture:
Tier 1 — Live REST Source (Primary)

Use TransitLand REST: 
stops; routes; operators; departures (later); routing (later)

Use this for:
current city graph; nearby stops; live route discovery; dynamic simulation inputs

Tier 2 — Cached Snapshot (Fallback)
Use cached JSON snapshots of the live REST data, refreshed every 24 hours stored in 
RTD_SIM/data/. This provides a fallback when the API is unavailable or rate-limited.

Use it when:
API unavailable; rate limit exceeded; offline mode; testing mode; deterministic replay mode

Tier 3 — Static GTFS (Legacy Fallback)
Use GTFS ZIP files as a last resort fallback, loaded externerally. This is the legacy 
method and should be phased out over time.

"""

import os
import json
import math
import time
import requests

from pathlib import Path
from collections import defaultdict

# ==========================================================
# ROOT / PATHS
# ==========================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CACHE_DIR = PROJECT_ROOT / "cache"
DATA_DIR = PROJECT_ROOT / "data"

CACHE_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# ==========================================================
# CONFIG
# ==========================================================

API_KEY = os.getenv("TRANSITLAND_API_KEY")
BASE_URL = "https://transit.land/api/v2/rest"

CACHE_TTL_HOURS = 24
HTTP_TIMEOUT = 20
HTTP_RETRIES = 3
RETRY_SLEEP = 1.0

# lon1, lat1, lon2, lat2
CITY_BBOX = {
    "edinburgh": (-3.45, 55.85, -3.05, 56.05),
    "glasgow": (-4.45, 55.75, -4.05, 55.95),
    "london": (-0.55, 51.25, 0.25, 51.75),
    "manchester": (-2.65, 53.25, -1.95, 53.65),   # widened
    "leeds": (-1.75, 53.65, -1.35, 53.95),
    "birmingham": (-2.10, 52.35, -1.65, 52.65),
    "liverpool": (-3.10, 53.25, -2.70, 53.55),
    "bristol": (-2.75, 51.35, -2.45, 51.55),
    "newcastle": (-1.80, 54.90, -1.45, 55.10),
}

# ==========================================================
# HELPERS
# ==========================================================

def log(msg):
    print(f"[transit_loader] {msg}")


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000

    p1 = math.radians(lat1)
    p2 = math.radians(lat2)

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    )

    return 2 * R * math.asin(math.sqrt(a))


def route_mode(route_type):
    mapping = {
        0: "tram",
        1: "subway",
        2: "rail",
        3: "bus",
        4: "ferry",
        5: "cable",
        6: "gondola",
        7: "funicular",
        200: "coach",
    }
    return mapping.get(route_type, "other")


# ==========================================================
# CACHE
# ==========================================================

def cache_path(city):
    return CACHE_DIR / f"{city.lower()}_graph.json"


def cache_age_hours(path):
    if not path.exists():
        return 1e9
    return (time.time() - path.stat().st_mtime) / 3600


def cache_valid(path):
    return path.exists() and cache_age_hours(path) <= CACHE_TTL_HOURS


def save_cache(city, graph):
    p = cache_path(city)

    with open(p, "w") as f:
        json.dump(graph, f, indent=2)

    log(f"cache saved: {p.name}")


def load_cache(city):
    p = cache_path(city)

    if not p.exists():
        return None

    with open(p) as f:
        graph = json.load(f)

    return graph


# ==========================================================
# STATIC
# ==========================================================

def load_static(city):
    p = DATA_DIR / f"{city.lower()}.json"

    if not p.exists():
        return None

    with open(p) as f:
        graph = json.load(f)

    return graph


# ==========================================================
# HTTP
# ==========================================================

def request_json(endpoint, params):
    if not API_KEY:
        raise RuntimeError("TRANSITLAND_API_KEY missing")

    params = dict(params)
    params["apikey"] = API_KEY

    url = f"{BASE_URL}/{endpoint}"

    last_error = None

    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            r = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            return r.json()

        except Exception as e:
            last_error = e
            log(f"{endpoint} attempt {attempt}/{HTTP_RETRIES} failed: {e}")

            if attempt < HTTP_RETRIES:
                time.sleep(RETRY_SLEEP)

    raise last_error


# ==========================================================
# LIVE FETCH
# ==========================================================

def fetch_city_live(city):
    city = city.lower()

    if city not in CITY_BBOX:
        raise ValueError(f"No bbox configured for {city}")

    lon1, lat1, lon2, lat2 = CITY_BBOX[city]
    bbox = f"{lon1},{lat1},{lon2},{lat2}"

    log(f"fetching live data for {city}")

    stops_json = request_json("stops", {
        "bbox": bbox,
        "per_page": 300
    })

    routes_json = request_json("routes", {
        "bbox": bbox,
        "per_page": 300
    })

    stops = stops_json.get("stops", [])
    routes = routes_json.get("routes", [])

    if not stops:
        raise RuntimeError("No live stops returned")

    return stops, routes


# ==========================================================
# GRAPH BUILD
# ==========================================================

def build_graph(stops, routes):
    graph = {
        "nodes": {},
        "edges": [],
        "meta": {}
    }

    # ------------------------------------------------------
    # NODES
    # ------------------------------------------------------

    for s in stops:
        sid = s["onestop_id"]

        lon, lat = s["geometry"]["coordinates"]

        graph["nodes"][sid] = {
            "id": sid,
            "name": s.get("stop_name", sid),
            "lat": lat,
            "lon": lon,
            "type": "stop"
        }

    nodes = list(graph["nodes"].values())

    # ------------------------------------------------------
    # WALK EDGES (local transfers)
    # ------------------------------------------------------

    edge_set = set()

    for i in range(len(nodes)):
        a = nodes[i]

        for j in range(i + 1, len(nodes)):
            b = nodes[j]

            d = haversine(a["lat"], a["lon"], b["lat"], b["lon"])

            if d <= 220:
                key = tuple(sorted([a["id"], b["id"]])) + ("walk",)

                if key not in edge_set:
                    edge_set.add(key)

                    graph["edges"].append({
                        "from": a["id"],
                        "to": b["id"],
                        "mode": "walk",
                        "weight": round(d)
                    })

    # ------------------------------------------------------
    # TRANSIT EDGES (sparse chain links)
    # ------------------------------------------------------

    mode_routes = defaultdict(set)

    for r in routes:
        mode = route_mode(r.get("route_type", 3))
        short = r.get("route_short_name", "unknown")
        mode_routes[mode].add(short)

    ordered = sorted(nodes, key=lambda x: (x["lon"], x["lat"]))

    for mode, route_names in mode_routes.items():

        # create only one sparse chain per route
        for route_name in route_names:

            step = 3 if mode == "bus" else 1

            for i in range(0, len(ordered) - step, step):
                a = ordered[i]
                b = ordered[i + step]

                d = haversine(a["lat"], a["lon"], b["lat"], b["lon"])

                # realistic caps
                if mode == "bus" and d > 5000:
                    continue
                if mode in ("tram", "rail") and d > 8000:
                    continue
                if mode == "walk":
                    continue

                key = tuple(sorted([a["id"], b["id"]])) + (mode, route_name)

                if key not in edge_set:
                    edge_set.add(key)

                    graph["edges"].append({
                        "from": a["id"],
                        "to": b["id"],
                        "mode": mode,
                        "route": route_name,
                        "weight": round(d)
                    })

    # ------------------------------------------------------
    # META
    # ------------------------------------------------------

    mode_counts = defaultdict(int)

    for e in graph["edges"]:
        mode_counts[e["mode"]] += 1

    graph["meta"] = {
        "nodes": len(graph["nodes"]),
        "edges": len(graph["edges"]),
        "edge_modes": dict(mode_counts)
    }

    return graph


# ==========================================================
# LOADER
# ==========================================================

def load_city_graph(city, mode="auto"):
    city = city.lower()

    # ------------------------------------------------------
    # LIVE FIRST
    # ------------------------------------------------------

    if mode in ("auto", "live"):
        try:
            stops, routes = fetch_city_live(city)

            graph = build_graph(stops, routes)

            graph["meta"]["source"] = "live"

            save_cache(city, graph)

            return graph

        except Exception as e:
            log(f"live failed for {city}: {e}")

            if mode == "live":
                raise

    # ------------------------------------------------------
    # CACHE (fresh or stale)
    # ------------------------------------------------------

    if mode in ("auto", "cache"):
        graph = load_cache(city)

        if graph:
            age = round(cache_age_hours(cache_path(city)), 1)

            graph["meta"]["source"] = "cache"
            graph["meta"]["cache_age_hours"] = age

            log(f"using cache for {city} ({age}h old)")
            return graph

    # ------------------------------------------------------
    # STATIC
    # ------------------------------------------------------

    graph = load_static(city)

    if graph:
        graph["meta"]["source"] = "static"
        log(f"using static pack for {city}")
        return graph

    raise RuntimeError(f"No graph available for {city}")


# ==========================================================
# MULTI CITY
# ==========================================================

def merge_graphs(graphs):
    merged = {
        "nodes": {},
        "edges": [],
        "meta": {}
    }

    for g in graphs:
        merged["nodes"].update(g["nodes"])
        merged["edges"].extend(g["edges"])

    merged["meta"] = {
        "nodes": len(merged["nodes"]),
        "edges": len(merged["edges"]),
        "source": "merged"
    }

    return merged


def load_multi_city_graph(city_string, mode="auto"):
    cities = [
        c.strip().lower()
        for c in city_string.split(";")
        if c.strip()
    ]

    graphs = [load_city_graph(city, mode=mode) for city in cities]

    return merge_graphs(graphs)


# ==========================================================
# NEAREST STOP
# ==========================================================

def nearest_stop(graph, lat, lon):
    best = None
    best_d = 1e18

    for node in graph["nodes"].values():
        d = haversine(lat, lon, node["lat"], node["lon"])

        if d < best_d:
            best_d = d
            best = node

    return best, round(best_d)