"""
simulation/spatial/rail_spine.py

The UK Rail Spine — a lightweight hardcoded station graph kept in memory.

This provides two things:
  1. Realistic rail-via-station routing without needing OpenRailMap to be
     loaded (or when it fails).  Instead of a single diagonal line from
     origin to destination, agents travel origin → access_station →
     [intermediate stations] → egress_station → destination.

  2. A pre-seeded NetworkX graph of Edinburgh and intercity stations that
     the Router's intermodal logic can use as a starting point before the
     full OpenRailMap graph is available.

Edinburgh stations (per Network Rail / Scotrail):
  Waverley (EDB), Haymarket (HYM), Edinburgh Gateway (EGY),
  Edinburgh Park (EDP), South Gyle, Brunstane, Newcraighall,
  Kingsknowe, Slateford, Wester Hailes, Curriehill, Dalmeny,
  North Berwick (regional), Musselburgh (regional)

Intercity connections encoded:
  Edinburgh → Glasgow Queen St / Central (via Falkirk High / Polmont)
  Edinburgh → Dunfermline / Kirkcaldy (Fife Circle)
  Edinburgh → Dundee / Aberdeen (via Haymarket)
  Edinburgh → Newcastle / London KX (East Coast Main Line)
  Edinburgh → Inverness (Highland Main)
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


def _nearest_tram_stop(coord: Tuple[float, float]) -> Optional[str]:
    """Return the ID of the nearest Edinburgh tram stop to (lon, lat)."""
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
    return best_id


def route_via_tram_stops(
    origin: Tuple[float, float],
    dest: Tuple[float, float],
) -> List[Tuple[float, float]]:
    """
    Build a realistic Edinburgh tram route as a list of (lon, lat) waypoints.

    Strategy:
      1. Find nearest tram stop to origin.
      2. Find nearest tram stop to dest.
      3. Return [origin, stop_A, ...intermediate stops..., stop_B, dest]

    Since Edinburgh Trams is a single line, intermediate stops are simply
    all stops between stop_A and stop_B in the ordered TRAM_LINE sequence.

    If origin and destination are closest to the same stop, returns a
    direct walk [origin, dest] — too short for tram to be relevant.
    """
    origin_stop_id = _nearest_tram_stop(origin)
    dest_stop_id   = _nearest_tram_stop(dest)

    if origin_stop_id is None or dest_stop_id is None:
        return [origin, dest]

    if origin_stop_id == dest_stop_id:
        # Both ends snap to the same stop — trip too short for tram
        coord = _tram_stop_coord(origin_stop_id)
        return [origin, coord, dest] if coord else [origin, dest]

    # Find indices in the ordered stop list
    try:
        idx_a = _TRAM_STOP_ORDER.index(origin_stop_id)
        idx_b = _TRAM_STOP_ORDER.index(dest_stop_id)
    except ValueError:
        # Stop not in ordered list — fall back to just endpoints
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
    # ── Glasgow lines ─────────────────────────────────────────────────────────
    ("LIN", "FKH",  8.5,  "Edinburgh–Glasgow QL"),
    ("FKH", "GLQ", 19.0,  "Edinburgh–Glasgow QL"),
    ("FKH", "PBR",  2.5,  "Polmont Branch"),
    ("PBR", "GRN",  2.5,  "Grangemouth Branch"),
    ("GLQ", "GLC",  0.8,  "Glasgow City"),
    # ── Fife / Aberdeen ───────────────────────────────────────────────────────
    ("DEM", "KKD", 26.0,  "Fife Circle"),
    ("KKD", "DND", 35.0,  "East Coast Main"),
    ("DND", "ABD", 98.0,  "East Coast Main"),
    # ── Highlands ─────────────────────────────────────────────────────────────
    ("GLQ", "IVR",190.0,  "Highland Main"),
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
    # Tram mode — delegate to dedicated tram stop routing (Edinburgh tram line)
    if mode == 'tram':
        return route_via_tram_stops(origin, dest)

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