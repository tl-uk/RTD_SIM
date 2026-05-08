"""
simulation/spatial/bus_network.py

Bus shape enrichment pipeline for RTD_SIM.

PURPOSE
───────
The BODS GTFS feed for Scotland/UK is shape-incomplete: shapes.txt is missing
for many bus trips, causing the transit graph to have edges with shape_coords=[].
At routing time those edges receive straight-line interpolation that cuts
through buildings, parks, and water.

This module fills every empty shape_coords by routing between the two stop
coordinates on the OSMnx drive graph, producing road-following geometry.
This is done ONCE at setup time, after GTFSGraph.build(), and cached to disk
so subsequent runs are instant.

It is NOT a bus-lane extractor.  Buses run on all roads, not just busway-
tagged streets (fewer than 2% of Edinburgh bus routes have busway/lanes:bus
OSM tags).  Attempting to route on bus-tagged roads alone produces an
almost-empty graph that covers nothing useful.

INTEGRATION
───────────
Called from environment_setup.setup_environment() after GTFS graph is built:

    from simulation.spatial.bus_network import enrich_transit_shapes
    enrich_transit_shapes(env.graph_manager, city_tag=city_tag)

ARCHITECTURE
────────────
1. Iterate every edge (u, v) in G_transit with shape_coords == []
2. Get the lon/lat of stops u and v from G_transit.nodes
3. Snap each to the nearest OSMnx drive graph node
4. nx.shortest_path(drive_graph, u_node, v_node, weight='length')
5. Extract Shapely edge geometry into (lon, lat) list
6. Store back on the transit edge as shape_coords
7. Cache the (stop_u_id, stop_v_id) → coords mapping to disk

All enriched shapes are stored in memory on the graph object AND persisted
to a lightweight JSON cache so the operation runs in <1 s on re-runs.
"""

from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CACHE_ROOT  = Path.home() / ".rtd_sim_cache" / "transport"
CACHE_TTL_H = 72.0
CACHE_ROOT.mkdir(parents=True, exist_ok=True)


# ── Geometry helpers ─────────────────────────────────────────────────────────

def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    R = 6_371_000.0
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a  = math.sin(dp / 2)**2 + (
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
        * math.sin(dl / 2)**2
    )
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _extract_drive_path_coords(
    drive_graph,
    node_path: List,
) -> List[Tuple[float, float]]:
    """
    Convert a list of OSMnx node IDs into a (lon, lat) polyline.

    Uses Shapely geometry when present (accurate road curves); falls back
    to node centroids for edges that lack geometry.
    """
    coords: List[Tuple[float, float]] = []
    for i in range(len(node_path) - 1):
        u, v = node_path[i], node_path[i + 1]
        # MultiDiGraph: get_edge_data returns {key: attr_dict}
        edge_bundle = drive_graph.get_edge_data(u, v)
        if edge_bundle is None:
            n_data = drive_graph.nodes.get(v, {})
            coords.append((float(n_data.get('x', 0)), float(n_data.get('y', 0))))
            continue
        # Pick the first parallel edge
        if isinstance(edge_bundle, dict) and 0 in edge_bundle:
            edge_data = edge_bundle[0]
        elif isinstance(edge_bundle, dict):
            edge_data = next(iter(edge_bundle.values()))
        else:
            edge_data = edge_bundle

        geom = edge_data.get('geometry')
        if geom is not None and hasattr(geom, 'coords'):
            # Shapely LineString — skip the first point (already added as prev v)
            edge_pts = list(geom.coords)
            coords.extend(edge_pts[1:] if i > 0 else edge_pts)
        else:
            n_data = drive_graph.nodes.get(v, {})
            coords.append((float(n_data.get('x', 0)), float(n_data.get('y', 0))))
    return coords


# ── Main enrichment function ─────────────────────────────────────────────────

