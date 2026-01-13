"""
SpatialEnvironment - Refactored as Thin Facade (Phase 2.2 Refactored)

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
import random
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
        """
        Initialize spatial environment.
        
        Args:
            step_minutes: Simulation time step in minutes
            cache_dir: Cache directory for graphs (default: ~/.rtd_sim_cache/osm_graphs)
            use_congestion: Enable dynamic traffic congestion (Phase 2.2b)
        """
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
    
    def add_elevation_data(self, method: str = 'opentopo', **kwargs) -> bool:
        """Add elevation data to graph."""
        return self.graph_manager.add_elevation_data(method, **kwargs)
    
    # ============================================================================
    # Routing (Delegate to Router)
    # ============================================================================
    
    def compute_route(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str
    ) -> List[Tuple[float, float]]:
        """Compute shortest path route."""
        return self.router.compute_route(agent_id, origin, dest, mode)
    
    def compute_route_alternatives(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str,
        variants: List[str] = None
    ) -> List[Any]:
        """
        Compute multiple route alternatives.
        
        Returns RouteAlternative objects with metrics already computed.
        """
        alternatives = self.router.compute_alternatives(agent_id, origin, dest, mode, variants)
        
        # Compute metrics for each alternative
        for alt in alternatives:
            if hasattr(alt, 'compute_metrics'):
                alt.compute_metrics(self)
        
        return alternatives
    
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
    
    def get_random_origin_dest(self) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
        """Get random origin-destination pair."""
        origin = self.get_random_node_coords()
        dest = self.get_random_node_coords()
        
        if origin is None or dest is None:
            return None
        
        return origin, dest
    
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
    # Congestion Management (Phase 2.2b)
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