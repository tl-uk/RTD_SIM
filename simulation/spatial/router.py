"""
simulation/spatial/router.py

Route computation with generalised cost and intermodal rail transfers.

Architecture
────────────
Two parallel graphs, never merged:
  • Road graph  (OSMnx 'drive')  — existing, unchanged
  • Rail graph  (OpenRailMap)    — sparse, kept in memory as a NetworkX object
                                    loaded once on first rail request

Generalised Cost Formula (per edge)
─────────────────────────────────────
  cost = (time_h × VoT)  +  (dist_km × energy_price)  +  (emissions_kg × carbon_tax)

Where VoT / energy_price / carbon_tax are read from scenario policy context
so that a policy event (carbon tax hike, fuel price spike) immediately shifts
agent route choices without any code change.

Intermodal Transfer Logic
─────────────────────────
For modes that use the rail graph (local_train, intercity_train, freight_rail):
  1. Find nearest Transfer Node on rail graph to agent origin (road→rail snap).
  2. Route agent on drive graph to that Transfer Node (access leg).
  3. Route on rail graph from Transfer Node to nearest station to destination.
  4. Route agent on drive graph from egress station to destination (egress leg).
  5. Concatenate access + rail + egress with a configurable boarding penalty.

The returned route is a flat list of (lon,lat) 2-tuples compatible with all
downstream code — coordinate_utils, visualization, agent state.

For non-rail routeable modes (drive/walk/bike) the existing single-graph
shortest-path logic is preserved unchanged.

Policy integration
──────────────────
Pass a `policy_context` dict to compute_route() with any of:
  value_of_time_gbp_h:  float   (default 10.0)
  energy_price_gbp_km:  float   (default 0.12)
  carbon_tax_gbp_tco2:  float   (default 0.0)
  boarding_penalty_min: float   (default 15.0)

These are populated by the dynamic policy engine when scenarios run.
"""

from __future__ import annotations

import logging
from typing import List, Tuple, Optional, Dict, Any, TYPE_CHECKING

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

# ── Modes that route on the rail graph (not drive) ───────────────────────────
# Add 'tram' so it routes on OpenRailMap tracks when GTFS is disabled
_RAIL_MODES = frozenset({'local_train', 'intercity_train', 'freight_rail', 'tram'})

# ── Modes that route on the GTFS transit graph when available ─────────────────
# When no GTFS graph is loaded these fall back to _compute_road_route (drive
# proxy) so the simulation degrades gracefully rather than crashing.
_TRANSIT_MODES = frozenset({'bus', 'tram', 'ferry_diesel', 'ferry_electric'})

# ── Default policy parameters (overridden per-call by scenario context) ───────
_DEFAULT_POLICY: Dict[str, float] = {
    'value_of_time_gbp_h':  10.0,   # £10/h UK average
    'energy_price_gbp_km':   0.12,   # ~12p/km petrol equivalent
    'carbon_tax_gbp_tco2':   0.0,    # £0 — no carbon tax by default
    'boarding_penalty_min':  15.0,   # 15 min transfer penalty at station
}

