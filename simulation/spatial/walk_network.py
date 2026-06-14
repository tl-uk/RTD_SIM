"""
simulation/spatial/walk_network.py

Comprehensive pedestrian transport layer for RTD_SIM.

This module provides a multi-source pipeline for pedestrian infrastructure:
    Tier 1 — Overpass live fetch (primary), tiled to avoid 504 timeouts
    Tier 2 — Cached pickle snapshot (~72h TTL)

Tiled Overpass queries (Issue 3)
─────────────────────────────────
A single Overpass request for a 25km-radius disc (~2,000 km²) times out
consistently with HTTP 504.  This module divides the bbox into a grid of
smaller tiles, each targeted at ≤400 km² (reliably under 60s for dense
UK urban areas).  The tile count is computed dynamically from the bbox
area so it works for any UK city or region — from a dense 5km city centre
to a 50km rural county — without hardcoding grid dimensions.

Pickle cache (Issue 4)
───────────────────────
GraphML serialises list attributes (shape_coords) as strings.  When loaded
from cache, shape_coords is a string not a list → router geometry extraction
gets a string → len() returns character count not point count → falls back to
straight-line between nodes, causing walk routes to zigzag.

Fix: replace GraphML cache with pickle.  Pickle preserves all Python types
exactly.  Delete stale *_walk.graphml files from ~/.rtd_sim_cache/transport/
after upgrading — the next run will rebuild as *_walk.pkl.

Visual Representation & Rendering:
    In OSM, pedestrian infrastructure is often distinguished by dashed lines:
    - highway=footway   → Salmon/Pink dashed lines (standard pedestrian paths)
    - highway=path      → Dark brown dashed lines (multi-use/unpaved)
    - highway=steps     → Ladder/Comb dashed pattern (vertical movement)
    - footway=crossing  → Thick white dashed segments (Zebra/Signalized)

BDI routing compatibility:
    The Router snaps agents to the nearest footway node. By extracting these
    specifically, we prevent "straight-line" fallback routing that causes
    agents to walk through buildings.
"""

from __future__ import annotations

import json
import logging
import math
import pickle
import time
from urllib import parse as _urllib_parse
from urllib import request as _urllib_request
from urllib import error as _urllib_error
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_OVERPASS_MIN_INTERVAL_S = 12   # Overpass free tier: ~1 request per 10-15s
_OVERPASS_429_RETRY_S    = 35   # Wait after a 429 before retrying the same tile
_OVERPASS_MAX_RETRIES    = 3    # Maximum retry attempts per tile

logger = logging.getLogger(__name__)

try:
    import networkx as nx
    _NX = True
except ImportError:
    _NX = False
    logger.warning("NetworkX not available — walk_network cannot build graphs")

# --- Cache ---
CACHE_ROOT = Path.home() / ".rtd_sim_cache" / "transport"
CACHE_ROOT.mkdir(parents=True, exist_ok=True)
CACHE_TTL_H = 72.0
_OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Target tile area in km² — each Overpass tile should be ≤ this value to stay
# under the 60s timeout for dense UK urban areas (empirically confirmed).
# The tile grid size is computed from this target at runtime, so it scales
# correctly for any UK region from a dense city-centre disc to a rural county.
_TARGET_TILE_KM2 = 400.0


def _haversine_m(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """Distance in meters between two (lon, lat) points."""
    R = 6371000.0
    lon1, lat1 = math.radians(a[0]), math.radians(a[1])
    lon2, lat2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    return 2 * R * math.asin(math.sqrt(h))


def _overpass_post(query: str, timeout_s: int = 60) -> Optional[dict]:
    """POST a query to the Overpass API and return parsed JSON, or None on error.

    Handles HTTP 429 (rate-limit) with configurable back-off and retry so that
    tiled queries do not fail when Overpass enforces its free-tier rate limit.
    """
    body = _urllib_parse.urlencode({'data': query}).encode('utf-8')
    for attempt in range(_OVERPASS_MAX_RETRIES):
        req = _urllib_request.Request(
            _OVERPASS_URL,
            data=body,
            method="POST",
            headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'User-Agent': 'RTD_SIM_Walk_Network_Loader/1.0',
            },
        )
        try:
            with _urllib_request.urlopen(req, timeout=timeout_s + 5) as resp:
                return json.loads(resp.read())
        except _urllib_error.HTTPError as e:
            if e.code == 429:
                wait = _OVERPASS_429_RETRY_S * (attempt + 1)
                logger.warning(
                    "Overpass walk fetch: 429 rate-limit (attempt %d/%d) "
                    "— retrying in %ds",
                    attempt + 1, _OVERPASS_MAX_RETRIES, wait,
                )
                time.sleep(wait)
            else:
                logger.warning("Overpass walk fetch failed: %s", e)
                return None
        except Exception as e:
            logger.warning("Overpass walk fetch failed: %s", e)
            return None
    logger.warning("Overpass walk fetch: gave up after %d retries (429)", _OVERPASS_MAX_RETRIES)
    return None


