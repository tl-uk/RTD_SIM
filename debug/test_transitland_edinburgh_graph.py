# RTD_SIM/debug/test_transitland_edinburgh_graph.py
"""
TransitLand Edinburgh Graph Tester
----------------------------------

Builds a lightweight live transit graph for Edinburgh using TransitLand REST.

Run:
    python debug/test_transitland_edinburgh_graph.py

Requires:
    pip install networkx python-dotenv

What it does:
1. Loads .env and TRANSITLAND_API_KEY
2. Pulls stops in Edinburgh bbox
3. Pulls routes in Edinburgh bbox
4. Builds NetworkX graph
5. Infers mode (tram / bus / rail)
6. Prints graph stats
7. Finds nearest stop to city centre
8. Saves graph JSON summary

Purpose:
Prototype replacement for GTFS ZIP ingestion in RTD_SIM.
"""

from pathlib import Path
import os
import sys
import json
import math
import urllib.request
import urllib.parse

import networkx as nx

# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------
HERE = Path(__file__).resolve()
PROJECT_ROOT = HERE.parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------
# Load .env
# ---------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

API_KEY = os.getenv("TRANSITLAND_API_KEY", "").strip()

print("=" * 76)
print("TransitLand Edinburgh Graph Tester")
print("=" * 76)

if API_KEY:
    print("✅ API key found")
else:
    print("⚠️ No API key found")

BASE = "https://transit.land/api/v2/rest"

# Edinburgh approx bbox
BBOX = "-3.45,55.87,-3.05,56.02"

# Princes Street centre
CITY_CENTRE = (-3.1938, 55.9533)

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def api(endpoint, params=None):
    params = params or {}
    params["per_page"] = params.get("per_page", 200)

    if API_KEY:
        params["apikey"] = API_KEY

    url = f"{BASE}/{endpoint}?{urllib.parse.urlencode(params)}"

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json"
        }
    )

    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def haversine(lon1, lat1, lon2, lat2):
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
    if "rail" in s or "train" in s:
        return "rail"
    return "bus"


# ---------------------------------------------------------------------
# Fetch data
# ---------------------------------------------------------------------
print("\nFetching stops...")
stops_data = api("stops", {"bbox": BBOX})

print("Fetching routes...")
routes_data = api("routes", {"bbox": BBOX})

stops = stops_data.get("stops", [])
routes = routes_data.get("routes", [])

print(f"Stops fetched : {len(stops)}")
print(f"Routes fetched: {len(routes)}")

# ---------------------------------------------------------------------
# Build graph
# ---------------------------------------------------------------------
G = nx.Graph()

# Add stop nodes
for s in stops:
    sid = s.get("onestop_id") or s.get("id")
    name = s.get("name", sid)

    geom = s.get("geometry", {})
    coords = geom.get("coordinates", [None, None])

    if len(coords) < 2:
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

# Connect nearby stops (walk links)
node_ids = list(G.nodes())

for i in range(len(node_ids)):
    a = node_ids[i]
    ax = G.nodes[a]["lon"]
    ay = G.nodes[a]["lat"]

    for j in range(i + 1, len(node_ids)):
        b = node_ids[j]
        bx = G.nodes[b]["lon"]
        by = G.nodes[b]["lat"]

        d = haversine(ax, ay, bx, by)

        # connect if under 500m
        if d <= 500:
            G.add_edge(a, b, weight=d, link_type="walk")

# ---------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------
print("\nGraph built")
print("-" * 76)
print("Nodes:", G.number_of_nodes())
print("Edges:", G.number_of_edges())

modes = {}
for _, data in G.nodes(data=True):
    m = data["mode"]
    modes[m] = modes.get(m, 0) + 1

print("Mode counts:", modes)

# Components
components = list(nx.connected_components(G))
print("Connected components:", len(components))
print("Largest component:", max(len(c) for c in components) if components else 0)

# ---------------------------------------------------------------------
# Nearest stop to city centre
# ---------------------------------------------------------------------
best = None
best_d = 1e18

for n, d in G.nodes(data=True):
    dist = haversine(CITY_CENTRE[0], CITY_CENTRE[1], d["lon"], d["lat"])
    if dist < best_d:
        best = (n, d["name"], d["mode"])
        best_d = dist

print("\nNearest stop to Princes Street:")
print(f"{best[1]} ({best[2]}) [{best[0]}]")
print(f"{best_d:.0f} m away")

# ---------------------------------------------------------------------
# Save summary
# ---------------------------------------------------------------------
out = PROJECT_ROOT / "debug" / "edinburgh_graph_summary.json"

summary = {
    "nodes": G.number_of_nodes(),
    "edges": G.number_of_edges(),
    "mode_counts": modes,
    "components": len(components),
    "largest_component": max(len(c) for c in components) if components else 0,
}

with open(out, "w") as f:
    json.dump(summary, f, indent=2)

print("\nSaved:", out)

print("=" * 76)
print("Done")
print("=" * 76)