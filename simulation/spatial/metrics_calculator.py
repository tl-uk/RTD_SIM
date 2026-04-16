"""
simulation/spatial/metrics_calculator.py

This module implements the MetricsCalculator class which calculates various performance 
metrics for routes and trips in the simulation. It provides methods to compute travel 
time, monetary cost, emissions (with elevation awareness), comfort, and risk for a given 
route and transport mode based on predefined parameters and assumptions. 

The MetricsCalculator uses utility functions for distance calculations and can integrate
with the GraphManager to access elevation data for more accurate emissions calculations.

Route and trip metrics calculator.

Calculates:
- Travel time
- Monetary cost  
- Emissions (with elevation awareness)
- Comfort
- Risk

NOTE: speeds_km_min now uses simple floats instead of nested dicts

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

# ============================================================
# Metrics Calculator Class
# ============================================================
class MetricsCalculator:
    """
    Calculates performance metrics for routes and trips.
    """
    
    def __init__(self):
        """Initialize with default mode speeds and parameters."""
        # Speed in km per MINUTE (simple floats, not nested dicts)
        self.speeds_km_min = {
            # Active mobility
            'walk': 0.083,       # 5 km/h = 0.083 km/min
            'bike': 0.25,        # 15 km/h = 0.25 km/min
            'cargo_bike': 0.20,  # 12 km/h = 0.20 km/min
            'e_scooter': 0.33,   # 20 km/h = 0.33 km/min
            
            # Passenger vehicles
            'bus': 0.33,         # 20 km/h city average
            'car': 0.5,          # 30 km/h city average
            'ev': 0.5,           # 30 km/h city average
            'taxi_ev': 0.45,     # Slightly faster than buses, traffic limited
            'taxi_diesel': 0.45,
            
            # Light commercial (Phase 4.5F)
            'van_electric': 0.58,   # 35 km/h = 0.58 km/min
            'van_diesel': 0.58,     # 35 km/h = 0.58 km/min
            
            # Medium freight (Phase 4.5F)
            'truck_electric': 0.50, # 30 km/h = 0.50 km/min
            'truck_diesel': 0.50,   # 30 km/h = 0.50 km/min
            
            # Heavy freight (Phase 4.5F)
            'hgv_electric': 0.42,   # 25 km/h = 0.42 km/min
            'hgv_diesel': 0.42,     # 25 km/h = 0.42 km/min
            'hgv_hydrogen': 0.42,   # 25 km/h = 0.42 km/min
            
            # Public transport (Phase 4.5G)
            'tram': 0.42,           # 25 km/h = 0.42 km/min
            'local_train': 1.0,     # 60 km/h = 1.0 km/min
            'intercity_train': 2.0, # 120 km/h = 2.0 km/min
            # freight_rail: 50 km/h average (mixed-traffic UK freight paths,
            # slower than passenger — Network Rail LoS C/D paths).
            'freight_rail': 0.83,   # 50 km/h = 0.83 km/min
            
            # Maritime (Phase 4.5G)
            'ferry_diesel': 0.58,   # 35 km/h = 0.58 km/min
            'ferry_electric': 0.50, # 30 km/h = 0.50 km/min
            
            # Aviation (Phase 4.5G)
            'flight_domestic': 7.5,    # 450 km/h = 7.5 km/min
            'flight_electric': 5.83,   # 350 km/h = 5.83 km/min
        }
        
        # Base emissions in grams CO2 per km
        self.emissions_grams_per_km = {
            # Zero emission
            'walk': 0,
            'bike': 0,
            'cargo_bike': 0,
            'e_scooter': 0,
            'ev': 0,
            'taxi_ev': 0,
            'van_electric': 0,
            'truck_electric': 0,
            'hgv_electric': 0,
            
            # Electric public transport (grid carbon)
            'tram': 30,
            'local_train': 35,
            'intercity_train': 25,
            # freight_rail: UK electrified freight.  Grid carbon intensity 2026
            # ≈ 150 g CO₂/kWh (CCC 2024); ~0.023 kWh/tonne-km for a loaded train
            # → effectively ~35 g/km operator perspective (consistent with modes.py).
            'freight_rail': 35,
            'ferry_electric': 40,
            'flight_electric': 50,
            
            # Combustion
            'bus': 80,
            'car': 180,
            'taxi_diesel': 160,
            'van_diesel': 250,
            'truck_diesel': 400,
            'hgv_diesel': 800,
            'hgv_hydrogen': 100,
            
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
            'ev': {'base': 1.0, 'per_km': 0.22},
            # Note: For the *driver*, cost is running cost. 
            # ev per_km = 0.22: electricity ~8p + servicing ~7p + tyres ~7p (BEIS 2024).
            # Capital purchase premium is handled separately in bdi_planner._EV_CAPITAL_PER_KM
            # so this figure covers operating cost only — not double-counted.
            'taxi_ev': {'base': 1.0, 'per_km': 0.22},
            'taxi_diesel': {'base': 1.0, 'per_km': 0.35},
            
            # Freight
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
            # freight_rail: Network Rail slot fee + energy.  Per-tonne-km rates vary
            # widely; £0.06/km reflects a typical electrified intermodal movement
            # amortised across a standard 1,500-tonne train — relevant for the
            # RailFreightAgent operator perspective.
            'freight_rail': {'base': 8.0, 'per_km': 0.06},
            
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
            'taxi_ev': 0.8, 'taxi_diesel': 0.8,
            'van_electric': 0.75,
            'van_diesel': 0.75,
            'truck_electric': 0.70,
            'truck_diesel': 0.70,
            'hgv_electric': 0.65,
            'hgv_diesel': 0.65,
            'cargo_bike': 0.55,
            
            # Public transport — high comfort but variable reliability penalty
            # applied via transfer boarding overhead in calculate_travel_time
            'tram':            0.75,
            'local_train':     0.72,   # suburban services: standing, crowds
            'intercity_train': 0.82,   # seated, smoother ride
            'freight_rail':    0.55,   # operator perspective: paperwork/waiting
            # Maritime
            'ferry_diesel':    0.65,
            'ferry_electric':  0.70,
            # Aviation
            'flight_domestic': 0.70,
            'flight_electric': 0.72,
            # Micro
            'e_scooter': 0.55,
        }
        
        # Risk scores (0-1, higher = more risky)
        self.risk_scores = {
            'walk': 0.2,
            'bike': 0.3,
            'bus': 0.15,
            'car': 0.25,
            'ev': 0.20,
            'taxi_ev': 0.25, 'taxi_diesel': 0.25,
            'van_electric': 0.25,
            'van_diesel': 0.25,
            'truck_electric': 0.30,
            'truck_diesel': 0.30,
            'hgv_electric': 0.35,
            'hgv_diesel': 0.35,
            'cargo_bike': 0.35,
            # Public transport — generally safe but schedule-risk
            'tram':            0.12,
            'local_train':     0.10,
            'intercity_train': 0.08,
            'freight_rail':    0.15,
            # Maritime / aviation — low personal risk, high disruption risk
            'ferry_diesel':    0.18,
            'ferry_electric':  0.16,
            'flight_domestic': 0.12,
            'flight_electric': 0.14,
            # Micro
            'e_scooter': 0.35,
        }
    
    # ============================================================
    # Metric Calculation Methods
    # ============================================================
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

        For abstract rail/ferry/air routes (2-point straight line), applies:
          1. Detour factor — tracks/routes are not straight lines.
             Rail lines in the UK average ~20% longer than crow-flies.
          2. Boarding penalty — walk to station + wait + board.
             Omitting this made rail artificially ~5x cheaper than road.

        These corrections bring rail/ferry/air into realistic competition
        with road modes so the BDI cost function can model true modal shift.
        """
        distance_km = self.calculate_distance(route)
        speed = self.speeds_km_min.get(mode, 0.1)

        if speed <= 0:
            return float('inf')

        base_time = distance_km / speed

        # ── Abstract route correction ─────────────────────────────────────────
        # Abstract routes have exactly 2 waypoints (origin, dest).
        # All real OSMnx road routes have many more points.
        # Only apply to modes that are genuinely abstract (no graph geometry).
        #
        # NOTE: 'tram' is NOT in this set.  Tram is now real-routed via the
        # OSM railway=tram graph (environment_setup step 3.5) and produces
        # many-point routes.  Adding boarding overhead for tram is handled
        # below as an unconditional block that applies regardless of route
        # length, since walking to a tram stop + waiting is always present.
        _ABSTRACT_MODES = {
            'local_train', 'intercity_train', 'freight_rail',
            'ferry_diesel', 'ferry_electric',
            'flight_domestic', 'flight_electric',
        }
        if mode in _ABSTRACT_MODES and len(route) <= 3:
            # Detour factor: straight-line → realistic route distance
            # Rail: track geometry adds ~20%; ferry: near-straight; air: ~2%
            _DETOUR = {
                'local_train':     1.25,   # city suburban services are indirect
                'intercity_train': 1.18,   # intercity more direct but not straight
                'freight_rail':    1.20,
                'ferry_diesel':    1.05,
                'ferry_electric':  1.05,
                'flight_domestic': 1.02,
                'flight_electric': 1.02,
            }
            detour = _DETOUR.get(mode, 1.15)
            base_time *= detour

            # Boarding penalty (minutes): walk to stop + wait + board/alight
            # This is the key missing cost that was letting rail "teleport".
            # Values are empirical UK averages (DfT 2023 generalised cost studies).
            _BOARDING_MIN = {
                'local_train':     20.0,   # walk to station + 8 min wait + board
                'intercity_train': 25.0,   # longer station access + 10 min wait
                'freight_rail':    30.0,   # terminal drayage + loading time
                'ferry_diesel':    35.0,   # port access + check-in + boarding
                'ferry_electric':  35.0,
                'flight_domestic': 75.0,   # airport access + check-in + security
                'flight_electric': 75.0,
            }
            boarding = _BOARDING_MIN.get(mode, 20.0)
            base_time += boarding

        # ── Tram boarding overhead (unconditional) ────────────────────────────
        # Tram has real geometry via the OSM tram graph, so len(route) >> 3 and
        # the abstract block above never fires.  But boarding a tram still has a
        # fixed overhead: walk to nearest stop (~4 min at Edinburgh tram stop
        # spacing of ~600 m) + average wait (~4.5 min at 9-min peak headway).
        # This is separate from the access/egress walk legs produced by the
        # router — those cover the agent's home→stop walk; this covers the
        # stop-level dwell time that the BDI cost function must see.
        if mode == 'tram':
            base_time += 9.0   # 4 min walk-on-platform + 4.5 min average wait + 0.5 min buffer

        return base_time

    def calculate_cost(
        self, 
        route: List[Tuple[float, float]], 
        mode: str
    ) -> float:
        """
        Calculate monetary cost for route.

        For abstract rail/ferry/air routes uses the distance-based fare params
        already in cost_params (which have realistic base fares).  The distance
        used is the straight-line distance × detour factor so cost is consistent
        with travel time calculation.
        """
        params = self.cost_params.get(mode, {'base': 1.0, 'per_km': 0.0})
        distance_km = self.calculate_distance(route)

        # Apply the same detour factor as calculate_travel_time so monetary
        # cost is proportional to realistic trip length, not straight-line.
        _ABSTRACT_MODES = {
            'local_train', 'intercity_train', 'freight_rail',
            'ferry_diesel', 'ferry_electric',
            'flight_domestic', 'flight_electric',
        }
        if mode in _ABSTRACT_MODES and len(route) <= 3:
            _DETOUR = {
                'local_train': 1.25, 'intercity_train': 1.18,
                'freight_rail': 1.20,
                'ferry_diesel': 1.05, 'ferry_electric': 1.05,
                'flight_domestic': 1.02, 'flight_electric': 1.02,
            }
            distance_km *= _DETOUR.get(mode, 1.15)

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
                
                n1 = graph_manager.get_nearest_node(p1, network_type)
                n2 = graph_manager.get_nearest_node(p2, network_type)
                
                if n1 is None or n2 is None:
                    seg_dist = segment_distance_km(p1, p2)
                    total_emissions += base_rate * seg_dist
                    continue
                
                elev1 = graph.nodes[n1].get('elevation', 0)
                elev2 = graph.nodes[n2].get('elevation', 0)
                
                seg_dist = segment_distance_km(p1, p2)
                elev_change = elev2 - elev1
                grade = elev_change / (seg_dist * 1000) if seg_dist > 0 else 0
                
                if grade > 0:
                    factor = 1.0 + (5.0 * grade)
                else:
                    factor = 1.0 + (2.0 * grade)
                    factor = max(0.5, factor)
                
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
            'taxi_ev': 'drive',
            'taxi_diesel': 'drive',
            'van_electric': 'drive',
            'van_diesel': 'drive',
            'truck_electric': 'drive',
            'truck_diesel': 'drive',
            'hgv_electric': 'drive',
            'hgv_diesel': 'drive',
            'hgv_hydrogen': 'drive',
        }
        return mode_network_map.get(mode, 'drive')