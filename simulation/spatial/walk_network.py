"""
simulation/spatial/walk_network.py

Comprehensive pedestrian transport layer for RTD_SIM.

This module provides a multi-source pipeline for pedestrian infrastructure:
    Tier 1 — Overpass live fetch (primary)
    Tier 2 — Cached GraphML snapshot (~72h TTL)

Visual Representation & Rendering:
    In OSM, pedestrian infrastructure is often distinguished by dashed lines:
    - highway=footway   → Salmon/Pink dashed lines (standard pedestrian paths)
    - highway=path      → Dark brown dashed lines (multi-use/unpaved)[cite: 17]
    - highway=steps     → Ladder/Comb dashed pattern (vertical movement)[cite: 17]
    - footway=crossing  → Thick white dashed segments (Zebra/Signalized)[cite: 17]

BDI routing compatibility:
    The Router snaps agents to the nearest footway node. By extracting these 
    specifically, we prevent "straight-line" fallback routing that causes 
    agents to walk through buildings.
"""

from __future__ import annotations

import json
import logging
import math
import time
from urllib import parse as _urllib_parse
from urllib import request as _urllib_request
from urllib import error as _urllib_error
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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

def _haversine_m(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """Distance in meters between two (lon, lat) points."""
    R = 6371000.0
    lon1, lat1 = math.radians(a[0]), math.radians(a[1])
    lon2, lat2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    return 2 * R * math.asin(math.sqrt(h))

def _overpass_post(query: str, timeout_s: int = 60) -> Optional[dict]:
    body = _urllib_parse.urlencode({'data': query}).encode('utf-8')
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
    except Exception as e:
        logger.warning(f"Overpass walk fetch failed: {e}")
        return None

def build_walk_network(
    bbox: Tuple[float, float, float, float], 
    city_tag: str = "default",
    use_cache: bool = True
) -> 'nx.MultiDiGraph':
    """
    Builds a bidirectional pedestrian graph. 
    Prioritizes dedicated walking infrastructure to keep agents off road networks.
    """
    north, south, east, west = bbox
    cache_path = CACHE_ROOT / f"{city_tag}_walk.graphml"

    if use_cache and cache_path.exists():
        if (time.time() - cache_path.stat().st_mtime) / 3600 < CACHE_TTL_H:
            try:
                G = nx.read_graphml(cache_path)
                logger.info(f"✅ Walk network loaded from cache: {city_tag}")
                return G
            except Exception: pass

    # Fetch footways, paths, steps, and pedestrian areas
    query = (
        f"[out:json][timeout:60];"
        f"("
        f"  way[\"highway\"=\"footway\"]({south},{west},{north},{east});"
        f"  way[\"highway\"=\"pedestrian\"]({south},{west},{north},{east});"
        f"  way[\"highway\"=\"steps\"]({south},{west},{north},{east});"
        f"  way[\"highway\"=\"path\"][\"foot\"!~\"no\"]({south},{west},{north},{east});"
        f");"
        f"out body geom;"
    )

    data = _overpass_post(query)
    G = nx.MultiDiGraph()
    G.graph['name'] = 'walk'

    if not data or 'elements' not in data:
        return G

    for el in data['elements']:
        if el['type'] != 'way': continue
        
        tags = el.get('tags', {})
        geom = el.get('geometry', [])
        coords = [(float(pt['lon']), float(pt['lat'])) for pt in geom]
        if len(coords) < 2: continue

        # Identify visual mode for 'dashed' rendering logic
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
        for i in range(len(coords) - 1):
            length += _haversine_m(coords[i], coords[i+1])

        u_id, v_id = str(el['nodes'][0]), str(el['nodes'][-1])
        
        # Nodes
        G.add_node(u_id, x=coords[0][0], y=coords[0][1], node_type='walk_node')
        G.add_node(v_id, x=coords[-1][0], y=coords[-1][1], node_type='walk_node')

        # Edges (Bidirectional)
        edge_attrs = {
            'mode': mode,
            'length': length,
            'name': tags.get('name', 'Unnamed walk way'),
            'surface': tags.get('surface', 'unknown'),
            'shape_coords': coords
        }
        G.add_edge(u_id, v_id, **edge_attrs)
        
        rev_attrs = edge_attrs.copy()
        rev_attrs['shape_coords'] = list(reversed(coords))
        G.add_edge(v_id, u_id, **rev_attrs)

    if use_cache and G.number_of_nodes() > 0:
        nx.write_graphml(G, cache_path)

    return G

def get_walk_layer_styles() -> Dict:
    """Returns palette info for pydeck LineLayer dashing."""
    return {
        'walk_lane': {'color': [250, 158, 160], 'dash': [4, 4]},     # Pink Dashed[cite: 17]
        'walk_path': {'color': [140, 100, 70], 'dash': [3, 5]},     # Brown Dashed[cite: 17]
        'walk_stairs': {'color': [200, 50, 50], 'dash': [1, 1]},    # Red "Ladder"[cite: 17]
        'walk_crossing': {'color': [255, 255, 255], 'dash': [2, 2]} # White Zebra[cite: 17]
    }