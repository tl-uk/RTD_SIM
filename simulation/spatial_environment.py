"""
simulation/spatial_environment.py

Lightweight orchestrator that delegates to specialised subsystems:

  GraphManager       — OSM graph loading, caching, nearest-node queries
  Router             — Route computation and alternatives
  MetricsCalculator  — Travel time, cost, emissions, comfort, risk
  ElevationProvider  — Elevation annotation (already separate)
  RouteAlternative   — Route data class (already separate)

All existing public API methods are preserved for backward compatibility.

Rail graph loading
------------------
load_rail_graph() calls get_or_fallback_rail_graph(), which tries to
download the OpenRailMap graph and falls back to the hardcoded rail spine.
After download, the LARGEST WEAKLY CONNECTED COMPONENT is extracted.
This is critical: the raw OpenRailMap graph contains dozens of isolated
sub-graphs (sidings, depot stub tracks, buffer stops) that have no path
to the main line.  When agents snap to a node in one of these islands,
nx.shortest_path raises NetworkXNoPath and the route is rejected.
Keeping only the LCC guarantees that every node in the routing graph is
reachable from every other node.

GTFS transit loading
--------------------
load_gtfs_graph() derives the spatial bounding box from the drive graph
and applies a generous 0.3° (~30 km) padding before filtering stops.
This is necessary for routes that extend significantly beyond the OSM
drive graph boundary — the most common example being express bus and rail
services that cross the Forth (Edinburgh Airport → Ferrytoll P&R, etc.).
GTFS shape geometry is always trusted for stops outside the drive graph
bbox; the road-proxy fallback is only applied to stops that ARE within
the drive graph.
"""

from __future__ import annotations

import logging
import random
import secrets
from collections import defaultdict

from osmnx import graph

try:
    from utils.secure_rng import AgentRandom
    _SECURE_RNG_AVAILABLE = True
