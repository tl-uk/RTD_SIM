"""
simulation/spatial/air_network.py

Air transport layer for RTD_SIM.

STATUS: Foundation module — Phase 10c.
  Passenger simulation (domestic_flight, flight_electric) uses this module.
  Freight air simulation (freight_air) is planned for Phase 12.

DATA SOURCES
────────────
Primary: OpenAIP REST API (https://api.core.openaip.net)
  • Airport positions, ICAO codes, runway counts, elevation
  • Registration required (free tier: 1,000 req/day)
  • Set OPENAIP_API_KEY in .env to enable

Secondary: OpenAviationMap (OAM) / OurAirports CSV
  • OurAirports: https://ourairports.com/data/airports.csv
  • No API key required; 67,000 airports worldwide
  • Filtered to UK (iso_country='GB') by default

Fallback: Hardcoded UK airport spine (_UK_AIRPORTS)
  • 35 UK airports with ICAO codes and coordinates
  • Always available, offline-safe

Airway routing
──────────────
Aviation does not use OSMnx road graphs.  All flight paths are computed
as great-circle arcs between airport nodes.  The BDI router calls:

    route = compute_flight_route(origin_coord, dest_coord, mode)

which returns a great-circle polyline (30 points by default) that can be
rendered on the map.  This is semantically correct: commercial aircraft
follow great-circle routes at altitude, not road networks.

Modes handled:
    flight_domestic   — short/medium haul, speed 700 km/h
    flight_electric   — emerging eVTOL/electric short-haul, speed 400 km/h
    freight_air       — air freight, same routing as flight_domestic

BDI integration
───────────────
    from simulation.spatial.air_network import (
        get_or_build_airport_graph,
        compute_flight_route,
        snap_to_airport,
    )

    G_air = get_or_build_airport_graph(bbox)
    route = compute_flight_route(origin, dest, 'flight_domestic')

Visualisation
─────────────
Flight paths are rendered as dashed arcs (great-circle curves) in a pydeck
ArcLayer or PathLayer.  Use get_flight_arc_data(routes) to format them.
Colour convention:
    flight_domestic  → [220, 100, 30, 180]   amber
    flight_electric  → [80,  200, 80, 180]   green
    freight_air      → [180, 80,  80, 180]   red

OpenAviationMap / OpenAIP note
──────────────────────────────
OpenAIP (https://www.openaip.net) is the most comprehensive open aviation
dataset, covering:
  • Airports (position, ICAO, type: civil/military/glider/helipad)
  • Airspaces (CTR, TMA, Class A-G)
  • Navigation aids (VOR, NDB, DME)
  • Reporting points
  • Obstacles

OpenAviationMap (https://openavitaionmap.org) is a Mapbox/Leaflet viewer
over the same data.  For programmatic access, use the OpenAIP REST API or
the OurAirports CSV dataset (no key needed).

For RTD_SIM Phase 12 (freight, airspace constraints), add:
  • Airspace polygon layer (CTR, TMA avoidance)
  • ATC sector boundaries
  • Restricted zones (danger areas, military)
"""

from __future__ import annotations

import csv
import io
import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import networkx as nx
    _NX = True
except ImportError:
    _NX = False

try:
    import requests as _requests
    _REQUESTS = True
except ImportError:
    _REQUESTS = False

# ─── Cache ────────────────────────────────────────────────────────────────────
CACHE_ROOT = Path.home() / ".rtd_sim_cache" / "transport"
CACHE_ROOT.mkdir(parents=True, exist_ok=True)
CACHE_TTL_H = 72.0   # Airport positions change rarely — 3-day cache

_OURAIRPORTS_URL = "https://ourairports.com/data/airports.csv"
_OPENAIP_BASE    = "https://api.core.openaip.net/api"


def _cache_stale(path: Path, ttl_h: float = CACHE_TTL_H) -> bool:
    if not path.exists():
        return True
    return (time.time() - path.stat().st_mtime) / 3600 > ttl_h


