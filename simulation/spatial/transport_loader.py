"""
simulation/spatial/transport_loader.py

Unified multi-layer transport graph loader for RTD_SIM.

Architecture
------------
Replaces the previous patchwork of separate per-mode loaders with a single
coherent module that downloads, caches, and returns all transport layers
needed for physically accurate multimodal routing:

    Layer          Graph key   Source
    ─────────────  ──────────  ────────────────────────────────────────────
    Road (drive)   'drive'     OSMnx network_type='drive'
    Walk           'walk'      OSMnx network_type='walk'
    Bike           'bike'      OSMnx network_type='bike'
    Tram track     'tram'      OSMnx custom_filter railway=tram|light_rail
    Rail           'rail'      OpenRailMap Overpass (railway=rail)
    GTFS transit   'transit'   TransitLand REST → local cache → synthetic
    Ferry          'ferry'     Overpass route=ferry → hardcoded UK spine
    NaPTAN stops   (list)      DfT NaPTAN CSV (stop coordinates)

BDI routing compatibility
─────────────────────────
All graphs use (lon, lat) node attributes 'x' and 'y' so Router._extract_geometry
and get_nearest_node work without changes.

Transfer edges
──────────────
After all graphs are loaded, _add_transfer_edges() links walk-graph nodes that
are within 100 m of GTFS stop coordinates, giving the BDI planner a continuous
pedestrian path from any origin to the nearest transit stop.

Caching strategy
────────────────
Each layer is cached separately under ~/.rtd_sim_cache/transport/:
  <city>_<layer>.graphml   — for NetworkX graphs (OSMnx serialisable)
  <city>_gtfs.json         — GTFS graph serialised as node/edge JSON
  <city>_naptan.json       — NaPTAN stop list
  <city>_ferry.graphml     — ferry graph

Caches older than CACHE_TTL_HOURS are refreshed automatically.

Multi-city support
──────────────────
load_transport_graphs(cities=['Edinburgh', 'Glasgow']) downloads each city
independently and stitches their graphs via nx.compose_all(), giving a
single connected graph per layer spanning the corridor.

Usage
─────
    from simulation.spatial.transport_loader import load_transport_graphs

    graphs, naptan_stops = load_transport_graphs(
        place='Edinburgh, UK',
        gtfs_feed_path='/path/to/gtfs.zip',   # optional
        use_cache=True,
    )
    # graphs is a dict: {'drive': G_drive, 'walk': G_walk, ..., 'transit': G_transit}
    # naptan_stops is a list of NaPTANStop namedtuples
    env.graph_manager.graphs.update(graphs)
    env.graph_manager.naptan_stops = naptan_stops
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from collections import namedtuple
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import networkx as nx
import requests

logger = logging.getLogger(__name__)

# ─── Cache ────────────────────────────────────────────────────────────────────
CACHE_ROOT     = Path.home() / ".rtd_sim_cache" / "transport"
CACHE_TTL_HOURS = 24

CACHE_ROOT.mkdir(parents=True, exist_ok=True)


def _cache_stale(path: Path, ttl_h: float = CACHE_TTL_HOURS) -> bool:
    if not path.exists():
        return True
    age_h = (time.time() - path.stat().st_mtime) / 3600
    return age_h > ttl_h


# ─── NaPTAN ───────────────────────────────────────────────────────────────────
NaPTANStop = namedtuple('NaPTANStop', ['atco', 'name', 'lon', 'lat', 'stop_type'])

_NAPTAN_URL = (
    "https://naptan.api.dft.gov.uk/v1/access-nodes"
    "?dataFormat=csv&status=active"
)

# Mapping NaPTAN StopType codes → human-readable labels
_NAPTAN_TYPE_MAP = {
    'RLY': 'rail', 'RSE': 'rail', 'RCE': 'rail',  # national rail
    'TMU': 'tram', 'MET': 'tram',                   # metro/tram
    'FER': 'ferry',                                  # ferry terminal
    'BCS': 'bus', 'BCT': 'bus', 'BCE': 'bus',       # bus stops
    'AIR': 'air',
}


def load_naptan(
    bbox: Optional[Tuple[float, float, float, float]] = None,
    city_tag: str = "default",
    use_cache: bool = True,
) -> List[NaPTANStop]:
    """
    Download DfT NaPTAN stop data and return as a list of NaPTANStop.

    Args:
        bbox:       (north, south, east, west) in decimal degrees.
                    If None, all UK stops are downloaded (large — ~440 k).
                    Prefer passing a bbox derived from the drive graph.
        city_tag:   Cache key prefix (e.g. 'edinburgh').
        use_cache:  Use on-disk JSON cache (refreshed every CACHE_TTL_HOURS).

    Returns:
        List[NaPTANStop] — empty list on failure.
    """
    cache_file = CACHE_ROOT / f"{city_tag}_naptan.json"
    if use_cache and not _cache_stale(cache_file):
        try:
            with open(cache_file) as f:
                raw = json.load(f)
            stops = [NaPTANStop(**s) for s in raw]
            logger.info("✅ NaPTAN: %d stops (cache: %s)", len(stops), cache_file.name)
            return stops
        except Exception as exc:
            logger.debug("NaPTAN cache read failed: %s", exc)

    logger.info("📍 Downloading NaPTAN stops (bbox=%s)…", bbox)
    try:
        import csv, io
        params: dict = {}
        if bbox is not None:
            north, south, east, west = bbox
            params = {
                'boundingBox.minLatitude':  south,
                'boundingBox.maxLatitude':  north,
                'boundingBox.minLongitude': west,
                'boundingBox.maxLongitude': east,
            }
        resp = requests.get(_NAPTAN_URL, params=params, timeout=60)
        resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.text))
        stops: List[NaPTANStop] = []
        for row in reader:
            try:
                lon = float(row.get('Longitude') or row.get('longitude', 0))
                lat = float(row.get('Latitude') or row.get('latitude', 0))
                if lon == 0 and lat == 0:
                    continue
                stop_type_raw = row.get('StopType', row.get('stop_type', ''))
                stops.append(NaPTANStop(
                    atco      = row.get('ATCOCode', row.get('atco', '')),
                    name      = row.get('CommonName', row.get('name', '')),
                    lon       = lon,
                    lat       = lat,
                    stop_type = _NAPTAN_TYPE_MAP.get(stop_type_raw[:3], 'bus'),
                ))
            except (ValueError, KeyError):
                continue

        # Cache
        try:
            with open(cache_file, 'w') as f:
                json.dump([s._asdict() for s in stops], f)
        except Exception:
            pass

        logger.info("✅ NaPTAN: %d stops downloaded", len(stops))
        return stops

    except Exception as exc:
        logger.warning("⚠️ NaPTAN download failed: %s — continuing without NaPTAN", exc)
        return []


def nearest_naptan_stop(
    coord: Tuple[float, float],
    stops: List[NaPTANStop],
    stop_types: Optional[List[str]] = None,
    max_km: float = 2.0,
) -> Optional[NaPTANStop]:
    """
    Return the nearest NaPTAN stop within max_km of coord (lon, lat).

    Args:
        coord:      (lon, lat)
        stops:      List from load_naptan()
        stop_types: Filter by NaPTAN type e.g. ['rail','tram']. None = all.
        max_km:     Maximum search radius.
    """
    lon, lat = coord
    best: Optional[NaPTANStop] = None
    best_d: float = float('inf')
    for s in stops:
        if stop_types and s.stop_type not in stop_types:
            continue
        d = _haversine_km((lon, lat), (s.lon, s.lat))
        if d < best_d and d <= max_km:
            best_d = d
            best = s
    return best


# ─── Geometry helpers ─────────────────────────────────────────────────────────

def _haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    R = 6371.0
    lon1, lat1 = math.radians(a[0]), math.radians(a[1])
    lon2, lat2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _graph_bbox(G) -> Tuple[float, float, float, float]:
    """Return (north, south, east, west) of all nodes in G."""
    xs = [d['x'] for _, d in G.nodes(data=True) if 'x' in d]
    ys = [d['y'] for _, d in G.nodes(data=True) if 'y' in d]
    if not xs:
        return (56.0, 55.85, -3.05, -3.40)  # Edinburgh default
    return (max(ys), min(ys), max(xs), min(xs))


# ─── OSMnx road / walk / bike / tram graphs ───────────────────────────────────

def _load_osmnx_graph(
    place: Optional[str],
    bbox: Optional[Tuple],         # (north, south, east, west)
    network_type: str,
    custom_filter: Optional[str],
    city_tag: str,
    use_cache: bool,
) -> Optional[object]:
    """
    Download or cache an OSMnx graph.  Returns None on failure.

    For tram/light_rail pass custom_filter='["railway"~"tram|light_rail"]'.
    For standard road/walk/bike pass network_type and custom_filter=None.
    """
    try:
        import osmnx as ox
    except ImportError:
        logger.error("osmnx not installed — cannot load OSM graphs")
        return None

    layer_id = custom_filter.strip('"[]~').replace('|', '_') if custom_filter else network_type
    cache_file = CACHE_ROOT / f"{city_tag}_{layer_id}.graphml"

    if use_cache and not _cache_stale(cache_file):
        try:
            G = ox.load_graphml(cache_file)
            logger.info(
                "✅ %s graph (cache): %d nodes, %d edges",
                layer_id, G.number_of_nodes(), G.number_of_edges(),
            )
            return G
        except Exception as exc:
            logger.debug("OSM cache read failed (%s): %s", layer_id, exc)

    logger.info("🗺️ Downloading OSM %s graph for %s…", layer_id, city_tag)
    try:
        common_kw = dict(retain_all=True)
        if custom_filter:
            common_kw['custom_filter'] = custom_filter
        else:
            common_kw['network_type'] = network_type

        if place:
            G = ox.graph_from_place(place, **common_kw)
        elif bbox:
            north, south, east, west = bbox
            G = ox.graph_from_bbox(north=north, south=south,
                                   east=east, west=west, **common_kw)
        else:
            return None

        if G is None or G.number_of_nodes() == 0:
            return None

        # Cache
        try:
            ox.save_graphml(G, cache_file)
        except Exception:
            pass

        logger.info(
            "✅ %s graph downloaded: %d nodes, %d edges",
            layer_id, G.number_of_nodes(), G.number_of_edges(),
        )
        return G

    except Exception as exc:
        logger.warning("⚠️ OSM %s graph failed: %s", layer_id, exc)
        return None


# ─── OpenRailMap rail graph ────────────────────────────────────────────────────

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_OVERPASS_TIMEOUT = 60


def _fetch_rail_overpass(
    bbox: Tuple[float, float, float, float],   # (north, south, east, west)
) -> Optional[nx.Graph]:
    """
    Build a NetworkX graph from OpenRailMap via Overpass API.
    Returns None on failure.  All nodes carry 'x' (lon) and 'y' (lat).
    """
    north, south, east, west = bbox
    query = f"""
    [out:json][timeout:{_OVERPASS_TIMEOUT}];
    (
      way["railway"~"^(rail|preserved|narrow_gauge)$"]
         ({south},{west},{north},{east});
    );
    out body geom;
    """
    try:
        resp = requests.post(_OVERPASS_URL, data={'data': query}, timeout=_OVERPASS_TIMEOUT + 10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("⚠️ OpenRailMap Overpass failed: %s", exc)
        return None

    G = nx.DiGraph()
    G.graph['name'] = 'rail'
    node_counter = 0

    for elem in data.get('elements', []):
        if elem['type'] != 'way':
            continue
        geom = elem.get('geometry', [])
        if len(geom) < 2:
            continue
        tags = elem.get('tags', {})
        railway = tags.get('railway', 'rail')

        prev_node = None
        for pt in geom:
            lon, lat = pt['lon'], pt['lat']
            # Use rounded coords as node key (reduces duplicates)
            nid = f"{lat:.5f},{lon:.5f}"
            if nid not in G:
                G.add_node(nid, x=lon, y=lat)
                node_counter += 1
            if prev_node is not None and prev_node != nid:
                prev_lon = G.nodes[prev_node]['x']
                prev_lat = G.nodes[prev_node]['y']
                length_m = _haversine_km((prev_lon, prev_lat), (lon, lat)) * 1000
                G.add_edge(prev_node, nid, length=length_m, railway=railway)
                G.add_edge(nid, prev_node, length=length_m, railway=railway)  # bidirectional
            prev_node = nid

    if G.number_of_nodes() < 2:
        return None

    # Keep only largest connected component
    components = sorted(nx.weakly_connected_components(G), key=len, reverse=True)
    G = G.subgraph(components[0]).copy()
    G.graph['name'] = 'rail'

    logger.info("✅ Rail graph: %d nodes, %d edges (Overpass)", G.number_of_nodes(), G.number_of_edges())
    return G


def load_rail_graph(
    bbox: Tuple[float, float, float, float],
    city_tag: str,
    use_cache: bool = True,
) -> Optional[nx.Graph]:
    cache_file = CACHE_ROOT / f"{city_tag}_rail.graphml"
    if use_cache and not _cache_stale(cache_file):
        try:
            G = nx.read_graphml(cache_file)
            G.graph['name'] = 'rail'
            logger.info("✅ Rail graph (cache): %d nodes", G.number_of_nodes())
            return G
        except Exception:
            pass

    G = _fetch_rail_overpass(bbox)
    if G is not None:
        try:
            nx.write_graphml(G, cache_file)
        except Exception:
            pass
    return G


# ─── Ferry graph ──────────────────────────────────────────────────────────────

_UK_FERRY_SPINE: List[Dict] = [
    # Each entry: start_name, start_lon, start_lat, end_name, end_lon, end_lat, operator
    {'s': 'Leith',       'slon': -3.177, 'slat': 55.976,
     'e': 'Kirkcaldy',   'elon': -3.163, 'elat': 56.107, 'op': 'McNeil'},
    {'s': 'Aberdeen',    'slon': -2.094, 'slat': 57.144,
     'e': 'Lerwick',     'elon': -1.143, 'elat': 60.155, 'op': 'NorthLink'},
    {'s': 'Ardrossan',   'slon': -4.814, 'slat': 55.640,
     'e': 'Brodick',     'elon': -5.140, 'elat': 55.575, 'op': 'CalMac'},
    {'s': 'Ullapool',    'slon': -5.156, 'slat': 57.895,
     'e': 'Stornoway',   'elon': -6.394, 'elat': 58.209, 'op': 'CalMac'},
    {'s': 'Oban',        'slon': -5.473, 'slat': 56.413,
     'e': 'Craignure',   'elon': -5.717, 'elat': 56.466, 'op': 'CalMac'},
]


def _fetch_ferry_overpass(bbox: Tuple) -> Optional[nx.Graph]:
    north, south, east, west = bbox
    # Add 1° padding to catch cross-sea terminals outside drive bbox
    north += 1.0; south -= 1.0; east += 1.0; west -= 1.0
    query = f"""
    [out:json][timeout:{_OVERPASS_TIMEOUT}];
    (
      relation["route"="ferry"]({south},{west},{north},{east});
    );
    out body geom;
    """
    try:
        resp = requests.post(_OVERPASS_URL, data={'data': query}, timeout=_OVERPASS_TIMEOUT + 10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("⚠️ Ferry Overpass failed: %s", exc)
        return None

    G = nx.Graph()
    G.graph['name'] = 'ferry'

    for elem in data.get('elements', []):
        if elem['type'] != 'relation':
            continue
        tags = elem.get('tags', {})
        route_name = tags.get('name', 'Ferry route')

        coords: List[Tuple[float, float]] = []
        for member in elem.get('members', []):
            geom = member.get('geometry', [])
            for pt in geom:
                coords.append((pt['lon'], pt['lat']))

        if len(coords) < 2:
            continue

        u_id = f"ferry_{len(G.nodes())}_start"
        v_id = f"ferry_{len(G.nodes())}_end"
        G.add_node(u_id, x=coords[0][0], y=coords[0][1])
        G.add_node(v_id, x=coords[-1][0], y=coords[-1][1])
        length_m = _haversine_km(coords[0], coords[-1]) * 1000
        G.add_edge(u_id, v_id,
                   name=route_name,
                   mode='ferry_diesel',
                   length=length_m,
                   shape_coords=coords)
        G.add_edge(v_id, u_id,
                   name=route_name,
                   mode='ferry_diesel',
                   length=length_m,
                   shape_coords=list(reversed(coords)))

    return G if G.number_of_nodes() > 1 else None


def _build_spine_ferry_graph() -> nx.Graph:
    """Fallback: hardcoded UK ferry spine as a NetworkX graph."""
    G = nx.Graph()
    G.graph['name'] = 'ferry'
    for i, route in enumerate(_UK_FERRY_SPINE):
        uid = f"ferry_spine_{i}_s"
        vid = f"ferry_spine_{i}_e"
        G.add_node(uid, x=route['slon'], y=route['slat'], name=route['s'])
        G.add_node(vid, x=route['elon'], y=route['elat'], name=route['e'])
        # Straight great-circle shape for spine routes
        shape = [(route['slon'], route['slat']), (route['elon'], route['elat'])]
        length_m = _haversine_km(shape[0], shape[1]) * 1000
        G.add_edge(uid, vid, name=f"{route['s']}–{route['e']}",
                   mode='ferry_diesel', length=length_m, shape_coords=shape)
        G.add_edge(vid, uid, name=f"{route['e']}–{route['s']}",
                   mode='ferry_diesel', length=length_m,
                   shape_coords=list(reversed(shape)))
    return G


def load_ferry_graph(
    bbox: Tuple,
    city_tag: str,
    use_cache: bool = True,
) -> nx.Graph:
    cache_file = CACHE_ROOT / f"{city_tag}_ferry.graphml"
    if use_cache and not _cache_stale(cache_file):
        try:
            G = nx.read_graphml(cache_file)
            G.graph['name'] = 'ferry'
            logger.info("✅ Ferry graph (cache): %d nodes", G.number_of_nodes())
            return G
        except Exception:
            pass

    G = _fetch_ferry_overpass(bbox)
    if G is None or G.number_of_nodes() < 2:
        logger.info("Ferry Overpass returned nothing — using UK spine fallback")
        G = _build_spine_ferry_graph()

    try:
        nx.write_graphml(G, cache_file)
    except Exception:
        pass

    logger.info("✅ Ferry graph: %d nodes, %d routes", G.number_of_nodes(), G.number_of_edges() // 2)
    return G


# ─── GTFS transit graph ────────────────────────────────────────────────────────

def _load_gtfs_from_file(gtfs_path: str) -> Optional[object]:
    """
    Build a GTFSGraph from a local .zip or directory.
    Returns the NetworkX graph or None.
    """
    try:
        from simulation.gtfs.gtfs_graph import GTFSGraph
        from simulation.gtfs.gtfs_loader import GTFSLoader
        loader = GTFSLoader()
        feed = loader.load(gtfs_path)
        if feed is None:
            return None
        builder = GTFSGraph(feed)
        G = builder.build()
        return G
    except ImportError:
        logger.warning("GTFSGraph/GTFSLoader not available")
        return None
    except Exception as exc:
        logger.warning("GTFS load from file failed: %s", exc)
        return None


def _download_gtfs_transitland(
    operator_onestop_id: str,
    output_dir: str = "/tmp",
    api_key: str = "",
) -> Optional[str]:
    """
    Download the latest GTFS feed for a TransitLand operator onestop ID.

    TransitLand v2 REST endpoint:
      GET /api/v2/rest/feeds?operators={operator_id}
      → follow feed download link for latest version

    Returns local path of the downloaded .zip, or None on failure.
    """
    base = "https://transit.land/api/v2/rest"
    headers = {}
    if api_key:
        headers['apikey'] = api_key

    try:
        # Step 1: resolve operator → feeds
        r = requests.get(
            f"{base}/feeds",
            params={'operators': operator_onestop_id, 'per_page': 5},
            headers=headers,
            timeout=20,
        )
        r.raise_for_status()
        feeds = r.json().get('feeds', [])
        if not feeds:
            logger.warning("No feeds found for operator: %s", operator_onestop_id)
            return None

        feed_id = feeds[0]['onestop_id']

        # Step 2: get the latest feed version download URL
        r2 = requests.get(
            f"{base}/feed_versions",
            params={'feed_onestop_id': feed_id, 'per_page': 1},
            headers=headers,
            timeout=20,
        )
        r2.raise_for_status()
        versions = r2.json().get('feed_versions', [])
        if not versions:
            return None

        dl_url = versions[0].get('url') or versions[0].get('download_url')
        if not dl_url:
            return None

        # Step 3: download the zip
        r3 = requests.get(dl_url, timeout=120, stream=True)
        r3.raise_for_status()
        out_path = os.path.join(output_dir, f"{feed_id}.zip")
        with open(out_path, 'wb') as f:
            for chunk in r3.iter_content(65536):
                f.write(chunk)

        logger.info("✅ GTFS downloaded: %s → %s", feed_id, out_path)
        return out_path

    except Exception as exc:
        logger.warning("TransitLand download failed (%s): %s", operator_onestop_id, exc)
        return None


# ─── Smart stop snapping ──────────────────────────────────────────────────────

def snap_to_graph(
    coord: Tuple[float, float],
    G,
    max_km: float = 2.0,
) -> Optional[object]:
    """
    Return the nearest graph node to coord (lon, lat) within max_km.

    Prefers nodes with 'x'/'y' attributes (OSMnx convention).
    Falls back to scanning 'lon'/'lat' keys.
    Returns None if the nearest node is beyond max_km.
    """
    lon, lat = coord
    best_node = None
    best_d = float('inf')
    for n, d in G.nodes(data=True):
        nlon = float(d.get('x', d.get('lon', 0)))
        nlat = float(d.get('y', d.get('lat', 0)))
        dist = _haversine_km((lon, lat), (nlon, nlat))
        if dist < best_d:
            best_d = dist
            best_node = n
    if best_d > max_km:
        return None
    return best_node


def snap_to_naptan(
    coord: Tuple[float, float],
    naptan_stops: List[NaPTANStop],
    stop_types: Optional[List[str]] = None,
    max_km: float = 1.0,
) -> Optional[Tuple[float, float]]:
    """
    Return the NaPTAN stop coordinate nearest to coord, or None if beyond max_km.
    Used by the router to precision-snap rail/tram access legs to platform coordinates.
    """
    hit = nearest_naptan_stop(coord, naptan_stops, stop_types=stop_types, max_km=max_km)
    if hit is None:
        return None
    return (hit.lon, hit.lat)


# ─── Transfer edges (walk ↔ transit) ─────────────────────────────────────────

def add_transfer_edges(
    G_walk,
    G_transit,
    transfer_radius_m: float = 100.0,
) -> int:
    """
    Add bidirectional transfer edges between walk-graph nodes and GTFS stop nodes.

    For each GTFS stop node, find all walk-graph nodes within transfer_radius_m
    and add synthetic edges with mode='transfer' and length=distance_m.
    This lets the router chain walk → board transit → walk without a gap.

    Returns the number of transfer edges added (divided by 2 for bidirectional).
    """
    if G_walk is None or G_transit is None:
        return 0

    # Build a flat list of (node_id, lon, lat) for walk nodes
    walk_nodes = [
        (n, float(d.get('x', 0)), float(d.get('y', 0)))
        for n, d in G_walk.nodes(data=True)
    ]

    added = 0
    radius_km = transfer_radius_m / 1000.0

    for stop_id, stop_data in G_transit.nodes(data=True):
        slон = float(stop_data.get('x', stop_data.get('lon', 0)))
        slat = float(stop_data.get('y', stop_data.get('lat', 0)))
        if slон == 0 and slat == 0:
            continue

        for wn_id, wlon, wlat in walk_nodes:
            d = _haversine_km((slон, slat), (wlon, wlat))
            if d <= radius_km:
                length_m = d * 1000
                # Add to walk graph so walk router can reach transit stop
                if not G_walk.has_edge(wn_id, stop_id):
                    G_walk.add_node(stop_id, x=slон, y=slat,
                                    name=stop_data.get('name', stop_id))
                    G_walk.add_edge(wn_id, stop_id,
                                    length=length_m, mode='transfer')
                    G_walk.add_edge(stop_id, wn_id,
                                    length=length_m, mode='transfer')
                    added += 2

    logger.info("Transfer edges: %d added (walk ↔ transit, radius=%.0fm)", added // 2, transfer_radius_m)
    return added // 2


# ─── Multi-city stitching ─────────────────────────────────────────────────────

def _stitch_graphs(graph_lists: List[Dict[str, object]]) -> Dict[str, object]:
    """
    Merge per-city graph dicts into one graph per layer using nx.compose_all.
    """
    keys = {k for city in graph_lists for k in city}
    result: Dict[str, object] = {}
    for key in keys:
        parts = [city[key] for city in graph_lists if city.get(key) is not None]
        if not parts:
            continue
        if len(parts) == 1:
            result[key] = parts[0]
        else:
            try:
                result[key] = nx.compose_all(parts)
                logger.info("Stitched %d cities for layer '%s'", len(parts), key)
            except Exception as exc:
                logger.warning("Stitch failed for '%s': %s — using first graph", key, exc)
                result[key] = parts[0]
    return result


# ─── Public API ───────────────────────────────────────────────────────────────

def load_transport_graphs(
    place: Optional[str] = None,
    bbox: Optional[Tuple] = None,             # (north, south, east, west)
    cities: Optional[List[str]] = None,       # multi-city: ['Edinburgh', 'Glasgow']
    gtfs_feed_path: Optional[str] = None,     # local GTFS zip/dir
    transitland_operator_ids: Optional[List[str]] = None,  # TransitLand auto-download
    transitland_api_key: str = "",
    naptan_bbox_pad: float = 0.3,             # degrees padding for NaPTAN query
    use_cache: bool = True,
    transfer_radius_m: float = 100.0,
    progress_callback=None,
) -> Tuple[Dict[str, object], List[NaPTANStop]]:
    """
    Load all transport layers for one or more cities/regions.

    Args:
        place:                 OSMnx place name string, e.g. 'Edinburgh, UK'.
        bbox:                  Explicit (north, south, east, west) instead of place.
        cities:                List of place strings for multi-city corridor.
                               Takes priority over ``place``.
        gtfs_feed_path:        Path to a local GTFS .zip or directory.
        transitland_operator_ids:
                               TransitLand operator onestop IDs to auto-download
                               (e.g. ['o-gcpv-lothianbuses', 'o-gcpv-edinburghtramsltd']).
                               Appended to gtfs_feed_path if both are given.
        transitland_api_key:   Optional TransitLand API key for higher rate limits.
        naptan_bbox_pad:       Degrees to expand NaPTAN bbox beyond drive graph bounds.
        use_cache:             Read/write on-disk caches.
        transfer_radius_m:     Walk-to-transit transfer edge radius (metres).
        progress_callback:     Optional callable(fraction: float, message: str).

    Returns:
        (graphs, naptan_stops)

        graphs: dict with keys:
          'drive'   — OSMnx road graph
          'walk'    — OSMnx walk graph (with transfer edges injected)
          'bike'    — OSMnx bike graph
          'tram'    — OSM tram track graph
          'rail'    — OpenRailMap graph
          'transit' — GTFS transit graph (None if no feed available)
          'ferry'   — Ferry route graph

        naptan_stops: List[NaPTANStop]
    """
    def _prog(frac, msg):
        if progress_callback:
            try:
                progress_callback(frac, msg)
            except Exception:
                pass

    # ── Resolve place list ────────────────────────────────────────────────────
    city_list: List[Tuple[Optional[str], Optional[Tuple], str]] = []
    if cities:
        for c in cities:
            tag = c.lower().replace(',', '').replace(' ', '_')[:20]
            city_list.append((c, None, tag))
    elif place:
        tag = place.lower().replace(',', '').replace(' ', '_')[:20]
        city_list.append((place, None, tag))
    elif bbox:
        city_list.append((None, bbox, 'custom_region'))
    else:
        logger.error("load_transport_graphs: provide place, bbox, or cities")
        return {}, []

    per_city_graphs: List[Dict] = []
    all_naptan: List[NaPTANStop] = []

    total_cities = len(city_list)
    for ci, (city_place, city_bbox, city_tag) in enumerate(city_list):
        base_prog = ci / total_cities
        city_graphs: Dict[str, object] = {}

        _prog(base_prog + 0.00 / total_cities, f"🛣️ Drive network: {city_place or city_tag}…")
        G_drive = _load_osmnx_graph(city_place, city_bbox, 'drive', None, city_tag, use_cache)
        city_graphs['drive'] = G_drive

        # Derive bbox from drive graph for subsequent layers
        if G_drive is not None:
            derived_bbox = _graph_bbox(G_drive)
        elif city_bbox:
            derived_bbox = city_bbox
        else:
            derived_bbox = (56.0, 55.85, -3.05, -3.40)

        _prog(base_prog + 0.10 / total_cities, f"🚶 Walk network: {city_tag}…")
        G_walk = _load_osmnx_graph(city_place, city_bbox, 'walk', None, city_tag, use_cache)
        city_graphs['walk'] = G_walk

        _prog(base_prog + 0.20 / total_cities, f"🚲 Bike network: {city_tag}…")
        G_bike = _load_osmnx_graph(city_place, city_bbox, 'bike', None, city_tag, use_cache)
        city_graphs['bike'] = G_bike

        _prog(base_prog + 0.30 / total_cities, f"🚋 Tram track: {city_tag}…")
        G_tram = _load_osmnx_graph(
            city_place, city_bbox, None,
            '["railway"~"tram|light_rail"]',
            city_tag, use_cache,
        )
        if G_tram is not None and G_tram.number_of_nodes() > 0:
            logger.info(
                "✅ Tram graph: %d nodes, %d edges",
                G_tram.number_of_nodes(), G_tram.number_of_edges(),
            )
        else:
            logger.warning("⚠️ Tram graph empty for %s — tram routes will use straight lines", city_tag)
        city_graphs['tram'] = G_tram

        _prog(base_prog + 0.40 / total_cities, f"🚆 Rail network: {city_tag}…")
        G_rail = load_rail_graph(derived_bbox, city_tag, use_cache)
        city_graphs['rail'] = G_rail

        _prog(base_prog + 0.50 / total_cities, f"⛴️ Ferry routes: {city_tag}…")
        G_ferry = load_ferry_graph(derived_bbox, city_tag, use_cache)
        city_graphs['ferry'] = G_ferry

        _prog(base_prog + 0.60 / total_cities, f"📍 NaPTAN stops: {city_tag}…")
        north, south, east, west = derived_bbox
        naptan_bbox = (
            north + naptan_bbox_pad,
            south - naptan_bbox_pad,
            east  + naptan_bbox_pad,
            west  - naptan_bbox_pad,
        )
        naptan = load_naptan(bbox=naptan_bbox, city_tag=city_tag, use_cache=use_cache)
        all_naptan.extend(naptan)

        per_city_graphs.append(city_graphs)

    # ── Stitch multi-city ─────────────────────────────────────────────────────
    graphs = _stitch_graphs(per_city_graphs) if len(per_city_graphs) > 1 else per_city_graphs[0]

    # ── GTFS transit graph ────────────────────────────────────────────────────
    _prog(0.70, "🚌 Loading GTFS transit data…")
    G_transit: Optional[object] = None

    # Local file takes priority
    if gtfs_feed_path:
        G_transit = _load_gtfs_from_file(gtfs_feed_path)

    # Auto-download from TransitLand (can supplement local file)
    if transitland_operator_ids and G_transit is None:
        for op_id in transitland_operator_ids:
            _prog(0.72, f"⬇️ TransitLand: {op_id}…")
            dl_path = _download_gtfs_transitland(
                op_id,
                output_dir="/tmp",
                api_key=transitland_api_key,
            )
            if dl_path:
                G_candidate = _load_gtfs_from_file(dl_path)
                if G_candidate is not None:
                    if G_transit is None:
                        G_transit = G_candidate
                    else:
                        # Merge additional feed into existing transit graph
                        try:
                            G_transit = nx.compose(G_transit, G_candidate)
                        except Exception as exc:
                            logger.warning("GTFS merge failed (%s): %s", op_id, exc)

    if G_transit is not None:
        logger.info(
            "✅ GTFS transit graph: %d stops, %d service edges",
            G_transit.number_of_nodes(), G_transit.number_of_edges(),
        )
    else:
        logger.warning(
            "⚠️ No GTFS feed — bus/tram use tram-graph/spine/drive-proxy fallbacks"
        )
    graphs['transit'] = G_transit

    # ── Transfer edges: walk graph ↔ GTFS stops ───────────────────────────────
    _prog(0.85, "🔗 Adding walk→transit transfer edges…")
    G_walk_stitched = graphs.get('walk')
    if G_walk_stitched is not None and G_transit is not None:
        n_transfers = add_transfer_edges(
            G_walk_stitched, G_transit, transfer_radius_m=transfer_radius_m
        )
        graphs['walk'] = G_walk_stitched  # update with transfer edges

    # ── De-duplicate NaPTAN stops across cities ───────────────────────────────
    seen_atco: set = set()
    unique_naptan: List[NaPTANStop] = []
    for s in all_naptan:
        if s.atco and s.atco not in seen_atco:
            seen_atco.add(s.atco)
            unique_naptan.append(s)

    _prog(1.00, "✅ Transport layers loaded")
    _log_summary(graphs, unique_naptan)
    return graphs, unique_naptan


def _log_summary(graphs: Dict, naptan_stops: List) -> None:
    """Log a one-line summary of every loaded layer."""
    logger.info("=" * 60)
    logger.info("RTD_SIM Transport Layer Summary")
    logger.info("=" * 60)
    layer_labels = {
        'drive':   '🛣️  Drive',
        'walk':    '🚶 Walk ',
        'bike':    '🚲 Bike ',
        'tram':    '🚋 Tram ',
        'rail':    '🚆 Rail ',
        'transit': '🚌 GTFS ',
        'ferry':   '⛴️  Ferry',
    }
    for key, label in layer_labels.items():
        G = graphs.get(key)
        if G is None:
            logger.info("  %s  ——— not loaded", label)
        else:
            logger.info(
                "  %s  %5d nodes  %6d edges",
                label, G.number_of_nodes(), G.number_of_edges(),
            )
    logger.info("  📍 NaPTAN   %5d stops", len(naptan_stops))
    logger.info("=" * 60)


# ─── BDI-compatible graph accessor ────────────────────────────────────────────

def register_graphs_on_env(env, graphs: Dict, naptan_stops: List[NaPTANStop]) -> None:
    """
    Register all loaded transport layers on a SpatialEnvironment.
    Equivalent to the piecemeal registrations in environment_setup.py,
    but done in one call after load_transport_graphs().

    Usage:
        graphs, naptan = load_transport_graphs(place='Edinburgh, UK')
        register_graphs_on_env(env, graphs, naptan)
    """
    for key, G in graphs.items():
        if G is not None:
            env.graph_manager.graphs[key] = G

    env.naptan_stops = naptan_stops
    env.graph_manager.naptan_stops = naptan_stops  # type: ignore[attr-defined]

    # Ensure graph_loaded flag is set if drive graph is present
    if graphs.get('drive') is not None:
        env.graph_loaded = True

    logger.info(
        "✅ Registered %d transport layers + %d NaPTAN stops on SpatialEnvironment",
        sum(1 for G in graphs.values() if G is not None),
        len(naptan_stops),
    )
