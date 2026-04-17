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


# =============================================================================
# FERRY GRAPH
# =============================================================================

# Hardcoded UK ferry terminal pairs — (route_name, (origin_lon, origin_lat), (dest_lon, dest_lat))
# Used as offline fallback when the Overpass query fails.
# Covers all major domestic crossings, Irish Sea, North Sea, and English Channel.
_UK_FERRY_ROUTES = [
    # Irish Sea — Scotland
    ("Cairnryan_Belfast",           (-5.012, 55.003), (-5.930, 54.612)),
    ("Cairnryan_Larne",             (-5.012, 55.003), (-5.820, 54.858)),
    # Irish Sea — Wales / England
    ("Holyhead_Dublin",             (-4.620, 53.306), (-6.222, 53.341)),
    ("Holyhead_DunLaoghaire",       (-4.620, 53.306), (-6.135, 53.300)),
    ("Pembroke_Rosslare",           (-4.930, 51.673), (-6.340, 52.254)),
    ("Fishguard_Rosslare",          (-4.979, 51.994), (-6.340, 52.254)),
    ("Liverpool_Dublin",            (-3.002, 53.408), (-6.222, 53.341)),
    # English Channel
    ("Dover_Calais",                (1.357,  51.124), (1.850,  50.972)),
    ("Dover_Dunkirk",               (1.357,  51.124), (2.374,  51.038)),
    ("Newhaven_Dieppe",             (0.058,  50.793), (1.076,  49.920)),
    ("Portsmouth_Cherbourg",        (-1.105, 50.798), (-1.625, 49.645)),
    ("Portsmouth_Caen",             (-1.105, 50.798), (-0.362, 49.182)),
    ("Portsmouth_StMalo",           (-1.105, 50.798), (-2.026, 48.649)),
    ("Portsmouth_Santander",        (-1.105, 50.798), (-3.794, 43.463)),
    ("Plymouth_Roscoff",            (-4.143, 50.367), (-3.983, 48.724)),
    ("Plymouth_Santander",          (-4.143, 50.367), (-3.794, 43.463)),
    ("Poole_Cherbourg",             (-1.992, 50.719), (-1.625, 49.645)),
    # North Sea
    ("Newcastle_Amsterdam",         (-1.594, 54.970), (4.900,  52.413)),
    ("Hull_Rotterdam",              (-0.200, 53.740), (4.460,  51.890)),
    ("Hull_Zeebrugge",              (-0.200, 53.740), (3.200,  51.330)),
    ("Harwich_HoekVanHolland",      (1.281,  51.947), (4.123,  51.978)),
    ("Harwich_Esbjerg",             (1.281,  51.947), (8.460,  55.467)),
    # Scottish Northern Isles
    ("Aberdeen_Lerwick",            (-2.079, 57.151), (-1.139, 60.153)),
    ("Aberdeen_Kirkwall",           (-2.079, 57.151), (-2.965, 58.988)),
    ("Scrabster_Stromness",         (-3.543, 58.613), (-3.295, 58.958)),
    ("Gill_Kirkwall",               (-2.920, 58.627), (-2.965, 58.988)),
    # Hebrides & West Scotland
    ("Ullapool_Stornoway",          (-5.157, 57.896), (-6.374, 58.209)),
    ("Oban_Craignure",              (-5.478, 56.413), (-5.698, 56.463)),
    ("Oban_Colonsay",               (-5.478, 56.413), (-6.188, 56.064)),
    ("Oban_Castlebay",              (-5.478, 56.413), (-7.493, 57.003)),
    ("Oban_Lochboisdale",           (-5.478, 56.413), (-7.323, 57.155)),
    ("Mallaig_Armadale",            (-5.827, 57.007), (-5.897, 57.068)),
    ("Tarbert_Portavadie",          (-5.409, 55.868), (-5.315, 55.877)),
    ("Gourock_Dunoon",              (-4.817, 55.963), (-4.924, 55.949)),
    ("Wemyss_Rothesay",             (-4.886, 55.874), (-5.053, 55.838)),
    ("Ardrossan_Brodick",           (-4.825, 55.641), (-5.141, 55.576)),
    ("Kennacraig_PortEllen",        (-5.488, 55.803), (-6.190, 55.633)),
    ("Kennacraig_PortAskaig",       (-5.488, 55.803), (-6.107, 55.850)),
    # Firth of Clyde
    ("Gourock_Kilcreggan",          (-4.817, 55.963), (-4.684, 55.982)),
    # Firth of Forth
    ("SouthQueensferry_NorthQF",    (-3.398, 55.990), (-3.393, 56.001)),
    # Isle of Wight
    ("Portsmouth_Fishbourne",       (-1.105, 50.798), (-1.124, 50.732)),
    ("Southampton_Cowes",           (-1.404, 50.897), (-1.297, 50.762)),
    ("Lymington_Yarmouth",          (-1.549, 50.775), (-1.499, 50.709)),
    # Isles of Scilly
    ("Penzance_StMarys",            (-5.534, 50.120), (-6.296, 49.919)),
]