def _make_tile_query(tile_s: float, tile_n: float, tile_w: float, tile_e: float) -> str:
    """Return an Overpass QL query for pedestrian ways within a bbox tile."""
    return (
        f"[out:json][timeout:60];"
        f"("
        f"  way[\"highway\"=\"footway\"]({tile_s},{tile_w},{tile_n},{tile_e});"
        f"  way[\"highway\"=\"pedestrian\"]({tile_s},{tile_w},{tile_n},{tile_e});"
        f"  way[\"highway\"=\"steps\"]({tile_s},{tile_w},{tile_n},{tile_e});"
        f"  way[\"highway\"=\"path\"][\"foot\"!~\"no\"]({tile_s},{tile_w},{tile_n},{tile_e});"
        f");"
        f"out body geom;"
    )


def _fetch_tiled(
    north: float,
    south: float,
    east: float,
    west: float,
) -> List[dict]:
    """
    Tile the bbox into a dynamic grid and merge Overpass results.

    Tile count is computed from the bbox area so it works for any UK region:
      target area per tile ≤ 400 km² → each tile finishes in < 60s.

    Returns a merged list of OSM way elements.
    """
    # Approximate bbox area in km²
    lat_mid = (north + south) / 2.0
    lat_km  = (north - south) * 111.0
    lon_km  = (east  - west)  * 111.0 * math.cos(math.radians(lat_mid))
    bbox_km2 = lat_km * lon_km

    # Number of tiles along each axis (minimum 1×1 for small regions)
    tile_grid = max(1, math.ceil(math.sqrt(bbox_km2 / _TARGET_TILE_KM2)))
    lat_step  = (north - south) / tile_grid
    lon_step  = (east  - west)  / tile_grid

    logger.info(
        "Walk network: tiling %dx%d (bbox=%.0fkm², target tile=%.0fkm²) "
        "N=%.4f S=%.4f E=%.4f W=%.4f",
        tile_grid, tile_grid, bbox_km2, _TARGET_TILE_KM2,
        north, south, east, west,
    )

    all_elements: List[dict] = []
    seen_ids: set = set()   # deduplicate way IDs across tile boundaries
    success = 0
    fail    = 0

    for i in range(tile_grid):
        for j in range(tile_grid):
            tile_s = south + i * lat_step
            tile_n = tile_s + lat_step
            tile_w = west  + j * lon_step
            tile_e = tile_w + lon_step

            # Enforce minimum inter-request interval to respect the Overpass
            # free-tier rate limit (~1 request per 10-15s per IP).
            # Skip the delay on the very first tile so startup is not held up.
            if i > 0 or j > 0:
                time.sleep(_OVERPASS_MIN_INTERVAL_S)

            query = _make_tile_query(tile_s, tile_n, tile_w, tile_e)
            data  = _overpass_post(query, timeout_s=60)

            if data and 'elements' in data:
                for el in data['elements']:
                    eid = el.get('id')
                    if eid not in seen_ids:
                        seen_ids.add(eid)
                        all_elements.append(el)
                success += 1
            else:
                fail += 1
                logger.warning(
                    "Walk network: tile (%d,%d) failed — "
                    "N=%.4f S=%.4f E=%.4f W=%.4f",
                    i, j, tile_n, tile_s, tile_e, tile_w,
                )

    logger.info(
        "Walk network: fetched %d unique elements (%d/%d tiles succeeded)",
        len(all_elements), success, tile_grid * tile_grid,
    )
    return all_elements


def _build_graph_from_elements(elements: List[dict]) -> 'nx.MultiDiGraph':
    """Convert a list of Overpass OSM way elements into a NetworkX MultiDiGraph."""
    G = nx.MultiDiGraph()
    G.graph['name'] = 'walk'
    # OSMnx's ox.distance.nearest_nodes requires the graph CRS to select
    # the correct distance metric (haversine for WGS84, Euclidean for
    # projected).  Without this, nearest_nodes silently falls back to the
    # OSMnx walk graph instead of the footways graph on every call.
    G.graph['crs'] = 'epsg:4326'

    for el in elements:
        if el.get('type') != 'way':
            continue

        tags  = el.get('tags', {})
        geom  = el.get('geometry', [])
        coords = [(float(pt['lon']), float(pt['lat'])) for pt in geom]
        if len(coords) < 2:
            continue

        # Identify visual mode for dashed rendering logic
        hway = tags.get('highway', 'footway')
        if hway == 'steps':
            mode = 'walk_stairs'
        elif tags.get('footway') == 'crossing':
            mode = 'walk_crossing'
        elif hway == 'path':
            mode = 'walk_path'
        else:
            mode = 'walk_lane'

        # Calculate edge length
        length = 0.0
        for k in range(len(coords) - 1):
            length += _haversine_m(coords[k], coords[k + 1])

        u_id = int(el['nodes'][0]) #str(el['nodes'][0])
        v_id = int(el['nodes'][-1]) #str(el['nodes'][-1])

        G.add_node(u_id, x=coords[0][0],  y=coords[0][1],  node_type='walk_node')
        G.add_node(v_id, x=coords[-1][0], y=coords[-1][1], node_type='walk_node')

        edge_attrs = {
            'mode':         mode,
            'length':       length,
            'name':         tags.get('name', 'Unnamed walk way'),
            'surface':      tags.get('surface', 'unknown'),
            'shape_coords': coords,   # list of (lon, lat) tuples — preserved by pickle
        }
        G.add_edge(u_id, v_id, **edge_attrs)

        rev_attrs = edge_attrs.copy()
        rev_attrs['shape_coords'] = list(reversed(coords))
        G.add_edge(v_id, u_id, **rev_attrs)

    return G


