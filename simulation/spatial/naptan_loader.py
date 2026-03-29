"""
simulation/spatial/naptan_loader.py

NaPTAN (National Public Transport Access Nodes) loader for Phase 10b.

NaPTAN is the UK government's authoritative dataset of every station, bus stop,
tram stop, and ferry terminal.  It provides the "Transfer Nodes" that stitch
together the road and rail graphs in the layered super-graph architecture.

Why NaPTAN matters for RTD_SIM
───────────────────────────────
The layered super-graph approach (road + rail + bus + tram, connected only
at Transfer Nodes) is the architecture required to model genuine modal shift
(the 'S' in ASI).  An agent's cost calculation for Drive→Rail+Walk must include:

    drive cost (origin → Park & Ride)
  + walk cost  (P&R → platform)
  + rail cost  (platform → destination station)
  + walk cost  (destination station → final destination)

NaPTAN gives us the exact WGS84 coordinates of every UK platform / stop so
the Transfer Nodes are placed on real geography, not approximated centroids.

Data sources
────────────
• NaPTAN: https://naptan.api.dft.gov.uk/v1/access-nodes
  (Department for Transport open data, CSV / JSON)
• OpenRailMap / OSM: rail attributes (electrification, max speed, signal type)
• OS MRN (Ordnance Survey Multi-modal Routing Network): pre-connected
  road+rail+ferry graph — the ideal backbone for Phase 10c.

Current implementation
──────────────────────
Phase 10b stub:  download_naptan() fetches the DfT NaPTAN API and returns
a filtered list of rail station stop points as (name, crs, lon, lat) tuples.

This is used by the Router to:
  1. Snap agent origins/destinations to their nearest NaPTAN transfer node.
  2. Build Transfer Edges between the rail spine and the road graph.

Caching
───────
NaPTAN data changes infrequently (new stations, renaming).  We cache the
download to ~/.rtd_sim_cache/naptan/ and refresh only when the cache is older
than CACHE_MAX_AGE_DAYS (default 30).
"""

from __future__ import annotations

import csv
import json
import logging
import math
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Cache configuration ────────────────────────────────────────────────────────
_CACHE_DIR     = Path.home() / ".rtd_sim_cache" / "naptan"
_CACHE_FILE    = _CACHE_DIR / "rail_stops.json"
CACHE_MAX_AGE_DAYS = 30

# ── NaPTAN API (DfT open data) ─────────────────────────────────────────────────
# As of 2024 the DfT provides NaPTAN via a REST API.
# The CSV bulk download is at:
#   https://naptan.api.dft.gov.uk/v1/access-nodes?dataFormat=csv
# The JSON endpoint is:
#   https://naptan.api.dft.gov.uk/v1/access-nodes?dataFormat=json
_NAPTAN_API_URL = "https://naptan.api.dft.gov.uk/v1/access-nodes"

# ── Station type filter ────────────────────────────────────────────────────────
# NaPTAN StopType codes for rail / metro / ferry / tram stops
_RAIL_STOP_TYPES = frozenset({
    'RLY',   # Railway station entrance / stop
    'MET',   # Metro / underground station
    'FER',   # Ferry terminal
    'TMU',   # Tram / metro / underground stop
    'LCB',   # Light rail / cable car
    'BCE',   # Bus / coach station entrance (for intermodal)
})


# ── NaPTAN stop dataclass ──────────────────────────────────────────────────────

