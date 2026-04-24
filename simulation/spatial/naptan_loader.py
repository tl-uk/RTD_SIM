"""
simulation/spatial/naptan_loader.py

NaPTAN (National Public Transport Access Nodes) loader.

NaPTAN is the UK government's authoritative dataset of every rail station,
bus stop, tram stop, and ferry terminal (~430,000 stops total; ~2,500 rail,
metro, tram, and ferry stops relevant to RTD_SIM intermodal routing).

DATA DIRECTORY
──────────────
NaPTAN data lives in the project tree, not the user home directory:

    RTD_SIM/
    └── data/
        └── naptan/
            ├── NAPTAN_National_Stops.csv   ← 102 MB DfT bulk download
            ├── NPTG_Localities.csv         ←   5 MB locality name lookup
            └── cache/
                ├── national.json           ← full UK cache (auto-built)
                └── <atco_codes>.json       ← per-region cache files

The cache directory is created automatically.  The CSV files must be placed
manually (or are downloaded automatically on first run).

LOADING PRIORITY
────────────────
  1. Per-region disk cache  (data/naptan/cache/<codes>.json, 30-day TTL)
  2. National disk cache    (data/naptan/cache/national.json, 30-day TTL)
  3. Local CSV files        (data/naptan/NAPTAN_National_Stops.csv)
     Also looks in  ~/Dev/Python/GTFS/ for pre-downloaded CSVs.
  4. DfT HTTPS API — targeted by ATCO area codes for the simulation bbox
     Endpoint: GET /v1/access-nodes?atcoAreaCodes=629,630&dataFormat=csv
     This downloads only the relevant region (~1-5 MB vs ~102 MB national).
  5. DfT HTTPS API — national fallback (no ATCO codes — downloads all ~102 MB)
  6. rail_spine fallback    (hardcoded UK stations — always works offline)

ATCO AREA CODE AUTO-SELECTION
──────────────────────────────
When the simulation bbox is known (derived from the OSMnx drive graph),
the loader selects the ATCO area codes whose geographic centroids fall
inside the bbox.  Edinburgh → codes 629 (Lothian), 630 (Fife), 710 (Central).
Highlands → codes 659 (Highland), 669 (Western Isles), 679 (Orkney), etc.

This means a Highland & Islands simulation downloads only the ~3,000 stops
for that region rather than all 430,000 national stops.

SSL ISSUES ON macOS
─────────────────────
macOS Python often lacks the intermediate cert for naptan.api.dft.gov.uk.
Fix options (in order of preference):
  A. Place the CSV in data/naptan/ (then no API call is ever made).
  B. Run:  /Applications/Python 3.x/Install Certificates.command
  C. Set env var:  NAPTAN_SKIP_SSL_VERIFY=1  (disables cert check for this loader)

DfT API REFERENCE
──────────────────
  GET /v1/access-nodes?atcoAreaCodes=629,659&dataFormat=csv
  GET /v1/access-nodes?dataFormat=csv              ← national (102 MB)
  GET /v1/nptg/localities                          ← locality names (5 MB CSV)

UK ATCO AREA CODES
───────────────────
  629 Lothian (Edinburgh)      659 Highland (Inverness/Fort William)
  630 Fife                     669 Western Isles (Stornoway)
  639 Tayside (Dundee/Perth)   679 Orkney
  649 Grampian (Aberdeen)      689 Shetland
  610 Strathclyde (Glasgow)    699 Dumfries & Galloway
  710 Central (Stirling)       700 Borders
  720 Wales                    010 Greater London
  (Full list in ATCO_AREAS below)
"""

from __future__ import annotations

import csv
import io
import json
import logging
import math
import os
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

import os
from pathlib import Path
from typing import List

# ── Project-local data directory ───────────────────────────────────────────────
# naptan_loader.py lives at simulation/spatial/naptan_loader.py.
# Project root is therefore three parents up.
_HERE         = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parent.parent.parent   # RTD_SIM/

_DATA_DIR     = _PROJECT_ROOT / "data" / "naptan"
_CACHE_DIR    = _DATA_DIR / "cache"
_NATIONAL_CSV = _DATA_DIR / "NAPTAN_National_Stops.csv"
_NPTG_CSV     = _DATA_DIR / "NPTG_Localities.csv"

# 1. Start with the standard project paths
_CSV_SEARCH_PATHS: List[Path] = [_NATIONAL_CSV]
_NPTG_SEARCH_PATHS: List[Path] = [_NPTG_CSV]