# ── Emissions factors (g CO₂/km) — mirrors modes.py for cost weighting ───────
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
    Computes routes and route alternatives using parallel road + rail graphs.

    Strategy:
      • Road agents  → single-graph generalised-cost route on drive/walk/bike.
      • Rail agents  → access leg (drive) + rail leg + egress leg (drive).
      • Abstract modes (ferry/air, per modes.py routeable=False) are handled
        upstream in bdi_planner before compute_route() is called.
    """

    def __init__(self, graph_manager: 'GraphManager', congestion_manager=None):
        self.graph_manager    = graph_manager
        self.congestion_manager = congestion_manager

        # Rail graph loaded lazily on first rail request
        self._rail_graph: Optional[Any] = None
        self._rail_graph_attempted: bool = False

        # ── Mode → OSMnx network type ─────────────────────────────────────────
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
            'tram':            'drive',    # drive proxy until GTFS
            'local_train':     'rail',
            'intercity_train': 'rail',
            'freight_rail':    'rail',
            'ferry_diesel':    'drive',    # drive proxy (abstract in modes.py)
            'ferry_electric':  'drive',
            'flight_domestic': 'drive',
            'flight_electric': 'drive',
        }

        # ── Speed in km/min (used for cost and travel-time estimation) ─────────
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

        Rail modes → intermodal (access + rail + egress).
        All other routeable modes → single-graph road route.

        Returns a flat list of (lon, lat) 2-tuples.
        Falls back to [origin, dest] on any failure.
        """
        if not (is_valid_lonlat(origin) and is_valid_lonlat(dest)):
            logger.error("❌ %s: invalid coords %s → %s", agent_id, origin, dest)
            return []

        if haversine_km(origin, dest) < 0.1:
            return [origin, dest]

        policy = {**_DEFAULT_POLICY, **(policy_context or {})}

        # Tram: prefer GTFS when available, fall back to rail spine
        if mode == 'tram':
            return self._compute_gtfs_route(agent_id, origin, dest, mode, policy)

        if mode in _RAIL_MODES:   # local_train, intercity_train, freight_rail only
            return self._compute_intermodal_route(agent_id, origin, dest, mode, policy)

        # Transit (bus/tram/ferry): GTFS four-leg route when graph loaded,
        # road-graph proxy otherwise.  Headway cost makes infrequent services
        # correctly expensive vs frequent ones in the BDI generalised cost.
        if mode in _TRANSIT_MODES:   # bus, ferry
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
            route = self.compute_route(
                agent_id, origin, dest, mode, policy_context
            )
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
            basic = self.compute_route(
                agent_id, origin, dest, mode, policy_context
            )
            if basic and len(basic) >= 2:
                alternatives.append(RouteAlternative(basic, mode, 'shortest'))

        return alternatives

    # =========================================================================
    # ROAD ROUTING — single-graph, generalised cost
    # =========================================================================

    # def _compute_road_route(
    #     self,
    #     agent_id: str,
    #     origin: Tuple[float, float],
    #     dest: Tuple[float, float],
    #     mode: str,
    #     policy: Dict,
    # ) -> List[Tuple[float, float]]:
    #     """Route on a single OSMnx graph using generalised edge weights."""
    #     network_type = self.mode_network_types.get(mode, 'drive')
    #     graph = self.graph_manager.get_graph(network_type)

    #     if graph is None:
    #         logger.error(
    #             "❌ %s: no graph for mode=%s network=%s; falling back to drive",
    #             agent_id, mode, network_type,
    #         )
    #         network_type = 'drive'
    #         graph = self.graph_manager.get_graph('drive')
    #         if graph is None:
    #             return [origin, dest]

    #     try:
    #         orig_node = self.graph_manager.get_nearest_node(origin, network_type)
    #         dest_node = self.graph_manager.get_nearest_node(dest,   network_type)
    #         if orig_node is None or dest_node is None:
    #             return [origin, dest]
    #         if orig_node == dest_node:
    #             return [origin, dest]

    #         weight_key = self._apply_generalised_weights(graph, mode, policy)
    #         route_nodes = nx.shortest_path(
    #             graph, orig_node, dest_node, weight=weight_key
    #         )
    #         coords = self._extract_geometry(graph, route_nodes)
    #         coords = self._interpolate(coords, max_segment_km=0.05)
    #         logger.info(
    #             "✅ %s: %s (%s) %.1fkm, %d pts",
    #             agent_id, mode, network_type,
    #             route_distance_km(coords), len(coords),
    #         )
    #         return coords

    #     except nx.NetworkXNoPath:
    #         logger.warning("❌ %s: no road path for %s", agent_id, mode)
    #         return [origin, dest]
    #     except Exception as exc:
    #         logger.error("❌ %s: road routing failed: %s", agent_id, exc)
    #         return [origin, dest]

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
        Strictly enforces physical road geometry. Rejects physically impossible routes.
        """
        network_type = self.mode_network_types.get(mode, 'drive')
        graph = self.graph_manager.get_graph(network_type)

        if graph is None:
            logger.warning("❌ %s: Graph '%s' missing. Rejecting route.", agent_id, network_type)
            return self._get_invalid_route(origin, dest)

        try:
            orig_node = self.graph_manager.get_nearest_node(origin, network_type)
            dest_node = self.graph_manager.get_nearest_node(dest,   network_type)
            
            if orig_node is None or dest_node is None or orig_node == dest_node:
                return self._get_invalid_route(origin, dest)

            weight_key = self._apply_generalised_weights(graph, mode, policy)
            
            # Attempt strict directed routing (respecting one-way streets)
            # route_nodes = nx.shortest_path(graph, orig_node, dest_node, weight=weight_key)
            # coords = self._extract_geometry(graph, route_nodes)
            # return self._interpolate(coords, max_segment_km=0.05)

            # Attempt to find the path on the actual road/rail graph
            route_nodes = nx.shortest_path(graph, orig_node, dest_node, weight=weight_key)
            return self._interpolate(self._extract_geometry(graph, route_nodes), max_segment_km=0.05)

        except nx.NetworkXNoPath:
            # CRITICAL: Do NOT return [origin, dest]. 
            # Return an invalid route so the BDI planner knows this mode is impossible.
            logger.warning(f"No physical path for {agent_id} using {mode}")
            return self._get_invalid_route(origin, dest)
            # If directed routing fails (e.g. one-way bridge traps), fall back to undirected.
            # This guarantees the bus stays on the physical road geometry rather than flying over water!
            # try:
            #     G_un = graph.to_undirected()
            #     route_nodes = nx.shortest_path(G_un, orig_node, dest_node, weight=weight_key)
            #     coords = self._extract_geometry(G_un, route_nodes)
            #     return self._interpolate(coords, max_segment_km=0.05)
            # except Exception:
            #     logger.warning("❌ %s: Absolute no physical road path for %s. Rejecting.", agent_id, mode)
            #     # STRICT ECONOMIC REJECTION - Do not draw a straight line!
            #     return self._get_invalid_route(origin, dest)
                
        except Exception as exc:
            logger.error("❌ %s: Road routing failed: %s", agent_id, exc)
            return self._get_invalid_route(origin, dest)

    # =========================================================================
    # RAIL INTERMODAL ROUTING
    # =========================================================================

    def _get_rail_graph(self) -> Optional[Any]:
        """
        Return the rail graph, loading it lazily on first call.

        Priority:
          1. graph_manager already has 'rail' (e.g. loaded by environment_setup)
          2. self._rail_graph cached from previous call
          3. Fetch from OpenRailMap using drive-graph bbox
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
                xs = [d['x'] for _, d in drive.nodes(data=True)]
                ys = [d['y'] for _, d in drive.nodes(data=True)]
                # fetch_rail_graph expects (north, south, east, west)
                bbox = (max(ys), min(ys), max(xs), min(xs))
            else:
                bbox = (56.0, 55.85, -3.05, -3.40)   # Edinburgh fallback

            self._rail_graph = fetch_rail_graph(bbox)

            if self._rail_graph is not None:
                logger.info(
                    "✅ Rail graph: %d nodes, %d edges",
                    len(self._rail_graph.nodes), len(self._rail_graph.edges),
                )
                # Register with graph_manager so visualization can access it
                try:
                    self.graph_manager.graphs['rail'] = self._rail_graph
                except Exception:
                    pass
            else:
                logger.warning(
                    "⚠️  Rail graph fetch returned None — "
                    "rail agents will use straight-line synthetic routes"
                )
        except Exception as exc:
            logger.error("Rail graph load failed: %s", exc)
            self._rail_graph = None

        return self._rail_graph

    # =========================================================================
    # GTFS TRANSIT ROUTING
    # =========================================================================

    def _get_transit_graph(self) -> Optional[Any]:
        """
        Return the GTFS transit graph (bus/tram/ferry stops + service edges).

        The transit graph is never auto-fetched — it must be pre-loaded via
        environment_setup.py:
            env.load_gtfs_graph(feed_path=config.gtfs_feed_path)
        or registered directly:
            env.graph_manager.graphs['transit'] = G_transit

        Returns None when no GTFS data is available so callers fall back
        to the drive-graph proxy gracefully.
        """
        return self.graph_manager.get_graph('transit')
    
    def _get_invalid_route(self, origin: Tuple[float, float], dest: Tuple[float, float]) -> List[Tuple[float, float]]:
        """
        Returns a heavily penalized route to force the BDI planner to reject this mode.
        Used when a transit mode is physically inaccessible (e.g. no tracks nearby).
        By sending the agent 10 degrees off-map, the cost becomes infinite.
        """
        penalty_waypoint = (origin[0] + 10.0, origin[1] + 10.0)
        return []   # callers: `if not route or len(route) < 2: use fallback`

    def _transit_fallback(self, agent_id: str, origin: Tuple[float, float], dest: Tuple[float, float], mode: str, policy: Dict) -> List[Tuple[float, float]]:
        """Clean fallback when GTFS graph is missing or routing fails."""
        if mode == 'tram':
            # Force trams to use the strict physical track infrastructure
            return self._compute_intermodal_route(agent_id, origin, dest, mode, policy)
        elif mode in ('ferry_diesel', 'ferry_electric', 'local_train', 'intercity_train'):
            return self._get_invalid_route(origin, dest)
        else:
            # Bus modes gracefully fall back to the standard physical road network
            return self._compute_road_route(agent_id, origin, dest, mode, policy)

    def _compute_access_leg(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        max_straight_km: float = 3.0,
    ) -> List[Tuple[float, float]]:
        """
        Compute a pedestrian access or egress leg between a trip origin/destination
        and a transit stop or rail station.

        Strategy (in priority order):
          1. Walk graph is loaded → route on it.
          2. Walk graph unavailable AND distance ≤ max_straight_km → return an
             interpolated straight line.  This is more realistic for pedestrian
             access than routing on the drive graph (pedestrians use footpaths,
             shortcuts, cut-throughs that are NOT in the drive graph), and it
             prevents the 200+ waypoint residential-street squiggle that appears
             when the drive graph is used as a walk fallback.
          3. Distance > max_straight_km and walk graph unavailable → drive graph
             (agent is driving to a park-and-ride, not walking).

        Args:
            agent_id:         Used only for logging.
            origin:           (lon, lat) start coord.
            dest:             (lon, lat) end coord (usually a stop/station).
            max_straight_km:  Threshold below which the straight-line strategy
                              is used when the walk graph is absent.

        Returns:
            List of (lon, lat) 2-tuples.
        """
        dist_km = haversine_km(origin, dest)

        # ── Walk graph available ──────────────────────────────────────────────
        G_walk = self.graph_manager.get_graph('walk')
        if G_walk is not None:
            try:
                orig_node = self.graph_manager.get_nearest_node(origin, 'walk')
                dest_node = self.graph_manager.get_nearest_node(dest,   'walk')
                if orig_node and dest_node and orig_node != dest_node:
                    walk_nodes = nx.shortest_path(G_walk, orig_node, dest_node)
                    coords = self._extract_geometry(G_walk, walk_nodes)
                    return self._interpolate(coords, max_segment_km=0.05)
            except Exception:
                pass  # fall through

        # ── Walk graph unavailable — straight line for short legs ─────────────
        if dist_km <= max_straight_km:
            logger.debug(
                "%s: walk graph absent, access leg %.2fkm — using interpolated line",
                agent_id, dist_km,
            )
            return self._interpolate([origin, dest], max_segment_km=0.05)

        # ── Long access leg without walk graph — drive graph as last resort ───
        # If the car route also fails (e.g. agent generated outside the road
        # network bbox), fall back to an interpolated straight line.  This
        # prevents a failed drive route returning [origin, dest] (2 points)
        # from being used as an access leg, which produces dark diagonal lines
        # on the map mislabelled as rail or tram routes.
        logger.debug(
            "%s: walk graph absent, access leg %.2fkm > %.2fkm — drive proxy",
            agent_id, dist_km, max_straight_km,
        )
        drive_result = self._compute_road_route(agent_id, origin, dest, 'car', _DEFAULT_POLICY)
        if len(drive_result) > 2:
            return drive_result
        # Drive proxy failed — use interpolated line as final fallback
        logger.debug(
            "%s: drive proxy failed for access leg (got %d pts) — interpolated line",
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
        Four-leg GTFS transit route:
            walk access → board at nearest stop
            → ride (headway-weighted generalised cost)
            → alight at nearest stop to destination
            → walk egress

        Generalised cost per transit edge:
            gen_cost = (travel_time_h + headway_h/2) × VoT
                     + dist_km × energy_price
                     + dist_km × emit_kg_km × carbon_tax

        The headway/2 term is the expected waiting time (E[wait] = headway/2
        for uniform arrivals) — the critical term that makes 4-minute-frequency
        Edinburgh trams competitive while 60-minute rural buses are not.

        Falls back to _compute_road_route (drive proxy) when no GTFS graph
        is loaded or no stops are within 2km of origin/dest.
        """
        G_transit = self._get_transit_graph()

        if G_transit is None:
            if mode == 'tram':
                logger.debug("%s: no GTFS — using tram spine fallback", agent_id)
                try:
                    from simulation.spatial.rail_spine import route_via_tram_stops
                    spine_route = route_via_tram_stops(origin, dest)
                    if spine_route and len(spine_route) > 2:
                        realistic_route = []
                        for i in range(len(spine_route) - 1):
                            leg = self._compute_road_route(agent_id, spine_route[i], spine_route[i+1], 'car', policy)
                            if leg and len(leg) > 1:
                                realistic_route.extend(leg[:-1])
                            else:
                                realistic_route.append(spine_route[i])
                        realistic_route.append(spine_route[-1])
                        return realistic_route
                    return spine_route if spine_route else [origin, dest]
                except Exception:
                    pass
            
            # Fallback for buses/ferries
            # return self._compute_road_route(agent_id, origin, dest, mode, policy)
            return self._transit_fallback(agent_id, origin, dest, mode, policy)

        try:
            from simulation.gtfs.gtfs_graph import GTFSGraph, _haversine_m
        except ImportError:
            # return self._compute_road_route(agent_id, origin, dest, mode, policy)
            return self._transit_fallback(agent_id, origin, dest, mode, policy)

        builder = GTFSGraph(None)

        # ── Snap to nearest stops ─────────────────────────────────────────
        # For tram, BODS encodes Edinburgh Trams as route_type=0 → 'local_train'.
        # Try 'tram' first (correct encoding), then 'local_train' (BODS encoding).
        # No None fallback — mode_filter=None finds bus stops ('6200...' ATCO codes)
        # in Edinburgh, which are cheaper in gen_cost due to higher frequency, so
        # shortest_path routes across the entire bus network instead of 2 tram stops.
        if mode == 'tram':
            _tram_filters: list = ['tram', 'local_train']
            _tram_catchment: int = 5000  # 5km — tram stops can be far apart
            origin_stop = dest_stop = None
            for mf in _tram_filters:
                origin_stop = builder.nearest_stop(
                    G_transit, origin, mode_filter=mf, max_distance_m=_tram_catchment
                )
                dest_stop = builder.nearest_stop(
                    G_transit, dest,   mode_filter=mf, max_distance_m=_tram_catchment
                )
                if origin_stop and dest_stop and origin_stop != dest_stop:
                    logger.debug(
                        "%s: tram GTFS snap via mode_filter=%s (%s → %s)",
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

        if origin_stop is None or dest_stop is None:
            logger.debug(
                "%s: no GTFS stop within catchment for %s — transit fallback",
                agent_id, mode,
            )
            return self._transit_fallback(agent_id, origin, dest, mode, policy)

        if origin_stop == dest_stop:
            return self._transit_fallback(agent_id, origin, dest, mode, policy)

        # ── Allowed mode families for gen_cost masking ────────────────────
        # The GTFS transit graph has ALL service modes mixed together.  Bus
        # edges have lower gen_cost than tram edges (buses are more frequent
        # → smaller headway_h penalty).  Without masking, nx.shortest_path
        # routes tram trips via bus edges, producing 20–43 stop detours.
        # Set gen_cost=inf for edges outside the requested mode family so the
        # path is forced to stay on the correct service type.
        # Transfer edges (mode='walk') are always allowed — they are dead-end
        # stubs in G_transit (terminal walk-graph nodes) and can't form a path.
        _TRAM_MODES  = frozenset({'tram', 'local_train'})
        _RAIL_MODES  = frozenset({'local_train', 'intercity_train', 'rail', 'freight_rail'})
        _BUS_MODES   = frozenset({'bus'})
        if mode == 'tram':
            _allowed_modes = _TRAM_MODES
        elif mode in ('local_train', 'intercity_train'):
            _allowed_modes = _RAIL_MODES
        elif mode == 'bus':
            _allowed_modes = _BUS_MODES
        else:
            _allowed_modes = frozenset({mode})

        # ── Apply headway-weighted generalised cost to transit edges ──────
        vot     = float(policy.get('value_of_time_gbp_h',  10.0))
        e_price = float(policy.get('energy_price_gbp_km',   0.12))
        c_tax   = float(policy.get('carbon_tax_gbp_tco2',   0.0))

        for u, v, key, data in G_transit.edges(keys=True, data=True):
            edge_mode = data.get('mode', 'bus')
            # Transfer / walk edges are dead-ends; give them high cost so they
            # don't form part of the in-service path but don't cause errors.
            if edge_mode == 'walk' or data.get('highway') == 'transfer':
                data['gen_cost'] = 9999.0
                continue
            # Block edges of wrong service family
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

        # ── Route on transit graph ────────────────────────────────────────
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

        # ── Extract geometry from shape_coords ────────────────────────────
        # ── Extract geometry from shape_coords ────────────────────────────
        transit_coords: List[Tuple[float, float]] = []
        for i in range(len(transit_nodes) - 1):
            u_node = transit_nodes[i]
            v_node = transit_nodes[i + 1]
            edge_map = G_transit.get_edge_data(u_node, v_node)
            
            shape = []
            if edge_map:
                first_key = next(iter(edge_map))
                shape = edge_map[first_key].get('shape_coords', [])

            if shape and len(shape) > 2:
                transit_coords.extend(shape if i == 0 else shape[1:])
            else:
                # Shape missing. Map buses to the road, but connect-the-dots for Trams/Ferries.
                u_x, u_y = float(G_transit.nodes[u_node].get('x', 0)), float(G_transit.nodes[u_node].get('y', 0))
                v_x, v_y = float(G_transit.nodes[v_node].get('x', 0)), float(G_transit.nodes[v_node].get('y', 0))
                
                if mode in ('bus', 'van_electric', 'van_diesel'):
                    leg = self._compute_road_route(agent_id, (u_x, u_y), (v_x, v_y), 'car', policy)
                    if leg and len(leg) > 1:
                        transit_coords.extend(leg if i == 0 else leg[1:])
                    else:
                        if i == 0: transit_coords.append((u_x, u_y))
                        transit_coords.append((v_x, v_y))
                else:
                    if i == 0: transit_coords.append((u_x, u_y))
                    transit_coords.append((v_x, v_y))

        if not transit_coords:
            return self._transit_fallback(agent_id, origin, dest, mode, policy)

        # ── Access leg (walk to first stop) ───────────────────────────────
        first_d = G_transit.nodes.get(origin_stop, {})
        first_coord = (float(first_d.get('x', origin[0])), float(first_d.get('y', origin[1])))
        access_leg = self._compute_access_leg(agent_id + '_access', origin, first_coord)

        # ── Egress leg (walk from last stop) ──────────────────────────────
        last_d = G_transit.nodes.get(dest_stop, {})
        last_coord = (float(last_d.get('x', dest[0])), float(last_d.get('y', dest[1])))
        egress_leg = self._compute_access_leg(agent_id + '_egress', last_coord, dest)

        # ── Stitch ────────────────────────────────────────────────────────
        full_route: List[Tuple[float, float]] = (
            (access_leg[:-1] if access_leg else [])
            + transit_coords
            + (egress_leg[1:] if len(egress_leg) > 1 else [])
        )

        if len(full_route) < 2:
            full_route = [origin, dest]

        from simulation.spatial.coordinate_utils import route_distance_km as _rdkm
        logger.info(
            "✅ %s: GTFS %s %.1fkm (%d stops, %d pts)",
            agent_id, mode, _rdkm(full_route), len(transit_nodes), len(full_route),
        )
        return full_route


    def _nearest_rail_node(
        self,
        coord: Tuple[float, float],
        rail_graph: Any,
    ) -> Optional[int]:
        """
        Brute-force nearest node on the rail graph to (lon, lat) coord.

        For the hardcoded spine graph (string CRS node IDs) this also
        consults the NaPTAN bridge so that the 25-station spine can be
        augmented by live DfT data when available.
        """
        if rail_graph is None:
            return None
        lon, lat = coord
        best_node = None
        best_dist = float('inf')
        for node, data in rail_graph.nodes(data=True):
            nlon = float(data.get('x', data.get('lon', 0)))
            nlat = float(data.get('y', data.get('lat', 0)))
            d = haversine_km((lon, lat), (nlon, nlat))
            if d < best_dist:
                best_dist = d
                best_node = node
        return best_node

    def _snap_to_transfer_node(
        self,
        coord: Tuple[float, float],
        rail_graph: Any,
    ) -> Tuple[Optional[int], Tuple[float, float]]:
        """
        Return (graph_node_id, station_coord) for the nearest transfer node.

        Strategy:
          1. Try NaPTAN bridge (live DfT data, ~2,500 UK stations).
          2. If NaPTAN lookup finds a station that exists in the rail graph,
             return that node directly.
          3. Fall back to brute-force nearest-node on the rail graph.

        This ensures that when the full OpenRailMap graph is loaded, the
        agent snaps to the correct node even if its coordinates differ
        slightly from the NaPTAN dataset.
        """
        # ── Attempt NaPTAN snap ───────────────────────────────────────────
        try:
            from simulation.spatial.rail_spine import nearest_transfer_node
            node_info = nearest_transfer_node(coord, max_km=30.0)
            if node_info and rail_graph is not None:
                # Try to find this station in the graph by CRS code or proximity
                crs = node_info.get('crs', '')
                if crs and crs in rail_graph.nodes:
                    nd = rail_graph.nodes[crs]
                    return (crs, (float(nd.get('x', 0)), float(nd.get('y', 0))))
                # Proximity match if CRS not in graph
                nlon, nlat = node_info['lon'], node_info['lat']
                snap_node = self._nearest_rail_node((nlon, nlat), rail_graph)
                if snap_node is not None:
                    nd = rail_graph.nodes[snap_node]
                    return (snap_node,
                            (float(nd.get('x', 0)), float(nd.get('y', 0))))
        except Exception:
            pass  # NaPTAN unavailable — fall through to brute-force

        # ── Brute-force fallback ──────────────────────────────────────────
        node = self._nearest_rail_node(coord, rail_graph)
        if node is None:
            return (None, coord)
        nd = rail_graph.nodes[node]
        return (node, (float(nd.get('x', 0)), float(nd.get('y', 0))))
    

    # def _compute_intermodal_route(
    #     self,
    #     agent_id: str,
    #     origin: Tuple[float, float],
    #     dest: Tuple[float, float],
    #     mode: str,
    #     policy: Dict,
    # ) -> List[Tuple[float, float]]:
    #     """
    #     Three-leg intermodal route: access (road) → rail → egress (road).

    #     Transfer penalty is encoded in policy['boarding_penalty_min'].
    #     The penalty inflates the effective distance of the access leg so the
    #     cost function discourages rail for very short trips where boarding
    #     overhead makes it non-competitive.  It does NOT insert fake waypoints.

    #     Falls back to synthetic straight-line route if rail graph unavailable.
    #     """
    #     rail_graph = self._get_rail_graph()

    #     if rail_graph is None:
    #         # Spine fallback: route via hardcoded station waypoints so rail
    #         # agents travel through real station locations rather than a bare
    #         # straight line across the map (including over water/hills).
    #         logger.debug(
    #             "%s: rail graph unavailable — spine station fallback for %s",
    #             agent_id, mode,
    #         )
    #         try:
    #             from simulation.spatial.rail_spine import route_via_stations
    #             spine_route = route_via_stations(origin, dest, mode)
    #             if spine_route and len(spine_route) > 2:
    #                 realistic_route = []
    #                 for i in range(len(spine_route) - 1):
    #                     # Use the car router to map the rail path to the physical landscape
    #                     leg = self._compute_road_route(agent_id, spine_route[i], spine_route[i+1], 'car', policy)
    #                     if leg and len(leg) > 1:
    #                         realistic_route.extend(leg[:-1])
    #                     else:
    #                         realistic_route.append(spine_route[i])
    #                 realistic_route.append(spine_route[-1])
                    
    #                 logger.info("✅ %s: %s spine fallback mapped to road geometry (%d pts)", 
    #                             agent_id, mode, len(realistic_route))
    #                 return realistic_route
                
    #             return spine_route if spine_route else [origin, dest]
                
    #         except Exception as exc:
    #             logger.warning("%s: spine fallback failed: %s", agent_id, exc)
    #             return [origin, dest]

    #     # ── Snap to rail transfer nodes ───────────────────────────────────────
    #     orig_rail_node = self._nearest_rail_node(origin, rail_graph)
    #     dest_rail_node = self._nearest_rail_node(dest,   rail_graph)

    #     if orig_rail_node is None or dest_rail_node is None:
    #         logger.warning(
    #             "%s: rail snap failed for %s — synthetic fallback",
    #             agent_id, mode,
    #         )
    #         return [origin, dest]

    #     orig_rail_coord = (
    #         float(rail_graph.nodes[orig_rail_node].get('x', 0)),
    #         float(rail_graph.nodes[orig_rail_node].get('y', 0)),
    #     )
    #     dest_rail_coord = (
    #         float(rail_graph.nodes[dest_rail_node].get('x', 0)),
    #         float(rail_graph.nodes[dest_rail_node].get('y', 0)),
    #     )

    #     # ── Access leg: origin → origin rail station (drive) ──────────────────
    #     access_leg = self._compute_road_route(
    #         agent_id + '_access', origin, orig_rail_coord, 'car', policy
    #     )

    #     # ── Rail leg: origin station → destination station ────────────────────
    #     try:
    #         if orig_rail_node == dest_rail_node:
    #             rail_coords = [orig_rail_coord, dest_rail_coord]
    #         else:
    #             rail_weight_key = self._apply_generalised_weights(
    #                 rail_graph, mode, policy
    #             )
    #             rail_nodes = nx.shortest_path(
    #                 rail_graph,
    #                 orig_rail_node,
    #                 dest_rail_node,
    #                 weight=rail_weight_key,
    #             )
    #             rail_coords = self._extract_geometry(rail_graph, rail_nodes)
                
    #             # VISUAL FIX: If OpenRailMap returns raw nodes with poor curves (mostly straight lines),
    #             # map the segments to the physical road network so it bends with the terrain!
    #             if len(rail_coords) < len(rail_nodes) * 1.5:
    #                 realistic_route = []
    #                 for i in range(len(rail_nodes) - 1):
    #                     leg_u = (float(rail_graph.nodes[rail_nodes[i]]['x']), float(rail_graph.nodes[rail_nodes[i]]['y']))
    #                     leg_v = (float(rail_graph.nodes[rail_nodes[i+1]]['x']), float(rail_graph.nodes[rail_nodes[i+1]]['y']))
    #                     leg = self._compute_road_route(agent_id, leg_u, leg_v, 'car', policy)
    #                     if leg and len(leg) > 1:
    #                         realistic_route.extend(leg[:-1])
    #                     else:
    #                         realistic_route.append(leg_u)
    #                 realistic_route.append((float(rail_graph.nodes[rail_nodes[-1]]['x']), float(rail_graph.nodes[rail_nodes[-1]]['y'])))
    #                 rail_coords = realistic_route

    #             rail_coords = self._interpolate(rail_coords, max_segment_km=0.2)
                
    #     except nx.NetworkXNoPath:
    #         logger.warning(
    #             "%s: no rail path %s→%s on OpenRailMap, mapping to road proxy",
    #             agent_id, orig_rail_node, dest_rail_node,
    #         )
    #         # VISUAL FIX 2: The rail graph is fragmented. Route the train on the road 
    #         # network so it physically bends with the terrain!
    #         leg = self._compute_road_route(agent_id, orig_rail_coord, dest_rail_coord, 'car', policy)
    #         rail_coords = leg if leg and len(leg) > 1 else [orig_rail_coord, dest_rail_coord]
            
    #     except Exception as exc:
    #         logger.error("%s: rail leg failed: %s, mapping to road proxy", agent_id, exc)
    #         leg = self._compute_road_route(agent_id, orig_rail_coord, dest_rail_coord, 'car', policy)
    #         rail_coords = leg if leg and len(leg) > 1 else [orig_rail_coord, dest_rail_coord]

    #     # ── Egress leg: destination station → destination (drive) ─────────────
    #     egress_leg = self._compute_road_route(
    #         agent_id + '_egress', dest_rail_coord, dest, 'car', policy
    #     )

    #     # ── Stitch legs (remove duplicated boundary points) ───────────────────
        # full_route: List[Tuple[float, float]] = (
        #     (access_leg[:-1] if access_leg else [])
        #     + rail_coords
        #     + (egress_leg[1:] if len(egress_leg) > 1 else [])
        # )

        # if len(full_route) < 2:
        #     full_route = [origin, dest]

        # access_km = route_distance_km(access_leg)
        # rail_km   = route_distance_km(rail_coords)
        # egress_km = route_distance_km(egress_leg)
        # board_km  = (
        #     policy['boarding_penalty_min'] / 60.0
        #     * self.speeds_km_min.get(mode, 1.33)
        # )

        # logger.info(
        #     "✅ %s: %s intermodal %.1fkm "
        #     "(access %.1f + board-penalty %.1f + rail %.1f + egress %.1f)",
        #     agent_id, mode,
        #     access_km + board_km + rail_km + egress_km,
        #     access_km, board_km, rail_km, egress_km,
        # )
    #     return full_route

    # Maximum credible walk-to-station distance in km.
    # If _nearest_rail_node snaps to a node further than this the OpenRailMap
    # graph is too sparse / fragmented for this area — use the spine instead.
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

        Guards that trigger spine fallback (avoid residential-street rat-runs):
          1. Rail graph unavailable.
          2. Both ends snap to the same rail node (degenerate rail leg).
          3. Nearest rail node is >_MAX_ACCESS_KM away (sparse/fragmented graph).
        """
        rail_graph = self._get_rail_graph()

        if rail_graph is None:
            return self._get_invalid_route(origin, dest)
            # try:
            #     from simulation.spatial.rail_spine import route_via_stations
            #     spine_route = route_via_stations(origin, dest, mode)
            #     return spine_route if spine_route else self._get_invalid_route(origin, dest)
            # except Exception:
            #     return self._get_invalid_route(origin, dest)

        # ── Snap to rail transfer nodes ───────────────────────────────────────
        orig_rail_node = self._nearest_rail_node(origin, rail_graph)
        dest_rail_node = self._nearest_rail_node(dest,   rail_graph)

        # if orig_rail_node is None or dest_rail_node is None:
        if orig_rail_node is None or dest_rail_node is None or orig_rail_node == dest_rail_node:
            return self._get_invalid_route(origin, dest)
        
        orig_rail_coord = (float(rail_graph.nodes[orig_rail_node].get('x', 0)), 
                           float(rail_graph.nodes[orig_rail_node].get('y', 0)))
        dest_rail_coord = (float(rail_graph.nodes[dest_rail_node].get('x', 0)), 
                           float(rail_graph.nodes[dest_rail_node].get('y', 0)))

        # ── Guard 1: both ends snap to the same rail node ────────────────────
        # The rail leg collapses to [station, station] and the full route
        # becomes two OSM walk legs — producing 1000+ residential-street
        # waypoints mislabelled as "Intercity Train".
        # if orig_rail_node == dest_rail_node:
        #     try:
        #         from simulation.spatial.rail_spine import route_via_stations
        #         spine_route = route_via_stations(origin, dest, mode)
        #         if spine_route and len(spine_route) >= 2:
        #             return spine_route
        #     except Exception:
        #         pass
        #     return self._get_invalid_route(origin, dest)

        # Guard: Reject if the nearest station is too far (e.g. graph is fragmented)
        from simulation.spatial.coordinate_utils import haversine_km
        if haversine_km(origin, orig_rail_coord) > 5.0 or haversine_km(dest_rail_coord, dest) > 5.0:
            return self._get_invalid_route(origin, dest)
        
        # ── Guard 2: nearest rail node is unreasonably far ───────────────────
        # A snap distance >_MAX_ACCESS_KM means the OpenRailMap graph has no
        # nodes near the agent — walking 5+ km to a "station" then routing via
        # road-network geometry produces the 1000+ waypoint residential tangle
        # visible on the map as "Intercity Train" squiggles through suburbs.

        # from simulation.spatial.coordinate_utils import haversine_km
        # access_dist_km  = haversine_km(origin, orig_rail_coord)
        # egress_dist_km  = haversine_km(dest_rail_coord, dest)
        # journey_dist_km = haversine_km(origin, dest)

        # Access/Egress (Walk to station)
        access_leg = self._compute_access_leg(agent_id + '_access', origin, orig_rail_coord)
        egress_leg = self._compute_access_leg(agent_id + '_egress', dest_rail_coord, dest)

        # if (access_dist_km > self._MAX_ACCESS_KM
        #         or egress_dist_km > self._MAX_ACCESS_KM
        #         # Also catch the case where rail snap distance exceeds the
        #         # whole trip (both origin+dest are closer to each other than
        #         # to any rail node — short local trip mislabelled as rail).
        #         or access_dist_km + egress_dist_km > journey_dist_km * 1.5):
        #     logger.debug(
        #         "%s: %s snap distances too large (access %.1fkm, egress %.1fkm, "
        #         "journey %.1fkm) — spine fallback",
        #         agent_id, mode, access_dist_km, egress_dist_km, journey_dist_km,
        #     )
        #     try:
        #         from simulation.spatial.rail_spine import route_via_stations
        #         spine_route = route_via_stations(origin, dest, mode)
        #         if spine_route and len(spine_route) >= 2:
        #             return spine_route
        #     except Exception:
        #         pass
        #     return self._get_invalid_route(origin, dest)

        # ── Access leg (walk/interpolated) ───────────────────────────────────
        # _compute_access_leg tries walk graph first, falls back to interpolated
        # straight line for short legs, and drive graph for long ones.  It
        # avoids the 200+ waypoint residential squiggle from _compute_road_route
        # ('walk') which always fails here because no walk graph is loaded.
        # access_leg = self._compute_access_leg(agent_id + '_access', origin, orig_rail_coord)

        # ── Guard 3: reject routes with unroutable long access/egress legs ───
        # If _compute_access_leg returned only 2 points for a long leg, it means
        # the drive proxy failed (agent outside road network bbox) and we got a
        # bare [origin, station] 2-point line.  _interpolate then turns that into
        # ~100 evenly-spaced points along a straight diagonal, e.g. eco_warrior
        # tourist_scenic_rail with 103 waypoints but all in a straight line.
        # Reject the route here so the BDI planner falls back to another mode.
        # _access_dist_km = haversine_km(origin, orig_rail_coord)
        # if len(access_leg) <= 2 and _access_dist_km > 1.0:
        #     logger.debug(
        #         "%s: %s access leg unroutable (%.1fkm, %d pts) — invalid route",
        #         agent_id, mode, _access_dist_km, len(access_leg),
        #     )
        #     return self._get_invalid_route(origin, dest)

        # ── Rail leg ──────────────────────────────────────────────────────────
        try:
            rail_weight_key = self._apply_generalised_weights(rail_graph, mode, policy)
            rail_nodes = nx.shortest_path(rail_graph, orig_rail_node, dest_rail_node, weight=rail_weight_key)
            rail_coords = self._extract_geometry(rail_graph, rail_nodes)

            rail_coords = self._interpolate(rail_coords, max_segment_km=0.2)

        except nx.NetworkXNoPath:
            logger.warning("❌ %s: Track topology fragmented between %s and %s.", agent_id, orig_rail_node, dest_rail_node)
            return self._get_invalid_route(origin, dest)
        except Exception as exc:
            logger.error("❌ %s: Rail routing failed: %s", agent_id, exc)
            return self._get_invalid_route(origin, dest)

            # ── Spine geometry check ──────────────────────────────────────────
            # The 41-station spine has no Shapely edge geometry.  _extract_geometry
            # returns exactly one coordinate per node, so len(rail_coords) == len(rail_nodes).
            # Interpolating those bare node coordinates at 0.2km spacing creates a
            # smooth straight diagonal labelled "Intercity Train" — visually wrong.
            # Fix: route each consecutive station pair on the drive graph instead.
            # Roads in Scotland run parallel to rail corridors, so the result is
            # geographically sensible even if not perfectly on the tracks.
            # PATCH: Only apply road-mapping if the graph lacks OSM IDs (i.e. it is the spine). 
            # Real OSM rail tracks will now retain their true geometry.
            # is_spine = not any('osmid' in d for u, v, d in rail_graph.edges(data=True))
            # if is_spine and len(rail_coords) <= len(rail_nodes):
            #     road_routed: List[Tuple[float, float]] = []
            #     for idx in range(len(rail_nodes) - 1):
            #         u_c = (float(rail_graph.nodes[rail_nodes[idx]].get('x', 0)),
            #                float(rail_graph.nodes[rail_nodes[idx]].get('y', 0)))
            #         v_c = (float(rail_graph.nodes[rail_nodes[idx + 1]].get('x', 0)),
            #                float(rail_graph.nodes[rail_nodes[idx + 1]].get('y', 0)))
            #         seg = self._compute_road_route(
            #             agent_id + f'_rail{idx}', u_c, v_c, 'car', policy
            #         )
            #         if seg and len(seg) > 2:
            #             road_routed.extend(seg[:-1] if idx < len(rail_nodes) - 2 else seg)
            #         else:
            #             if not road_routed:
            #                 road_routed.append(u_c)
            #             road_routed.append(v_c)
            #     if len(road_routed) > 2:
            #         rail_coords = road_routed
            #     else:
            #         rail_coords = self._interpolate(rail_coords, max_segment_km=0.2)
            # else:
            #     # OSMnx graph returned real edge geometry — keep it!
            #     rail_coords = self._interpolate(rail_coords, max_segment_km=0.2)

            # if len(rail_coords) <= len(rail_nodes):
            #     road_routed: List[Tuple[float, float]] = []
            #     for idx in range(len(rail_nodes) - 1):
            #         u_c = (float(rail_graph.nodes[rail_nodes[idx]].get('x', 0)),
            #                float(rail_graph.nodes[rail_nodes[idx]].get('y', 0)))
            #         v_c = (float(rail_graph.nodes[rail_nodes[idx + 1]].get('x', 0)),
            #                float(rail_graph.nodes[rail_nodes[idx + 1]].get('y', 0)))
            #         seg = self._compute_road_route(
            #             agent_id + f'_rail{idx}', u_c, v_c, 'car', policy
            #         )
            #         if seg and len(seg) > 2:
            #             # Exclude last point on intermediate segments to avoid duplication
            #             road_routed.extend(seg[:-1] if idx < len(rail_nodes) - 2 else seg)
            #         else:
            #             # Drive routing failed for this segment — keep node coord
            #             if not road_routed:
            #                 road_routed.append(u_c)
            #             road_routed.append(v_c)
            #     if len(road_routed) > 2:
            #         rail_coords = road_routed
            #     else:
            #         # Drive routing completely failed — interpolate as last resort
            #         rail_coords = self._interpolate(rail_coords, max_segment_km=0.2)
            # else:
            #     # OSMnx graph returned real edge geometry — interpolate normally
            #     rail_coords = self._interpolate(rail_coords, max_segment_km=0.2)

        # except nx.NetworkXNoPath:
        #     logger.debug("%s: no rail path on OpenRailMap — road-proxy station-to-station", agent_id)
        #     rail_coords = self._compute_road_route(
        #         agent_id + '_railleg', orig_rail_coord, dest_rail_coord, 'car', policy
        #     )
        #     if len(rail_coords) <= 2:
        #         try:
        #             from simulation.spatial.rail_spine import route_via_stations
        #             rail_coords = route_via_stations(orig_rail_coord, dest_rail_coord, mode)
        #             if not rail_coords or len(rail_coords) < 2:
        #                 rail_coords = self._interpolate([orig_rail_coord, dest_rail_coord], max_segment_km=0.2)
        #         except Exception:
        #             rail_coords = self._interpolate([orig_rail_coord, dest_rail_coord], max_segment_km=0.2)
        # except Exception:
        #     try:
        #         from simulation.spatial.rail_spine import route_via_stations
        #         rail_coords = route_via_stations(orig_rail_coord, dest_rail_coord, mode)
        #         if not rail_coords or len(rail_coords) < 2:
        #             return self._get_invalid_route(origin, dest)
        #     except Exception:
        #         return self._get_invalid_route(origin, dest)

        # ── Egress leg (walk/interpolated) ────────────────────────────────────
        # egress_leg = self._compute_access_leg(agent_id + '_egress', dest_rail_coord, dest)

        # _egress_dist_km = haversine_km(dest_rail_coord, dest)
        # if len(egress_leg) <= 2 and _egress_dist_km > 1.0:
        #     logger.debug(
        #         "%s: %s egress leg unroutable (%.1fkm, %d pts) — invalid route",
        #         agent_id, mode, _egress_dist_km, len(egress_leg),
        #     )
        #     return self._get_invalid_route(origin, dest)

        # ── Stitch legs (remove duplicated boundary points) ───────────────────
        full_route: List[Tuple[float, float]] = (
            (access_leg[:-1] if access_leg else [])
            + rail_coords
            + (egress_leg[1:] if len(egress_leg) > 1 else [])
        )

        # if len(full_route) < 2:
        #     full_route = [origin, dest]

        # access_km = route_distance_km(access_leg)
        # rail_km   = route_distance_km(rail_coords)
        # egress_km = route_distance_km(egress_leg)
        # board_km  = (
        #     policy['boarding_penalty_min'] / 60.0
        #     * self.speeds_km_min.get(mode, 1.33)
        # )

        # logger.info(
        #     "✅ %s: %s intermodal %.1fkm "
        #     "(access %.1f + board-penalty %.1f + rail %.1f + egress %.1f)",
        #     agent_id, mode,
        #     access_km + board_km + rail_km + egress_km,
        #     access_km, board_km, rail_km, egress_km,
        # )


        return full_route if len(full_route) >= 2 else self._get_invalid_route(origin, dest)
    

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

        Recomputed every call so policy changes take effect immediately.
        Returns the edge attribute name used for nx.shortest_path weight.
        """
        vot     = float(policy.get('value_of_time_gbp_h',  10.0))
        e_price = float(policy.get('energy_price_gbp_km',   0.12))
        c_tax   = float(policy.get('carbon_tax_gbp_tco2',   0.0))

        speed_km_h  = self.speeds_km_min.get(mode, 0.5) * 60.0
        emit_kg_km  = _EMISSIONS_G_KM.get(mode, 100) / 1000.0

        # Check if we are operating on the rail graph
        is_rail_graph = graph.graph.get('name') == 'rail'

        for u, v, key, data in graph.edges(keys=True, data=True):
            dist_km = data.get('length', 0.0) / 1000.0

            # Congestion multiplier on travel time
            if self.congestion_manager is not None:
                try:
                    cong = self.congestion_manager.get_congestion_factor(u, v, key)
                except Exception:
                    cong = 1.0
            else:
                cong = 1.0

            time_h = (dist_km / max(speed_km_h, 0.1)) * cong

            data['gen_cost'] = (
                time_h  * vot
                + dist_km * e_price
                + dist_km * emit_kg_km * c_tax
            )

            if is_rail_graph:
                rw = data.get('railway', '')
                if isinstance(rw, list):
                    rw = rw[0]
                if mode == 'tram' and rw not in ('tram', 'light_rail', 'subway'):
                    data['gen_cost'] = float('inf')      # overwrite in-place
                elif mode in ('local_train', 'intercity_train', 'freight_rail') and rw in ('tram', 'light_rail'):
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
        """Extract (lon, lat) 2-tuples from an ordered list of graph nodes."""
        coords: List[Tuple[float, float]] = []
        for i in range(len(route_nodes) - 1):
            u, v = route_nodes[i], route_nodes[i + 1]
            if i == 0:
                coords.append(
                    (float(graph.nodes[u]['x']), float(graph.nodes[u]['y']))
                )
            edge_dict = graph.get_edge_data(u, v) or {}
            edge_data = ( # pick the edge with the best geometry, falling back to shortest:
                next((d for d in edge_dict.values() if 'geometry' in d), None)
                or next(iter(edge_dict.values()), None)
            )
            if edge_data and isinstance(edge_data, dict) and 0 in edge_data:
                edge_data = edge_data[0]
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
        """Insert intermediate points for smooth visualization."""
        if len(coords) < 2:
            return coords
        out = [coords[0]]
        for i in range(len(coords) - 1):
            p1, p2 = coords[i], coords[i + 1]
            dist = haversine_km(p1, p2)
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
          generalised / shortest — minimum generalised cost (time×VoT + dist×energy + emissions×carbon_tax)
          fastest                — minimum travel time
          safest                 — minimum risk for active / vulnerable modes
          greenest               — minimum operational CO₂ (gradient-aware if elevation available)
          cheapest               — minimum monetary cost (fuel + fares); primary research metric for
                                   "lowest cost to decarbonisation" analysis
          decarbonisation        — minimum lifecycle CO₂ weighted by UK carbon budget trajectory;
                                   used for resilience-to-decarbonisation research
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
        graph = self.graph_manager.get_graph(network_type)
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

            route_nodes = nx.shortest_path(
                graph, orig_node, dest_node, weight=weight_key
            )
            coords = self._extract_geometry(graph, route_nodes)
            return self._interpolate(coords, max_segment_km=0.05)

        except nx.NetworkXNoPath:
            return []
        except Exception as exc:
            logger.warning("%s: variant %s failed: %s", agent_id, variant, exc)
            return []

    # =========================================================================
    # WEIGHT HELPERS
    # =========================================================================

    def _add_time_weights(self, graph: Any, mode: str) -> str:
        speed_m_min = self.speeds_km_min.get(mode, 0.5) * 1000
        for u, v, key, data in graph.edges(keys=True, data=True):
            length = data.get('length', 0)
            base = length / max(speed_m_min, 1.0)
            if self.congestion_manager is not None:
                try:
                    base *= self.congestion_manager.get_congestion_factor(u, v, key)
                except Exception:
                    pass
            data['time_weight'] = base
        return 'time_weight'

    def _add_safety_weights(self, graph: Any, mode: str) -> str:
        _RISK = {
            'motorway': 100, 'motorway_link': 100, 'trunk': 50, 'trunk_link': 50,
            'primary': 5, 'primary_link': 5, 'secondary': 2, 'secondary_link': 2,
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

        Uses `grade` edge attribute when available (populated by
        ox.add_edge_grades after UTM projection).  Falls back to elevation
        node-pair difference when grade is absent, and to flat-terrain when
        elevation is absent.

        True grade formula:
          grade = Δelevation_m / length_m   (dimensionless, signed)
          penalty_factor = 1 + max(0, grade) × 5  (uphill burns more fuel)
          recovery_factor = max(0.5, 1 + grade × 2)  (downhill saves some)
        """
        has_elev = self.graph_manager.has_elevation()
        emit_g_km = _EMISSIONS_G_KM.get(mode, 100)
        zero_emit = emit_g_km == 0

        for _u, _v, _k, data in graph.edges(keys=True, data=True):
            length_m = data.get('length', 0.0)
            length_km = length_m / 1000.0

            if zero_emit:
                # Zero-emission modes: weight by time only (to prefer faster edges)
                data['emission_weight'] = length_m / max(
                    self.speeds_km_min.get(mode, 0.5) * 1000, 1.0
                )
                continue

            factor = 1.0
            if has_elev:
                # Prefer ox.add_edge_grades() result ('grade' attribute, dimensionless)
                grade = data.get('grade', None)
                if grade is None and length_m > 0:
                    # Fallback: derive grade from node elevations
                    eu = graph.nodes[_u].get('elevation', 0)
                    ev = graph.nodes[_v].get('elevation', 0)
                    grade = (ev - eu) / length_m  # dimensionless true grade

                if grade is not None:
                    if grade > 0:
                        factor = 1.0 + grade * 5.0   # uphill: +5% per % grade
                    else:
                        factor = max(0.5, 1.0 + grade * 2.0)  # downhill: save up to 50%
                    factor = max(0.5, min(3.0, factor))   # clamp [0.5, 3.0]

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

        This is the primary weight for the 'cheapest' variant used in
        "lowest cost to decarbonisation" research.

        cost_per_edge = dist_km × energy_price_gbp_km
                      + dist_km × emit_kg_km × carbon_tax_gbp_tco2
                      + dist_km × toll_per_km (from edge attributes)

        The carbon tax term means a carbon pricing policy immediately makes
        high-emission routes more expensive — this is the mechanism by which
        carbon taxes drive modal shift in the simulation.
        """
        e_price  = float(policy.get('energy_price_gbp_km',  0.12))
        c_tax    = float(policy.get('carbon_tax_gbp_tco2',  0.0))
        emit_g_km = _EMISSIONS_G_KM.get(mode, 100)
        emit_kg_km = emit_g_km / 1000.0

        for _u, _v, _k, data in graph.edges(keys=True, data=True):
            dist_km = data.get('length', 0.0) / 1000.0
            toll_km = data.get('toll_per_km', 0.0)   # future: congestion charge zone
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
        Lifecycle CO₂ weights for 'decarbonisation' route variant.

        Minimises total carbon cost including:
          - Operational emissions (g CO₂/km × grade factor)
          - Embodied carbon amortised per km (vehicle manufacturing)
          - Infrastructure carbon amortised per km (road/rail construction)
          - UK carbon budget trajectory weighting (2030 target = 2× today's price)

        This variant answers "which route minimises lifetime CO₂ under the
        UK's net-zero trajectory?" — the core RTD_SIM research question.

        Carbon budget trajectory (UK CCC 6th Carbon Budget):
          2025: £80/tCO₂   2030: £120/tCO₂   2035: £180/tCO₂   2050: £300/tCO₂
        We use a simple linear interpolation from scenario year.
        """
        from datetime import datetime
        # Scenario year — use current year as default
        scenario_year = int(policy.get('scenario_year', datetime.now().year))

        # UK CCC carbon budget price trajectory (£/tCO₂)
        _BUDGET_PRICE = {2025: 80, 2030: 120, 2035: 180, 2040: 240, 2050: 300}
        years = sorted(_BUDGET_PRICE)
        if scenario_year <= years[0]:
            c_budget_price = _BUDGET_PRICE[years[0]]
        elif scenario_year >= years[-1]:
            c_budget_price = _BUDGET_PRICE[years[-1]]
        else:
            for i in range(len(years) - 1):
                y0, y1 = years[i], years[i + 1]
                if y0 <= scenario_year <= y1:
                    t = (scenario_year - y0) / (y1 - y0)
                    c_budget_price = _BUDGET_PRICE[y0] + t * (_BUDGET_PRICE[y1] - _BUDGET_PRICE[y0])
                    break

        # Embodied carbon (kg CO₂ per km per vehicle) — SMMT / Ricardo lifecycle data
        _EMBODIED_KG_KM = {
            'car': 0.060, 'ev': 0.085,           # EV higher manufacture offset over lifetime
            'bus': 0.020, 'tram': 0.015,
            'van_diesel': 0.040, 'van_electric': 0.055,
            'truck_diesel': 0.035, 'truck_electric': 0.045,
            'hgv_diesel': 0.025, 'hgv_electric': 0.035, 'hgv_hydrogen': 0.030,
            'walk': 0.0, 'bike': 0.001, 'e_scooter': 0.002, 'cargo_bike': 0.002,
            'local_train': 0.010, 'intercity_train': 0.008, 'freight_rail': 0.012,
        }
        embodied_kg_km = _EMBODIED_KG_KM.get(mode, 0.030)

        has_elev = self.graph_manager.has_elevation()
        emit_g_km = _EMISSIONS_G_KM.get(mode, 100)
        emit_kg_km = emit_g_km / 1000.0

        for _u, _v, _k, data in graph.edges(keys=True, data=True):
            dist_km = data.get('length', 0.0) / 1000.0

            # Gradient factor for operational emissions (same as _add_emission_weights)
            factor = 1.0
            if has_elev:
                grade = data.get('grade', None)
                if grade is None and data.get('length', 0) > 0:
                    eu = graph.nodes[_u].get('elevation', 0)
                    ev_node = graph.nodes[_v].get('elevation', 0)
                    grade = (ev_node - eu) / data['length']
                if grade is not None:
                    factor = 1.0 + max(0, grade) * 5.0 if grade > 0 else max(0.5, 1.0 + grade * 2.0)
                    factor = max(0.5, min(3.0, factor))

            operational_kg = emit_kg_km * dist_km * factor
            lifecycle_kg   = operational_kg + embodied_kg_km * dist_km

            # Convert to monetary equivalent at carbon budget price (£/tCO₂ → £/kg = /1000)
            data['decarb_weight'] = lifecycle_kg * (c_budget_price / 1000.0)

        return 'decarb_weight'

    def _add_scenic_weights(self, graph: Any, mode: str) -> str:
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