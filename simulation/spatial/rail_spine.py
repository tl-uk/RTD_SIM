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
}

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