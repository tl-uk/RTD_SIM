"""
simulation/route_alternative.py

RouteAlternative data class for Phase 2.2

Represents a single route option with computed metrics.
Multiple alternatives can be compared and ranked.
"""

from __future__ import annotations
from typing import Tuple, List, Dict, Optional, TYPE_CHECKING
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from simulation.spatial_environment import SpatialEnvironment


@dataclass
class RouteAlternative:
    """
    Represents one route option with all computed metrics.
    
    Attributes:
        route: List of (lon, lat) coordinates
        mode: Transport mode ('walk', 'bike', 'bus', 'car', 'ev')
        variant: Route type ('shortest', 'fastest', 'safest', 'greenest', 'scenic')
        metrics: Computed performance metrics
    """
    route: List[Tuple[float, float]]
    mode: str
    variant: str
    metrics: Dict[str, float] = field(default_factory=dict)
    
    def compute_metrics(self, env: 'SpatialEnvironment') -> None:
        """
        Calculate all metrics for this route.

        Metrics computed:
          distance, time, cost, emissions, comfort, risk  — core
          monetary_cost                                    — fuel + fares only (cheapest variant)
          lifecycle_co2_kg                                 — operational + embodied carbon (decarbonisation variant)
        """
        if not self.route or len(self.route) < 2:
            self.metrics = {
                'distance': 0.0, 'time': 0.0, 'cost': 0.0,
                'emissions': 0.0, 'comfort': 0.0, 'risk': 0.0,
                'monetary_cost': 0.0, 'lifecycle_co2_kg': 0.0,
            }
            return
        
        # Core metrics
        self.metrics['distance']  = env._distance(self.route)
        self.metrics['time']      = env.estimate_travel_time(self.route, self.mode)
        self.metrics['cost']      = env.estimate_monetary_cost(self.route, self.mode)
        self.metrics['comfort']   = env.estimate_comfort(self.route, self.mode)
        self.metrics['risk']      = env.estimate_risk(self.route, self.mode)
        
        # Use elevation-aware emissions if available
        if env.has_elevation:
            self.metrics['emissions'] = env.estimate_emissions_with_elevation(self.route, self.mode)
        else:
            self.metrics['emissions'] = env.estimate_emissions(self.route, self.mode)
        
        # ── Research metrics ─────────────────────────────────────────────────
        # monetary_cost: fuel/energy/fares only (no time valuation).
        # Used by the 'cheapest' variant for "lowest cost to decarbonisation".
        self.metrics['monetary_cost'] = self.metrics['cost']

        # lifecycle_co2_kg: operational + embodied carbon per trip.
        # Embodied carbon (vehicle manufacture amortised over lifetime km)
        # — SMMT / Ricardo Energy & Environment lifecycle data (2023).
        _EMBODIED_KG_KM = {
            'car': 0.060, 'ev': 0.085,
            'bus': 0.020, 'tram': 0.015,
            'van_diesel': 0.040, 'van_electric': 0.055,
            'truck_diesel': 0.035, 'truck_electric': 0.045,
            'hgv_diesel': 0.025, 'hgv_electric': 0.035, 'hgv_hydrogen': 0.030,
            'walk': 0.0, 'bike': 0.001, 'e_scooter': 0.002, 'cargo_bike': 0.002,
            'local_train': 0.010, 'intercity_train': 0.008, 'freight_rail': 0.012,
            'ferry_diesel': 0.018, 'ferry_electric': 0.014,
            'flight_domestic': 0.025, 'flight_electric': 0.020,
        }
        dist_km = self.metrics['distance']
        operational_kg = self.metrics['emissions'] / 1000.0   # g → kg
        embodied_kg = _EMBODIED_KG_KM.get(self.mode, 0.030) * dist_km
        self.metrics['lifecycle_co2_kg'] = operational_kg + embodied_kg

        # Waypoint count
        self.metrics['waypoints'] = len(self.route)

        # Elevation metrics if available
        if env.has_elevation:
            self._compute_elevation_metrics(env)
    
    def _compute_elevation_metrics(self, env: 'SpatialEnvironment') -> None:
        """Compute elevation-specific metrics."""
        network_type = env.mode_network_types.get(self.mode, 'all')
        graph = env.mode_graphs.get(network_type, env.G)
        
        if graph is None or not env.has_elevation:
            return
        
        elevations = []
        for coord in self.route:
            node = env._get_nearest_node(coord, network_type)
            if node is not None:
                elev = graph.nodes[node].get('elevation')
                if elev is not None:
                    elevations.append(elev)
        
        if elevations:
            self.metrics['elevation_min'] = min(elevations)
            self.metrics['elevation_max'] = max(elevations)
            self.metrics['elevation_gain'] = sum(max(0, elevations[i+1] - elevations[i]) 
                                                  for i in range(len(elevations)-1))
            self.metrics['elevation_loss'] = sum(max(0, elevations[i] - elevations[i+1]) 
                                                  for i in range(len(elevations)-1))
    
    def score(self, weights: Dict[str, float]) -> float:
        """
        Score this route based on weighted preferences.

        Standard metrics: time, cost, emissions, comfort, risk, distance
        Research metrics:
          monetary_cost    — fuel + fares only; use for 'cheapest' variant
          lifecycle_co2_kg — operational + embodied carbon; use for 'decarbonisation' variant

        Args:
            weights: metric → importance weight.
                     Negative weights = minimise, positive = maximise.

        Returns:
            Weighted score (higher = better).

        Examples:
            # Cheapest: minimise monetary cost
            weights = {'monetary_cost': -1.0, 'time': -0.2}

            # Decarbonisation: minimise lifecycle CO₂
            weights = {'lifecycle_co2_kg': -1.0, 'time': -0.3, 'cost': -0.2}

            # Balanced
            weights = {'time': -0.8, 'cost': -0.3, 'comfort': 0.5}
        """
        score = 0.0
        
        for metric, weight in weights.items():
            if metric in self.metrics:
                score += self.metrics[metric] * weight
        
        return score
    
    def __repr__(self) -> str:
        """String representation."""
        return (f"RouteAlternative(mode={self.mode}, variant={self.variant}, "
                f"distance={self.metrics.get('distance', 0):.2f}km, "
                f"time={self.metrics.get('time', 0):.1f}min)")
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            'route': self.route,
            'mode': self.mode,
            'variant': self.variant,
            'metrics': self.metrics,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'RouteAlternative':
        """Create from dictionary."""
        return cls(
            route=data['route'],
            mode=data['mode'],
            variant=data['variant'],
            metrics=data.get('metrics', {})
        )


