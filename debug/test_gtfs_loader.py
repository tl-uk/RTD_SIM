# RTD_SIM/debug/test_gtfs_loader.py
"""
Quick diagnostic for TransitLand GTFS key + downloader.

Run from VSCode terminal (project root):
    python debug/test_gtfs_loader.py

What it does:
1. Loads RTD_SIM/.env
2. Checks if TRANSITLAND_API_KEY exists
3. Imports download_gtfs_feed from simulation.gtfs.gtfs_validator
4. Attempts to download Edinburgh Trams feed
5. Reports success/failure + file size

If imports fail, it also tells you what to fix.
"""

from pathlib import Path
import os
import sys
import traceback

# -------------------------------------------------------------------
# Ensure project root on path
# -------------------------------------------------------------------
HERE = Path(__file__).resolve()
PROJECT_ROOT = HERE.parents[1]   # RTD_SIM/
sys.path.insert(0, str(PROJECT_ROOT))

# -------------------------------------------------------------------
# Load .env manually
# -------------------------------------------------------------------
ENV_PATH = PROJECT_ROOT / ".env"

print("=" * 70)
print("RTD_SIM GTFS TransitLand Loader Test")
print("=" * 70)

print(f"Project root : {PROJECT_ROOT}")
print(f".env path    : {ENV_PATH}")

if not ENV_PATH.exists():
    print("❌ .env file not found")
    sys.exit(1)

# Try dotenv first
try:
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)
    print("✅ Loaded .env via python-dotenv")
except Exception:
    print("⚠️ python-dotenv unavailable, using manual parser")

    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip().strip('"').strip("'")

# -------------------------------------------------------------------
# Check API key
# -------------------------------------------------------------------
api_key = os.getenv("TRANSITLAND_API_KEY", "").strip()

if api_key:
    masked = api_key[:4] + "*" * max(0, len(api_key) - 8) + api_key[-4:]
    print(f"✅ TRANSITLAND_API_KEY found: {masked}")
else:
    print("⚠️ TRANSITLAND_API_KEY not found")
    print("   Continuing anyway (public feeds may still work)")

print()

# -------------------------------------------------------------------
# Import downloader
# -------------------------------------------------------------------
try:
    from simulation.gtfs.gtfs_validator import download_gtfs_feed
    print("✅ Imported download_gtfs_feed")
except Exception:
    print("❌ Could not import download_gtfs_feed")
    traceback.print_exc()
    sys.exit(1)

# -------------------------------------------------------------------
# Test feed IDs
# -------------------------------------------------------------------
TEST_FEEDS = [
    ("UK Bus Open Data", "f-bus~dft~gov~uk"),
    ("UK Rail", "f-uk~rail"),
]

downloaded = False

for label, feed_id in TEST_FEEDS:
    print("-" * 70)
    print(f"Testing: {label}")
    print(f"Feed ID: {feed_id}")

    try:
        result = download_gtfs_feed(
            operator_id_or_url=feed_id,
            output_dir=str(PROJECT_ROOT / "debug"),
            api_key=api_key,
        )

        if result:
            p = Path(result)
            if p.exists():
                size_kb = p.stat().st_size // 1024
                print(f"✅ Download succeeded")
                print(f"File: {p}")
                print(f"Size: {size_kb:,} KB")
                downloaded = True
                break
            else:
                print("⚠️ Function returned path but file missing")
        else:
            print("❌ Download returned None")

    except Exception:
        print("❌ Exception during download")
        traceback.print_exc()

print("-" * 70)

if downloaded:
    print("RESULT: SUCCESS")
else:
    print("RESULT: FAILED")
    print()
    print("Likely causes:")
    print("1. Wrong API key name in .env")
    print("   Must be: TRANSITLAND_API_KEY=your_key")
    print("2. .env not in RTD_SIM root")
    print("3. Feed IDs outdated")
    print("4. Firewall / proxy / SSL issue")
    print("5. TransitLand endpoint changed")

print("=" * 70)