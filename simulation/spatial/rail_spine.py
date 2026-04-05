"""
simulation/spatial/rail_spine.py

UK Rail Spine — last-resort fallback station graph.

ROLE IN THE ROUTING ARCHITECTURE
──────────────────────────────────
This module is NOT the primary source of station locations.  The routing
priority is:

    1. NaPTAN (DfT authoritative dataset, ~2,500 UK stations + ferry terminals,
       cached 30 days via naptan_loader.py).  Provides ±5 m platform accuracy
       for every UK rail, metro, tram, and CalMac ferry terminal.

    2. OpenRailMap graph (fetched by rail_network.py via OSMnx on each run).
       Provides actual track geometry so rail agents follow real alignments.

    3. This spine (hardcoded STATIONS dict + TRACK_EDGES list).  Used when:
         • NaPTAN download fails (offline / DfT API down)
         • OpenRailMap fetch fails or returns a sparse/disconnected graph

UK COVERAGE
───────────
This spine covers:

    Edinburgh city stations and tram interchanges
    Edinburgh → Glasgow (via Polmont / Falkirk High)
    Edinburgh → Fife Circle (Kirkcaldy)
    Edinburgh → Dundee / Aberdeen (East Coast Main Line)
    Edinburgh → Newcastle / York / Leeds / Birmingham / London (ECML + WCML)
    Edinburgh → Inverness (Highland Main via Perth)
    Inverness → Wick / Thurso (Far North Line)
    Inverness → Kyle of Lochalsh (Kyle Line)
    Inverness → Aberdeen
    Glasgow → Fort William → Mallaig (West Highland Line)
    Glasgow → Oban (Oban Line)
    CalMac ferry terminals: Ullapool, Ardrossan, Kennacraig, Stornoway, Scrabster

For agents in the Scottish Highlands, Islands, or ferry-dependent corridors
(Orkney, Hebrides), the spine provides usable if not precise transfer nodes.
NaPTAN gives much better results and is strongly preferred.

TRAM ROUTING
────────────
Edinburgh tram stops are in TRAM_STOPS (separate from STATIONS) and are
used by route_via_tram_stops().  With a GTFS feed loaded, tram agents route
entirely on the GTFS transit graph and the spine is not used.

Edinburgh stations (per Network Rail / ScotRail):
  Waverley (EDB), Haymarket (HYM), Edinburgh Gateway (EGY),
  Edinburgh Park (EDP), South Gyle, Brunstane, Newcraighall,
  Kingsknowe, Slateford, Wester Hailes, Curriehill, Dalmeny,
  North Berwick (regional), Musselburgh (regional)

Intercity connections encoded:
  Edinburgh → Glasgow Queen St / Central (via Falkirk High / Polmont)
  Edinburgh → Dunfermline / Kirkcaldy (Fife Circle)
  Edinburgh → Dundee / Aberdeen (via Haymarket)
  Edinburgh → Newcastle / London KX (East Coast Main Line)
  Edinburgh → Inverness (Highland Main via Perth)
  Inverness → Wick / Thurso (Far North)
  Inverness → Kyle of Lochalsh
  Glasgow → Fort William → Mallaig (West Highland)
  Glasgow → Oban
"""

from __future__ import annotations

import logging
import math
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import networkx as nx
    _NX_AVAILABLE = True
except ImportError:
    _NX_AVAILABLE = False
    logger.warning("NetworkX not available — rail spine will use nearest-station only")