class NaptanStop:
    """Lightweight NaPTAN stop record."""
    __slots__ = ('atco_code', 'common_name', 'stop_type',
                 'lon', 'lat', 'crs_code', 'status')

    def __init__(self, atco_code: str, common_name: str, stop_type: str,
                 lon: float, lat: float, crs_code: str = '', status: str = 'act'):
        self.atco_code   = atco_code
        self.common_name = common_name
        self.stop_type   = stop_type
        self.lon         = lon
        self.lat         = lat
        self.crs_code    = crs_code
        self.status      = status

    def to_dict(self) -> dict:
        return {
            'atco_code':   self.atco_code,
            'common_name': self.common_name,
            'stop_type':   self.stop_type,
            'lon':         self.lon,
            'lat':         self.lat,
            'crs_code':    self.crs_code,
            'status':      self.status,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'NaptanStop':
        return cls(
            atco_code   = d['atco_code'],
            common_name = d['common_name'],
            stop_type   = d['stop_type'],
            lon         = d['lon'],
            lat         = d['lat'],
            crs_code    = d.get('crs_code', ''),
            status      = d.get('status', 'act'),
        )

    def __repr__(self) -> str:
        return (f"NaptanStop({self.common_name!r}, type={self.stop_type}, "
                f"lon={self.lon:.4f}, lat={self.lat:.4f})")


# ── Download and parse ─────────────────────────────────────────────────────────

def download_naptan(
    bbox: Optional[Tuple[float, float, float, float]] = None,
    stop_types: Optional[frozenset] = None,
    force_refresh: bool = False,
) -> List[NaptanStop]:
    """
    Download NaPTAN rail/metro/ferry stop data.

    Results are cached to disk for CACHE_MAX_AGE_DAYS days.
    On failure, falls back to the hardcoded Edinburgh stations from rail_spine.py.

    Args:
        bbox:          Optional (north, south, east, west) spatial filter.
                       When None, downloads all UK stops (large — ~400k rows).
        stop_types:    NaPTAN StopType codes to include.
                       Default: _RAIL_STOP_TYPES.
        force_refresh: Bypass the disk cache and re-download.

    Returns:
        List of NaptanStop records.
    """
    stop_types = stop_types or _RAIL_STOP_TYPES

    # ── Try disk cache ─────────────────────────────────────────────────────────
    if not force_refresh and _cache_is_fresh():
        try:
            stops = _load_cache()
            if bbox:
                stops = _filter_bbox(stops, bbox)
            logger.info(
                "NaPTAN: loaded %d stops from cache (bbox filter=%s)",
                len(stops), bbox is not None,
            )
            return stops
        except Exception as exc:
            logger.warning("NaPTAN cache load failed: %s — re-downloading", exc)

    # ── Download from DfT API ──────────────────────────────────────────────────
    try:
        stops = _fetch_from_api(stop_types)
        if stops:
            _save_cache(stops)
            logger.info("NaPTAN: downloaded and cached %d stops", len(stops))
        if bbox:
            stops = _filter_bbox(stops, bbox)
        return stops
    except Exception as exc:
        logger.error("NaPTAN download failed: %s — using rail_spine fallback", exc)
        return _fallback_from_spine()


# def _fetch_from_api(stop_types: frozenset) -> List[NaptanStop]:
#     """Download from DfT NaPTAN API (JSON format)."""
#     try:
#         import urllib.request
#         url = f"{_NAPTAN_API_URL}?dataFormat=json"
        
#         # HACK: User-Agent spoofing to bypass DfT firewalls, and 120s timeout for large payload
#         headers = {
#             'Accept': 'application/json',
#             'User-Agent': 'RTD-SIM/1.0 (freight-decarbonisation-simulator)'
#         }
#         req = urllib.request.Request(url, headers=headers)
        
#         logger.info("Fetching NaPTAN data from DfT API (this may take up to 2 minutes)...")
#         with urllib.request.urlopen(req, timeout=120) as resp:
#             data = json.loads(resp.read().decode('utf-8'))
#     except Exception as exc:
#         raise RuntimeError(f"NaPTAN API request failed: {exc}") from exc

#     stops: List[NaptanStop] = []
#     raw_list = data if isinstance(data, list) else data.get('stopPoints', [])

#     for item in raw_list:
#         stop_type = item.get('stopType', '')
#         if stop_type not in stop_types:
#             continue
#         status = item.get('status', 'act')
#         if status not in ('act', 'active'):
#             continue
#         try:
#             lon = float(item.get('longitude', item.get('lon', 0)))
#             lat = float(item.get('latitude',  item.get('lat', 0)))
#         except (TypeError, ValueError):
#             continue
#         if lon == 0 and lat == 0:
#             continue

#         stops.append(NaptanStop(
#             atco_code   = item.get('atcoCode', ''),
#             common_name = item.get('commonName', item.get('name', '')),
#             stop_type   = stop_type,
#             lon         = lon,
#             lat         = lat,
#             crs_code    = item.get('crsCode', ''),
#             status      = status,
#         ))

#     return stops
def _fetch_from_api(stop_types: frozenset) -> List[NaptanStop]:
    """Download from DfT NaPTAN API (CSV format - much more stable than JSON)."""
    import urllib.request
    import csv
    import io
    
    try:
        url = f"{_NAPTAN_API_URL}?dataFormat=csv"
        
        # Spoof standard browser to bypass DfT bot protection
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'
        }
        req = urllib.request.Request(url, headers=headers)
        
        logger.info("Fetching NaPTAN data from DfT CSV API (this is large, please wait)...")
        with urllib.request.urlopen(req, timeout=120) as resp:
            # Read and decode CSV stream
            csv_text = resp.read().decode('utf-8-sig')
            
    except Exception as exc:
        raise RuntimeError(f"NaPTAN API request failed: {exc}") from exc

    stops: List[NaptanStop] = []
    reader = csv.DictReader(io.StringIO(csv_text))
    
    for row in reader:
        stop_type = row.get('StopType', '')
        if stop_type not in stop_types:
            continue
        status = row.get('Status', 'act')
        if status not in ('act', 'active'):
            continue
            
        try:
            lon = float(row.get('Longitude', 0))
            lat = float(row.get('Latitude', 0))
        except (TypeError, ValueError):
            continue
            
        if lon == 0 and lat == 0:
            continue

        stops.append(NaptanStop(
            atco_code   = row.get('ATCOCode', ''),
            common_name = row.get('CommonName', ''),
            stop_type   = stop_type,
            lon         = lon,
            lat         = lat,
            crs_code    = row.get('CrsCode', ''),
            status      = status,
        ))

    return stops


