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
    enrich_transit_shapes(env.graph_manager, city_tag=city_tag, max_stop_snap_m=800.0)

Note: max_stop_snap_m should be passed as 800.0 (not the default 400.0) to
catch urban stops on pedestrianised streets and bus stations that have no
drive node within 400m.  800m is a safer default for all UK contexts.

ARCHITECTURE
────────────
1. Iterate every edge (u, v) in G_transit with shape_coords == []
2. Get the lon/lat of stops u and v from G_transit.nodes
3. Snap each to the nearest OSMnx drive graph node
4. nx.shortest_path(drive_graph, u_node, v_node, weight='length')
5. Extract Shapely edge geometry into (lon, lat) list
6. Store back on the transit edge as shape_coords
7. Cache the (stop_u_id, stop_v_id) → coords mapping to disk

GTFS route_shapes fallback (Issue 2B)
──────────────────────────────────────
For stops that are outside the drive-graph disc (cross-regional express
services, rural connections), the drive-graph snap will fail because there
is no road node within max_stop_snap_m.  Before writing a straight-line
fallback, this module checks if the transit graph edge has GTFS shapes.txt
geometry stored in G_transit.graph['route_shapes'].  This is region-agnostic:
any GTFS feed with shapes.txt coverage will benefit, regardless of UK city.

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

# Bump this whenever enrich_transit_shapes' logic changes (priority order,
# what counts as "enriched", what gets cached, etc).
#
# Session 21 reordered the lookup to check GTFS route_shapes before drive
# snapping — but the cache itself wasn't versioned, so a cache built under
# the OLD logic (drive-routing-first, AND one that cached degenerate 2-point
# straight-line fallbacks as "enriched" successes) kept being loaded and
# short-circuiting the new logic entirely (99.7% cache-hit rate observed).
#
# Session 22: bumping this discards that poisoned cache. Also fixed: drive
# routing failures (NetworkXNoPath/NodeNotFound/degenerate path/exception)
# are no longer cached or counted as "enriched" — only genuine GTFS-shape
# geometry, genuine road-following drive routes, and short same-drive-node
# straight lines (< max_stop_snap_m) are cached as successes.
_CACHE_VERSION = "v22-no-degenerate-cache"


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