# ─── Hardcoded UK airport spine ───────────────────────────────────────────────
# (icao, name, lon, lat, airport_type)
# Types: 'large_airport', 'medium_airport', 'small_airport', 'heliport'
_UK_AIRPORTS: List[Tuple] = [
    # Scotland
    ("EGPH", "Edinburgh Airport",         -3.3725, 55.9500, "large_airport"),
    ("EGPF", "Glasgow Airport",           -4.4331, 55.8719, "large_airport"),
    ("EGPN", "Dundee Airport",            -3.0258, 56.4525, "medium_airport"),
    ("EGPE", "Inverness Airport",         -4.0475, 57.5425, "medium_airport"),
    ("EGPD", "Aberdeen Airport",          -2.1978, 57.2019, "large_airport"),
    ("EGPC", "Wick Airport",              -3.0931, 58.4589, "small_airport"),
    ("EGPU", "Tiree Airport",             -6.8692, 56.4994, "small_airport"),
    ("EGPM", "Scatsta Airport",           -1.2961, 60.4328, "small_airport"),
    ("EGPB", "Sumburgh Airport",          -1.2956, 59.8789, "medium_airport"),
    ("EGPA", "Kirkwall Airport",          -2.9050, 58.9578, "medium_airport"),
    ("EGPK", "Prestwick Airport",         -4.5867, 55.5094, "large_airport"),
    # England
    ("EGLL", "London Heathrow",           -0.4543, 51.4775, "large_airport"),
    ("EGKK", "London Gatwick",            -0.1903, 51.1481, "large_airport"),
    ("EGSS", "London Stansted",            0.2350, 51.8850, "large_airport"),
    ("EGGW", "London Luton",              -0.3683, 51.8747, "large_airport"),
    ("EGCC", "Manchester Airport",        -2.2750, 53.3537, "large_airport"),
    ("EGBB", "Birmingham Airport",        -1.7481, 52.4539, "large_airport"),
    ("EGNX", "East Midlands Airport",     -1.3281, 52.8311, "large_airport"),
    ("EGGD", "Bristol Airport",           -2.7191, 51.3827, "large_airport"),
    ("EGHI", "Southampton Airport",       -1.3578, 50.9503, "medium_airport"),
    ("EGNH", "Blackpool Airport",         -3.0286, 53.7733, "medium_airport"),
    ("EGNJ", "Humberside Airport",        -0.3508, 53.5744, "medium_airport"),
    ("EGNM", "Leeds Bradford Airport",    -1.6606, 53.8659, "medium_airport"),
    ("EGNT", "Newcastle Airport",         -1.6917, 54.9933, "large_airport"),
    ("EGNO", "Warton Aerodrome",          -2.8833, 53.7453, "medium_airport"),
    # Wales
    ("EGFF", "Cardiff Airport",           -3.3433, 51.3967, "large_airport"),
    ("EGOV", "Anglesey Airport",          -4.5350, 53.2481, "small_airport"),
    # Northern Ireland
    ("EGAA", "Belfast International",     -6.2158, 54.6575, "large_airport"),
    ("EGAC", "Belfast City Airport",      -5.8722, 54.6181, "medium_airport"),
    ("EGAD", "Newtownards Airport",       -5.6936, 54.5806, "small_airport"),
    # Channel Islands
    ("EGJJ", "Jersey Airport",            -2.1953, 49.2078, "medium_airport"),
    ("EGJB", "Guernsey Airport",          -2.6025, 49.4350, "medium_airport"),
    # Offshore
    ("EGPG", "Scone Airport",             -3.3717, 56.4428, "small_airport"),
    ("EGPR", "Barra Airport",             -7.4439, 57.0228, "small_airport"),  # beach runway
    ("EGPL", "Benbecula Airport",         -7.3628, 57.4814, "small_airport"),
]

# ICAO prefix ranges for UK filtering in OurAirports CSV
_UK_ICAO_PREFIXES = ('EG', 'EI')   # EG = UK, EI = Ireland (included for routing)
_UK_ISO_COUNTRIES = {'GB', 'GG', 'JE', 'IM', 'IE'}  # GB, Channel Islands, Isle of Man, Ireland


# ─── Geometry helpers ─────────────────────────────────────────────────────────

