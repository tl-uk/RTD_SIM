# debug/test_naptan_loader.py

from pathlib import Path
import sys
import time
import logging

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s"
)

from simulation.spatial.naptan_loader import download_naptan

print("=" * 72)
print("RTD_SIM NaPTAN Loader Test")
print("=" * 72)

# Edinburgh bbox
bbox = (
    55.99,   # north
    55.90,   # south
    -3.10,   # east
    -3.40    # west
)

# -------------------------------------------------------------------
# First load
# -------------------------------------------------------------------

print("\nFIRST LOAD")
t0 = time.time()

stops = download_naptan(bbox=bbox)

dt = time.time() - t0

print(f"\nLoaded {len(stops)} stops")
print(f"Time   {dt:.2f}s")

# -------------------------------------------------------------------
# Second load
# -------------------------------------------------------------------

print("\nSECOND LOAD (should hit cache)")
t0 = time.time()

stops2 = download_naptan(bbox=bbox)

dt = time.time() - t0

print(f"\nLoaded {len(stops2)} stops")
print(f"Time   {dt:.2f}s")

# -------------------------------------------------------------------
# Force refresh
# -------------------------------------------------------------------

print("\nFORCE REFRESH (should hit DfT/API or CSV)")
t0 = time.time()

stops3 = download_naptan(
    bbox=bbox,
    force_refresh=True
)

dt = time.time() - t0

print(f"\nLoaded {len(stops3)} stops")
print(f"Time   {dt:.2f}s")

print("\nDone.")