# 2. Allow machine-agnostic overrides via Environment Variables
# A developer can set RTD_SIM_GTFS_DIR on their specific machine if they keep data elsewhere.
_CUSTOM_DATA_DIR = os.getenv("RTD_SIM_GTFS_DIR")

if _CUSTOM_DATA_DIR:
    custom_path = Path(_CUSTOM_DATA_DIR)
    
    # Prepend or append depending on your priority. 
    # Appending makes it a fallback; prepending makes it an override.
    _CSV_SEARCH_PATHS.append(custom_path / "NAPTAN_National_Stops.csv")
    _NPTG_SEARCH_PATHS.append(custom_path / "NPTG_Localities.csv")

CACHE_MAX_AGE_DAYS = 30

# ── DfT API ────────────────────────────────────────────────────────────────────
_NAPTAN_API_BASE  = "https://naptan.api.dft.gov.uk/v1"
_ACCESS_NODES_URL = f"{_NAPTAN_API_BASE}/access-nodes"
_NPTG_LOCAL_URL   = f"{_NAPTAN_API_BASE}/nptg/localities"

# ── StopType filter ────────────────────────────────────────────────────────────
_RAIL_STOP_TYPES = frozenset({
    'RLY',   # Railway station entrance / stop
    'MET',   # Metro / underground station
    'FER',   # Ferry terminal
    'TMU',   # Tram / metro / underground stop
    'LCB',   # Light rail / cable car
    'BCE',   # Bus / coach station entrance (intermodal hubs)
})

# ── Mode-specific stop type sets ───────────────────────────────────────────────
# These are narrower subsets used when snapping to a SPECIFIC transport mode.
# Using _RAIL_STOP_TYPES (which includes MET/FER/TMU) for local_train snapping
# caused agents to be snapped to tram stops (MET) or ferry landings (FER) which
# have no rail connection → trunk leg routing fails → agent forced to EV.

# National Rail stations only — for local_train / intercity_train snapping
RAIL_ONLY_STOP_TYPES = frozenset({'RLY'})

# Tram / light-rail stops — for tram snapping.
#
# CRITICAL: Edinburgh Trams stops are classified as 'MET' in NaPTAN, NOT 'TMU'.
# 'TMU' is used by Greater Manchester Metrolink and some other systems.
# Using only {'TMU'} caused snap_to_transit_stop to return None for every
# Edinburgh tram agent, silently failing and falling back to bus.
#
# Both MET and TMU are included here to cover:
#   MET → Edinburgh Trams, some Scottish metro interchanges
#   TMU → Metrolink (Manchester), Midland Metro, Nottingham Express Transit
TRAM_STOP_TYPES = frozenset({'TMU', 'MET'})

# Ferry terminals only — for ferry_diesel / ferry_electric snapping
FERRY_STOP_TYPES = frozenset({'FER', 'FBT'})

# Bus stops and interchanges — for bus snapping (permissive)
BUS_STOP_TYPES = frozenset({'BCT', 'BCE', 'BCS', 'BST'})

# ── Which RTD_SIM modes each stop type serves ─────────────────────────────────
# Used to build NaptanStop.modes_served so the router can validate that a stop
# actually serves the mode it is being snapped for.
STOP_TYPE_TO_MODES: dict = {
    'RLY': ['local_train', 'intercity_train', 'freight_rail'],
    'RSE': ['local_train', 'intercity_train'],
    'MET': ['tram'],          # Edinburgh Trams MET stops are tram, NOT rail
    'TMU': ['tram'],
    'LCB': ['tram'],
    'FER': ['ferry_diesel', 'ferry_electric'],
    'FBT': ['ferry_diesel', 'ferry_electric'],
    'BCE': ['bus'],
    'BCT': ['bus'],
    'BCS': ['bus'],
    'BST': ['bus'],
    'AIR': ['flight_domestic', 'flight_electric'],
}