except Exception:  # pragma: no cover
    _SECURE_RNG_AVAILABLE = False

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from simulation.spatial.graph_manager import GraphManager
from simulation.spatial.router import Router
from simulation.spatial.metrics_calculator import MetricsCalculator
from simulation.spatial.coordinate_utils import (
    densify_route,
    interpolate_along_segment,
    is_valid_lonlat,
    route_distance_km,
    segment_distance_km,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level GTFS transit graph cache.
# Prevents the 2-minute GTFS parse running twice when startup_manager and
# simulation_runner each create a fresh SpatialEnvironment for the same feed.
# Key: (feed_path, service_date_or_None) → built GTFSGraph object.
# ---------------------------------------------------------------------------
_GTFS_TRANSIT_CACHE: dict = {}



class SpatialEnvironment:
    """
    Main spatial environment — orchestrates all spatial subsystems.

    Provides a backward-compatible API while delegating implementation to
    specialised components so each can be tested and replaced independently.
    """

    def __init__(
        self,
        step_minutes: float = 1.0,
        cache_dir: Optional[Path] = None,
        use_congestion: bool = False,
    ) -> None:
        """
        Args:
            step_minutes:   Simulation time step in minutes.
            cache_dir:      Directory for OSM graph cache.
                            Defaults to ~/.rtd_sim_cache/osm_graphs.
            use_congestion: Enable per-edge congestion tracking.
        """
        self.step_minutes   = step_minutes
        self.graph_manager  = GraphManager(cache_dir)

        self.congestion_manager = None
        if use_congestion:
            try:
                from simulation.spatial.congestion_manager import CongestionManager
                self.congestion_manager = CongestionManager(self.graph_manager)
                logger.info("Congestion tracking enabled")
            except ImportError:
                logger.warning("CongestionManager not available — congestion disabled")

        self.router  = Router(self.graph_manager, self.congestion_manager)
        self.metrics = MetricsCalculator()

        # Backward-compatibility aliases
        self.mode_network_types = self.router.mode_network_types
        self.speeds_km_min      = self.metrics.speeds_km_min

        # NaPTAN stops — populated by environment_setup, read by visualiser.
        # Declared here so Pylance resolves env.naptan_stops without error.
        self.naptan_stops: list = []

        # Weather speed multipliers: {mode: multiplier}
        self._weather_speed_multipliers: Dict[str, float] = defaultdict(lambda: 1.0)

        # RNG for OD sampling (CSPRNG when available)
        if _SECURE_RNG_AVAILABLE:
            self._od_rng = AgentRandom(None)
        else:
            self._od_rng = random.Random(secrets.randbits(128))


    # =========================================================================
    # WEATHER INTEGRATION
    # =========================================================================

    def set_weather_speed_multiplier(self, mode: str, multiplier: float) -> None:
        """Set weather-based speed adjustment for a mode."""
        self._weather_speed_multipliers[mode] = multiplier

    # =========================================================================
    # PROPERTIES (backward compatibility)
    # =========================================================================

    @property
    def graph_loaded(self) -> bool:
        return self.graph_manager.is_loaded()

    @property
    def G(self) -> Optional[Any]:
        """Primary graph (backward compatibility)."""
        return self.graph_manager.primary_graph

    @property
    def mode_graphs(self) -> dict:
        return self.graph_manager.graphs

    @property
    def has_elevation(self) -> bool:
        return self.graph_manager.has_elevation()

    # =========================================================================
    # GRAPH LOADING
    # =========================================================================

    def load_osm_graph(
        self,
        place: Optional[str] = None,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        network_type: str = 'all',
        use_cache: bool = True,
    ) -> None:
        """Load a single OSM graph by place name or bounding box."""
        self.graph_manager.load_graph(place, bbox, network_type, use_cache)

    def load_mode_specific_graphs(
        self,
        place: Optional[str] = None,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        modes: Optional[List[str]] = None,
        use_cache: bool = True,
    ) -> None:
        """Load separate OSM graphs for each requested transport mode."""
        # Narrow Optional[List[str]] to List[str] for Pylance
        _modes: List[str] = modes if modes is not None else ['drive', 'walk', 'bike']
        modes = _modes
        self.graph_manager.load_mode_specific_graphs(place, bbox, modes, use_cache)

    def load_rail_graph(
        self,
        bbox: Optional[Tuple[float, float, float, float]] = None,
    ) -> bool:
        """
        Download the OpenRailMap rail graph and register it with graph_manager.

        Called by environment_setup.py after the drive graph is loaded.
        Always attempts a fresh download and overwrites any previously
        registered graph (including the JIT-loaded spine).

        Largest-component extraction
        ----------------------------
        The raw OpenRailMap download for a city bbox contains many isolated
        sub-graphs: depot stub tracks, buffer stops, crossing loops, and
        freight sidings that are not connected to the main line.  When an
        agent snaps to a node in one of these islands, nx.shortest_path
        raises NetworkXNoPath and the route is silently rejected.

        After download, we extract the largest weakly connected component
        and discard all other sub-graphs.  This guarantees that every node
        in the routing graph is reachable from every other node, eliminating
        the "track topology fragmented" errors.

        The spine fallback (41 stations) is used when the download fails or
        returns an empty / very small graph.  The spine is fully connected
        by construction.

        Args:
            bbox: Optional (north, south, east, west) override.
                  Derived from the drive graph when not supplied.

        Returns:
            True if a usable rail graph was loaded, False otherwise.
        """
        from simulation.spatial.rail_network import get_or_fallback_rail_graph

        G_rail = get_or_fallback_rail_graph(env=self)

        if G_rail is None:
            logger.error("load_rail_graph: no rail graph available (download + spine both failed)")
            return False

        # Extract the largest weakly connected component to eliminate isolated
        # sidings and buffer-stop sub-graphs that cause NetworkXNoPath errors.
        try:
            import networkx as nx
            components = list(nx.weakly_connected_components(G_rail))
            if len(components) > 1:
                largest = max(components, key=len)
                n_before = G_rail.number_of_nodes()
                G_rail   = G_rail.subgraph(largest).copy()
                G_rail.graph['name'] = 'rail'   # preserve graph attribute
                logger.info(
                    "Rail graph: extracted largest component "
                    "(%d → %d nodes, discarded %d isolated sub-graphs)",
                    n_before, G_rail.number_of_nodes(), len(components) - 1,
                )
        except Exception as exc:
            logger.warning(
                "Rail LCC extraction failed (%s) — using full graph as-is", exc
            )

        # Register with graph_manager, overwriting any JIT-loaded spine.
        self.graph_manager.register_rail_graph(G_rail)

        # Also update the router's cached reference so it doesn't re-fetch.
        self.router._rail_graph          = G_rail
        self.router._rail_graph_attempted = True

        logger.info(
            "✅ Rail graph ready: %d nodes, %d edges",
            G_rail.number_of_nodes(), G_rail.number_of_edges(),
        )
        return True

    def get_rail_graph(self) -> Optional[Any]:
        """Return the loaded rail graph, or None.  Used by visualization."""
        return self.graph_manager.get_graph('rail')

    def load_ferry_graph(self) -> bool:
        """Load ferry route graph from Overpass API or hardcoded UK spine."""
        try:
            from simulation.spatial.rail_network import get_or_fallback_ferry_graph
            G = get_or_fallback_ferry_graph(self)
            if G is not None:
                self.graph_manager.graphs['ferry'] = G
                logger.info(
                    "✅ Ferry graph registered: %d terminals, %d routes",
                    G.number_of_nodes(), G.number_of_edges() // 2,
                )
                return True
            return False
        except Exception as exc:
            logger.error("load_ferry_graph failed: %s", exc)
            return False

    def get_ferry_graph(self) -> Optional[Any]:
        """Return the ferry route graph, or None if not yet loaded."""
        return self.graph_manager.get_graph('ferry')

    def compute_route_with_segments(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str,
        policy_context: Optional[dict] = None,
    ) -> Tuple[List[Tuple[float, float]], List[dict]]:
        """
        Compute route AND per-leg segment metadata for multimodal visualisation.

        This is the preferred API for agents so the visualiser can colour each
        leg (walk-to-stop / transit / walk-from-stop) independently.  Falls
        back to compute_route() with an empty segment list when the router
        does not support this method.

        Args:
            agent_id:       Identifier for logging.
            origin:         (lon, lat) start coordinate.
            dest:           (lon, lat) end coordinate.
            mode:           Transport mode string.
            policy_context: Generalised cost parameter overrides.

        Returns (flat_route, segments) where each segment is:
            {'path': [(lon,lat),...], 'mode': str, 'label': str}
        segments is [] for single-mode routes or on routing failure.
        """
        if hasattr(self.router, 'compute_route_with_segments'):
            return self.router.compute_route_with_segments(
                agent_id, origin, dest, mode,
                policy_context=policy_context,
            )
        route = self.router.compute_route(
            agent_id, origin, dest, mode,
            policy_context=policy_context,
        )
        return route, []

    def load_gtfs_graph(
        self,
        feed_path: str,
        service_date: Optional[str] = None,
        fuel_overrides: Optional[dict] = None,
        headway_window: Optional[tuple] = None,
    ) -> bool:
        """
        Parse a GTFS static feed and register the transit graph.

        Bounding box and padding
        ------------------------
        The spatial filter for stops is derived from the loaded drive graph
        plus a 0.3° (~30 km) padding in every direction.

        The larger padding is intentional: Edinburgh's bus and rail network
        extends well beyond the city's OSM drive graph boundary.  Key
        examples include:

          • E1 (Edinburgh Airport Express) → Ferrytoll P&R, north of the Forth
          • X56/X57 → South Queensferry, Dalmeny
          • ScotRail services → North Berwick, Musselburgh, Kirkcaldy

        With only 0.05° padding, stops north of the Forth are excluded and
        their routes degrade to straight-line fallbacks.  With 0.3° padding,
        all stops within a realistic commuter catchment are included and
        shape geometry is used correctly.

        Walk graph integration
        ----------------------
        If the walk graph is loaded, build_transfer_edges() stitches each
        GTFS stop to its nearest walk-graph node so the Router can chain
        walk → board → ride → alight → walk.

        Args:
            feed_path:      Path to GTFS .zip or directory.
            service_date:   'YYYYMMDD' string.  Restricts to services active
                            on this date.  None = all services (slower).
            fuel_overrides: {route_id: fuel_type} overrides.
            headway_window: (start_s, end_s) for headway computation.
                            Defaults to AM peak 07:00–09:30.

        Returns:
            True if transit graph loaded and registered successfully.
        """
        # Idempotent: skip if already loaded on this instance.
        if self.graph_manager.get_graph('transit') is not None:
            logger.debug("GTFS transit graph already loaded — skipping")
            return True

        # Module-level cache: reuse a previously-built transit graph when a
        # second SpatialEnvironment is created for the same feed (e.g.
        # startup_manager preview followed by simulation_runner setup).
        # Parsing 3.2M stop_times takes ~2 minutes; this eliminates the
        # redundant second pass without any loss of correctness.
        _cache_key = (str(feed_path), str(service_date))
        if _cache_key in _GTFS_TRANSIT_CACHE:
            cached = _GTFS_TRANSIT_CACHE[_cache_key]
            self.graph_manager.graphs['transit'] = cached['graph']
            self.gtfs_loader = cached['loader']
            logger.info(
                "GTFS transit graph: reused from module cache (feed=%s, date=%s) "                "— %d stops, %d edges",
                feed_path, service_date,
                cached['graph'].number_of_nodes(),
                cached['graph'].number_of_edges(),
            )
            return True

        try:
            # Derive spatial filter from drive graph with generous padding.
            bbox = None
            drive = self.graph_manager.get_graph('drive')
            if drive is not None and len(drive.nodes) > 0:
                lons = [d['x'] for _, d in drive.nodes(data=True)]
                lats = [d['y'] for _, d in drive.nodes(data=True)]

                # 0.3° ≈ 30 km — captures cross-Forth and regional services.
                # This is larger than the OSM drive graph so GTFS stops outside
                # the city boundary (Ferrytoll, Musselburgh, Kirkcaldy) are
                # included with their shape geometry intact.
                pad = 0.30
                bbox = (
                    min(lons) - pad,
                    min(lats) - pad,
                    max(lons) + pad,
                    max(lats) + pad,
                )
                logger.info(
                    "GTFS spatial filter: bbox=(%.4f, %.4f, %.4f, %.4f) "
                    "[drive graph + %.2f° padding]",
                    *bbox, pad,
                )

            from simulation.gtfs.gtfs_loader import GTFSLoader
            from simulation.gtfs.gtfs_graph import GTFSGraph

            loader = GTFSLoader(
                feed_path      = feed_path,
                service_date   = service_date,
                fuel_overrides = fuel_overrides,
                bbox           = bbox,
            )
            loader.load()

            summary = loader.summary()
            logger.info(
                "GTFS loaded: %d stops, %d routes, %d trips, %d shapes — modes: %s",
                summary['stops'], summary['routes'],
                summary['trips'], summary['shapes'],
                summary['modes'],
            )

            # Sanity check: warn if the feed appears nearly empty after filtering.
            if summary['stops'] < 10:
                logger.warning(
                    "⚠️  GTFS: only %d stops after spatial filter — "
                    "the feed may not cover this region, or the bbox is too small",
                    summary['stops'],
                )

            headways  = loader.compute_headways(headway_window)
            builder   = GTFSGraph(loader, headways)
            G_transit = builder.build()

            if G_transit is None:
                logger.warning("⚠️  GTFS: transit graph build returned None")
                return False

            # Stitch GTFS stops to the walk graph when available.
            G_walk = self.graph_manager.get_graph('walk')
            if G_walk is not None:
                n_transfer = builder.build_transfer_edges(G_transit, G_walk)
                logger.info("GTFS: %d stops linked to walk graph", n_transfer)
            else:
                logger.debug(
                    "GTFS: no walk graph loaded — transfer edges skipped. "
                    "Access/egress legs will use interpolated straight lines. "
                    "Load network_type='walk' via load_mode_specific_graphs() "
                    "for proper pedestrian routing to/from stops."
                )

            self.graph_manager.graphs['transit'] = G_transit
            self.gtfs_loader = loader   # stash for analytics / pydeck layers

            # Populate the module-level cache so any subsequent SpatialEnvironment
            # instance for the same feed can skip the 2-minute parse.
            _GTFS_TRANSIT_CACHE[_cache_key] = {
                'graph':  G_transit,
                'loader': loader,
            }
            logger.info(
                "✅ GTFS transit graph: %d stops, %d service edges",
                G_transit.number_of_nodes(), G_transit.number_of_edges(),
            )
            return True

        except Exception as exc:
            logger.exception("load_gtfs_graph failed: %s", exc)
            return False

    def get_transit_graph(self) -> Optional[Any]:
        """Return the loaded GTFS transit graph, or None.  Used by visualization."""
        return self.graph_manager.get_graph('transit')

    # =========================================================================
    # ELEVATION
    # =========================================================================

    def add_elevation_data(self, method: str = 'opentopo', **kwargs) -> bool:
        """Add elevation data to the primary graph."""
        return self.graph_manager.add_elevation_data(method, **kwargs)

    # =========================================================================
    # ROUTING
    # =========================================================================

    def _interpolate_route_geometry(
        self,
        coords: List[Tuple[float, float]],
        max_segment_km: float = 0.05,
    ) -> List[Tuple[float, float]]:
        """
        Insert intermediate points along route segments for smooth rendering.

        Args:
            coords:          Original route coordinates.
            max_segment_km:  Maximum gap between consecutive points (default 50 m).

        Returns:
            Densified coordinate list.
        """
        if not coords or len(coords) < 2:
            return coords

        out = [coords[0]]
        for i in range(len(coords) - 1):
            p1, p2   = coords[i], coords[i + 1]
            dist_km  = segment_distance_km(p1, p2)
            if dist_km > max_segment_km:
                n = int(dist_km / max_segment_km) + 1
                for j in range(1, n):
                    t = j / n
                    out.append((
                        p1[0] + t * (p2[0] - p1[0]),
                        p1[1] + t * (p2[1] - p1[1]),
                    ))
            out.append(p2)
        return out

    def compute_route(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str,
        policy_context: Optional[dict] = None,
    ) -> List[Tuple[float, float]]:
        """
        Compute shortest generalised-cost route.

        Args:
            agent_id:       Identifier for logging.
            origin:         (lon, lat) start coordinate.
            dest:           (lon, lat) end coordinate.
            mode:           Transport mode string.
            policy_context: Generalised cost parameter overrides, e.g.
                            {'carbon_tax_gbp_tco2': 25.0,
                             'energy_price_gbp_km': 0.15,
                             'boarding_penalty_min': 20.0,
                             'value_of_time_gbp_h': 10.0}.
                            When None the router uses its defaults.

        Returns:
            List of (lon, lat) 2-tuples, or [] on failure.
        """
        return self.router.compute_route(
            agent_id, origin, dest, mode,
            policy_context=policy_context,
        )

    def compute_route_alternatives(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str,
        variants: Optional[List[str]] = None,  # narrowed below
        policy_context: Optional[dict] = None,
    ) -> List[Any]:
        """
        Compute multiple route alternatives.

        Returns RouteAlternative objects with metrics already computed.
        """
        # Narrow Optional[List[str]] to List[str] for type checkers
        _variants: List[str] = variants if variants is not None else ['shortest', 'fastest', 'greenest']
        alternatives = self.router.compute_alternatives(
            agent_id, origin, dest, mode, _variants,
            policy_context=policy_context,
        )
        for alt in alternatives:
            # hasattr guard: alt is typed Any from router; Pylance can't resolve
            # compute_metrics. The guard is the correct runtime check.
            compute_fn = getattr(alt, 'compute_metrics', None)
            if compute_fn is not None:
                compute_fn(self)
        return alternatives

    def route(
        self,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str = 'walk',  # noqa: ARG002 — kept for API compatibility; callers pass mode
    ) -> List[Tuple[float, float]]:
        """
        Route with detailed road geometry for visualization (legacy method).

        Uses OSMnx directly on the primary graph.  Prefer compute_route()
        for new code — it uses the Router with generalised cost and supports
        all transport modes.
        """
        import osmnx as ox

        if segment_distance_km(origin, dest) < 0.1:
            return [origin, dest]

        # self.G is Optional — guard before any graph calls so Pylance
        # resolves nearest_nodes / shortest_path / get_edge_data / .nodes
        if self.G is None:
            return [origin, dest]

        G: Any = self.G  # narrowed non-None reference for the block below

        try:
            orig_node = ox.distance.nearest_nodes(G, origin[0], origin[1])
            dest_node = ox.distance.nearest_nodes(G, dest[0],   dest[1])

            if orig_node == dest_node:
                return [origin, dest]

            node_route = ox.shortest_path(G, orig_node, dest_node, weight='length')
            if node_route is None:
                return [origin, dest]

            coords = [origin]
            for i in range(len(node_route) - 1):
                u, v      = node_route[i], node_route[i + 1]
                edge_data = G.get_edge_data(u, v)
                if edge_data is None:
                    coords.append((G.nodes[v]['x'], G.nodes[v]['y']))
                    continue
                if isinstance(edge_data, dict) and 0 in edge_data:
                    edge_data = edge_data[0]
                if 'geometry' in edge_data and hasattr(edge_data['geometry'], 'coords'):
                    coords.extend(list(edge_data['geometry'].coords)[1:])
                else:
                    coords.append((G.nodes[v]['x'], G.nodes[v]['y']))

            if coords[-1] != dest:
                coords.append(dest)

            return self._interpolate_route_geometry(coords, max_segment_km=0.05)

        except Exception as exc:
            logger.warning("route() failed: %s", exc)
            return [origin, dest]

    # =========================================================================
    # METRICS
    # =========================================================================

    def estimate_travel_time(
        self,
        route: List[Tuple[float, float]],
        mode: str,
    ) -> float:
        """Calculate travel time, adjusted for weather speed multiplier."""
        base = self.metrics.calculate_travel_time(route, mode)
        mult = self._weather_speed_multipliers.get(mode, 1.0)
        return base / mult   # slower speed → more time

    def estimate_monetary_cost(
        self,
        route: List[Tuple[float, float]],
        mode: str,
    ) -> float:
        """Calculate monetary cost."""
        return self.metrics.calculate_cost(route, mode)

    def estimate_emissions(
        self,
        route: List[Tuple[float, float]],
        mode: str,
    ) -> float:
        """Calculate emissions (flat terrain assumption)."""
        return self.metrics.calculate_emissions(route, mode)

    def estimate_emissions_with_elevation(
        self,
        route: List[Tuple[float, float]],
        mode: str,
    ) -> float:
        """Calculate emissions with elevation-grade adjustments."""
        return self.metrics.calculate_emissions_with_elevation(
            route, mode, self.graph_manager
        )

    def estimate_comfort(
        self,
        route: List[Tuple[float, float]],
        mode: str,
    ) -> float:
        """Calculate comfort score."""
        return self.metrics.calculate_comfort(route, mode)

    def estimate_risk(
        self,
        route: List[Tuple[float, float]],
        mode: str,
    ) -> float:
        """Calculate risk score."""
        return self.metrics.calculate_risk(route, mode)

    def get_speed_km_min(self, mode: str) -> float:
        """Return speed in km per minute for a given mode."""
        return self.metrics.get_speed_km_min(mode)

    # =========================================================================
    # MOVEMENT
    # =========================================================================

    def advance_along_route(
        self,
        route: List[Tuple[float, float]],
        current_index: int,
        offset_km: float,
        mode: str,
    ) -> Tuple[int, float, Tuple[float, float]]:
        """
        Advance an agent along its route by one simulation time step.

        Args:
            route:         Full route coordinate list.
            current_index: Current segment index within the route.
            offset_km:     Distance already travelled on the current segment.
            mode:          Transport mode (determines speed).

        Returns:
            (new_segment_index, new_offset_km, current_position_lonlat)
        """
        if not route or len(route) < 2:
            return 0, 0.0, route[0] if route else (0.0, 0.0)

        remaining = self.get_speed_km_min(mode) * self.step_minutes
        i   = max(0, min(current_index, len(route) - 2))
        off = max(0.0, offset_km)

        while remaining > 1e-9 and i < len(route) - 1:
            p1, p2       = route[i], route[i + 1]
            seg_len      = segment_distance_km(p1, p2)
            left_on_seg  = max(0.0, seg_len - off)

            if remaining < left_on_seg:
                new_pos = interpolate_along_segment(p1, p2, off + remaining)
                return i, off + remaining, new_pos
            else:
                remaining -= left_on_seg
                i  += 1
                off = 0.0

        return len(route) - 2, 0.0, route[-1]

    def densify_route(
        self,
        route: List[Tuple[float, float]],
        step_meters: float = 20.0,
    ) -> List[Tuple[float, float]]:
        """Add intermediate points for smooth visualization."""
        return densify_route(route, step_meters)

    # =========================================================================
    # ORIGIN–DESTINATION GENERATION
    # =========================================================================

    def get_random_node_coords(self) -> Optional[Tuple[float, float]]:
        """Return a random node coordinate from the primary graph."""
        if not self.graph_loaded:
            return None
        nodes = list(self.G.nodes(data=True))
        if not nodes:
            return None
        _, data = self._od_rng.choice(nodes)
        return (float(data.get('x')), float(data.get('y')))

    def get_random_origin_dest(
        self,
        min_distance_km: float = 0.5,
        max_attempts: int = 30,
    ) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
        """
        Return a random (origin, destination) pair sampled from OSM
        building/address nodes, snapped to the nearest drive graph node.

        Agents MUST start and end at real-world addresses — not at road
        intersections, which are the only coordinates that pure drive-graph
        sampling produces.  Starting on a road makes agents appear to walk
        out of the tarmac and violates the simulation's realism contract.

        Priority:
          1. OSM building/address centroids (loaded via _ensure_address_nodes)
          2. Drive graph nodes as fallback (original behaviour)

        Both sources are snapped to the nearest drive node so routing
        still works; the sampled address is kept as the display coordinate.

        Args:
            min_distance_km: Minimum straight-line distance between OD pair.
            max_attempts:    Maximum sampling attempts before giving up.

        Returns:
            ((origin_lon, origin_lat), (dest_lon, dest_lat)) or None.
        """
        if not self.graph_loaded:
            logger.warning("Graph not loaded for random OD generation")
            return None

        graph = self.graph_manager.get_graph('drive')
        if graph is None or graph.number_of_nodes() < 2:
            logger.warning("No 'drive' graph available for random OD generation")
            return None

        from simulation.spatial.coordinate_utils import haversine_km
        import networkx as nx

        # ── Prefer address/building nodes ─────────────────────────────────────
        address_nodes = self._ensure_address_nodes()
        use_addresses = len(address_nodes) >= 10

        for _ in range(max_attempts):
            if use_addresses:
                raw_origin = address_nodes[self._od_rng.randrange(len(address_nodes))]
                raw_dest   = address_nodes[self._od_rng.randrange(len(address_nodes))]
            else:
                drive_nodes = list(graph.nodes())
                n1, n2 = self._od_rng.sample(drive_nodes, 2)
                raw_origin = (graph.nodes[n1]['x'], graph.nodes[n1]['y'])
                raw_dest   = (graph.nodes[n2]['x'], graph.nodes[n2]['y'])

            if haversine_km(raw_origin, raw_dest) < min_distance_km:
                continue

            # Snap to nearest drive node for routing
            node1 = self.graph_manager.get_nearest_node(raw_origin, 'drive')
            node2 = self.graph_manager.get_nearest_node(raw_dest,   'drive')
            if node1 is None or node2 is None or node1 == node2:
                continue

            origin = (float(graph.nodes[node1]['x']), float(graph.nodes[node1]['y']))
            dest   = (float(graph.nodes[node2]['x']), float(graph.nodes[node2]['y']))

            if haversine_km(origin, dest) < min_distance_km:
                continue

            try:
                path = nx.shortest_path(graph, node1, node2, weight='length')
                if len(path) >= 2:
                    logger.debug(
                        "Generated OD pair: %.1fkm apart (addresses: %s)",
                        haversine_km(origin, dest), use_addresses,
                    )
                    return (origin, dest)
            except nx.NetworkXNoPath:
                continue

        logger.error(
            "Failed to generate valid OD pair after %d attempts",
            max_attempts,
        )
        return None

    def _ensure_address_nodes(self) -> list:
        """
        Return cached list of (lon, lat) building/address centroids.

        Fetches from Overpass on first call and caches for the lifetime of
        the environment.  Falls back to [] if Overpass is unavailable.
        """
        if hasattr(self, '_address_node_cache') and self._address_node_cache:
            return self._address_node_cache

        self._address_node_cache = []

        try:
            bbox = self.graph_manager.get_bbox()
            if bbox is None:
                return []
            north, south, east, west = bbox

            # Fetch building and address nodes from Overpass.
            # We request centroids (out center) to get one coord per building.
            import json, urllib.request, urllib.parse
            query = (
                f"[out:json][timeout:45];"                f"("                f"  node['addr:street']({south},{west},{north},{east});"                f"  way['building']({south},{west},{north},{east});"                f"  way['amenity']['amenity'!~'parking|parking_space']"                f"    ({south},{west},{north},{east});"                f");"                f"out center;"            )
            body = urllib.parse.urlencode({'data': query}).encode('utf-8')
            req  = urllib.request.Request(
                'https://overpass-api.de/api/interpreter',
                data=body, method='POST',
                headers={'Content-Type': 'application/x-www-form-urlencoded',
                         'User-Agent':   'RTD_SIM_AddressSampler/1.0'},
            )
            with urllib.request.urlopen(req, timeout=50) as resp:
                data = json.loads(resp.read())

            nodes = []
            for el in data.get('elements', []):
                if el['type'] == 'node':
                    nodes.append((float(el['lon']), float(el['lat'])))
                elif el['type'] == 'way' and 'center' in el:
                    nodes.append((float(el['center']['lon']), float(el['center']['lat'])))

            self._address_node_cache = nodes
            logger.info(
                "✅ Address/building nodes loaded: %d locations for agent OD sampling",
                len(nodes),
            )
        except Exception as exc:
            logger.warning("Address node fetch failed (%s) — falling back to drive nodes", exc)

        return self._address_node_cache

    # =========================================================================
    # GRAPH STATS & UTILITIES
    # =========================================================================

    def get_graph_stats(self) -> dict:
        """Return graph statistics including node/edge counts and spatial bounds."""
        return self.graph_manager.get_stats()

    def precompute_nearest_nodes(
        self,
        points: List[Tuple[float, float]],
    ) -> None:
        """Pre-warm nearest-node cache for a list of coordinates."""
        self.graph_manager.precompute_nearest_nodes(points)

    def clear_cache(self) -> None:
        """Delete all cached graph files from disk."""
        self.graph_manager.clear_cache()

    # =========================================================================
    # CONGESTION MANAGEMENT
    # =========================================================================

    def update_agent_congestion(
        self,
        agent_id: str,
        current_edge: Optional[Tuple[int, int, int]] = None,
    ) -> None:
        """
        Update an agent's position for congestion tracking.

        Args:
            agent_id:     Agent identifier.
            current_edge: (u, v, key) edge tuple, or None when off-network.
        """
        if self.congestion_manager:
            self.congestion_manager.update_agent_position(agent_id, current_edge)

    def get_congestion_stats(self) -> dict:
        """Return congestion statistics."""
        if self.congestion_manager:
            return self.congestion_manager.get_stats()
        return {'congestion_enabled': False}

    def advance_congestion_time(self, hours: float = None) -> None:
        """Advance the congestion simulation clock by one step."""
        if self.congestion_manager:
            if hours is None:
                hours = self.step_minutes / 60.0
            self.congestion_manager.advance_time(hours)

    def get_congestion_heatmap(self) -> dict:
        """Return per-edge congestion factors for the current time step."""
        if self.congestion_manager:
            return self.congestion_manager.get_congestion_heatmap()
        return {}

    # =========================================================================
    # BACKWARD COMPATIBILITY SHIMS
    # =========================================================================

    def _estimate_base_travel_time(
        self,
        route: List[Tuple[float, float]],
        mode: str,
    ) -> float:
        """Legacy shim — delegates to MetricsCalculator."""
        return self.metrics.calculate_travel_time(route, mode)

    def _distance(self, route: List[Tuple[float, float]]) -> float:
        return route_distance_km(route)

    def _segment_distance_km(
        self,
        coord1: Tuple[float, float],
        coord2: Tuple[float, float],
    ) -> float:
        return segment_distance_km(coord1, coord2)

    def _is_lonlat(self, coord: Tuple[float, float]) -> bool:
        return is_valid_lonlat(coord)

    def _get_nearest_node(
        self,
        coord: Tuple[float, float],
        network_type: str = 'all',
    ) -> Optional[int]:
        return self.graph_manager.get_nearest_node(coord, network_type)

    @staticmethod
    def _haversine_km(
        coord1: Tuple[float, float],
        coord2: Tuple[float, float],
    ) -> float:
        from simulation.spatial.coordinate_utils import haversine_km
        return haversine_km(coord1, coord2)

    def _haversine_m(
        self,
        coord1: Tuple[float, float],
        coord2: Tuple[float, float],
    ) -> float:
        from simulation.spatial.coordinate_utils import haversine_m
        return haversine_m(coord1, coord2)

    def _get_cache_key(
        self,
        place: Optional[str],
        bbox: Optional[Tuple],
        network_type: str,
    ) -> str:
        return self.graph_manager._get_cache_key(place, bbox, network_type)

    @property
    def cache_dir(self) -> Path:
        return self.graph_manager.cache_dir