def _great_circle_waypoints(
    origin: Tuple[float, float],
    dest: Tuple[float, float],
    n: int = 12,
) -> list:
    """Return n evenly-spaced great-circle interpolation points between origin and dest."""
    return [
        (origin[0] + (dest[0] - origin[0]) * i / (n - 1),
         origin[1] + (dest[1] - origin[1]) * i / (n - 1))
        for i in range(n)
    ]


def fetch_ferry_graph(
    bbox: Tuple[float, float, float, float],
) -> Optional[nx.MultiDiGraph]:
    """
    Download ferry route geometry from the OpenStreetMap Overpass API.

    Queries for:
      • route=ferry relations
      • way[route=ferry] ways
      • way[ferry=yes] ways

    Each OSM way/relation is turned into a bi-directional pair of edges in a
    NetworkX MultiDiGraph keyed as ``graph['name'] == 'ferry'``.  Nodes
    represent port terminals (or intermediate waypoints for long crossings).
    Edges carry:
      shape_coords  — list of (lon, lat) tuples for visualisation
      mode          — 'ferry_diesel'
      length        — edge length in metres (haversine)
      name          — operator/route name from OSM tags

    Args:
        bbox: (north, south, east, west) — RTD_SIM internal convention.
              Internally expanded by 0.3° to capture cross-boundary terminals
              without pulling in continental routes outside the simulation region.

    Returns:
        NetworkX MultiDiGraph tagged graph['name']='ferry', or None on failure.
    """
    if not _NX:
        return None

    import urllib.request
    import json

    north, south, east, west = bbox
    # Expand by 2° to capture terminals that sit outside the drive graph bbox
    # 0.3° padding captures cross-boundary terminals without pulling in
    # continental routes (e.g. Amsterdam/Hook of Holland from an Edinburgh bbox).
    # The hardcoded _UK_FERRY_ROUTES spine provides long-haul sea freight
    # routes when they are needed by the simulation scenario.
    north, south, east, west = north + 0.3, south - 0.3, east + 0.3, west - 0.3

    query = (
        "[out:json][timeout:30];"
        "("
        f'  relation["route"="ferry"]({south},{west},{north},{east});'
        f'  way["route"="ferry"]({south},{west},{north},{east});'
        f'  way["ferry"="yes"]({south},{west},{north},{east});'
        ");"
        "out body;>;out skel qt;"
    )
    overpass_url = "https://overpass-api.de/api/interpreter"
    try:
        req = urllib.request.Request(
            overpass_url,
            data=query.encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=35) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        logger.warning("Overpass ferry query failed: %s", exc)
        return None

    elements   = data.get("elements", [])
    osm_nodes  = {
        el["id"]: (float(el["lon"]), float(el["lat"]))
        for el in elements
        if el["type"] == "node"
    }
    ways = [el for el in elements if el["type"] == "way"]

    if not ways:
        logger.warning("fetch_ferry_graph: Overpass returned 0 ferry ways")
        return None

    G = nx.MultiDiGraph()
    G.graph["name"] = "ferry"

    _node_index: dict = {}   # (lon4, lat4) → node_id
    _next_id: list = [0]

    def _get_node(lon: float, lat: float, name: str = "") -> int:
        key = (round(lon, 4), round(lat, 4))
        if key in _node_index:
            return _node_index[key]
        nid = _next_id[0]
        _next_id[0] += 1
        G.add_node(nid, x=lon, y=lat, name=name)
        _node_index[key] = nid
        return nid

    from simulation.spatial.coordinate_utils import haversine_km as _hav

    added = 0
    for way in ways:
        node_refs = way.get("nodes", [])
        coords    = [osm_nodes[n] for n in node_refs if n in osm_nodes]
        if len(coords) < 2:
            continue
        tags     = way.get("tags", {})
        name_tag = tags.get("name") or tags.get("operator") or ""

        try:
            from shapely.geometry import LineString as _LS
            geom_fwd = _LS(coords)
            geom_rev = _LS(list(reversed(coords)))
        except Exception:
            geom_fwd = geom_rev = None

        u_nid = _get_node(*coords[0])
        v_nid = _get_node(*coords[-1])
        if u_nid == v_nid:
            continue

        dist_m = _hav(coords[0], coords[-1]) * 1000.0
        G.add_edge(u_nid, v_nid,
                   shape_coords=coords,
                   geometry=geom_fwd,
                   mode="ferry_diesel",
                   length=dist_m,
                   name=name_tag,
                   operator=tags.get("operator", ""))
        G.add_edge(v_nid, u_nid,
                   shape_coords=list(reversed(coords)),
                   geometry=geom_rev,
                   mode="ferry_diesel",
                   length=dist_m,
                   name=name_tag)
        added += 1

    logger.info(
        "✅ Ferry graph (Overpass): %d terminals, %d routes",
        G.number_of_nodes(), added,
    )
    return G if G.number_of_nodes() > 1 else None


