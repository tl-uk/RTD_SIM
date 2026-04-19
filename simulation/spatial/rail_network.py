"""
simulation/spatial/rail_network.py

Downloads and processes rail/tram infrastructure via OSMnx + OpenRailMap.

Two public entry-points
-----------------------
fetch_rail_graph(bbox)
    Download from OSM using OpenRailMap tag filters.  The bbox is expected
    in (north, south, east, west) order — the internal convention used by
    get_or_fallback_rail_graph().  The function unpacks and passes the axes
    to OSMnx in the correct (west, south, east, north) order for 2.x.

get_or_fallback_rail_graph(env)
    Try download; fall back to the hardcoded Edinburgh / UK rail spine so
    rail agents always have something to route on even when offline.
    Returns a NetworkX MultiDiGraph in either case.

Geometry handling
-----------------
OSMnx stores curved track geometry as a Shapely LineString on each
simplified directed edge, with coordinates ordered u→v.  The older
approach of calling to_undirected().to_directed() destroyed that
geometry because NetworkX does not guarantee attribute preservation or
direction correctness on round-trip conversion.

Instead we iterate the directed graph and explicitly add a reversed copy
of every one-way edge, reversing the LineString coordinate sequence so
the geometry is correct in both directions.  This guarantees:
  • nx.shortest_path never fails due to arbitrary OSM drawing direction.
  • _extract_geometry reads the correct Shapely coords for every edge.

Transfer-node links
-------------------
link_to_road_network(G_rail, G_road) adds bi-directional 'transfer' edges
between rail station nodes and their nearest road nodes so the Router's
intermodal logic can compute access/egress legs correctly.
"""

from __future__ import annotations
import logging
from typing import Tuple, Optional, List

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

# Synthetic transfer-edge constants used by link_to_road_network().
_TRANSFER_LENGTH_M    = 300
_TRANSFER_TIME_H      = 0.25   # 15-min boarding penalty expressed as hours
_TRANSFER_HIGHWAY_TAG = 'transfer'


