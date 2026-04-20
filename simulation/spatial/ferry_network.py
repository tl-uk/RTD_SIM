"""
simulation/spatial/ferry_network.py

Comprehensive maritime transport layer for RTD_SIM.

This module supersedes the ferry graph code that was embedded in rail_network.py
and transport_loader.py.  It provides a multi-source pipeline:

    Tier 1 — Overpass live fetch (primary)
    ──────────────────────────────────────
    Five parallel Overpass queries, each with a targeted timeout:
      A) route=ferry relations        — public passenger/vehicle ferries
      B) amenity=ferry_terminal       — terminal infrastructure (foot/motorcar tags)
      C) seamark:type shipping lanes  — Traffic Separation Schemes (TSS)
      D) harbour=yes, port=yes        — major port nodes
      E) Navigable waterways          — canals, rivers with boat=yes

    Each query runs independently so a timeout on one (e.g. seamark layer)
    doesn't prevent the others from completing.

    Tier 2 — Cached GraphML snapshot (fallback)
    ────────────────────────────────────────────
    ~/.rtd_sim_cache/transport/<city_tag>_ferry.graphml  (24 h TTL)

    Tier 3 — Hardcoded UK spine (last resort)
    ─────────────────────────────────────────
    build_hardcoded_ferry_graph() — covers all major UK ferry crossings with
    great-circle arc waypoints so routes render as smooth curves on the map.

Graph schema
────────────
All nodes:
    x, y              — lon, lat (OSMnx convention)
    name              — terminal/port name
    node_type         — 'terminal' | 'port' | 'harbour' | 'waypoint'
    foot              — True/False (foot passengers permitted)
    motorcar          — True/False (vehicles carried)
    osm_id            — original OSM node id (str)

Ferry edges:
    mode              — 'ferry_diesel' | 'ferry_electric' | 'ferry_roro'
    length            — great-circle distance in metres
    shape_coords      — list of (lon, lat) tuples (arc waypoints)
    name              — route/operator name
    operator          — operator string from OSM
    foot              — True/False
    motorcar          — True/False

Shipping-lane edges:
    mode              — 'shipping_lane'
    seamark_type      — 'separation_lane' | 'separation_zone' | 'separation_boundary'
                        'navigation_line' | 'recommended_track'
    length            — metres
    shape_coords      — polyline from Overpass geometry

Waterway edges:
    mode              — 'canal' | 'river'
    waterway          — OSM waterway tag value
    navigable         — True (only returned for boat=yes/ship=yes ways)
    length            — metres

BDI routing compatibility
─────────────────────────
Router._compute_ferry_route() snaps agent origin/destination to the nearest
ferry_terminal node using snap_to_ferry_terminal(), then routes via the graph.

Visualisation
─────────────
Shipping lanes are returned in the separate get_shipping_lane_data() helper
as a list of dicts for the pydeck LineLayer.  They are dashed by convention
(matching OpenSeaMap rendering): the visualiser should set getDashArray=[5,5].

Map rendering colour palette:
    ferry_diesel      → [0, 130, 110, 200]   teal
    ferry_electric    → [0, 180, 90, 200]    green
    ferry_roro        → [0, 80, 160, 200]    blue
    shipping_lane     → [100, 130, 200, 120] steel-blue, dashed
    canal             → [60, 150, 200, 180]  cyan
    river (navigable) → [80, 160, 220, 140]  light blue
"""

from __future__ import annotations

import json
import logging
import math
import time
# Import urllib sub-modules explicitly so both runtime and static type checkers
# (Pylance / pyright) recognise them.  'import urllib.request' alone causes
# Pylance to report "'request' is not a known attribute of module 'urllib'"
# because urllib's type stubs don't expose sub-modules as attributes; explicit
# 'from urllib import request/parse' resolves this cleanly.
from urllib import parse  as _urllib_parse
from urllib import request as _urllib_request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import networkx as nx
    _NX = True
except ImportError:
    _NX = False
    logger.warning("NetworkX not available — ferry_network cannot build graphs")

# ─── Cache ────────────────────────────────────────────────────────────────────
CACHE_ROOT = Path.home() / ".rtd_sim_cache" / "transport"
CACHE_ROOT.mkdir(parents=True, exist_ok=True)
CACHE_TTL_H = 24.0

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def _cache_stale(path: Path, ttl_h: float = CACHE_TTL_H) -> bool:
    if not path.exists():
        return True
    return (time.time() - path.stat().st_mtime) / 3600 > ttl_h


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
    n_points: int = 16,
) -> List[Tuple[float, float]]:
    """
    Interpolate n_points along a great-circle arc from origin to dest.

    Uses spherical linear interpolation (slerp) so arcs over long sea crossings
    (e.g. Aberdeen→Lerwick) curve correctly rather than appearing as straight lines.

    Args:
        origin, dest: (lon, lat) in decimal degrees.
        n_points:     Number of interpolation points (including endpoints).
    """
    lon1, lat1 = math.radians(origin[0]), math.radians(origin[1])
    lon2, lat2 = math.radians(dest[0]), math.radians(dest[1])

    # Convert to ECEF unit vectors
    def to_xyz(lo, la):
        return (math.cos(la) * math.cos(lo),
                math.cos(la) * math.sin(lo),
                math.sin(la))

    x1, y1, z1 = to_xyz(lon1, lat1)
    x2, y2, z2 = to_xyz(lon2, lat2)

    # Angular separation
    dot = max(-1.0, min(1.0, x1 * x2 + y1 * y2 + z1 * z2))
    omega = math.acos(dot)

    points: List[Tuple[float, float]] = []
    for i in range(n_points):
        t = i / max(n_points - 1, 1)
        if omega < 1e-9:
            xi, yi, zi = x1, y1, z1
        else:
            s = math.sin(omega)
            a = math.sin((1 - t) * omega) / s
            b = math.sin(t * omega) / s
            xi, yi, zi = a * x1 + b * x2, a * y1 + b * y2, a * z1 + b * z2

        lat_i = math.degrees(math.atan2(zi, math.sqrt(xi ** 2 + yi ** 2)))
        lon_i = math.degrees(math.atan2(yi, xi))
        points.append((lon_i, lat_i))

    return points


