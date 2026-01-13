"""
Route and trip metrics calculator.

Calculates:
- Travel time
- Monetary cost  
- Emissions (with elevation awareness)
- Comfort
- Risk
"""

from __future__ import annotations
import logging
from typing import List, Tuple, Optional, TYPE_CHECKING, Any

if TYPE_CHECKING:
    from simulation.spatial.graph_manager import GraphManager

logger = logging.getLogger(__name__)

# Import utilities - with fallback
try:
    from simulation.spatial.coordinate_utils import route_distance_km, segment_distance_km
except ImportError:
    # Fallback if coordinate_utils not available yet
    def route_distance_km(route):
        return 0.0
    def segment_distance_km(a, b):
        return 0.0


class MetricsCalculator:
    """
    Calculates performance metrics for routes and trips.
    """
    
    def __init__(self):
        """Initialize with default mode speeds and parameters."""
        # Speed in km per minute
        self.speeds_km_min = {
            'walk': {'city': 5, 'highway': 5},
            'bike': {'city': 15, 'highway': 15},
            'bus': {'city': 20, 'highway': 60},
            'car': {'city': 30, 'highway': 100},
            'ev': {'city': 30, 'highway': 100},
            
            # Freight (existing)
            'cargo_bike': {'city': 15, 'highway': 15},
            'van_electric': {'city': 35, 'highway': 90},
            'van_diesel': {'city': 35, 'highway': 90},
            'truck_electric': {'city': 30, 'highway': 80},
            'truck_diesel': {'city': 30, 'highway': 80},
            'hgv_electric': {'city': 25, 'highway': 70},
            'hgv_diesel': {'city': 25, 'highway': 80},
            'hgv_hydrogen': {'city': 25, 'highway': 80},
            
            # Public transport
            'tram': {'city': 25, 'highway': 25},
            'local_train': {'city': 60, 'highway': 60},
            'intercity_train': {'city': 120, 'highway': 120},
            
            # Maritime
            'ferry_diesel': {'city': 35, 'highway': 35},
            'ferry_electric': {'city': 30, 'highway': 30},
            
            # Aviation
            'flight_domestic': {'city': 450, 'highway': 450},
            'flight_electric': {'city': 350, 'highway': 350},
            
            # Micro-mobility
            'e_scooter': {'city': 20, 'highway': 20},
        }
        
        # Base emissions in grams CO2 per km
        self.emissions_grams_per_km = {
            # Zero emission
            'walk': 0,
            'bike': 0,
            'cargo_bike': 0,
            'e_scooter': 0,
            'ev': 0,
            
            # NEW: Electric public transport (grid carbon)
            'tram': 30,
            'local_train': 35,
            'intercity_train': 25,
            'ferry_electric': 40,
            'flight_electric': 50,
            
            # Combustion
            'bus': 80,
            'car': 180,
            'van_diesel': 250,
            'truck_diesel': 400,
            'hgv_diesel': 800,
            'hgv_hydrogen': 100,  # Some emissions from hydrogen production
            
            # High-emission modes
            'ferry_diesel': 120,
            'flight_domestic': 250,
        }
        
        # Monetary cost (base fare + per km)
        self.cost_params = {
            'walk': {'base': 0, 'per_km': 0},
            'bike': {'base': 0, 'per_km': 0},
            'bus': {'base': 2.5, 'per_km': 0.10},
            'car': {'base': 1.0, 'per_km': 0.40},
            'ev': {'base': 1.0, 'per_km': 0.15},
            
            # Freight (existing)
            'cargo_bike': {'base': 0.5, 'per_km': 0.05},
            'van_electric': {'base': 2.0, 'per_km': 0.20},
            'van_diesel': {'base': 2.0, 'per_km': 0.35},
            'truck_electric': {'base': 5.0, 'per_km': 0.40},
            'truck_diesel': {'base': 5.0, 'per_km': 0.60},
            'hgv_electric': {'base': 10.0, 'per_km': 0.80},
            'hgv_diesel': {'base': 10.0, 'per_km': 1.20},
            'hgv_hydrogen': {'base': 10.0, 'per_km': 1.00},
            
            # Public transport
            'tram': {'base': 2.0, 'per_km': 0.08},
            'local_train': {'base': 3.0, 'per_km': 0.12},
            'intercity_train': {'base': 10.0, 'per_km': 0.15},
            
            # Maritime
            'ferry_diesel': {'base': 15.0, 'per_km': 0.25},
            'ferry_electric': {'base': 12.0, 'per_km': 0.20},
            
            # Aviation
            'flight_domestic': {'base': 50.0, 'per_km': 0.20},
            'flight_electric': {'base': 60.0, 'per_km': 0.15},
            
            # Micro-mobility
            'e_scooter': {'base': 1.0, 'per_km': 0.25},
        }
        
        # Comfort scores (0-1, higher = more comfortable)
        self.comfort_scores = {
            'walk': 0.5,
            'bike': 0.6,
            'bus': 0.7,
            'car': 0.8,
            'ev': 0.85,
            'van_electric': 0.75,  # Better than original 0.7
            'van_diesel': 0.75,
        }
        
        # Risk scores (0-1, higher = more risky)
        self.risk_scores = {
            'walk': 0.2,
            'bike': 0.3,
            'bus': 0.15,
            'car': 0.25,
            'ev': 0.20,
            'van_electric': 0.25,
            'van_diesel': 0.25,
        }
    
    def calculate_distance(self, route: List[Tuple[float, float]]) -> float:
        """
        Calculate total route distance.
        
        Args:
            route: List of (lon, lat) coordinates
        
        Returns:
            Distance in kilometers
        """
        return route_distance_km(route)
    
    def calculate_travel_time(
        self, 
        route: List[Tuple[float, float]], 
        mode: str
    ) -> float:
        """
        Calculate travel time for route.
        
        Args:
            route: List of (lon, lat) coordinates
            mode: Transport mode
        
        Returns:
            Travel time in minutes
        """
        distance_km = self.calculate_distance(route)
        speed = self.speeds_km_min.get(mode, 0.1)
        
        if speed <= 0:
            return float('inf')
        
        return distance_km / speed
    
    def calculate_cost(
        self, 
        route: List[Tuple[float, float]], 
        mode: str
    ) -> float:
        """
        Calculate monetary cost for route.
        
        Args:
            route: List of (lon, lat) coordinates
            mode: Transport mode
        
        Returns:
            Cost in currency units
        """
        params = self.cost_params.get(mode, {'base': 1.0, 'per_km': 0.0})
        distance_km = self.calculate_distance(route)
        
        return params['base'] + (params['per_km'] * distance_km)
    
    def calculate_emissions(
        self, 
        route: List[Tuple[float, float]], 
        mode: str
    ) -> float:
        """
        Calculate emissions for route (flat terrain assumption).
        
        Args:
            route: List of (lon, lat) coordinates
            mode: Transport mode
        
        Returns:
            Emissions in grams CO2e
        """
        distance_km = self.calculate_distance(route)
        emission_rate = self.emissions_grams_per_km.get(mode, 100.0)
        
        return emission_rate * distance_km
    
    def calculate_emissions_with_elevation(
        self,
        route: List[Tuple[float, float]],
        mode: str,
        graph_manager: 'GraphManager'
    ) -> float:
        """
        Calculate emissions accounting for elevation changes.
        
        Uses elevation data from graph to adjust emissions based on grade:
        - Uphill: +50% emissions per 10% grade
        - Downhill: -20% emissions per 10% grade (regenerative braking)
        
        Args:
            route: List of (lon, lat) coordinates
            mode: Transport mode
            graph_manager: GraphManager instance with elevation data
        
        Returns:
            Emissions in grams CO2e
        """
        if not graph_manager.has_elevation():
            return self.calculate_emissions(route, mode)
        
        if len(route) < 2:
            return 0.0
        
        base_rate = self.emissions_grams_per_km.get(mode, 100.0)
        network_type = self._get_network_type(mode)
        graph = graph_manager.get_graph(network_type)
        
        if graph is None:
            return self.calculate_emissions(route, mode)
        
        total_emissions = 0.0
        
        try:
            for i in range(len(route) - 1):
                p1, p2 = route[i], route[i + 1]
                
                # Get nearest nodes
                n1 = graph_manager.get_nearest_node(p1, network_type)
                n2 = graph_manager.get_nearest_node(p2, network_type)
                
                if n1 is None or n2 is None:
                    # Fallback to flat calculation
                    seg_dist = segment_distance_km(p1, p2)
                    total_emissions += base_rate * seg_dist
                    continue
                
                # Get elevations
                elev1 = graph.nodes[n1].get('elevation', 0)
                elev2 = graph.nodes[n2].get('elevation', 0)
                
                # Calculate segment distance and grade
                seg_dist = segment_distance_km(p1, p2)
                elev_change = elev2 - elev1  # meters
                grade = elev_change / (seg_dist * 1000) if seg_dist > 0 else 0
                
                # Adjustment factor based on grade
                if grade > 0:  # Uphill
                    factor = 1.0 + (5.0 * grade)  # +50% per 10% grade
                else:  # Downhill
                    factor = 1.0 + (2.0 * grade)  # -20% per 10% grade
                    factor = max(0.5, factor)     # Min 50% of base
                
                # Clamp to reasonable range
                factor = max(0.5, min(2.0, factor))
                
                seg_emissions = base_rate * seg_dist * factor
                total_emissions += seg_emissions
        
        except Exception as e:
            logger.warning(f"Elevation-aware calculation failed: {e}")
            return self.calculate_emissions(route, mode)
        
        return total_emissions
    
    def calculate_comfort(
        self, 
        route: List[Tuple[float, float]], 
        mode: str
    ) -> float:
        """
        Calculate comfort score for route.
        
        Args:
            route: List of (lon, lat) coordinates
            mode: Transport mode
        
        Returns:
            Comfort score (0-1, higher = more comfortable)
        """
        return self.comfort_scores.get(mode, 0.5)
    
    def calculate_risk(
        self, 
        route: List[Tuple[float, float]], 
        mode: str
    ) -> float:
        """
        Calculate risk score for route.
        
        Args:
            route: List of (lon, lat) coordinates
            mode: Transport mode
        
        Returns:
            Risk score (0-1, higher = more risky)
        """
        return self.risk_scores.get(mode, 0.2)
    
    def get_speed_km_min(self, mode: str) -> float:
        """Get speed in km per minute for mode."""
        return self.speeds_km_min.get(mode, 0.1)
    
    @staticmethod
    def _get_network_type(mode: str) -> str:
        """Map transport mode to OSM network type."""
        mode_network_map = {
            'walk': 'walk',
            'bike': 'bike',
            'bus': 'drive',
            'car': 'drive',
            'ev': 'drive',
        }
        return mode_network_map.get(mode, 'all')