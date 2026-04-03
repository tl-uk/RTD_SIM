"""
simulation/spatial/rail_network.py

Downloads and processes rail/tram infrastructure via OSMnx + OpenRailMap.

Two entry-points:
  fetch_rail_graph(bbox)          — download from OSM using OpenRailMap filters.
  get_or_fallback_rail_graph(env) — try download; fall back to the hardcoded
                                     Edinburgh / UK rail spine so rail agents
                                     always have something to route on.

Transfer-node links:
  link_to_road_network(G_rail, G_road) adds bi-directional 'transfer' edges
  between rail station nodes and their nearest road nodes so the Router's
  intermodal logic can compute access/egress legs correctly.
"""

from __future__ import annotations
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

try:
    import networkx as nx
    _NX = True
except ImportError:
    _NX = False

try:
    import osmnx as ox
    _OX = True
except ImportError:
    _OX = False
    logger.warning("OSMnx not available — rail graph cannot be fetched from OpenRailMap")

_TRANSFER_LENGTH_M    = 300
_TRANSFER_TIME_H      = 0.25   # 15 min boarding penalty
_TRANSFER_HIGHWAY_TAG = 'transfer'


# def fetch_rail_graph(
#     bbox: Tuple[float, float, float, float],
# ) -> Optional[object]:
#     """
#     Download rail/tram graph from OpenStreetMap (OpenRailMap tag filters).

#     Args:
#         bbox: (north, south, east, west) — OSMnx convention

#     Returns:
#         NetworkX MultiDiGraph or None on failure.
#     """
#     if not _OX:
#         logger.warning("fetch_rail_graph: OSMnx not available")
#         return None

#     north, south, east, west = bbox
#     rail_filter = '["railway"~"rail|tram|subway|light_rail"]'

#     try:
#         # OSMnx >= 1.0 keyword-argument form
#         G_rail = ox.graph_from_bbox(
#             north=north,
#             south=south,
#             east=east,
#             west=west,
#             custom_filter=rail_filter,
#             retain_all=True,
#             simplify=True,
#         )
#         logger.info(
#             "✅ Rail graph fetched: %d nodes, %d edges",
#             len(G_rail.nodes), len(G_rail.edges),
#         )
#         return G_rail

#     except TypeError:
#         # Older OSMnx positional fallback
#         try:
#             G_rail = ox.graph_from_bbox(
#                 north, south, east, west,
#                 custom_filter=rail_filter,
#                 retain_all=True,
#                 simplify=True,
#             )
#             logger.info(
#                 "✅ Rail graph fetched (legacy API): %d nodes, %d edges",
#                 len(G_rail.nodes), len(G_rail.edges),
#             )
#             return G_rail
#         except Exception as exc:
#             logger.error("fetch_rail_graph (legacy API) failed: %s", exc)
#             return None

#     except Exception as exc:
#         logger.error("fetch_rail_graph failed: %s", exc)
#         return None

def fetch_rail_graph(
    bbox: Tuple[float, float, float, float],
) -> Optional[object]:
    """
    Download unified rail/tram graph from OSM, preserving tags for filtering,
    and ensuring bi-directional topology for routing.
    """
    if not _OX:
        logger.warning("fetch_rail_graph: OSMnx not available")
        return None

    # 1. Preserve the 'railway' tag so router.py can filter by track type
    useful_tags = list(ox.settings.useful_tags_way)
    if 'railway' not in useful_tags:
        useful_tags.append('railway')
        ox.settings.useful_tags_way = useful_tags

    north, south, east, west = bbox
    rail_filter = '["railway"~"rail|tram|subway|light_rail"]'

    try:
        # OSMnx 2.0+ API
        G_directed = ox.graph_from_bbox(
            bbox=(west, south, east, north),   # ← matches OSMnx 2.x (left, bottom, right, top)
            custom_filter=rail_filter,
            simplify=True,
            retain_all=True,
        )

        # CRITICAL FIX FOR ECONOMIC ROUTING:
        # Convert to an undirected graph, then back to directed.
        # This guarantees bi-directional edges everywhere, preventing
        # shortest_path from failing due to arbitrary OSM drawing directions.
        # G_rail = G_directed.to_undirected().to_directed()
        for u, v, key, data in list(G_directed.edges(keys=True, data=True)):
            if not G_directed.has_edge(v, u):
                rev = dict(data)
                if 'geometry' in rev and hasattr(rev['geometry'], 'coords'):
                    from shapely.geometry import LineString
                    rev['geometry'] = LineString(reversed(list(rev['geometry'].coords)))
                G_directed.add_edge(v, u, **rev)
        G_rail = G_directed
        G_rail.graph['name'] = 'rail'

        logger.info(
            "✅ Bi-directional Rail graph fetched: %d nodes, %d edges",
            len(G_rail.nodes), len(G_rail.edges),
        )
        return G_rail

    except TypeError:
        # OSMnx 1.x legacy API fallback
        try:
            G_directed = ox.graph_from_bbox(
                north, south, east, west,
                custom_filter=rail_filter,
                retain_all=True,
                simplify=True,
            )
            G_rail = G_directed.to_undirected().to_directed()
            G_rail.graph['name'] = 'rail'
            
            logger.info("✅ Rail graph fetched (legacy API): %d nodes", len(G_rail.nodes))
            return G_rail
        except Exception as exc:
            logger.error("fetch_rail_graph (legacy) failed: %s", exc)
            return None
    except Exception as exc:
        logger.error("fetch_rail_graph failed: %s", exc)
        return None
    