# ─────────────────────────────────────────────────────────────────────────────
# STATION DATABASE
# Coordinates are (lon, lat) — same convention as all other spatial code.
# CRS codes used as node IDs for readability.
# ─────────────────────────────────────────────────────────────────────────────
STATIONS: Dict[str, Dict] = {
    # ── Edinburgh city stations ───────────────────────────────────────────────
    "EDB": {
        "name":     "Edinburgh Waverley",
        "lon":      -3.1909,
        "lat":       55.9521,
        "type":     "major",
        "tram_link": False,
    },
    "HYM": {
        "name":     "Edinburgh Haymarket",
        "lon":      -3.2183,
        "lat":       55.9462,
        "type":     "major",
        "tram_link": False,
    },
    "EGY": {
        "name":     "Edinburgh Gateway",
        "lon":      -3.3072,
        "lat":       55.9272,
        "type":     "interchange",   # tram interchange
        "tram_link": True,
    },
    "EDP": {
        "name":     "Edinburgh Park",
        "lon":      -3.3071,
        "lat":       55.9261,
        "type":     "suburban",
        "tram_link": True,
    },
    "SGL": {
        "name":     "South Gyle",
        "lon":      -3.3012,
        "lat":       55.9306,
        "type":     "suburban",
        "tram_link": False,
    },
    "KGN": {
        "name":     "Kingsknowe",
        "lon":      -3.2674,
        "lat":       55.9218,
        "type":     "suburban",
        "tram_link": False,
    },
    "SLA": {
        "name":     "Slateford",
        "lon":      -3.2378,
        "lat":       55.9285,
        "type":     "suburban",
        "tram_link": False,
    },
    "WHS": {
        "name":     "Wester Hailes",
        "lon":      -3.2863,
        "lat":       55.9157,
        "type":     "suburban",
        "tram_link": False,
    },
    "CRH": {
        "name":     "Curriehill",
        "lon":      -3.3350,
        "lat":       55.9063,
        "type":     "suburban",
        "tram_link": False,
    },
    "BRS": {
        "name":     "Brunstane",
        "lon":      -3.1050,
        "lat":       55.9420,
        "type":     "suburban",
        "tram_link": False,
    },
    "NCR": {
        "name":     "Newcraighall",
        "lon":      -3.0962,
        "lat":       55.9320,
        "type":     "suburban",
        "tram_link": False,
    },
    "DEM": {
        "name":     "Dalmeny",
        "lon":      -3.3820,
        "lat":       55.9939,
        "type":     "suburban",
        "tram_link": False,
    },
    # ── Regional ──────────────────────────────────────────────────────────────
    "MUS": {
        "name":     "Musselburgh",
        "lon":      -3.0572,
        "lat":       55.9422,
        "type":     "regional",
        "tram_link": False,
    },
    "NBW": {
        "name":     "North Berwick",
        "lon":      -2.7234,
        "lat":       56.0573,
        "type":     "regional",
        "tram_link": False,
    },
    # ── ECML / intercity ──────────────────────────────────────────────────────
    "LIN": {
        "name":     "Linlithgow",
        "lon":      -3.6020,
        "lat":       55.9779,
        "type":     "intercity_stop",
        "tram_link": False,
    },
    "FKH": {
        "name":     "Falkirk High",
        "lon":      -3.7840,
        "lat":       55.9998,
        "type":     "intercity_stop",
        "tram_link": False,
    },
    "GLQ": {
        "name":     "Glasgow Queen Street",
        "lon":      -4.2491,
        "lat":       55.8638,
        "type":     "major",
        "tram_link": False,
    },
    "GLC": {
        "name":     "Glasgow Central",
        "lon":      -4.2572,
        "lat":       55.8591,
        "type":     "major",
        "tram_link": False,
    },
    "KKD": {
        "name":     "Kirkcaldy",
        "lon":      -3.1612,
        "lat":       56.1138,
        "type":     "intercity_stop",
        "tram_link": False,
    },
    "DND": {
        "name":     "Dundee",
        "lon":      -2.9707,
        "lat":       56.4575,
        "type":     "major",
        "tram_link": False,
    },
    "ABD": {
        "name":     "Aberdeen",
        "lon":      -2.0993,
        "lat":       57.1441,
        "type":     "major",
        "tram_link": False,
    },
    "NCL": {
        "name":     "Newcastle",
        "lon":      -1.6178,
        "lat":       54.9783,
        "type":     "major",
        "tram_link": False,
    },
    "IVR": {
        "name":     "Inverness",
        "lon":      -4.2248,
        "lat":       57.4804,
        "type":     "major",
        "tram_link": False,
    },
    # ── Freight-relevant (ScotRail freight corridors) ─────────────────────────
    "PBR": {
        "name":     "Polmont",
        "lon":      -3.7154,
        "lat":       55.9953,
        "type":     "freight_junction",
        "tram_link": False,
    },
    "GRN": {
        "name":     "Grangemouth Jct",
        "lon":      -3.7174,
        "lat":       56.0104,
        "type":     "freight_junction",
        "tram_link": False,
    },

    # ── Central Scotland ──────────────────────────────────────────────────────
    "STG": {
        "name":     "Stirling",
        "lon":      -3.9353,
        "lat":       56.1168,
        "type":     "major",
        "tram_link": False,
    },
    "DBL": {
        "name":     "Dunblane",
        "lon":      -3.9668,
        "lat":       56.1867,
        "type":     "suburban",
        "tram_link": False,
    },
    "PTH": {
        "name":     "Perth",
        "lon":      -3.4237,
        "lat":       56.3936,
        "type":     "major",
        "tram_link": False,
    },
    "DEE": {
        "name":     "Dundee",
        "lon":      -2.9726,
        "lat":       56.4560,
        "type":     "major",
        "tram_link": False,
    },
    "LRH": {
        "name":     "Leuchars",
        "lon":      -2.8918,
        "lat":       56.3814,
        "type":     "regional",
        "tram_link": False,
    },

    # ── West Highland & Argyll ────────────────────────────────────────────────
    # These stations are the only rail-connected points for agents in the
    # Western Highlands and Argyll.  NaPTAN will augment these with halts,
    # but having them in the spine ensures Highland agents route correctly
    # even when the NaPTAN download fails.
    "FTW": {
        "name":     "Fort William",
        "lon":      -5.1027,
        "lat":       56.8220,
        "type":     "major",
        "tram_link": False,
    },
    "MLG": {
        "name":     "Mallaig",
        "lon":      -5.8285,
        "lat":       57.0070,
        "type":     "regional",
        "tram_link": False,
    },
    "OBN": {
        "name":     "Oban",
        "lon":      -5.4742,
        "lat":       56.4150,
        "type":     "major",       # also CalMac ferry terminal
        "tram_link": False,
    },
    "CRN": {
        "name":     "Crianlarich",
        "lon":      -4.6168,
        "lat":       56.3899,
        "type":     "interchange",  # West Highland / Oban split junction
        "tram_link": False,
    },

    # ── Far North ─────────────────────────────────────────────────────────────
    # Caithness is the end of the UK rail network.  Without these, agents in
    # Wick or Thurso have no valid intermodal snap point.
    "WCK": {
        "name":     "Wick",
        "lon":      -3.0882,
        "lat":       58.4394,
        "type":     "regional",
        "tram_link": False,
    },
    "THS": {
        "name":     "Thurso",
        "lon":      -3.5246,
        "lat":       58.5927,
        "type":     "regional",
        "tram_link": False,
    },
    "IVB": {
        "name":     "Invergordon",
        "lon":      -4.1726,
        "lat":       57.6873,
        "type":     "regional",
        "tram_link": False,
    },
    "KYL": {
        "name":     "Kyle of Lochalsh",
        "lon":      -5.7170,
        "lat":       57.2772,
        "type":     "regional",    # ferry to Skye (pre-bridge), Stornoway bus
        "tram_link": False,
    },

    # ── Ferry terminals (for intermodal ferry-rail agents) ────────────────────
    # These are NOT rail stations but are registered as transfer nodes so
    # ferry_diesel / ferry_electric agents can snap to them correctly.
    # NaPTAN FER type covers ferry terminals; these are the spine fallback.
    "ULP": {
        "name":     "Ullapool Ferry Terminal",
        "lon":      -5.1560,
        "lat":       57.8936,
        "type":     "ferry_terminal",
        "tram_link": False,
    },
    "ARD": {
        "name":     "Ardrossan Harbour",
        "lon":      -4.8201,
        "lat":       55.6398,
        "type":     "ferry_terminal",  # Caledonian MacBrayne to Arran
        "tram_link": False,
    },
    "KEN": {
        "name":     "Kennacraig Ferry Terminal",
        "lon":      -5.4881,
        "lat":       55.8906,
        "type":     "ferry_terminal",  # CalMac to Islay / Jura
        "tram_link": False,
    },
    "STO": {
        "name":     "Stornoway Ferry Terminal",
        "lon":      -6.3862,
        "lat":       58.2088,
        "type":     "ferry_terminal",  # Ullapool–Stornoway
        "tram_link": False,
    },
    "SCR": {
        "name":     "Scrabster Ferry Terminal",
        "lon":      -3.5428,
        "lat":       58.6107,
        "type":     "ferry_terminal",  # NorthLink to Stromness (Orkney)
        "tram_link": False,
    },
    "STR": {
        "name":     "Stromness Ferry Terminal",
        "lon":      -3.2966,
        "lat":       58.9638,
        "type":     "ferry_terminal",  # NorthLink from Scrabster
        "tram_link": False,
    },

    # ── England intercity (East/West Coast Main Lines) ────────────────────────
    # Present as last-resort fallback for cross-border agents.
    # NaPTAN covers the full ~2,500 UK station network; these only matter
    # when NaPTAN is unavailable.
    "YRK": {
        "name":     "York",
        "lon":      -1.0928,
        "lat":       53.9581,
        "type":     "intercity_stop",
        "tram_link": False,
    },
    "LDS": {
        "name":     "Leeds",
        "lon":      -1.5491,
        "lat":       53.7960,
        "type":     "major",
        "tram_link": False,
    },
    "MAN": {
        "name":     "Manchester Piccadilly",
        "lon":      -2.2308,
        "lat":       53.4773,
        "type":     "major",
        "tram_link": False,
    },
    "BHM": {
        "name":     "Birmingham New Street",
        "lon":      -1.9003,
        "lat":       52.4778,
        "type":     "major",
        "tram_link": False,
    },
    "LBG": {
        "name":     "London King's Cross",
        "lon":      -0.1240,
        "lat":       51.5308,
        "type":     "major",
        "tram_link": False,
    },

    # ── Edinburgh Tram stops (Airport → Newhaven, Phase 1 + 2 extension) ─────
    # Coordinates from Transport for Edinburgh / Lothian Buses open data.
    # Type 'tram_stop' is used exclusively for tram routing via route_via_stations().
    # 'tram_terminus' marks end-of-line stops.
    "TRAM_AIR": {
        "name":     "Edinburgh Airport",
        "lon":      -3.3616,
        "lat":       55.9501,
        "type":     "tram_terminus",
        "tram_link": True,
    },
    "TRAM_ING": {
        "name":     "Ingliston Park & Ride",
        "lon":      -3.3501,
        "lat":       55.9388,
        "type":     "tram_stop",
        "tram_link": False,
    },
    "TRAM_GOG": {
        "name":     "Gogar",
        "lon":      -3.3262,
        "lat":       55.9285,
        "type":     "tram_stop",
        "tram_link": False,
    },
    "TRAM_BNK": {
        "name":     "Bankhead",
        "lon":      -3.2989,
        "lat":       55.9271,
        "type":     "tram_stop",
        "tram_link": False,
    },
    "TRAM_STN": {
        "name":     "Stenhouse",
        "lon":      -3.2708,
        "lat":       55.9267,
        "type":     "tram_stop",
        "tram_link": False,
    },
    "TRAM_BLG": {
        "name":     "Balgreen",
        "lon":      -3.2570,
        "lat":       55.9347,
        "type":     "tram_stop",
        "tram_link": False,
    },
    "TRAM_MRF": {
        "name":     "Murrayfield Stadium",
        "lon":      -3.2445,
        "lat":       55.9411,
        "type":     "tram_stop",
        "tram_link": False,
    },
    "TRAM_RSB": {
        "name":     "Roseburn",
        "lon":      -3.2333,
        "lat":       55.9466,
        "type":     "tram_stop",
        "tram_link": False,
    },
    "TRAM_WEP": {
        "name":     "West End – Princes Street",
        "lon":      -3.2130,
        "lat":       55.9495,
        "type":     "tram_stop",
        "tram_link": False,
    },
    "TRAM_PRS": {
        "name":     "Princes Street",
        "lon":      -3.1983,
        "lat":       55.9506,
        "type":     "tram_stop",
        "tram_link": False,
    },
    "TRAM_SAS": {
        "name":     "St Andrew Square",
        "lon":      -3.1890,
        "lat":       55.9527,
        "type":     "tram_stop",
        "tram_link": False,
    },
    "TRAM_YRK": {
        "name":     "York Place",
        "lon":      -3.1862,
        "lat":       55.9573,
        "type":     "tram_stop",
        "tram_link": False,
    },
    # ── Newhaven extension (opened June 2023) ─────────────────────────────────
    "TRAM_PIC": {
        "name":     "Picardy Place",
        "lon":      -3.1844,
        "lat":       55.9600,
        "type":     "tram_stop",
        "tram_link": False,
    },
    "TRAM_MCR": {
        "name":     "McDonald Road",
        "lon":      -3.1807,
        "lat":       55.9638,
        "type":     "tram_stop",
        "tram_link": False,
    },
    "TRAM_BAL": {
        "name":     "Balfour Street",
        "lon":      -3.1754,
        "lat":       55.9692,
        "type":     "tram_stop",
        "tram_link": False,
    },
    "TRAM_NEW": {
        "name":     "Newhaven",
        "lon":      -3.1717,
        "lat":       55.9779,
        "type":     "tram_terminus",
        "tram_link": False,
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# EDINBURGH TRAMS STOP DATABASE
# Source: Edinburgh Trams official stop coordinates (2024), including the
# Newhaven extension opened May 2023.
# All coordinates verified against Ordnance Survey 1:25000.
# Keys are short identifiers used as graph node IDs.
# ─────────────────────────────────────────────────────────────────────────────
TRAM_STOPS: Dict[str, Dict] = {
    # ── Airport / West corridor ───────────────────────────────────────────────
    "EAP": {"name": "Edinburgh Airport",      "lon": -3.3636, "lat": 55.9503},
    "IPR": {"name": "Ingliston Park & Ride",  "lon": -3.3490, "lat": 55.9421},
    # EGY (Edinburgh Gateway) is shared with rail — defined in STATIONS
    "GOG": {"name": "Gogar",                  "lon": -3.3251, "lat": 55.9259},
    # EDP (Edinburgh Park) is shared with rail — defined in STATIONS
    "BKH": {"name": "Bankhead",               "lon": -3.2978, "lat": 55.9230},
    "GYL": {"name": "Gyle Centre",            "lon": -3.2882, "lat": 55.9230},
    # ── West Edinburgh ────────────────────────────────────────────────────────
    "BLG": {"name": "Balgreen",               "lon": -3.2613, "lat": 55.9260},
    "MFS": {"name": "Murrayfield Stadium",    "lon": -3.2524, "lat": 55.9428},
    "MFD": {"name": "Murrayfield",            "lon": -3.2382, "lat": 55.9430},
    # ── City centre ───────────────────────────────────────────────────────────
    "WEP": {"name": "West End – Princes St",  "lon": -3.2199, "lat": 55.9498},
    "PST": {"name": "Princes Street",         "lon": -3.2014, "lat": 55.9508},
    "SAS": {"name": "St Andrew Square",       "lon": -3.1905, "lat": 55.9530},
    "YRP": {"name": "York Place",             "lon": -3.1851, "lat": 55.9567},
    # ── Newhaven extension (2023) ──────────────────────────────────────────────
    "PCP": {"name": "Picardy Place",          "lon": -3.1823, "lat": 55.9590},
    "MDR": {"name": "McDonald Road",          "lon": -3.1836, "lat": 55.9621},
    "BFS": {"name": "Balfour Street",         "lon": -3.1817, "lat": 55.9665},
    "BRO": {"name": "Bonnington Road",        "lon": -3.1787, "lat": 55.9717},
    "OHT": {"name": "Ocean Terminal",         "lon": -3.1778, "lat": 55.9768},
    "NWH": {"name": "Newhaven",               "lon": -3.1757, "lat": 55.9804},
}

# Ordered list of stops along the single tram line (Airport to Newhaven)
# Distances in km are approximate inter-stop spacings.
TRAM_LINE: List[Tuple[str, str, float]] = [
    # (from_stop, to_stop, distance_km)
    ("EAP", "IPR", 1.2),
    ("IPR", "EGY", 1.4),   # EGY is a rail/tram interchange — use STATIONS coords
    ("EGY", "GOG", 0.9),
    ("GOG", "EDP", 0.3),   # EDP is a rail/tram interchange
    ("EDP", "BKH", 0.5),
    ("BKH", "GYL", 0.7),
    ("GYL", "BLG", 2.5),
    ("BLG", "MFS", 0.8),
    ("MFS", "MFD", 0.7),
    ("MFD", "WEP", 0.9),
    ("WEP", "PST", 0.8),
    ("PST", "SAS", 0.7),
    ("SAS", "YRP", 0.5),
    ("YRP", "PCP", 0.4),
    ("PCP", "MDR", 0.5),
    ("MDR", "BFS", 0.5),
    ("BFS", "BRO", 0.5),
    ("BRO", "OHT", 0.5),
    ("OHT", "NWH", 0.4),
]

# Ordered stop sequence (for path finding without NX)
_TRAM_STOP_ORDER = [edge[0] for edge in TRAM_LINE] + [TRAM_LINE[-1][1]]


def _tram_stop_coord(stop_id: str) -> Optional[Tuple[float, float]]:
    """Return (lon, lat) for a tram stop, checking TRAM_STOPS then STATIONS."""
    if stop_id in TRAM_STOPS:
        info = TRAM_STOPS[stop_id]
        return (info['lon'], info['lat'])
    if stop_id in STATIONS:
        info = STATIONS[stop_id]
        return (info['lon'], info['lat'])
    return None


def _nearest_tram_stop(
    coord: Tuple[float, float],
    max_km: float = 2.5,
) -> Optional[str]:
    """
    Return the ID of the nearest Edinburgh tram stop within max_km.

    Returns None when no stop is within the catchment distance so that
    tram is correctly excluded as a mode option for agents far from the
    corridor (e.g. agents in Balerno, Musselburgh, Bo'ness).

    DfT walking distance standard for tram/LRT: 700m (modal shift model).
    We use 2.5km — Edinburgh tram stops are up to ~2.3km from agents placed
    in outer suburbs (Balgreen, Slateford, Longstone). 1.5km was too tight.

    Args:
        coord:  (lon, lat)
        max_km: Maximum walk/access distance to nearest stop (default 2.5km).
    """
    lon, lat = coord
    best_id   = None
    best_dist = float('inf')
    for stop_id, info in TRAM_STOPS.items():
        d = _haversine(lon, lat, info['lon'], info['lat'])
        if d < best_dist:
            best_dist = d
            best_id   = stop_id
    # Also check shared rail/tram interchange stops
    for stop_id in ('EGY', 'EDP'):
        if stop_id in STATIONS:
            info = STATIONS[stop_id]
            d = _haversine(lon, lat, info['lon'], info['lat'])
            if d < best_dist:
                best_dist = d
                best_id   = stop_id

    if best_dist > max_km:
        logger.debug(
            "_nearest_tram_stop: nearest stop %.2fkm away (max %.1fkm) — outside catchment",
            best_dist, max_km,
        )
        return None
    return best_id


def route_via_tram_stops(
    origin: Tuple[float, float],
    dest: Tuple[float, float],
    max_access_km: float = 2.5,
) -> Optional[List[Tuple[float, float]]]:
    """
    Build a realistic Edinburgh tram route as a list of (lon, lat) waypoints.

    Returns None when either origin or destination is outside the tram
    corridor catchment (default 2.5km from nearest stop).  Callers must
    check for None and fall back to make_synthetic_route or skip tram.
    A route with only 2 points (origin, dest) is also treated as None by
    the caller — it means the routing failed, not that tram is viable.

    Strategy:
      1. Find nearest tram stop within max_access_km of origin.
      2. Find nearest tram stop within max_access_km of dest.
      3. If either is None → return None (tram not viable for this trip).
      4. Route through ordered stops between the two snapped stops.

    Args:
        origin:         (lon, lat)
        dest:           (lon, lat)
        max_access_km:  Maximum walk/feeder distance to tram stop (default 2.5km).
    """
    origin_stop_id = _nearest_tram_stop(origin, max_km=max_access_km)
    dest_stop_id   = _nearest_tram_stop(dest,   max_km=max_access_km)

    # One or both ends are outside tram catchment — not viable
    if origin_stop_id is None or dest_stop_id is None:
        return None

    if origin_stop_id == dest_stop_id:
        # Both ends snap to the same stop — trip too short for tram.
        # Return None rather than a 2-point list: a 2-point route is
        # indistinguishable from "routing failed" and would be shown
        # as a straight diagonal on the map.
        return None

    # Find indices in the ordered stop list
    try:
        idx_a = _TRAM_STOP_ORDER.index(origin_stop_id)
        idx_b = _TRAM_STOP_ORDER.index(dest_stop_id)
    except ValueError:
        # Stop not in ordered list — fall back to endpoints only
        a = _tram_stop_coord(origin_stop_id)
        b = _tram_stop_coord(dest_stop_id)
        return [origin] + ([a] if a else []) + ([b] if b else []) + [dest]

    # Slice in correct direction
    if idx_a <= idx_b:
        stop_ids = _TRAM_STOP_ORDER[idx_a : idx_b + 1]
    else:
        stop_ids = list(reversed(_TRAM_STOP_ORDER[idx_b : idx_a + 1]))

    waypoints = []
    for sid in stop_ids:
        coord = _tram_stop_coord(sid)
        if coord:
            waypoints.append(coord)

    route = [origin] + waypoints + [dest]
    logger.debug(
        "route_via_tram_stops: %s→%s via %d stops (%s→%s)",
        origin, dest, len(waypoints),
        origin_stop_id, dest_stop_id,
    )
    return route

# ─────────────────────────────────────────────────────────────────────────────
# TRACK CONNECTIONS
# Edges: (from_crs, to_crs, distance_km, line_name)
# Bidirectional — we add both directions when building the graph.
# Distances are approximate track km.
# ─────────────────────────────────────────────────────────────────────────────
TRACK_EDGES: List[Tuple[str, str, float, str]] = [
    # ── Suburban Edinburgh (Waverley → W) ─────────────────────────────────────
    ("EDB", "SLA",  3.0,  "Edinburgh Suburban"),
    ("SLA", "KGN",  2.5,  "Edinburgh Suburban"),
    ("KGN", "WHS",  3.5,  "Edinburgh Suburban"),
    ("WHS", "CRH",  3.0,  "Edinburgh Suburban"),
    # Waverley → Haymarket (main line west)
    ("EDB", "HYM",  2.5,  "Edinburgh Main"),
    # Haymarket → South Gyle → Edinburgh Gateway → Edinburgh Park
    ("HYM", "SGL",  4.0,  "Airport Line"),
    ("SGL", "EGY",  1.0,  "Airport Line"),
    ("EGY", "EDP",  0.5,  "Airport Line"),
    # Currie / South Gyle branch
    ("HYM", "WHS",  6.0,  "Shotts Line"),
    ("WHS", "CRH",  3.0,  "Shotts Line"),
    # Firth of Forth / Dalmeny
    ("HYM", "DEM",  8.0,  "Fife Circle"),
    ("DEM", "LIN",  7.5,  "Fife Circle"),
    # Waverley → East (Brunstane / Newcraighall / Musselburgh)
    ("EDB", "BRS",  6.0,  "East Suburban"),
    ("BRS", "NCR",  1.5,  "East Suburban"),
    ("NCR", "MUS",  3.0,  "East Coast"),
    ("MUS", "NBW", 30.0,  "North Berwick Line"),
    # ── ECML south ────────────────────────────────────────────────────────────
    ("EDB", "NCL", 170.0, "ECML"),
    ("NCL", "YRK",  80.0, "ECML"),
    ("YRK", "LDS",  32.0, "ECML"),
    ("LDS", "BHM", 165.0, "Cross-Country"),
    ("BHM", "LBG", 190.0, "West Coast Main Line"),
    # ── Glasgow lines ─────────────────────────────────────────────────────────
    ("LIN", "FKH",  8.5,  "Edinburgh–Glasgow QL"),
    ("FKH", "GLQ", 19.0,  "Edinburgh–Glasgow QL"),
    ("FKH", "PBR",  2.5,  "Polmont Branch"),
    ("PBR", "GRN",  2.5,  "Grangemouth Branch"),
    ("GLQ", "GLC",  0.8,  "Glasgow City"),
    ("GLQ", "MAN", 340.0, "West Coast Main Line"),  # via Preston
    # ── Central Scotland ──────────────────────────────────────────────────────
    ("GLQ", "STG",  40.0, "Stirling Line"),
    ("STG", "DBL",   7.0, "Stirling Line"),
    ("DBL", "PTH",  56.0, "Highland Main"),
    ("PTH", "DEE",  32.0, "East Coast Main"),
    ("DEE", "LRH",  19.0, "East Coast Main"),
    ("LRH", "ABD",  79.0, "East Coast Main"),
    # ── Fife / Kirkcaldy (separate from Perth path) ───────────────────────────
    ("DEM", "KKD", 26.0,  "Fife Circle"),
    ("KKD", "DND", 35.0,  "East Coast Main"),
    ("DND", "ABD", 98.0,  "East Coast Main"),
    # ── Highlands ─────────────────────────────────────────────────────────────
    ("GLQ", "IVR", 190.0, "Highland Main"),
    ("IVR", "WCK", 109.0, "Far North Line"),
    ("WCK", "THS",  19.0, "Far North Line"),
    ("IVR", "IVB",  50.0, "Far North Line"),
    ("IVR", "KYL",  82.0, "Kyle of Lochalsh Line"),
    # ── West Highland ─────────────────────────────────────────────────────────
    ("GLQ", "CRN",  75.0, "West Highland Line"),
    ("CRN", "FTW",  38.0, "West Highland Line"),
    ("FTW", "MLG",  66.0, "West Highland Line (Mallaig Extension)"),
    ("CRN", "OBN",  49.0, "Oban Line"),
    # ── ABD → IVR (Inverness via Aberdeen corridor) ───────────────────────────
    ("ABD", "IVR",  69.0, "Aberdeen–Inverness"),
]


# ─────────────────────────────────────────────────────────────────────────────
# GRAPH BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def build_rail_spine_graph():
    """
    Build a NetworkX MultiDiGraph of the Edinburgh / UK rail spine.

    Node attributes: x (lon), y (lat), name, type
    Edge attributes: length (m), distance_km, line_name, gen_cost (stub)
    """
    if not _NX_AVAILABLE:
        return None

    G = nx.MultiDiGraph()

    for crs, info in STATIONS.items():
        G.add_node(
            crs,
            x=info["lon"],
            y=info["lat"],
            name=info["name"],
            station_type=info["type"],
            railway="station",
        )

    for src, dst, dist_km, line in TRACK_EDGES:
        if src not in G.nodes or dst not in G.nodes:
            logger.warning("Rail spine: unknown station in edge %s→%s", src, dst)
            continue
        length_m = dist_km * 1000
        # Add both directions (rail is bidirectional for passenger service)
        for u, v in ((src, dst), (dst, src)):
            G.add_edge(
                u, v,
                length=length_m,
                distance_km=dist_km,
                line_name=line,
                highway="rail",     # so _apply_generalised_weights can parse it
                gen_cost=dist_km,   # stub — router overwrites this
            )

    logger.info(
        "Rail spine built: %d stations, %d directed edges",
        G.number_of_nodes(), G.number_of_edges(),
    )
    return G


# ─────────────────────────────────────────────────────────────────────────────
# STATION LOOKUP
# ─────────────────────────────────────────────────────────────────────────────

def _haversine(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Haversine distance in km."""
    R = 6371.0
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a  = (math.sin(dp / 2) ** 2
          + math.cos(math.radians(lat1))
          * math.cos(math.radians(lat2))
          * math.sin(dl / 2) ** 2)
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def nearest_station(
    coord: Tuple[float, float],
    station_types: Optional[List[str]] = None,
    max_distance_km: float = 50.0,
) -> Optional[str]:
    """
    Return the CRS code of the nearest station to (lon, lat) coord.

    Args:
        coord:            (lon, lat)
        station_types:    If set, only consider stations of these types.
                          e.g. ['major', 'suburban'] to exclude freight junctions.
        max_distance_km:  Return None if nearest is further than this.

    Returns:
        CRS string or None.
    """
    lon, lat = coord
    best_crs  = None
    best_dist = float('inf')

    for crs, info in STATIONS.items():
        if station_types and info.get("type") not in station_types:
            continue
        d = _haversine(lon, lat, info["lon"], info["lat"])
        if d < best_dist:
            best_dist = d
            best_crs  = crs

    if best_crs is None or best_dist > max_distance_km:
        return None
    return best_crs


def station_coord(crs: str) -> Optional[Tuple[float, float]]:
    """Return (lon, lat) for a station CRS, or None."""
    info = STATIONS.get(crs)
    if info is None:
        return None
    return (info["lon"], info["lat"])


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE-VIA-STATIONS
# The core function used by bdi_planner when generating abstract rail routes.
# ─────────────────────────────────────────────────────────────────────────────

_PASSENGER_TYPES = ['major', 'suburban', 'interchange', 'regional', 'intercity_stop']
_INTERCITY_TYPES  = ['major', 'intercity_stop']


def route_via_stations(
    origin: Tuple[float, float],
    dest: Tuple[float, float],
    mode: str = 'local_train',
) -> List[Tuple[float, float]]:
    """
    Build a realistic rail route as a list of (lon, lat) waypoints.

    Strategy:
      1. Find nearest passenger station to origin  (origin_station)
      2. Find nearest passenger station to dest    (dest_station)
      3. If a NetworkX spine is available, find intermediate stations
         on the shortest path.
      4. Return  [origin, origin_station, ...intermediates..., dest_station, dest]

    The resulting multi-point polyline renders on the map as a route that
    bends through real station locations — far more realistic than a single
    diagonal line — without needing the full OpenRailMap graph to be loaded.

    For local_train / tram: prefer nearby suburban stations.
    For intercity_train:    prefer major/intercity stations.
    """
    # Tram mode — delegate to dedicated tram stop routing.
    # Returns None when origin/dest are outside the tram corridor catchment
    # (>1.5km from any stop).  Callers must handle None.
    if mode == 'tram':
        return route_via_tram_stops(origin, dest, max_access_km=2.5)

    # Select station types based on mode
    if mode in ('intercity_train', 'freight_rail'):
        s_types = _INTERCITY_TYPES
    else:
        s_types = _PASSENGER_TYPES

    origin_crs = nearest_station(origin, station_types=s_types)
    dest_crs   = nearest_station(dest,   station_types=s_types)

    if origin_crs is None or dest_crs is None:
        # No stations found within range — return bare straight line
        logger.debug(
            "route_via_stations: no stations found for %s → %s, bare line",
            origin, dest,
        )
        return [origin, dest]

    origin_stn = station_coord(origin_crs)
    dest_stn   = station_coord(dest_crs)

    if origin_crs == dest_crs:
        # Origin and destination are in the same station catchment — short trip
        return [origin, origin_stn, dest]

    # ── Try to route through intermediate stations on the spine graph ─────────
    intermediate_coords: List[Tuple[float, float]] = []

    if _NX_AVAILABLE:
        G = _get_or_build_spine()
        if G is not None and origin_crs in G and dest_crs in G:
            try:
                path_nodes = nx.shortest_path(G, origin_crs, dest_crs, weight='distance_km')
                # Only include intermediate nodes (skip first and last — we add explicitly)
                for crs in path_nodes[1:-1]:
                    coord = station_coord(crs)
                    if coord:
                        intermediate_coords.append(coord)
                logger.debug(
                    "route_via_stations %s→%s via %s: %d intermediates",
                    origin_crs, dest_crs,
                    ' → '.join(path_nodes),
                    len(intermediate_coords),
                )
            except nx.NetworkXNoPath:
                logger.debug(
                    "route_via_stations: no spine path %s→%s",
                    origin_crs, dest_crs,
                )
            except Exception as exc:
                logger.debug("route_via_stations spine error: %s", exc)

    return [origin, origin_stn] + intermediate_coords + [dest_stn, dest]


# ─────────────────────────────────────────────────────────────────────────────
# MODULE-LEVEL SPINE GRAPH CACHE
# ─────────────────────────────────────────────────────────────────────────────
_spine_graph = None


def _get_or_build_spine():
    """Return cached spine graph, building it on first call."""
    global _spine_graph
    if _spine_graph is None:
        _spine_graph = build_rail_spine_graph()
    return _spine_graph


def get_spine_graph():
    """Public accessor — returns the rail spine as a NetworkX graph."""
    return _get_or_build_spine()


def get_station_pydeck_data() -> List[Dict]:
    """
    Return station list as pydeck-compatible dicts for the station icon layer.

    Each dict has: lon, lat, name, type, tooltip_html
    """
    data = []
    for crs, info in STATIONS.items():
        s_type = info.get("type", "suburban")
        type_emoji = {
            "major":           "🚉",
            "interchange":     "🔄",
            "suburban":        "🚊",
            "regional":        "🚆",
            "intercity_stop":  "🚄",
            "freight_junction": "🚂",
        }.get(s_type, "🚉")

        data.append({
            "lon":     info["lon"],
            "lat":     info["lat"],
            "name":    info["name"],
            "crs":     crs,
            "type":    s_type,
            "tooltip_html": (
                f"<b>{type_emoji} {info['name']}</b><br/>"
                f"CRS: {crs}<br/>"
                f"Type: {s_type.replace('_', ' ').title()}"
                + ("<br/>🚋 Tram interchange" if info.get("tram_link") else "")
            ),
        })
    return data


# ─────────────────────────────────────────────────────────────────────────────
# NAPTAN BRIDGE
# Provide a unified interface: use live NaPTAN data when available;
# fall back to the hardcoded STATIONS dict when offline or in tests.
# ─────────────────────────────────────────────────────────────────────────────

_naptan_stops: Optional[List] = None   # cached after first load
_naptan_loaded: bool = False


def get_transfer_nodes(
    bbox: Optional[Tuple[float, float, float]] = None,
    force_spine: bool = False,
) -> List[Dict]:
    """
    Return transfer nodes for the intermodal router.

    Attempts to load NaPTAN rail stops (DfT open data, ~2,500 UK stations).
    Falls back to the 25-station hardcoded spine when NaPTAN is unavailable.

    Args:
        bbox:        Optional (north, south, east, west) filter.
        force_spine: If True, bypass NaPTAN and use the hardcoded spine only.
                     Useful in unit tests and offline environments.

    Returns:
        List of dicts: {lon, lat, name, crs, stop_type, atco_code}
    """
    global _naptan_stops, _naptan_loaded

    if force_spine or _naptan_loaded is False:
        if not force_spine:
            try:
                from simulation.spatial.naptan_loader import build_transfer_nodes
                nodes = build_transfer_nodes(bbox=bbox)
                if nodes:
                    _naptan_stops = nodes
                    _naptan_loaded = True
                    logger.info(
                        "Transfer nodes: %d NaPTAN stops loaded", len(nodes)
                    )
                    return nodes
            except Exception as exc:
                logger.debug("NaPTAN load failed (%s) — using spine", exc)

        # Hardcoded spine fallback
        spine_nodes = [
            {
                'lon':       info['lon'],
                'lat':       info['lat'],
                'name':      info['name'],
                'crs':       crs,
                'stop_type': 'RLY',
                'atco_code': crs,
            }
            for crs, info in STATIONS.items()
        ]
        _naptan_stops = spine_nodes
        _naptan_loaded = True
        logger.debug(
            "Transfer nodes: using hardcoded spine (%d stations)", len(spine_nodes)
        )
        return spine_nodes

    # Already loaded
    nodes = _naptan_stops or []
    if bbox:
        north, south, east, west = bbox
        nodes = [
            n for n in nodes
            if south <= n['lat'] <= north and west <= n['lon'] <= east
        ]
    return nodes


def nearest_transfer_node(
    coord: Tuple[float, float],
    bbox: Optional[Tuple] = None,
    max_km: float = 50.0,
) -> Optional[Dict]:
    """
    Return the nearest transfer node (station) to (lon, lat) coord.
 
    Used by the Router to snap an agent's origin/destination to a station
    before computing the rail leg of an intermodal route.
 
    Args:
        coord:   (lon, lat).
        bbox:    Optional spatial filter passed to get_transfer_nodes.
        max_km:  Return None if nearest node is further than this.
    """
    nodes = get_transfer_nodes(bbox=bbox)
    if not nodes:
        return None
 
    lon, lat = coord
    best = None
    best_dist = float('inf')
    for node in nodes:
        d = _haversine(lon, lat, node['lon'], node['lat'])
        if d < best_dist:
            best_dist = d
            best = node
 
    return best if best_dist <= max_km else None