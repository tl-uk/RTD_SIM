# RTD_SIM/debug/test_transitland_edinburgh_graph_v2.py
"""
TransitLand Edinburgh Graph Tester v2
=====================================

Builds a richer Edinburgh transit graph using TransitLand REST API.

Goals:
1. Pull multiple pages of stops/routes
2. Build walk-transfer edges
3. Build synthetic transit edges by route grouping / mode clustering
4. Support cache fallback when API unavailable
5. Save static snapshot usable as GTFS-style fallback for RTD_SIM

Run:
    python debug/test_transitland_edinburgh_graph_v2.py

Requirements:
    pip install networkx python-dotenv

Outputs:
    debug/edinburgh_graph_v2_summary.json
    debug/edinburgh_graph_cache.json
"""

from pathlib import Path
import os
import sys
import json
import math
import time
import urllib.request
import urllib.parse

import networkx as nx

# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------
HERE = Path(__file__).resolve()
PROJECT_ROOT = HERE.parents[1]
DEBUG_DIR = PROJECT_ROOT / "debug"
DEBUG_DIR.mkdir(exist_ok=True)

sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------
# ENV
# ---------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

API_KEY = os.getenv("TRANSITLAND_API_KEY", "").strip()

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------
BASE = "https://transit.land/api/v2/rest"
CACHE_FILE = DEBUG_DIR / "edinburgh_graph_cache.json"

# Wider Edinburgh region
BBOX = "-3.55,55.82,-3.00,56.08"

CITY_CENTRE = (-3.1938, 55.9533)

MAX_PAGES = 5
PER_PAGE = 200

WALK_LINK_M = 450
TRANSIT_LINK_M = 1800   # synthetic same-mode sequential links

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def hav(lon1, lat1, lon2, lat2):
    R = 6371000
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))


def infer_mode(name):
    s = (name or "").lower()
    if "tram" in s:
        return "tram"
    if "rail" in s or "train" in s or "station" in s:
        return "rail"
    return "bus"


def fetch(endpoint, page=1):
    params = {
        "bbox": BBOX,
        "per_page": PER_PAGE,
        "page": page,
    }

    if API_KEY:
        params["apikey"] = API_KEY

    url = f"{BASE}/{endpoint}?{urllib.parse.urlencode(params)}"

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        }
    )

    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def paged_fetch(endpoint, key):
    rows = []

    for page in range(1, MAX_PAGES + 1):
        try:
            data = fetch(endpoint, page)
            batch = data.get(key, [])
            rows.extend(batch)

            if len(batch) < PER_PAGE:
                break

            time.sleep(0.25)

        except Exception as e:
            print(f"⚠️ {endpoint} page {page} failed: {e}")
            break

    return rows


def save_cache(data):
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_cache():
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            return json.load(f)
    return None


# ---------------------------------------------------------------------
# Load live or cache
# ---------------------------------------------------------------------
print("=" * 78)
print("TransitLand Edinburgh Graph Tester v2")
print("=" * 78)

live_ok = False

try:
    print("Fetching live stops...")
    stops = paged_fetch("stops", "stops")

    print("Fetching live routes...")
    routes = paged_fetch("routes", "routes")

    if stops:
        save_cache({"stops": stops, "routes": routes})
        live_ok = True

except Exception as e:
    print("⚠️ Live fetch failed:", e)

if not live_ok:
    print("Using cache fallback...")
    cache = load_cache()

    if not cache:
        print("❌ No cache available.")
        sys.exit(1)

    stops = cache["stops"]
    routes = cache["routes"]

print(f"Stops loaded : {len(stops)}")
print(f"Routes loaded: {len(routes)}")

# ---------------------------------------------------------------------
# Build graph
# ---------------------------------------------------------------------
G = nx.Graph()

# Nodes
for s in stops:
    sid = s.get("onestop_id") or s.get("id")
    if not sid:
        continue

    name = s.get("name", sid)

    geom = s.get("geometry", {})
    coords = geom.get("coordinates", [None, None])

    if len(coords) < 2 or coords[0] is None:
        continue

    lon, lat = coords[0], coords[1]

    mode = infer_mode(name)

    G.add_node(
        sid,
        name=name,
        lon=lon,
        lat=lat,
        mode=mode
    )

node_ids = list(G.nodes())

# ---------------------------------------------------------------------
# Walk edges
# ---------------------------------------------------------------------
for i in range(len(node_ids)):
    a = node_ids[i]
    ax = G.nodes[a]["lon"]
    ay = G.nodes[a]["lat"]

    for j in range(i + 1, len(node_ids)):
        b = node_ids[j]
        bx = G.nodes[b]["lon"]
        by = G.nodes[b]["lat"]

        d = hav(ax, ay, bx, by)

        if d <= WALK_LINK_M:
            G.add_edge(a, b, weight=d, link="walk")

# ---------------------------------------------------------------------
# Synthetic transit edges:
# connect nearest same-mode nodes
# ---------------------------------------------------------------------
for mode in ["tram", "rail", "bus"]:
    ids = [n for n in G.nodes if G.nodes[n]["mode"] == mode]

    for a in ids:
        ax = G.nodes[a]["lon"]
        ay = G.nodes[a]["lat"]

        nearest = None
        best = 1e18

        for b in ids:
            if a == b:
                continue

            bx = G.nodes[b]["lon"]
            by = G.nodes[b]["lat"]

            d = hav(ax, ay, bx, by)

            if d < best and d <= TRANSIT_LINK_M:
                best = d
                nearest = b

        if nearest and not G.has_edge(a, nearest):
            G.add_edge(
                a,
                nearest,
                weight=best * 0.35,   # faster than walking
                link=mode
            )

# ---------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------
print("\nGraph built")
print("-" * 78)
print("Nodes:", G.number_of_nodes())
print("Edges:", G.number_of_edges())

# mode counts
modes = {}
for _, d in G.nodes(data=True):
    m = d["mode"]
    modes[m] = modes.get(m, 0) + 1

print("Modes:", modes)

# edge counts
edge_types = {}
for _, _, d in G.edges(data=True):
    t = d["link"]
    edge_types[t] = edge_types.get(t, 0) + 1

print("Edge types:", edge_types)

# connectivity
components = list(nx.connected_components(G))
largest = max((len(c) for c in components), default=0)

print("Components:", len(components))
print("Largest component:", largest)

# ---------------------------------------------------------------------
# Nearest city centre
# ---------------------------------------------------------------------
best = None
best_d = 1e18

for n, d in G.nodes(data=True):
    dist = hav(CITY_CENTRE[0], CITY_CENTRE[1], d["lon"], d["lat"])
    if dist < best_d:
        best_d = dist
        best = (n, d["name"], d["mode"])

print("\nNearest Princes Street stop:")
print(best[1], "|", best[2], "|", round(best_d), "m")

# ---------------------------------------------------------------------
# Save summary
# ---------------------------------------------------------------------
summary = {
    "nodes": G.number_of_nodes(),
    "edges": G.number_of_edges(),
    "modes": modes,
    "edge_types": edge_types,
    "components": len(components),
    "largest_component": largest,
    "source": "live" if live_ok else "cache",
}

with open(DEBUG_DIR / "edinburgh_graph_v2_summary.json", "w") as f:
    json.dump(summary, f, indent=2)

print("\nSaved:")
print(" - debug/edinburgh_graph_v2_summary.json")
print(" - debug/edinburgh_graph_cache.json")

print("=" * 78)
print("Done")
print("=" * 78)