def _fallback_from_spine() -> List[NaptanStop]:
    """Return NaptanStop objects derived from the hardcoded rail_spine.py."""
    try:
        from simulation.spatial.rail_spine import STATIONS
        stops = []
        for crs, info in STATIONS.items():
            stops.append(NaptanStop(
                atco_code   = crs,
                common_name = info['name'],
                stop_type   = 'RLY',
                lon         = info['lon'],
                lat         = info['lat'],
                crs_code    = crs,
                status      = 'act',
            ))
        logger.info("NaPTAN: using rail_spine fallback (%d stations)", len(stops))
        return stops
    except Exception as exc:
        logger.error("NaPTAN spine fallback failed: %s", exc)
        return []


# ── Bbox filter ────────────────────────────────────────────────────────────────

def _filter_bbox(
    stops: List[NaptanStop],
    bbox: Tuple[float, float, float, float],
) -> List[NaptanStop]:
    north, south, east, west = bbox
    return [
        s for s in stops
        if south <= s.lat <= north and west <= s.lon <= east
    ]


# ── Cache helpers ──────────────────────────────────────────────────────────────

def _cache_is_fresh() -> bool:
    if not _CACHE_FILE.exists():
        return False
    age_days = (time.time() - _CACHE_FILE.stat().st_mtime) / 86400.0
    return age_days < CACHE_MAX_AGE_DAYS


def _save_cache(stops: List[NaptanStop]) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(_CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump([s.to_dict() for s in stops], f)


def _load_cache() -> List[NaptanStop]:
    with open(_CACHE_FILE, 'r', encoding='utf-8') as f:
        return [NaptanStop.from_dict(d) for d in json.load(f)]


# ── Transfer node integration ──────────────────────────────────────────────────

def build_transfer_nodes(
    bbox: Optional[Tuple[float, float, float, float]] = None,
) -> List[Dict]:
    """
    Build transfer node dicts for use in the Router intermodal snap.

    Each dict has: lon, lat, name, crs, stop_type, atco_code.
    These are used by Router._nearest_rail_node() to snap agent origins /
    destinations to the nearest station before routing on the rail graph.

    Args:
        bbox: Spatial filter (north, south, east, west).  When None returns
              all downloaded stops (use sparingly — ~2,500 rail stops UK-wide).

    Returns:
        List of dicts compatible with rail-spine station format.
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
        if s.stop_type in ('RLY', 'MET')   # rail + metro only for now
    ]


# ── Haversine (standalone, no external deps) ───────────────────────────────────

def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    R = 6371.0
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a  = (math.sin(dp / 2) ** 2
          + math.cos(math.radians(lat1))
          * math.cos(math.radians(lat2))
          * math.sin(dl / 2) ** 2)
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def nearest_naptan_stop(
    coord: Tuple[float, float],
    stops: List[NaptanStop],
    max_km: float = 30.0,
) -> Optional[NaptanStop]:
    """
    Return the nearest NaptanStop to (lon, lat) coord within max_km.

    Used by the Router to snap agents to transfer nodes before
    computing the rail or ferry leg.
    """
    lon, lat = coord
    best: Optional[NaptanStop] = None
    best_dist = float('inf')
    for s in stops:
        d = _haversine_km(lon, lat, s.lon, s.lat)
        if d < best_dist:
            best_dist = d
            best = s
    return best if best_dist <= max_km else None