# ── ATCO area code registry ────────────────────────────────────────────────────
# Each entry: code -> {name, centroid_lon, centroid_lat}
# Centroids are approximate geographic centres of each administrative area.
# Used to auto-select relevant codes from the simulation bbox.
ATCO_AREAS: Dict[str, Dict] = {
    # Scotland
    '610': {'name': 'Strathclyde (Glasgow)',      'lon': -4.25,  'lat': 55.86},
    '629': {'name': 'Lothian (Edinburgh)',         'lon': -3.19,  'lat': 55.95},
    '630': {'name': 'Fife',                        'lon': -3.15,  'lat': 56.22},
    '639': {'name': 'Tayside (Dundee/Perth)',      'lon': -3.20,  'lat': 56.45},
    '649': {'name': 'Grampian (Aberdeen)',         'lon': -2.09,  'lat': 57.14},
    '659': {'name': 'Highland (Inverness/FW)',     'lon': -4.75,  'lat': 57.50},
    '669': {'name': 'Western Isles (Stornoway)',   'lon': -6.38,  'lat': 58.21},
    '679': {'name': 'Orkney',                      'lon': -3.10,  'lat': 58.96},
    '689': {'name': 'Shetland',                    'lon': -1.30,  'lat': 60.30},
    '699': {'name': 'Dumfries & Galloway',         'lon': -3.95,  'lat': 55.07},
    '700': {'name': 'Scottish Borders',            'lon': -2.80,  'lat': 55.55},
    '710': {'name': 'Central (Stirling/Falkirk)',  'lon': -3.94,  'lat': 56.12},
    # Wales
    '720': {'name': 'Wales',                       'lon': -3.70,  'lat': 52.10},
    # North England
    '070': {'name': 'Tyne & Wear (Newcastle)',     'lon': -1.61,  'lat': 54.97},
    '110': {'name': 'Northumberland',              'lon': -1.95,  'lat': 55.20},
    '120': {'name': 'Durham',                      'lon': -1.58,  'lat': 54.78},
    '130': {'name': 'Tees Valley',                 'lon': -1.22,  'lat': 54.57},
    '030': {'name': 'Greater Manchester',          'lon': -2.23,  'lat': 53.48},
    '040': {'name': 'West Yorkshire',              'lon': -1.55,  'lat': 53.80},
    '050': {'name': 'South Yorkshire',             'lon': -1.47,  'lat': 53.38},
    '060': {'name': 'Merseyside',                  'lon': -2.98,  'lat': 53.41},
    '140': {'name': 'Humber (Hull)',               'lon': -0.33,  'lat': 53.74},
    # Midlands
    '020': {'name': 'West Midlands',               'lon': -1.90,  'lat': 52.48},
    '150': {'name': 'East Midlands',               'lon': -1.12,  'lat': 52.94},
    '160': {'name': 'Nottinghamshire',             'lon': -1.16,  'lat': 53.00},
    '170': {'name': 'Derbyshire',                  'lon': -1.47,  'lat': 53.10},
    '230': {'name': 'Leicestershire',              'lon': -1.13,  'lat': 52.63},
    # East England
    '240': {'name': 'Norfolk',                     'lon':  1.30,  'lat': 52.66},
    '250': {'name': 'Suffolk',                     'lon':  1.00,  'lat': 52.24},
    '260': {'name': 'Cambridgeshire',              'lon':  0.12,  'lat': 52.20},
    '290': {'name': 'Essex',                       'lon':  0.47,  'lat': 51.74},
    # South / London
    '010': {'name': 'Greater London',              'lon': -0.12,  'lat': 51.51},
    '300': {'name': 'Kent',                        'lon':  0.52,  'lat': 51.28},
    '310': {'name': 'East Sussex',                 'lon':  0.27,  'lat': 50.91},
    '320': {'name': 'West Sussex',                 'lon': -0.46,  'lat': 50.93},
    '330': {'name': 'Surrey',                      'lon': -0.40,  'lat': 51.26},
    '340': {'name': 'Hampshire',                   'lon': -1.30,  'lat': 51.07},
    '350': {'name': 'Berkshire',                   'lon': -1.10,  'lat': 51.46},
    '360': {'name': 'Oxfordshire',                 'lon': -1.26,  'lat': 51.75},
    '430': {'name': 'Gloucestershire',             'lon': -2.08,  'lat': 51.86},
    '440': {'name': 'Bristol',                     'lon': -2.60,  'lat': 51.45},
    '400': {'name': 'Devon',                       'lon': -3.79,  'lat': 50.72},
    '410': {'name': 'Cornwall',                    'lon': -4.70,  'lat': 50.32},
}


# ── NaPTAN stop record ─────────────────────────────────────────────────────────