def _get_gtfs_shape_for_edge(
    G_transit,
    u: str,
    v: str,
    route_short_names: Optional[List[str]] = None,
) -> Optional[List[Tuple[float, float]]]:
    """
    Return GTFS shapes.txt geometry for the transit edge (u, v), or None.

    GTFSGraph.build() stores shapes keyed by route_short_name in
    G_transit.graph['route_shapes'] = {route_short_name: {(stop_u, stop_v): coords}}.

    This is region-agnostic: any GTFS feed with shapes.txt coverage will
    return geometry here, regardless of UK city or operator.

    Args:
        G_transit:          The GTFS transit graph (NetworkX MultiDiGraph).
        u, v:               Stop IDs for the edge to look up.
        route_short_names:  Optional — the calling edge's own
                             ``route_short_names`` (already available on
                             ``data`` in the enrichment loop). When given,
                             only those routes are checked first, which is
                             O(1) per edge instead of scanning every route
                             in ``route_shapes`` — important when called for
                             tens of thousands of empty edges.

    Returns:
        List of (lon, lat) tuples with ≥ 2 points, or None if not found.
    """
    route_shapes = G_transit.graph.get('route_shapes', {})
    if not route_shapes:
        return None

    # Fast path: the edge already knows which route(s) serve it.
    if route_short_names:
        for rsn in route_short_names:
            coords = route_shapes.get(rsn, {}).get((u, v))
            if coords and len(coords) >= 2:
                return [tuple(pt) for pt in coords]

    # Also check the edge data directly for a route_short_name hint
    # (covers callers that didn't pass route_short_names explicitly).
    edge_map = G_transit.get_edge_data(u, v)
    if edge_map:
        for ed in edge_map.values():
            for rsn in ed.get('route_short_names', []):
                coords = route_shapes.get(rsn, {}).get((u, v))
                if coords and len(coords) >= 2:
                    return [tuple(pt) for pt in coords]

    # Slow path / last resort: search every route for this stop pair. Only
    # reached if the edge carries no route_short_names hint at all.
    for _route, _pair_map in route_shapes.items():
        coords = _pair_map.get((u, v))
        if coords and len(coords) >= 2:
            return [tuple(pt) for pt in coords]

    return None


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
    # Cache filename includes _CACHE_VERSION so a logic change (priority order,
    # what gets cached as a success) automatically invalidates old caches —
    # see _CACHE_VERSION comment above.
    cache_path = CACHE_ROOT / f"{city_tag}_bus_shapes_{_CACHE_VERSION}.json"
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

    # ── Pre-filter: skip everything if graph is already fully enriched ────────
    # A second call (different city_tag, empty cache) sees 0 empty edges after
    # the first call has already filled shape_coords in-place.  Exit before
    # building the drive-node list to avoid wasting ~10 seconds.
    _all_edges_pre = list(G_transit.edges(keys=True, data=True))
    _empty_pre = [
        (u, v, k, d) for u, v, k, d in _all_edges_pre
        if (d.get('mode', 'bus') not in ('walk',) and
            d.get('highway') != 'transfer' and
            not d.get('shape_coords'))
    ]
    if not _empty_pre:
        logger.info("Bus shape enrichment: all transit edges already have shape_coords — nothing to do")
        return 0

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

    # ── Drive graph bbox guard ─────────────────────────────────────────────────
    # Pre-reject stops outside the drive graph area before running the O(N) scan.
    _MARGIN_DEG = max_stop_snap_m / 111_320.0
    if _drive_nodes:
        _xs = [nx_ for _, nx_, _ in _drive_nodes]
        _ys = [ny_ for _, _, ny_ in _drive_nodes]
        _bbox_min_lon = min(_xs) - _MARGIN_DEG
        _bbox_max_lon = max(_xs) + _MARGIN_DEG
        _bbox_min_lat = min(_ys) - _MARGIN_DEG
        _bbox_max_lat = max(_ys) + _MARGIN_DEG
    else:
        _bbox_min_lon = _bbox_max_lon = _bbox_min_lat = _bbox_max_lat = 0.0

    def _fast_nearest(lon: float, lat: float) -> Optional:
        # Fast bbox pre-rejection.
        if not (_bbox_min_lon <= lon <= _bbox_max_lon
                and _bbox_min_lat <= lat <= _bbox_max_lat):
            return None
        best_node, best_dist = None, float('inf')
        for node, nx_, ny_ in _drive_nodes:
            dx = (nx_ - lon) * 111_320 * math.cos(math.radians(lat))
            dy = (ny_ - lat) * 111_320
            d  = math.sqrt(dx * dx + dy * dy)
            if d < best_dist:
                best_dist, best_node = d, node
        return best_node if best_dist <= max_stop_snap_m else None

    def _nearest_any(lon: float, lat: float) -> Optional:
        """Nearest drive node with NO distance cap and NO bbox pre-rejection.

        Used as the "edge of the drive graph nearest this out-of-range stop"
        for partial routing (see enriched_partial below). Unlike
        _fast_nearest, this always returns a node if the drive graph is
        non-empty — the caller decides whether the resulting straight "tail"
        segment (from this node's coordinates to the actual stop) is short
        enough to be useful.
        """
        best_node, best_dist = None, float('inf')
        for node, nx_, ny_ in _drive_nodes:
            dx = (nx_ - lon) * 111_320 * math.cos(math.radians(lat))
            dy = (ny_ - lat) * 111_320
            d  = math.sqrt(dx * dx + dy * dy)
            if d < best_dist:
                best_dist, best_node = d, node
        return best_node

    # ── Iterate transit edges ─────────────────────────────────────────────────
    enriched         = 0
    enriched_gtfs    = 0
    enriched_drive   = 0
    enriched_partial = 0
    enriched_samenode = 0
    skipped_no_snap  = 0
    no_snap_in_bbox  = 0
    no_snap_outside_bbox = 0
    skipped_no_path  = 0
    skipped_degenerate = 0
    skipped_out_bbox = 0
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

        # ── GTFS shapes.txt geometry — TRY THIS FIRST ───────────────────────────
        # gtfs_graph.py's GTFSGraph.build() already slices the GTFS feed's own
        # shapes.txt polylines per stop-pair into G_transit.graph['route_shapes'].
        # This is the ACTUAL path the vehicle drives/runs, as published by the
        # operator — it is authoritative and should always be preferred over a
        # generic shortest-path-by-length route on the OSM drive graph, which
        # frequently picks a different (and sometimes nonsensical) road.
        #
        # Previously this GTFS-shape lookup only ran as a last resort, AFTER
        # drive-graph snapping succeeded and drive routing was already used.
        # Since nearly every stop snaps to *some* drive node within
        # max_stop_snap_m, the drive-graph branch below ran for almost every
        # edge and the real shapes.txt geometry (2960 shapes in the BODS feed)
        # was essentially never used. Checking it first fixes that.
        #
        # This is region-agnostic: works for any GTFS feed with shapes.txt,
        # regardless of UK city or operator.
        _gtfs_shape = _get_gtfs_shape_for_edge(G_transit, u, v, data.get('route_short_names'))
        if _gtfs_shape and len(_gtfs_shape) >= 2:
            data['shape_coords'] = _gtfs_shape
            shape_cache[cache_key] = _gtfs_shape
            enriched += 1
            enriched_gtfs += 1
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
        # Fast-reject stop pairs where either endpoint is outside the drive bbox.
        # _u_in = (_bbox_min_lon <= u_lon <= _bbox_max_lon and _bbox_min_lat <= u_lat <= _bbox_max_lat)
        # _v_in = (_bbox_min_lon <= v_lon <= _bbox_max_lon and _bbox_min_lat <= v_lat <= _bbox_max_lat)
        # if not (_u_in and _v_in):
        #     skipped_out_bbox += 1
        #     continue

        u_node = _fast_nearest(u_lon, u_lat)
        v_node = _fast_nearest(v_lon, v_lat)

        if u_node is None or v_node is None:
            # Diagnostic: which endpoint failed, and was it because the stop
            # is outside the drive graph's geographic extent entirely (the
            # 25km disc + margin), or inside it but >max_stop_snap_m from any
            # node (a genuine coverage gap in the drive graph)?
            for _lon, _lat, _node, _label in (
                (u_lon, u_lat, u_node, 'u'), (v_lon, v_lat, v_node, 'v')
            ):
                if _node is not None:
                    continue
                _in_bbox = (_bbox_min_lon <= _lon <= _bbox_max_lon
                            and _bbox_min_lat <= _lat <= _bbox_max_lat)
                if _in_bbox:
                    no_snap_in_bbox += 1
                else:
                    no_snap_outside_bbox += 1
                if no_snap_in_bbox + no_snap_outside_bbox <= 10:
                    logger.debug(
                        "No drive snap for %s stop %s (lon=%.4f, lat=%.4f): "
                        "%s drive graph bbox (lon %.4f..%.4f, lat %.4f..%.4f)",
                        _label, u if _label == 'u' else v, _lon, _lat,
                        "inside" if _in_bbox else "OUTSIDE",
                        _bbox_min_lon, _bbox_max_lon, _bbox_min_lat, _bbox_max_lat,
                    )

            # ── Partial drive routing (Issue: 44824 edges with no geometry) ───
            # If exactly ONE endpoint is outside the drive graph's reach
            # (the common case for routes crossing the drive-graph boundary
            # — e.g. an Edinburgh stop paired with a Dunfermline/North
            # Berwick stop), route on the drive graph from the IN-RANGE
            # endpoint to whichever drive node is nearest the OUT-OF-RANGE
            # stop (no distance cap), then add a short straight "tail" to
            # the actual out-of-range stop coordinate. This gives mostly
            # road-following geometry instead of one straight line spanning
            # the entire region. If BOTH endpoints are out of range, there's
            # no drive-graph benefit — fall through to unresolved.
            if (u_node is None) != (v_node is None):
                try:
                    if u_node is None:
                        _edge_node = _nearest_any(u_lon, u_lat)
                        if _edge_node is None:
                            raise ValueError("empty drive graph")
                        _node_path = nx.shortest_path(G_drive, _edge_node, v_node, weight='length')
                        _path_coords = _extract_drive_path_coords(G_drive, _node_path)
                        if not _path_coords or len(_path_coords) < 2:
                            raise ValueError("degenerate path")
                        coords = [(u_lon, u_lat)] + _path_coords
                    else:
                        _edge_node = _nearest_any(v_lon, v_lat)
                        if _edge_node is None:
                            raise ValueError("empty drive graph")
                        _node_path = nx.shortest_path(G_drive, u_node, _edge_node, weight='length')
                        _path_coords = _extract_drive_path_coords(G_drive, _node_path)
                        if not _path_coords or len(_path_coords) < 2:
                            raise ValueError("degenerate path")
                        coords = _path_coords + [(v_lon, v_lat)]

                    data['shape_coords'] = [tuple(pt) for pt in coords]
                    shape_cache[cache_key] = coords
                    enriched += 1
                    enriched_partial += 1
                    continue
                except (nx.NetworkXNoPath, nx.NodeNotFound, ValueError):
                    pass
                except Exception as exc:
                    logger.debug("Partial drive routing failed for %s→%s: %s", u, v, exc)

            # Both endpoints out of range (or partial routing failed above),
            # and no GTFS shape was found earlier. Do not cache failures —
            # empty entries block retries when the drive graph or snap
            # radius changes. Let the next run retry.
            skipped_no_snap += 1
            continue


        if u_node == v_node:
            # Both stops snap to the same drive node — they're within
            # max_stop_snap_m of each other (and of that node). A straight
            # line between the two STOP coordinates (not the drive node) is
            # a genuinely short hop and a reasonable approximation.
            coords = [(u_lon, u_lat), (v_lon, v_lat)]
            data['shape_coords'] = coords
            shape_cache[cache_key] = coords
            enriched += 1
            enriched_samenode += 1
            continue

        # ── Route on drive graph ──────────────────────────────────────────────
        # IMPORTANT: unlike the u_node==v_node case above, a routing FAILURE
        # here (no path between two distinct, successfully-snapped drive
        # nodes; or a degenerate <2-point extraction) does NOT mean "short
        # hop, straight line is fine" — it can mean the two stops are on
        # opposite sides of a body of water, in disconnected graph
        # components, or otherwise far apart with no real direct road link.
        # Previously these cases wrote a 2-point straight line, CACHED it,
        # and counted it as `enriched` — indistinguishable from genuine
        # road-following geometry. That poisoned the cache: once cached, the
        # GTFS-shape check above would never run again for this edge, even
        # if shapes.txt has the real geometry. Session 22: do NOT cache or
        # count these as enriched. Leave shape_coords empty so a future
        # rendering-layer fix can choose to skip/distinctly-style genuinely
        # unresolved edges instead of drawing long straight lines across
        # buildings/water.
        try:
            node_path = nx.shortest_path(G_drive, u_node, v_node, weight='length')
            coords    = _extract_drive_path_coords(G_drive, node_path)
            if not coords or len(coords) < 2:
                skipped_degenerate += 1
                continue
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            skipped_no_path += 1
            continue
        except Exception as exc:
            logger.debug("Drive routing failed for %s→%s: %s", u, v, exc)
            skipped_degenerate += 1
            continue

        data['shape_coords'] = [tuple(pt) for pt in coords]
        shape_cache[cache_key] = coords
        enriched += 1
        enriched_drive += 1

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
        "✅ Bus shape enrichment complete: %d enriched (%d cache hits, "
        "%d via GTFS shapes, %d via drive routing, %d partial drive+tail, "
        "%d same-node short hops) "
        "— %d unresolved (%d no drive snap [%d outside drive-graph bbox, "
        "%d inside bbox but >max_stop_snap_m], %d no drive path between "
        "snapped nodes, %d degenerate drive path)",
        enriched, cache_hits, enriched_gtfs, enriched_drive, enriched_partial,
        enriched_samenode,
        skipped_no_snap + skipped_no_path + skipped_degenerate,
        skipped_no_snap, no_snap_outside_bbox, no_snap_in_bbox,
        skipped_no_path, skipped_degenerate,
    )
    if skipped_no_snap + skipped_no_path + skipped_degenerate:
        logger.warning(
            "%d transit edges have NO shape_coords after enrichment. These "
            "will fall back to whatever the visualisation layer does for "
            "empty shape_coords (likely a straight line between stop "
            "coordinates) — see RTD_SIM_HANDOFF for the rendering-layer fix "
            "needed to skip/distinctly-style these instead.",
            skipped_no_snap + skipped_no_path + skipped_degenerate,
        )
    return enriched