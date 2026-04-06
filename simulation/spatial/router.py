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
# 'tram' is NOT in _RAIL_MODES — trams route via GTFS / tram spine, not
# the OpenRailMap mainline topology.
_RAIL_MODES    = frozenset({'local_train', 'intercity_train', 'freight_rail'})
_TRANSIT_MODES = frozenset({'bus', 'ferry_diesel', 'ferry_electric'})

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

        if mode == 'tram':
            return self._compute_gtfs_route(agent_id, origin, dest, mode, policy)

        if mode in _RAIL_MODES:
            return self._compute_intermodal_route(agent_id, origin, dest, mode, policy)

        if mode in _TRANSIT_MODES:
            return self._compute_gtfs_route(agent_id, origin, dest, mode, policy)

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

            if orig_node is None or dest_node is None or orig_node == dest_node:
                return self._get_invalid_route(origin, dest)

            weight_key  = self._apply_generalised_weights(graph, mode, policy)
            route_nodes = nx.shortest_path(graph, orig_node, dest_node, weight=weight_key)
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
    _MAX_ACCESS_KM: float = 5.0

    def _nearest_rail_node(
        self,
        coord: Tuple[float, float],
        rail_graph: Any,
    ) -> Optional[Any]:
        """
        Return the nearest node in the rail graph to (lon, lat) coord.

        NaPTAN-aware snapping
        ---------------------
        When NaPTAN stop data has been loaded (stored on
        graph_manager.naptan_stops by environment_setup.py), we:
          1. Find the nearest NaPTAN rail/metro stop to the agent coord.
          2. Use the NaPTAN platform coordinate as the snap target.
          3. Find the nearest OpenRailMap graph node to that platform.

        This gives better results than snapping directly to OpenRailMap
        nodes, which are often mid-track rather than at the platform edge.
        NaPTAN coordinates come from the DfT's authoritative dataset and
        are accurate to ±5 m for most UK stations.

        Falls back to direct brute-force graph node scan when NaPTAN is
        absent or the nearest NaPTAN stop is beyond 5 km.
        """
        if rail_graph is None:
            return None

        # ── NaPTAN snap (preferred) ───────────────────────────────────────
        naptan_stops = getattr(self.graph_manager, 'naptan_stops', [])
        if naptan_stops:
            try:
                from simulation.spatial.naptan_loader import nearest_naptan_stop
                naptan_hit = nearest_naptan_stop(coord, naptan_stops, max_km=self._MAX_ACCESS_KM)
                if naptan_hit is not None:
                    # Use the NaPTAN platform coordinate as the precision snap target.
                    snap_coord = (naptan_hit.lon, naptan_hit.lat)
                    return self._brute_force_nearest_node(snap_coord, rail_graph)
            except Exception:
                pass   # NaPTAN unavailable — fall through to direct scan

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
        # PATCH: Force trams AND heavy rail onto the physical rail track intermodal router 
        # when GTFS is disabled, preventing them from disappearing.
        if mode in ('tram', 'local_train', 'intercity_train'):
            return self._compute_intermodal_route(agent_id, origin, dest, mode, policy)
        if mode in ('ferry_diesel', 'ferry_electric'):
            return self._get_invalid_route(origin, dest)
        # Buses gracefully fall back to the standard physical drive graph
        return self._compute_road_route(agent_id, origin, dest, mode, policy)

    def _compute_access_leg(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        max_straight_km: float = 3.0,
    ) -> List[Tuple[float, float]]:
        """
        Compute a pedestrian access or egress leg to/from a transit stop.

        Strategy (priority order)
        -------------------------
        1. Walk graph available → route on it using weight='length' (physical
           distance, not hop count — OSMnx BFS default minimises intersections
           which can produce circuitous pedestrian routes).
        2. Walk graph absent AND distance ≤ max_straight_km → interpolated
           straight line (avoids the 200+ waypoint residential squiggle from
           routing on the drive graph via roads pedestrians don't use).
        3. Distance > max_straight_km and walk graph absent → drive graph proxy.
        4. Drive proxy fails → interpolated straight line.
        """
        dist_km = haversine_km(origin, dest)

        G_walk = self.graph_manager.get_graph('walk')
        if G_walk is not None:
            try:
                orig_node = self.graph_manager.get_nearest_node(origin, 'walk')
                dest_node = self.graph_manager.get_nearest_node(dest,   'walk')
                if orig_node and dest_node and orig_node != dest_node:
                    walk_nodes = nx.shortest_path(
                        G_walk, orig_node, dest_node, weight='length'
                    )
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
        drive_result = self._compute_road_route(agent_id, origin, dest, 'car', _DEFAULT_POLICY)
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
                    spine_route = route_via_tram_stops(origin, dest)
                    if spine_route and len(spine_route) > 2:
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
                    return spine_route if spine_route else []
                except Exception:
                    pass
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
                # Tram / ferry: straight stop-to-stop interpolation.
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
        """Prefer quiet / green roads over arterials."""
        _S = {
            'path': 0.5, 'footway': 0.5, 'cycleway': 0.5, 'track': 0.5,
            'residential': 0.7, 'living_street': 0.7, 'pedestrian': 0.7,
            'tertiary': 0.9, 'unclassified': 0.9, 'secondary': 1.2,
        }
        for _u, _v, _k, data in graph.edges(keys=True, data=True):
            hw = data.get('highway', 'residential')
            if isinstance(hw, list):
                hw = hw[0] if hw else 'residential'
            data['scenic_weight'] = data.get('length', 0) * _S.get(hw, 1.5)
        return 'scenic_weight'