def enrich_transit_shapes(
    graph_manager,
    city_tag: str = "default",
    max_stop_snap_m: float = 400.0,
    batch_log_every: int = 200,
) -> int:
    """
    Fill empty shape_coords on every transit edge by routing on the drive graph.

    Args:
        graph_manager:    GraphManager with 'transit' and 'drive' graphs registered.
        city_tag:         Cache key prefix (use the simulation place name).
        max_stop_snap_m:  Maximum distance (metres) to snap a GTFS stop to a
                          drive graph node.  Stops further away than this are
                          skipped (they are likely outside the drive graph bbox).
        batch_log_every:  Log a progress line every N enriched edges.

    Returns:
        Number of edges enriched.
    """
    try:
        import networkx as nx
    except ImportError:
        logger.error("NetworkX not available — bus shape enrichment skipped")
        return 0

    G_transit = graph_manager.get_graph('transit')
    G_drive   = graph_manager.get_graph('drive')

    if G_transit is None:
        logger.warning("No transit graph registered — bus shape enrichment skipped")
        return 0
    if G_drive is None:
        logger.warning("No drive graph registered — bus shape enrichment skipped")
        return 0

    # ── Load cache ────────────────────────────────────────────────────────────
    cache_path = CACHE_ROOT / f"{city_tag}_bus_shapes.json"
    shape_cache: Dict[str, List] = {}
    if cache_path.exists():
        age_h = (time.time() - cache_path.stat().st_mtime) / 3600
        if age_h < CACHE_TTL_H:
            try:
                shape_cache = json.loads(cache_path.read_text())
                logger.info(
                    "Bus shape cache loaded: %d entries (%.1fh old)",
                    len(shape_cache), age_h,
                )
            except Exception as exc:
                logger.debug("Bus shape cache unreadable (%s) — rebuilding", exc)

    # ── Build drive-node lookup: (lon, lat) → nearest drive node ─────────────
    # We use a simple linear scan here because the drive graph is small enough
    # (<100k nodes for Edinburgh) and each stop is only looked up once.
    def _nearest_drive_node(lon: float, lat: float) -> Optional[int]:
        """Return nearest drive graph node within max_stop_snap_m."""
        best_node, best_dist = None, float('inf')
        for node, data in G_drive.nodes(data=True):
            d = _haversine_m(lon, lat, float(data.get('x', 0)), float(data.get('y', 0)))
            if d < best_dist:
                best_dist, best_node = d, node
        if best_dist <= max_stop_snap_m:
            return best_node
        return None

    # Pre-build node list for efficiency
    _drive_nodes = [
        (node, float(data.get('x', 0)), float(data.get('y', 0)))
        for node, data in G_drive.nodes(data=True)
    ]

    def _fast_nearest(lon: float, lat: float) -> Optional:
        best_node, best_dist = None, float('inf')
        for node, nx_, ny_ in _drive_nodes:
            # Fast Euclidean pre-filter (degrees × 111km)
            dx = (nx_ - lon) * 111_320 * math.cos(math.radians(lat))
            dy = (ny_ - lat) * 111_320
            d  = math.sqrt(dx * dx + dy * dy)
            if d < best_dist:
                best_dist, best_node = d, node
        # Convert degrees-distance back to metres for threshold check
        return best_node if best_dist * 1000 <= max_stop_snap_m else None

    # ── Iterate transit edges ─────────────────────────────────────────────────
    enriched = 0
    skipped_no_snap  = 0
    skipped_no_path  = 0
    cache_hits       = 0

    all_edges = list(G_transit.edges(keys=True, data=True))
    empty_edges = [
        (u, v, k, d) for u, v, k, d in all_edges
        if (d.get('mode', 'bus') not in ('walk',) and
            d.get('highway') != 'transfer' and
            not d.get('shape_coords'))
    ]

    total = len(empty_edges)
    logger.info(
        "Bus shape enrichment: %d / %d transit edges lack geometry — filling now",
        total, len(all_edges),
    )
    if total == 0:
        logger.info("All transit edges already have shape_coords — nothing to enrich")
        return 0

    for u, v, k, data in empty_edges:
        cache_key = f"{u}|{v}"

        # ── Cache hit ─────────────────────────────────────────────────────────
        if cache_key in shape_cache:
            cached_coords = shape_cache[cache_key]
            if cached_coords and len(cached_coords) >= 2:
                data['shape_coords'] = [tuple(pt) for pt in cached_coords]
                cache_hits += 1
                enriched  += 1
                continue

        # ── Get stop coordinates ──────────────────────────────────────────────
        u_data = G_transit.nodes.get(u, {})
        v_data = G_transit.nodes.get(v, {})
        u_lon, u_lat = float(u_data.get('x', 0)), float(u_data.get('y', 0))
        v_lon, v_lat = float(v_data.get('x', 0)), float(v_data.get('y', 0))

        if (u_lon == 0 and u_lat == 0) or (v_lon == 0 and v_lat == 0):
            skipped_no_snap += 1
            continue

        # ── Snap stops to drive graph ─────────────────────────────────────────
        u_node = _fast_nearest(u_lon, u_lat)
        v_node = _fast_nearest(v_lon, v_lat)

        if u_node is None or v_node is None:
            skipped_no_snap += 1
            shape_cache[cache_key] = []   # mark as unresolvable
            continue

        if u_node == v_node:
            # Very close stops — straight line is acceptable (< max_stop_snap_m)
            coords = [(u_lon, u_lat), (v_lon, v_lat)]
            data['shape_coords'] = coords
            shape_cache[cache_key] = coords
            enriched += 1
            continue

        # ── Route on drive graph ──────────────────────────────────────────────
        try:
            node_path = nx.shortest_path(G_drive, u_node, v_node, weight='length')
            coords    = _extract_drive_path_coords(G_drive, node_path)
            if not coords or len(coords) < 2:
                coords = [(u_lon, u_lat), (v_lon, v_lat)]
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            coords = [(u_lon, u_lat), (v_lon, v_lat)]
            skipped_no_path += 1
        except Exception as exc:
            logger.debug("Drive routing failed for %s→%s: %s", u, v, exc)
            coords = [(u_lon, u_lat), (v_lon, v_lat)]

        data['shape_coords'] = [tuple(pt) for pt in coords]
        shape_cache[cache_key] = coords
        enriched += 1

        if enriched % batch_log_every == 0:
            logger.info(
                "Bus shape enrichment: %d / %d complete (cache hits: %d)",
                enriched, total, cache_hits,
            )

    # ── Save cache ────────────────────────────────────────────────────────────
    try:
        cache_path.write_text(json.dumps(shape_cache))
    except Exception as exc:
        logger.debug("Could not write bus shape cache: %s", exc)

    logger.info(
        "✅ Bus shape enrichment complete: %d enriched (%d cache hits), "
        "%d skipped (no snap), %d skipped (no path)",
        enriched, cache_hits, skipped_no_snap, skipped_no_path,
    )
    return enriched