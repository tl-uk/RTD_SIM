"""
simulation/spatial/router.py

Route computation with generalised cost and intermodal rail/transit transfers.

Architecture
------------
Three parallel graphs, never merged:
  • Road graph   (OSMnx 'drive')  — car, bus, van, truck, HGV
  • Rail graph   (OpenRailMap)    — local_train, intercity_train, freight_rail
  • Transit graph (GTFS)          — bus, tram, ferry

Generalised cost formula (per edge)
------------------------------------
    cost = (time_h × VoT)
         + (dist_km × energy_price)
         + (dist_km × emit_kg_km × carbon_tax)

Routing dispatch
-----------------
    mode == 'tram'         → _compute_gtfs_route  (GTFS → tram-spine fallback)
    mode in _RAIL_MODES    → _compute_intermodal_route
    mode in _TRANSIT_MODES → _compute_gtfs_route  (bus, ferry)
    all others             → _compute_road_route

Intermodal rail logic (NaPTAN-aware)
--------------------------------------
For local_train / intercity_train / freight_rail:
  1. Snap origin to nearest rail station using NaPTAN platform coordinates
     when available (stored on graph_manager.naptan_stops by environment_setup).
     Falls back to brute-force nearest OpenRailMap graph node.
  2. Same for destination.
  3. Walk access leg: origin → station (walk graph, interpolation, or drive).
  4. Rail leg on OpenRailMap graph with generalised-cost + track-type filtering.
  5. Walk egress leg: station → destination.
  6. Concatenate, removing duplicate boundary points.

NaPTAN integration
------------------
environment_setup.py stores DfT NaPTAN stop data on
graph_manager.naptan_stops after download.  The router reads this
attribute lazily so it works with or without NaPTAN — OpenRailMap node
snapping is the automatic fallback.

Walk graph weight
-----------------
When the walk graph is available, _compute_access_leg routes on it using
weight='length' (physical distance in metres), not hop count.  This
avoids the OSMnx BFS default which minimises the number of intersections
traversed rather than the actual walking distance.

Invalid route sentinel
-----------------------
_get_invalid_route() returns [].  Callers check ``if not route or len(route) < 2``.

Policy integration
------------------
Pass a ``policy_context`` dict to compute_route() with any of:
    value_of_time_gbp_h:  float  (default 10.0)
    energy_price_gbp_km:  float  (default 0.12)
    carbon_tax_gbp_tco2:  float  (default 0.0)
    boarding_penalty_min: float  (default 15.0)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING, cast

from simulation.spatial.coordinate_utils import (
    is_valid_lonlat, haversine_km, route_distance_km,
)
from simulation.spatial.rail_network import fetch_rail_graph

if TYPE_CHECKING:
    from simulation.spatial.graph_manager import GraphManager

logger = logging.getLogger(__name__)

try:
    import networkx as nx
    NETWORKX_AVAILABLE = True
except ImportError:
    NETWORKX_AVAILABLE = False
    logger.warning("NetworkX not available")

try:
    from simulation.route_alternative import RouteAlternative
    ROUTE_ALTERNATIVE_AVAILABLE = True
except ImportError:
    ROUTE_ALTERNATIVE_AVAILABLE = False

# ── Mode sets ──────────────────────────────────────────────────────────────────
# 'tram' is NOT in _RAIL_MODES — trams route via GTFS / tram spine, not
# the OpenRailMap mainline topology.
_RAIL_MODES    = frozenset({'local_train', 'intercity_train', 'freight_rail'})
_TRANSIT_MODES = frozenset({'bus', 'ferry_diesel', 'ferry_electric'})

# Minimum walk-leg distance to include in multimodal segment list.
# Legs shorter than this exist physically (e.g. 30 m snap to nearest rail node)
# but render as a dot on the map and clutter the per-segment tooltip.
# 150 m is the threshold: anything shorter is omitted from route_segments
# while still being included in the flat full_route for agent movement.
_MIN_WALK_LEG_KM: float = 0.15

# ── Default policy parameters ─────────────────────────────────────────────────
_DEFAULT_POLICY: Dict[str, float] = {
    'value_of_time_gbp_h':  10.0,
    'energy_price_gbp_km':   0.12,
    'carbon_tax_gbp_tco2':   0.0,
    'boarding_penalty_min':  15.0,
}

# ── Emissions factors (g CO₂/km) ─────────────────────────────────────────────
_EMISSIONS_G_KM: Dict[str, float] = {
    'walk': 0, 'bike': 0, 'e_scooter': 0, 'cargo_bike': 0,
    'car': 170, 'ev': 0, 'bus': 82, 'tram': 35,
    'taxi_ev': 0, 'taxi_diesel': 160,
    'van_electric': 0, 'van_diesel': 150,
    'truck_electric': 0, 'truck_diesel': 200,
    'hgv_electric': 0, 'hgv_diesel': 900, 'hgv_hydrogen': 0,
    'local_train': 41, 'intercity_train': 41, 'freight_rail': 35,
    'ferry_diesel': 115, 'ferry_electric': 0,
    'flight_domestic': 255, 'flight_electric': 0,
}


class Router:
    """
    Computes routes and alternatives using parallel road + rail + transit graphs.

    NaPTAN awareness
    ----------------
    When environment_setup.py loads NaPTAN stop data, it stores it on
    graph_manager.naptan_stops.  _nearest_rail_node() uses these precise
    platform coordinates to snap agents to stations before routing on the
    OpenRailMap graph, giving better results than snapping to raw OSM node
    centroids which may be mid-track rather than at the platform.
    """

    def __init__(self, graph_manager: 'GraphManager', congestion_manager=None):
        self.graph_manager      = graph_manager
        self.congestion_manager = congestion_manager

        # Rail graph loaded lazily on first rail request.
        self._rail_graph: Optional[Any]  = None
        self._rail_graph_attempted: bool = False

        # ── Mode → OSMnx network type ──────────────────────────────────────────
        self.mode_network_types: Dict[str, str] = {
            'walk':            'walk',
            'bike':            'bike',
            'cargo_bike':      'bike',
            'e_scooter':       'bike',
            'bus':             'drive',
            'car':             'drive',
            'ev':              'drive',
            'taxi_ev':         'drive',
            'taxi_diesel':     'drive',
            'van_electric':    'drive',
            'van_diesel':      'drive',
            'truck_electric':  'drive',
            'truck_diesel':    'drive',
            'hgv_electric':    'drive',
            'hgv_diesel':      'drive',
            'hgv_hydrogen':    'drive',
            'tram':            'drive',    # drive proxy when no GTFS/spine
            'local_train':     'rail',
            'intercity_train': 'rail',
            'freight_rail':    'rail',
            'ferry_diesel':    'drive',
            'ferry_electric':  'drive',
            'flight_domestic': 'drive',
            'flight_electric': 'drive',
        }

        # ── Speed in km/min ─────────────────────────────────────────────────────
        self.speeds_km_min: Dict[str, float] = {
            'walk':            0.083,   # 5 km/h
            'bike':            0.25,    # 15 km/h
            'cargo_bike':      0.20,
            'e_scooter':       0.33,    # 20 km/h
            'bus':             0.33,
            'car':             0.50,    # 30 km/h urban average
            'ev':              0.50,
            'taxi_ev':         0.45,
            'taxi_diesel':     0.45,
            'van_electric':    0.45,
            'van_diesel':      0.45,
            'truck_electric':  0.40,
            'truck_diesel':    0.40,
            'hgv_electric':    0.35,
            'hgv_diesel':      0.42,
            'hgv_hydrogen':    0.42,
            'tram':            0.42,
            'local_train':     1.33,    # 80 km/h
            'intercity_train': 2.50,    # 150 km/h
            'freight_rail':    1.33,
            'ferry_diesel':    0.58,    # 35 km/h
            'ferry_electric':  0.50,
            'flight_domestic': 11.67,   # 700 km/h
            'flight_electric': 6.67,
        }

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def compute_route(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str,
        policy_context: Optional[Dict] = None,
    ) -> List[Tuple[float, float]]:
        """
        Compute shortest generalised-cost route.

        Returns [] on any failure so callers can test ``if not route``.
        """
        if not (is_valid_lonlat(origin) and is_valid_lonlat(dest)):
            logger.error("❌ %s: invalid coords %s → %s", agent_id, origin, dest)
            return []

        if haversine_km(origin, dest) < 0.1:
            return [origin, dest]

        policy = {**_DEFAULT_POLICY, **(policy_context or {})}

        if mode == 'tram':
            return self._compute_gtfs_route(agent_id, origin, dest, mode, policy)

        if mode in _RAIL_MODES:
            return self._compute_intermodal_route(agent_id, origin, dest, mode, policy)

        if mode in _TRANSIT_MODES:
            if mode in ('ferry_diesel', 'ferry_electric'):
                return self._compute_ferry_route(agent_id, origin, dest, mode, policy)
            return self._compute_gtfs_route(agent_id, origin, dest, mode, policy)

        return self._compute_road_route(agent_id, origin, dest, mode, policy)

    def compute_route_with_segments(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str,
        policy_context: Optional[Dict] = None,
    ) -> Tuple[List[Tuple[float, float]], List[Dict]]:
        """
        Compute a route and return it together with per-segment mode metadata.

        This is the preferred API for agents that need multi-modal colour-coding
        on the map.  The BDI planner should store ``route_segments`` on the
        agent state so visualization.py can split PathLayer per segment.

        Returns
        -------
        (flat_route, segments)

        flat_route  : List[Tuple[float, float]] — same as compute_route()
        segments    : List[dict], each with keys:
                        path   — List[Tuple[float, float]] for this segment
                        mode   — transport mode string (e.g. 'walk', 'local_train')
                        label  — human-readable label (e.g. 'ScotRail', 'walk')

        For non-PT modes (car, ev, bike, walk) segments == [{'path': route, 'mode': mode}].
        For intermodal rail: access-walk / rail / egress-walk segments.
        For GTFS transit:    access-walk / transit / egress-walk segments.
        For ferry:           access-walk / ferry / egress-walk segments.

        Callers may always fall back to the flat_route when segments is empty.
        """
        if not (is_valid_lonlat(origin) and is_valid_lonlat(dest)):
            return [], []

        policy = {**_DEFAULT_POLICY, **(policy_context or {})}

        # ── Rail intermodal ────────────────────────────────────────────────────
        if mode in _RAIL_MODES:
            return self._intermodal_with_segments(agent_id, origin, dest, mode, policy)

        # ── Ferry ──────────────────────────────────────────────────────────────
        if mode in ('ferry_diesel', 'ferry_electric'):
            return self._ferry_with_segments(agent_id, origin, dest, mode)

        # ── GTFS transit (bus, tram) ───────────────────────────────────────────
        if mode == 'tram' or mode == 'bus':
            return self._gtfs_with_segments(agent_id, origin, dest, mode, policy)

        # ── All other modes: single segment ───────────────────────────────────
        route = self.compute_route(agent_id, origin, dest, mode, policy_context)
        segments = [{'path': route, 'mode': mode, 'label': mode}] if route else []
        return route, segments

    def _intermodal_with_segments(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str,
        policy: Dict,
    ) -> Tuple[List, List]:
        """Intermodal rail route split into (walk, rail, walk) segments."""
        # Compute the full route; then re-derive segment boundaries from access
        # and egress leg lengths.
        rail_graph = self._get_rail_graph()
        if rail_graph is None:
            route = self._get_invalid_route(origin, dest)
            return route, []

        orig_node = self._nearest_rail_node(origin, rail_graph)
        dest_node = self._nearest_rail_node(dest,   rail_graph)
        if orig_node is None or dest_node is None or orig_node == dest_node:
            return [], []

        orig_coord = (float(rail_graph.nodes[orig_node].get('x', 0)),
                      float(rail_graph.nodes[orig_node].get('y', 0)))
        dest_coord = (float(rail_graph.nodes[dest_node].get('x', 0)),
                      float(rail_graph.nodes[dest_node].get('y', 0)))

        if (haversine_km(origin, orig_coord) > self._MAX_ACCESS_KM
                or haversine_km(dest_coord, dest) > self._MAX_ACCESS_KM):
            return [], []

        access_leg = self._compute_access_leg(agent_id + '_access', origin, orig_coord)
        egress_leg = self._compute_access_leg(agent_id + '_egress', dest_coord, dest)

        try:
            wk = self._apply_generalised_weights(rail_graph, mode, policy)
            rail_nodes = nx.shortest_path(rail_graph, orig_node, dest_node, weight=wk)
            # ── Kinematic guard: edge-penalty retry ──────────────────────────
            # nx.restricted_view([reversal_node]) raises NetworkXNoPath when
            # that node is the only topological connection between origin and
            # destination (common at the Craiglockhart/Slateford crossing).
            # The bare `except Exception: return [],[]` swallows this silently,
            # producing zero log output and forcing EV fallback.
            #
            # Fix: multiply the gen_cost on all edges incident to the reversal
            # node by ×10,000.  Dijkstra will still find a path (topology
            # unchanged) but strongly prefers any alternative route.  Original
            # weights are restored in the `finally` block.
            if self._has_heading_reversal(rail_graph, rail_nodes):
                reversal_node = self._find_reversal_node(rail_graph, rail_nodes)
                if reversal_node is not None:
                    _PENALTY = 10_000.0
                    _incident = (
                        list(rail_graph.in_edges(reversal_node,  keys=True, data=True))
                        + list(rail_graph.out_edges(reversal_node, keys=True, data=True))
                    )
                    _saved = {(u, v, k): d.get(wk, 1.0) for u, v, k, d in _incident}
                    try:
                        for u, v, k, d in _incident:
                            d[wk] = _saved[(u, v, k)] * _PENALTY
                        rail_nodes = nx.shortest_path(
                            rail_graph, orig_node, dest_node, weight=wk
                        )
                        if self._has_heading_reversal(rail_graph, rail_nodes):
                            logger.warning(
                                "%s: %s heading reversal persists after penalty "
                                "retry — accepting best available route",
                                agent_id, mode,
                            )
                        else:
                            logger.info(
                                "%s: %s heading reversal resolved via penalty "
                                "on node %s",
                                agent_id, mode, reversal_node,
                            )
                    except Exception as _pen_exc:
                        logger.warning(
                            "%s: %s penalty retry failed (%s) — rejecting",
                            agent_id, mode, _pen_exc,
                        )
                        return [], []
                    finally:
                        for u, v, k, d in _incident:
                            d[wk] = _saved[(u, v, k)]
                else:
                    logger.warning(
                        "%s: %s heading reversal — reversal node not found",
                        agent_id, mode,
                    )
            rail_coords = self._interpolate(
                self._extract_geometry(rail_graph, rail_nodes), max_segment_km=0.2,
            )
        except Exception:
            return [], []

        if not rail_coords or len(rail_coords) < 2:
            return [], []

        # Sanity-check: reject routes whose rail portion is far more circuitous
        # than the straight-line distance.  The OpenRailMap graph has isolated
        # sub-graphs joined by long transfer edges; shortest-path sometimes
        # threads through them producing impossible sharp bends.
        rail_straight = haversine_km(orig_coord, dest_coord)
        rail_actual   = route_distance_km(rail_coords)
        if rail_straight > 0.5 and rail_actual > rail_straight * 4.0:
            logger.warning(
                "%s: %s rail detour too large (%.1fkm rail vs %.1fkm straight, ratio=%.1f) — rejecting",
                agent_id, mode, rail_actual, rail_straight, rail_actual / rail_straight,
            )
            return [], []

        # Only include walk legs that are long enough to be meaningful on the
        # map (≥ _MIN_WALK_LEG_KM). Access legs longer than _WALK_ACCESS_KM are
        # labelled 'car' (drive to station) rather than 'walk' — no agent walks
        # 2+ km to board a train when a car/taxi is available.
        access_dist = haversine_km(origin, orig_coord)
        egress_dist = haversine_km(dest_coord, dest)

        def _access_mode(dist_km: float) -> str:
            return 'walk' if dist_km <= self._WALK_ACCESS_KM else 'car'

        segments: List[Dict] = []
        if access_leg and len(access_leg) >= 2 and access_dist >= _MIN_WALK_LEG_KM:
            a_mode = _access_mode(access_dist)
            segments.append({
                'path':  access_leg,
                'mode':  a_mode,
                'label': 'Walk to station' if a_mode == 'walk' else 'Drive to station',
            })
        if rail_coords and len(rail_coords) >= 2:
            segments.append({
                'path':  rail_coords,
                'mode':  mode,
                'label': mode.replace('_', ' ').title(),
            })
        if egress_leg and len(egress_leg) >= 2 and egress_dist >= _MIN_WALK_LEG_KM:
            e_mode = _access_mode(egress_dist)
            segments.append({
                'path':  egress_leg,
                'mode':  e_mode,
                'label': 'Walk from station' if e_mode == 'walk' else 'Drive from station',
            })

        full_route = (
            (access_leg[:-1] if access_leg else [])
            + rail_coords
            + (egress_leg[1:] if len(egress_leg) > 1 else [])
        )

        logger.info(
            "✅ %s: %s intermodal-segments %.1fkm (%d pts, %d legs — access=%.2fkm egress=%.2fkm)",
            agent_id, mode, route_distance_km(full_route), len(full_route), len(segments),
            access_dist, egress_dist,
        )
        return full_route, segments

    def _ferry_with_segments(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str,
    ) -> Tuple[List, List]:
        """Ferry route split into (walk to port, ferry, walk from port) segments."""
        import networkx as nx  # guard against module-level ImportError branch
        G_ferry = self.graph_manager.get_graph('ferry')
        ferry_coords: List = []

        if G_ferry is not None and G_ferry.number_of_nodes() > 1:
            try:
                import osmnx as ox
                orig_node = ox.distance.nearest_nodes(G_ferry, origin[0], origin[1])
                dest_node = ox.distance.nearest_nodes(G_ferry, dest[0],   dest[1])
                if orig_node != dest_node:
                    path_nodes = nx.shortest_path(G_ferry, orig_node, dest_node, weight='length')
                    for i in range(len(path_nodes) - 1):
                        u, v = path_nodes[i], path_nodes[i + 1]
                        edge_map = G_ferry.get_edge_data(u, v) or {}
                        best_shape: list = []
                        for ed in edge_map.values():
                            s = ed.get('shape_coords') or []
                            if len(s) > len(best_shape):
                                best_shape = s
                        if best_shape:
                            ferry_coords.extend(best_shape if i == 0 else best_shape[1:])
                        else:
                            ux = G_ferry.nodes[u].get('x', 0)
                            uy = G_ferry.nodes[u].get('y', 0)
                            vx = G_ferry.nodes[v].get('x', 0)
                            vy = G_ferry.nodes[v].get('y', 0)
                            if i == 0:
                                ferry_coords.append((ux, uy))
                            ferry_coords.append((vx, vy))
                    ferry_coords = self._interpolate(ferry_coords, max_segment_km=0.2)
            except Exception as exc:
                logger.debug("Ferry segment routing failed: %s", exc)

        if not ferry_coords:
            ferry_coords = self._interpolate([origin, dest], max_segment_km=0.2)

        # Access/egress: walk to/from nearest terminal
        access_leg = []
        egress_leg = []
        orig_pos   = origin   # safe defaults if graph lookup fails
        dest_pos   = dest
        if G_ferry is not None and G_ferry.number_of_nodes() > 1:
            try:
                import osmnx as ox
                orig_n   = ox.distance.nearest_nodes(G_ferry, origin[0], origin[1])
                dest_n   = ox.distance.nearest_nodes(G_ferry, dest[0],   dest[1])
                orig_pos = (G_ferry.nodes[orig_n].get('x', origin[0]),
                            G_ferry.nodes[orig_n].get('y', origin[1]))
                dest_pos = (G_ferry.nodes[dest_n].get('x', dest[0]),
                            G_ferry.nodes[dest_n].get('y', dest[1]))
                access_leg = self._compute_access_leg(agent_id + '_access', origin, orig_pos)
                egress_leg = self._compute_access_leg(agent_id + '_egress', dest_pos, dest)
            except Exception:
                pass

        access_dist = haversine_km(origin, orig_pos)
        egress_dist = haversine_km(dest_pos, dest)

        segments: List[Dict] = []
        if access_leg and len(access_leg) >= 2 and access_dist >= _MIN_WALK_LEG_KM:
            segments.append({'path': access_leg, 'mode': 'walk', 'label': 'Walk to port'})
        if ferry_coords and len(ferry_coords) >= 2:
            label = 'Ferry (electric)' if 'electric' in mode else 'Ferry'
            segments.append({'path': ferry_coords, 'mode': mode, 'label': label})
        if egress_leg and len(egress_leg) >= 2 and egress_dist >= _MIN_WALK_LEG_KM:
            segments.append({'path': egress_leg, 'mode': 'walk', 'label': 'Walk from port'})

        full_route = (
            (access_leg[:-1] if access_leg else [])
            + ferry_coords
            + (egress_leg[1:] if len(egress_leg) > 1 else [])
        )
        if not full_route:
            full_route = ferry_coords
        return full_route, segments

    def _gtfs_with_segments(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str,
        policy: Dict,
    ) -> Tuple[List, List]:
        """GTFS route split into (walk, transit, walk) segments."""
        # Compute full route via standard GTFS path; we reconstruct the access
        # and egress legs to determine split points.
        G_transit = self._get_transit_graph()
        if G_transit is None:
            route = self._transit_fallback(agent_id, origin, dest, mode, policy)
            segments = [{'path': route, 'mode': mode, 'label': mode}] if route else []
            return route, segments

        try:
            from simulation.gtfs.gtfs_graph import GTFSGraph
            builder = GTFSGraph(None)
            origin_stop = builder.nearest_stop(G_transit, origin, mode_filter=mode, max_distance_m=2000)
            dest_stop   = builder.nearest_stop(G_transit, dest,   mode_filter=mode, max_distance_m=2000)
        except Exception:
            route = self._compute_gtfs_route(agent_id, origin, dest, mode, policy)
            segments = [{'path': route, 'mode': mode, 'label': mode}] if route else []
            return route, segments

        if not origin_stop or not dest_stop or origin_stop == dest_stop:
            # ── Same-stop snap: find second-nearest stop for dest ─────────────
            # When origin and destination are both close to the same GTFS stop
            # (e.g. agent 8828: both ends near Haymarket tram stop) the snap
            # returns the same node and routing fails.  Find the nearest stop
            # to dest that is NOT origin_stop and retry.
            if origin_stop and dest_stop and origin_stop == dest_stop:
                try:
                    from simulation.gtfs.gtfs_graph import GTFSGraph as _GTFSGraph
                    _builder2 = _GTFSGraph(None)
                    _tram_filters2 = ['tram', 'local_train'] if mode == 'tram' else [mode]
                    _max_m = 5000 if mode == 'tram' else 2000
                    for _mf2 in _tram_filters2:
                        # Try the exclude_stop kwarg first; fall back to a
                        # manual O(N) scan if GTFSGraph doesn't support it.
                        _candidate = None
                        try:
                            # Pass exclude_stop via **kwargs so Pylance does not
                            # statically check the GTFSGraph.nearest_stop signature
                            # (the parameter may not exist in all GTFSGraph versions).
                            # RuntimeError is caught below if the kwarg is unsupported.
                            _exclude_kwargs: Dict[str, Any] = {'exclude_stop': origin_stop}
                            _candidate = _builder2.nearest_stop(
                                G_transit, dest,
                                mode_filter=_mf2,
                                max_distance_m=_max_m,
                                **_exclude_kwargs,
                            )
                        except TypeError:
                            _best_d2 = float('inf')
                            for _nid2, _nd2 in G_transit.nodes(data=True):
                                if _nid2 == origin_stop:
                                    continue
                                _d2 = haversine_km(
                                    dest,
                                    (float(_nd2.get('x', 0)),
                                     float(_nd2.get('y', 0))),
                                )
                                if _d2 < _best_d2 and _d2 <= _max_m / 1000.0:
                                    _best_d2 = _d2
                                    _candidate = _nid2
                        if _candidate and _candidate != origin_stop:
                            dest_stop = _candidate
                            logger.debug(
                                "%s: GTFS same-stop resolved — dest_stop %s (mode=%s)",
                                agent_id, dest_stop, _mf2,
                            )
                            break
                except Exception as _ss_exc:
                    logger.debug("%s: same-stop retry failed: %s", agent_id, _ss_exc)

            if not origin_stop or not dest_stop or origin_stop == dest_stop:
                route = self._transit_fallback(agent_id, origin, dest, mode, policy)
                segments = [{'path': route, 'mode': mode, 'label': mode}] if route else []
                return route, segments

        first_d     = G_transit.nodes.get(origin_stop, {})
        first_coord = (float(first_d.get('x', origin[0])), float(first_d.get('y', origin[1])))
        last_d      = G_transit.nodes.get(dest_stop, {})
        last_coord  = (float(last_d.get('x', dest[0])), float(last_d.get('y', dest[1])))

        access_leg  = self._compute_access_leg(agent_id + '_access', origin, first_coord)
        egress_leg  = self._compute_access_leg(agent_id + '_egress', last_coord, dest)
        transit_route = self._compute_gtfs_route(agent_id, origin, dest, mode, policy)

        # Extract the transit-only portion (strip access/egress) for clean segment
        access_len  = len(access_leg) - 1 if access_leg else 0
        egress_len  = len(egress_leg) - 1 if egress_leg else 0
        transit_mid = transit_route[access_len: len(transit_route) - egress_len] if transit_route else transit_route

        access_dist = haversine_km(origin, first_coord)
        egress_dist = haversine_km(last_coord, dest)

        segments: List[Dict] = []
        if access_leg and len(access_leg) >= 2 and access_dist >= _MIN_WALK_LEG_KM:
            segments.append({'path': access_leg, 'mode': 'walk', 'label': 'Walk to stop'})
        if transit_mid and len(transit_mid) >= 2:
            segments.append({'path': transit_mid, 'mode': mode, 'label': mode.replace('_', ' ').title()})
        if egress_leg and len(egress_leg) >= 2 and egress_dist >= _MIN_WALK_LEG_KM:
            segments.append({'path': egress_leg, 'mode': 'walk', 'label': 'Walk from stop'})

        return transit_route, segments

    def compute_alternatives(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str,
        variants: List[str] = None,
        policy_context: Optional[Dict] = None,
    ) -> list:
        """Compute multiple route alternatives."""
        if not ROUTE_ALTERNATIVE_AVAILABLE:
            route = self.compute_route(agent_id, origin, dest, mode, policy_context)
            return [{'route': route, 'mode': mode, 'variant': 'shortest'}]

        variants = variants or ['shortest', 'fastest']
        policy   = {**_DEFAULT_POLICY, **(policy_context or {})}
        alternatives = []

        for variant in variants:
            route = self._compute_route_variant(origin, dest, mode, variant, agent_id, policy)
            if route and len(route) >= 2:
                alternatives.append(RouteAlternative(route, mode, variant))

        if not alternatives:
            basic = self.compute_route(agent_id, origin, dest, mode, policy_context)
            if basic and len(basic) >= 2:
                alternatives.append(RouteAlternative(basic, mode, 'shortest'))

        return alternatives

    # =========================================================================
    # ROAD ROUTING
    # =========================================================================

    def _compute_road_route(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str,
        policy: Dict,
    ) -> List[Tuple[float, float]]:
        """
        Route on a single OSMnx graph using generalised edge weights.

        Geometry is extracted from Shapely LineString attributes and interpolated
        at 50 m intervals for smooth animation and accurate per-step tracking.
        Returns [] when no path exists.
        """
        network_type = self.mode_network_types.get(mode, 'drive')
        graph        = self.graph_manager.get_graph(network_type)

        if graph is None:
            logger.warning("❌ %s: graph '%s' not loaded", agent_id, network_type)
            return self._get_invalid_route(origin, dest)

        try:
            orig_node = self.graph_manager.get_nearest_node(origin, network_type)
            dest_node = self.graph_manager.get_nearest_node(dest,   network_type)

            # ── Roundabout avoidance ──────────────────────────────────────────
            # Snapping to a roundabout node produces routes that start or end
            # mid-roundabout (physically impossible).  Walk off to the nearest
            # non-roundabout neighbour before routing.
            orig_node = self._avoid_roundabout(graph, orig_node)
            dest_node = self._avoid_roundabout(graph, dest_node)

            if orig_node is None or dest_node is None or orig_node == dest_node:
                return self._get_invalid_route(origin, dest)

            # ── Turn-restriction enforcement ──────────────────────────────────
            # nx.shortest_path on a MultiDiGraph respects edge direction (oneway
            # streets) but ignores OSM turn restrictions (no_left_turn,
            # no_u_turn, no_straight_on etc.) because those are stored as
            # relation metadata, not as edge attributes.
            #
            # Fix: use ox.routing.route_to_gdf / ox.shortest_path which
            # internally constructs a turn-penalty graph from OSM restriction
            # relations when the graph has been prepared with ox.add_edge_speeds
            # and ox.add_edge_travel_times.  We ensure travel_time is present
            # on the graph before routing and use it as the weight.
            #
            # If osmnx.shortest_path is unavailable (older osmnx), we fall back
            # to nx.shortest_path — the routes will be legal in direction but
            # turn restrictions won't be applied.
            weight_key = self._apply_generalised_weights(graph, mode, policy)
            self._ensure_travel_time(graph)

            try:
                import osmnx as ox
                route_nodes = ox.shortest_path(
                    graph, orig_node, dest_node, weight=weight_key,
                )
                if route_nodes is None:
                    raise nx.NetworkXNoPath("ox.shortest_path returned None")
            except AttributeError:
                # osmnx version does not expose ox.shortest_path
                route_nodes = nx.shortest_path(
                    graph, orig_node, dest_node, weight=weight_key,
                )

            # ── Road U-turn / illegal heading reversal guard ──────────────────
            # nx.shortest_path on a drive MultiDiGraph respects one-way edge
            # direction but does NOT enforce OSM turn restriction relations
            # (no_u_turn, no_left_turn, etc. stored as relation metadata).
            # Complex junctions (Princes Street / Lothian Road in Edinburgh)
            # have restrictions that only appear as OSM relations, producing
            # visually illegal U-turns when routed by length or travel_time.
            #
            # Fix: apply the same edge-penalty approach used for rail reversals.
            # Road U-turns have bearing change > 170° (tighter than rail 150°
            # because sharp road corners are legitimate at ~90°).
            # On detection: penalise incident edges of the reversal node ×1000,
            # re-route, then restore weights in finally.
            if (route_nodes is not None
                    and len(route_nodes) >= 3
                    and self._has_heading_reversal(
                        graph, route_nodes, threshold_deg=170.0)):
                reversal_node = self._find_reversal_node(
                    graph, route_nodes, threshold_deg=170.0
                )
                if reversal_node is not None:
                    _ROAD_PENALTY = 1_000.0
                    _incident = (
                        list(graph.in_edges(reversal_node,  keys=True, data=True))
                        + list(graph.out_edges(reversal_node, keys=True, data=True))
                    )
                    _saved = {(u, v, k): d.get(weight_key, 1.0)
                              for u, v, k, d in _incident}
                    try:
                        for u, v, k, d in _incident:
                            d[weight_key] = _saved[(u, v, k)] * _ROAD_PENALTY
                        retry_nodes = nx.shortest_path(
                            graph, orig_node, dest_node, weight=weight_key,
                        )
                        if not self._has_heading_reversal(
                            graph, retry_nodes, threshold_deg=170.0
                        ):
                            route_nodes = retry_nodes
                            logger.debug(
                                "%s: %s U-turn resolved via penalty on node %s",
                                agent_id, mode, reversal_node,
                            )
                        else:
                            logger.debug(
                                "%s: %s U-turn persists after penalty retry — "
                                "accepting best available route",
                                agent_id, mode,
                            )
                            route_nodes = retry_nodes
                    except Exception:
                        pass  # penalty retry failed — use original route
                    finally:
                        for u, v, k, d in _incident:
                            d[weight_key] = _saved[(u, v, k)]

            return self._interpolate(
                self._extract_geometry(graph, route_nodes),
                max_segment_km=0.05,
            )

        except nx.NetworkXNoPath:
            logger.warning("No road path for %s using %s", agent_id, mode)
            return self._get_invalid_route(origin, dest)
        except Exception as exc:
            logger.error("❌ %s: road routing failed: %s", agent_id, exc)
            return self._get_invalid_route(origin, dest)

    # =========================================================================
    # RAIL INTERMODAL ROUTING
    # =========================================================================

    def _get_rail_graph(self) -> Optional[Any]:
        """
        Return the rail graph, loading it lazily when not yet registered.

        Priority:
          1. graph_manager.graphs['rail'] — set by env.load_rail_graph().
          2. self._rail_graph — cached from a previous lazy load.
          3. Fetch from OpenRailMap using drive-graph bbox (last resort).

        env.load_rail_graph() should always be called during setup
        (environment_setup.py).  Path 3 is a last-resort fallback.
        """
        cached = self.graph_manager.get_graph('rail')
        if cached is not None:
            return cached

        if self._rail_graph is not None:
            return self._rail_graph

        if self._rail_graph_attempted:
            return None

        self._rail_graph_attempted = True
        logger.info("Loading OpenRailMap graph (lazy first-access)…")
        try:
            drive = self.graph_manager.get_graph('drive')
            if drive is not None:
                xs   = [d['x'] for _, d in drive.nodes(data=True)]
                ys   = [d['y'] for _, d in drive.nodes(data=True)]
                bbox = (max(ys), min(ys), max(xs), min(xs))   # N, S, E, W
            else:
                bbox = (56.0, 55.85, -3.05, -3.40)   # Edinburgh default

            self._rail_graph = fetch_rail_graph(bbox)

            if self._rail_graph is not None:
                logger.info(
                    "✅ Rail graph: %d nodes, %d edges",
                    len(self._rail_graph.nodes), len(self._rail_graph.edges),
                )
                self.graph_manager.graphs['rail'] = self._rail_graph
            else:
                logger.warning("⚠️  Rail graph fetch returned None")
        except Exception as exc:
            logger.error("Rail graph load failed: %s", exc)
            self._rail_graph = None

        return self._rail_graph

    # Maximum walk-to-station distance: beyond this the graph is too sparse
    # for the area and the route is rejected rather than producing a
    # multi-kilometre "walk" leg mislabelled as a rail route.
    _MAX_ACCESS_KM: float = 3.0   # Maximum station access distance accepted
    _WALK_ACCESS_KM: float = 1.2  # Above this, access leg is labelled 'car' not 'walk'
    # Rationale: a 5km _MAX_ACCESS_KM was accepting 4-5km walk legs to stations,
    # which are unrealistic (no one walks 5km to board a train).  3km is still
    # generous enough to handle Edinburgh's station spacing while suppressing
    # topology artefacts where the nearest rail node is far from any real station.

    def _nearest_rail_node(
        self,
        coord: Tuple[float, float],
        rail_graph: Any,
    ) -> Optional[Any]:
        """
        Return the nearest node in the rail graph to (lon, lat) coord.

        NaPTAN-aware snapping
        ---------------------
        When NaPTAN stop data has been loaded, environment_setup.py stores it
        on both env.naptan_stops (for the visualiser) and
        graph_manager.naptan_stops (for the router).  _nearest_rail_node reads
        from graph_manager.naptan_stops:

          1. Find the nearest NaPTAN rail/metro stop to the agent coord.
          2. Use the NaPTAN platform coordinate as the snap target.
          3. Find the nearest OpenRailMap graph node to that platform.

        This gives better results than snapping directly to OpenRailMap
        nodes, which are often mid-track rather than at the platform edge.
        NaPTAN coordinates come from the DfT's authoritative dataset and
        are accurate to ±5 m for most UK stations.

        Falls back to direct brute-force graph node scan when NaPTAN is
        absent or the nearest NaPTAN stop is beyond _MAX_ACCESS_KM.
        """
        if rail_graph is None:
            return None

        # ── NaPTAN snap (preferred) ───────────────────────────────────────
        naptan_stops = getattr(self.graph_manager, 'naptan_stops', [])
        if naptan_stops:
            try:
                from simulation.spatial.naptan_loader import (
                    nearest_naptan_stop,
                    RAIL_ONLY_STOP_TYPES,   # RLY only — never MET/FER/TMU
                )
                # Use RAIL_ONLY_STOP_TYPES (RLY) not the broad RAIL_STOP_TYPES.
                # RAIL_STOP_TYPES includes MET (tram stops) and FER (ferry
                # terminals) — both of which are not on the rail graph.
                # Edinburgh has 74 MET stops and 18 FER stops vs 20 RLY stops;
                # the MET stops are closer to most city-centre agents, so without
                # this fix the snap returns a tram stop, then the intermodal
                # routing fails because that coordinate is not on the rail graph.
                naptan_hit = nearest_naptan_stop(
                    coord,
                    naptan_stops,
                    stop_types=RAIL_ONLY_STOP_TYPES,
                    max_km=self._MAX_ACCESS_KM,
                )
                if naptan_hit is not None:
                    snap_coord = (naptan_hit.lon, naptan_hit.lat)
                    logger.debug(
                        "NaPTAN rail snap: %.4f,%.4f → %s (%s) at %.0fm",
                        coord[0], coord[1],
                        naptan_hit.common_name, naptan_hit.stop_type,
                        haversine_km(coord, snap_coord) * 1000,
                    )
                    return self._brute_force_nearest_node(snap_coord, rail_graph)
            except Exception as _ne:
                logger.debug("NaPTAN snap failed: %s — direct scan", _ne)

        # ── Direct brute-force scan (fallback) ────────────────────────────
        return self._brute_force_nearest_node(coord, rail_graph)

    def _brute_force_nearest_node(
        self,
        coord: Tuple[float, float],
        rail_graph: Any,
    ) -> Optional[Any]:
        """
        O(N) nearest-node scan of the rail graph.

        For the OpenRailMap graph (hundreds–thousands of nodes per city bbox)
        this is fast enough.  For the 41-station spine it is trivial.
        """
        lon, lat = coord
        best_node = None
        best_dist = float('inf')
        for node, data in rail_graph.nodes(data=True):
            nlon = float(data.get('x', data.get('lon', 0)))
            nlat = float(data.get('y', data.get('lat', 0)))
            d    = haversine_km((lon, lat), (nlon, nlat))
            if d < best_dist:
                best_dist = d
                best_node = node
        return best_node

    def _ensure_travel_time(self, graph: Any) -> None:
        """
        Ensure every edge in graph has a 'travel_time' attribute.

        osmnx.shortest_path() uses travel_time as its default weight for
        turn-restriction-aware routing.  If the graph was loaded from a
        pickle cache created before travel_time was added, the attribute
        will be missing and ox.shortest_path falls back to length, defeating
        the turn-restriction logic.

        This method is idempotent — it checks one edge before doing work,
        so it is cheap to call on every road route.
        """
        try:
            import osmnx as ox
            # Fast check: sample first edge
            sample = next(iter(graph.edges(data=True)), None)
            if sample is None:
                return
            _, _, sample_data = sample
            if 'travel_time' in sample_data:
                return
            # Add speeds and travel times in-place
            graph = ox.add_edge_speeds(graph)
            graph = ox.add_edge_travel_times(graph)
        except Exception:
            pass   # non-fatal — routing still works with length weight

    def _avoid_roundabout(
        self,
        graph: Any,
        node: Any,
        max_hops: int = 2,
    ) -> Any:
        """
        Step off a roundabout node to the nearest non-roundabout neighbour.

        OSMnx `nearest_nodes()` finds the closest graph node by Euclidean
        distance regardless of road type.  Roundabout nodes sit at junctions
        and are statistically overrepresented near any road origin/destination.
        An agent whose snapped node is mid-roundabout produces routes that
        start or end in the middle of a traffic circle, which is:
          (a) physically impossible (no stopping on a roundabout)
          (b) visually confusing on the map

        Strategy: if the snapped node has any adjacent edge tagged
        junction=roundabout, walk up to max_hops hops along the graph to
        find a connected node that is NOT part of a roundabout.

        Args:
            graph:    NetworkX drive/walk graph.
            node:     Node returned by get_nearest_node().
            max_hops: Maximum number of hops to walk (default 2 — one hop
                      always exits a standard roundabout; two handles large
                      multi-lane roundabouts like the A720/A8 interchange).

        Returns:
            Adjusted node (original node if no roundabout was detected,
            or if the graph is None / the node is not in the graph).
        """
        if node is None or graph is None or node not in graph:
            return node

        def _on_roundabout(n: Any) -> bool:
            """Return True if any edge adjacent to n is a roundabout edge."""
            try:
                for _, _, data in graph.edges(n, data=True):
                    junction = data.get('junction', '')
                    hw       = data.get('highway', '')
                    if junction == 'roundabout' or hw == 'roundabout':
                        return True
                # Also check OSMnx node tag
                if graph.nodes[n].get('junction') == 'roundabout':
                    return True
            except Exception:
                pass
            return False

        if not _on_roundabout(node):
            return node

        # BFS up to max_hops to find the nearest non-roundabout node
        from collections import deque
        visited = {node}
        queue   = deque([(node, 0)])
        while queue:
            current, depth = queue.popleft()
            if depth > max_hops:
                break
            try:
                neighbours = list(graph.neighbors(current))
            except Exception:
                break
            for nb in neighbours:
                if nb in visited:
                    continue
                visited.add(nb)
                if not _on_roundabout(nb):
                    logger.debug(
                        "Roundabout avoidance: %s → %s (%d hop%s)",
                        node, nb, depth + 1, 's' if depth else '',
                    )
                    return nb
                queue.append((nb, depth + 1))

        # Could not escape — return original
        return node

    def _compute_intermodal_route(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str,
        policy: Dict,
    ) -> List[Tuple[float, float]]:
        """
        Three-leg intermodal route: access (walk) → rail → egress (walk).

        Rejection guards
        ----------------
        1. Rail graph unavailable.
        2. Origin and destination snap to the same rail node.
        3. Nearest rail node is > _MAX_ACCESS_KM away (fragmented graph).
        4. Track topology fragmented — nx.NetworkXNoPath raised.

        All guards return [] so the BDI planner falls back to another mode.
        """
        rail_graph = self._get_rail_graph()
        if rail_graph is None:
            return self._get_invalid_route(origin, dest)

        orig_rail_node = self._nearest_rail_node(origin, rail_graph)
        dest_rail_node = self._nearest_rail_node(dest,   rail_graph)

        if (orig_rail_node is None
                or dest_rail_node is None
                or orig_rail_node == dest_rail_node):
            return self._get_invalid_route(origin, dest)

        orig_rail_coord = (
            float(rail_graph.nodes[orig_rail_node].get('x', 0)),
            float(rail_graph.nodes[orig_rail_node].get('y', 0)),
        )
        dest_rail_coord = (
            float(rail_graph.nodes[dest_rail_node].get('x', 0)),
            float(rail_graph.nodes[dest_rail_node].get('y', 0)),
        )

        if (haversine_km(origin, orig_rail_coord) > self._MAX_ACCESS_KM
                or haversine_km(dest_rail_coord, dest) > self._MAX_ACCESS_KM):
            return self._get_invalid_route(origin, dest)

        # ── Access and egress legs ────────────────────────────────────────────
        access_leg = self._compute_access_leg(agent_id + '_access', origin, orig_rail_coord)
        egress_leg = self._compute_access_leg(agent_id + '_egress', dest_rail_coord, dest)

        # ── Rail leg ──────────────────────────────────────────────────────────
        try:
            rail_weight_key = self._apply_generalised_weights(rail_graph, mode, policy)
            rail_nodes      = nx.shortest_path(
                rail_graph, orig_rail_node, dest_rail_node, weight=rail_weight_key,
            )
            # ── Kinematic guard with one-shot retry ───────────────────────────
            if self._has_heading_reversal(rail_graph, rail_nodes):
                reversal_node = self._find_reversal_node(rail_graph, rail_nodes)
                if reversal_node is not None:
                    try:
                        G_restricted = nx.restricted_view(
                            rail_graph, [reversal_node], []
                        )
                        rail_nodes = nx.shortest_path(
                            G_restricted, orig_rail_node, dest_rail_node,
                            weight=rail_weight_key,
                        )
                        if self._has_heading_reversal(G_restricted, rail_nodes):
                            logger.warning(
                                "%s: %s heading reversal persists after retry — rejecting",
                                agent_id, mode,
                            )
                            return self._get_invalid_route(origin, dest)
                        logger.info(
                            "%s: %s heading reversal resolved by excluding node %s",
                            agent_id, mode, reversal_node,
                        )
                    except Exception:
                        return self._get_invalid_route(origin, dest)
                else:
                    logger.warning(
                        "%s: %s heading reversal — no retry node found, rejecting",
                        agent_id, mode,
                    )
                    return self._get_invalid_route(origin, dest)
            rail_coords     = self._interpolate(
                self._extract_geometry(rail_graph, rail_nodes),
                max_segment_km=0.2,
            )
        except nx.NetworkXNoPath:
            logger.warning(
                "❌ %s: track topology fragmented between %s and %s",
                agent_id, orig_rail_node, dest_rail_node,
            )
            return self._get_invalid_route(origin, dest)
        except Exception as exc:
            logger.error("❌ %s: rail leg failed: %s", agent_id, exc)
            return self._get_invalid_route(origin, dest)

        # ── Stitch ────────────────────────────────────────────────────────────
        full_route: List[Tuple[float, float]] = (
            (access_leg[:-1] if access_leg else [])
            + rail_coords
            + (egress_leg[1:] if len(egress_leg) > 1 else [])
        )

        if len(full_route) < 2:
            return self._get_invalid_route(origin, dest)

        logger.info(
            "✅ %s: %s intermodal %.1fkm (%d pts)",
            agent_id, mode, route_distance_km(full_route), len(full_route),
        )
        return full_route

    # =========================================================================
    # GTFS TRANSIT ROUTING
    # =========================================================================

    def _get_transit_graph(self) -> Optional[Any]:
        """
        Return the GTFS transit graph or None.

        Must be pre-loaded via env.load_gtfs_graph() — it is never fetched
        lazily because GTFS feeds are large and require a user-supplied path.
        """
        return self.graph_manager.get_graph('transit')

    def snap_to_transit_stop(
        self,
        coord: Tuple[float, float],
        mode: str,
        max_distance_m: int = 5000,
        exclude_stop: Optional[str] = None,
    ) -> Optional[Tuple[float, float]]:
        """
        Return the (lon, lat) of the nearest transit stop for *mode*.

        Used by TripChainBuilder to anchor boarding and alighting points to
        real physical infrastructure before routing each leg.

        Priority
        --------
        1. GTFS transit graph  — platform-level accuracy, mode-filtered
        2. NaPTAN stop registry — DfT authoritative, filtered by stop type:
               tram  → TMU   (Edinburgh Trams, Metrolink, etc.)
               rail  → RLY   (National Rail stations)
               ferry → FER   (ferry terminals)
        3. None — caller falls back to waypoint interpolation

        Args:
            coord:          (lon, lat) query coordinate.
            mode:           Transport mode string from modes.py.
            max_distance_m: Search radius in metres.
            exclude_stop:   GTFS stop_id to skip (used for second-nearest snaps).

        Returns:
            (lon, lat) of the nearest stop, or None if nothing is within
            max_distance_m.
        """
        # ── Tier 1: GTFS transit graph ────────────────────────────────────────
        G_transit = self._get_transit_graph()
        if G_transit is not None:
            try:
                from simulation.gtfs.gtfs_graph import GTFSGraph
                _mode_filter = 'tram' if mode == 'tram' else mode
                stop_id = GTFSGraph(None).nearest_stop(
                    G_transit, coord,
                    mode_filter=_mode_filter,
                    max_distance_m=max_distance_m,
                    **({'exclude_stop': exclude_stop}
                       if exclude_stop is not None else {}),
                )
                if stop_id:
                    n = G_transit.nodes.get(stop_id, {})
                    x, y = n.get('x'), n.get('y')
                    if x is not None and y is not None:
                        return (float(x), float(y))
            except Exception as _exc:
                logger.debug("snap_to_transit_stop GTFS failed: %s", _exc)

        # ── Tier 2: NaPTAN stop registry ─────────────────────────────────────
        try:
            from simulation.spatial.naptan_loader import (
                nearest_naptan_stop,
                RAIL_ONLY_STOP_TYPES,   # RLY only — never MET/FER for rail
                TRAM_STOP_TYPES,        # TMU only
                FERRY_STOP_TYPES,       # FER+FBT only
            )
            naptan = getattr(self.graph_manager, 'naptan_stops', [])
            if naptan:
                if mode == 'tram':
                    stop_types: Optional[frozenset] = TRAM_STOP_TYPES
                elif mode in ('ferry_diesel', 'ferry_electric'):
                    stop_types = FERRY_STOP_TYPES
                elif mode in ('local_train', 'intercity_train', 'freight_rail'):
                    # CRITICAL: RLY only — not MET (tram) or FER (ferry)
                    # Edinburgh has 74 MET stops vs 20 RLY stops; without
                    # this filter, local_train agents snap to tram stops,
                    # then the rail trunk leg fails because the tram stop
                    # has no rail graph connection.
                    stop_types = RAIL_ONLY_STOP_TYPES
                else:
                    stop_types = None

                hit = nearest_naptan_stop(
                    coord, naptan,
                    stop_types=stop_types,
                    max_km=max_distance_m / 1000.0,
                )
                if hit is not None:
                    # Extra validation: confirm this stop actually serves the mode
                    if stop_types is None or hit.stop_type in stop_types:
                        return (hit.lon, hit.lat)
        except Exception as _exc:
            logger.debug("snap_to_transit_stop NaPTAN failed: %s", _exc)

        return None

    def _get_invalid_route(
        self,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
    ) -> List[Tuple[float, float]]:
        """Return [] to signal routing failure. Callers check ``if not route``."""
        return []

    def _transit_fallback(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str,
        policy: Dict,
    ) -> List[Tuple[float, float]]:
        """
        Fallback when GTFS is missing or routing fails.

        Trams:  route via Edinburgh tram spine (physical geometry).
        Ferries: return [] — no road proxy for water crossings.
        Buses:  fall back to drive graph.
        """
        if mode == 'tram':
            # ── Tier 1: pre-loaded OSM tram graph (environment_setup.py step 3.5) ──
            # environment_setup downloads the OSM railway=tram layer at startup and
            # registers it as graphs['tram'].  Routing on this is fast (no network
            # call), physically accurate (real track geometry), and never times out.
            # The Overpass live-fetch is kept as Tier 2 in case the graph is absent.
            #
            # ── Catchment validity guard ──────────────────────────────────────
            # The OSM tram graph covers Edinburgh tram tracks.  Agents whose
            # origin/dest are nowhere near a tram stop (e.g. Kirkliston, 7 km
            # west of the nearest tram stop) must NOT be routed on this graph:
            # doing so produces a route that snaps to the nearest tram track
            # node (anywhere on the line) and routes track→track regardless of
            # whether the agent can physically reach it.  We check both ends
            # against NaPTAN tram stops (TMU type) before routing.
            # If neither end is within _TRAM_STOP_CATCHMENT_KM of a tram stop,
            # skip to Tier 2/3.
            #
            # IMPORTANT: filter to TMU (tram/metro/underground) only.
            # Including RLY (rail station) or MET caused agents near rail stations
            # (e.g. Scotstounhill station, 4.3°W) to pass the tram catchment check
            # despite being 40+ km from the nearest actual tram stop, producing
            # nonsensical 20+ km tram routes through parts of Edinburgh the agent
            # cannot physically reach by tram.
            _TRAM_STOP_CATCHMENT_KM = 2.0   # 2 km: generous but not 7 km
            _origin_near_tram = False
            _dest_near_tram   = False
            _naptan = getattr(self.graph_manager, 'naptan_stops', [])
            # CRITICAL: Edinburgh Trams stops use NaPTAN type 'MET', not 'TMU'.
            # TMU-only filtering returned an empty list for every Edinburgh run,
            # causing the guard to fall through to the less reliable G_tram-node
            # proximity check which accepted agents 10+ km from the tram line.
            _tmu_stops = [s for s in _naptan
                          if getattr(s, 'stop_type', '') in ('TMU', 'MET')]
            if _tmu_stops:
                for _s in _tmu_stops:
                    _d_orig = haversine_km(origin, (_s.lon, _s.lat))
                    _d_dest = haversine_km(dest,   (_s.lon, _s.lat))
                    if _d_orig <= _TRAM_STOP_CATCHMENT_KM:
                        _origin_near_tram = True
                    if _d_dest <= _TRAM_STOP_CATCHMENT_KM:
                        _dest_near_tram = True
                    if _origin_near_tram and _dest_near_tram:
                        break
            else:
                # No NaPTAN TMU data — fall back to G_tram-node proximity check
                G_tram_chk = self.graph_manager.get_graph('tram')
                if G_tram_chk is not None:
                    try:
                        import osmnx as ox
                        _tn_o = ox.distance.nearest_nodes(G_tram_chk, origin[0], origin[1])
                        _tn_d = ox.distance.nearest_nodes(G_tram_chk, dest[0],   dest[1])
                        _o_xy = (float(G_tram_chk.nodes[_tn_o].get('x', 0)),
                                 float(G_tram_chk.nodes[_tn_o].get('y', 0)))
                        _d_xy = (float(G_tram_chk.nodes[_tn_d].get('x', 0)),
                                 float(G_tram_chk.nodes[_tn_d].get('y', 0)))
                        _origin_near_tram = haversine_km(origin, _o_xy) <= 2.0
                        _dest_near_tram   = haversine_km(dest,   _d_xy) <= 2.0
                    except Exception:
                        _origin_near_tram = _dest_near_tram = True  # skip guard

            if not (_origin_near_tram and _dest_near_tram):
                logger.debug(
                    "%s: tram OSM graph skipped — origin or dest not near a tram stop "
                    "(origin_near=%s, dest_near=%s) — tram not viable",
                    agent_id, _origin_near_tram, _dest_near_tram,
                )
                # Neither Overpass nor spine will help either — tram is not viable
                return []

            G_tram_local = self.graph_manager.get_graph('tram')
            if G_tram_local is not None and G_tram_local.number_of_nodes() > 1:
                try:
                    import osmnx as ox
                    tn_orig = ox.distance.nearest_nodes(G_tram_local, origin[0], origin[1])
                    tn_dest = ox.distance.nearest_nodes(G_tram_local, dest[0], dest[1])
                    if tn_orig != tn_dest:
                        orig_xy = (float(G_tram_local.nodes[tn_orig].get('x', 0)),
                                   float(G_tram_local.nodes[tn_orig].get('y', 0)))
                        dest_xy = (float(G_tram_local.nodes[tn_dest].get('x', 0)),
                                   float(G_tram_local.nodes[tn_dest].get('y', 0)))
                        # 5km catchment: same as GTFS tram_catchment
                        if (haversine_km(origin, orig_xy) <= 5.0
                                and haversine_km(dest, dest_xy) <= 5.0):
                            path_nodes = nx.shortest_path(
                                G_tram_local, tn_orig, tn_dest, weight='length'
                            )
                            tram_geom = self._interpolate(
                                self._extract_geometry(G_tram_local, path_nodes),
                                max_segment_km=0.05,
                            )
                            if tram_geom and len(tram_geom) > 2:
                                access = self._compute_access_leg(
                                    agent_id + '_access', origin, orig_xy)
                                egress = self._compute_access_leg(
                                    agent_id + '_egress', dest_xy, dest)
                                full = (
                                    (access[:-1] if access else [])
                                    + tram_geom
                                    + (egress[1:] if len(egress) > 1 else [])
                                )
                                logger.info(
                                    "✅ %s: tram OSM graph %.1fkm (%d pts) — no GTFS",
                                    agent_id, route_distance_km(full), len(full),
                                )
                                return full
                except Exception as _tram_exc:
                    logger.debug("%s: tram OSM graph routing failed: %s", agent_id, _tram_exc)

            # ── Tier 2: Overpass relation slice (cached; used when G_tram absent) ──
            # fetch_tram_relations_overpass returns a list of polylines, one per
            # tram route relation.  We cache it on graph_manager after the first
            # call so it is only downloaded once per session.
            if not hasattr(self.graph_manager, 'tram_relations'):
                logger.debug("%s: no GTFS, no tram graph — Overpass relation fetch", agent_id)
                drive = self.graph_manager.get_graph('drive')
                if drive is not None:
                    xs = [d['x'] for _, d in drive.nodes(data=True)]
                    ys = [d['y'] for _, d in drive.nodes(data=True)]
                    bbox = (max(ys), min(ys), max(xs), min(xs))
                else:
                    bbox = (56.0, 55.85, -3.05, -3.40)
                try:
                    from simulation.spatial.rail_network import fetch_tram_relations_overpass
                    setattr(self.graph_manager, 'tram_relations',
                            fetch_tram_relations_overpass(bbox))
                except Exception as _ov_exc:
                    logger.debug("Overpass tram fetch exception: %s", _ov_exc)
                    setattr(self.graph_manager, 'tram_relations', [])

            # Remove Ovrpass relation distance limit — some agents are legitimately >3 km from
            # the nearest track node but still within reach of the tram network.
            # The route slice logic will find the optimal boarding/alighting points on the nearest
            # track segment regardless of distance, and the access/egress legs will handle any long
            # walks to/from the stops.
            tram_routes = getattr(self.graph_manager, 'tram_relations', [])
            if tram_routes:
                try:
                    from shapely.geometry import Point, LineString as SLineString

                    orig_pt = Point(origin)
                    dest_pt = Point(dest)

                    best_route:  list  = []
                    best_board:  tuple = origin  # (lon, lat) of boarding point on track
                    best_alight: tuple = dest    # (lon, lat) of alighting point on track
                    best_dist        = float('inf')

                    # Sanity limit: ignore any tram route whose nearest point to the
                    # agent's origin is > 20 km away (prevents Edinburgh routes matching
                    # Glasgow agents, or any city being assigned a foreign tram network).
                    _MAX_TRAM_MATCH_KM = 20.0

                    for coords in tram_routes:
                        if len(coords) < 2:
                            continue
                        line = SLineString(coords)

                        # Shapely .distance() on WGS84 coords returns degrees.
                        # ×111.0 gives approximate km — adequate for relative ranking.
                        d1_km = line.distance(orig_pt) * 111.0
                        d2_km = line.distance(dest_pt) * 111.0

                        # Skip tram lines that are too far from the agent
                        if d1_km > _MAX_TRAM_MATCH_KM or d2_km > _MAX_TRAM_MATCH_KM:
                            continue

                        combined = d1_km + d2_km
                        if combined >= best_dist:
                            continue

                        best_dist = combined

                        proj1 = line.project(orig_pt)
                        proj2 = line.project(dest_pt)
                        p_start, p_end = min(proj1, proj2), max(proj1, proj2)

                        if p_end <= p_start:
                            # Origin and destination project to the same point — very
                            # short leg entirely within one track segment.  Use the full
                            # coord span between the two projections.
                            board  = line.interpolate(proj1)
                            alight = line.interpolate(proj2)
                            best_route  = [(board.x, board.y), (alight.x, alight.y)]
                            best_board  = (board.x, board.y)
                            best_alight = (alight.x, alight.y)
                        else:
                            # ── Primary: shapely.ops.substring ────────────────────
                            try:
                                from shapely.ops import substring
                                segment   = substring(line, p_start, p_end)
                                seg_coords = list(segment.coords)
                            except Exception as _sub_err:
                                logger.debug(
                                    "Shapely substring failed (%s) — manual slicer",
                                    _sub_err,
                                )
                                # ── Bulletproof manual coordinate slicer ──────────
                                # Walk the coordinate sequence accumulating arc length.
                                # Collect points whose arc-distance falls in [p_start, p_end].
                                # The boarding and alighting points are interpolated
                                # precisely using line.interpolate() rather than being
                                # approximated as the nearest coord vertex.
                                board_pt  = line.interpolate(p_start)
                                alight_pt = line.interpolate(p_end)
                                seg_coords = [(board_pt.x, board_pt.y)]
                                accum = 0.0
                                for i in range(len(coords) - 1):
                                    seg = SLineString([coords[i], coords[i + 1]])
                                    seg_len = seg.length
                                    next_accum = accum + seg_len
                                    # Include vertices that lie strictly inside the slice window
                                    if accum > p_start and accum < p_end:
                                        seg_coords.append(coords[i])
                                    accum = next_accum
                                seg_coords.append((alight_pt.x, alight_pt.y))

                            if not seg_coords or len(seg_coords) < 2:
                                continue

                            # ── NaPTAN stop snapping ──────────────────────────────
                            # Snap the computed boarding/alighting coordinates to the
                            # nearest NaPTAN TMU stop within 300 m.  This ensures the
                            # tram leg starts and ends at a real stop rather than an
                            # arbitrary track projection point.
                            # Explicit 2-float cast: seg_coords elements are built
                            # from Shapely coordinate extraction and typed as
                            # tuple[float, ...] by Pylance.  nearest_naptan_stop
                            # requires Tuple[float, float] — narrow here.
                            board_coord:  Tuple[float, float] = (
                                float(seg_coords[0][0]), float(seg_coords[0][1])
                            )
                            alight_coord: Tuple[float, float] = (
                                float(seg_coords[-1][0]), float(seg_coords[-1][1])
                            )
                            _naptan = getattr(self.graph_manager, 'naptan_stops', [])
                            # Include MET — Edinburgh Trams uses MET, not TMU
                            _tmu = [s for s in _naptan
                                    if getattr(s, 'stop_type', '') in ('TMU', 'MET')]
                            if _tmu:
                                try:
                                    from simulation.spatial.naptan_loader import nearest_naptan_stop
                                    _hit_b = nearest_naptan_stop(
                                        board_coord, _tmu,
                                        stop_types=frozenset({'TMU', 'MET'}),
                                        max_km=0.30,
                                    )
                                    if _hit_b:
                                        board_coord = (_hit_b.lon, _hit_b.lat)
                                        seg_coords[0] = board_coord
                                    _hit_a = nearest_naptan_stop(
                                        alight_coord, _tmu,
                                        stop_types=frozenset({'TMU', 'MET'}),
                                        max_km=0.30,
                                    )
                                    if _hit_a:
                                        alight_coord = (_hit_a.lon, _hit_a.lat)
                                        seg_coords[-1] = alight_coord
                                except Exception:
                                    pass

                            # Reverse track direction if agent travels in opposite direction
                            if proj1 > proj2:
                                seg_coords.reverse()

                            best_route  = seg_coords
                            best_board  = tuple(seg_coords[0])
                            best_alight = tuple(seg_coords[-1])

                    if best_route and len(best_route) > 1:
                        # Access leg: origin → boarding stop (walk or drive graph)
                        access = self._compute_access_leg(
                            agent_id + '_access', origin,
                            cast(Tuple[float, float], best_board),
                        )
                        # Egress leg: alighting stop → destination (walk or drive graph)
                        egress = self._compute_access_leg(
                            agent_id + '_egress',
                            cast(Tuple[float, float], best_alight), dest,
                        )

                        route_typed: List[Tuple[float, float]] = [
                            cast(Tuple[float, float], pt) for pt in best_route
                        ]
                        # Stitch: access (drop last pt to avoid dup) + tram track + egress (drop first pt)
                        full = (
                            (access[:-1] if access else [])
                            + route_typed
                            + (egress[1:] if len(egress) > 1 else [])
                        )
                        logger.info(
                            "✅ %s: tram Overpass relation %.1fkm (%d pts on track)",
                            agent_id, route_distance_km(full), len(best_route),
                        )
                        return full

                except Exception as _ov2_exc:
                    logger.debug(
                        "%s: Overpass tram slice failed: %s", agent_id, _ov2_exc
                    )

            # ── Tier 3: tram spine ────────────────────────────────────────────────
            logger.debug("%s: no GTFS/tram-graph/relations — tram spine fallback", agent_id)
            try:
                from simulation.spatial.rail_spine import route_via_tram_stops
                spine_route = route_via_tram_stops(origin, dest, max_access_km=5.0)
                if spine_route and len(spine_route) > 2:
                    return spine_route
            except Exception:
                pass
            return []
        # ───────────────────────────────────────────────────────────────────
        if mode in ('ferry_diesel', 'ferry_electric'):
            # Provide a visible great-circle line — never silent [] for ferry.
            logger.debug("%s: ferry — no GTFS/graph, using great-circle interpolation", agent_id)
            return self._interpolate([origin, dest], max_segment_km=0.2)
        return self._compute_road_route(agent_id, origin, dest, mode, policy)

    def _compute_ferry_route(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str,
        policy: Dict,
    ) -> List[Tuple[float, float]]:
        """
        Three-tier ferry route.

        1. GTFS transit graph (if loaded and contains ferry service edges).
        2. Ferry graph from Overpass API / hardcoded UK spine.
        3. Great-circle interpolation — always produces a visible line.

        Ferry routes are NEVER returned as [] — the great-circle fallback
        ensures ferry agents are always visible on the map even when no
        GTFS or graph data is available.
        """
        # ── Tier 1: GTFS transit graph ────────────────────────────────────────
        G_transit = self._get_transit_graph()
        if G_transit is not None:
            try:
                gtfs_route = self._compute_gtfs_route(agent_id, origin, dest, mode, policy)
                if gtfs_route and len(gtfs_route) >= 2:
                    return gtfs_route
            except Exception:
                pass

        # ── Tier 2: Ferry graph (Overpass or hardcoded spine) ─────────────────
        G_ferry = self.graph_manager.get_graph('ferry')
        if G_ferry is not None and G_ferry.number_of_nodes() > 1:
            try:
                import osmnx as ox
                orig_node = ox.distance.nearest_nodes(G_ferry, origin[0], origin[1])
                dest_node = ox.distance.nearest_nodes(G_ferry, dest[0],   dest[1])
                if orig_node != dest_node:
                    path_nodes = nx.shortest_path(G_ferry, orig_node, dest_node, weight='length')
                    coords: List[Tuple[float, float]] = []
                    for i in range(len(path_nodes) - 1):
                        u, v    = path_nodes[i], path_nodes[i + 1]
                        edge_map = G_ferry.get_edge_data(u, v) or {}
                        best_shape: list = []
                        for ed in edge_map.values():
                            s = ed.get('shape_coords') or []
                            if len(s) > len(best_shape):
                                best_shape = s
                        if best_shape:
                            coords.extend(best_shape if i == 0 else best_shape[1:])
                        else:
                            ux = float(G_ferry.nodes[u].get('x', 0))
                            uy = float(G_ferry.nodes[u].get('y', 0))
                            vx = float(G_ferry.nodes[v].get('x', 0))
                            vy = float(G_ferry.nodes[v].get('y', 0))
                            if i == 0:
                                coords.append((ux, uy))
                            coords.append((vx, vy))

                    # Access leg: origin → nearest terminal (walk graph or straight line)
                    orig_pos = (float(G_ferry.nodes[orig_node].get('x', origin[0])),
                                float(G_ferry.nodes[orig_node].get('y', origin[1])))
                    dest_pos = (float(G_ferry.nodes[dest_node].get('x', dest[0])),
                                float(G_ferry.nodes[dest_node].get('y', dest[1])))
                    access_leg = self._compute_access_leg(agent_id + '_access', origin, orig_pos)
                    egress_leg = self._compute_access_leg(agent_id + '_egress', dest_pos, dest)

                    coords = self._interpolate(coords, max_segment_km=0.2)
                    full: List[Tuple[float, float]] = (
                        (access_leg[:-1] if access_leg else [])
                        + coords
                        + (egress_leg[1:] if len(egress_leg) > 1 else [])
                    )
                    if len(full) >= 2:
                        logger.info(
                            "✅ %s: ferry graph %.1fkm (%d pts)",
                            agent_id, route_distance_km(full), len(full),
                        )
                        return full
            except nx.NetworkXNoPath:
                logger.debug("%s: no ferry graph path — great-circle fallback", agent_id)
            except Exception as exc:
                logger.debug("%s: ferry graph routing failed (%s) — great-circle fallback", agent_id, exc)

        # ── Tier 3: Great-circle interpolation ───────────────────────────────
        logger.debug("%s: ferry great-circle fallback (%.1fkm)", agent_id, haversine_km(origin, dest))
        return self._interpolate([origin, dest], max_segment_km=0.2)

    def _compute_access_leg(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        max_straight_km: float = 3.0,
        snap_to_naptan: bool = False,
        naptan_stop_types: Optional[frozenset] = None,
    ) -> List[Tuple[float, float]]:
        """
        Compute a pedestrian access or egress leg to/from a transit stop.

        Four-tier strategy (tried in order):
        ──────────────────────────────────────────────────────────────────
        Tier 0 — NaPTAN stop snapping (when snap_to_naptan=True)
            Adjust dest (or origin for egress) to the exact NaPTAN platform
            coordinate before routing.  This prevents the leg terminating at
            a random mid-track point and ensures boarding at a real stop.

        Tier 1 — Walk graph (distance ≤ max_straight_km)
            OSMnx walk graph; weight='length'.  Guaranteed to follow paths,
            pavements, and bridges — never cuts through buildings or waterways.
            Short legs (< 150 m) bypass the graph and use a straight line.

        Tier 2 — Drive proxy (distance > _WALK_ACCESS_KM or walk graph fails)
            The car graph covers all roads pedestrians can also use and always
            has full connectivity.  This is the correct fallback for legs of
            1.2–3+ km where walk routing would be slow or disconnected.

        Tier 3 — Interpolated straight line (absolute last resort)
            Only used when BOTH the walk graph and drive proxy fail
            (e.g. origin or dest outside the loaded graph bbox).
            This is the path that was producing canal routes and routes
            through buildings — it should now be very rare.

        Design notes
        ────────────
        • Canal towpath routes: the walk graph correctly includes the Union
          Canal towpath as a valid pedestrian path.  When the tram boarding
          point is on the south bank of the canal, the walk graph will use
          the nearest bridge.  If the walk graph is absent or Tier 1 fails,
          Tier 2 (drive graph) is used — the drive graph does NOT include
          canal towpaths, so it routes via road bridges only.

        • The old "PATCH 1" guard (`if dist_km > 1.2km: drive proxy; return`)
          was skipping the walk graph entirely for all legs > 1.2 km.  This
          produced drive-quality routes for pedestrian legs — motorway-class
          roads appeared in access legs.  The revised logic tries the walk
          graph first regardless of distance, falls to drive only on failure.
        """
        dist_km = haversine_km(origin, dest)

        # ── Tier 0: NaPTAN stop snapping ─────────────────────────────────────
        # When routing an access leg TO a transit stop (snap_to_naptan=True),
        # adjust dest to the authoritative DfT NaPTAN platform coordinate.
        # This prevents the leg terminating at an arbitrary mid-track point.
        if snap_to_naptan and naptan_stop_types is not None:
            naptan_stops = getattr(self.graph_manager, 'naptan_stops', [])
            if naptan_stops:
                try:
                    from simulation.spatial.naptan_loader import (
                        nearest_naptan_stop, RAIL_STOP_TYPES,
                    )
                    hit = nearest_naptan_stop(
                        dest, naptan_stops,
                        stop_types=naptan_stop_types,
                        max_km=0.5,
                    )
                    if hit is not None:
                        dest = (hit.lon, hit.lat)
                        dist_km = haversine_km(origin, dest)
                except Exception:
                    pass

        # Very short legs: straight line is always correct
        if dist_km < 0.15:
            return self._interpolate([origin, dest], max_segment_km=0.05)

        # ── Tier 1: Walk graph ────────────────────────────────────────────────
        G_walk = self.graph_manager.get_graph('walk')
        if G_walk is not None and G_walk.number_of_nodes() > 10:
            try:
                orig_node = self.graph_manager.get_nearest_node(origin, 'walk')
                dest_node = self.graph_manager.get_nearest_node(dest,   'walk')
                orig_node = self._avoid_roundabout(G_walk, orig_node)
                dest_node = self._avoid_roundabout(G_walk, dest_node)

                # Same-node snap correction: when both ends snap to the same
                # walk node (graph boundary edge case), find the next-nearest
                # node for dest rather than returning a degenerate 0-length leg.
                if (orig_node is not None and dest_node is not None
                        and orig_node == dest_node and dist_km > 0.05):
                    dest_lon, dest_lat = dest
                    best_alt: Any     = None
                    best_alt_d: float = float('inf')
                    for n, nd in G_walk.nodes(data=True):
                        if n == orig_node:
                            continue
                        d = haversine_km(
                            (dest_lon, dest_lat),
                            (float(nd.get('x', 0)), float(nd.get('y', 0))),
                        )
                        if d < best_alt_d:
                            best_alt_d = d
                            best_alt   = n
                    if best_alt is not None:
                        dest_node = best_alt

                if orig_node and dest_node and orig_node != dest_node:
                    walk_nodes = nx.shortest_path(
                        G_walk, orig_node, dest_node, weight='length'
                    )
                    coords = self._extract_geometry(G_walk, walk_nodes)
                    if coords and len(coords) >= 2:
                        return self._interpolate(coords, max_segment_km=0.05)

            except nx.NetworkXNoPath:
                pass   # fall through to Tier 2
            except Exception as _walk_exc:
                logger.debug(
                    "%s: walk routing failed (%.2fkm): %s — drive proxy",
                    agent_id, dist_km, _walk_exc,
                )

        # ── Tier 2: Drive proxy ───────────────────────────────────────────────
        # The drive graph covers all bridges and city streets that pedestrians
        # also use.  It never routes through canals or buildings.
        _drive = self._compute_road_route(agent_id, origin, dest, 'car', _DEFAULT_POLICY)
        if _drive and len(_drive) > 2:
            logger.debug(
                "%s: access→drive proxy: %d pts (%.2fkm)",
                agent_id, len(_drive), dist_km,
            )
            return _drive

        # ── Tier 3: Interpolated straight line (absolute last resort) ─────────
        logger.debug(
            "%s: walk+drive both failed (%.2fkm) — straight line",
            agent_id, dist_km,
        )
        return self._interpolate([origin, dest], max_segment_km=0.05)

    def _compute_gtfs_route(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str,
        policy: Dict,
    ) -> List[Tuple[float, float]]:
        """
        Four-leg GTFS transit route.

        Legs: access walk → board → ride (headway-weighted) → alight → egress walk.

        Generalised cost per transit edge:
            gen_cost = (travel_time_h + headway_h/2) × VoT
                     + dist_km × energy_price
                     + dist_km × emit_kg_km × carbon_tax

        headway_h/2 is E[wait] for uniform arrivals — this makes frequent
        Edinburgh trams competitive vs infrequent rural buses in the BDI
        cost model.

        Tram BODS encoding
        ------------------
        BODS may encode Edinburgh Trams as route_type=0 ('tram') or as
        route_type=3 ('local_train').  We try both and use the first that
        returns a valid stop pair with origin ≠ destination.

        Mode masking
        ------------
        gen_cost=inf is set on wrong-family edges so shortest_path cannot
        route a tram trip via cheaper bus edges or vice versa.

        Shape geometry
        --------------
        GTFS shape_coords are the ground-truth polyline from shapes.txt.
        We select the edge with the longest (most detailed) shape when
        multiple parallel edges exist for the same stop pair.
        Bus edges without shape fall back to the drive graph for that segment.
        Tram/ferry edges without shape fall back to straight interpolation.
        """
        G_transit = self._get_transit_graph()

        if G_transit is None:
            if mode == 'tram':
                logger.debug("%s: no GTFS — tram spine fallback", agent_id)
                try:
                    from simulation.spatial.rail_spine import route_via_tram_stops
                    # Use a wider catchment (5.0 km) when no GTFS is loaded.
                    # The default 2.5 km is too tight for Edinburgh: random OD
                    # pairs commonly have their nearest tram stop 3–5 km away
                    # (e.g. Colinton → Murrayfield is ~3.8 km).  5 km matches
                    # the GTFS tram_catchment used when GTFS IS loaded.
                    spine_route = route_via_tram_stops(origin, dest, max_access_km=5.0)
                    if spine_route and len(spine_route) > 2:
                        logger.debug(
                            "%s: tram spine → %d waypoints, road-following each leg",
                            agent_id, len(spine_route),
                        )
                        realistic: List[Tuple[float, float]] = []
                        for i in range(len(spine_route) - 1):
                            leg = self._compute_road_route(
                                agent_id, spine_route[i], spine_route[i + 1], 'car', policy,
                            )
                            if leg and len(leg) > 1:
                                realistic.extend(leg[:-1])
                            else:
                                realistic.append(spine_route[i])
                        realistic.append(spine_route[-1])
                        return realistic
                    # spine_route is None or 2-point → outside catchment
                    logger.debug(
                        "%s: tram spine returned %s — origin/dest outside 5km tram catchment",
                        agent_id, "None" if spine_route is None else f"{len(spine_route)} pts",
                    )
                    return []
                except Exception as _exc:
                    logger.debug("%s: tram spine exception: %s", agent_id, _exc)
                    return []
            return self._transit_fallback(agent_id, origin, dest, mode, policy)

        try:
            from simulation.gtfs.gtfs_graph import GTFSGraph
        except ImportError:
            return self._transit_fallback(agent_id, origin, dest, mode, policy)

        builder = GTFSGraph(None)

        # ── Stop snapping ─────────────────────────────────────────────────────
        if mode == 'tram':
            _tram_filters   = ['tram', 'local_train']
            _tram_catchment = 5000   # 5 km — tram stops can be far apart
            origin_stop = dest_stop = None
            for mf in _tram_filters:
                origin_stop = builder.nearest_stop(
                    G_transit, origin, mode_filter=mf, max_distance_m=_tram_catchment,
                )
                dest_stop = builder.nearest_stop(
                    G_transit, dest, mode_filter=mf, max_distance_m=_tram_catchment,
                )
                if origin_stop and dest_stop and origin_stop != dest_stop:
                    logger.debug(
                        "%s: tram stop snap via mode_filter=%s (%s→%s)",
                        agent_id, mf, origin_stop, dest_stop,
                    )
                    break
        else:
            origin_stop = builder.nearest_stop(
                G_transit, origin, mode_filter=mode, max_distance_m=2000
            )
            dest_stop = builder.nearest_stop(
                G_transit, dest, mode_filter=mode, max_distance_m=2000
            )

        if not origin_stop or not dest_stop or origin_stop == dest_stop:
            # ── Same-stop snap: find second-nearest stop for dest ─────────────
            if origin_stop and dest_stop and origin_stop == dest_stop:
                try:
                    _builder_r = GTFSGraph(None)
                    _filters_r = ['tram', 'local_train'] if mode == 'tram' else [mode]
                    _max_r = _tram_catchment if mode == 'tram' else 2000
                    for _mf_r in _filters_r:
                        _cand_r = None
                        try:
                            _excl_kwargs_r: Dict[str, Any] = {'exclude_stop': origin_stop}
                            _cand_r = _builder_r.nearest_stop(
                                G_transit, dest,
                                mode_filter=_mf_r,
                                max_distance_m=_max_r,
                                **_excl_kwargs_r,
                            )
                        except TypeError:
                            _best_r = float('inf')
                            for _nr, _ndr in G_transit.nodes(data=True):
                                if _nr == origin_stop:
                                    continue
                                _dr = haversine_km(
                                    dest,
                                    (float(_ndr.get('x', 0)),
                                     float(_ndr.get('y', 0))),
                                )
                                if _dr < _best_r and _dr <= _max_r / 1000.0:
                                    _best_r = _dr
                                    _cand_r = _nr
                        if _cand_r and _cand_r != origin_stop:
                            dest_stop = _cand_r
                            logger.debug(
                                "%s: GTFS same-stop resolved — dest_stop %s",
                                agent_id, dest_stop,
                            )
                            break
                except Exception as _sr_exc:
                    logger.debug("%s: GTFS same-stop retry failed: %s", agent_id, _sr_exc)

            if not origin_stop or not dest_stop or origin_stop == dest_stop:
                logger.debug("%s: no GTFS stop pair for %s", agent_id, mode)
                return self._transit_fallback(agent_id, origin, dest, mode, policy)

        # ── Mode masking ──────────────────────────────────────────────────────
        _TRAM_MODES = frozenset({'tram', 'local_train'})
        _RAIL_MODES = frozenset({'local_train', 'intercity_train', 'rail', 'freight_rail'})
        _BUS_MODES  = frozenset({'bus'})
        if mode == 'tram':
            _allowed = _TRAM_MODES
        elif mode in ('local_train', 'intercity_train'):
            _allowed = _RAIL_MODES
        elif mode == 'bus':
            _allowed = _BUS_MODES
        else:
            _allowed = frozenset({mode})

        # ── Headway-weighted generalised cost ─────────────────────────────────
        vot     = float(policy.get('value_of_time_gbp_h',  10.0))
        e_price = float(policy.get('energy_price_gbp_km',   0.12))
        c_tax   = float(policy.get('carbon_tax_gbp_tco2',   0.0))

        for u, v, key, data in G_transit.edges(keys=True, data=True):
            edge_mode = data.get('mode', 'bus')
            if edge_mode == 'walk' or data.get('highway') == 'transfer':
                data['gen_cost'] = 9999.0
                continue
            if edge_mode not in _allowed:
                data['gen_cost'] = float('inf')
                continue
            travel_h  = data.get('travel_time_s', 300) / 3600.0
            headway_h = data.get('headway_s', 1800) / 3600.0 / 2.0
            dist_km   = data.get('length', 0) / 1000.0
            emit_kg   = data.get('emissions_g_km', 100.0) / 1000.0
            data['gen_cost'] = (
                (travel_h + headway_h) * vot
                + dist_km * e_price
                + dist_km * emit_kg * c_tax
            )

        # ── Route on transit graph ─────────────────────────────────────────────
        try:
            transit_nodes = nx.shortest_path(
                G_transit, origin_stop, dest_stop, weight='gen_cost'
            )
        except Exception:
            logger.debug(
                "%s: no GTFS path %s→%s — fallback", agent_id, origin_stop, dest_stop,
            )
            return self._compute_road_route(agent_id, origin, dest, mode, policy)

        # ── Extract geometry from shape_coords ────────────────────────────────
        # For each consecutive stop pair, prefer the parallel edge whose
        # shape_coords is longest (most detailed).  This avoids taking a
        # dead-run edge (empty shape) over a revenue service edge.
        transit_coords: List[Tuple[float, float]] = []
        for i in range(len(transit_nodes) - 1):
            u_node   = transit_nodes[i]
            v_node   = transit_nodes[i + 1]
            edge_map = G_transit.get_edge_data(u_node, v_node) or {}

            # Select edge with longest shape_coords, falling back to first edge.
            shape: List[Tuple[float, float]] = []
            if edge_map:
                for ed in edge_map.values():
                    s = ed.get('shape_coords') or []
                    if len(s) > len(shape):
                        shape = s

            u_x = float(G_transit.nodes[u_node].get('x', 0))
            u_y = float(G_transit.nodes[u_node].get('y', 0))
            v_x = float(G_transit.nodes[v_node].get('x', 0))
            v_y = float(G_transit.nodes[v_node].get('y', 0))

            if shape and len(shape) > 2:
                transit_coords.extend(shape if i == 0 else shape[1:])
            elif mode in ('bus', 'van_electric', 'van_diesel'):
                # Bus: road proxy for missing shape segments.
                leg = self._compute_road_route(
                    agent_id, (u_x, u_y), (v_x, v_y), 'car', policy
                )
                if leg and len(leg) > 1:
                    transit_coords.extend(leg if i == 0 else leg[1:])
                else:
                    if i == 0:
                        transit_coords.append((u_x, u_y))
                    transit_coords.append((v_x, v_y))
            else:
                # ── FIX Bug 3: tram OSM track geometry fallback ───────────────
                # Edinburgh Tram GTFS from BODS has no shapes.txt entries, so
                # shape_coords is always empty for tram trips.  Before falling
                # back to a straight line between stops, try to route on the
                # OSM tram graph (registered as graphs['tram'] by
                # environment_setup.py).  This follows actual track geometry
                # through Princes Street / Shandwick Place / the airport spur
                # instead of diagonal lines through buildings.
                _tram_seg_added = False
                if mode == 'tram':
                    G_tram = self.graph_manager.get_graph('tram')
                    if G_tram is not None and G_tram.number_of_nodes() > 1:
                        try:
                            import osmnx as ox
                            tn_orig = ox.distance.nearest_nodes(G_tram, u_x, u_y)
                            tn_dest = ox.distance.nearest_nodes(G_tram, v_x, v_y)
                            if tn_orig != tn_dest:
                                tram_path = nx.shortest_path(
                                    G_tram, tn_orig, tn_dest, weight='length'
                                )
                                tram_seg = self._interpolate(
                                    self._extract_geometry(G_tram, tram_path),
                                    max_segment_km=0.05,
                                )
                                if tram_seg and len(tram_seg) > 1:
                                    transit_coords.extend(
                                        tram_seg if i == 0 else tram_seg[1:]
                                    )
                                    _tram_seg_added = True
                                    logger.debug(
                                        "%s: tram OSM track geometry: %d pts "
                                        "between stops %s→%s",
                                        agent_id, len(tram_seg), u_node, v_node,
                                    )
                        except Exception as _tram_exc:
                            logger.debug(
                                "%s: tram OSM segment %d failed: %s",
                                agent_id, i, _tram_exc,
                            )
                if not _tram_seg_added:
                    # Ferry / tram (no OSM graph): straight stop-to-stop line.
                    if i == 0:
                        transit_coords.append((u_x, u_y))
                    transit_coords.append((v_x, v_y))

        if not transit_coords:
            return self._transit_fallback(agent_id, origin, dest, mode, policy)

        # ── Access leg ────────────────────────────────────────────────────────
        first_d     = G_transit.nodes.get(origin_stop, {})
        first_coord = (float(first_d.get('x', origin[0])), float(first_d.get('y', origin[1])))
        access_leg  = self._compute_access_leg(agent_id + '_access', origin, first_coord)

        # ── Egress leg ────────────────────────────────────────────────────────
        last_d     = G_transit.nodes.get(dest_stop, {})
        last_coord = (float(last_d.get('x', dest[0])), float(last_d.get('y', dest[1])))
        egress_leg = self._compute_access_leg(agent_id + '_egress', last_coord, dest)

        # ── Stitch ────────────────────────────────────────────────────────────
        full_route: List[Tuple[float, float]] = (
            (access_leg[:-1] if access_leg else [])
            + transit_coords
            + (egress_leg[1:] if len(egress_leg) > 1 else [])
        )

        if len(full_route) < 2:
            full_route = [origin, dest]

        logger.info(
            "✅ %s: GTFS %s %.1fkm (%d stops, %d pts)",
            agent_id, mode, route_distance_km(full_route),
            len(transit_nodes), len(full_route),
        )
        return full_route

    # =========================================================================
    # GENERALISED COST EDGE WEIGHTS
    # =========================================================================

    def _apply_generalised_weights(
        self,
        graph: Any,
        mode: str,
        policy: Dict,
    ) -> str:
        """
        Write 'gen_cost' to every edge:

            cost = (time_h × VoT)
                 + (dist_km × energy_price)
                 + (dist_km × emit_kg_km × carbon_tax)

        For rail graphs, infrastructure filtering overwrites gen_cost with
        inf for edges of the wrong track type (trams blocked from mainline
        rail; heavy rail blocked from tram/light_rail).  The base cost is
        always written unconditionally first — no dangling variable reference.

        Returns edge attribute name for nx.shortest_path weight=.
        """
        vot        = float(policy.get('value_of_time_gbp_h',  10.0))
        e_price    = float(policy.get('energy_price_gbp_km',   0.12))
        c_tax      = float(policy.get('carbon_tax_gbp_tco2',   0.0))
        speed_km_h = self.speeds_km_min.get(mode, 0.5) * 60.0
        emit_kg_km = _EMISSIONS_G_KM.get(mode, 100) / 1000.0

        is_rail_graph = graph.graph.get('name') == 'rail'

        for u, v, key, data in graph.edges(keys=True, data=True):
            dist_km = data.get('length', 0.0) / 1000.0
            cong    = 1.0
            if self.congestion_manager is not None:
                try:
                    cong = self.congestion_manager.get_congestion_factor(u, v, key)
                except Exception:
                    pass
            time_h = (dist_km / max(speed_km_h, 0.1)) * cong

            # Base cost — always written before any override.
            data['gen_cost'] = (
                time_h   * vot
                + dist_km * e_price
                + dist_km * emit_kg_km * c_tax
            )

            # Track-type filter for rail graph only.
            if is_rail_graph:
                rw = data.get('railway', '')
                if isinstance(rw, list):
                    rw = rw[0] if rw else ''
                if mode == 'tram' and rw not in ('tram', 'light_rail', 'subway'):
                    data['gen_cost'] = float('inf')
                elif (mode in ('local_train', 'intercity_train', 'freight_rail')
                      and rw in ('tram', 'light_rail')):
                    data['gen_cost'] = float('inf')

        return 'gen_cost'

    # =========================================================================
    # GEOMETRY EXTRACTION & INTERPOLATION
    # =========================================================================

    def _extract_geometry(
        self,
        graph: Any,
        route_nodes: List,
    ) -> List[Tuple[float, float]]:
        """
        Extract (lon, lat) 2-tuples from an ordered node list.

        Prefers edges with Shapely LineString geometry (OSMnx curved roads).
        When multiple parallel edges exist, picks the one with geometry over
        one without.  Falls back to straight node-to-node lines.
        """
        coords: List[Tuple[float, float]] = []

        for i in range(len(route_nodes) - 1):
            u, v = route_nodes[i], route_nodes[i + 1]

            if i == 0:
                coords.append(
                    (float(graph.nodes[u]['x']), float(graph.nodes[u]['y']))
                )

            edge_dict = graph.get_edge_data(u, v) or {}
            edge_data = (
                next((d for d in edge_dict.values() if 'geometry' in d), None)
                or next(iter(edge_dict.values()), None)
            )

            if edge_data and 'geometry' in edge_data:
                geom = edge_data['geometry']
                if hasattr(geom, 'coords'):
                    coords.extend(
                        (float(x), float(y)) for x, y in list(geom.coords)[1:]
                    )
                else:
                    coords.append(
                        (float(graph.nodes[v]['x']), float(graph.nodes[v]['y']))
                    )
            else:
                coords.append(
                    (float(graph.nodes[v]['x']), float(graph.nodes[v]['y']))
                )

        if not coords and len(route_nodes) >= 2:
            first, last = route_nodes[0], route_nodes[-1]
            coords = [
                (float(graph.nodes[first]['x']), float(graph.nodes[first]['y'])),
                (float(graph.nodes[last]['x']),  float(graph.nodes[last]['y'])),
            ]
        return coords

    def _interpolate(
        self,
        coords: List[Tuple[float, float]],
        max_segment_km: float = 0.05,
    ) -> List[Tuple[float, float]]:
        """
        Insert intermediate points so no segment exceeds max_segment_km.

        Serves two purposes:
          • Smooth animation — agents move on curves, not between distant nodes.
          • Accurate position tracking — per-step distance arithmetic is stable.
        """
        if len(coords) < 2:
            return coords
        out = [coords[0]]
        for i in range(len(coords) - 1):
            p1, p2 = coords[i], coords[i + 1]
            dist   = haversine_km(p1, p2)
            if dist > max_segment_km:
                steps = max(1, int(dist / max_segment_km))
                for j in range(1, steps):
                    t = j / steps
                    out.append((
                        p1[0] + t * (p2[0] - p1[0]),
                        p1[1] + t * (p2[1] - p1[1]),
                    ))
            out.append(p2)
        return out

    # =========================================================================
    # ROUTE VARIANTS
    # =========================================================================

    def _compute_route_variant(
        self,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str,
        variant: str,
        agent_id: str = 'unknown',
        policy: Optional[Dict] = None,
    ) -> List[Tuple[float, float]]:
        """
        Compute a named route variant.

        Variants: generalised / shortest, fastest, safest, greenest,
                  cheapest, decarbonisation, scenic.
        """
        if not (is_valid_lonlat(origin) and is_valid_lonlat(dest)):
            return []
        policy = policy or dict(_DEFAULT_POLICY)

        if mode in _RAIL_MODES:
            return self._compute_intermodal_route(agent_id, origin, dest, mode, policy)

        network_type = self.mode_network_types.get(mode, 'drive')
        graph        = self.graph_manager.get_graph(network_type)
        if graph is None:
            return []

        try:
            orig_node = self.graph_manager.get_nearest_node(origin, network_type)
            dest_node = self.graph_manager.get_nearest_node(dest,   network_type)
            # Roundabout avoidance — same fix as _compute_road_route
            orig_node = self._avoid_roundabout(graph, orig_node)
            dest_node = self._avoid_roundabout(graph, dest_node)
            if orig_node is None or dest_node is None:
                return []

            weight_key = {
                'generalised':     lambda: self._apply_generalised_weights(graph, mode, policy),
                'shortest':        lambda: self._apply_generalised_weights(graph, mode, policy),
                'fastest':         lambda: self._add_time_weights(graph, mode),
                'safest':          lambda: self._add_safety_weights(graph, mode),
                'greenest':        lambda: self._add_emission_weights(graph, mode),
                'cheapest':        lambda: self._add_monetary_weights(graph, mode, policy),
                'decarbonisation': lambda: self._add_decarbonisation_weights(graph, mode, policy),
                'scenic':          lambda: self._add_scenic_weights(graph, mode),
            }.get(variant, lambda: 'length')()

            route_nodes = nx.shortest_path(graph, orig_node, dest_node, weight=weight_key)
            return self._interpolate(
                self._extract_geometry(graph, route_nodes), max_segment_km=0.05,
            )

        except nx.NetworkXNoPath:
            return []
        except Exception as exc:
            logger.warning("%s: variant %s failed: %s", agent_id, variant, exc)
            return []

    # =========================================================================
    # RAIL KINEMATICS — HEADING REVERSAL GUARD
    # =========================================================================

    @staticmethod
    def _bearing_between(
        graph: Any,
        u: Any,
        v: Any,
    ) -> float:
        """
        Compass bearing (degrees, 0-360) from node u to node v.

        Uses the forward azimuth formula on the WGS-84 spheroid.
        All node coordinates are (lon, lat) as stored by OSMnx.
        """
        import math
        ux = float(graph.nodes[u].get('x', 0))
        uy = float(graph.nodes[u].get('y', 0))
        vx = float(graph.nodes[v].get('x', 0))
        vy = float(graph.nodes[v].get('y', 0))
        lat1 = math.radians(uy)
        lat2 = math.radians(vy)
        dlon = math.radians(vx - ux)
        y = math.sin(dlon) * math.cos(lat2)
        x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
        return (math.degrees(math.atan2(y, x)) + 360) % 360

    def _has_heading_reversal(
        self,
        graph: Any,
        node_list: List,
        threshold_deg: float = 150.0,
    ) -> bool:
        """
        Return True if any consecutive triple of nodes forms an acute switchback.

        Computes the minimum angular difference between successive bearings so
        that both clockwise and counter-clockwise reversals are caught equally.
        The previous `abs(b2-b1)` approach was subtly asymmetric when combined
        with the `if diff > 180: diff = 360-diff` fold-down, because floating
        point bearing values near 0°/360° could produce slightly different
        diffs depending on direction.  The correct formula is:

            diff = |((b2 - b1 + 180) % 360) - 180|

        This maps any signed circular difference to [0, 180] symmetrically,
        making CW and CCW reversals equivalent.

        The loop runs range(check_up_to) — not range(check_up_to - 1).
        The previous off-by-one skipped the last interior triple on every path,
        missing reversals at the penultimate junction node.

        Args:
            graph:         Rail NetworkX graph (nodes must have 'x', 'y' attrs).
            node_list:     Ordered nodes from nx.shortest_path.
            threshold_deg: Bearing-change above which a reversal is called.
                           150° (tighter than the previous 160°) to catch the
                           Craiglockhart junction (Δ≈161°) and similar cases.

        Returns:
            True if at least one bearing reversal is found mid-route.
        """
        if len(node_list) < 3:
            return False
        # Exclude the LAST node only — terminus direction-change is legitimate
        check_up_to = len(node_list) - 2   # last i for triple (i, i+1, i+2)
        for i in range(check_up_to):       # was range(check_up_to - 1): off-by-one
            b1 = self._bearing_between(graph, node_list[i],     node_list[i + 1])
            b2 = self._bearing_between(graph, node_list[i + 1], node_list[i + 2])
            # Symmetric minimum circular difference — handles CW and CCW equally
            diff = abs(((b2 - b1 + 180.0) % 360.0) - 180.0)
            if diff > threshold_deg:
                logger.warning(
                    "Heading reversal detected at rail node %s "
                    "(bearing %.0f° → %.0f°, Δ=%.0f°) — kinematic constraint "
                    "violation; rejecting route",
                    node_list[i + 1], b1, b2, diff,
                )
                return True
        return False

    def _find_reversal_node(
        self,
        graph: Any,
        node_list: List,
        threshold_deg: float = 150.0,
    ) -> Optional[Any]:
        """
        Return the junction node (mid-point) of the first heading reversal.

        Uses the same symmetric circular-difference formula as _has_heading_reversal
        and the corrected range so it finds the same reversal node that the guard
        detected.

        Returns None if the list is too short to contain a mid-path reversal.
        """
        if len(node_list) < 3:
            return None
        check_up_to = len(node_list) - 2
        for i in range(check_up_to):
            b1 = self._bearing_between(graph, node_list[i],     node_list[i + 1])
            b2 = self._bearing_between(graph, node_list[i + 1], node_list[i + 2])
            diff = abs(((b2 - b1 + 180.0) % 360.0) - 180.0)
            if diff > threshold_deg:
                return node_list[i + 1]
        return None

    # =========================================================================
    # WEIGHT HELPERS
    # =========================================================================

    def _add_time_weights(self, graph: Any, mode: str) -> str:
        """Minimise travel time only."""
        speed_m_min = self.speeds_km_min.get(mode, 0.5) * 1000
        for u, v, key, data in graph.edges(keys=True, data=True):
            base = data.get('length', 0) / max(speed_m_min, 1.0)
            if self.congestion_manager is not None:
                try:
                    base *= self.congestion_manager.get_congestion_factor(u, v, key)
                except Exception:
                    pass
            data['time_weight'] = base
        return 'time_weight'

    def _add_safety_weights(self, graph: Any, mode: str) -> str:
        """Minimise risk for active / vulnerable road users."""
        _RISK = {
            'motorway': 100, 'motorway_link': 100,
            'trunk': 50, 'trunk_link': 50,
            'primary': 5, 'primary_link': 5,
            'secondary': 2, 'secondary_link': 2,
            'residential': 0.8, 'living_street': 0.8,
            'cycleway': 0.7, 'path': 0.7, 'footway': 0.7,
        }
        active = {'walk', 'bike', 'cargo_bike', 'e_scooter'}
        for _u, _v, _k, data in graph.edges(keys=True, data=True):
            hw = data.get('highway', 'residential')
            if isinstance(hw, list):
                hw = hw[0] if hw else 'residential'
            risk = _RISK.get(hw, 1.0) if mode in active else 1.0
            data['safety_weight'] = data.get('length', 0) * risk
        return 'safety_weight'

    def _add_emission_weights(self, graph: Any, mode: str) -> str:
        """
        Gradient-aware emission weights.

        Uses 'grade' attribute from ox.add_edge_grades when available;
        falls back to node elevation difference; falls back to flat terrain.
        Uphill: factor = 1 + grade × 5.  Downhill: factor = max(0.5, 1 + grade × 2).
        Both clamped to [0.5, 3.0].
        """
        has_elev  = self.graph_manager.has_elevation()
        emit_g_km = _EMISSIONS_G_KM.get(mode, 100)
        zero_emit = emit_g_km == 0

        for _u, _v, _k, data in graph.edges(keys=True, data=True):
            length_m  = data.get('length', 0.0)
            length_km = length_m / 1000.0

            if zero_emit:
                data['emission_weight'] = length_m / max(
                    self.speeds_km_min.get(mode, 0.5) * 1000, 1.0
                )
                continue

            factor = 1.0
            if has_elev:
                grade = data.get('grade')
                if grade is None and length_m > 0:
                    eu    = graph.nodes[_u].get('elevation', 0)
                    ev    = graph.nodes[_v].get('elevation', 0)
                    grade = (ev - eu) / length_m
                if grade is not None:
                    factor = (1.0 + grade * 5.0) if grade > 0 else max(0.5, 1.0 + grade * 2.0)
                    factor = max(0.5, min(3.0, factor))

            data['emission_weight'] = emit_g_km * length_km * factor
        return 'emission_weight'

    def _add_monetary_weights(self, graph: Any, mode: str, policy: Dict) -> str:
        """
        Monetary cost weights: fuel/energy cost + carbon tax + tolls.

        Primary metric for "lowest cost to decarbonisation" research.
        """
        e_price    = float(policy.get('energy_price_gbp_km',  0.12))
        c_tax      = float(policy.get('carbon_tax_gbp_tco2',  0.0))
        emit_kg_km = _EMISSIONS_G_KM.get(mode, 100) / 1000.0

        for _u, _v, _k, data in graph.edges(keys=True, data=True):
            dist_km  = data.get('length', 0.0) / 1000.0
            toll_km  = data.get('toll_per_km', 0.0)
            data['monetary_weight'] = (
                dist_km * e_price
                + dist_km * emit_kg_km * c_tax
                + dist_km * toll_km
            )
        return 'monetary_weight'

    def _add_decarbonisation_weights(
        self, graph: Any, mode: str, policy: Dict,
    ) -> str:
        """
        Lifecycle CO₂ weights (UK CCC 6th Carbon Budget trajectory).

        Includes: operational emissions × grade factor, embodied manufacturing
        carbon, and infrastructure carbon amortised per km.  Carbon price
        trajectory: £80/tCO₂ in 2025 → £300/tCO₂ in 2050 (linearly interpolated).
        """
        from datetime import datetime
        scenario_year = int(policy.get('scenario_year', datetime.now().year))
        _BUDGET = {2025: 80, 2030: 120, 2035: 180, 2040: 240, 2050: 300}
        years   = sorted(_BUDGET)
        if scenario_year <= years[0]:
            c_price = _BUDGET[years[0]]
        elif scenario_year >= years[-1]:
            c_price = _BUDGET[years[-1]]
        else:
            for i in range(len(years) - 1):
                y0, y1 = years[i], years[i + 1]
                if y0 <= scenario_year <= y1:
                    t       = (scenario_year - y0) / (y1 - y0)
                    c_price = _BUDGET[y0] + t * (_BUDGET[y1] - _BUDGET[y0])
                    break

        _EMBODIED: Dict[str, float] = {
            'car': 0.060, 'ev': 0.085, 'bus': 0.020, 'tram': 0.015,
            'van_diesel': 0.040, 'van_electric': 0.055,
            'truck_diesel': 0.035, 'truck_electric': 0.045,
            'hgv_diesel': 0.025, 'hgv_electric': 0.035, 'hgv_hydrogen': 0.030,
            'walk': 0.0, 'bike': 0.001, 'e_scooter': 0.002, 'cargo_bike': 0.002,
            'local_train': 0.010, 'intercity_train': 0.008, 'freight_rail': 0.012,
        }
        embodied_kg_km = _EMBODIED.get(mode, 0.030)
        has_elev       = self.graph_manager.has_elevation()
        emit_kg_km     = _EMISSIONS_G_KM.get(mode, 100) / 1000.0

        for _u, _v, _k, data in graph.edges(keys=True, data=True):
            dist_km = data.get('length', 0.0) / 1000.0
            factor  = 1.0
            if has_elev:
                grade = data.get('grade')
                if grade is None and data.get('length', 0) > 0:
                    eu    = graph.nodes[_u].get('elevation', 0)
                    ev    = graph.nodes[_v].get('elevation', 0)
                    grade = (ev - eu) / data['length']
                if grade is not None:
                    factor = (1.0 + grade * 5.0) if grade > 0 else max(0.5, 1.0 + grade * 2.0)
                    factor = max(0.5, min(3.0, factor))

            operational_kg = emit_kg_km * dist_km * factor
            lifecycle_kg   = operational_kg + embodied_kg_km * dist_km
            data['decarb_weight'] = lifecycle_kg * (c_price / 1000.0)

        return 'decarb_weight'

    def _add_scenic_weights(self, graph: Any, mode: str) -> str:
        """
        Prefer quiet, green roads over arterials and motorways.

        Graph-type safety: OSMnx returns MultiDiGraph (edges are 4-tuples:
        u, v, key, data).  Some internal graphs (converted tram, OpenRailMap)
        may be plain Graph or DiGraph (3-tuples: u, v, data — no key field).
        The previous `for _u, _v, _k, data in graph.edges(keys=True, data=True)`
        worked for MultiDiGraph but silently broke for plain Graph: `keys=True`
        is ignored by non-multi graphs so it still returns 3-tuples, and
        Python would unpack `_k = data` (the dict) and `data = StopIteration`,
        making every `data.get(...)` raise AttributeError (caught by the caller
        and silently dropped).  The fix uses `edge[-1]` — always the data dict
        regardless of tuple length.
        """
        _S: Dict[str, float] = {
            'motorway':       8.0,
            'motorway_link':  6.0,
            'trunk':          5.0,
            'trunk_link':     4.0,
            'primary':        3.0,
            'primary_link':   2.5,
            'secondary':      1.8,
            'secondary_link': 1.5,
            'tertiary':       0.9,
            'unclassified':   0.85,
            'residential':    0.70,
            'living_street':  0.60,
            'pedestrian':     0.50,
            'path':           0.45,
            'footway':        0.40,
            'cycleway':       0.40,
            'track':          0.40,
            'service':        1.00,
        }
        is_multi = graph.is_multigraph()
        for edge in graph.edges(keys=is_multi, data=True):
            data = edge[-1]   # (u,v,key,data)→data or (u,v,data)→data
            if not isinstance(data, dict):
                continue
            hw = data.get('highway', 'residential')
            if isinstance(hw, list):
                hw = hw[0] if hw else 'residential'
            data['scenic_weight'] = data.get('length', 0) * _S.get(hw, 1.5)
        return 'scenic_weight'