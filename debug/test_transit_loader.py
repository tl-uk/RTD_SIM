# debug/test_transit_loader.py

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from simulation.spatial.transit_loader import (
    load_city_graph,
    load_multi_city_graph,
    nearest_stop
)

print("=" * 72)
print("RTD_SIM Transit Loader v2 Test")
print("=" * 72)

# ==========================================================
# SINGLE CITY TESTS
# ==========================================================

for city in ["edinburgh", "glasgow", "manchester"]:

    print(f"\nLoading city: {city}")

    try:
        graph = load_city_graph(city, mode="auto")

        print("SUCCESS")
        print("Source :", graph["meta"]["source"])
        print("Nodes  :", graph["meta"]["nodes"])
        print("Edges  :", graph["meta"]["edges"])
        print("Modes  :", graph["meta"].get("edge_modes", {}))

    except Exception as e:
        print("FAILED")
        print(str(e))

# ==========================================================
# MULTI CITY TEST
# ==========================================================

print("\n" + "-" * 72)
print("Multi-city test: Edinburgh;Glasgow")

try:
    graph = load_multi_city_graph("edinburgh;glasgow")

    print("SUCCESS")
    print("Nodes:", graph["meta"]["nodes"])
    print("Edges:", graph["meta"]["edges"])

except Exception as e:
    print("FAILED")
    print(str(e))

# ==========================================================
# NEAREST STOP TEST
# ==========================================================

print("\n" + "-" * 72)
print("Nearest stop test (Princes Street Edinburgh approx)")

try:
    graph = load_city_graph("edinburgh")

    stop, dist = nearest_stop(graph, 55.9520, -3.1960)

    print("Nearest:", stop["name"])
    print("ID     :", stop["id"])
    print("Dist m :", dist)

except Exception as e:
    print("FAILED")
    print(str(e))

print("\nDone.")