def fetch_rail_graph(
    bbox: Tuple[float, float, float, float],
) -> Optional[nx.MultiDiGraph]:
    """
    Download a unified, bi-directional rail/tram graph from OpenStreetMap.

    The 'railway' tag is preserved on every edge so router.py can filter
    by track type (e.g. tram vs mainline).  Reverse edges are added
    explicitly with their LineString geometry reversed so that routing
    works regardless of the direction in which OSM contributors drew the
    original way.

    Args:
        bbox: (north, south, east, west) — RTD_SIM internal convention.
              Internally unpacked and passed to OSMnx as (west, south,
              east, north) to match the OSMnx 2.x API.

    Returns:
        NetworkX MultiDiGraph tagged with graph['name'] = 'rail', or None.
    """
    if not _OX:
        logger.warning("fetch_rail_graph: OSMnx not available")
        return None

    # Preserve the 'railway' tag so router.py can filter by track type.
    useful_tags = list(ox.settings.useful_tags_way)
    if 'railway' not in useful_tags:
        useful_tags.append('railway')
        ox.settings.useful_tags_way = useful_tags

    north, south, east, west = bbox

    # ── OSM rail filter rationale ─────────────────────────────────────────────
    # Tag values explicitly INCLUDED (anchored regex):
    #   rail        — mainline passenger + freight (Network Rail)
    #   light_rail  — DLR, tram-train hybrids
    #   subway      — Glasgow Subway, future Edinburgh metro
    #   tram        — Edinburgh Trams, Manchester Metrolink etc.
    #   monorail    — future systems
    #
    # Excluded by NOT being in the inclusion list:
    #   railway=disused, abandoned, construction, proposed, miniature, preserved
    #
    # ADDITIONAL EXCLUSIONS (new — fix for Craiglockhart freight junction):
    # ── usage=freight / usage=industrial ──────────────────────────────────────
    # OSM 'usage' tag on railway=rail ways:
    #   main       — mainline passenger (Edinburgh–Glasgow, ECML etc.)
    #   branch     — branch passenger lines (e.g. Borders Railway)
    #   freight    — freight-only (Caledonian goods line, aggregates spurs)
    #   industrial — private sidings (quarries, ports, power stations)
    # Freight lines (e.g. the Caledonian line from Slateford to Millerhill)
    # cross the main line at Craiglockhart without any passenger station.
    # They were generating V-shaped routes and impossible junction transfers.
    # Excluding usage=freight and usage=industrial removes them entirely.
    #
    # ── passenger=no ──────────────────────────────────────────────────────────
    # Some OSM ways correctly tagged railway=rail but passenger=no
    # (e.g. pure freight spurs, shunting necks).  Exclude these too.
    #
    # ── service=yard|siding|crossover|spur (retained from before) ─────────────
    # Dead-end maintenance infrastructure — causes impossible acute turns.
    rail_filter = (
        '["railway"~"^(rail|light_rail|subway|tram|monorail)$"]'
        '["service"!~"^(yard|siding|crossover|spur)$"]'
        '["usage"!~"^(freight|industrial)$"]'
        '["passenger"!="no"]'
    )

    # ── Graph simplification ───────────────────────────────────────────────────
    # simplify=True (default): OSMnx merges collinear nodes, reducing node count.
    # For rail and subway this is fine — tracks are nearly straight.
    # For TRAM: simplify=True creates chord edges that cut through buildings and
    # stadiums (observed: Edinburgh Trams route through Murrayfield Stadium).
    # The Edinburgh Trams curve around Roseburn/Balgreen was being reduced to a
    # single straight edge. Fix: tram layer uses simplify=False to preserve the
    # full curved track geometry.  Other layers keep simplify=True for performance.
    # We detect tram from the filter string rather than adding a parameter.
    _is_tram_layer = '"tram"' in rail_filter and '"rail"' not in rail_filter
    _simplify = not _is_tram_layer   # False for tram-only, True for mixed/rail

    try:
        # OSMnx 2.x expects (left, bottom, right, top) = (west, south, east, north).
        G_directed = ox.graph_from_bbox(
            bbox=(west, south, east, north),
            custom_filter=rail_filter,
            simplify=_simplify,
            retain_all=True,
        )
    except TypeError:
        # OSMnx 1.x positional fallback — still uses the correct axis order.
        try:
            G_directed = ox.graph_from_bbox(
                north, south, east, west,
                custom_filter=rail_filter,
                retain_all=True,
                simplify=_simplify,
            )
        except Exception as exc:
            logger.error("fetch_rail_graph (OSMnx 1.x fallback) failed: %s", exc)
            return None
    except Exception as exc:
        logger.error("fetch_rail_graph failed: %s", exc)
        return None

    # Add reverse edges for any one-way segment, preserving Shapely geometry.
    # Using to_undirected().to_directed() is NOT safe here — it strips or
    # mis-orients edge geometry.  We add reversed edges manually instead.
    for u, v, key, data in list(G_directed.edges(keys=True, data=True)):
        if not G_directed.has_edge(v, u):
            rev = dict(data)
            if 'geometry' in rev and hasattr(rev['geometry'], 'coords'):
                from shapely.geometry import LineString
                rev['geometry'] = LineString(reversed(list(rev['geometry'].coords)))
            G_directed.add_edge(v, u, **rev)

    G_directed.graph['name'] = 'rail'

    logger.info(
        "✅ Rail graph fetched: %d nodes, %d edges",
        len(G_directed.nodes), len(G_directed.edges),
    )
    return G_directed