def rank_alternatives(
    alternatives: List[RouteAlternative],
    weights: Dict[str, float]
) -> List[Tuple[float, RouteAlternative]]:
    """
    Rank route alternatives by weighted score.
    
    Args:
        alternatives: List of RouteAlternative objects
        weights: Scoring weights (negative=minimize, positive=maximize)
    
    Returns:
        List of (score, alternative) tuples, sorted by score (best first)
    
    Example:
        >>> weights = {'time': -1.0, 'emissions': -0.5, 'comfort': 0.3}
        >>> ranked = rank_alternatives(alternatives, weights)
        >>> best_route = ranked[0][1]  # Get alternative with highest score
    """
    scored = [(alt.score(weights), alt) for alt in alternatives]
    scored.sort(reverse=True, key=lambda x: x[0])
    return scored

def cheapest_route(
    alternatives: List[RouteAlternative],
    time_weight: float = 0.2,
) -> Optional[RouteAlternative]:
    """
    Return the alternative with the lowest monetary cost.

    Used for "lowest cost to decarbonisation" research analysis.
    Optionally penalises very slow routes via time_weight.

    Args:
        alternatives: Computed RouteAlternative list (with metrics).
        time_weight:  Small penalty for travel time (default 0.2).

    Returns:
        Cheapest RouteAlternative or None.
    """
    if not alternatives:
        return None
    ranked = rank_alternatives(
        alternatives,
        weights={'monetary_cost': -1.0, 'time': -time_weight},
    )
    return ranked[0][1] if ranked else None


def lowest_carbon_route(
    alternatives: List[RouteAlternative],
    time_weight: float = 0.3,
) -> Optional[RouteAlternative]:
    """
    Return the alternative with the lowest lifecycle CO₂.

    Used for "resilience to decarbonisation" research analysis.
    Uses lifecycle_co2_kg (operational + embodied) not just operational
    emissions so EVs with high embodied carbon are correctly modelled.

    Args:
        alternatives: Computed RouteAlternative list (with metrics).
        time_weight:  Small penalty for travel time (default 0.3).

    Returns:
        Lowest-carbon RouteAlternative or None.
    """
    if not alternatives:
        return None
    ranked = rank_alternatives(
        alternatives,
        weights={'lifecycle_co2_kg': -1.0, 'time': -time_weight},
    )
    return ranked[0][1] if ranked else None


def filter_pareto_optimal(alternatives: List[RouteAlternative]) -> List[RouteAlternative]:
    """
    Filter to Pareto-optimal routes (no route is strictly better on all metrics).
    
    A route is Pareto-optimal if there's no other route that is better in
    all objectives (time, cost, emissions, etc.).
    
    Args:
        alternatives: List of RouteAlternative objects
    
    Returns:
        Subset of alternatives that are Pareto-optimal
    """
    if not alternatives:
        return []
    
    # Objectives to minimize (lower is better)
    objectives = ['time', 'cost', 'emissions', 'risk', 'distance']
    
    pareto_optimal = []
    
    for alt in alternatives:
        is_dominated = False
        
        for other in alternatives:
            if alt is other:
                continue
            
            # Check if 'other' dominates 'alt'
            # (better or equal on all objectives, strictly better on at least one)
            better_count = 0
            equal_count = 0
            worse_count = 0
            
            for obj in objectives:
                if obj not in alt.metrics or obj not in other.metrics:
                    continue
                
                if other.metrics[obj] < alt.metrics[obj]:
                    better_count += 1
                elif other.metrics[obj] == alt.metrics[obj]:
                    equal_count += 1
                else:
                    worse_count += 1
            
            # 'other' dominates 'alt' if it's better on at least one and not worse on any
            if better_count > 0 and worse_count == 0:
                is_dominated = True
                break
        
        if not is_dominated:
            pareto_optimal.append(alt)
    
    return pareto_optimal