class NaptanStop:
    """
    Lightweight NaPTAN stop record with semantic boarding/alighting fields.

    Semantic fields (derived from stop_type at construction):
        modes_served:         List of RTD_SIM mode strings this stop serves.
                              e.g. RLY → ['local_train', 'intercity_train']
                              MET → ['tram']  (NOT rail — key distinction)
        can_board:            True if passengers can board here (default True).
        can_alight:           True if passengers can alight here (default True).
        wheelchair_accessible: True if the stop has step-free access.
                               Populated from GTFS wheelchair_boarding when
                               available; defaults to False when unknown.

    These fields implement a lightweight stop ontology so the router can
    validate that a stop genuinely serves a given mode before snapping to it,
    preventing MET (tram) stops from being returned for rail-mode queries.
    """
    __slots__ = ('atco_code', 'common_name', 'stop_type',
                 'lon', 'lat', 'crs_code', 'status',
                 'modes_served', 'can_board', 'can_alight',
                 'wheelchair_accessible')

    def __init__(
        self,
        atco_code:   str,
        common_name: str,
        stop_type:   str,
        lon:         float,
        lat:         float,
        crs_code:    str  = '',
        status:      str  = 'act',
        modes_served: Optional[List[str]] = None,
        can_board:    bool = True,
        can_alight:   bool = True,
        wheelchair_accessible: bool = False,
    ):
        self.atco_code   = atco_code
        self.common_name = common_name
        self.stop_type   = stop_type
        self.lon         = lon
        self.lat         = lat
        self.crs_code    = crs_code
        self.status      = status
        self.can_board   = can_board
        self.can_alight  = can_alight
        self.wheelchair_accessible = wheelchair_accessible
        # Derive modes_served from stop_type if not explicitly provided
        self.modes_served: List[str] = (
            modes_served
            if modes_served is not None
            else list(STOP_TYPE_TO_MODES.get(stop_type, []))
        )

    def serves_mode(self, mode: str) -> bool:
        """Return True if this stop serves the given RTD_SIM mode string."""
        return mode in self.modes_served

    def to_dict(self) -> dict:
        return {
            'atco_code':            self.atco_code,
            'common_name':          self.common_name,
            'stop_type':            self.stop_type,
            'lon':                  self.lon,
            'lat':                  self.lat,
            'crs_code':             self.crs_code,
            'status':               self.status,
            'modes_served':         self.modes_served,
            'can_board':            self.can_board,
            'can_alight':           self.can_alight,
            'wheelchair_accessible': self.wheelchair_accessible,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'NaptanStop':
        return cls(
            atco_code   = d['atco_code'],
            common_name = d['common_name'],
            stop_type   = d['stop_type'],
            lon         = float(d['lon']),
            lat         = float(d['lat']),
            crs_code    = d.get('crs_code', ''),
            status      = d.get('status', 'act'),
            modes_served = d.get('modes_served'),
            can_board    = d.get('can_board', True),
            can_alight   = d.get('can_alight', True),
            wheelchair_accessible = d.get('wheelchair_accessible', False),
        )

    def __repr__(self) -> str:
        return (
            f"NaptanStop({self.common_name!r}, type={self.stop_type}, "
            f"modes={self.modes_served}, lon={self.lon:.4f}, lat={self.lat:.4f})"
        )


# ── Public API ─────────────────────────────────────────────────────────────────

def download_naptan(
    bbox:          Optional[Tuple[float, float, float, float]] = None,
    stop_types:    Optional[frozenset] = None,
    force_refresh: bool = False,
) -> List[NaptanStop]:
    """
    Load NaPTAN rail/metro/ferry/tram stops for the simulation region.

    Args:
        bbox:          (north, south, east, west) spatial filter.  Used to
                       auto-select ATCO area codes for targeted API download.
        stop_types:    NaPTAN StopType codes (default _RAIL_STOP_TYPES).
        force_refresh: Ignore all caches and reload from source.

    Returns:
        List of NaptanStop records.
    """
    stop_types  = stop_types or _RAIL_STOP_TYPES
    _ensure_dirs()

    # Auto-select ATCO codes from bbox
    atco_codes = _atco_codes_for_bbox(bbox) if bbox else set()
    cache_key  = _cache_key(atco_codes)
    cache_file = _CACHE_DIR / f"{cache_key}.json"

    # ── 1 & 2: Disk cache ─────────────────────────────────────────────────────
    if not force_refresh:
        cached = _try_load_cache(cache_file, bbox, stop_types)
        if cached is not None:
            return cached
        # Also try national cache (covers any region)
        national_cache = _CACHE_DIR / "national.json"
        if national_cache != cache_file:
            cached = _try_load_cache(national_cache, bbox, stop_types)
            if cached is not None:
                return cached

    # ── 3: Local CSV ───────────────────────────────────────────────────────────
    csv_path  = _find_file(_CSV_SEARCH_PATHS)
    nptg_path = _find_file(_NPTG_SEARCH_PATHS)

    if csv_path:
        try:
            stops = _load_from_csv(csv_path, stop_types, nptg_path)
            if stops:
                _save_cache(stops, _CACHE_DIR / "national.json")
                result = _filter_bbox(stops, bbox) if bbox else stops
                logger.info(
                    "NaPTAN: %d/%d stops from local CSV (%s)",
                    len(result), len(stops), csv_path.name,
                )
                return result
        except Exception as exc:
            logger.warning("NaPTAN CSV load failed (%s) — trying API", exc)
    else:
        logger.info(
            "NaPTAN: no local CSV found. "
            "Place NAPTAN_National_Stops.csv in %s to avoid API downloads.",
            _DATA_DIR,
        )

    # ── 4: DfT API — targeted by ATCO codes ───────────────────────────────────
    if atco_codes:
        try:
            stops = _fetch_api_by_codes(atco_codes, stop_types, nptg_path)
            if stops:
                _save_cache(stops, cache_file)
                result = _filter_bbox(stops, bbox) if bbox else stops
                logger.info(
                    "NaPTAN: %d stops from API (ATCO codes: %s)",
                    len(result), ','.join(sorted(atco_codes)),
                )
                return result
        except Exception as exc:
            logger.warning(
                "NaPTAN regional API failed (%s) — trying national download", exc
            )

    # ── 5: DfT API — national ─────────────────────────────────────────────────
    try:
        stops = _fetch_api_national(stop_types, nptg_path)
        if stops:
            _save_cache(stops, _CACHE_DIR / "national.json")
            result = _filter_bbox(stops, bbox) if bbox else stops
            logger.info(
                "NaPTAN: %d/%d stops from national API download",
                len(result), len(stops),
            )
            return result
    except Exception as exc:
        logger.error(
            "NaPTAN national API failed: %s — using rail_spine fallback.\n"
            "  To fix: place NAPTAN_National_Stops.csv in %s",
            exc, _DATA_DIR,
        )

    # ── 6: rail_spine fallback ─────────────────────────────────────────────────
    return _fallback_from_spine()


# ── ATCO code selection ────────────────────────────────────────────────────────

def _atco_codes_for_bbox(
    bbox:        Tuple[float, float, float, float],
    padding_deg: float = 0.2,
) -> Set[str]:
    """
    Return ATCO area codes whose centroids fall within the bbox.

    Adds padding_deg to each edge so that areas just outside the drive
    graph boundary (e.g. Fife when simulating Edinburgh) are included.
    """
    north, south, east, west = bbox
    north += padding_deg
    south -= padding_deg
    east  += padding_deg
    west  -= padding_deg

    codes: Set[str] = set()
    for code, info in ATCO_AREAS.items():
        if (south <= info['lat'] <= north
                and west <= info['lon'] <= east):
            codes.add(code)

    if codes:
        names = ', '.join(ATCO_AREAS[c]['name'] for c in sorted(codes))
        logger.info("NaPTAN: ATCO codes %s (%s)", sorted(codes), names)
    else:
        logger.debug(
            "NaPTAN: no ATCO centroids in bbox — will use national dataset"
        )
    return codes


def get_atco_codes_for_place(place_name: str) -> List[str]:
    """
    Return suggested ATCO codes for a named place.

    Supports named groupings: 'Scotland', 'Highlands', 'Highlands and Islands',
    'Edinburgh', 'Glasgow', 'Aberdeen', 'Dundee', 'Inverness', 'Fife',
    'London', 'Wales'.

    Also does a fuzzy substring match on ATCO_AREAS names for other places.
    """
    name_lower = place_name.lower()
    _GROUPS: Dict[str, List[str]] = {
        'highlands and islands': ['659', '669', '679', '689', '649'],
        'highlands':             ['659', '669', '679', '689'],
        'scotland':              ['610', '629', '630', '639', '649',
                                  '659', '669', '679', '689', '699', '700', '710'],
        'edinburgh':             ['629'],
        'glasgow':               ['610'],
        'aberdeen':              ['649'],
        'dundee':                ['639'],
        'inverness':             ['659'],
        'fife':                  ['630'],
        'london':                ['010'],
        'wales':                 ['720'],
        'yorkshire':             ['040', '050'],
        'manchester':            ['030'],
        'birmingham':            ['020'],
        'bristol':               ['440'],
    }
    for group_key, group_codes in _GROUPS.items():
        if group_key in name_lower:
            return group_codes

    # Fallback: substring match on individual area names
    return [
        code for code, info in ATCO_AREAS.items()
        if name_lower in info['name'].lower()
    ]


# ── API fetchers ───────────────────────────────────────────────────────────────

def _fetch_api_by_codes(
    codes:      Set[str],
    stop_types: frozenset,
    nptg_path:  Optional[Path] = None,
) -> List[NaptanStop]:
    """Download NaPTAN for specific ATCO area codes via the DfT CSV endpoint."""
    codes_param = ','.join(sorted(codes))
    url = f"{_ACCESS_NODES_URL}?atcoAreaCodes={codes_param}&dataFormat=csv"
    logger.info(
        "NaPTAN: fetching from DfT API (ATCO codes: %s)…", codes_param
    )
    data = _api_get(url)
    return _parse_csv_bytes(data, stop_types, nptg_path)


def _fetch_api_national(
    stop_types: frozenset,
    nptg_path:  Optional[Path] = None,
) -> List[NaptanStop]:
    """Download the full national NaPTAN dataset (~102 MB CSV)."""
    url = f"{_ACCESS_NODES_URL}?dataFormat=csv"
    logger.info(
        "NaPTAN: fetching national dataset from DfT API (~102 MB, please wait)…"
    )
    data = _api_get(url)

    # Save as local CSV so future runs skip the download.
    try:
        _ensure_dirs()
        _NATIONAL_CSV.write_bytes(data)
        logger.info(
            "NaPTAN: saved national CSV to %s (%d MB)",
            _NATIONAL_CSV, len(data) // (1024 * 1024),
        )
    except Exception as exc:
        logger.debug("NaPTAN: could not save national CSV: %s", exc)

    return _parse_csv_bytes(data, stop_types, nptg_path)


def _api_get(url: str) -> bytes:
    """
    HTTP GET from the DfT NaPTAN API.

    SSL handling: set NAPTAN_SKIP_SSL_VERIFY=1 if cert verification fails
    on macOS (common when stdlib ssl store lacks DfT intermediate cert).
    """
    skip_verify = os.environ.get('NAPTAN_SKIP_SSL_VERIFY', '').lower() in (
        '1', 'true', 'yes',
    )
    req = urllib.request.Request(
        url,
        headers={
            'Accept':     'text/csv,application/csv,text/plain,*/*',
            'User-Agent': 'RTD_SIM/1.0 (transport research)',
        },
    )
    try:
        if skip_verify:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode    = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
                return resp.read()
        else:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()

    except ssl.SSLError as exc:
        raise RuntimeError(
            f"NaPTAN API SSL error: {exc}\n"
            f"  Fix A: place NAPTAN_National_Stops.csv in {_DATA_DIR}\n"
            f"  Fix B: export NAPTAN_SKIP_SSL_VERIFY=1\n"
            f"  Fix C: run /Applications/Python 3.x/Install Certificates.command"
        ) from exc
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"NaPTAN API HTTP {exc.code}: {url}") from exc
    except Exception as exc:
        raise RuntimeError(f"NaPTAN API request failed: {exc}") from exc