def build_hardcoded_ferry_graph() -> Optional[nx.MultiDiGraph]:
    """
    Build a lightweight ferry graph from the hardcoded ``_UK_FERRY_ROUTES`` list.

    Used as offline fallback when the Overpass query fails.  Each route is
    represented by 12 great-circle interpolation points so ferry paths are
    rendered as smooth arcs rather than single straight lines.

    Returns:
        NetworkX MultiDiGraph tagged graph['name']='ferry'.
    """
    if not _NX:
        return None

    from simulation.spatial.coordinate_utils import haversine_km as _hav

    G = nx.MultiDiGraph()
    G.graph["name"] = "ferry"

    for route_name, (olon, olat), (dlon, dlat) in _UK_FERRY_ROUTES:
        u = f"port_{olon:.4f}_{olat:.4f}"
        v = f"port_{dlon:.4f}_{dlat:.4f}"

        origin_label = route_name.split("_")[0]
        dest_label   = "_".join(route_name.split("_")[1:])

        if not G.has_node(u):
            G.add_node(u, x=olon, y=olat, name=origin_label)
        if not G.has_node(v):
            G.add_node(v, x=dlon, y=dlat, name=dest_label)

        dist_m = _hav((olon, olat), (dlon, dlat)) * 1000.0
        waypoints_fwd = _great_circle_waypoints((olon, olat), (dlon, dlat))
        waypoints_rev = list(reversed(waypoints_fwd))

        for u2, v2, wpts in [(u, v, waypoints_fwd), (v, u, waypoints_rev)]:
            G.add_edge(u2, v2,
                       shape_coords=wpts,
                       mode="ferry_diesel",
                       length=dist_m,
                       name=route_name)

    logger.info(
        "✅ Ferry spine (hardcoded): %d terminals, %d routes",
        G.number_of_nodes(), len(_UK_FERRY_ROUTES),
    )
    return G


def get_or_fallback_ferry_graph(env=None) -> Optional[nx.MultiDiGraph]:
    """
    Try Overpass ferry fetch; fall back to hardcoded UK spine.

    The bbox is derived from the drive graph nodes when *env* is supplied.
    A 2° expansion is applied inside ``fetch_ferry_graph`` so terminals
    outside the simulation region are still captured.

    Args:
        env: SpatialEnvironment — used to derive the bbox.
             Pass None to use a full-UK bounding box.

    Returns:
        NetworkX MultiDiGraph (Overpass result or hardcoded spine).
    """
    bbox = None

    if env is not None:
        gm = getattr(env, "graph_manager", None)
        if gm is not None:
            drive = gm.get_graph("drive")
            if drive is not None and len(drive.nodes) > 0:
                xs   = [d["x"] for _, d in drive.nodes(data=True)]
                ys   = [d["y"] for _, d in drive.nodes(data=True)]
                bbox = (max(ys), min(ys), max(xs), min(xs))

    if bbox is None:
        # Full UK + Ireland + near-Continent
        bbox = (61.0, 49.0, 6.0, -11.0)
        logger.info("get_or_fallback_ferry_graph: no drive graph — using full-UK bbox")

    G = fetch_ferry_graph(bbox)
    if G is not None and G.number_of_nodes() > 1:
        return G

    logger.warning(
        "Overpass ferry fetch failed or empty — falling back to hardcoded spine"
    )
    return build_hardcoded_ferry_graph()