# ─── Overpass query helpers ───────────────────────────────────────────────────

def _overpass_post(
    query: str,
    timeout_s: int = 45,
    max_retries: int = 3,
    initial_delay: float = 2.0,
) -> Optional[dict]:
    """
    POST a query to the Overpass API with exponential backoff.

    HTTP 406 fix: Overpass requires the query as a URL-encoded form field
    named 'data':
        POST body:  data=<url-encoded query string>
        Content-Type: application/x-www-form-urlencoded
    Sending the raw query string as the body (without the 'data=' prefix)
    causes the server to return HTTP 406 Not Acceptable.

    Handles:
      HTTP 429 Too Many Requests — rate-limit; back off and retry
      HTTP 504 Gateway Timeout   — server busy; back off and retry
      HTTP 406 Not Acceptable    — encoding error; fails immediately
    """
    import random as _rand
    # Encode query as a proper HTML form field — required by Overpass API
    body = _urllib_parse.urlencode({'data': query}).encode('utf-8')

    for attempt in range(max_retries):
        try:
            req = _urllib_request.Request(
                _OVERPASS_URL,
                data=body,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with _urllib_request.urlopen(req, timeout=timeout_s + 5) as resp:
                status = getattr(resp, 'status', 200)
                raw    = resp.read()
                if status == 200:
                    return json.loads(raw)
                if status == 406:
                    logger.error(
                        "Overpass HTTP 406 — query encoding error; "
                        "body must be sent as data=<urlencoded> form field"
                    )
                    return None
                logger.warning(
                    "Overpass HTTP %d (attempt %d/%d)", status, attempt + 1, max_retries
                )
        except Exception as exc:
            msg = str(exc)
            is_rate_limit = '429' in msg
            is_timeout    = '504' in msg or 'timed out' in msg.lower()
            if attempt < max_retries - 1 and (is_rate_limit or is_timeout):
                delay  = initial_delay * (2 ** attempt)
                jitter = delay * 0.25 * (2 * _rand.random() - 1)
                wait   = max(1.0, delay + jitter)
                logger.warning(
                    "Overpass %s (attempt %d/%d) — retrying in %.1fs",
                    '429 rate-limit' if is_rate_limit else '504/timeout',
                    attempt + 1, max_retries, wait,
                )
                time.sleep(wait)
                continue
            logger.warning("Overpass POST failed: %s", exc)
            return None
    return None


def _node_coord_map(elements: list) -> Dict[int, Tuple[float, float]]:
    """Build {osm_node_id → (lon, lat)} from a flat elements list."""
    return {
        el["id"]: (float(el["lon"]), float(el["lat"]))
        for el in elements
        if el["type"] == "node" and "lon" in el and "lat" in el
    }


# ─── Query A: Public ferry routes ─────────────────────────────────────────────

def _fetch_ferry_routes(
    south: float, west: float, north: float, east: float,
) -> Optional[dict]:
    """
    Fetch route=ferry relations and ferry ways from Overpass.

    Returns raw Overpass JSON (elements list) or None on timeout.

    OSM tags captured:
        route=ferry     — public passenger/vehicle/freight ferry routes
        ferry=yes       — ways explicitly marked as ferry crossings
        motorcar=yes    — vehicle-carrying ferries
        foot=yes        — foot passenger ferries
    """
    query = (
        f"[out:json][timeout:40];"
        "(  "
        f"  relation[\"route\"=\"ferry\"]({south},{west},{north},{east});"
        f"  way[\"route\"=\"ferry\"]({south},{west},{north},{east});"
        f"  way[\"ferry\"=\"yes\"]({south},{west},{north},{east});"
        ");"
        "out body geom;"
    )
    return _overpass_post(query, timeout_s=40)


# ─── Query B: Ferry terminals ──────────────────────────────────────────────────

def _fetch_ferry_terminals(
    south: float, west: float, north: float, east: float,
) -> Optional[dict]:
    """
    Fetch ferry terminal nodes from Overpass.

    OSM tags captured:
        amenity=ferry_terminal  — official ferry terminal designations
        harbour=yes             — harbour areas (used as fallback terminal points)
        port=yes                — commercial ports

    Each terminal node records foot=yes/no and motorcar=yes/no so the
    router can filter by what the terminal/service permits.
    """
    query = (
        f"[out:json][timeout:25];"
        "("
        f"  node[\"amenity\"=\"ferry_terminal\"]({south},{west},{north},{east});"
        f"  node[\"harbour\"=\"yes\"]({south},{west},{north},{east});"
        f"  node[\"port\"=\"yes\"]({south},{west},{north},{east});"
        f"  node[\"waterway\"=\"dock\"]({south},{west},{north},{east});"
        ");"
        "out body;"
    )
    return _overpass_post(query, timeout_s=25)


# ─── Query C: Seamark / shipping lanes ─────────────────────────────────────────

def _fetch_shipping_lanes(
    south: float, west: float, north: float, east: float,
) -> Optional[dict]:
    """
    Fetch OpenSeaMap seamark data defining Traffic Separation Schemes (TSS).

    These are the dashed magenta/blue lines on nautical charts separating
    inbound and outbound commercial shipping.  They are not routable for
    passenger ferries but are visualised as reference layers.

    OSM/seamark tags captured:
        seamark:type=separation_lane      — the actual traffic lane
        seamark:type=separation_zone      — the separation zone between lanes
        seamark:type=separation_boundary  — lane boundary lines
        seamark:type=navigation_line      — recommended navigation tracks
        seamark:type=recommended_track    — deep-water recommended tracks

    Note: Seamark data is globally sparse in Overpass.  This query uses a
    wider bbox (additional 1.0° expansion) to capture TSS data for the North
    Sea, English Channel, and Irish Sea that affect UK ferry operations.
    """
    # Seamark data tends to be sparser — expand bbox more generously
    s2, w2, n2, e2 = south - 1.0, west - 1.0, north + 1.0, east + 1.0
    seamark_types = "|".join([
        "separation_lane",
        "separation_zone",
        "separation_boundary",
        "navigation_line",
        "recommended_track",
    ])
    query = (
        f"[out:json][timeout:30];"
        "("
        f"  way[\"seamark:type\"~\"^({seamark_types})$\"]({s2},{w2},{n2},{e2});"
        f"  relation[\"seamark:type\"~\"^({seamark_types})$\"]({s2},{w2},{n2},{e2});"
        ");"
        "out body geom;"
    )
    return _overpass_post(query, timeout_s=30)


# ─── Query D: Navigable waterways ─────────────────────────────────────────────

def _fetch_navigable_waterways(
    south: float, west: float, north: float, east: float,
) -> Optional[dict]:
    """
    Fetch navigable inland waterways from Overpass.

    OSM tags captured:
        waterway=canal          — commercial canals (Forth & Clyde, Union Canal etc.)
        waterway=river          — navigable rivers (only where boat=yes or ship=yes)
        waterway=lock           — canal/river locks (physical constraint nodes)
        waterway=dock           — docks/basins
        route=waterway          — named waterway route relations
    """
    query = (
        f"[out:json][timeout:25];"
        "("
        f"  way[\"waterway\"=\"canal\"]({south},{west},{north},{east});"
        f"  way[\"waterway\"=\"river\"][\"boat\"=\"yes\"]({south},{west},{north},{east});"
        f"  way[\"waterway\"=\"river\"][\"ship\"=\"yes\"]({south},{west},{north},{east});"
        f"  node[\"waterway\"=\"lock\"]({south},{west},{north},{east});"
        f"  node[\"waterway\"=\"lock_gate\"]({south},{west},{north},{east});"
        f"  way[\"waterway\"=\"dock\"]({south},{west},{north},{east});"
        ");"
        "out body geom;"
    )
    return _overpass_post(query, timeout_s=25)


# ─── Graph builders ───────────────────────────────────────────────────────────

class _NodeRegistry:
    """Deduplicate graph nodes by (lon, lat) rounded to 4 decimal places."""

    def __init__(self, G: 'nx.MultiDiGraph'):
        self.G = G
        self._index: Dict[Tuple, int] = {}
        self._counter = 0

    def get(
        self,
        lon: float,
        lat: float,
        name: str = "",
        node_type: str = "waypoint",
        foot: bool = True,
        motorcar: bool = False,
        osm_id: str = "",
    ) -> int:
        key = (round(lon, 4), round(lat, 4))
        if key in self._index:
            return self._index[key]
        nid = self._counter
        self._counter += 1
        self.G.add_node(
            nid, x=lon, y=lat, name=name,
            node_type=node_type, foot=foot, motorcar=motorcar, osm_id=osm_id,
        )
        self._index[key] = nid
        return nid


def _build_ferry_graph_from_overpass(
    route_data: Optional[dict],
    terminal_data: Optional[dict],
) -> 'nx.MultiDiGraph':
    """
    Build a ferry NetworkX MultiDiGraph from Overpass JSON.

    Processes route=ferry relations, ferry ways, and terminal nodes.
    Each ferry route gets:
        - A great-circle arc waypoint list (shape_coords) for smooth rendering
        - foot/motorcar tags from OSM
        - Bi-directional edges
    Terminal nodes are added with node_type='terminal'.
    """
    G = nx.MultiDiGraph()
    G.graph['name'] = 'ferry'
    reg = _NodeRegistry(G)

    # ── Terminal nodes first (highest precision) ───────────────────────────────
    terminal_coords: Dict[str, int] = {}   # name → node_id for snapping
    if terminal_data:
        for el in terminal_data.get('elements', []):
            if el.get('type') != 'node':
                continue
            try:
                lon = float(el['lon'])
                lat = float(el['lat'])
            except (KeyError, TypeError, ValueError):
                continue
            tags = el.get('tags', {})
            name = tags.get('name') or tags.get('operator', '')
            foot_ok = tags.get('foot', 'yes').lower() not in ('no', 'private')
            car_ok  = tags.get('motorcar', 'no').lower() in ('yes', 'designated')
            amenity = tags.get('amenity', tags.get('harbour', ''))

            node_type = (
                'terminal' if amenity == 'ferry_terminal'
                else 'harbour' if tags.get('harbour') == 'yes'
                else 'port'
            )
            nid = reg.get(lon, lat, name=name, node_type=node_type,
                          foot=foot_ok, motorcar=car_ok,
                          osm_id=str(el.get('id', '')))
            if name:
                terminal_coords[name.lower()] = nid

    # ── Ferry routes and ways ──────────────────────────────────────────────────
    added = 0
    if route_data:
        elements = route_data.get('elements', [])

        # Build node coordinate map from skel nodes
        node_coords = _node_coord_map(elements)

        for el in elements:
            etype = el.get('type')
            tags  = el.get('tags', {})

            # Determine ferry mode from OSM tags
            operator = tags.get('operator', '')
            name_tag = tags.get('name') or operator or ''
            foot_ok  = tags.get('foot', 'yes').lower() not in ('no', 'private')
            car_ok   = tags.get('motorcar', 'no').lower() in ('yes', 'designated', 'ferry')
            bicycle_ok = tags.get('bicycle', 'yes').lower() not in ('no', 'private')

            # Infer mode: vehicle ferries are 'ferry_roro', foot-only are 'ferry_diesel'
            if car_ok:
                mode = 'ferry_roro'
            else:
                mode = 'ferry_diesel'

            # ── Relations (route=ferry) ────────────────────────────────────────
            if etype == 'relation':
                # Collect all member way geometries in order
                all_coords: List[Tuple[float, float]] = []
                for member in el.get('members', []):
                    if member.get('type') != 'way':
                        continue
                    geom = member.get('geometry', [])
                    for pt in geom:
                        try:
                            all_coords.append((float(pt['lon']), float(pt['lat'])))
                        except (KeyError, TypeError):
                            continue

                if len(all_coords) < 2:
                    continue

                origin_coord = all_coords[0]
                dest_coord   = all_coords[-1]

                # Use great-circle arc for routes > 5 km (sea crossings)
                dist_km = _haversine_km(origin_coord, dest_coord)
                if dist_km > 5.0:
                    shape = _great_circle_arc(origin_coord, dest_coord, n_points=20)
                else:
                    shape = all_coords   # short crossing: use actual geometry

                u = reg.get(*origin_coord, name=name_tag, node_type='terminal',
                            foot=foot_ok, motorcar=car_ok)
                v = reg.get(*dest_coord,   name=name_tag, node_type='terminal',
                            foot=foot_ok, motorcar=car_ok)
                if u == v:
                    continue

                dist_m = dist_km * 1000
                for src, dst, shp in [(u, v, shape), (v, u, list(reversed(shape)))]:
                    G.add_edge(src, dst,
                               mode=mode, length=dist_m,
                               shape_coords=shp, name=name_tag,
                               operator=operator,
                               foot=foot_ok, motorcar=car_ok,
                               bicycle=bicycle_ok)
                added += 1

            # ── Ways (route=ferry or ferry=yes) ───────────────────────────────
            elif etype == 'way':
                # Prefer inline geometry from 'out body geom'; fall back to node map
                geom = el.get('geometry', [])
                if geom:
                    coords = [(float(pt['lon']), float(pt['lat']))
                              for pt in geom if 'lon' in pt and 'lat' in pt]
                else:
                    coords = [node_coords[n] for n in el.get('nodes', [])
                              if n in node_coords]

                if len(coords) < 2:
                    continue

                dist_km = _haversine_km(coords[0], coords[-1])
                shape   = (
                    _great_circle_arc(coords[0], coords[-1], n_points=12)
                    if dist_km > 2.0 else coords
                )
                u = reg.get(*coords[0], name=name_tag, node_type='terminal',
                            foot=foot_ok, motorcar=car_ok)
                v = reg.get(*coords[-1], name=name_tag, node_type='terminal',
                            foot=foot_ok, motorcar=car_ok)
                if u == v:
                    continue

                dist_m = dist_km * 1000
                for src, dst, shp in [(u, v, shape), (v, u, list(reversed(shape)))]:
                    G.add_edge(src, dst,
                               mode=mode, length=dist_m,
                               shape_coords=shp, name=name_tag,
                               operator=operator,
                               foot=foot_ok, motorcar=car_ok)
                added += 1

    logger.info(
        "✅ Ferry graph (Overpass): %d terminals/nodes, %d routes (%d directed edges)",
        G.number_of_nodes(), added, G.number_of_edges(),
    )
    return G


def _build_shipping_lane_graph(lane_data: Optional[dict]) -> 'nx.MultiDiGraph':
    """
    Build a separate NetworkX graph for OpenSeaMap shipping lanes.

    These are NOT used for passenger ferry routing.  They are returned as
    a separate layer ('shipping_lanes') for visualisation only — rendered
    as dashed steel-blue lines on the map (matching OpenSeaMap convention).

    Returns an empty graph (not None) on failure so callers don't need to
    check for None.
    """
    G = nx.MultiDiGraph()
    G.graph['name'] = 'shipping_lanes'

    if not lane_data:
        return G

    elements = lane_data.get('elements', [])
    node_coords = _node_coord_map(elements)

    reg = _NodeRegistry(G)
    added = 0

    for el in elements:
        if el.get('type') not in ('way', 'relation'):
            continue

        tags = el.get('tags', {})
        seamark_type = tags.get('seamark:type', 'separation_lane')
        name_tag     = tags.get('name', tags.get('seamark:name', ''))

        # Collect coordinates from inline geometry or node map
        geom = el.get('geometry', [])
        if geom:
            coords = [(float(pt['lon']), float(pt['lat']))
                      for pt in geom if 'lon' in pt and 'lat' in pt]
        else:
            coords = [node_coords[n] for n in el.get('nodes', [])
                      if n in node_coords]
        if el.get('type') == 'relation':
            # Flatten member way geometries
            coords = []
            for member in el.get('members', []):
                for pt in member.get('geometry', []):
                    try:
                        coords.append((float(pt['lon']), float(pt['lat'])))
                    except (KeyError, TypeError):
                        continue

        if len(coords) < 2:
            continue

        u = reg.get(*coords[0])
        v = reg.get(*coords[-1])
        if u == v:
            continue

        dist_m = _haversine_km(coords[0], coords[-1]) * 1000
        G.add_edge(u, v,
                   mode='shipping_lane',
                   seamark_type=seamark_type,
                   length=dist_m,
                   shape_coords=coords,
                   name=name_tag)
        added += 1

    logger.info("✅ Shipping lanes: %d segments", added)
    return G


def _build_waterway_graph(waterway_data: Optional[dict]) -> 'nx.MultiDiGraph':
    """
    Build a NetworkX graph for navigable inland waterways.

    Canals, navigable rivers, and their associated locks are all included.
    Lock nodes are tagged as infrastructure=lock so the router can model
    the time penalty of passing through a lock (approx 20–40 minutes each).
    """
    G = nx.MultiDiGraph()
    G.graph['name'] = 'waterways'

    if not waterway_data:
        return G

    elements = waterway_data.get('elements', [])
    node_coords = _node_coord_map(elements)

    reg = _NodeRegistry(G)
    lock_count = 0
    way_count  = 0

    for el in elements:
        etype = el.get('type')
        tags  = el.get('tags', {})

        if etype == 'node' and tags.get('waterway') in ('lock', 'lock_gate'):
            # Lock nodes — record as infrastructure constraint points
            try:
                lon, lat = float(el['lon']), float(el['lat'])
                reg.get(lon, lat,
                        name=tags.get('name', 'Lock'),
                        node_type='lock',
                        osm_id=str(el.get('id', '')))
                lock_count += 1
            except (KeyError, TypeError, ValueError):
                continue

        elif etype == 'way':
            waterway_type = tags.get('waterway', '')
            if waterway_type not in ('canal', 'river', 'dock'):
                continue

            geom = el.get('geometry', [])
            if geom:
                coords = [(float(pt['lon']), float(pt['lat']))
                          for pt in geom if 'lon' in pt and 'lat' in pt]
            else:
                coords = [node_coords[n] for n in el.get('nodes', [])
                          if n in node_coords]

            if len(coords) < 2:
                continue

            u = reg.get(*coords[0], node_type='harbour')
            v = reg.get(*coords[-1], node_type='harbour')
            if u == v:
                continue

            dist_m = _haversine_km(coords[0], coords[-1]) * 1000
            mode_label = 'canal' if waterway_type == 'canal' else 'river'

            for src, dst, shp in [(u, v, coords), (v, u, list(reversed(coords)))]:
                G.add_edge(src, dst,
                           mode=mode_label,
                           waterway=waterway_type,
                           navigable=True,
                           length=dist_m,
                           shape_coords=shp,
                           name=tags.get('name', ''))
            way_count += 1

    logger.info(
        "✅ Waterways: %d navigable ways, %d locks",
        way_count, lock_count,
    )
    return G


# ─── Hardcoded UK ferry spine ─────────────────────────────────────────────────

# (route_name, (origin_lon, origin_lat), (dest_lon, dest_lat), foot, motorcar)
_UK_FERRY_ROUTES: List[Tuple] = [
    # Irish Sea — Scotland
    ("Cairnryan–Belfast",           (-5.012, 55.003), (-5.930, 54.612), True,  True),
    ("Cairnryan–Larne",             (-5.012, 55.003), (-5.820, 54.858), True,  True),
    # Irish Sea — Wales / England
    ("Holyhead–Dublin",             (-4.620, 53.306), (-6.222, 53.341), True,  True),
    ("Holyhead–DunLaoghaire",       (-4.620, 53.306), (-6.135, 53.300), True,  True),
    ("Pembroke–Rosslare",           (-4.930, 51.673), (-6.340, 52.254), True,  True),
    ("Fishguard–Rosslare",          (-4.979, 51.994), (-6.340, 52.254), True,  True),
    ("Liverpool–Dublin",            (-3.002, 53.408), (-6.222, 53.341), True,  True),
    # English Channel
    ("Dover–Calais",                ( 1.357, 51.124), ( 1.850, 50.972), True,  True),
    ("Dover–Dunkirk",               ( 1.357, 51.124), ( 2.374, 51.038), True,  True),
    ("Newhaven–Dieppe",             ( 0.058, 50.793), ( 1.076, 49.920), True,  True),
    ("Portsmouth–Cherbourg",        (-1.105, 50.798), (-1.625, 49.645), True,  True),
    ("Portsmouth–Caen",             (-1.105, 50.798), (-0.362, 49.182), True,  True),
    ("Portsmouth–StMalo",           (-1.105, 50.798), (-2.026, 48.649), True,  True),
    ("Portsmouth–Santander",        (-1.105, 50.798), (-3.794, 43.463), True,  True),
    ("Plymouth–Roscoff",            (-4.143, 50.367), (-3.983, 48.724), True,  True),
    # North Sea
    ("Newcastle–Amsterdam",         (-1.594, 54.970), ( 4.900, 52.413), True,  True),
    ("Hull–Rotterdam",              (-0.200, 53.740), ( 4.460, 51.890), True,  True),
    ("Hull–Zeebrugge",              (-0.200, 53.740), ( 3.200, 51.330), True,  True),
    ("Harwich–HoekVanHolland",      ( 1.281, 51.947), ( 4.123, 51.978), True,  True),
    # Scottish Northern Isles (NorthLink / CalMac)
    ("Aberdeen–Lerwick",            (-2.079, 57.151), (-1.139, 60.153), True,  True),
    ("Aberdeen–Kirkwall",           (-2.079, 57.151), (-2.965, 58.988), True,  True),
    ("Scrabster–Stromness",         (-3.543, 58.613), (-3.295, 58.958), True,  True),
    ("Gill–Kirkwall",               (-2.920, 58.627), (-2.965, 58.988), True,  True),
    # Hebrides & West Scotland (CalMac)
    ("Ullapool–Stornoway",          (-5.157, 57.896), (-6.374, 58.209), True,  True),
    ("Oban–Craignure",              (-5.478, 56.413), (-5.698, 56.463), True,  True),
    ("Oban–Colonsay",               (-5.478, 56.413), (-6.188, 56.064), True,  True),
    ("Oban–Castlebay",              (-5.478, 56.413), (-7.493, 57.003), True,  True),
    ("Mallaig–Armadale",            (-5.827, 57.007), (-5.897, 57.068), True,  True),
    ("Tarbert–Portavadie",          (-5.409, 55.868), (-5.315, 55.877), True,  False),
    ("Gourock–Dunoon",              (-4.817, 55.963), (-4.924, 55.949), True,  True),
    ("Wemyss–Rothesay",             (-4.886, 55.874), (-5.053, 55.838), True,  True),
    ("Ardrossan–Brodick",           (-4.825, 55.641), (-5.141, 55.576), True,  True),
    ("Kennacraig–PortEllen",        (-5.488, 55.803), (-6.190, 55.633), True,  True),
    # Firth of Forth
    ("SouthQueensferry–NorthQF",    (-3.398, 55.990), (-3.393, 56.001), True,  False),
    # Isle of Wight
    ("Portsmouth–Fishbourne",       (-1.105, 50.798), (-1.124, 50.732), True,  True),
    ("Southampton–Cowes",           (-1.404, 50.897), (-1.297, 50.762), True,  False),
    ("Lymington–Yarmouth",          (-1.549, 50.775), (-1.499, 50.709), True,  True),
    # Isles of Scilly
    ("Penzance–StMarys",            (-5.534, 50.120), (-6.296, 49.919), True,  False),
    # Forth & Clyde / Union Canal (inland)
    ("ForthClyde–Falkirk",          (-3.783, 56.001), (-3.554, 55.993), True,  False),
]


def build_hardcoded_ferry_graph() -> 'nx.MultiDiGraph':
    """
    Build the hardcoded UK ferry spine as a NetworkX MultiDiGraph.

    All routes use great-circle arc interpolation (20 points) so they
    render as smooth curves on the map rather than straight diagonal lines.
    Bi-directional edges are added for every route.
    """
    if not _NX:
        return None

    G = nx.MultiDiGraph()
    G.graph['name'] = 'ferry'
    reg = _NodeRegistry(G)

    for route_name, (olon, olat), (dlon, dlat), foot_ok, car_ok in _UK_FERRY_ROUTES:
        origin  = (olon, olat)
        dest    = (dlon, dlat)
        dist_km = _haversine_km(origin, dest)

        # Use slerp arc for sea crossings > 5km; linear for short crossings
        arc = (
            _great_circle_arc(origin, dest, n_points=20)
            if dist_km > 5.0
            else [origin, dest]
        )

        u = reg.get(olon, olat, name=route_name.split('–')[0],
                    node_type='terminal', foot=foot_ok, motorcar=car_ok)
        v = reg.get(dlon, dlat, name=route_name.split('–')[-1],
                    node_type='terminal', foot=foot_ok, motorcar=car_ok)

        dist_m = dist_km * 1000
        mode   = 'ferry_roro' if car_ok else 'ferry_diesel'

        for src, dst, shp in [(u, v, arc), (v, u, list(reversed(arc)))]:
            G.add_edge(src, dst,
                       mode=mode, length=dist_m,
                       shape_coords=shp, name=route_name,
                       foot=foot_ok, motorcar=car_ok)

    logger.info(
        "✅ Ferry spine (hardcoded): %d terminals, %d routes (%d directed edges)",
        G.number_of_nodes(), len(_UK_FERRY_ROUTES), G.number_of_edges(),
    )
    return G


# ─── Public API ───────────────────────────────────────────────────────────────

def fetch_maritime_graphs(
    bbox: Tuple[float, float, float, float],   # (north, south, east, west)
    city_tag: str = "default",
    use_cache: bool = True,
) -> Dict[str, 'nx.MultiDiGraph']:
    """
    Download all maritime layers for the given bounding box.

    Runs four Overpass queries in parallel (ferry routes, terminals,
    shipping lanes, waterways).  Each query has its own timeout so one
    slow or failed query doesn't block the rest.

    Returns a dict with keys:
        'ferry'          — passenger/vehicle ferry graph
        'shipping_lanes' — OpenSeaMap TSS layer (visualisation only)
        'waterways'      — navigable inland waterways

    Falls back to hardcoded spine for 'ferry' if Overpass fails.
    Returns empty graphs (never None) for 'shipping_lanes' and 'waterways'
    if those queries fail.

    Args:
        bbox:             (north, south, east, west)
        city_tag:         Cache key prefix.
        use_cache:        Read/write GraphML cache.
        parallel_queries: Run Overpass queries in parallel threads (default True).
                          Set False in tests or offline mode.
    """
    ferry_cache  = CACHE_ROOT / f"{city_tag}_ferry.graphml"
    lanes_cache  = CACHE_ROOT / f"{city_tag}_shipping_lanes.graphml"
    water_cache  = CACHE_ROOT / f"{city_tag}_waterways.graphml"

    # ── Check cache ───────────────────────────────────────────────────────────
    result: Dict[str, 'nx.MultiDiGraph'] = {}

    if use_cache and not _cache_stale(ferry_cache):
        try:
            G = nx.read_graphml(ferry_cache)
            G.graph['name'] = 'ferry'
            result['ferry'] = G
            logger.info("✅ Ferry graph (cache): %d nodes, %d edges",
                        G.number_of_nodes(), G.number_of_edges())
        except Exception:
            pass

    if use_cache and not _cache_stale(lanes_cache):
        try:
            G = nx.read_graphml(lanes_cache)
            G.graph['name'] = 'shipping_lanes'
            result['shipping_lanes'] = G
            logger.info("✅ Shipping lanes (cache): %d segments", G.number_of_edges())
        except Exception:
            pass

    if use_cache and not _cache_stale(water_cache):
        try:
            G = nx.read_graphml(water_cache)
            G.graph['name'] = 'waterways'
            result['waterways'] = G
        except Exception:
            pass

    if len(result) == 3:
        return result

    # ── Live Overpass fetch ───────────────────────────────────────────────────
    north, south, east, west = bbox
    # Expand 0.5° for terminal capture
    s, w, n, e = south - 0.5, west - 0.5, north + 0.5, east + 0.5

    logger.info("🚢 Fetching maritime data (bbox=%.2f,%.2f,%.2f,%.2f)…", s, w, n, e)

    # Sequential queries with pauses between them to avoid Overpass 429 rate-limit.
    # The previous parallel approach fired 4 simultaneous requests which immediately
    # triggered 429 Too Many Requests on all but the first to arrive.
    # Each _overpass_post() already handles 429/504 with exponential backoff internally,
    # but inter-query pauses reduce the baseline hit rate significantly.
    _INTER_QUERY_PAUSE = 1.5  # seconds between query dispatches

    route_data    = None
    terminal_data = None
    lane_data     = None
    water_data    = None

    route_data = _fetch_ferry_routes(s, w, n, e)
    time.sleep(_INTER_QUERY_PAUSE)

    terminal_data = _fetch_ferry_terminals(s, w, n, e)
    time.sleep(_INTER_QUERY_PAUSE)

    lane_data = _fetch_shipping_lanes(s, w, n, e)
    time.sleep(_INTER_QUERY_PAUSE)

    water_data = _fetch_navigable_waterways(s, w, n, e)

    # ── Build graphs ──────────────────────────────────────────────────────────

    if 'ferry' not in result:
        has_routes = (route_data and
                      any(el.get('type') in ('way', 'relation')
                          for el in route_data.get('elements', [])))
        if has_routes:
            G_ferry = _build_ferry_graph_from_overpass(route_data, terminal_data)
        else:
            logger.warning(
                "⚠️ Overpass ferry query returned no routes — using hardcoded spine"
            )
            G_ferry = build_hardcoded_ferry_graph()

        result['ferry'] = G_ferry
        if use_cache and G_ferry is not None and G_ferry.number_of_nodes() > 1:
            try:
                nx.write_graphml(G_ferry, ferry_cache)
            except Exception:
                pass

    if 'shipping_lanes' not in result:
        G_lanes = _build_shipping_lane_graph(lane_data)
        result['shipping_lanes'] = G_lanes
        if use_cache and G_lanes.number_of_nodes() > 0:
            try:
                nx.write_graphml(G_lanes, lanes_cache)
            except Exception:
                pass

    if 'waterways' not in result:
        G_water = _build_waterway_graph(water_data)
        result['waterways'] = G_water
        if use_cache and G_water.number_of_nodes() > 0:
            try:
                nx.write_graphml(G_water, water_cache)
            except Exception:
                pass

    return result


# ─── Snapping helpers ─────────────────────────────────────────────────────────

def snap_to_ferry_terminal(
    coord: Tuple[float, float],
    G_ferry: 'nx.MultiDiGraph',
    max_km: float = 5.0,
    foot_required: bool = True,
    motorcar_required: bool = False,
) -> Optional[int]:
    """
    Return the graph node ID of the nearest ferry terminal to coord (lon, lat).

    Filters by foot/motorcar capability when required.
    Returns None if no terminal is within max_km.
    """
    lon, lat = coord
    best_node = None
    best_dist = float('inf')

    for nid, data in G_ferry.nodes(data=True):
        if data.get('node_type', 'waypoint') not in ('terminal', 'harbour', 'port'):
            continue
        if foot_required and not data.get('foot', True):
            continue
        if motorcar_required and not data.get('motorcar', False):
            continue

        nlon = float(data.get('x', 0))
        nlat = float(data.get('y', 0))
        dist = _haversine_km((lon, lat), (nlon, nlat))
        if dist < best_dist:
            best_dist = dist
            best_node = nid

    return best_node if best_dist <= max_km else None


# ─── Visualisation data helpers ───────────────────────────────────────────────

_SHIPPING_LANE_COLOURS = {
    'separation_lane':     [100, 130, 200, 140],
    'separation_zone':     [130, 110, 180, 100],
    'separation_boundary': [80,  110, 200, 160],
    'navigation_line':     [60,  160, 220, 140],
    'recommended_track':   [40,  180, 220, 120],
}
_DEFAULT_LANE_COLOUR = [100, 130, 200, 120]


def get_shipping_lane_data(G_lanes: 'nx.MultiDiGraph') -> List[Dict]:
    """
    Return pydeck-compatible dicts for the shipping-lane LineLayer.

    Each dict has:
        path       — list of [lon, lat] pairs (for pydeck PathLayer)
        color      — [R, G, B, A]
        seamark    — seamark:type string
        name       — route/lane name
        dashed     — True (always; lanes are rendered dashed by convention)

    Rendering note: pydeck PathLayer does not support native dashing.
    Render these as a separate LineLayer with getDashArray=[5, 5] or
    use a ScatterplotLayer for the endpoint markers.
    """
    rows = []
    for u, v, data in G_lanes.edges(data=True):
        shape = data.get('shape_coords', [])
        if len(shape) < 2:
            continue
        seamark = data.get('seamark_type', 'separation_lane')
        rows.append({
            'path':    [[lon, lat] for lon, lat in shape],
            'color':   _SHIPPING_LANE_COLOURS.get(seamark, _DEFAULT_LANE_COLOUR),
            'seamark': seamark,
            'name':    data.get('name', ''),
            'dashed':  True,
        })
    return rows


_FERRY_COLOURS = {
    'ferry_roro':    [0, 80,  160, 200],
    'ferry_diesel':  [0, 130, 110, 200],
    'ferry_electric':[0, 180, 90,  200],
}
_DEFAULT_FERRY_COLOUR = [0, 130, 110, 200]


def get_ferry_route_data(G_ferry: 'nx.MultiDiGraph') -> List[Dict]:
    """
    Return pydeck-compatible dicts for the ferry PathLayer.

    Each dict has:
        path         — list of [lon, lat] pairs
        color        — [R, G, B, A]
        mode         — 'ferry_diesel' | 'ferry_roro' | 'ferry_electric'
        name         — route name
        foot         — bool
        motorcar     — bool
    """
    seen: set = set()
    rows = []
    for u, v, data in G_ferry.edges(data=True):
        pair = (min(u, v), max(u, v))
        if pair in seen:
            continue
        seen.add(pair)
        shape = data.get('shape_coords', [])
        if len(shape) < 2:
            continue
        mode = data.get('mode', 'ferry_diesel')
        rows.append({
            'path':    [[lon, lat] for lon, lat in shape],
            'color':   _FERRY_COLOURS.get(mode, _DEFAULT_FERRY_COLOUR),
            'mode':    mode,
            'name':    data.get('name', ''),
            'foot':    data.get('foot', True),
            'motorcar':data.get('motorcar', False),
        })
    return rows


# ─── Legacy shim (used by rail_network.get_or_fallback_ferry_graph) ───────────

def get_or_fallback_ferry_graph(env=None) -> 'nx.MultiDiGraph':
    """
    Shim for backward compatibility with rail_network.get_or_fallback_ferry_graph.

    Preferred call is fetch_maritime_graphs()['ferry'].
    This shim derives the bbox from env and calls the new pipeline.
    """
    bbox = (61.0, 49.0, 6.0, -11.0)  # full UK default

    if env is not None:
        gm = getattr(env, 'graph_manager', None)
        if gm is not None:
            drive = gm.get_graph('drive')
            if drive is not None and len(drive.nodes) > 0:
                xs = [d['x'] for _, d in drive.nodes(data=True)]
                ys = [d['y'] for _, d in drive.nodes(data=True)]
                bbox = (max(ys), min(ys), max(xs), min(xs))

    city_tag = 'ferry_env'
    graphs = fetch_maritime_graphs(bbox, city_tag=city_tag)
    return graphs.get('ferry') or build_hardcoded_ferry_graph()