# ── CSV parsing ────────────────────────────────────────────────────────────────

def _load_from_csv(
    csv_path:   Path,
    stop_types: frozenset,
    nptg_path:  Optional[Path] = None,
) -> List[NaptanStop]:
    """Parse a local NAPTAN_National_Stops.csv file."""
    logger.info("NaPTAN: reading %s…", csv_path)
    data = csv_path.read_bytes()
    return _parse_csv_bytes(data, stop_types, nptg_path)


def _parse_csv_bytes(
    data:       bytes,
    stop_types: frozenset,
    nptg_path:  Optional[Path] = None,
) -> List[NaptanStop]:
    """
    Parse CSV bytes (DfT NaPTAN format) into NaptanStop records.

    Handles UTF-8 BOM.  Column names are lower-cased for robustness.
    """
    locality_map: Dict[str, str] = {}
    if nptg_path and nptg_path.exists():
        try:
            locality_map = _load_nptg_localities(nptg_path)
            logger.debug("NPTG: %d localities loaded", len(locality_map))
        except Exception as exc:
            logger.debug("NPTG load failed (%s)", exc)

    text   = data.decode('utf-8-sig', errors='replace')
    reader = csv.DictReader(io.StringIO(text))

    if reader.fieldnames:
        reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]

    stops: List[NaptanStop] = []
    skipped = 0

    for row in reader:
        stop_type = row.get('stoptype', row.get('stop_type', '')).strip()
        if stop_type not in stop_types:
            continue

        status_raw = row.get('status', 'active').strip().lower()
        if status_raw not in ('active', 'act', '1', 'true'):
            skipped += 1
            continue

        try:
            lon = float(row.get('longitude', row.get('lon', '')) or '0')
            lat = float(row.get('latitude',  row.get('lat', '')) or '0')
        except ValueError:
            skipped += 1
            continue
        if lon == 0.0 and lat == 0.0:
            skipped += 1
            continue

        common_name   = row.get('commonname', row.get('common_name', '')).strip()
        locality_code = row.get('nptglocalitycode', '').strip()
        if locality_code and locality_code in locality_map:
            locality = locality_map[locality_code]
            if locality and locality.lower() not in common_name.lower():
                common_name = f"{common_name}, {locality}"

        atco_code = row.get('atcocode', row.get('atco_code', '')).strip()
        crs_code  = row.get(
            'crsref', row.get('crscode', row.get('crs_code', row.get('crs', '')))
        ).strip()

        stops.append(NaptanStop(
            atco_code   = atco_code,
            common_name = common_name,
            stop_type   = stop_type,
            lon         = lon,
            lat         = lat,
            crs_code    = crs_code,
            status      = 'act',
        ))

    logger.debug(
        "NaPTAN CSV: %d stops kept, %d skipped (inactive/bad coords)",
        len(stops), skipped,
    )
    return stops


