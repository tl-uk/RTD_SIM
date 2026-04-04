"""
simulatio/spatial/spatial_environment.py

This is now a lightweight orchestrator that delegates to specialized subsystems:
- GraphManager: OSM graph loading & caching
- Router: Route computation & alternatives
- MetricsCalculator: Performance metrics
- ElevationProvider: Elevation data (already separate)
- RouteAlternative: Route data class (already separate)

BACKWARD COMPATIBLE: All existing API methods still work!
"""

from __future__ import annotations
from typing import List, Tuple, Optional, Any
from pathlib import Path
from collections import defaultdict
import random
import secrets  # ✅ ADD: Cryptographic RNG
import logging

from simulation.spatial.graph_manager import GraphManager
from simulation.spatial.router import Router
from simulation.spatial.metrics_calculator import MetricsCalculator
from simulation.spatial.coordinate_utils import (
    route_distance_km,
    densify_route,
    interpolate_along_segment,
    segment_distance_km,
    is_valid_lonlat,
)

logger = logging.getLogger(__name__)


class SpatialEnvironment:
    """
    Main spatial environment - orchestrates all spatial subsystems.
    
    Provides backward-compatible API while delegating to specialized components.
    """
    
    def __init__(self, step_minutes: float = 1.0, cache_dir: Optional[Path] = None, use_congestion: bool = False) -> None:
        """Initialize spatial environment."""
        self.step_minutes = step_minutes
        
        # Initialize subsystems
        self.graph_manager = GraphManager(cache_dir)
        
        # Optional congestion manager
        self.congestion_manager = None
        if use_congestion:
            try:
                from simulation.spatial.congestion_manager import CongestionManager
                self.congestion_manager = CongestionManager(self.graph_manager)
                logger.info("Congestion tracking enabled")
            except ImportError:
                logger.warning("CongestionManager not available, congestion disabled")
        
        self.router = Router(self.graph_manager, self.congestion_manager)
        self.metrics = MetricsCalculator()
        
        # Backward compatibility properties
        self.mode_network_types = self.router.mode_network_types
        self.speeds_km_min = self.metrics.speeds_km_min

        # Weather speed multipliers (FIX: defaultdict now imported!)
        self._weather_speed_multipliers = defaultdict(lambda: 1.0)

    # ============================================================================
    # Weather Integration
    # ============================================================================
    def set_weather_speed_multiplier(self, mode: str, multiplier: float):
        """Set weather-based speed adjustment for a mode."""
        self._weather_speed_multipliers[mode] = multiplier
    
    def estimate_travel_time(self, route, mode):
        """Estimate with weather adjustment."""
        base_time = self._estimate_base_travel_time(route, mode)
        
        # Apply weather multiplier
        weather_mult = self._weather_speed_multipliers.get(mode, 1.0)
        
        return base_time / weather_mult  # Slower speed = more time
    
    # ============================================================================
    # Properties (Backward Compatibility)
    # ============================================================================
    
    @property
    def graph_loaded(self) -> bool:
        """Check if graph is loaded."""
        return self.graph_manager.is_loaded()
    
    @property
    def G(self) -> Optional[Any]:
        """Get primary graph (backward compatibility)."""
        return self.graph_manager.primary_graph
    
    @property
    def mode_graphs(self) -> dict:
        """Get mode-specific graphs (backward compatibility)."""
        return self.graph_manager.graphs
    
    @property
    def has_elevation(self) -> bool:
        """Check if elevation data available."""
        return self.graph_manager.has_elevation()
    
    # ============================================================================
    # Graph Loading (Delegate to GraphManager)
    # ============================================================================
    
    def load_osm_graph(
        self,
        place: Optional[str] = None,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        network_type: str = 'all',
        use_cache: bool = True
    ) -> None:
        """Load single OSM graph."""
        self.graph_manager.load_graph(place, bbox, network_type, use_cache)
    
    def load_mode_specific_graphs(
        self,
        place: Optional[str] = None,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        modes: List[str] = None,
        use_cache: bool = True
    ) -> None:
        """Load mode-specific graphs."""
        self.graph_manager.load_mode_specific_graphs(place, bbox, modes, use_cache)
    
    def load_rail_graph(
        self,
        bbox: Optional[Tuple[float, float, float, float]] = None,
    ) -> bool:
        """
        Load the OpenRailMap rail graph and register it with graph_manager.

        Called by environment_setup.py after the drive graph is loaded.
        Safe to call multiple times — returns immediately if already loaded.

        Args:
            bbox: Optional (north, south, east, west) override.
                  If None, derives bbox from the loaded drive graph.

        Returns:
            True if rail graph loaded successfully, False otherwise.
        """
        # if self.graph_manager.get_graph('rail') is not None:
        #     logger.debug("Rail graph already loaded — skipping")
        #     return True
        from simulation.spatial.rail_network import get_or_fallback_rail_graph, fetch_rail_graph
        G_rail = get_or_fallback_rail_graph(env=self)
        if G_rail is not None:
            self.graph_manager.graphs['rail'] = G_rail   # always overwrite
            logger.info("Rail graph loaded: %d nodes", len(G_rail.nodes))
            return True
        return False

        # if bbox is None:
        #     drive = self.graph_manager.get_graph('drive')
        #     if drive is not None:
        #         xs = [d['x'] for _, d in drive.nodes(data=True)]
        #         ys = [d['y'] for _, d in drive.nodes(data=True)]
        #         bbox = (max(ys), min(ys), max(xs), min(xs))
        #     else:
        #         logger.warning(
        #             "load_rail_graph: drive graph not loaded — using Edinburgh bbox"
        #         )
        #         bbox = (56.0, 55.85, -3.05, -3.40)

        # try:
        #     logger.info("Fetching rail graph from OpenRailMap (bbox=%s)…", bbox)
        #     G_rail = fetch_rail_graph(bbox)
        #     if G_rail is not None:
        #         self.graph_manager.graphs['rail'] = G_rail
        #         # Also cache on the router so it doesn't re-fetch
        #         self.router._rail_graph = G_rail
        #         self.router._rail_graph_attempted = True
        #         logger.info(
        #             "✅ Rail graph loaded: %d nodes, %d edges",
        #             len(G_rail.nodes), len(G_rail.edges),
        #         )
        #         return True
        #     else:
        #         logger.warning("⚠️  OpenRailMap returned None — rail agents will use synthetic routes")
        #         return False
        # except Exception as exc:
        #     logger.error("load_rail_graph failed: %s", exc)
        #     return False

    def get_rail_graph(self):
        """Return the loaded rail graph (or None). Used by visualization."""
        return self.graph_manager.get_graph('rail')

    def load_gtfs_graph(
        self,
        feed_path: str,
        service_date: Optional[str] = None,
        fuel_overrides: Optional[dict] = None,
        headway_window: Optional[tuple] = None,
    ) -> bool:
        """
        Parse a GTFS static feed and register the transit graph.

        Builds a NetworkX transit graph (stops + service edges with shape
        geometry and headways) and stores it as graph_manager.graphs['transit'].
        Also stitches walk-transfer edges so agents can walk to/from stops.

        Args:
            feed_path:      Path to GTFS .zip or directory.
            service_date:   'YYYYMMDD' — restrict to services active on this date.
                            None = load all services (larger graph, slower).
            fuel_overrides: {route_id: 'electric'|'diesel'|'hydrogen'}
                            overrides the loader's auto-inferred fuel type.
            headway_window: (start_s, end_s) for headway computation.
                            Defaults to AM peak 07:00–09:30.

        Returns:
            True if transit graph loaded and registered successfully.
        """
        if self.graph_manager.get_graph('transit') is not None:
            logger.debug("GTFS transit graph already loaded — skipping")
            return True

        try:
            # Dynamically calculate the map bounds to filter the massive UK feed
            bbox = None
            drive = self.graph_manager.get_graph('drive')
            if drive is not None and len(drive.nodes) > 0:
                lons = [d['x'] for _, d in drive.nodes(data=True)]
                lats = [d['y'] for _, d in drive.nodes(data=True)]
                
                # Add a 0.05 degree (~5km) padding to ensure we catch transit lines 
                # that start/end just outside the visible simulation area
                pad = 0.05
                bbox = (min(lons) - pad, min(lats) - pad, max(lons) + pad, max(lats) + pad)
                logger.info(f"Applying GTFS Spatial Filter: bbox={bbox}")

            # Instantiate directly to pass the bbox argument
            from simulation.gtfs.gtfs_loader import GTFSLoader
            from simulation.gtfs.gtfs_graph import GTFSGraph
            
            loader = GTFSLoader(
                feed_path=feed_path,
                service_date=service_date,
                fuel_overrides=fuel_overrides,
                bbox=bbox  # <-- Critical: Passes the bounding box
            )
            loader.load()
            
            headways = loader.compute_headways(headway_window)
            builder = GTFSGraph(loader, headways)
            G_transit = builder.build()

            if G_transit is None:
                logger.warning("⚠️  GTFS: transit graph build returned None")
                return False

            # Link transit nodes to walkable road network
            G_walk = self.graph_manager.get_graph('walk')
            if G_walk is not None:
                builder.build_transfer_edges(G_transit, G_walk)

            self.graph_manager.graphs['transit'] = G_transit
            self.gtfs_loader = loader  # stash for analytics / pydeck layers
            
            logger.info("✅ GTFS transit graph: %d stops, %d service edges",
                        G_transit.number_of_nodes(), G_transit.number_of_edges())
            return True

        except Exception as exc:
            logger.error("load_gtfs_graph failed: %s", exc)
            return False

    def get_transit_graph(self):
        """Return the loaded GTFS transit graph (or None). Used by visualization."""
        return self.graph_manager.get_graph('transit')

    def add_elevation_data(self, method: str = 'opentopo', **kwargs) -> bool:
        """Add elevation data to graph."""
        return self.graph_manager.add_elevation_data(method, **kwargs)
    
    # ============================================================================
    # Routing (Delegate to Router)
    # ============================================================================
    
    def _interpolate_route_geometry(
        self, 
        coords: List[Tuple[float, float]], 
        max_segment_km: float = 0.05
    ) -> List[Tuple[float, float]]:
        """
        Add intermediate points between route coordinates for smoother visualization.
        
        Args:
            coords: Original route coordinates
            max_segment_km: Maximum distance between points (default 50m)
        
        Returns:
            Interpolated route with additional points
        """
        if not coords or len(coords) < 2:
            return coords
        
        interpolated = [coords[0]]  # Start with first point
        
        for i in range(len(coords) - 1):
            p1 = coords[i]
            p2 = coords[i + 1]
            
            # Calculate distance between points
            dist_km = self._segment_distance_km(p1, p2)
            
            # If segment is longer than max, add intermediate points
            if dist_km > max_segment_km:
                # Number of segments to split into
                num_segments = int(dist_km / max_segment_km) + 1
                
                # Add intermediate points
                for j in range(1, num_segments):
                    t = j / num_segments  # Interpolation factor (0 to 1)
                    
                    # Linear interpolation
                    interp_lon = p1[0] + t * (p2[0] - p1[0])
                    interp_lat = p1[1] + t * (p2[1] - p1[1])
                    
                    interpolated.append((interp_lon, interp_lat))
            
            # Add the next point
            interpolated.append(p2)
        
        return interpolated

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
            policy_context: Dict with generalised cost parameters, e.g.
                            {'carbon_tax_gbp_tco2': 25.0,
                             'energy_price_gbp_km': 0.15,
                             'boarding_penalty_min': 20.0,
                             'value_of_time_gbp_h': 10.0}
                            When None the router uses its own defaults.
                            Pass agent_context from BDI planner so that
                            scenario policy changes (carbon tax hike, fuel
                            subsidy) immediately shift generalised costs.
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
        variants: List[str] = None,
        policy_context: Optional[dict] = None,
    ) -> List[Any]:
        """
        Compute multiple route alternatives.

        Returns RouteAlternative objects with metrics already computed.
        """
        alternatives = self.router.compute_alternatives(
            agent_id, origin, dest, mode, variants,
            policy_context=policy_context,
        )
        for alt in alternatives:
            if hasattr(alt, 'compute_metrics'):
                alt.compute_metrics(self)
        return alternatives
    
    def route(self, origin: Tuple[float, float], dest: Tuple[float, float], mode: str = 'walk'):
        """
        Route with detailed road geometry for visualization.
        
        Returns route with ALL geometry points, not just intersections.
        """
        import osmnx as ox
        
        # Check if points are too close (< 100m)
        distance = self._segment_distance_km(origin, dest)
        if distance < 0.1:  # Less than 100m
            # Return a simple 2-point route for very short trips
            return [origin, dest]
        
        # Try OSMnx routing
        try:
            # Find nearest nodes
            orig_node = ox.distance.nearest_nodes(
                self.G, origin[0], origin[1], 
                return_dist=False
            )
            dest_node = ox.distance.nearest_nodes(
                self.G, dest[0], dest[1], 
                return_dist=False
            )
            
            # If same node, return short route
            if orig_node == dest_node:
                return [origin, dest]
            
            # Get route nodes
            node_route = ox.shortest_path(self.G, orig_node, dest_node, weight='length')
            
            if node_route is None:
                logger.warning(f"No path found from {origin} to {dest}")
                return [origin, dest]
            
            # Extract detailed geometry from edges
            detailed_coords = [origin]  # Start with origin
            
            for i in range(len(node_route) - 1):
                u = node_route[i]
                v = node_route[i + 1]
                
                # Get edge data (may have multiple edges between same nodes)
                edge_data = self.G.get_edge_data(u, v)
                
                if edge_data is None:
                    # Fallback: straight line between nodes
                    u_coord = (self.G.nodes[u]['x'], self.G.nodes[u]['y'])
                    v_coord = (self.G.nodes[v]['x'], self.G.nodes[v]['y'])
                    detailed_coords.append(v_coord)
                    continue
                
                # Handle multi-edges (take first edge)
                if isinstance(edge_data, dict) and 0 in edge_data:
                    edge_data = edge_data[0]
                
                # Extract geometry
                if 'geometry' in edge_data:
                    # Edge has detailed LineString geometry
                    geom = edge_data['geometry']
                    # Extract coordinates from LineString
                    if hasattr(geom, 'coords'):
                        edge_coords = list(geom.coords)
                        # Add all geometry points except the first (already added)
                        detailed_coords.extend(edge_coords[1:])
                    else:
                        # Fallback to node coordinates
                        v_coord = (self.G.nodes[v]['x'], self.G.nodes[v]['y'])
                        detailed_coords.append(v_coord)
                else:
                    # No geometry: use node coordinates
                    v_coord = (self.G.nodes[v]['x'], self.G.nodes[v]['y'])
                    detailed_coords.append(v_coord)
            
            # Add destination if different from last point
            if detailed_coords[-1] != dest:
                detailed_coords.append(dest)
            
            # ✅ INTERPOLATION: Add intermediate points since geometry data is missing
            detailed_coords = self._interpolate_route_geometry(detailed_coords, max_segment_km=0.05)
            
            logger.debug(f"Route computed: {len(node_route)} nodes → {len(detailed_coords)} interpolated points")
            return detailed_coords
            
        except Exception as e:
            logger.warning(f"Routing failed: {e}")
            return [origin, dest]
        
    # ============================================================================
    # Metrics (Delegate to MetricsCalculator)
    # ============================================================================
    
    def estimate_travel_time(self, route: List[Tuple[float, float]], mode: str) -> float:
        """Calculate travel time."""
        return self.metrics.calculate_travel_time(route, mode)
    
    def estimate_monetary_cost(self, route: List[Tuple[float, float]], mode: str) -> float:
        """Calculate monetary cost."""
        return self.metrics.calculate_cost(route, mode)
    
    def estimate_emissions(self, route: List[Tuple[float, float]], mode: str) -> float:
        """Calculate emissions (flat terrain)."""
        return self.metrics.calculate_emissions(route, mode)
    
    def estimate_emissions_with_elevation(
        self,
        route: List[Tuple[float, float]],
        mode: str
    ) -> float:
        """Calculate emissions with elevation adjustments."""
        return self.metrics.calculate_emissions_with_elevation(route, mode, self.graph_manager)
    
    def estimate_comfort(self, route: List[Tuple[float, float]], mode: str) -> float:
        """Calculate comfort score."""
        return self.metrics.calculate_comfort(route, mode)
    
    def estimate_risk(self, route: List[Tuple[float, float]], mode: str) -> float:
        """Calculate risk score."""
        return self.metrics.calculate_risk(route, mode)
    
    def get_speed_km_min(self, mode: str) -> float:
        """Get speed in km per minute."""
        return self.metrics.get_speed_km_min(mode)
    
    # ============================================================================
    # Movement (Local Implementation)
    # ============================================================================
    
    def advance_along_route(
        self,
        route: List[Tuple[float, float]],
        current_index: int,
        offset_km: float,
        mode: str
    ) -> Tuple[int, float, Tuple[float, float]]:
        """
        Advance agent along route by one time step.
        
        Args:
            route: Route coordinates
            current_index: Current segment index
            offset_km: Distance already traveled on current segment
            mode: Transport mode
        
        Returns:
            Tuple of (new_index, new_offset_km, current_position)
        """
        if not route or len(route) < 2:
            return 0, 0.0, route[0] if route else (0.0, 0.0)
        
        # Distance to travel this step
        remaining = self.get_speed_km_min(mode) * self.step_minutes
        
        i = max(0, min(current_index, len(route) - 2))
        off = max(0.0, offset_km)
        
        while remaining > 1e-9 and i < len(route) - 1:
            p1, p2 = route[i], route[i + 1]
            seg_len = segment_distance_km(p1, p2)
            left_on_seg = max(0.0, seg_len - off)
            
            if remaining < left_on_seg:
                # Stop partway through segment
                new_pos = interpolate_along_segment(p1, p2, off + remaining)
                return i, off + remaining, new_pos
            else:
                # Complete this segment and continue
                remaining -= left_on_seg
                i += 1
                off = 0.0
        
        # Reached end of route
        return len(route) - 2, 0.0, route[-1]
    
    def densify_route(
        self,
        route: List[Tuple[float, float]],
        step_meters: float = 20.0
    ) -> List[Tuple[float, float]]:
        """Add intermediate points for smooth visualization."""
        return densify_route(route, step_meters)
    
    # ============================================================================
    # Utility Methods (Backward Compatibility)
    # ============================================================================
    
    def get_random_node_coords(self) -> Optional[Tuple[float, float]]:
        """Get random node coordinates from graph."""
        if not self.graph_loaded:
            return None
        
        nodes = list(self.G.nodes(data=True))
        if not nodes:
            return None
        
        _, data = random.choice(nodes)
        return (float(data.get('x')), float(data.get('y')))
    
    def get_random_origin_dest(self, min_distance_km=0.5, max_attempts=20):
        """
        Get random origin-destination pair from graph.
        
        ✅ FIX: Ensures minimum distance and validates connectivity
        ✅ FIX: Uses cryptographic RNG for better spatial distribution
        """
        if not self.graph_loaded:
            logger.warning("Graph not loaded for random OD generation")
            return None
        
        graph = self.graph_manager.get_graph('drive')
        if graph is None or graph.number_of_nodes() < 2:
            logger.warning("No 'drive' graph available for random OD")
            return None
        
        nodes = list(graph.nodes())
        
        from simulation.spatial.coordinate_utils import haversine_km
        import networkx as nx
        
        # ✅ FIX: Use cryptographic RNG instead of basic random
        crypto_rng = random.Random(secrets.randbits(128))
        
        for _ in range(max_attempts):  # _ instead of attempt (unused variable)
            # Pick 2 random nodes using crypto RNG
            node1, node2 = crypto_rng.sample(nodes, 2)
            
            # Get coordinates
            origin = (graph.nodes[node1]['x'], graph.nodes[node1]['y'])
            dest = (graph.nodes[node2]['x'], graph.nodes[node2]['y'])
            
            # Check distance
            distance = haversine_km(origin, dest)
            
            if distance < min_distance_km:
                continue  # Too close
            
            # ✅ CRITICAL: Verify path exists
            try:
                path = nx.shortest_path(graph, node1, node2, weight='length')
                if len(path) >= 2:
                    logger.debug(f"Generated OD pair: {distance:.1f}km apart")
                    return (origin, dest)
            except nx.NetworkXNoPath:
                continue  # No path, try again
        
        logger.error(f"Failed to generate valid OD pair after {max_attempts} attempts!")
        logger.error("  This may indicate graph connectivity issues or bbox too small")
        return None
    
    def get_graph_stats(self) -> dict:
        """Get graph statistics."""
        return self.graph_manager.get_stats()
    
    def precompute_nearest_nodes(self, points: List[Tuple[float, float]]) -> None:
        """Precompute nearest nodes for list of points."""
        self.graph_manager.precompute_nearest_nodes(points)
    
    def clear_cache(self) -> None:
        """Clear graph cache."""
        self.graph_manager.clear_cache()
    
    # ============================================================================
    # Internal Methods (Backward Compatibility)
    # ============================================================================
    
    def _distance(self, route: List[Tuple[float, float]]) -> float:
        """Calculate route distance (backward compatibility)."""
        return route_distance_km(route)
    
    def _segment_distance_km(
        self,
        coord1: Tuple[float, float],
        coord2: Tuple[float, float]
    ) -> float:
        """Calculate segment distance (backward compatibility)."""
        return segment_distance_km(coord1, coord2)
    
    def _is_lonlat(self, coord: Tuple[float, float]) -> bool:
        """Check if valid lon/lat (backward compatibility)."""
        return is_valid_lonlat(coord)
    
    def _get_nearest_node(
        self,
        coord: Tuple[float, float],
        network_type: str = 'all'
    ) -> Optional[int]:
        """Get nearest node (backward compatibility)."""
        return self.graph_manager.get_nearest_node(coord, network_type)
    
    @staticmethod
    def _haversine_km(
        coord1: Tuple[float, float],
        coord2: Tuple[float, float]
    ) -> float:
        """Haversine distance (backward compatibility)."""
        from simulation.spatial.coordinate_utils import haversine_km
        return haversine_km(coord1, coord2)
    
    def _haversine_m(
        self,
        coord1: Tuple[float, float],
        coord2: Tuple[float, float]
    ) -> float:
        """Haversine in meters (backward compatibility)."""
        from simulation.spatial.coordinate_utils import haversine_m
        return haversine_m(coord1, coord2)
    
    def _get_cache_key(
        self,
        place: Optional[str],
        bbox: Optional[Tuple],
        network_type: str
    ) -> str:
        """Get cache key (backward compatibility for tests)."""
        return self.graph_manager._get_cache_key(place, bbox, network_type)
    
    @property
    def cache_dir(self) -> Path:
        """Get cache directory (backward compatibility)."""
        return self.graph_manager.cache_dir
    
    # ============================================================================
    # Congestion Management
    # ============================================================================
    
    def update_agent_congestion(
        self,
        agent_id: str,
        current_edge: Optional[Tuple[int, int, int]] = None
    ) -> None:
        """
        Update agent's position for congestion tracking.
        
        Args:
            agent_id: Agent identifier
            current_edge: Current edge (u, v, key) or None if not on network
        """
        if self.congestion_manager:
            self.congestion_manager.update_agent_position(agent_id, current_edge)
    
    def get_congestion_stats(self) -> dict:
        """Get congestion statistics."""
        if self.congestion_manager:
            return self.congestion_manager.get_stats()
        return {'congestion_enabled': False}
    
    def advance_congestion_time(self, hours: float = None) -> None:
        """Advance congestion simulation time."""
        if self.congestion_manager:
            if hours is None:
                hours = self.step_minutes / 60.0
            self.congestion_manager.advance_time(hours)
    
    def get_congestion_heatmap(self) -> dict:
        """Get congestion factors for all edges."""
        if self.congestion_manager:
            return self.congestion_manager.get_congestion_heatmap()
        return {}