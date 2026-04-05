"""
simulation/spatial/router.py

Route computation with generalised cost and intermodal rail/transit transfers.

Architecture
------------
Three parallel graphs, never merged:
  • Road graph   (OSMnx 'drive')  — car, bus, van, truck, HGV
  • Rail graph   (OpenRailMap)    — local_train, intercity_train,
                                    freight_rail; loaded via
                                    env.load_rail_graph()
  • Transit graph (GTFS)          — bus, tram, ferry; loaded via
                                    env.load_gtfs_graph()

Generalised cost formula (per edge)
------------------------------------
    cost = (time_h × VoT)
         + (dist_km × energy_price)
         + (dist_km × emit_kg_km × carbon_tax)

VoT / energy_price / carbon_tax are read from a per-call policy_context
dict so that scenario policy events (carbon tax hike, fuel price spike)
immediately shift agent route choices without any code change.

Routing dispatch (compute_route)
---------------------------------
    mode == 'tram'         → _compute_gtfs_route  (GTFS preferred;
                             tram-spine fallback when GTFS absent)
    mode in _RAIL_MODES    → _compute_intermodal_route
    mode in _TRANSIT_MODES → _compute_gtfs_route  (bus, ferry)
    all others             → _compute_road_route

Intermodal transfer logic
--------------------------
For modes that use the rail graph (local_train, intercity_train,
freight_rail):
  1. Snap origin to nearest rail node (max 5 km).
  2. Snap destination to nearest rail node (max 5 km).
  3. Walk/interpolated access leg: origin → origin station.
  4. Rail leg on OpenRailMap graph with generalised-cost weights.
  5. Walk/interpolated egress leg: dest station → destination.
  6. Concatenate all three legs, dropping duplicate boundary points.

Invalid route sentinel
-----------------------
_get_invalid_route() returns an empty list [].  Callers check
``if not route or len(route) < 2`` to detect failure.  The old approach
of returning an off-map penalty point (+10°) caused those coordinates
to appear in the PathLayer and drew diagonal artefacts on the map.

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
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

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
# 'tram' is deliberately NOT in _RAIL_MODES — trams are routed via GTFS
# (or the tram spine) so they follow actual tram track geometry rather
# than the OpenRailMap mainline rail topology.
_RAIL_MODES    = frozenset({'local_train', 'intercity_train', 'freight_rail'})
_TRANSIT_MODES = frozenset({'bus', 'ferry_diesel', 'ferry_electric'})

# ── Default policy parameters (overridden per-call by scenario context) ────────
_DEFAULT_POLICY: Dict[str, float] = {
    'value_of_time_gbp_h':  10.0,   # £10/h UK average
    'energy_price_gbp_km':   0.12,   # ~12p/km petrol equivalent
    'carbon_tax_gbp_tco2':   0.0,    # £0 — no carbon tax by default
    'boarding_penalty_min':  15.0,   # 15-min transfer penalty at station
}

# ── Emissions factors (g CO₂/km) — mirrors modes.py for cost weighting ────────
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
    Computes routes and route alternatives using parallel road + rail + transit
    graphs.

    Strategy
    --------
    • Road agents  → single-graph generalised-cost route on drive/walk/bike.
    • Rail agents  → access leg (walk) + rail leg + egress leg (walk).
    • Tram agents  → GTFS route (shape_coords geometry); spine fallback.
    • Bus agents   → GTFS route with road fallback for missing shape segments.
    • Abstract modes (ferry/air) — handled upstream in bdi_planner.
    """

    def __init__(self, graph_manager: 'GraphManager', congestion_manager=None):
        self.graph_manager      = graph_manager
        self.congestion_manager = congestion_manager

        # Rail graph loaded lazily on first rail request (see _get_rail_graph).
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
            'walk':            0.083,
            'bike':            0.25,
            'cargo_bike':      0.20,
            'e_scooter':       0.33,
            'bus':             0.33,
            'car':             0.50,
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
            'ferry_diesel':    0.58,
            'ferry_electric':  0.50,
            'flight_domestic': 11.67,
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

        Dispatches to the correct routing strategy based on mode.  Returns
        an empty list on any failure so callers can test ``if not route``.

        Args:
            agent_id:       Used for logging.
            origin:         (lon, lat) start coordinate.
            dest:           (lon, lat) end coordinate.
            mode:           RTD_SIM mode string.
            policy_context: Optional policy parameter overrides.

        Returns:
            List of (lon, lat) 2-tuples, or [] on failure.
        """
        if not (is_valid_lonlat(origin) and is_valid_lonlat(dest)):
            logger.error("❌ %s: invalid coords %s → %s", agent_id, origin, dest)
            return []

        # if haversine_km(origin, dest) < 0.1:
        #     return [origin, dest]
        dist_km = haversine_km(origin, dest)
        if dist_km < 0.1:
            return [origin, dest]

        # PATCH: Enforce absolute maximum ranges for active modes
        # This stops the BDI planner from plotting 15km e-scooter or walk trips
        if mode == 'e_scooter' and dist_km > 10.0:
            return self._get_invalid_route(origin, dest)
        if mode == 'walk' and dist_km > 10.0:
            return self._get_invalid_route(origin, dest)
        if mode in ('bike', 'cargo_bike') and dist_km > 25.0:
            return self._get_invalid_route(origin, dest)

        policy = {**_DEFAULT_POLICY, **(policy_context or {})}

        # Tram: GTFS preferred; tram-spine fallback when GTFS absent.
        if mode == 'tram':
            return self._compute_gtfs_route(agent_id, origin, dest, mode, policy)

        # Heavy rail: three-leg intermodal route.
        if mode in _RAIL_MODES:
            return self._compute_intermodal_route(
                agent_id, origin, dest, mode, policy
            )

        # Bus / ferry: GTFS four-leg route; road proxy when GTFS absent.
        if mode in _TRANSIT_MODES:
            return self._compute_gtfs_route(agent_id, origin, dest, mode, policy)

        # All other modes: single-graph road route.
        return self._compute_road_route(agent_id, origin, dest, mode, policy)

    def compute_alternatives(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str,
        variants: List[str] = None,
        policy_context: Optional[Dict] = None,
    ) -> list:
        """Compute multiple route alternatives (e.g. fastest, greenest, cheapest)."""
        if not ROUTE_ALTERNATIVE_AVAILABLE:
            route = self.compute_route(agent_id, origin, dest, mode,
                                       policy_context)
            return [{'route': route, 'mode': mode, 'variant': 'shortest'}]

        variants = variants or ['shortest', 'fastest']
        policy   = {**_DEFAULT_POLICY, **(policy_context or {})}
        alternatives = []

        for variant in variants:
            route = self._compute_route_variant(
                origin, dest, mode, variant, agent_id, policy
            )
            if route and len(route) >= 2:
                alternatives.append(RouteAlternative(route, mode, variant))

        if not alternatives:
            basic = self.compute_route(agent_id, origin, dest, mode,
                                       policy_context)
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

        Returns an empty list when no path exists so the BDI planner knows
        the mode is physically inaccessible for this origin–destination pair.

        Geometry is extracted from Shapely LineString edge attributes and
        then interpolated at 50 m intervals for smooth animation and correct
        per-step position tracking.
        """
        network_type = self.mode_network_types.get(mode, 'drive')
        graph        = self.graph_manager.get_graph(network_type)

        if graph is None:
            logger.warning(
                "❌ %s: graph '%s' not loaded — rejecting route",
                agent_id, network_type,
            )
            return self._get_invalid_route(origin, dest)

        try:
            orig_node = self.graph_manager.get_nearest_node(origin, network_type)
            dest_node = self.graph_manager.get_nearest_node(dest,   network_type)

            if orig_node is None or dest_node is None or orig_node == dest_node:
                return self._get_invalid_route(origin, dest)

            weight_key   = self._apply_generalised_weights(graph, mode, policy)
            route_nodes  = nx.shortest_path(
                graph, orig_node, dest_node, weight=weight_key
            )
            return self._interpolate(
                self._extract_geometry(graph, route_nodes),
                max_segment_km=0.05,
            )

        except nx.NetworkXNoPath:
            logger.warning("No physical road path for %s using %s", agent_id, mode)
            return self._get_invalid_route(origin, dest)
        except Exception as exc:
            logger.error("❌ %s: road routing failed: %s", agent_id, exc)
            return self._get_invalid_route(origin, dest)

    # =========================================================================
    # RAIL INTERMODAL ROUTING
    # =========================================================================

    def _get_rail_graph(self) -> Optional[Any]:
        """
        Return the rail graph, loading it lazily on first call.

        Priority:
          1. graph_manager already has 'rail' (loaded by env.load_rail_graph()).
          2. self._rail_graph cached from a previous call.
          3. Fetch from OpenRailMap using the drive-graph bounding box.

        NOTE: env.load_rail_graph() should always be called during setup
        (see environment_setup.py).  When it is, the graph_manager already
        holds the OpenRailMap result and path (1) is taken immediately.
        Path (3) is a last-resort fallback for environments where setup was
        skipped.
        """
        cached = self.graph_manager.get_graph('rail')
        if cached is not None:
            return cached

        if self._rail_graph is not None:
            return self._rail_graph

        if self._rail_graph_attempted:
            return None

        self._rail_graph_attempted = True
        logger.info("Loading OpenRailMap graph (first rail request)…")
        try:
            drive = self.graph_manager.get_graph('drive')
            if drive is not None:
                xs   = [d['x'] for _, d in drive.nodes(data=True)]
                ys   = [d['y'] for _, d in drive.nodes(data=True)]
                bbox = (max(ys), min(ys), max(xs), min(xs))   # N,S,E,W
            else:
                bbox = (56.0, 55.85, -3.05, -3.40)   # Edinburgh default

            self._rail_graph = fetch_rail_graph(bbox)

            if self._rail_graph is not None:
                logger.info(
                    "✅ Rail graph: %d nodes, %d edges",
                    len(self._rail_graph.nodes), len(self._rail_graph.edges),
                )
                # Register so the visualizer can also access it.
                self.graph_manager.graphs['rail'] = self._rail_graph
            else:
                logger.warning(
                    "⚠️  Rail graph fetch returned None — "
                    "rail agents cannot route"
                )
        except Exception as exc:
            logger.error("Rail graph load failed: %s", exc)
            self._rail_graph = None

        return self._rail_graph

    # Maximum credible walk-to-station distance in km.  If the nearest rail
    # node is further than this the OpenRailMap graph is too sparse for this
    # area and the route is rejected rather than creating a multi-kilometre
    # "walk" leg on residential streets mislabelled as a rail route.
    _MAX_ACCESS_KM: float = 5.0

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
        2. Origin and destination snap to the same rail node (degenerate
           rail leg — trip is too short for rail or graph is very sparse).
        3. Nearest rail node is > _MAX_ACCESS_KM away (fragmented graph).
        4. Track topology fragmented — nx.NetworkXNoPath raised.

        All guards return [] so the BDI planner can fall back to another
        mode rather than displaying a broken route.
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

        # Reject if the snap distances are unreasonably large.
        if (haversine_km(origin, orig_rail_coord) > self._MAX_ACCESS_KM
                or haversine_km(dest_rail_coord, dest) > self._MAX_ACCESS_KM):
            return self._get_invalid_route(origin, dest)

        # ── Access and egress legs (walk graph, interpolated line, or drive) ──
        access_leg = self._compute_access_leg(
            agent_id + '_access', origin, orig_rail_coord
        )
        egress_leg = self._compute_access_leg(
            agent_id + '_egress', dest_rail_coord, dest
        )

        # ── Rail leg ──────────────────────────────────────────────────────────
        try:
            rail_weight_key = self._apply_generalised_weights(
                rail_graph, mode, policy
            )
            rail_nodes  = nx.shortest_path(
                rail_graph, orig_rail_node, dest_rail_node,
                weight=rail_weight_key,
            )
            rail_coords = self._interpolate(
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

        # ── Stitch: drop duplicate boundary points ────────────────────────────
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
        Return the GTFS transit graph (bus/tram/ferry stops + service edges).

        The transit graph is never auto-fetched — it must be pre-loaded via:
            env.load_gtfs_graph(feed_path=config.gtfs_feed_path)
        or registered directly:
            env.graph_manager.graphs['transit'] = G_transit

        Returns None when no GTFS data is available so callers fall back
        gracefully.
        """
        return self.graph_manager.get_graph('transit')

    def _get_invalid_route(
        self,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
    ) -> List[Tuple[float, float]]:
        """
        Return an empty list to signal routing failure to the BDI planner.

        Callers check: ``if not route or len(route) < 2``

        The previous implementation returned [origin, (+10°), dest] as an
        off-map penalty route.  This caused those coordinates to appear in
        the PathLayer and draw diagonal artefacts across the map.
        """
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
        Fallback strategy when GTFS graph is missing or routing fails.

        Trams use the rail spine (physical track geometry).
        Ferries return an invalid route (no road proxy for water crossings).
        Buses fall back to the drive graph.
        """
        # PATCH: Force trams AND heavy rail onto the physical rail track intermodal router 
        # when GTFS is disabled, preventing them from disappearing.
        if mode in ('tram', 'local_train', 'intercity_train'):
            return self._compute_intermodal_route(agent_id, origin, dest, mode, policy)
            
        # Ferries over water without GTFS are impossible to proxy
        if mode in ('ferry_diesel', 'ferry_electric'):
            return self._get_invalid_route(origin, dest)
            
        # Buses gracefully fall back to the standard physical drive graph
        return self._compute_road_route(agent_id, origin, dest, mode, policy)
    
        # if mode == 'tram':
        #     return self._compute_intermodal_route(
        #         agent_id, origin, dest, mode, policy
        #     )
        # if mode in ('ferry_diesel', 'ferry_electric'):
        #     return self._get_invalid_route(origin, dest)
        # return self._compute_road_route(agent_id, origin, dest, mode, policy)

    def _compute_access_leg(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        max_straight_km: float = 3.0,
    ) -> List[Tuple[float, float]]:
        """
        Compute a pedestrian access or egress leg to/from a transit stop.

        Strategy (in priority order):
          1. Walk graph loaded → route on it.
          2. Walk graph absent AND distance ≤ max_straight_km →
             interpolated straight line (pedestrians use footpaths and
             cut-throughs not present in the drive graph; a straight line
             avoids the 200+ waypoint residential squiggle of a drive
             proxy route).
          3. Distance > max_straight_km and walk graph absent →
             drive graph proxy.
          4. Drive proxy also fails → interpolated straight line.

        Args:
            agent_id:        For logging only.
            origin:          (lon, lat) start.
            dest:            (lon, lat) end (usually a stop/station).
            max_straight_km: Threshold for strategy 2 vs 3.

        Returns:
            List of (lon, lat) 2-tuples.
        """
        dist_km = haversine_km(origin, dest)

        G_walk = self.graph_manager.get_graph('walk')
        if G_walk is not None:
            try:
                orig_node = self.graph_manager.get_nearest_node(origin, 'walk')
                dest_node = self.graph_manager.get_nearest_node(dest,   'walk')
                if orig_node and dest_node and orig_node != dest_node:
                    walk_nodes = nx.shortest_path(G_walk, orig_node, dest_node)
                    return self._interpolate(
                        self._extract_geometry(G_walk, walk_nodes),
                        max_segment_km=0.05,
                    )
            except Exception:
                pass

        if dist_km <= max_straight_km:
            logger.debug(
                "%s: walk graph absent, access leg %.2fkm — interpolated line",
                agent_id, dist_km,
            )
            return self._interpolate([origin, dest], max_segment_km=0.05)

        logger.debug(
            "%s: walk graph absent, access leg %.2fkm > %.2fkm — drive proxy",
            agent_id, dist_km, max_straight_km,
        )
        drive_result = self._compute_road_route(
            agent_id, origin, dest, 'car', _DEFAULT_POLICY
        )
        if len(drive_result) > 2:
            return drive_result

        logger.debug(
            "%s: drive proxy failed (%d pts) — interpolated line",
            agent_id, len(drive_result),
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

        Leg structure:
            access walk  → board at nearest stop
            → ride (headway-weighted generalised cost on transit graph)
            → alight at nearest stop to destination
            → egress walk

        Generalised cost per transit edge:
            gen_cost = (travel_time_h + headway_h/2) × VoT
                     + dist_km × energy_price
                     + dist_km × emit_kg_km × carbon_tax

        headway_h/2 is the expected waiting time (E[wait] = headway/2 for
        uniform arrivals) — the term that makes 4-min Edinburgh trams
        competitive vs 60-min rural buses in the BDI cost model.

        Tram snap logic
        ---------------
        BODS may encode Edinburgh Trams as route_type=0 ('tram') or as
        route_type=3 ('local_train') depending on the feed version.  We
        try both filter strings in sequence and use the first that returns
        a valid stop pair.

        Mode masking
        ------------
        The GTFS transit graph mixes all service modes.  Without masking,
        nx.shortest_path may route a tram trip via cheap bus edges.  We
        set gen_cost=inf for edges of the wrong mode family so the path is
        forced to stay on the correct service type.

        Geometry
        ---------
        shape_coords are BODS GTFS polylines — ground-truth geometry for
        each stop pair.  Bus edges that lack shape_coords fall back to the
        drive graph for that segment.  Tram/ferry edges without shape_coords
        fall back to a straight stop-to-stop interpolation.
        """
        G_transit = self._get_transit_graph()

        if G_transit is None:
            if mode == 'tram':
                logger.debug("%s: no GTFS — using tram spine fallback", agent_id)
                try:
                    from simulation.spatial.rail_spine import route_via_tram_stops
                    spine_route = route_via_tram_stops(origin, dest)
                    if spine_route and len(spine_route) > 2:
                        # Map each tram-stop segment to the road network so the
                        # route follows actual street geometry rather than
                        # a straight line between stop centroids.
                        realistic_route: List[Tuple[float, float]] = []
                        for i in range(len(spine_route) - 1):
                            leg = self._compute_road_route(
                                agent_id, spine_route[i], spine_route[i + 1],
                                'car', policy,
                            )
                            if leg and len(leg) > 1:
                                realistic_route.extend(leg[:-1])
                            else:
                                realistic_route.append(spine_route[i])
                        realistic_route.append(spine_route[-1])
                        return realistic_route
                    return spine_route if spine_route else []
                except Exception:
                    pass
            return self._transit_fallback(agent_id, origin, dest, mode, policy)

        try:
            from simulation.gtfs.gtfs_graph import GTFSGraph, _haversine_m
        except ImportError:
            return self._transit_fallback(agent_id, origin, dest, mode, policy)

        builder = GTFSGraph(None)

        # ── Snap origin and destination to nearest stops ───────────────────────
        if mode == 'tram':
            # Try 'tram' encoding first, then 'local_train' (BODS fallback).
            _tram_filters  = ['tram', 'local_train']
            _tram_catchment = 5000   # 5 km — tram stops can be far apart
            origin_stop = dest_stop = None
            for mf in _tram_filters:
                origin_stop = builder.nearest_stop(
                    G_transit, origin, mode_filter=mf,
                    max_distance_m=_tram_catchment,
                )
                dest_stop = builder.nearest_stop(
                    G_transit, dest, mode_filter=mf,
                    max_distance_m=_tram_catchment,
                )
                if origin_stop and dest_stop and origin_stop != dest_stop:
                    logger.debug(
                        "%s: tram snap via mode_filter=%s (%s→%s)",
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
            logger.debug(
                "%s: no GTFS stop pair for %s — transit fallback",
                agent_id, mode,
            )
            return self._transit_fallback(agent_id, origin, dest, mode, policy)

        # ── Mode masking — block wrong-family edges ────────────────────────────
        _TRAM_MODES = frozenset({'tram', 'local_train'})
        _RAIL_MODES = frozenset({'local_train', 'intercity_train', 'rail',
                                 'freight_rail'})
        _BUS_MODES  = frozenset({'bus'})
        if mode == 'tram':
            _allowed_modes = _TRAM_MODES
        elif mode in ('local_train', 'intercity_train'):
            _allowed_modes = _RAIL_MODES
        elif mode == 'bus':
            _allowed_modes = _BUS_MODES
        else:
            _allowed_modes = frozenset({mode})

        # ── Headway-weighted generalised cost ─────────────────────────────────
        vot     = float(policy.get('value_of_time_gbp_h',  10.0))
        e_price = float(policy.get('energy_price_gbp_km',   0.12))
        c_tax   = float(policy.get('carbon_tax_gbp_tco2',   0.0))

        for u, v, key, data in G_transit.edges(keys=True, data=True):
            edge_mode = data.get('mode', 'bus')
            if edge_mode == 'walk' or data.get('highway') == 'transfer':
                data['gen_cost'] = 9999.0
                continue
            if edge_mode not in _allowed_modes:
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
                "%s: no GTFS path %s→%s — drive proxy",
                agent_id, origin_stop, dest_stop,
            )
            return self._compute_road_route(agent_id, origin, dest, mode, policy)

        # ── Extract geometry from shape_coords ────────────────────────────────
        transit_coords: List[Tuple[float, float]] = []
        for i in range(len(transit_nodes) - 1):
            u_node   = transit_nodes[i]
            v_node   = transit_nodes[i + 1]
            edge_map = G_transit.get_edge_data(u_node, v_node) or {}
            first_key = next(iter(edge_map), None)
            shape     = edge_map[first_key].get('shape_coords', []) if first_key else []

            if shape and len(shape) > 2:
                transit_coords.extend(shape if i == 0 else shape[1:])
            else:
                # Shape missing — road proxy for buses, interpolation for tram/ferry.
                u_x = float(G_transit.nodes[u_node].get('x', 0))
                u_y = float(G_transit.nodes[u_node].get('y', 0))
                v_x = float(G_transit.nodes[v_node].get('x', 0))
                v_y = float(G_transit.nodes[v_node].get('y', 0))

                if mode in ('bus', 'van_electric', 'van_diesel'):
                    leg = self._compute_road_route(
                        agent_id, (u_x, u_y), (v_x, v_y), 'car', policy
                    )
                    if leg and len(leg) > 1:
                        transit_coords.extend(leg if i == 0 else leg[1:])
                    else:
                        # PATCH: Do NOT draw a straight line if the road proxy fails.
                        # Reject the route so the bus doesn't fly over water or buildings.
                        logger.warning("❌ %s: Road proxy failed between GTFS stops. Rejecting.", agent_id)
                        return self._get_invalid_route(origin, dest)
                    # else:
                    #     if i == 0:
                    #         transit_coords.append((u_x, u_y))
                    #     transit_coords.append((v_x, v_y))
                else:
                    if i == 0:
                        transit_coords.append((u_x, u_y))
                    transit_coords.append((v_x, v_y))

        if not transit_coords:
            return self._transit_fallback(agent_id, origin, dest, mode, policy)

        # ── Access leg (walk to first stop) ───────────────────────────────────
        first_d     = G_transit.nodes.get(origin_stop, {})
        first_coord = (
            float(first_d.get('x', origin[0])),
            float(first_d.get('y', origin[1])),
        )
        access_leg = self._compute_access_leg(
            agent_id + '_access', origin, first_coord
        )

        # ── Egress leg (walk from last stop) ──────────────────────────────────
        last_d     = G_transit.nodes.get(dest_stop, {})
        last_coord = (
            float(last_d.get('x', dest[0])),
            float(last_d.get('y', dest[1])),
        )
        egress_leg = self._compute_access_leg(
            agent_id + '_egress', last_coord, dest
        )

        # ── Stitch ─────────────────────────────────────────────────────────────
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
    # RAIL NODE SNAPPING
    # =========================================================================

    def _nearest_rail_node(
        self,
        coord: Tuple[float, float],
        rail_graph: Any,
    ) -> Optional[int]:
        """
        Snap a coordinate to the nearest node on the rail graph.

        Strategy (in priority order)
        ----------------------------
        1.  NaPTAN transfer nodes (DfT authoritative ~2,500 UK stations, cached
            30 days).  ``nearest_transfer_node()`` returns precise platform
            coordinates (±5 m).  We then snap those coordinates to the nearest
            rail graph node so the routing works on the actual loaded graph.

        2.  Brute-force O(N) scan of rail graph nodes (fallback when NaPTAN is
            unavailable or the transfer node is outside the graph).

        NaPTAN integration significantly improves accuracy in two ways:
          • Platforms are not the same as OSM node centroids — snapping to NaPTAN
            first then to the graph avoids a multi-hundred-metre mis-placement.
          • For agents in the Highlands or Islands, NaPTAN has stations the
            OpenRailMap graph may not include (e.g. small halts, ferry terminals),
            so this path also improves coverage.
        """
        if rail_graph is None:
            return None

        # ── Strategy 1: NaPTAN → nearest graph node ───────────────────────────
        try:
            from simulation.spatial.rail_spine import nearest_transfer_node
            transfer = nearest_transfer_node(coord, max_km=self._MAX_ACCESS_KM)
            if transfer:
                snap_coord = (transfer['lon'], transfer['lat'])
                # Find the graph node nearest the precise platform coordinate.
                lon, lat = snap_coord
                best_node = None
                best_dist = float('inf')
                for node, data in rail_graph.nodes(data=True):
                    nlon = float(data.get('x', data.get('lon', 0)))
                    nlat = float(data.get('y', data.get('lat', 0)))
                    d    = haversine_km((lon, lat), (nlon, nlat))
                    if d < best_dist:
                        best_dist = d
                        best_node = node
                if best_node is not None and best_dist < self._MAX_ACCESS_KM:
                    return best_node
        except Exception:
            pass

        # ── Strategy 2: brute-force O(N) scan of rail graph ───────────────────
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
        Write a 'gen_cost' attribute to every edge:

            cost = (time_h × VoT)
                 + (dist_km × energy_price)
                 + (dist_km × emit_kg_km × carbon_tax)

        For rail graphs, infrastructure-type filtering is applied after the
        base cost:
          • trams are blocked from mainline rail edges (gen_cost = inf).
          • heavy rail is blocked from tram/light_rail edges.

        The base gen_cost is always written FIRST; the infrastructure filter
        only OVERWRITES it when the edge is the wrong type.  There is no
        dangling variable reference.

        Recomputed every call so policy changes take effect immediately.

        Returns:
            Edge attribute name for nx.shortest_path weight='gen_cost'.
        """
        vot        = float(policy.get('value_of_time_gbp_h',  10.0))
        e_price    = float(policy.get('energy_price_gbp_km',   0.12))
        c_tax      = float(policy.get('carbon_tax_gbp_tco2',   0.0))
        speed_km_h = self.speeds_km_min.get(mode, 0.5) * 60.0
        emit_kg_km = _EMISSIONS_G_KM.get(mode, 100) / 1000.0

        is_rail_graph = graph.graph.get('name') == 'rail'

        for u, v, key, data in graph.edges(keys=True, data=True):
            dist_km = data.get('length', 0.0) / 1000.0

            cong = 1.0
            if self.congestion_manager is not None:
                try:
                    cong = self.congestion_manager.get_congestion_factor(u, v, key)
                except Exception:
                    pass

            time_h = (dist_km / max(speed_km_h, 0.1)) * cong

            # Base generalised cost — always written unconditionally.
            data['gen_cost'] = (
                time_h   * vot
                + dist_km * e_price
                + dist_km * emit_kg_km * c_tax
            )

            # Infrastructure filter — overwrite gen_cost for wrong track type.
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
        Extract (lon, lat) 2-tuples from an ordered list of graph nodes.

        For each consecutive node pair (u, v), the method prefers a Shapely
        LineString on the edge (OSMnx geometry for curved roads/tracks).
        When multiple parallel edges exist, the edge with geometry is
        preferred over one without.  Falls back to straight u→v if no
        geometry attribute is present.
        """
        coords: List[Tuple[float, float]] = []

        for i in range(len(route_nodes) - 1):
            u, v = route_nodes[i], route_nodes[i + 1]

            if i == 0:
                coords.append(
                    (float(graph.nodes[u]['x']), float(graph.nodes[u]['y']))
                )

            edge_dict = graph.get_edge_data(u, v) or {}
            # Prefer the edge that carries a Shapely geometry attribute.
            edge_data = (
                next((d for d in edge_dict.values() if 'geometry' in d), None)
                or next(iter(edge_dict.values()), None)
            )

            if edge_data and 'geometry' in edge_data:
                geom = edge_data['geometry']
                if hasattr(geom, 'coords'):
                    coords.extend(
                        (float(x), float(y))
                        for x, y in list(geom.coords)[1:]
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
        Insert intermediate points so that no segment exceeds max_segment_km.

        This serves two purposes:
          • Smooth visual rendering — animated agents move along curves
            rather than jumping between distant OSM intersection nodes.
          • Accurate per-step position tracking — the simulation advances
            agents by a fixed distance each step; without dense waypoints
            the position arithmetic drifts on long straight segments.

        Intermediate points are linearly interpolated in lon/lat space.
        For the segment lengths used here (≤50 m for roads, ≤200 m for
        rail) the error vs great-circle interpolation is negligible.
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
    # ROUTE VARIANTS (for compute_alternatives)
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

        Variants:
            generalised / shortest — minimum generalised cost
            fastest                — minimum travel time
            safest                 — minimum risk (active/vulnerable modes)
            greenest               — minimum operational CO₂ (grade-aware)
            cheapest               — minimum monetary cost (fuel + fares)
            decarbonisation        — minimum lifecycle CO₂ (UK carbon budget)
            scenic                 — prefer quiet / green roads
        """
        if not (is_valid_lonlat(origin) and is_valid_lonlat(dest)):
            return []
        policy = policy or dict(_DEFAULT_POLICY)

        if mode in _RAIL_MODES:
            return self._compute_intermodal_route(
                agent_id, origin, dest, mode, policy
            )

        network_type = self.mode_network_types.get(mode, 'drive')
        graph        = self.graph_manager.get_graph(network_type)
        if graph is None:
            return []

        try:
            orig_node = self.graph_manager.get_nearest_node(origin, network_type)
            dest_node = self.graph_manager.get_nearest_node(dest,   network_type)
            if orig_node is None or dest_node is None:
                return []

            weight_key = {
                'generalised':     lambda: self._apply_generalised_weights(
                                       graph, mode, policy),
                'shortest':        lambda: self._apply_generalised_weights(
                                       graph, mode, policy),
                'fastest':         lambda: self._add_time_weights(graph, mode),
                'safest':          lambda: self._add_safety_weights(graph, mode),
                'greenest':        lambda: self._add_emission_weights(graph, mode),
                'cheapest':        lambda: self._add_monetary_weights(
                                       graph, mode, policy),
                'decarbonisation': lambda: self._add_decarbonisation_weights(
                                       graph, mode, policy),
                'scenic':          lambda: self._add_scenic_weights(graph, mode),
            }.get(variant, lambda: 'length')()

            route_nodes = nx.shortest_path(
                graph, orig_node, dest_node, weight=weight_key
            )
            return self._interpolate(
                self._extract_geometry(graph, route_nodes),
                max_segment_km=0.05,
            )

        except nx.NetworkXNoPath:
            return []
        except Exception as exc:
            logger.warning("%s: variant %s failed: %s", agent_id, variant, exc)
            return []

    # =========================================================================
    # WEIGHT HELPERS
    # =========================================================================

    def _add_time_weights(self, graph: Any, mode: str) -> str:
        """Minimise travel time only (ignores energy cost and emissions)."""
        speed_m_min = self.speeds_km_min.get(mode, 0.5) * 1000
        for u, v, key, data in graph.edges(keys=True, data=True):
            length = data.get('length', 0)
            base   = length / max(speed_m_min, 1.0)
            if self.congestion_manager is not None:
                try:
                    base *= self.congestion_manager.get_congestion_factor(u, v, key)
                except Exception:
                    pass
            data['time_weight'] = base
        return 'time_weight'

    def _add_safety_weights(self, graph: Any, mode: str) -> str:
        """
        Minimise risk for active/vulnerable road users.

        Risk multipliers by road type are highest for motorways and zero
        for dedicated cycleways and footways.
        """
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
        Gradient-aware emission weights using true road grade.

        Uses the 'grade' edge attribute (from ox.add_edge_grades) when
        available; falls back to node-pair elevation difference; falls back
        to flat-terrain assumption.

        Uphill penalty:   factor = 1 + max(0, grade) × 5
        Downhill saving:  factor = max(0.5, 1 + grade × 2)
        Both clamped to [0.5, 3.0].
        """
        has_elev   = self.graph_manager.has_elevation()
        emit_g_km  = _EMISSIONS_G_KM.get(mode, 100)
        zero_emit  = emit_g_km == 0

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
                    if grade > 0:
                        factor = 1.0 + grade * 5.0
                    else:
                        factor = max(0.5, 1.0 + grade * 2.0)
                    factor = max(0.5, min(3.0, factor))

            data['emission_weight'] = emit_g_km * length_km * factor
        return 'emission_weight'

    def _add_monetary_weights(
        self,
        graph: Any,
        mode: str,
        policy: Dict,
    ) -> str:
        """
        Monetary cost weights: fuel/energy cost per edge.

        cost = dist_km × energy_price
             + dist_km × emit_kg_km × carbon_tax
             + dist_km × toll_per_km  (future: congestion charge zone)

        This is the primary weight for the 'cheapest' variant used in
        "lowest cost to decarbonisation" research.
        """
        e_price    = float(policy.get('energy_price_gbp_km',  0.12))
        c_tax      = float(policy.get('carbon_tax_gbp_tco2',  0.0))
        emit_g_km  = _EMISSIONS_G_KM.get(mode, 100)
        emit_kg_km = emit_g_km / 1000.0

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
        self,
        graph: Any,
        mode: str,
        policy: Dict,
    ) -> str:
        """
        Lifecycle CO₂ weights for the 'decarbonisation' route variant.

        Minimises total carbon cost including:
          • Operational emissions (g CO₂/km × grade factor)
          • Embodied carbon amortised per km (vehicle manufacturing)
          • Infrastructure carbon amortised per km (road/rail construction)
          • UK carbon budget trajectory weighting (2030 target = 2× today)

        Carbon budget trajectory (UK CCC 6th Carbon Budget, £/tCO₂):
            2025: £80  2030: £120  2035: £180  2040: £240  2050: £300
        Linearly interpolated for intermediate years.
        """
        from datetime import datetime

        scenario_year = int(policy.get('scenario_year', datetime.now().year))
        _BUDGET = {2025: 80, 2030: 120, 2035: 180, 2040: 240, 2050: 300}
        years   = sorted(_BUDGET)

        if scenario_year <= years[0]:
            c_budget_price = _BUDGET[years[0]]
        elif scenario_year >= years[-1]:
            c_budget_price = _BUDGET[years[-1]]
        else:
            for i in range(len(years) - 1):
                y0, y1 = years[i], years[i + 1]
                if y0 <= scenario_year <= y1:
                    t = (scenario_year - y0) / (y1 - y0)
                    c_budget_price = _BUDGET[y0] + t * (_BUDGET[y1] - _BUDGET[y0])
                    break

        # Embodied carbon (kg CO₂ per km per vehicle) — SMMT / Ricardo lifecycle data.
        _EMBODIED: Dict[str, float] = {
            'car': 0.060, 'ev': 0.085,
            'bus': 0.020, 'tram': 0.015,
            'van_diesel': 0.040, 'van_electric': 0.055,
            'truck_diesel': 0.035, 'truck_electric': 0.045,
            'hgv_diesel': 0.025, 'hgv_electric': 0.035, 'hgv_hydrogen': 0.030,
            'walk': 0.0, 'bike': 0.001, 'e_scooter': 0.002, 'cargo_bike': 0.002,
            'local_train': 0.010, 'intercity_train': 0.008, 'freight_rail': 0.012,
        }
        embodied_kg_km = _EMBODIED.get(mode, 0.030)
        has_elev       = self.graph_manager.has_elevation()
        emit_g_km      = _EMISSIONS_G_KM.get(mode, 100)
        emit_kg_km     = emit_g_km / 1000.0

        for _u, _v, _k, data in graph.edges(keys=True, data=True):
            dist_km = data.get('length', 0.0) / 1000.0

            factor = 1.0
            if has_elev:
                grade = data.get('grade')
                if grade is None and data.get('length', 0) > 0:
                    eu    = graph.nodes[_u].get('elevation', 0)
                    ev    = graph.nodes[_v].get('elevation', 0)
                    grade = (ev - eu) / data['length']
                if grade is not None:
                    if grade > 0:
                        factor = 1.0 + grade * 5.0
                    else:
                        factor = max(0.5, 1.0 + grade * 2.0)
                    factor = max(0.5, min(3.0, factor))

            operational_kg = emit_kg_km * dist_km * factor
            lifecycle_kg   = operational_kg + embodied_kg_km * dist_km
            data['decarb_weight'] = lifecycle_kg * (c_budget_price / 1000.0)

        return 'decarb_weight'

    def _add_scenic_weights(self, graph: Any, mode: str) -> str:
        """
        Prefer quiet, green roads over arterials.

        Lower multiplier = preferred.  Residential streets, paths, and
        cycleways score below 1.0; primary roads and above score above 1.0.
        """
        _S = {
            'path': 0.5, 'footway': 0.5, 'cycleway': 0.5, 'track': 0.5,
            'residential': 0.7, 'living_street': 0.7, 'pedestrian': 0.7,
            'tertiary': 0.9, 'unclassified': 0.9,
            'secondary': 1.2,
        }
        for _u, _v, _k, data in graph.edges(keys=True, data=True):
            hw = data.get('highway', 'residential')
            if isinstance(hw, list):
                hw = hw[0] if hw else 'residential'
            data['scenic_weight'] = data.get('length', 0) * _S.get(hw, 1.5)
        return 'scenic_weight'