def _load_nptg_localities(path: Path) -> Dict[str, str]:
    """Parse NPTG_Localities.csv -> {NptgLocalityCode: LocalityName}."""
    result: Dict[str, str] = {}
    data   = path.read_bytes()
    text   = data.decode('utf-8-sig', errors='replace')
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames:
        reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]
    for row in reader:
        code = row.get('nptglocalitycode', '').strip()
        name = row.get('localityname', row.get('locality_name', '')).strip()
        if code and name:
            result[code] = name
    return result


# ── rail_spine fallback ────────────────────────────────────────────────────────

def _fallback_from_spine() -> List[NaptanStop]:
    """Return NaptanStop objects from the hardcoded rail_spine STATIONS dict."""
    try:
        from simulation.spatial.rail_spine import STATIONS
        stops = [
            NaptanStop(
                atco_code   = crs,
                common_name = info['name'],
                stop_type   = 'RLY',
                lon         = info['lon'],
                lat         = info['lat'],
                crs_code    = crs,
                status      = 'act',
            )
            for crs, info in STATIONS.items()
            if info.get('type') not in ('tram_stop', 'tram_terminus', 'ferry_terminal')
        ]
        logger.info("NaPTAN: rail_spine fallback — %d stations", len(stops))
        return stops
    except Exception as exc:
        logger.error("NaPTAN spine fallback failed: %s", exc)
        return []