def build_walk_network(
    bbox: Optional[Tuple[float, float, float, float]] = None,
    city_tag: str = "default",
    use_cache: bool = True,
    graph_manager=None,
) -> 'nx.MultiDiGraph':
    """
    Build a bidirectional pedestrian graph from Overpass OSM data.

    Prioritises dedicated walking infrastructure (footways, paths, steps,
    pedestrian areas) to keep agents off road networks.

    Issue 3 fix: tiled Overpass queries avoid 504 timeouts for large bboxes.
    Issue 4 fix: pickle cache preserves shape_coords as lists (GraphML
                 serialises them as strings, corrupting geometry on reload).

    Args:
        bbox:          (north, south, east, west) in WGS84.  If None, derived
                       from the drive graph registered on graph_manager.
        city_tag:      Cache key prefix (e.g. 'edinburgh_uk').
        use_cache:     Whether to read/write a pickle cache.
        graph_manager: Optional GraphManager; used to derive bbox from the
                       drive graph when bbox is not explicitly supplied.

    Returns:
        nx.MultiDiGraph with pedestrian edges, each carrying:
            mode, length, name, surface, shape_coords
    """
    # ── Derive bbox from drive graph when not provided ─────────────────────────
    if bbox is None and graph_manager is not None:
        try:
            G_drive = graph_manager.get_graph('drive')
            if G_drive is not None and G_drive.number_of_nodes() > 0:
                xs = [float(d.get('x', 0)) for _, d in G_drive.nodes(data=True)]
                ys = [float(d.get('y', 0)) for _, d in G_drive.nodes(data=True)]
                # Add a small margin (≈400m) so footways just outside the drive
                # graph hull are still included.
                _margin = 0.004
                north = max(ys) + _margin
                south = min(ys) - _margin
                east  = max(xs) + _margin
                west  = min(xs) - _margin
                bbox  = (north, south, east, west)
                logger.info(
                    "Walk network: bbox derived from drive graph "
                    "(N=%.4f S=%.4f E=%.4f W=%.4f)", north, south, east, west,
                )
        except Exception as _bbox_exc:
            logger.warning(
                "Walk network: could not derive bbox from drive graph: %s", _bbox_exc,
            )

    if bbox is None:
        logger.warning("Walk network: no bbox available — returning empty graph")
        G = nx.MultiDiGraph()
        G.graph['name'] = 'walk'
        G.graph['crs']  = 'epsg:4326'
        return G

    north, south, east, west = bbox

    # ── Pickle cache (Issue 4: replaces GraphML which corrupts shape_coords) ──
    cache_path = CACHE_ROOT / f"{city_tag}_walk.pkl"

    if use_cache and cache_path.exists():
        age_h = (time.time() - cache_path.stat().st_mtime) / 3600
        if age_h < CACHE_TTL_H:
            try:
                G = pickle.loads(cache_path.read_bytes())
                logger.info(
                    "✅ Walk network loaded from pickle cache: %s (%.1fh old, %d nodes, %d edges)",
                    city_tag, age_h, G.number_of_nodes(), G.number_of_edges(),
                )
                return G
            except Exception as _cache_exc:
                logger.warning(
                    "Walk network: pickle cache unreadable (%s) — rebuilding", _cache_exc,
                )

    # ── Tiled Overpass fetch (Issue 3: avoids 504 timeouts on large bboxes) ──
    elements = _fetch_tiled(north, south, east, west)

    G = _build_graph_from_elements(elements)

    logger.info(
        "Walk network: built graph — %d nodes, %d edges",
        G.number_of_nodes(), G.number_of_edges(),
    )

    # ── Write pickle cache ─────────────────────────────────────────────────────
    if use_cache and G.number_of_nodes() > 0:
        try:
            cache_path.write_bytes(pickle.dumps(G))
            logger.info("Walk network: pickle cache written → %s", cache_path.name)
        except Exception as _write_exc:
            logger.warning("Walk network: could not write pickle cache: %s", _write_exc)

    return G


def get_walk_layer_styles() -> Dict:
    """Returns palette info for pydeck LineLayer dashing."""
    return {
        'walk_lane':     {'color': [250, 158, 160], 'dash': [4, 4]},   # Pink Dashed
        'walk_path':     {'color': [140, 100,  70], 'dash': [3, 5]},   # Brown Dashed
        'walk_stairs':   {'color': [200,  50,  50], 'dash': [1, 1]},   # Red "Ladder"
        'walk_crossing': {'color': [255, 255, 255], 'dash': [2, 2]},   # White Zebra
    }