def _haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    R = 6371.0
    lon1, lat1 = math.radians(a[0]), math.radians(a[1])
    lon2, lat2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _great_circle_arc(
    origin: Tuple[float, float],
    dest: Tuple[float, float],
    n_points: int = 30,
) -> List[Tuple[float, float]]:
    """
    Spherical-linear interpolated great-circle arc.
    Returns n_points (lon, lat) tuples from origin to dest.
    """
    lon1, lat1 = math.radians(origin[0]), math.radians(origin[1])
    lon2, lat2 = math.radians(dest[0]), math.radians(dest[1])

    def to_xyz(lo, la):
        return (math.cos(la)*math.cos(lo), math.cos(la)*math.sin(lo), math.sin(la))

    x1, y1, z1 = to_xyz(lon1, lat1)
    x2, y2, z2 = to_xyz(lon2, lat2)
    dot = max(-1.0, min(1.0, x1*x2 + y1*y2 + z1*z2))
    omega = math.acos(dot)

    points = []
    for i in range(n_points):
        t = i / max(n_points - 1, 1)
        if omega < 1e-9:
            xi, yi, zi = x1, y1, z1
        else:
            s = math.sin(omega)
            a = math.sin((1 - t) * omega) / s
            b = math.sin(t * omega) / s
            xi, yi, zi = a*x1 + b*x2, a*y1 + b*y2, a*z1 + b*z2
        lat_i = math.degrees(math.atan2(zi, math.sqrt(xi**2 + yi**2)))
        lon_i = math.degrees(math.atan2(yi, xi))
        points.append((lon_i, lat_i))

    return points


# ─── Airport data sources ──────────────────────────────────────────────────────

def _fetch_ourairports(
    iso_countries: Optional[set] = None,
) -> List[Dict]:
    """
    Download OurAirports CSV and return a list of airport dicts.

    Filters to `iso_countries` (default: UK + Ireland).
    Each dict has: icao, name, lon, lat, airport_type, iso_country.
    Returns [] on failure (graceful — spine fallback covers UK airports).
    """
    import urllib.request

    # Only include types that are operationally meaningful for transport simulation.
    # OurAirports 'type' field values observed in UK data:
    #   large_airport, medium_airport, small_airport, heliport,
    #   closed, balloonport, seaplane_base
    # 'closed' airports (395 in UK) must be excluded — they are derelict sites that
    # generate massive scatter blobs and confuse the airport-snap router.
    # 'balloonport' and 'seaplane_base' are not relevant for RTD_SIM passenger/freight.
    _INCLUDE_TYPES = {
        'large_airport',    # 22 in UK — EGLL, EGCC, EGPH etc.
        'medium_airport',   # 81 in UK — regional airports
        'small_airport',    # included but filtered downstream by snap radius
        'heliport',         # included for completeness (offshore oil, hospitals)
    }
    _EXCLUDE_TYPES = {'closed', 'balloonport', 'seaplane_base'}
    countries = iso_countries or _UK_ISO_COUNTRIES
    try:
        with urllib.request.urlopen(_OURAIRPORTS_URL, timeout=30) as resp:
            content = resp.read().decode('utf-8', errors='replace')
    except Exception as exc:
        logger.warning("OurAirports fetch failed: %s", exc)
        return []

    airports = []
    try:
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            if row.get('iso_country') not in countries:
                continue
            atype = row.get('type', 'small_airport')
            if atype in _EXCLUDE_TYPES or atype not in _INCLUDE_TYPES:
                continue
            try:
                lon = float(row['longitude_deg'])
                lat = float(row['latitude_deg'])
            except (KeyError, ValueError):
                continue
            airports.append({
                'icao':         row.get('ident', ''),
                'name':         row.get('name', ''),
                'lon':          lon,
                'lat':          lat,
                'airport_type': atype,
                'iso_country':  row.get('iso_country', ''),
                'iata':         row.get('iata_code', ''),
                'elevation_ft': row.get('elevation_ft', ''),
            })
    except Exception as exc:
        logger.warning("OurAirports CSV parse error: %s", exc)
        return []

    logger.info(
        "✅ OurAirports: %d airports (UK/Ireland, excl. closed/balloonport/seaplane)",
        len(airports),
    )
    return airports


