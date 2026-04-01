"""
ui/components/rail_visualizer.py

Pydeck layer definitions for the rail/tram network overlay.

Design notes
────────────
The RTD_SIM rail graph can be either:
  (a) The hardcoded 41-station Scottish spine graph loaded by rail_spine.py.
      Nodes use string CRS codes ('EDB', 'HYM', 'NCR' ...) as node IDs.
      Node attributes: x (lon), y (lat), name, crs.
      Edge attributes: length, travel_time_s.  No 'geometry' attribute.

  (b) An OSMnx OpenRailMap graph fetched by rail_network.py.
      Nodes use integer OSMnx IDs.
      Node attributes: x (lon), y (lat).
      Edge attributes: geometry (Shapely LineString), length, ...

The original implementation called ox.graph_to_gdfs(G_rail) which fails for
case (a) because graph_to_gdfs expects integer node IDs and OSMnx metadata.
The exception was silently swallowed in visualization.py, making the rail
overlay never appear.

This version extracts node coordinates and edge geometry directly, building
a pydeck PathLayer that works for both graph types without OSMnx.
"""

from __future__ import annotations
import logging
from typing import Any, List, Optional, Dict, Tuple

logger = logging.getLogger(__name__)

try:
    import pydeck as pdk
    _PDK = True
except ImportError:
    _PDK = False
    logger.warning("pydeck not available -- rail layer disabled")


def _node_coord(G: Any, node_id: Any) -> Optional[Tuple[float, float]]:
    """Return (lon, lat) for a graph node, trying multiple attribute names."""
    data = G.nodes.get(node_id, {})
    lon = data.get('x') or data.get('lon') or data.get('longitude')
    lat = data.get('y') or data.get('lat') or data.get('latitude')
    if lon is None or lat is None:
        return None
    try:
        return float(lon), float(lat)
    except (TypeError, ValueError):
        return None


def create_rail_layer(G_rail: Any) -> Optional[Any]:
    """
    Build a pydeck PathLayer for the rail network graph.

    Works with both the hardcoded station spine (string node IDs, no edge
    geometry) and the OpenRailMap graph (integer node IDs, Shapely edge
    geometry).  Falls back to a straight stop-to-stop line when no edge
    geometry is present -- acceptable for the spine because the stations are
    the source of truth, not the track geometry.

    Args:
        G_rail: NetworkX graph (MultiDiGraph or DiGraph).

    Returns:
        pydeck.Layer or None if unavailable or empty.
    """
    if not _PDK or G_rail is None:
        return None

    path_data: List[Dict] = []
    seen_edges: set = set()   # deduplicate undirected edges

    for u, v, data in G_rail.edges(data=True):
        # Skip duplicate reverse edges
        edge_key = (min(str(u), str(v)), max(str(u), str(v)))
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)

        u_coord = _node_coord(G_rail, u)
        v_coord = _node_coord(G_rail, v)
        if u_coord is None or v_coord is None:
            continue

        # Use Shapely edge geometry when present (OSMnx graph)
        geom = data.get('geometry')
        if geom is not None and hasattr(geom, 'coords'):
            shape = [[float(x), float(y)] for x, y in geom.coords]
        else:
            # Spine graph: straight line between station nodes
            shape = [list(u_coord), list(v_coord)]

        if len(shape) < 2:
            continue

        path_data.append({'path': shape})

    if not path_data:
        logger.debug("create_rail_layer: no valid edges found in graph")
        return None

    logger.info("create_rail_layer: built %d path segments from %d nodes",
                len(path_data), G_rail.number_of_nodes())

    return pdk.Layer(
        'PathLayer',
        data=path_data,
        get_path='path',
        get_color=[255, 140, 0, 160],   # orange, slightly transparent
        width_min_pixels=2,
        width_max_pixels=5,
        pickable=False,   # rail network is background -- not interactive
        rounded=True,
        joint_rounded=True,
    )


def create_train_path_layer(path_coords: List) -> Optional[Any]:
    """
    Visualise the active path of a train agent.

    Args:
        path_coords: List of [lon, lat] pairs following track geometry.

    Returns:
        pydeck.Layer or None.
    """
    if not _PDK or not path_coords or len(path_coords) < 2:
        return None

    return pdk.Layer(
        'PathLayer',
        [{'path': [[float(c[0]), float(c[1])] for c in path_coords]}],
        get_path='path',
        get_color=[255, 255, 255, 220],   # white for active routing
        width_min_pixels=4,
        rounded=True,
        pickable=False,
    )