# Module-level cache so fetch_tram_relations_overpass is only called once per
# process regardless of how many agents trigger the lazy-load path.
_TRAM_RELATIONS_CACHE: Optional[List[List[Tuple[float, float]]]] = None
_TRAM_RELATIONS_FETCHED: bool = False


def fetch_tram_relations_overpass(
    bbox: Tuple[float, float, float, float],
) -> List[List[Tuple[float, float]]]:
    """
    Download Edinburgh tram route relations from the Overpass API.

    Returns a list of polylines — one list of (lon, lat) tuples per tram
    route relation found within the bbox.  Returns [] on any failure.

    Implementation notes
    --------------------
    • Uses ``urllib.request`` (stdlib) not ``requests`` — rail_network.py
      already uses urllib for the ferry Overpass query; keeping the same
      HTTP client avoids an extra dependency and makes the network call
      pattern consistent across the module.
    • The query uses ``out geom;`` on the relation so each member way's
      geometry is returned inline without a second ``node`` lookup.
    • A module-level flag prevents repeated API calls across a session.
      The tram track geometry is static; downloading it once is enough.
    • HTTP non-200 responses and JSON parse failures both return [] so
      the caller receives an empty list and falls through to the tram-spine
      fallback — never crashes the planning pipeline.

    Overpass query
    --------------
    ``relation["route"="tram"]`` filtered by bbox with ``out geom`` returns
    each relation's member ways with their full node coordinates.
    """
    global _TRAM_RELATIONS_CACHE, _TRAM_RELATIONS_FETCHED  # noqa: PLW0603

    # Return cached result (including empty list from a prior failed fetch)
    if _TRAM_RELATIONS_FETCHED:
        return _TRAM_RELATIONS_CACHE or []

    _TRAM_RELATIONS_FETCHED = True

    import urllib.request
    import json as _json

    north, south, east, west = bbox
    logger.info("Fetching OSM Tram relations via Overpass API (bbox=%.3f,%.3f,%.3f,%.3f)…",
                south, west, north, east)

    # Overpass QL: fetch tram route relations with inline geometry.
    # "out geom" returns each member way's node coordinates so we don't need
    # a separate node-lookup query.
    query = (
        f"[out:json][timeout:30];"
        f'relation["route"="tram"]({south},{west},{north},{east});'
        f"out geom;"
    ).encode("utf-8")

    overpass_url = "https://overpass-api.de/api/interpreter"
    try:
        req = urllib.request.Request(
            overpass_url,
            data=query,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=35) as resp:
            # Check HTTP status before attempting JSON parse.
            # Overpass returns 429 (rate limit) or 504 (gateway timeout) as
            # non-200; reading the empty body then calling json.loads crashes
            # with "Expecting value: line 1 column 1 (char 0)".
            status = getattr(resp, 'status', 200)
            raw = resp.read()
            if status != 200:
                logger.warning(
                    "Overpass tram query returned HTTP %d — "
                    "falling back to tram graph / spine",
                    status,
                )
                _TRAM_RELATIONS_CACHE = []
                return []
            if not raw:
                logger.warning("Overpass tram query returned empty body")
                _TRAM_RELATIONS_CACHE = []
                return []
            data = _json.loads(raw)
    except Exception as exc:
        logger.error("❌ Overpass tram relation fetch failed: %s", exc)
        _TRAM_RELATIONS_CACHE = []
        return []

    tram_routes: List[List[Tuple[float, float]]] = []
    for element in data.get("elements", []):
        if element.get("type") != "relation":
            continue
        route_coords: List[Tuple[float, float]] = []
        for member in element.get("members", []):
            if member.get("type") == "way" and "geometry" in member:
                for pt in member["geometry"]:
                    try:
                        route_coords.append((float(pt["lon"]), float(pt["lat"])))
                    except (KeyError, TypeError, ValueError):
                        continue
        if len(route_coords) >= 2:
            tram_routes.append(route_coords)

    logger.info("✅ Downloaded %d physical tram relations via Overpass.", len(tram_routes))
    _TRAM_RELATIONS_CACHE = tram_routes
    return tram_routes