def get_or_fallback_rail_graph(env=None) -> Optional[nx.MultiDiGraph]:
    """
    Try to fetch the OpenRailMap graph; fall back to the hardcoded rail spine.

    The rail spine (rail_spine.py) is a lightweight NetworkX graph of
    Edinburgh and UK intercity stations so rail agents always have routing
    geometry even when the OpenRailMap download fails or the user is offline.

    bbox construction
    -----------------
    Derives the bounding box from the drive graph node coordinates when env
    is supplied.  The tuple is built as (north, south, east, west) — the
    RTD_SIM internal convention that fetch_rail_graph() unpacks correctly.

    Args:
        env: SpatialEnvironment — used to derive the bbox from the drive
             graph.  Pass None to use the Edinburgh default.

    Returns:
        NetworkX MultiDiGraph (from OpenRailMap or the spine fallback).
    """
    bbox = None

    if env is not None:
        drive = None
        if hasattr(env, 'graph_manager'):
            drive = env.graph_manager.get_graph('drive')
        if drive is not None and len(drive.nodes) > 0:
            xs = [d['x'] for _, d in drive.nodes(data=True)]
            ys = [d['y'] for _, d in drive.nodes(data=True)]
            # (north, south, east, west) — fetch_rail_graph unpacks this correctly.
            bbox = (max(ys), min(ys), max(xs), min(xs))

    if bbox is None:
        logger.warning("get_or_fallback_rail_graph: no drive graph — using Edinburgh default bbox")
        # Edinburgh: north=56.0, south=55.85, east=-3.05, west=-3.40
        bbox = (56.0, 55.85, -3.05, -3.40)

    G_rail = fetch_rail_graph(bbox)

    if G_rail is not None and len(G_rail.nodes) > 10:
        # ── Remove known-bad junction nodes ───────────────────────────────────
        # OSM node IDs for at-grade freight/passenger crossings where there is
        # physically no station but the graph topology creates a valid path.
        # These cause impossible V-shaped routes through track crossings.
        #   21517407  — Craiglockhart at-grade crossing (Caledonian freight /
        #               Edinburgh–Glasgow mainline).  No station, no platform.
        #   Agents 2601, 9204 were routing through this node across two
        #   independent track alignments.
        # The freight exclusion filter (usage!=freight) removes the Caledonian
        # branch way, but OSMnx may retain the shared node from OSM's topology.
        _BAD_NODES = {
            '21517407',   # Craiglockhart crossing — string (OSMnx loads IDs as str)
            21517407,     # int form — whichever OSMnx uses
            '2524591112', # Slateford junction connector node
            2524591112,
        }
        removed = [n for n in list(G_rail.nodes()) if n in _BAD_NODES]
        if removed:
            G_rail.remove_nodes_from(removed)
            logger.info(
                "Removed %d known-bad junction nodes from rail graph: %s",
                len(removed), removed,
            )
            # Keep only largest weakly-connected component after node removal
            import networkx as _nx2
            ccs = sorted(_nx2.weakly_connected_components(G_rail), key=len, reverse=True)
            if ccs:
                G_rail = G_rail.subgraph(ccs[0]).copy()
                G_rail.graph['name'] = 'rail'
        # ── End bad-node removal ──────────────────────────────────────────────
        return G_rail

    logger.warning(
        "OpenRailMap fetch failed or returned an empty graph — "
        "falling back to hardcoded rail spine"
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
        logger.error("rail_spine fallback also failed: %s", exc)
        return None


def link_to_road_network(
    G_rail: nx.MultiDiGraph,
    G_road: nx.MultiDiGraph,
    radius_m: int = _TRANSFER_LENGTH_M,
) -> None:
    """
    Add bi-directional 'transfer' edges between rail station nodes and their
    nearest road nodes.

    These edges are used by the Router's intermodal logic to compute access
    and egress legs.  The edge length is set to the fixed radius_m value
    (a synthetic boarding penalty) rather than the true haversine distance,
    so the gen_cost reflects the time cost of walking to/from the platform.

    Station detection strategy
    --------------------------
    Nodes tagged railway='station' are preferred.  If no such nodes exist
    (e.g. the graph is the simplified spine), all graph nodes are used.

    Args:
        G_rail:   Rail NetworkX MultiDiGraph.
        G_road:   Drive NetworkX MultiDiGraph.
        radius_m: Synthetic edge length in metres (default 300 m).
    """
    if not _NX or not _OX:
        return
    if G_rail is None or G_road is None:
        return

    # Prefer nodes explicitly tagged as stations; fall back to all nodes.
    stations = [
        n for n, d in G_rail.nodes(data=True)
        if d.get('railway') == 'station'
        or d.get('station_type') in (
            'major', 'suburban', 'interchange', 'regional', 'intercity_stop',
        )
    ]
    if not stations:
        stations = list(G_rail.nodes())

    links_added = 0
    for stn_node in stations:
        nd  = G_rail.nodes[stn_node]
        lat = nd.get('y', nd.get('lat', 0))
        lon = nd.get('x', nd.get('lon', 0))
        try:
            road_node = ox.distance.nearest_nodes(G_road, lon, lat)
        except Exception:
            continue

        # Add rail→road edge in the rail graph and road→rail edge in the road
        # graph so the Router can chain walk/drive legs at both ends.
        for u, v, g in (
            (stn_node, road_node, G_rail),
            (road_node, stn_node, G_road),
        ):
            if not g.has_edge(u, v):
                g.add_edge(
                    u, v,
                    length      = radius_m,
                    highway     = _TRANSFER_HIGHWAY_TAG,
                    time_h      = _TRANSFER_TIME_H,
                    gen_cost    = _TRANSFER_TIME_H * 10.0,
                )
        links_added += 1

    logger.info(
        "link_to_road_network: transfer edges added for %d / %d stations",
        links_added, len(stations),
    )


# =============================================================================
# FERRY — shim only; all ferry logic lives in ferry_network.py
# =============================================================================

def _great_circle_waypoints(
    origin: Tuple[float, float],
    dest:   Tuple[float, float],
    n: int = 16,
) -> list:
    """
    Return n points along the great-circle arc from origin to dest.

    Uses spherical linear interpolation (slerp) — NOT flat lon/lat lerp.
    The previous implementation used linear interpolation in geographic
    coordinate space, which causes long-distance routes (e.g. Aberdeen→Lerwick,
    320 km) to pass through land because the great-circle arc curves away
    from the straight lat/lon diagonal.

    Args:
        origin: (lon, lat) in decimal degrees.
        dest:   (lon, lat) in decimal degrees.
        n:      Number of interpolation points including endpoints.
    """
    import math
    lon1, lat1 = math.radians(origin[0]), math.radians(origin[1])
    lon2, lat2 = math.radians(dest[0]),   math.radians(dest[1])

    def _xyz(lo, la):
        return (math.cos(la) * math.cos(lo),
                math.cos(la) * math.sin(lo),
                math.sin(la))

    x1, y1, z1 = _xyz(lon1, lat1)
    x2, y2, z2 = _xyz(lon2, lat2)
    dot   = max(-1.0, min(1.0, x1*x2 + y1*y2 + z1*z2))
    omega = math.acos(dot)

    points = []
    for i in range(n):
        t = i / max(n - 1, 1)
        if omega < 1e-9:
            xi, yi, zi = x1, y1, z1
        else:
            s  = math.sin(omega)
            a  = math.sin((1 - t) * omega) / s
            b  = math.sin(t * omega) / s
            xi, yi, zi = a*x1 + b*x2, a*y1 + b*y2, a*z1 + b*z2
        lat_i = math.degrees(math.atan2(zi, math.sqrt(xi**2 + yi**2)))
        lon_i = math.degrees(math.atan2(yi, xi))
        points.append((lon_i, lat_i))
    return points


def get_or_fallback_ferry_graph(env=None):
    """
    Backward-compatibility shim.  Delegates to ferry_network.py.

    This stub exists so that any legacy import of
    `simulation.spatial.rail_network.get_or_fallback_ferry_graph`
    does not raise ImportError.  All actual ferry graph logic lives
    in simulation.spatial.ferry_network.fetch_maritime_graphs().
    """
    try:
        from simulation.spatial.ferry_network import (
            fetch_maritime_graphs,
            build_hardcoded_ferry_graph,
        )
        # Derive bbox from environment drive graph
        bbox = (61.0, 49.0, 6.0, -11.0)  # full UK default
        if env is not None:
            gm    = getattr(env, 'graph_manager', None)
            drive = gm.get_graph('drive') if gm else None
            if drive is not None and drive.number_of_nodes() > 0:
                xs = [d['x'] for _, d in drive.nodes(data=True)]
                ys = [d['y'] for _, d in drive.nodes(data=True)]
                bbox = (max(ys), min(ys), max(xs), min(xs))

        graphs = fetch_maritime_graphs(bbox, city_tag='ferry_shim', use_cache=True)
        return graphs.get('ferry') or build_hardcoded_ferry_graph()
    except Exception as exc:
        logger.warning("get_or_fallback_ferry_graph shim failed: %s", exc)
        return None