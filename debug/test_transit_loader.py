# PATCHED debug/test_transit_loader.py
# Compatible with transit_loader.py v3.0
# Fixes:
# - old signature using mode=
# - handles tuple returns (G, source)
# - removes legacy meta usage
# - fixes nearest stop test

from pathlib import Path
import sys
import traceback

# ------------------------------------------------------------------
# import project
# ------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from simulation.spatial.transit_loader import (
    load_city_graph,
    load_multi_city_graph,
    graph_summary,
    nearest_stop,
)

print("=" * 72)
print("RTD_SIM Transit Loader Test")
print("=" * 72)


def test_city(city):
    print(f"\nLoading city: {city}")

    try:
        result = load_city_graph(city)

        # supports either G or (G, source)
        if isinstance(result, tuple):
            G, source = result
        else:
            G = result
            source = "unknown"

        if G is None:
            print("FAILED")
            print("No graph available")
            return

        s = graph_summary(G)

        print("SUCCESS")
        print("Source :", source)
        print("Nodes  :", s["nodes"])
        print("Edges  :", s["edges"])
        print("Modes  :", s["modes"])

    except Exception as e:
        print("FAILED")
        print(e)


# ------------------------------------------------------------------
# Single city tests
# ------------------------------------------------------------------

for city in ["edinburgh", "glasgow", "manchester"]:
    test_city(city)

# ------------------------------------------------------------------
# Multi city test
# ------------------------------------------------------------------

print("\n" + "-" * 72)
print("Multi-city test: Edinburgh;Glasgow")

try:
    G = load_multi_city_graph("Edinburgh;Glasgow")

    s = graph_summary(G)

    print("SUCCESS")
    print("Nodes:", s["nodes"])
    print("Edges:", s["edges"])

except Exception as e:
    print("FAILED")
    print(e)

# ------------------------------------------------------------------
# Nearest stop test
# ------------------------------------------------------------------

print("\n" + "-" * 72)
print("Nearest stop test (Princes Street Edinburgh approx)")

try:
    result = load_city_graph("edinburgh")

    if isinstance(result, tuple):
        G, _ = result
    else:
        G = result

    stop_id, stop_data, dist = nearest_stop(G, 55.9529, -3.1932)

    print("SUCCESS")
    print("Nearest:", stop_data.get("name"))
    print("ID     :", stop_id)
    print("Dist m :", dist)

except Exception as e:
    print("FAILED")
    print(e)

print("\nDone.")