# ── Spatial filter ─────────────────────────────────────────────────────────────

def _filter_bbox(
    stops: List[NaptanStop],
    bbox:  Tuple[float, float, float, float],
) -> List[NaptanStop]:
    """Filter stops to (north, south, east, west) bounding box."""
    north, south, east, west = bbox
    return [
        s for s in stops
        if south <= s.lat <= north and west <= s.lon <= east
    ]


# ── Cache helpers ──────────────────────────────────────────────────────────────

def _cache_key(codes: Set[str]) -> str:
    return "_".join(sorted(codes)) if codes else "national"


def _try_load_cache(
    cache_file: Path,
    bbox:       Optional[Tuple],
    stop_types: frozenset,
) -> Optional[List[NaptanStop]]:
    """Load and filter cache file; return None if stale/missing/invalid."""
    if not cache_file.exists():
        return None
    age_days = (time.time() - cache_file.stat().st_mtime) / 86400.0
    if age_days >= CACHE_MAX_AGE_DAYS:
        logger.debug(
            "NaPTAN: cache %s is %.0f days old — refreshing",
            cache_file.name, age_days,
        )
        return None
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        stops  = [NaptanStop.from_dict(d) for d in raw
                  if d.get('stop_type') in stop_types]
        result = _filter_bbox(stops, bbox) if bbox else stops
        logger.info(
            "NaPTAN: %d/%d stops from cache %s",
            len(result), len(stops), cache_file.name,
        )
        return result
    except Exception as exc:
        logger.debug("NaPTAN: cache read failed (%s) — will re-fetch", exc)
        return None


