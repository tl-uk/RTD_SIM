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

# Synthetic transfer-edge constants used by link_to_road_network().
_TRANSFER_LENGTH_M    = 300
_TRANSFER_TIME_H      = 0.25   # 15-min boarding penalty expressed as hours
_TRANSFER_HIGHWAY_TAG = 'transfer'


def fetch_rail_graph(
    bbox: Tuple[float, float, float, float],
) -> Optional[object]:
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
    rail_filter = '["railway"~"rail|tram|subway|light_rail"]'

    try:
        # OSMnx 2.x expects (left, bottom, right, top) = (west, south, east, north).
        G_directed = ox.graph_from_bbox(
            bbox=(west, south, east, north),
            custom_filter=rail_filter,
            simplify=True,
            retain_all=True,
        )
    except TypeError:
        # OSMnx 1.x positional fallback — still uses the correct axis order.
        try:
            G_directed = ox.graph_from_bbox(
                north, south, east, west,
                custom_filter=rail_filter,
                retain_all=True,
                simplify=True,
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


def get_or_fallback_rail_graph(env=None) -> Optional[object]:
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

# =============================================================================
# FERRY ROUTES
# Hardcoded UK ferry terminal pairs (lon, lat) for offline fallback
# =============================================================================
_UK_FERRY_ROUTES = [
    ("Cairnryan_Belfast",         (-5.012, 55.003), (-5.930, 54.612)),
    ("Cairnryan_Larne",           (-5.012, 55.003), (-5.820, 54.858)),
    ("Holyhead_Dublin",           (-4.620, 53.306), (-6.222, 53.341)),
    ("Pembroke_Rosslare",         (-4.930, 51.673), (-6.340, 52.254)),
    ("Dover_Calais",              (1.357,  51.124), (1.850,  50.972)),
    ("Dover_Dunkirk",             (1.357,  51.124), (2.374,  51.038)),
    ("Portsmouth_Santander",      (-1.105, 50.798), (-3.794, 43.463)),
    ("Plymouth_Roscoff",          (-4.143, 50.367), (-3.983, 48.724)),
    ("Newcastle_Amsterdam",       (-1.594, 54.970), (4.900,  52.413)),
    ("Hull_Rotterdam",            (-0.200, 53.740), (4.460,  51.890)),
    ("Scrabster_Stromness",       (-3.543, 58.613), (-3.295, 58.958)),
    ("Aberdeen_Lerwick",          (-2.079, 57.151), (-1.139, 60.153)),
    ("Ullapool_Stornoway",        (-5.157, 57.896), (-6.374, 58.209)),
    ("Oban_Craignure",            (-5.478, 56.413), (-5.698, 56.463)),
    ("Gourock_Dunoon",            (-4.817, 55.963), (-4.924, 55.949)),
    ("Portsmouth_Fishbourne",     (-1.105, 50.798), (-1.124, 50.732)),
    ("Southampton_Cowes",         (-1.404, 50.897), (-1.297, 50.762)),
    ("SouthQueensferry_North",    (-3.398, 55.990), (-3.393, 56.001)),  # Forth Ferry
]

def fetch_ferry_graph(bbox):
    """
    Fetch ferry route relations from OSM Overpass API.
    Returns NetworkX MultiDiGraph keyed as 'ferry', or None.
    Nodes carry x (lon) / y (lat) / name.
    Edges carry shape_coords, mode='ferry_diesel', length_km.
    """
    import urllib.request, json
    try:
        import networkx as nx
    except ImportError:
        return None

    north, south, east, west = bbox
    query = (
        f"[out:json][timeout:30];"
        f"("
        f'  relation["route"="ferry"]({south},{west},{north},{east});'
        f'  way["route"="ferry"]({south},{west},{north},{east});'
        f'  way["ferry"="yes"]({south},{west},{north},{east});'
        f");"
        f"out body;>;out skel qt;"
    )
    url = "https://overpass-api.de/api/interpreter"
    try:
        req = urllib.request.Request(
            url, data=query.encode(), method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        logger.warning("Overpass ferry fetch failed: %s", exc)
        return None

    elements = data.get("elements", [])
    nodes_by_id = {
        el["id"]: (el["lon"], el["lat"])
        for el in elements if el["type"] == "node"
    }
    ways = [el for el in elements if el["type"] == "way"]

    G = nx.MultiDiGraph()
    G.graph["name"] = "ferry"

    node_id_counter = 0
    def _get_or_add_node(lon, lat, name=""):
        nonlocal node_id_counter
        # round to 4 dp to deduplicate near-identical terminals
        key = (round(lon, 4), round(lat, 4))
        for nid, nd in G.nodes(data=True):
            if round(nd.get("x", 0), 4) == key[0] and round(nd.get("y", 0), 4) == key[1]:
                return nid
        nid = node_id_counter
        node_id_counter += 1
        G.add_node(nid, x=lon, y=lat, name=name)
        return nid

    from simulation.spatial.coordinate_utils import haversine_km
    for way in ways:
        coords = [nodes_by_id[n] for n in way.get("nodes", []) if n in nodes_by_id]
        if len(coords) < 2:
            continue
        u_nid = _get_or_add_node(*coords[0])
        v_nid = _get_or_add_node(*coords[-1])
        if u_nid == v_nid:
            continue
        try:
            from shapely.geometry import LineString
            geom = LineString(coords)
        except Exception:
            geom = None
        dist_km = haversine_km(coords[0], coords[-1])
        tags = way.get("tags", {})
        G.add_edge(u_nid, v_nid,
                   shape_coords=coords, geometry=geom,
                   mode="ferry_diesel", length=dist_km * 1000,
                   length_km=dist_km,
                   name=tags.get("name", ""),
                   operator=tags.get("operator", ""))
        # bi-directional
        G.add_edge(v_nid, u_nid,
                   shape_coords=list(reversed(coords)), geometry=geom,
                   mode="ferry_diesel", length=dist_km * 1000,
                   length_km=dist_km)

    logger.info("Ferry graph (Overpass): %d nodes, %d edges", G.number_of_nodes(), G.number_of_edges())
    return G if G.number_of_nodes() > 1 else None


def build_hardcoded_ferry_graph():
    """Build a lightweight ferry graph from the hardcoded UK route list."""
    try:
        import networkx as nx
        from simulation.spatial.coordinate_utils import haversine_km
    except ImportError:
        return None

    G = nx.MultiDiGraph()
    G.graph["name"] = "ferry"
    for name, (olon, olat), (dlon, dlat) in _UK_FERRY_ROUTES:
        u = f"port_{olon:.3f}_{olat:.3f}"
        v = f"port_{dlon:.3f}_{dlat:.3f}"
        G.add_node(u, x=olon, y=olat, name=name.split("_")[0])
        G.add_node(v, x=dlon, y=dlat, name=name.split("_")[-1])
        dist_km = haversine_km((olon, olat), (dlon, dlat))
        # 10 intermediate great-circle points for smooth display
        coords = [(olon + (dlon - olon) * t / 9, olat + (dlat - olat) * t / 9) for t in range(10)]
        for u2, v2, c in [(u, v, coords), (v, u, list(reversed(coords)))]:
            G.add_edge(u2, v2, shape_coords=c, mode="ferry_diesel",
                       length=dist_km * 1000, length_km=dist_km, name=name)
    logger.info("Ferry spine (hardcoded): %d routes", len(_UK_FERRY_ROUTES))
    return G


def get_or_fallback_ferry_graph(env=None):
    """Try Overpass; fall back to hardcoded spine."""
    bbox = None
    if env is not None:
        drive = getattr(env, "graph_manager", None) and env.graph_manager.get_graph("drive")
        if drive and len(drive.nodes) > 0:
            xs = [d["x"] for _, d in drive.nodes(data=True)]
            ys = [d["y"] for _, d in drive.nodes(data=True)]
            # Expand bbox by 2° to capture cross-sea routes
            bbox = (max(ys) + 2.0, min(ys) - 2.0, max(xs) + 2.0, min(xs) - 2.0)
    if bbox is None:
        bbox = (60.0, 49.0, 5.0, -10.0)  # Full UK + Irish Sea

    G = fetch_ferry_graph(bbox)
    if G and G.number_of_nodes() > 1:
        return G
    logger.warning("Ferry Overpass failed — using hardcoded spine")
    return build_hardcoded_ferry_graph()

def link_to_road_network(
    G_rail: object,
    G_road: object,
    radius_m: int = 300,
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