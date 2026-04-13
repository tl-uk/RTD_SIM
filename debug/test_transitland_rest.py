# RTD_SIM/debug/test_transitland_rest.py
"""
TransitLand REST API Tester (2026 compatible)

Run:
    python debug/test_transitland_rest.py

Tests:
1. Loads RTD_SIM/.env
2. Validates TRANSITLAND_API_KEY
3. Queries new TransitLand /rest endpoints
4. Searches Edinburgh / Scotland operators
5. Tests routes + stops endpoints
6. Determines whether TransitLand can power RTD_SIM directly

Uses:
https://transit.land/api/v2/rest/...

"""

from pathlib import Path
import os
import sys
import json
import urllib.request
import urllib.parse
import traceback

# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------
HERE = Path(__file__).resolve()
PROJECT_ROOT = HERE.parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

print("=" * 74)
print("TransitLand REST Tester")
print("=" * 74)

# ---------------------------------------------------------------------
# Load .env
# ---------------------------------------------------------------------
ENV_PATH = PROJECT_ROOT / ".env"

try:
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)
    print("✅ .env loaded")
except Exception:
    print("⚠️ python-dotenv unavailable")

API_KEY = os.getenv("TRANSITLAND_API_KEY", "").strip()

if API_KEY:
    print("✅ API key found")
else:
    print("⚠️ No API key found")

BASE = "https://transit.land/api/v2/rest"

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def call(endpoint, params=None):
    params = params or {}

    if API_KEY:
        params["apikey"] = API_KEY

    url = f"{BASE}/{endpoint}"

    if params:
        url += "?" + urllib.parse.urlencode(params)

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }

    req = urllib.request.Request(url, headers=headers)

    with urllib.request.urlopen(req, timeout=25) as r:
        txt = r.read().decode("utf-8")
        return json.loads(txt)


def test_endpoint(name, endpoint, params=None, sample_key=None):
    print("\n" + "-" * 74)
    print(name)

    try:
        data = call(endpoint, params)

        print("✅ Success")

        if isinstance(data, dict):
            keys = list(data.keys())
            print("Top keys:", keys[:10])

            if sample_key and sample_key in data:
                rows = data[sample_key]
                print(f"{sample_key}: {len(rows)} records")

                for row in rows[:5]:
                    print(" -", row.get("name", row.get("onestop_id", str(row)[:80])))

        return data

    except Exception as e:
        print("❌ Failed")
        print(e)
        return None


# ---------------------------------------------------------------------
# 1. Operators Search
# ---------------------------------------------------------------------
ops = test_endpoint(
    "Search operators: Edinburgh",
    "operators",
    {"search": "edinburgh", "per_page": 10},
    "operators"
)

# ---------------------------------------------------------------------
# 2. Scotland Search
# ---------------------------------------------------------------------
test_endpoint(
    "Search operators: Scotland",
    "operators",
    {"search": "scotland", "per_page": 10},
    "operators"
)

# ---------------------------------------------------------------------
# 3. Stops near Edinburgh bbox
# ---------------------------------------------------------------------
# Edinburgh bbox approx:
# west, south, east, north
bbox = "-3.45,55.87,-3.05,56.02"

test_endpoint(
    "Stops in Edinburgh bbox",
    "stops",
    {"bbox": bbox, "per_page": 10},
    "stops"
)

# ---------------------------------------------------------------------
# 4. Routes in Edinburgh bbox
# ---------------------------------------------------------------------
test_endpoint(
    "Routes in Edinburgh bbox",
    "routes",
    {"bbox": bbox, "per_page": 10},
    "routes"
)

# ---------------------------------------------------------------------
# 5. If operator found, test operator routes
# ---------------------------------------------------------------------
if ops and ops.get("operators"):
    first = ops["operators"][0]
    op_id = first.get("onestop_id")

    if op_id:
        test_endpoint(
            f"Routes for operator {op_id}",
            "routes",
            {"operator_onestop_id": op_id, "per_page": 10},
            "routes"
        )

# ---------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------
print("\n" + "=" * 74)
print("Interpretation")
print("=" * 74)
print("If operators/routes/stops all work:")
print("  → TransitLand REST can replace GTFS downloads.")
print()
print("If only operators work:")
print("  → limited access tier.")
print()
print("If all fail:")
print("  → key/account restrictions.")
print()
print("If bbox stops/routes work:")
print("  → ideal for RTD_SIM Edinburgh live transit layer.")
print("=" * 74)