def _save_cache(stops: List[NaptanStop], cache_file: Path) -> None:
    _ensure_dirs()
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump([s.to_dict() for s in stops], f, separators=(',', ':'))
    logger.debug("NaPTAN: cached %d stops to %s", len(stops), cache_file.name)


def _ensure_dirs() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _find_file(search_paths: List[Path]) -> Optional[Path]:
    for p in search_paths:
        if p.exists():
            return p
    return None


# ── Transfer node bridge ───────────────────────────────────────────────────────

def build_transfer_nodes(
    bbox: Optional[Tuple[float, float, float, float]] = None,
) -> List[Dict]:
    """
    Return transfer node dicts for the Router intermodal snap.

    Each dict: {lon, lat, name, crs, stop_type, atco_code}
    Includes rail (RLY), metro (MET), and tram (TMU) stops.
    """
    stops = download_naptan(bbox=bbox)
    return [
        {
            'lon':       s.lon,
            'lat':       s.lat,
            'name':      s.common_name,
            'crs':       s.crs_code or s.atco_code,
            'stop_type': s.stop_type,
            'atco_code': s.atco_code,
        }
        for s in stops
        if s.stop_type in ('RLY', 'MET', 'TMU')
    ]


# ── Nearest stop query ─────────────────────────────────────────────────────────

def nearest_naptan_stop(
    coord:      Tuple[float, float],
    stops:      List[NaptanStop],
    max_km:     float = 30.0,
    stop_types: Optional[frozenset] = None,
) -> Optional[NaptanStop]:
    """
    Return the nearest NaptanStop to (lon, lat) within max_km.

    Args:
        coord:      (lon, lat) in decimal degrees.
        stops:      List of NaptanStop objects from load_naptan_stops().
        max_km:     Maximum search radius in km.
        stop_types: Optional frozenset of NaPTAN StopType codes to include.
                    When supplied only stops whose stop_type is in this set
                    are considered.  When None all stop types are searched.

                    Use RAIL_STOP_TYPES for rail/metro/tram-only snapping
                    (prevents snapping a train agent to a nearby bus stop).

    Returns:
        Nearest matching NaptanStop, or None if none within max_km.
    """
    lon, lat = coord
    best:      Optional[NaptanStop] = None
    best_dist: float = float('inf')
    for s in stops:
        # ── Stop-type filter ─────────────────────────────────────────────────
        if stop_types is not None and s.stop_type not in stop_types:
            continue
        d = _haversine_km(lon, lat, s.lon, s.lat)
        if d < best_dist:
            best_dist = d
            best = s
    return best if best_dist <= max_km else None


# Public alias — imported by router.py for typed access.
# Rail/metro/tram stop types only: excludes bus, coach, ferry, air.
RAIL_STOP_TYPES = _RAIL_STOP_TYPES
# Narrower public aliases for mode-specific snapping (preferred over RAIL_STOP_TYPES):
__all__ = [
    'NaptanStop', 'download_naptan', 'nearest_naptan_stop', 'build_transfer_nodes',
    'RAIL_STOP_TYPES',      # broad set (RLY+MET+FER+TMU) — legacy
    'RAIL_ONLY_STOP_TYPES', # RLY only — use for local_train / intercity_train
    'TRAM_STOP_TYPES',      # TMU + MET (Edinburgh Trams uses MET)
    'FERRY_STOP_TYPES',     # FER+FBT
    'BUS_STOP_TYPES',       # BCT+BCE+BCS+BST
    'STOP_TYPE_TO_MODES',
]


# ── Haversine ──────────────────────────────────────────────────────────────────

def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    R   = 6371.0
    dp  = math.radians(lat2 - lat1)
    dl  = math.radians(lon2 - lon1)
    a   = (math.sin(dp / 2) ** 2
           + math.cos(math.radians(lat1))
           * math.cos(math.radians(lat2))
           * math.sin(dl / 2) ** 2)
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))