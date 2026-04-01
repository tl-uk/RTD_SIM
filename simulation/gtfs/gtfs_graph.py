"""
simulation/gtfs/gtfs_graph.py

Builds a NetworkX MultiDiGraph from a parsed GTFSLoader.

The graph is a transit network layer that sits alongside (never merged with)
the OSM road and rail graphs in GraphManager.  Nodes are GTFS stops; edges
carry scheduled travel times, headways, shape geometry, and fuel type so the
Router can compute a fully-loaded generalised cost.

Graph conventions (matching OSMnx / rail_spine conventions throughout):
  Node attributes:
    x          = longitude (float)
    y          = latitude  (float)
    stop_id    = GTFS stop_id (str)
    name       = stop_name (str)
    wheelchair = bool
    route_types = frozenset of GTFS route_type ints served at this stop

  Edge attributes:
    travel_time_s  = scheduled in-vehicle seconds (float)
    headway_s      = average headway in seconds (float)  — waiting cost
    shape_coords   = [(lon, lat), ...] from shapes.txt   — render geometry
    route_ids      = [route_id, ...]
    mode           = RTD_SIM mode string (e.g. 'bus', 'local_train')
    fuel_type      = 'electric' | 'diesel' | 'hydrogen' | 'hybrid'
    emissions_g_km = float (per-km CO₂e, derived from fuel_type)
    length         = approximate edge length in metres (haversine)
    gen_cost       = float stub (overwritten by Router._apply_generalised_weights)

Transfer nodes:
  build_transfer_edges() snaps each stop to its nearest OSM walk-graph node
  and adds a 'transfer' edge so the Router's intermodal logic can route
  access/egress legs on foot.

Fuel → emissions mapping (g CO₂e / km):
  electric  →  35  (UK grid carbon intensity, 2024 — update yearly)
  diesel    → 130  (GB average diesel bus, measured)
  hydrogen  →   0  (green hydrogen; conservative: 20 if grey hydrogen)
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


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Haversine distance in metres."""
    R = 6_371_000.0
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class GTFSGraph:
    """
    Builds a transit NetworkX graph from a GTFSLoader.

    Usage:
        loader = GTFSLoader('gtfs.zip').load()
        headways = loader.compute_headways()
        builder = GTFSGraph(loader, headways)
        G_transit = builder.build()          # full graph
        builder.build_transfer_edges(G_transit, G_walk)   # stitch to OSM walk
    """

    def __init__(
        self,
        loader: Any,    # GTFSLoader
        headways: Optional[Dict[Tuple[str, str], int]] = None,
    ):
        self.loader   = loader
        self.headways = headways or {}

    # ── Main build ────────────────────────────────────────────────────────────

    def build(self) -> Optional[Any]:
        """
        Build and return the transit NetworkX MultiDiGraph.

        Each edge represents a consecutive stop pair served by at least one
        trip.  Parallel trips (same stops, different schedules) are merged
        into a single edge whose headway_s is the average of all services.

        Returns None if NetworkX is unavailable.
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
                route_types = set(),    # populated below
            )

        # ── Collect edges from stop_times ─────────────────────────────────────
        # edge_data[(u, v)]: list of {travel_time_s, route_id, shape_coords, mode, fuel_type}
        edge_accumulator: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)

        for trip_id, stops in loader.stop_times.items():
            trip    = loader.trips.get(trip_id, {})
            route_id = trip.get('route_id', '')
            route   = loader.routes.get(route_id, {})
            mode    = route.get('mode', 'bus')
            fuel    = route.get('fuel_type', 'diesel')
            rtype   = route.get('route_type', 3)

            shape_coords = loader.get_shape_for_trip(trip_id)

            for i in range(len(stops) - 1):
                u_st = stops[i]
                v_st = stops[i + 1]

                u = u_st['stop_id']
                v = v_st['stop_id']

                if u not in G.nodes or v not in G.nodes:
                    continue

                dep_s = u_st['departure_s']
                arr_s = v_st['arrival_s']
                travel_s = max(0, arr_s - dep_s) if arr_s >= dep_s else 60

                # Annotate node with route types
                G.nodes[u]['route_types'].add(rtype)
                G.nodes[v]['route_types'].add(rtype)

                # Slice shape geometry relevant to this edge
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

            route_ids = list({r['route_id'] for r in records})
            mode      = records[0]['mode']        # all records share mode (same stop pair)
            fuel_type = records[0]['fuel_type']
            shape     = records[0]['shape_coords'] or []

            # ── Resolve human-readable service names for tooltip display ──────
            # GTFSLoader may store these as 'short_name'/'long_name' (normalised)
            # or as the raw GTFS keys 'route_short_name'/'route_long_name'.
            route_short_names: List[str] = []
            route_long_names:  List[str] = []
            for rid in route_ids:
                r_data = loader.routes.get(rid, {})
                sn = r_data.get('short_name') or r_data.get('route_short_name', '')
                ln = r_data.get('long_name')  or r_data.get('route_long_name',  '')
                if sn: route_short_names.append(str(sn))
                if ln: route_long_names.append(str(ln))

            # Average headway from pre-computed table (fall back to per-service spacing)
            # Use the first route_id that has a headway entry
            headway_s = 3600
            for rid in route_ids:
                hw = self.headways.get((rid, u), None)
                if hw is not None:
                    headway_s = hw
                    break

            u_data = G.nodes[u]
            v_data = G.nodes[v]
            dist_m = _haversine_m(u_data['x'], u_data['y'], v_data['x'], v_data['y'])
            dist_km = dist_m / 1000.0

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
                gen_cost           = avg_travel_s / 3600.0 * 10.0,  # stub (£10/h VoT)
            )

        # Freeze route_types to frozenset for hashability
        for node in G.nodes:
            G.nodes[node]['route_types'] = frozenset(G.nodes[node].get('route_types', set()))

        logger.info(
            "GTFSGraph built: %d stop nodes, %d transit edges",
            G.number_of_nodes(), G.number_of_edges(),
        )
        return G

    # ── Transfer edge creation ────────────────────────────────────────────────

    def build_transfer_edges(
        self,
        G_transit: Any,
        G_walk: Any,
        walk_speed_m_s: float = 1.2,   # 4.3 km/h
        max_snap_m: float = 500.0,
    ) -> int:
        """
        Add bidirectional transfer edges between each GTFS stop and its
        nearest OSM walk-graph node.

        This is the "glue" that lets the intermodal router chain
        walk → board transit → ride → alight → walk.

        Args:
            G_transit:      The transit graph from build()
            G_walk:         OSMnx walk graph from GraphManager
            walk_speed_m_s: Walking speed in m/s (default 1.2 = 4.3 km/h)
            max_snap_m:     Ignore stops >500m from any walk node

        Returns:
            Number of transfer edges added.
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
            wlon = float(walk_data.get('x', lon))
            wlat = float(walk_data.get('y', lat))
            dist_m = _haversine_m(lon, lat, wlon, wlat)

            if dist_m > max_snap_m:
                continue

            walk_time_s = dist_m / walk_speed_m_s

            for u, v in [(stop_id, walk_node), (walk_node, stop_id)]:
                target_graph = G_walk if u == walk_node else G_transit
                if not target_graph.has_node(u) or not target_graph.has_node(v):
                    continue
                if not G_walk.has_edge(u, v) and not G_transit.has_edge(u, v):
                    G_walk.add_edge(
                        u, v,
                        length         = dist_m,
                        travel_time_s  = walk_time_s,
                        headway_s      = 0,
                        highway        = 'transfer',
                        mode           = 'walk',
                        fuel_type      = 'electric',
                        emissions_g_km = 0.0,
                        gen_cost       = walk_time_s / 3600.0 * 10.0,
                    )
            added += 1

        logger.info(
            "GTFSGraph: %d transfer edges added (stop → walk_node)",
            added,
        )
        return added

    # ── Nearest stop query ────────────────────────────────────────────────────

    def nearest_stop(
        self,
        G_transit: Any,
        coord: Tuple[float, float],
        mode_filter: Optional[str] = None,
        max_distance_m: float = 2000.0,
    ) -> Optional[str]:
        """
        Return the stop_id of the nearest transit stop to (lon, lat) coord.

        Args:
            G_transit:      The transit graph from build()
            coord:          (lon, lat)
            mode_filter:    If set, only consider stops that serve this RTD_SIM mode
                            (e.g. 'bus', 'local_train').
            max_distance_m: Return None if nearest is further than this.

        Returns:
            stop_id string or None.
        """
        if G_transit is None:
            return None

        lon, lat = coord
        best_id   = None
        best_dist = float('inf')

        for stop_id, data in G_transit.nodes(data=True):
            slat = data.get('y', 0)
            slon = data.get('x', 0)

            if mode_filter is not None:
                # Check if any edge at this stop carries the requested mode
                served_modes = {
                    G_transit.edges[e].get('mode', '')
                    for e in G_transit.edges(stop_id, keys=True)
                }
                if mode_filter not in served_modes:
                    continue

            d = _haversine_m(lon, lat, slon, slat)
            if d < best_dist:
                best_dist = d
                best_id   = stop_id

        if best_dist > max_distance_m:
            return None
        return best_id

    # ── Pydeck layer data ─────────────────────────────────────────────────────

    def get_stop_pydeck_data(self, G_transit: Any) -> List[Dict]:
        """
        Return stop list as pydeck-compatible dicts for a ScatterplotLayer.

        Each dict: lon, lat, name, mode, fuel_type, wheelchair, tooltip_html
        """
        if G_transit is None:
            return []
        data = []
        for stop_id, attrs in G_transit.nodes(data=True):
            # Collect route short names served at this stop (from outgoing edges)
            served_shorts: list = []
            for _, _, edata in G_transit.edges(stop_id, data=True):
                if edata.get('mode', 'walk') == 'walk':
                    continue
                for sn in edata.get('route_short_names', []):
                    if sn and sn not in served_shorts:
                        served_shorts.append(sn)
            routes_str = ', '.join(served_shorts[:6]) if served_shorts else ''

            data.append({
                'lon':       attrs.get('x', 0),
                'lat':       attrs.get('y', 0),
                'name':      attrs.get('name', stop_id),
                'stop_id':   stop_id,
                'wheelchair': attrs.get('wheelchair', False),
                'tooltip_html': (
                    f"<b>{attrs.get('name', stop_id)}</b><br/>"
                    + (f"Routes: {routes_str}<br/>" if routes_str else '')
                    + f"Stop ID: {stop_id}"
                    + ("<br/>♿ Wheelchair accessible" if attrs.get('wheelchair') else "")
                ),
            })
        return data

    def get_route_pydeck_data(self, G_transit: Any) -> List[Dict]:
        """
        Return route lines as pydeck-compatible dicts for a PathLayer.

        Uses shape_coords from edge attributes when available; falls back
        to straight lines between stop nodes.
        """
        if G_transit is None:
            return []

        _MODE_COLORS = {
            'bus':             [245, 158, 11],  # amber
            'tram':            [255, 193, 7],   # yellow
            'local_train':     [33, 150, 243],  # blue
            'intercity_train': [63, 81, 181],   # indigo
            'ferry_diesel':    [0, 150, 136],   # teal
            'ferry_electric':  [0, 188, 212],   # cyan
        }

        data = []
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

            color = _MODE_COLORS.get(mode, [128, 128, 128])
            fuel  = attrs.get('fuel_type', 'diesel')
            # Electric routes get a distinct visual — slightly brighter
            if fuel == 'electric':
                color = [min(255, c + 40) for c in color]

            # Build a concise service label: "26 / X27" or "Intercity Train"
            short_names = attrs.get('route_short_names', [])
            long_names  = attrs.get('route_long_names',  [])
            if short_names:
                service_label = ' / '.join(short_names[:4])
            elif long_names:
                service_label = long_names[0][:40]
            else:
                service_label = mode.replace('_', ' ').title()

            headway_s = attrs.get('headway_s', 3600)
            headway_str = f"{headway_s // 60} min" if headway_s > 0 else "on-demand"

            data.append({
                'path':    [[lon, lat] for lon, lat in shape],
                'color':   color,
                'mode':    mode,
                'fuel':    fuel,
                'headway': headway_s,
                'tooltip_html': (
                    f"<b>{service_label}</b><br/>"
                    f"{mode.replace('_', ' ').title()} · {fuel}<br/>"
                    f"Headway: {headway_str}"
                ),
            })
        return data

    # ── Internal helpers ──────────────────────────────────────────────────────

    # @staticmethod
    # def _slice_shape(
    #     shape_coords: Optional[List[Tuple[float, float]]],
    #     u_lon: float, u_lat: float,
    #     v_lon: float, v_lat: float,
    #     window_m: float = 200.0,
    # ) -> List[Tuple[float, float]]:
    #     """
    #     Return the sub-sequence of shape_coords between stops u and v.

    #     Finds the two shape points closest to u and v, then extracts
    #     everything between them.  Falls back to a 2-point straight line
    #     if no shape or points outside window.
    #     """
    #     if not shape_coords or len(shape_coords) < 2:
    #         return [(u_lon, u_lat), (v_lon, v_lat)]

    #     def nearest_idx(lon: float, lat: float) -> int:
    #         best_i, best_d = 0, float('inf')
    #         for i, (slon, slat) in enumerate(shape_coords):
    #             d = _haversine_m(lon, lat, slon, slat)
    #             if d < best_d:
    #                 best_d, best_i = d, i
    #         return best_i if best_d < window_m else -1

    #     i_u = nearest_idx(u_lon, u_lat)
    #     i_v = nearest_idx(v_lon, v_lat)

    #     if i_u < 0 or i_v < 0 or i_u == i_v:
    #         return [(u_lon, u_lat), (v_lon, v_lat)]

    #     start, end = min(i_u, i_v), max(i_u, i_v)
    #     sliced = shape_coords[start: end + 1]

    #     # Ensure direction matches u→v
    #     if i_u > i_v:
    #         sliced = list(reversed(sliced))

    #     return sliced if sliced else [(u_lon, u_lat), (v_lon, v_lat)]
    @staticmethod
    def _slice_shape(
        shape_coords: Optional[List[Tuple[float, float]]],
        u_lon: float, u_lat: float,
        v_lon: float, v_lat: float,
        window_m: float = 1500.0,  # <-- MASSIVE INCREASE for UK BODS inaccuracies
    ) -> List[Tuple[float, float]]:
        """
        Return the sub-sequence of shape_coords between stops u and v.
        """
        if not shape_coords or len(shape_coords) < 2:
            return [(u_lon, u_lat), (v_lon, v_lat)]

        def nearest_idx(lon: float, lat: float) -> int:
            best_i, best_d = 0, float('inf')
            for i, (slon, slat) in enumerate(shape_coords):
                d = _haversine_m(lon, lat, slon, slat)
                if d < best_d:
                    best_d, best_i = d, i
            return best_i if best_d < window_m else -1

        i_u = nearest_idx(u_lon, u_lat)
        i_v = nearest_idx(v_lon, v_lat)

        # VISUAL FIX: If we couldn't snap the stops to the shape, return a 2-point
        # line. router.py will intercept this and map it to the physical road network!
        if i_u < 0 or i_v < 0 or i_u == i_v:
            return []
        # if i_u < 0 or i_v < 0 or i_u == i_v:
        #     return [(u_lon, u_lat), (v_lon, v_lat)]

        start, end = min(i_u, i_v), max(i_u, i_v)
        sliced = shape_coords[start: end + 1]

        # Ensure direction matches u→v
        if i_u > i_v:
            sliced = list(reversed(sliced))

        return sliced if sliced else [(u_lon, u_lat), (v_lon, v_lat)]