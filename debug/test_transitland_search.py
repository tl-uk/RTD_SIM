# RTD_SIM/debug/test_transitland_search.py
"""
TransitLand feed search + downloader tester.

Run from VSCode terminal:

    python debug/test_transitland_search.py

What it does:
1. Loads RTD_SIM/.env
2. Uses TRANSITLAND_API_KEY if present
3. Searches TransitLand for likely UK feeds
4. Prints candidate feeds
5. Tests download access for selected feeds
6. Helps identify valid 2026 feed IDs

Useful feeds to test:
- f-bus~dft~gov~uk
- f-uk~rail
"""

from pathlib import Path
import os
import sys
import json
import urllib.request
import urllib.parse
import traceback

# -------------------------------------------------------------------
# Paths
# -------------------------------------------------------------------
HERE = Path(__file__).resolve()
PROJECT_ROOT = HERE.parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

print("=" * 72)
print("TransitLand Search Tester")
print("=" * 72)

# -------------------------------------------------------------------
# Load .env
# -------------------------------------------------------------------
ENV_PATH = PROJECT_ROOT / ".env"

try:
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)
    print("✅ .env loaded")
except Exception:
    print("⚠️ dotenv unavailable")

API_KEY = os.getenv("TRANSITLAND_API_KEY", "").strip()

if API_KEY:
    print("✅ API key found")
else:
    print("⚠️ No API key found (public mode)")

# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------
BASE = "https://transit.land/api/v2"

SEARCH_TERMS = [
    "uk",
    "rail",
    "bus",
    "scotland",
    "edinburgh",
]

KNOWN_FEEDS = [
    "f-bus~dft~gov~uk",
    "f-uk~rail",
]

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def fetch_json(url):
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    req = urllib.request.Request(url, headers=headers)

    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def search_feeds(term):
    params = {"search": term, "per_page": 10}
    if API_KEY:
        params["apikey"] = API_KEY

    url = f"{BASE}/feeds?{urllib.parse.urlencode(params)}"

    try:
        data = fetch_json(url)
        return data.get("feeds", [])
    except Exception as e:
        print(f"❌ Search failed for '{term}': {e}")
        return []


def test_download(feed_id):
    url = f"{BASE}/feeds/{feed_id}/download"

    if API_KEY:
        url += f"?apikey={API_KEY}"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "*/*"
    }

    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            code = r.status
            ctype = r.headers.get("Content-Type", "")
            clen = r.headers.get("Content-Length", "?")
            return True, code, ctype, clen
    except Exception as e:
        return False, None, str(e), None


# -------------------------------------------------------------------
# Search
# -------------------------------------------------------------------
print("\nSEARCH RESULTS")
print("-" * 72)

seen = set()

for term in SEARCH_TERMS:
    print(f"\n🔎 Searching: {term}")

    feeds = search_feeds(term)

    if not feeds:
        print("   No results")
        continue

    for feed in feeds[:5]:
        fid = feed.get("id", "")
        name = feed.get("name", "")
        if fid in seen:
            continue
        seen.add(fid)

        print(f"   {fid:<30} {name}")

# -------------------------------------------------------------------
# Known feed tests
# -------------------------------------------------------------------
print("\nDOWNLOAD TESTS")
print("-" * 72)

for fid in KNOWN_FEEDS:
    print(f"\nTesting {fid}")

    ok, code, meta, size = test_download(fid)

    if ok:
        print("✅ Accessible")
        print(f"HTTP: {code}")
        print(f"Type: {meta}")
        print(f"Size: {size}")
    else:
        print("❌ Failed")
        print(meta)

print("\n" + "=" * 72)
print("Done")
print("=" * 72)