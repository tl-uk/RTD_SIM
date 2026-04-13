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

CITY_BBOX = {
    "edinburgh": (-3.45, 55.85, -3.05, 56.05),
    "glasgow": (-4.45, 55.75, -4.05, 55.95),
    "london": (-0.55, 51.25, 0.25, 51.75),
    "manchester": (-2.45, 53.35, -1.95, 53.65),
    "leeds": (-1.75, 53.65, -1.35, 53.95),
    "birmingham": (-2.10, 52.35, -1.65, 52.65),
    "liverpool": (-3.10, 53.25, -2.70, 53.55),
    "bristol": (-2.75, 51.35, -2.45, 51.55),
    "newcastle": (-1.80, 54.90, -1.45, 55.10),
}

# ==========================================================
# HELPERS
# ==========================================================

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


def request_json(endpoint, params):
    if not API_KEY:
        raise RuntimeError("TRANSITLAND_API_KEY missing")

    params["apikey"] = API_KEY

    url = f"{BASE_URL}/{endpoint}"

    r = requests.get(url, params=params, timeout=25)
    r.raise_for_status()

    return r.json()


# ==========================================================
# CACHE
# ==========================================================

def cache_path(city):
    return CACHE_DIR / f"{city.lower()}_graph.json"


def cache_valid(path):
    if not path.exists():
        return False

    age_hours = (time.time() - path.stat().st_mtime) / 3600
    return age_hours <= CACHE_TTL_HOURS


def save_cache(city, graph):
    with open(cache_path(city), "w") as f:
        json.dump(graph, f, indent=2)


def load_cache(city):
    p = cache_path(city)

    if p.exists():
        with open(p) as f:
            return json.load(f)

    return None


# ==========================================================
# STATIC
# ==========================================================

def load_static(city):
    p = DATA_DIR / f"{city.lower()}.json"

    if p.exists():
        with open(p) as f:
            return json.load(f)

    return None


# ==========================================================
# FETCH LIVE
# ==========================================================

def fetch_city_live(city):
    city = city.lower()

    if city not in CITY_BBOX:
        raise ValueError(f"No bbox configured for {city}")

    lon1, lat1, lon2, lat2 = CITY_BBOX[city]
    bbox = f"{lon1},{lat1},{lon2},{lat2}"

    stops = request_json("stops", {
        "bbox": bbox,
        "per_page": 300
    }).get("stops", [])

    routes = request_json("routes", {
        "bbox": bbox,
        "per_page": 300
    }).get("routes", [])

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

    # ------------------------------------------
    # Build nodes
    # ------------------------------------------
    for s in stops:
        sid = s["onestop_id"]

        lon, lat = s["geometry"]["coordinates"]

        graph["nodes"][sid] = {
            "id": sid,
            "name": s.get("stop_name", sid),
            "lat": lat,
            "lon": lon,
            "zone": s.get("zone_id"),
            "type": "stop"
        }

    node_ids = list(graph["nodes"].keys())

    # ------------------------------------------
    # Walking edges
    # ------------------------------------------
    for i in range(len(node_ids)):
        a = graph["nodes"][node_ids[i]]

        for j in range(i + 1, len(node_ids)):
            b = graph["nodes"][node_ids[j]]

            d = haversine(a["lat"], a["lon"], b["lat"], b["lon"])

            if d <= 250:
                graph["edges"].append({
                    "from": a["id"],
                    "to": b["id"],
                    "mode": "walk",
                    "weight": round(d)
                })

    # ------------------------------------------
    # Route clusters
    # ------------------------------------------
    route_groups = defaultdict(list)

    for r in routes:
        mode = route_mode(r.get("route_type", 3))
        short = r.get("route_short_name", "unknown")

        route_groups[(mode, short)].append(r)

    ordered_nodes = sorted(
        graph["nodes"].values(),
        key=lambda x: (x["lon"], x["lat"])
    )

    for (mode, route_name), _ in route_groups.items():

        for i in range(len(ordered_nodes) - 1):
            a = ordered_nodes[i]
            b = ordered_nodes[i + 1]

            d = haversine(a["lat"], a["lon"], b["lat"], b["lon"])

            if d <= 3500:
                graph["edges"].append({
                    "from": a["id"],
                    "to": b["id"],
                    "mode": mode,
                    "route": route_name,
                    "weight": round(d)
                })

    # ------------------------------------------
    # Metadata
    # ------------------------------------------
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
# PUBLIC LOADER
# ==========================================================

def load_city_graph(city, mode="auto"):
    city = city.lower()

    # ------------------------------------------
    # LIVE
    # ------------------------------------------
    if mode in ("auto", "live"):

        try:
            stops, routes = fetch_city_live(city)

            graph = build_graph(stops, routes)

            graph["meta"]["source"] = "live"

            save_cache(city, graph)

            return graph

        except Exception as e:
            if mode == "live":
                raise e

    # ------------------------------------------
    # CACHE
    # ------------------------------------------
    if mode in ("auto", "cache"):

        p = cache_path(city)

        if cache_valid(p):
            graph = load_cache(city)

            if graph:
                graph["meta"]["source"] = "cache"
                return graph

    # ------------------------------------------
    # STATIC
    # ------------------------------------------
    graph = load_static(city)

    if graph:
        graph["meta"]["source"] = "static"
        return graph

    raise RuntimeError(f"No graph available for {city}")


# ==========================================================
# MULTI CITY SUPPORT
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

    graphs = []

    for city in cities:
        graphs.append(load_city_graph(city, mode=mode))

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