def _fetch_openaip(
    bbox: Optional[Tuple] = None,
    api_key: str = "",
) -> List[Dict]:
    """
    Fetch airport data from the OpenAIP REST API.

    Requires OPENAIP_API_KEY in environment.  Returns [] if key is absent
    or the API is unavailable — OurAirports is used as fallback.

    Endpoint: GET /api/airports
    Docs: https://docs.openaip.net

    Args:
        bbox:    (north, south, east, west) optional spatial filter.
        api_key: OpenAIP API key (or reads from OPENAIP_API_KEY env var).
    """
    key = api_key or os.getenv('OPENAIP_API_KEY', '')
    if not key:
        logger.debug("OpenAIP API key not set — skipping OpenAIP fetch")
        return []

    if not _REQUESTS:
        logger.debug("requests library not available — skipping OpenAIP fetch")
        return []

    params: Dict = {'page': 1, 'limit': 200, 'country': 'GB'}
    if bbox:
        north, south, east, west = bbox
        params.update({'bbox': f"{west},{south},{east},{north}"})

    headers = {'x-openaip-api-key': key}
    airports = []
    page = 1

    while True:
        params['page'] = page
        try:
            r = _requests.get(
                f"{_OPENAIP_BASE}/airports",
                params=params, headers=headers, timeout=20,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            logger.warning("OpenAIP page %d failed: %s", page, exc)
            break

        items = data.get('items', [])
        if not items:
            break

        for item in items:
            geo = item.get('geometry', {}).get('coordinates', [])
            if len(geo) < 2:
                continue
                
            # Safely extract type (OpenAIP often returns ints: 3 = heliport)
            raw_type = item.get('type')
            if isinstance(raw_type, dict):
                atype = raw_type.get('name', 'small_airport')
            elif isinstance(raw_type, int):
                atype = 'heliport' if raw_type == 3 else 'small_airport'
            else:
                atype = 'small_airport'

            # Safely extract country
            raw_country = item.get('country')
            if isinstance(raw_country, dict):
                country = raw_country.get('code', 'GB')
            elif isinstance(raw_country, str):
                country = raw_country
            else:
                country = 'GB'

            # Safely extract elevation
            raw_elev = item.get('elevation')
            if isinstance(raw_elev, dict):
                elev = str(raw_elev.get('value', ''))
            else:
                elev = str(raw_elev) if raw_elev is not None else ''

            airports.append({
                'icao':         item.get('icaoCode', ''),
                'name':         item.get('name', ''),
                'lon':          float(geo[0]),
                'lat':          float(geo[1]),
                'airport_type': atype,
                'iso_country':  country,
                'iata':         item.get('iataCode', ''),
                'elevation_ft': elev,
            })

        total = data.get('totalCount', len(airports))
        if len(airports) >= total:
            break
        page += 1

    logger.info("✅ OpenAIP: %d airports fetched", len(airports))
    return airports


def _build_airport_graph(airports: List[Dict]) -> 'nx.MultiDiGraph':
    """
    Build a NetworkX airport graph.

    Each node represents an airport.  Edges are NOT pre-computed — flight
    routes are computed on-demand by compute_flight_route() since any airport
    can serve as origin or destination and pre-computing all O×D pairs is
    infeasible for 300+ airports.

    Node attributes:
        x, y          — lon, lat
        icao          — ICAO code
        iata          — IATA code ('' if none)
        name          — airport name
        airport_type  — 'large_airport' | 'medium_airport' | 'small_airport' | 'heliport'
        iso_country   — ISO 3166-1 alpha-2
        elevation_ft  — elevation (string from CSV/API)
    """
    G = nx.MultiDiGraph()
    G.graph['name'] = 'air'

    for ap in airports:
        icao = ap.get('icao', '')
        if not icao:
            continue
        G.add_node(
            icao,
            x=ap['lon'], y=ap['lat'],
            icao=icao,
            iata=ap.get('iata', ''),
            name=ap['name'],
            airport_type=ap.get('airport_type', 'small_airport'),
            iso_country=ap.get('iso_country', ''),
            elevation_ft=str(ap.get('elevation_ft', '')),
        )

    logger.info("✅ Airport graph: %d airports", G.number_of_nodes())
    return G


def _spine_airports() -> List[Dict]:
    """Convert _UK_AIRPORTS spine to dicts compatible with _build_airport_graph."""
    return [
        {
            'icao':         icao,
            'name':         name,
            'lon':          lon,
            'lat':          lat,
            'airport_type': atype,
            'iso_country':  'GB',
            'iata':         '',
            'elevation_ft': '',
        }
        for icao, name, lon, lat, atype in _UK_AIRPORTS
    ]


# ─── Public API ───────────────────────────────────────────────────────────────

def get_or_build_airport_graph(
    bbox: Optional[Tuple] = None,
    city_tag: str = 'uk',
    use_cache: bool = True,
    openaip_key: str = "",
) -> 'nx.MultiDiGraph':
    """
    Return a NetworkX airport graph for the given region.

    Data source priority:
        1. GraphML cache (< 72 h old)
        2. OpenAIP REST API (if OPENAIP_API_KEY is set)
        3. OurAirports CSV (free, global)
        4. Hardcoded UK spine (_UK_AIRPORTS)

    Args:
        bbox:        (north, south, east, west) — optional spatial filter.
        city_tag:    Cache key prefix.
        use_cache:   Read/write on-disk GraphML cache.
        openaip_key: OpenAIP API key (falls back to OPENAIP_API_KEY env var).

    Returns:
        NetworkX MultiDiGraph with airport nodes, graph['name']='air'.
    """
    if not _NX:
        logger.error("NetworkX not available — airport graph cannot be built")
        return None

    cache_file = CACHE_ROOT / f"{city_tag}_airports.graphml"

    if use_cache and not _cache_stale(cache_file):
        try:
            G = nx.read_graphml(cache_file)
            G.graph['name'] = 'air'
            logger.info("✅ Airport graph (cache): %d airports", G.number_of_nodes())
            return G
        except Exception:
            pass

    # Try OpenAIP first (most accurate, requires key)
    airports = _fetch_openaip(bbox=bbox, api_key=openaip_key)

    # Fall back to OurAirports (free, no key)
    if not airports:
        airports = _fetch_ourairports()

    # Final fallback: hardcoded spine
    if not airports:
        logger.warning("All airport data sources failed — using hardcoded UK spine")
        airports = _spine_airports()

    G = _build_airport_graph(airports)

    if use_cache and G is not None and G.number_of_nodes() > 0:
        try:
            nx.write_graphml(G, cache_file)
        except Exception:
            pass

    return G


def snap_to_airport(
    coord: Tuple[float, float],
    G_air: 'nx.MultiDiGraph',
    max_km: float = 50.0,
    min_type: str = 'small_airport',
) -> Optional[str]:
    """
    Return the ICAO code of the nearest usable airport to coord (lon, lat).

    Filters airports by type hierarchy:
        large_airport > medium_airport > small_airport > heliport

    Args:
        coord:    (lon, lat).
        G_air:    Airport graph from get_or_build_airport_graph().
        max_km:   Maximum snap radius in km (default 50 km).
        min_type: Minimum airport type to include.

    Returns:
        ICAO code string, or None if no airport within max_km.
    """
    _type_rank = {
        'large_airport':  4,
        'medium_airport': 3,
        'small_airport':  2,
        'heliport':       1,
    }
    min_rank = _type_rank.get(min_type, 1)

    lon, lat = coord
    best_icao = None
    best_dist = float('inf')

    for icao, data in G_air.nodes(data=True):
        atype = data.get('airport_type', 'small_airport')
        if _type_rank.get(atype, 0) < min_rank:
            continue
        alon = float(data.get('x', 0))
        alat = float(data.get('y', 0))
        dist = _haversine_km((lon, lat), (alon, alat))
        if dist < best_dist:
            best_dist = dist
            best_icao = icao

    return best_icao if best_dist <= max_km else None


def compute_flight_route(
    origin: Tuple[float, float],
    dest: Tuple[float, float],
    mode: str = 'flight_domestic',
    G_air: Optional['nx.MultiDiGraph'] = None,
    n_arc_points: int = 30,
    snap_to_airports: bool = True,
    snap_max_km: float = 50.0,
) -> List[Tuple[float, float]]:
    """
    Compute a great-circle flight route between origin and dest.

    If G_air is provided and snap_to_airports=True, the route is
    snapped to the nearest airport at each end.  This gives the
    visualiser a route like:
        origin → origin_airport → [30 arc points] → dest_airport → dest

    For abstract modes (flight_domestic, flight_electric) this is correct
    behaviour: the agent drives/walks to the airport, flies, then drives/walks
    from the destination airport.  The BDI planner handles the access legs.

    Args:
        origin:           (lon, lat) agent origin.
        dest:             (lon, lat) agent destination.
        mode:             'flight_domestic' | 'flight_electric' | 'freight_air'.
        G_air:            Airport graph.  None → route is origin→dest arc.
        n_arc_points:     Number of great-circle arc interpolation points.
        snap_to_airports: Snap endpoints to nearest airport.
        snap_max_km:      Snap radius (km).

    Returns:
        List of (lon, lat) tuples.
    """
    # Determine airport type preference by mode
    min_type = 'small_airport' if mode == 'flight_electric' else 'medium_airport'

    orig_airport = None
    dest_airport = None

    if G_air is not None and snap_to_airports:
        orig_icao = snap_to_airport(origin, G_air, max_km=snap_max_km, min_type=min_type)
        dest_icao = snap_to_airport(dest,   G_air, max_km=snap_max_km, min_type=min_type)

        if orig_icao and orig_icao in G_air:
            d = G_air.nodes[orig_icao]
            orig_airport = (float(d['x']), float(d['y']))

        if dest_icao and dest_icao in G_air:
            d = G_air.nodes[dest_icao]
            dest_airport = (float(d['x']), float(d['y']))

    arc_origin = orig_airport if orig_airport else origin
    arc_dest   = dest_airport if dest_airport else dest

    dist_km = _haversine_km(arc_origin, arc_dest)
    if dist_km < 10.0:
        # Very short flight (< 10 km) — straight line; don't waste arc points
        arc = [arc_origin, arc_dest]
    else:
        arc = _great_circle_arc(arc_origin, arc_dest, n_points=n_arc_points)

    # Full route: origin → airport → arc → airport → dest
    route: List[Tuple[float, float]] = []
    if orig_airport and orig_airport != origin:
        route.append(origin)
    route.extend(arc)
    if dest_airport and dest_airport != dest:
        route.append(dest)

    logger.debug(
        "Flight route %s→%s (%s): %.0f km arc, %d pts",
        orig_icao if orig_airport else 'origin',
        dest_icao if dest_airport else 'dest',
        mode, dist_km, len(route),
    )
    return route


# ─── Visualisation helpers ────────────────────────────────────────────────────

_FLIGHT_COLOURS = {
    'flight_domestic':  [220, 100, 30,  180],  # amber
    'flight_electric':  [80,  200, 80,  180],  # green
    'freight_air':      [180, 80,  80,  180],  # red
}
_DEFAULT_FLIGHT_COLOUR = [220, 100, 30, 180]

_AIRPORT_SIZE = {
    'large_airport':  12,
    'medium_airport': 8,
    'small_airport':  5,
    'heliport':       4,
}


def get_airport_pydeck_data(G_air: 'nx.MultiDiGraph') -> List[Dict]:
    """
    Return airport nodes as pydeck-compatible dicts for a ScatterplotLayer.

    Each dict has: lon, lat, icao, name, airport_type, size, color, tooltip_html.
    """
    data = []
    for icao, d in G_air.nodes(data=True):
        atype = d.get('airport_type', 'small_airport')
        data.append({
            'lon':          float(d.get('x', 0)),
            'lat':          float(d.get('y', 0)),
            'icao':         icao,
            'iata':         d.get('iata', ''),
            'name':         d.get('name', icao),
            'airport_type': atype,
            'size':         _AIRPORT_SIZE.get(atype, 5),
            'color':        [40, 120, 200, 200],
            'tooltip_html': (
                f"<b>✈️ {d.get('name', icao)}</b><br/>"
                f"ICAO: {icao}"
                + (f" / IATA: {d.get('iata')}" if d.get('iata') else "")
                + f"<br/>Type: {atype.replace('_', ' ').title()}"
            ),
        })
    return data


def get_flight_arc_data(
    routes: List[Dict],
) -> List[Dict]:
    """
    Format flight routes for pydeck ArcLayer or PathLayer rendering.

    Input: list of dicts with keys 'path' (list of [lon,lat]) and 'mode'.
    Output: list of dicts for pydeck PathLayer.

    For ArcLayer, use source_position and target_position (first and last point).
    """
    formatted = []
    for r in routes:
        path  = r.get('path', r.get('route', []))
        mode  = r.get('mode', 'flight_domestic')
        color = _FLIGHT_COLOURS.get(mode, _DEFAULT_FLIGHT_COLOUR)
        if len(path) < 2:
            continue
        formatted.append({
            'path':             [[lon, lat] for lon, lat in path],
            'source_position':  list(path[0]),
            'target_position':  list(path[-1]),
            'color':            color,
            'mode':             mode,
            'name':             r.get('name', ''),
            'dashed':           True,
        })
    return formatted


# ─── Summary ──────────────────────────────────────────────────────────────────

def log_air_summary(G_air: 'nx.MultiDiGraph') -> None:
    if G_air is None:
        logger.info("Air graph: not loaded")
        return
    type_counts: Dict[str, int] = {}
    for _, d in G_air.nodes(data=True):
        t = d.get('airport_type', 'unknown')
        type_counts[t] = type_counts.get(t, 0) + 1
    logger.info(
        "✅ Airport graph: %d airports — %s",
        G_air.number_of_nodes(),
        ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in sorted(type_counts.items())),
    )