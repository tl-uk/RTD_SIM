"""
simulation/gtfs/gtfs_graph.py

Builds a NetworkX MultiDiGraph from a parsed GTFSLoader.

The graph is a transit network layer that sits alongside (never merged
with) the OSM road and rail graphs in GraphManager.  Nodes are GTFS
stops; edges carry scheduled travel times, headways, shape geometry, and
fuel type so the Router can compute a fully-loaded generalised cost.

Graph conventions (matching OSMnx / rail_spine conventions throughout)
----------------------------------------------------------------------
Node attributes:
    x             = longitude  (float)
    y             = latitude   (float)
    stop_id       = GTFS stop_id (str)
    name          = stop_name (str)
    wheelchair    = bool
    route_types   = frozenset of GTFS route_type ints served at this stop

Edge attributes:
    travel_time_s     = scheduled in-vehicle seconds (float)
    headway_s         = average headway in seconds   (float)
    shape_coords      = [(lon, lat), …] from shapes.txt
    route_ids         = [route_id, …]
    route_short_names = [str, …]  — for tooltip display
    route_long_names  = [str, …]
    mode              = RTD_SIM mode string ('bus', 'local_train', …)
    fuel_type         = 'electric' | 'diesel' | 'hydrogen' | 'hybrid'
    emissions_g_km    = float (per-km CO₂e, from fuel_type)
    length            = approximate edge length in metres (haversine)
    gen_cost          = float stub (overwritten by Router at routing time)

Ghost-trip guard
----------------
GTFSLoader.stop_times contains ALL trips that touch the map bbox,
including trips from the wrong service day (the calendar filter applies
only to GTFSLoader.trips).  Every edge-building loop calls
``loader.trips.get(trip_id)`` WITHOUT a default argument — this returns
None for missing keys.  The guard ``if not trip: continue`` catches both
None (trip absent from calendar-filtered set) and {} (empty fallback).

CRITICAL: do NOT write ``loader.trips.get(trip_id, {})`` — the {} default
means missing keys return {} not None, and ``if {} is None`` is False, so
ghost trips slip through.  ``not {}`` evaluates True, which is why the
guard must be ``if not trip`` and NOT ``if trip is None``.

Transfer nodes
--------------
build_transfer_edges() snaps each stop to its nearest OSM walk-graph
node and adds a pair of 'transfer' edges (stop→walk, walk→stop).

IMPORTANT: This function is a SINGLE FLAT LOOP — one iteration per GTFS
stop.  A previous version had an inner replacement loop nested inside the
original outer loop, producing O(N²) redundant work and an overcounted
``added`` counter.  The outer loop has been removed; only the flat inner
implementation remains.

Fuel → emissions mapping (g CO₂e / km)
---------------------------------------
    electric  →  35  (UK grid carbon intensity, 2024)
    diesel    → 130  (GB average diesel bus, measured)
    hydrogen  →   0  (green hydrogen; conservative: 20 if grey H₂)
    hybrid    →  80  (plug-in hybrid average)
    unknown   → 100  (conservative default)
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import networkx as nx
    _NX = True
except ImportError:
    _NX = False
    logger.warning("NetworkX not available — GTFSGraph cannot be built")

try:
    import osmnx as ox
    _OX = True
except ImportError:
    _OX = False

_EMISSIONS_BY_FUEL: Dict[str, float] = {
    'electric':  35.0,
    'diesel':   130.0,
    'hydrogen':   0.0,
    'hybrid':    80.0,
    'unknown':  100.0,
}


def _haversine_m(
    lon1: float, lat1: float, lon2: float, lat2: float
) -> float:
    """Haversine distance in metres between two (lon, lat) points."""
    R = 6_371_000.0
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a  = (math.sin(dp / 2) ** 2
          + math.cos(math.radians(lat1))
          * math.cos(math.radians(lat2))
          * math.sin(dl / 2) ** 2)
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── GTFS route_type → RTD_SIM mode string ─────────────────────────────────────
# The BODS feed (f-bus~dft~gov~uk) stores route_type on routes but GTFSLoader
# may not populate 'mode' on the route dict.  Without this mapping, every
# edge in the transit graph has mode='bus' and mode_filter='tram' never matches.
# GTFS spec route_type values:
#   0 = Tram / Light Rail    1 = Subway / Metro    2 = Rail
#   3 = Bus                  4 = Ferry             5 = Cable car
_ROUTE_TYPE_TO_MODE: dict = {
    0: 'tram',
    1: 'bus',           # subway/metro — use bus as closest RTD_SIM equivalent
    2: 'local_train',
    3: 'bus',
    4: 'ferry_diesel',
    5: 'bus',           # cable car — rare
    6: 'bus',           # gondola
    7: 'bus',           # funicular
    11: 'bus',          # trolleybus
    12: 'bus',          # monorail
}


class GTFSGraph:
    """
    Builds a transit NetworkX graph from a GTFSLoader.

    Usage
    -----
        loader   = GTFSLoader('gtfs.zip').load()
        headways = loader.compute_headways()
        builder  = GTFSGraph(loader, headways)
        G        = builder.build()
        builder.build_transfer_edges(G, G_walk)   # stitch to OSM walk graph
    """

    def __init__(
        self,
        loader: Any,
        headways: Optional[Dict[Tuple[str, str], int]] = None,
    ):
        """
        Args:
            loader:   GTFSLoader instance (already loaded).
            headways: Pre-computed {(route_id, stop_id): avg_headway_s} dict
                      from loader.compute_headways().  Pass None or {} to use
                      the per-service 1-hour default for all edges.
        """
        self.loader   = loader
        self.headways = headways or {}

    # =========================================================================
    # MAIN BUILD
    # =========================================================================

    def build(self) -> Optional[Any]:
        """
        Build and return the transit NetworkX MultiDiGraph.

        Each edge represents a consecutive stop pair served by at least one
        calendar-active trip.  Parallel trips (same stop pair, different
        schedules) are merged into a single edge whose headway_s is the
        average of all services.

        Ghost-trip guard
        ----------------
        GTFSLoader.stop_times includes trips from wrong service days.
        ``loader.trips.get(trip_id)`` — NO default — returns None for
        missing keys.  ``if not trip: continue`` catches both None and {}.
        Never use ``get(trip_id, {})``; see module docstring.

        shape_coords selection
        ----------------------
        When multiple records exist for a stop pair, the first record that
        has a non-empty shape_coords is used.  This avoids taking geometry
        from dead-run / positioning trips (which often lack a shape_id)
        when a later revenue-service trip has correct geometry.

        Returns:
            NetworkX MultiDiGraph or None if NetworkX is unavailable.
        """
        if not _NX:
            return None

        loader = self.loader
        if not loader._loaded:
            loader.load()

        G = nx.MultiDiGraph()
        G.graph['type'] = 'transit'
        G.graph['crs']  = 'WGS84'

        # ── Add stop nodes ────────────────────────────────────────────────────
        for stop_id, stop in loader.stops.items():
            G.add_node(
                stop_id,
                x           = stop['lon'],
                y           = stop['lat'],
                stop_id     = stop_id,
                name        = stop['name'],
                wheelchair  = stop['wheelchair'],
                route_types = set(),   # populated during edge accumulation
            )

        # ── Accumulate edges from stop_times ──────────────────────────────────
        # {(u, v): [{travel_time_s, route_id, mode, fuel_type, shape_coords}]}
        edge_accumulator: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)

        for trip_id, stops in loader.stop_times.items():
            # GHOST-TRIP GUARD.
            # Do NOT add a {} default here — see module docstring.
            trip = loader.trips.get(trip_id)
            if not trip:
                continue

            route_id = trip.get('route_id', '')
            route    = loader.routes.get(route_id, {})
            rtype    = route.get('route_type', 3)
            # Derive mode from route_type — BODS may not set 'mode' on routes,
            # causing every edge to default to 'bus' and mode_filter='tram' to
            # never match even when Edinburgh Trams trips are present.
            mode     = route.get('mode') or _ROUTE_TYPE_TO_MODE.get(rtype, 'bus')
            fuel     = route.get('fuel_type', 'diesel')

            # get_shape_for_trip always returns a list (never None).
            shape_coords = loader.get_shape_for_trip(trip_id)

            for i in range(len(stops) - 1):
                u_st = stops[i]
                v_st = stops[i + 1]
                u    = u_st['stop_id']
                v    = v_st['stop_id']

                if u not in G.nodes or v not in G.nodes:
                    continue

                dep_s    = u_st['departure_s']
                arr_s    = v_st['arrival_s']
                travel_s = max(0, arr_s - dep_s) if arr_s >= dep_s else 60

                G.nodes[u]['route_types'].add(rtype)
                G.nodes[v]['route_types'].add(rtype)

                seg_shape = self._slice_shape(
                    shape_coords,
                    G.nodes[u]['x'], G.nodes[u]['y'],
                    G.nodes[v]['x'], G.nodes[v]['y'],
                )

                edge_accumulator[(u, v)].append({
                    'travel_time_s': travel_s,
                    'route_id':      route_id,
                    'mode':          mode,
                    'fuel_type':     fuel,
                    'shape_coords':  seg_shape,
                })

        # ── Add merged edges ──────────────────────────────────────────────────
        for (u, v), records in edge_accumulator.items():
            if not records:
                continue

            avg_travel_s = sum(r['travel_time_s'] for r in records) / len(records)
            route_ids    = list({r['route_id'] for r in records})
            mode         = records[0]['mode']
            fuel_type    = records[0]['fuel_type']

            # Take the first shape with real content — prefer revenue trips
            # over dead-runs and positioning trips that lack geometry.
            shape = next(
                (r['shape_coords'] for r in records if r.get('shape_coords')),
                [],
            )

            route_short_names: List[str] = []
            route_long_names:  List[str] = []
            for rid in route_ids:
                r_data = loader.routes.get(rid, {})
                sn = r_data.get('short_name') or r_data.get('route_short_name', '')
                ln = r_data.get('long_name')  or r_data.get('route_long_name',  '')
                if sn: route_short_names.append(str(sn))
                if ln: route_long_names.append(str(ln))

            # Use pre-computed headway for the first matching route/stop pair.
            headway_s = 3600
            for rid in route_ids:
                hw = self.headways.get((rid, u))
                if hw is not None:
                    headway_s = hw
                    break

            u_data = G.nodes[u]
            v_data = G.nodes[v]
            dist_m = _haversine_m(
                u_data['x'], u_data['y'], v_data['x'], v_data['y']
            )
            emit = _EMISSIONS_BY_FUEL.get(fuel_type, 100.0)

            G.add_edge(
                u, v,
                travel_time_s      = avg_travel_s,
                headway_s          = headway_s,
                shape_coords       = shape,
                route_ids          = route_ids,
                route_short_names  = route_short_names,
                route_long_names   = route_long_names,
                mode               = mode,
                fuel_type          = fuel_type,
                emissions_g_km     = emit,
                length             = dist_m,
                gen_cost           = avg_travel_s / 3600.0 * 10.0,   # VoT stub
            )

        # Freeze route_types to frozenset for hashability.
        for node in G.nodes:
            G.nodes[node]['route_types'] = frozenset(
                G.nodes[node].get('route_types', set())
            )

        # ── Build RAPTOR index structures ─────────────────────────────────────
        # Dijkstra on a shared-edge transit multigraph cannot stay on one
        # physical service — all routes sharing a stop pair share one edge,
        # so the shortest path freely mixes services 7, 11, and 25 in a
        # single journey.  RAPTOR avoids this by processing each route's
        # ordered stop sequence exactly once per round.
        #
        # route_stop_sequences:  {short_name: [[stop_id, ...], ...]}
        #   Each inner list is the ordered stop sequence for ONE trip.
        #   Multiple entries per route capture different directions / variants.
        #   Sequences with fewer than 2 in-graph stops are discarded.
        #
        # stop_routes:           {stop_id: [short_name, ...]}
        #   For each stop, which route short names serve it.
        #   Used in RAPTOR's marking step to limit route scanning to routes
        #   that touch stops improved in the previous round.
        #
        # route_avg_times:       {short_name: {(u_stop, v_stop): avg_s}}
        #   Per-route average travel time for each consecutive stop pair.
        #   Used to estimate journey time along a sequence-lookup path.

        route_seqs:  Dict[str, List[List[str]]]           = defaultdict(list)
        stop_routes: Dict[str, List[str]]                  = defaultdict(list)
        route_times: Dict[str, Dict[Tuple[str,str], float]] = defaultdict(dict)
        # Per-route per-stop-pair shape: lets the router retrieve
        # service-specific geometry rather than a merged-edge shape
        # that may belong to a different co-routed service.
        route_shapes: Dict[str, Dict[Tuple[str,str], list]] = defaultdict(dict)

        for trip_id, stops in loader.stop_times.items():
            trip = loader.trips.get(trip_id)
            if not trip:
                continue
            route_id = trip.get('route_id', '')
            route    = loader.routes.get(route_id, {})
            sn = str(
                route.get('short_name')
                or route.get('route_short_name', '')
            ).strip()
            if not sn:
                continue

            # Build ordered stop list for this trip (in-graph stops only)
            seq: List[str] = [
                s['stop_id'] for s in stops if s['stop_id'] in G.nodes
            ]
            if len(seq) < 2:
                continue

            # Store unique sequences per route (direction / terminal variants)
            # Two trips with identical stop sequences are deduplicated.
            if seq not in route_seqs[sn]:
                route_seqs[sn].append(seq)

            # Update stop→routes index
            for sid in seq:
                if sn not in stop_routes[sid]:
                    stop_routes[sid].append(sn)

            # Accumulate per-route stop-pair travel times (running mean)
            for i in range(len(stops) - 1):
                u = stops[i]['stop_id']
                v = stops[i + 1]['stop_id']
                if u not in G.nodes or v not in G.nodes:
                    continue
                dep_s    = stops[i]['departure_s']
                arr_s    = stops[i + 1]['arrival_s']
                travel_s = max(0.0, float(arr_s - dep_s)) if arr_s >= dep_s else 60.0
                key      = (u, v)
                prev     = route_times[sn].get(key)
                route_times[sn][key] = (
                    travel_s if prev is None else (prev + travel_s) / 2.0
                )

        # ── Build per-route per-segment shape index ──────────────────────
        # For each trip with shape data, extract the geometry slice between
        # each consecutive stop pair and store under the route short name.
        # First trip for a (route, stop_pair) wins; later trips skip it.
        for _tid, _sts in loader.stop_times.items():
            _tr = loader.trips.get(_tid)
            if not _tr:
                continue
            _sid = _tr.get('shape_id', '')
            _tshape = (
                loader.shapes.get(_sid, [])
                if _sid and getattr(loader, 'shapes', None)
                else []
            )
            if not _tshape:
                continue
            _rid  = _tr.get('route_id', '')
            _robj = loader.routes.get(_rid, {})
            _rsn  = str(_robj.get('short_name') or _robj.get('route_short_name', '')).strip()
            if not _rsn:
                continue
            for _i in range(len(_sts) - 1):
                _uid = _sts[_i]['stop_id']
                _vid = _sts[_i + 1]['stop_id']
                if _uid not in G.nodes or _vid not in G.nodes:
                    continue
                _pr = (_uid, _vid)
                if _pr in route_shapes[_rsn]:
                    continue
                _ud, _vd = G.nodes[_uid], G.nodes[_vid]
                _seg = self._slice_shape(
                    _tshape,
                    float(_ud.get('x', 0)), float(_ud.get('y', 0)),
                    float(_vd.get('x', 0)), float(_vd.get('y', 0)),
                )
                if _seg and len(_seg) >= 2:
                    route_shapes[_rsn][_pr] = _seg

        G.graph['route_stop_sequences'] = dict(route_seqs)
        G.graph['stop_routes']          = dict(stop_routes)
        G.graph['route_avg_times']      = {
            sn: dict(pairs) for sn, pairs in route_times.items()
        }
        G.graph['route_shapes'] = {
            sn: dict(pairs) for sn, pairs in route_shapes.items()
        }

        n_routes = len(route_seqs)
        n_seqs   = sum(len(v) for v in route_seqs.values())
        logger.info(
            "GTFSGraph built: %d stop nodes, %d transit edges, "
            "%d routes indexed (%d sequences) for RAPTOR routing",
            G.number_of_nodes(), G.number_of_edges(),
            n_routes, n_seqs,
        )
        return G

    # =========================================================================
    # TRANSFER EDGE CREATION
    # =========================================================================

    def build_transfer_edges(
        self,
        G_transit: Any,
        G_walk: Any,
        walk_speed_m_s: float = 1.2,   # 4.3 km/h
        max_snap_m: float = 500.0,
    ) -> int:
        """
        Add bidirectional transfer edges between each GTFS stop and its nearest
        OSM walk-graph node.

        This is the glue that lets the intermodal Router chain:
            walk → board transit → ride → alight → walk.

        Each stop is added as a node in G_walk (when not already present) and
        connected to its nearest walk-graph node with a synthetic 'transfer'
        edge in both directions.

        Implementation — single flat loop
        -----------------------------------
        This function iterates once over G_transit.nodes.  A previous version
        accidentally nested a replacement inner loop inside the original outer
        loop, producing O(N²) operations and an overcounted ``added`` counter.
        Only the flat implementation is present here.

        Args:
            G_transit:      The transit graph from build().
            G_walk:         OSMnx walk graph from GraphManager.
            walk_speed_m_s: Walking speed in m/s (default 1.2 ≈ 4.3 km/h).
            max_snap_m:     Stops further than this from any walk node are
                            skipped (default 500 m).

        Returns:
            Number of stops successfully linked to the walk graph.
        """
        if not _NX or not _OX:
            return 0
        if G_transit is None or G_walk is None:
            return 0

        added = 0

        for stop_id, data in G_transit.nodes(data=True):
            lon = data.get('x', 0)
            lat = data.get('y', 0)
            if lon == 0 and lat == 0:
                continue

            try:
                walk_node = ox.distance.nearest_nodes(G_walk, lon, lat)
            except Exception:
                continue

            walk_data = G_walk.nodes.get(walk_node, {})
            dist_m    = _haversine_m(
                lon, lat,
                walk_data.get('x', lon),
                walk_data.get('y', lat),
            )
            if dist_m > max_snap_m:
                continue

            walk_time_s = dist_m / walk_speed_m_s

            # Register the stop as a node in the walk graph so the Router
            # can terminate a walk shortest-path directly at a transit stop.
            if not G_walk.has_node(stop_id):
                G_walk.add_node(stop_id, x=lon, y=lat, stop_id=stop_id)

            edge_attrs = dict(
                length        = dist_m,
                travel_time_s = walk_time_s,
                highway       = 'transfer',
                mode          = 'walk',
                gen_cost      = walk_time_s / 3600.0 * 10.0,
            )
            G_walk.add_edge(walk_node, stop_id, **edge_attrs)
            G_walk.add_edge(stop_id, walk_node, **edge_attrs)
            added += 1

        logger.info(
            "GTFSGraph: %d stops linked to walk graph (transfer edges added)",
            added,
        )
        return added

    # =========================================================================
    # NEAREST STOP QUERY
    # =========================================================================

    def nearest_stop(
        self,
        G_transit: Any,
        coord: Tuple[float, float],
        mode_filter: Optional[str] = None,
        max_distance_m: float = 2000.0,
        exclude_stop: Optional[str] = None,
    ) -> Optional[str]:
        """
        Return the stop_id of the nearest transit stop to (lon, lat).

        Mode filter
        -----------
        When mode_filter is set, only stops that serve that mode are
        considered.  Both outgoing AND incoming edges are checked so that
        terminal stops (which have no outgoing service edges) are not
        incorrectly excluded.

        Args:
            G_transit:      The transit graph from build().
            coord:          (lon, lat).
            mode_filter:    RTD_SIM mode string, e.g. 'bus', 'local_train'.
                            None means any stop is eligible.
            max_distance_m: Return None when the nearest stop is further
                            than this (default 2 km).
            exclude_stop:   stop_id to skip (used by router to find the
                            second-nearest stop when origin and destination
                            snap to the same stop).

        Returns:
            stop_id string or None.
        """
        if G_transit is None:
            return None

        lon, lat = coord
        best_id   = None
        best_dist = float('inf')

        for stop_id, data in G_transit.nodes(data=True):
            if exclude_stop is not None and stop_id == exclude_stop:
                continue
            slat = data.get('y', 0)
            slon = data.get('x', 0)

            if mode_filter is not None:
                # Check both outgoing and incoming edges so terminal stops
                # (which have no outgoing service edges) are not skipped.
                #
                # CORRECT MultiDiGraph iteration: use data=True, keys=True
                # and unpack as (u, v, key, data_dict).  The previous pattern
                # of G_transit.edges[e].get('mode','') where e=(u,v,key) was
                # ambiguous across NetworkX versions — EdgeView.__getitem__
                # does not reliably unpack a 3-tuple on all builds, meaning
                # mode_filter never matched and nearest_stop always returned
                # None for tram/rail queries even when stops existed.
                out_modes = {
                    d.get('mode', '')
                    for _, _, _, d in G_transit.out_edges(
                        stop_id, data=True, keys=True
                    )
                }
                in_modes = {
                    d.get('mode', '')
                    for _, _, _, d in G_transit.in_edges(
                        stop_id, data=True, keys=True
                    )
                }
                if mode_filter not in (out_modes | in_modes):
                    continue

            d = _haversine_m(lon, lat, slon, slat)
            if d < best_dist:
                best_dist = d
                best_id   = stop_id

        if best_dist > max_distance_m:
            return None
        return best_id

    # =========================================================================
    # PYDECK LAYER DATA
    # =========================================================================

    def get_stop_pydeck_data(self, G_transit: Any) -> List[Dict]:
        """
        Return stop list as pydeck-compatible dicts for a ScatterplotLayer.
        Each dict: lon, lat, name, stop_id, wheelchair, tooltip_html.
        """
        if G_transit is None:
            return []
        out = []
        for stop_id, attrs in G_transit.nodes(data=True):
            served_shorts: List[str] = []
            for _, _, edata in G_transit.edges(stop_id, data=True):
                if edata.get('mode', 'walk') == 'walk':
                    continue
                for sn in edata.get('route_short_names', []):
                    if sn and sn not in served_shorts:
                        served_shorts.append(sn)
            routes_str = ', '.join(served_shorts[:6]) if served_shorts else ''
            out.append({
                'lon':        attrs.get('x', 0),
                'lat':        attrs.get('y', 0),
                'name':       attrs.get('name', stop_id),
                'stop_id':    stop_id,
                'wheelchair': attrs.get('wheelchair', False),
                'tooltip_html': (
                    f"<b>{attrs.get('name', stop_id)}</b><br/>"
                    + (f"Routes: {routes_str}<br/>" if routes_str else '')
                    + f"Stop ID: {stop_id}"
                    + ("<br/>♿ Wheelchair accessible"
                       if attrs.get('wheelchair') else "")
                ),
            })
        return out

    def get_route_pydeck_data(self, G_transit: Any) -> List[Dict]:
        """
        Return route lines as pydeck-compatible dicts for a PathLayer.
        Uses shape_coords when available; falls back to straight stop-to-stop lines.
        """
        if G_transit is None:
            return []

        _MODE_COLORS = {
            'bus':             [245, 158,  11],
            'tram':            [255, 193,   7],
            'local_train':     [ 33, 150, 243],
            'intercity_train': [ 63,  81, 181],
            'ferry_diesel':    [  0, 150, 136],
            'ferry_electric':  [  0, 188, 212],
        }

        out = []
        for u, v, attrs in G_transit.edges(data=True):
            mode  = attrs.get('mode', 'bus')
            shape = attrs.get('shape_coords')

            if not shape:
                u_d = G_transit.nodes.get(u, {})
                v_d = G_transit.nodes.get(v, {})
                shape = [
                    [u_d.get('x', 0), u_d.get('y', 0)],
                    [v_d.get('x', 0), v_d.get('y', 0)],
                ]

            color = list(_MODE_COLORS.get(mode, [128, 128, 128]))
            if attrs.get('fuel_type') == 'electric':
                color = [min(255, c + 40) for c in color]

            short_names = attrs.get('route_short_names', [])
            long_names  = attrs.get('route_long_names',  [])
            if short_names:
                service_label = ' / '.join(short_names[:4])
            elif long_names:
                service_label = long_names[0][:40]
            else:
                service_label = mode.replace('_', ' ').title()

            headway_s   = attrs.get('headway_s', 3600)
            headway_str = (f"{headway_s // 60} min"
                           if headway_s > 0 else "on-demand")

            out.append({
                'path':  [[lon, lat] for lon, lat in shape],
                'color': color,
                'mode':  mode,
                'fuel':  attrs.get('fuel_type', 'diesel'),
                'headway': headway_s,
                'tooltip_html': (
                    f"<b>{service_label}</b><br/>"
                    f"{mode.replace('_', ' ').title()} · "
                    f"{attrs.get('fuel_type', 'diesel')}<br/>"
                    f"Headway: {headway_str}"
                ),
            })
        return out

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    @staticmethod
    def _slice_shape(
        shape_coords: Optional[List[Tuple[float, float]]],
        u_lon: float, u_lat: float,
        v_lon: float, v_lat: float,
        window_m: float = 1500.0,
    ) -> List[Tuple[float, float]]:
        """
        Return the sub-sequence of shape_coords between stops u and v.

        Finds the shape point closest to each stop within window_m, then
        extracts the polyline between them.  Falls back to a 2-point
        straight line when the shape is absent or stops cannot be matched.

        The window_m default is 1500 m — larger than the original 200 m —
        to handle inaccurate stop coordinates in BODS feeds where the
        declared stop position may be hundreds of metres from the nearest
        shape point.  This is common in UK regional bus services.

        Args:
            shape_coords: Full trip shape from shapes.txt, or [] / None.
            u_lon, u_lat: Departure stop coordinates.
            v_lon, v_lat: Arrival stop coordinates.
            window_m:     Maximum acceptable snap distance in metres.

        Returns:
            List of (lon, lat) tuples.
        """
        if not shape_coords or len(shape_coords) < 2:
            return [] # [(u_lon, u_lat), (v_lon, v_lat)]

        # ── Step 1: Find i_u by scanning the full shape ───────────────────────
        # This is the only unrestricted global scan — departure stop U anchors
        # the search window so we know the direction of travel in the shape.
        def _nearest_from(lon: float, lat: float, start: int = 0) -> int:
            """Return the index of the shape point nearest to (lon, lat),
            searching only from `start` onwards.  Returns -1 if nothing
            found within window_m."""
            best_i, best_d = -1, float('inf')
            for i in range(start, len(shape_coords)):
                slon, slat = shape_coords[i]
                d = _haversine_m(lon, lat, slon, slat)
                if d < best_d:
                    best_d, best_i = d, i
            return best_i if best_d < window_m else -1

        i_u = _nearest_from(u_lon, u_lat, 0)
        if i_u < 0:
            return [] # [(u_lon, u_lat), (v_lon, v_lat)]

        # ── Step 2: Search for i_v FORWARD from i_u ───────────────────────────
        # Scanning forward from i_u prevents snapping to a shape point on the
        # return leg of a bidirectional shape (e.g. route 26 carries both
        # outbound and inbound geometry in one shape_id).  If the forward scan
        # fails (service 26 terminal turn-around, loop routes), fall back to a
        # reverse scan from i_u so we still get something rather than a
        # straight line.
        i_v = _nearest_from(v_lon, v_lat, i_u)
        if i_v < 0 or i_v == i_u:
            # Forward scan failed — try reverse scan (handles return-trip shapes)
            best_rev, best_d_rev = -1, float('inf')
            for i in range(i_u - 1, -1, -1):
                slon, slat = shape_coords[i]
                d = _haversine_m(v_lon, v_lat, slon, slat)
                if d < best_d_rev:
                    best_d_rev, best_rev = d, i
            if best_rev >= 0 and best_d_rev < window_m:
                i_v = best_rev
            else:
                return [] #[(u_lon, u_lat), (v_lon, v_lat)]

        # ── Step 3: Slice — direction is always i_u → i_v ────────────────────
        if i_u <= i_v:
            sliced = shape_coords[i_u: i_v + 1]
        else:
            sliced = list(reversed(shape_coords[i_v: i_u + 1]))

        return sliced if len(sliced) >= 2 else [] #[(u_lon, u_lat), (v_lon, v_lat)]