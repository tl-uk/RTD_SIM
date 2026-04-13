"""
simulation/spatial/transit_loader.py

Hybrid live/cache/synthetic transit graph loader for RTD_SIM
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

from __future__ import annotations

import os
import json
import math
import time
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import networkx as nx
from dotenv import load_dotenv

# ---------------------------------------------------------------------
# ENV
# ---------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "debug" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(ROOT / ".env")

API_KEY = os.getenv("TRANSITLAND_API_KEY", "").strip()

BASE = "https://transit.land/api/v2/rest"

# ---------------------------------------------------------------------
# CITY BBOXES (compact central areas for speed)
# ---------------------------------------------------------------------

CITY_BBOX = {
    "edinburgh": (-3.35, 55.90, -3.15, 55.98),
    "glasgow": (-4.35, 55.82, -4.18, 55.90),
    "manchester": (-2.30, 53.45, -2.20, 53.52),
    "birmingham": (-1.98, 52.45, -1.82, 52.53),
    "liverpool": (-3.03, 53.37, -2.87, 53.47),
    "leeds": (-1.62, 53.76, -1.48, 53.84),
    "bristol": (-2.66, 51.42, -2.52, 51.50),
}

# ---------------------------------------------------------------------
# ROUTE TYPES
# ---------------------------------------------------------------------

GTFS_MODE = {
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

# ---------------------------------------------------------------------
# REQUESTS
# ---------------------------------------------------------------------


def api_get(endpoint: str, params: dict, timeout=20):
    params["apikey"] = API_KEY
    url = f"{BASE}/{endpoint}"
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def api_retry(endpoint, params, timeout=20, attempts=4):
    for i in range(attempts):
        try:
            return api_get(endpoint, params, timeout=timeout)
        except Exception as e:
            if i == attempts - 1:
                raise
            print(f"[transit_loader] retry {endpoint} {i+1}/{attempts}: {e}")
            time.sleep(1.2 * (i + 1))


# ---------------------------------------------------------------------
# CACHE
# ---------------------------------------------------------------------


def cache_path(city):
    return CACHE_DIR / f"{city}_graph.json"


def save_cache(city, payload):
    with open(cache_path(city), "w") as f:
        json.dump(payload, f)


def load_cache(city):
    p = cache_path(city)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return None


# ---------------------------------------------------------------------
# DISTANCE
# ---------------------------------------------------------------------


def hav(lat1, lon1, lat2, lon2):
    r = 6371000
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    d1 = math.radians(lat2 - lat1)
    d2 = math.radians(lon2 - lon1)

    a = (
        math.sin(d1 / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(d2 / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------
# GRAPH BUILDERS
# ---------------------------------------------------------------------


def add_nodes(G, stops):
    for s in stops:
        coords = s.get("geometry", {}).get("coordinates", [0, 0])
        lon, lat = coords
        sid = s["onestop_id"]

        G.add_node(
            sid,
            name=s.get("stop_name", sid),
            lat=lat,
            lon=lon,
            mode="stop",
        )


def add_route_edges(G, routes, stops):
    ids = list(G.nodes())

    # sequential synthetic enrichment
    for i in range(len(ids) - 1):
        a = ids[i]
        b = ids[i + 1]

        rt = routes[i % len(routes)] if routes else {}
        mode = GTFS_MODE.get(rt.get("route_type", 3), "bus")

        G.add_edge(a, b, weight=1, mode=mode)


def add_walk_edges(G, radius=350):
    nodes = list(G.nodes(data=True))

    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            a, da = nodes[i]
            b, db = nodes[j]

            d = hav(da["lat"], da["lon"], db["lat"], db["lon"])

            if d <= radius:
                G.add_edge(a, b, weight=d / 100, mode="walk")


def build_graph(stops, routes):
    G = nx.Graph()

    add_nodes(G, stops)
    add_route_edges(G, routes, stops)
    add_walk_edges(G)

    return G


# ---------------------------------------------------------------------
# SYNTHETIC FALLBACK
# ---------------------------------------------------------------------


def synthetic_graph(city):
    print(f"[transit_loader] synthetic fallback: {city}")

    G = nx.Graph()

    for i in range(10):
        lat = 55.95 + i * 0.002
        lon = -3.20 + i * 0.002

        sid = f"{city}_synthetic_{i}"

        G.add_node(
            sid,
            name=f"{city.title()} Stop {i}",
            lat=lat,
            lon=lon,
        )

    ids = list(G.nodes())

    for i in range(len(ids) - 1):
        G.add_edge(ids[i], ids[i + 1], weight=1, mode="bus")

    return G, "synthetic"


# ---------------------------------------------------------------------
# LIVE FETCH
# ---------------------------------------------------------------------


def fetch_city_live(city):
    city = city.lower()

    if city not in CITY_BBOX:
        return None, None

    west, south, east, north = CITY_BBOX[city]
    bbox = f"{west},{south},{east},{north}"

    def get_stops():
        return api_retry(
            "stops",
            {"bbox": bbox, "per_page": 20},
            timeout=25,
        )

    def get_routes():
        return api_retry(
            "routes",
            {"bbox": bbox, "per_page": 20},
            timeout=45,
        )

    with ThreadPoolExecutor(max_workers=2) as ex:
        fut1 = ex.submit(get_stops)
        fut2 = ex.submit(get_routes)

        stops = []
        routes = []

        for fut in as_completed([fut1, fut2]):
            try:
                data = fut.result()

                if "stops" in data:
                    stops = data["stops"]

                if "routes" in data:
                    routes = data["routes"]

            except Exception as e:
                print("[transit_loader] partial live failure:", e)

    if not stops:
        return None, None

    G = build_graph(stops, routes)

    status = "live_partial" if not routes else "live"

    return G, status


# ---------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------


def load_city_graph(city):
    # 1 live
    try:
        G, status = fetch_city_live(city)
        if G:
            save_graph_json(city, G, status)
            return G, status
    except Exception as e:
        print("[transit_loader] live failed:", e)

    # 2 cache
    payload = load_cache(city)
    if payload:
        G = graph_from_json(payload)
        return G, "cache"

    # 3 synthetic
    return synthetic_graph(city)


def load_multi_city_graph(city_text):
    cities = [c.strip().lower() for c in city_text.split(";") if c.strip()]

    graphs = []

    for c in cities:
        G, _ = load_city_graph(c)
        graphs.append(G)

    return nx.compose_all(graphs)


# ---------------------------------------------------------------------
# JSON SERIALIZATION
# ---------------------------------------------------------------------


def save_graph_json(city, G, source):
    payload = {
        "source": source,
        "nodes": [],
        "edges": [],
    }

    for n, d in G.nodes(data=True):
        payload["nodes"].append({"id": n, **d})

    for u, v, d in G.edges(data=True):
        payload["edges"].append({"u": u, "v": v, **d})

    save_cache(city, payload)


def graph_from_json(payload):
    G = nx.Graph()

    for n in payload["nodes"]:
        nid = n.pop("id")
        G.add_node(nid, **n)

    for e in payload["edges"]:
        u = e.pop("u")
        v = e.pop("v")
        G.add_edge(u, v, **e)

    return G


# ---------------------------------------------------------------------
# ANALYTICS
# ---------------------------------------------------------------------


def graph_summary(G):
    modes = {}

    for _, _, d in G.edges(data=True):
        m = d.get("mode", "unknown")
        modes[m] = modes.get(m, 0) + 1

    return {
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "modes": modes,
    }


def nearest_stop(G, lat, lon):
    best = None
    best_d = 1e18

    for n, d in G.nodes(data=True):
        dd = hav(lat, lon, d["lat"], d["lon"])
        if dd < best_d:
            best = (n, d)
            best_d = dd

    return best[0], best[1], round(best_d)