def get_or_fallback_rail_graph(env=None) -> Optional[object]:
    """
    Try to fetch the OpenRailMap graph; fall back to the hardcoded rail spine.

    The rail spine (rail_spine.py) is a lightweight NetworkX graph of Edinburgh
    and UK intercity stations so rail agents always have routing geometry even
    when the OpenRailMap download fails or the user is offline.

    Args:
        env: SpatialEnvironment — used to derive the bbox from the drive graph.

    Returns:
        NetworkX MultiDiGraph (from OpenRailMap or rail spine).
    """
    bbox = None
    if env is not None:
        drive = None
        if hasattr(env, 'graph_manager'):
            drive = env.graph_manager.get_graph('drive')
        if drive is not None and len(drive.nodes) > 0:
            xs = [d['x'] for _, d in drive.nodes(data=True)]
            ys = [d['y'] for _, d in drive.nodes(data=True)]
            bbox = (max(ys), min(ys), max(xs), min(xs))

    if bbox is None:
        logger.warning("get_or_fallback_rail_graph: using Edinburgh default bbox")
        bbox = (56.0, 55.85, -3.05, -3.45)

    G_rail = fetch_rail_graph(bbox)

    if G_rail is not None and len(G_rail.nodes) > 10:
        return G_rail

    logger.warning(
        "OpenRailMap fetch failed or empty — falling back to hardcoded rail spine"
    )
    try:
        from simulation.spatial.rail_spine import get_spine_graph
        spine = get_spine_graph()
        if spine is not None:
            logger.info(
                "✅ Rail spine fallback: %d stations, %d edges",
                spine.number_of_nodes(), spine.number_of_edges(),
            )
        return spine
    except Exception as exc:
        logger.error("rail_spine fallback failed: %s", exc)
        return None


def link_to_road_network(
    G_rail: object,
    G_road: object,
    radius_m: int = 300,
) -> None:
    """
    Add Transfer Edges between rail station nodes and their nearest road nodes.

    Args:
        G_rail:   Rail NetworkX graph
        G_road:   Drive NetworkX graph
        radius_m: Synthetic edge length in metres
    """
    if not _NX or not _OX:
        return
    if G_rail is None or G_road is None:
        return

    stations = [
        n for n, d in G_rail.nodes(data=True)
        if d.get('railway') == 'station'
        or d.get('station_type') in (
            'major', 'suburban', 'interchange',
            'regional', 'intercity_stop',
        )
    ]
    if not stations:
        stations = list(G_rail.nodes())

    links_added = 0
    for stn_node in stations:
        nd = G_rail.nodes[stn_node]
        lat = nd.get('y', nd.get('lat', 0))
        lon = nd.get('x', nd.get('lon', 0))
        try:
            road_node = ox.distance.nearest_nodes(G_road, lon, lat)
        except Exception:
            continue
        for u, v, g in (
            (stn_node, road_node, G_rail),
            (road_node, stn_node, G_road),
        ):
            if not g.has_edge(u, v):
                g.add_edge(
                    u, v,
                    length=radius_m,
                    highway=_TRANSFER_HIGHWAY_TAG,
                    time_h=_TRANSFER_TIME_H,
                    gen_cost=_TRANSFER_TIME_H * 10.0,
                )
        links_added += 1

    logger.info(
        "link_to_road_network: transfer edges for %d/%d stations",
        links_added, len(stations),
    )
