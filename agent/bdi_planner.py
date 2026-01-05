"""
agent/bdi_planner.py - FIXED VERSION v2

CRITICAL FIX: Filter by context BEFORE filtering by distance
Otherwise freight modes get removed before they can be added!
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple

import random
import logging

logger = logging.getLogger(__name__)


@dataclass
class Action:
    mode: str
    route: List[Any]
    params: Dict[str, Any]


@dataclass
class ActionScore:
    action: Action
    cost: float
    breakdown: Optional[Dict[str, float]] = None


class BDIPlanner:
    """BDI planner with optional infrastructure awareness."""
    
    # EV constraints
    EV_RANGE_KM = {
        'ev': 350.0,
        'ev_delivery': 200.0,
        'ev_freight': 150.0,
    }
    
    CHARGING_TIME_MIN = {
        'level2': 240.0,
        'dcfast': 30.0,
        'depot': 480.0,
    }
    
    # Distance-based mode constraints
    MODE_MAX_DISTANCE_KM = {
        'walk': 5.0,
        'bike': 20.0,
        'bus': 100.0,
        'car': 500.0,
        'ev': 350.0,
        'van_electric': 200.0,
        'van_diesel': 500.0,
    }
    
    def __init__(self, infrastructure_manager: Optional[Any] = None) -> None:
        """Initialize planner."""
        self.default_modes = [
            'walk', 'bike', 'bus', 
            'car', 'ev',
            'van_electric', 'van_diesel',
        ]
        self.infrastructure = infrastructure_manager
        
        if self.infrastructure:
            logger.info("BDI planner: infrastructure-aware mode (Phase 4.5)")
        else:
            logger.info("BDI planner: basic mode (Phase 4)")
    
    @property
    def has_infrastructure(self) -> bool:
        """Check if infrastructure awareness is enabled."""
        return self.infrastructure is not None
    
    def actions_for(
        self,
        env,
        state,
        origin,
        dest,
        agent_context: Optional[Dict] = None
    ) -> List[Action]:
        """Generate possible actions with ROUTE-BASED distance filtering."""
        actions: List[Action] = []
        context = agent_context or {}
        
        # Calculate STRAIGHT-LINE distance for initial context filtering
        from simulation.spatial.coordinate_utils import haversine_km
        straight_line_distance = haversine_km(origin, dest)
        
        # Get candidate modes (use straight-line distance for initial filter)
        available_modes = self._filter_modes_by_context(context, straight_line_distance)
        
        logger.debug(f"Agent context: {context}, straight_line: {straight_line_distance:.1f}km, candidate modes: {available_modes}")
        
        for mode in available_modes:
            # Infrastructure feasibility check
            if not self._is_mode_feasible(mode, origin, dest, state, context):
                continue
            
            # Compute actual route
            route = env.compute_route(
                agent_id=getattr(state, 'agent_id', 'agent'),
                origin=origin,
                dest=dest,
                mode=mode
            )
            
            # Check ACTUAL ROUTE distance, not straight-line
            if route:
                from simulation.spatial.coordinate_utils import route_distance_km
                actual_route_distance = route_distance_km(route)
                
                # Apply strict distance constraint
                max_distance = self.MODE_MAX_DISTANCE_KM.get(mode, float('inf'))
                if actual_route_distance >= max_distance:  # Use >= for strict enforcement
                    logger.debug(f"Rejected {mode}: route {actual_route_distance:.1f}km >= max {max_distance}km")
                    continue
            
            params = {}
            
            # EV infrastructure params
            if mode in ['ev', 'van_electric'] and self.has_infrastructure:
                params = self._get_ev_params(origin, dest, route, context)
            
            actions.append(Action(mode=mode, route=route, params=params))
        
        return actions

    
    def _filter_modes_by_context(
        self, 
        context: Dict,
        trip_distance_km: float = 0.0
    ) -> List[str]:
        """
        Filter modes based on agent context AND trip distance.
        
        🆕 FIX: Use safety margin for straight-line distance
        """
        # STEP 1: Context-based filtering (unchanged)
        vehicle_required = context.get('vehicle_required', False)
        cargo_capacity = context.get('cargo_capacity', False)
        vehicle_type = context.get('vehicle_type', 'personal')
        priority = context.get('priority', 'normal')
        
        # Determine base mode set
        if priority == 'emergency':
            modes = ['car', 'ev']
        elif cargo_capacity or vehicle_required or vehicle_type == 'commercial':
            modes = ['car', 'ev', 'van_electric', 'van_diesel']
            logger.debug(f"Freight context detected: offering {modes}")
        elif context.get('luggage_present') or context.get('wheelchair_accessible'):
            modes = ['car', 'ev', 'bus']
        else:
            modes = self.default_modes.copy()
        
        # STEP 2: Distance-based filtering with SAFETY MARGIN
        if trip_distance_km > 0:
            original_modes = modes.copy()
            
            # Apply 0.65x safety margin to account for route vs straight-line
            # (Typical route distance is ~1.3-1.5x straight-line distance)
            modes = [
                m for m in modes 
                if trip_distance_km < (self.MODE_MAX_DISTANCE_KM.get(m, float('inf')) * 0.65)
            ]
            
            filtered = set(original_modes) - set(modes)
            if filtered:
                logger.debug(f"Distance filter ({trip_distance_km:.1f}km with 0.65x margin): removed {filtered}")
            
            # Fallback: Always keep at least one mode
            if not modes:
                if trip_distance_km > 50:
                    modes = ['van_diesel', 'car']
                elif trip_distance_km > 20:
                    modes = ['car', 'bus']
                else:
                    modes = ['car']
                logger.warning(f"No modes left after filtering! Using fallback: {modes}")
        
        return modes

    
    def _is_mode_feasible(
        self,
        mode: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        state,
        context: Dict
    ) -> bool:
        """Check if mode is feasible (infrastructure check)."""
        # Only check infrastructure for EVs
        if not self.has_infrastructure or mode not in ['ev', 'van_electric']:
            return True
        
        # Calculate trip distance
        from simulation.spatial.coordinate_utils import haversine_km
        trip_distance = haversine_km(origin, dest)
        
        # Determine EV type
        vehicle_type = context.get('vehicle_type', 'personal')
        if mode == 'van_electric' or vehicle_type == 'commercial':
            ev_type = 'ev_delivery'
        else:
            ev_type = 'ev'
        
        max_range = self.EV_RANGE_KM.get(ev_type, 350.0)
        
        # Range check with 90% safety margin
        if trip_distance > max_range * 0.9:
            logger.debug(f"{mode} not feasible: {trip_distance:.1f}km > {max_range*0.9:.1f}km range")
            return False
        
        # Check charger availability for long trips
        if trip_distance > max_range * 0.5:
            nearest = self.infrastructure.find_nearest_charger(
                dest, max_distance_km=5.0
            )
            if nearest is None:
                logger.debug(f"{mode} not feasible: no charger within 5km of destination")
                return False
        
        return True
    
    def _get_ev_params(
        self,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        route: List,
        context: Dict
    ) -> Dict:
        """Get EV infrastructure parameters."""
        from simulation.spatial.coordinate_utils import route_distance_km
        
        distance = route_distance_km(route)
        params = {'trip_distance_km': distance}
        
        nearest = self.infrastructure.find_nearest_charger(
            dest, charger_type='any', max_distance_km=2.0
        )
        
        if nearest:
            station_id, distance_to_charger = nearest
            params['nearest_charger'] = station_id
            params['charger_distance_km'] = distance_to_charger
            
            availability = self.infrastructure.get_charger_availability(station_id)
            params['charger_available'] = availability.get('available', False)
            params['charger_wait_min'] = availability.get('estimated_wait_min', 0)
            params['charging_cost_kwh'] = availability.get('cost_per_kwh', 0.15)
        
        return params
    
    def cost(
        self,
        action: Action,
        env,
        state,
        desires: Dict[str, float],
        agent_context: Optional[Dict] = None
    ) -> float:
        """Calculate action cost with infrastructure awareness."""
        route = action.route
        mode = action.mode
        params = action.params
        context = agent_context or {}
        
        # Get raw metrics
        time_min = env.estimate_travel_time(route, mode)
        money = env.estimate_monetary_cost(route, mode)
        comfort = env.estimate_comfort(route, mode)
        risk = env.estimate_risk(route, mode)
        emissions_g = env.estimate_emissions(route, mode)
        
        # Get desire weights
        w_time = desires.get('time', 0.5)
        w_cost = desires.get('cost', 0.3)
        w_comfort = desires.get('comfort', 0.2)
        w_risk = desires.get('risk', 0.2)
        w_eco = desires.get('eco', 0.6)
        
        # Normalize base metrics to [0,1]
        time_norm = min(1.0, time_min / 60.0)
        cost_norm = min(1.0, money / 5.0)
        emissions_norm = min(1.0, emissions_g / 500.0)
        comfort_penalty = 1.0 - comfort
        
        # Infrastructure adjustments
        infrastructure_penalty = 0.0
        
        if mode in ['ev', 'van_electric'] and self.has_infrastructure:
            # Range anxiety
            trip_distance = params.get('trip_distance_km', 0)
            vehicle_type = context.get('vehicle_type', 'personal')
            ev_type = 'ev_delivery' if vehicle_type == 'commercial' else 'ev'
            max_range = self.EV_RANGE_KM.get(ev_type, 350.0)
            range_ratio = trip_distance / max_range
            
            if range_ratio > 0.9:
                range_anxiety = desires.get('range_anxiety', 0.5)
                infrastructure_penalty += range_anxiety * 2.0
            elif range_ratio > 0.7:
                range_anxiety = desires.get('range_anxiety', 0.5)
                infrastructure_penalty += range_anxiety * 0.5
            
            # Charging availability
            if 'nearest_charger' in params:
                if not params.get('charger_available', False):
                    wait_time = params.get('charger_wait_min', 30)
                    time_norm += (wait_time / 60.0) * w_time
                    
                    if w_time > 0.7:
                        infrastructure_penalty += 0.3
                
                # Charging cost
                charging_cost_kwh = params.get('charging_cost_kwh', 0.15)
                charging_cost = (trip_distance * 0.2) * charging_cost_kwh
                cost_norm += (charging_cost / 5.0) * w_cost
                
                # Detour penalty
                detour_km = params.get('charger_distance_km', 0)
                if detour_km > 0.5:
                    time_norm += (detour_km / 30.0)
            else:
                infrastructure_penalty += 1.0
            
            # Grid stress
            if self.infrastructure:
                grid_stress = self.infrastructure.get_grid_stress_factor()
                if grid_stress > 1.0:
                    time_norm *= grid_stress
                    cost_norm *= grid_stress
        
        # Priority adjustments
        priority = context.get('priority', 'normal')
        
        if priority == 'emergency':
            w_time = 1.0
            w_cost = 0.0
            w_risk = 0.0
        elif priority == 'commercial':
            w_time = 0.7
            w_cost = 0.5
        
        # Calculate total cost
        total_cost = (
            w_time * time_norm +
            w_cost * cost_norm +
            w_comfort * comfort_penalty +
            w_risk * risk +
            w_eco * emissions_norm +
            infrastructure_penalty
        )
        
        # Add stochastic noise (±15%)
        total_cost += random.uniform(-0.15, 0.15)
        
        return total_cost
    
    def evaluate_actions(
        self,
        env,
        state,
        desires: Dict[str, float],
        origin,
        dest,
        agent_context: Optional[Dict] = None
    ) -> List[ActionScore]:
        """Evaluate all feasible actions."""
        actions = self.actions_for(env, state, origin, dest, agent_context)
        scores: List[ActionScore] = []
        
        for action in actions:
            cost = self.cost(action, env, state, desires, agent_context)
            
            breakdown = None
            if self.has_infrastructure:
                breakdown = self._calculate_cost_breakdown(action, env, desires, agent_context)
            
            scores.append(ActionScore(action=action, cost=cost, breakdown=breakdown))
        
        return scores
    
    def _calculate_cost_breakdown(
        self,
        action: Action,
        env,
        desires: Dict[str, float],
        context: Optional[Dict]
    ) -> Dict[str, float]:
        """Calculate detailed cost breakdown."""
        route = action.route
        mode = action.mode
        
        breakdown = {
            'time': env.estimate_travel_time(route, mode) / 60.0,
            'cost': env.estimate_monetary_cost(route, mode),
            'comfort': 1.0 - env.estimate_comfort(route, mode),
            'risk': env.estimate_risk(route, mode),
            'emissions': env.estimate_emissions(route, mode) / 500.0,
        }
        
        if mode in ['ev', 'van_electric']:
            breakdown['charging_wait'] = action.params.get('charger_wait_min', 0) / 60.0
            breakdown['range_anxiety'] = action.params.get('trip_distance_km', 0) / 350.0
        
        return breakdown
    
    def choose_action(self, scores: List[ActionScore]) -> Action:
        """Choose best action (lowest cost)."""
        if not scores:
            return Action(mode='walk', route=[], params={})
        
        best = min(scores, key=lambda s: s.cost)
        return best.action
    
    def explain_choice(
        self,
        chosen: Action,
        all_scores: List[ActionScore],
        desires: Dict[str, float]
    ) -> str:
        """Explain why an action was chosen (XAI)."""
        mode = chosen.mode
        
        chosen_score = next((s for s in all_scores if s.action.mode == mode), None)
        if not chosen_score:
            return f"Chose {mode} (no explanation available)"
        
        # Top desires
        top_desires = sorted(desires.items(), key=lambda x: x[1], reverse=True)[:3]
        desire_str = ', '.join(f'{k}={v:.1f}' for k, v in top_desires)
        
        explanation = (
            f"Chose {mode} because:\n"
            f"  My priorities: {desire_str}\n"
            f"  Total cost: {chosen_score.cost:.2f}\n"
        )
        
        # Infrastructure notes
        if mode in ['ev', 'van_electric'] and 'charger_wait_min' in chosen.params:
            wait = chosen.params['charger_wait_min']
            if wait > 0:
                explanation += f"  (Charging wait: {wait:.0f} min)\n"
        
        # Cost breakdown
        if chosen_score.breakdown:
            breakdown = chosen_score.breakdown
            top_costs = sorted(breakdown.items(), key=lambda x: x[1], reverse=True)[:3]
            cost_str = ', '.join(f'{k}={v:.2f}' for k, v in top_costs)
            explanation += f"  Main costs: {cost_str}\n"
        
        return explanation