"""
RTD_SIM/debug/test_transitland_feeds.py

Tests the validity of TransitLand feed IDs using the TRANSITLAND_API_KEY from .env.

Run:
    python debug/test_transitland_feeds.py
"""

import os
import json
import urllib.request
from pathlib import Path
from dotenv import load_dotenv

# 1. Load environment variables from the RTD_SIM project root
project_root = Path(__file__).resolve().parent.parent
env_path = project_root / ".env"
load_dotenv(env_path)

API_KEY = os.getenv("TRANSITLAND_API_KEY", "").strip()
BASE_URL = "https://transit.land/api/v2/rest/feeds"

# The original feeds to test
FEEDS_TO_TEST = {
    "lothian_buses":            "f-gcpv-lothianbuses",
    "edinburgh_trams":          "f-gcpv-edinburghtramsltd",
    "scotrail":                 "f-gcpv-scotrail",
    "glasgow_subway":           "f-gcpv-spt",
    "first_glasgow":            "f-gcpv-firstglasgow",
    "stagecoach_east_scotland": "f-gcpv-stagecoacheast",
    "traveline_scotland":       "f-gcpv-travelinescotland",
    "national_rail":            "f-u10-atoc",
    "tfl_london":               "f-gcpvj-tfl",
    "bods_england":             "f-u10-bods",
    "transport_for_wales":      "f-gcpv-transportforwales",
    # Added the correct one from the PDF to prove it works:
    "CORRECT_lothian_buses":    "f-bus~dft~gov~uk"
}

def test_feed(label: str, feed_id: str):
    if not API_KEY:
        print("❌ Error: TRANSITLAND_API_KEY not found in .env")
        return

    url = f"{BASE_URL}/{feed_id}"
    req = urllib.request.Request(
        url,
        headers={
            "apikey": API_KEY,
            "User-Agent": "RTD_SIM_Debugger/1.0"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            status = response.getcode()
            if status == 200:
                data = json.loads(response.read().decode('utf-8'))
                feed_name = data.get('feed', {}).get('name', 'Unknown Name')
                print(f"✅ {label:<25} | {feed_id:<25} | FOUND: {feed_name}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"❌ {label:<25} | {feed_id:<25} | NOT FOUND (404)")
        else:
            print(f"⚠️ {label:<25} | {feed_id:<25} | HTTP Error: {e.code}")
    except Exception as e:
        print(f"⚠️ {label:<25} | {feed_id:<25} | Error: {e}")

if __name__ == "__main__":
    print(f"Using .env from: {env_path}")
    if not API_KEY:
        print("ERROR: No API Key found. Exiting.")
        exit(1)
        
    print("-" * 75)
    print(f"{'Feed Label':<25} | {'Feed ID':<25} | {'Status'}")
    print("-" * 75)
    
    for label, feed_id in FEEDS_TO_TEST.items():
        test_feed(label, feed_id)
        
    print("-" * 75)
    print("Test complete.")