"""
agent/bdi_planner.py

BDI planner with optional infrastructure awareness.

Usage:
    # Phase 4 (basic):
    planner = BDIPlanner()
    
    # Phase 4.5 (infrastructure-aware):
    planner = BDIPlanner(infrastructure_manager=infra)
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
    breakdown: Optional[Dict[str, float]] = None  # For explainability


class BDIPlanner:
    """
    BDI planner with optional infrastructure awareness.
    
    Backward compatible: Works with or without infrastructure_manager.
    """
    
    # EV constraints (Phase 4.5)
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
    
    def __init__(
        self,
        infrastructure_manager: Optional[Any] = None
    ) -> None:
        """
        Initialize planner.
        
        Args:
            infrastructure_manager: Optional InfrastructureManager for Phase 4.5
        """
        self.default_modes = ['walk', 'bike', 'bus', 'car', 'ev',
            'van_electric', 'van_diesel',  # NEW: Freight modes
        ]
        self.infrastructure = infrastructure_manager
        
        # Log which mode we're in
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
        """
        Generate possible actions.
        
        Args:
            env: SpatialEnvironment
            state: Agent state
            origin: Origin coordinates
            dest: Destination coordinates
            agent_context: Optional context (vehicle_type, priority, etc.)
        
        Returns:
            List of feasible actions
        """
        actions: List[Action] = []
        context = agent_context or {}
        
        # Filter modes based on context (Phase 4.5)
        available_modes = self._filter_modes_by_context(context)
        
        for mode in available_modes:
            # Infrastructure feasibility check (Phase 4.5)
            if not self._is_mode_feasible(mode, origin, dest, state, context):
                continue
            
            route = env.compute_route(
                agent_id=getattr(state, 'agent_id', 'agent'),
                origin=origin,
                dest=dest,
                mode=mode
            )
            
            params = {}
            
            # EV infrastructure params (Phase 4.5)
            if mode in ['ev', 'van_electric'] and self.has_infrastructure:  # ← HERE!
                params = self._get_ev_params(origin, dest, route, context)
            
            actions.append(Action(mode=mode, route=route, params=params))
        
        return actions
    
    def _filter_modes_by_context(self, context: Dict) -> List[str]:
        """Filter modes based on agent context."""
        if not context:
            return self.default_modes
        
        priority = context.get('priority', 'normal')
        vehicle_required = context.get('vehicle_required', False)
        cargo_capacity = context.get('cargo_capacity', False)
        
        modes = self.default_modes.copy()
        
        if priority == 'emergency':
            modes = ['car', 'ev']
        elif cargo_capacity or vehicle_required:
            modes = ['car', 'ev', 'bus']
        
        return modes
    
    def _is_mode_feasible(
        self,
        mode: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        state,
        context: Dict
    ) -> bool:
        """Check if mode is feasible (Phase 4.5 infrastructure check)."""
        if not self.has_infrastructure or mode != 'ev':
            return True
        
        # Calculate trip distance
        from simulation.spatial.coordinate_utils import haversine_km
        trip_distance = haversine_km(origin, dest)
        
        # Get vehicle type
        vehicle_type = context.get('vehicle_type', 'personal')
        ev_type = 'ev_delivery' if vehicle_type == 'commercial' else 'ev'

        # NEW: Determine EV type with freight support
        if mode == 'van_electric' or vehicle_type == 'commercial':
            ev_type = 'ev_delivery'
        else:
            ev_type = 'ev'

        max_range = self.EV_RANGE_KM.get(ev_type, 350.0)
        
        # Range check with 90% safety margin
        if trip_distance > max_range * 0.9:
            return False
        
        # Check charger availability for long trips
        if trip_distance > max_range * 0.5:
            nearest = self.infrastructure.find_nearest_charger(
                dest, max_distance_km=5.0
            )
            if nearest is None:
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
        """
        Calculate action cost with optional infrastructure awareness.
        """
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
        
        # ====================================================================
        # INFRASTRUCTURE ADJUSTMENTS (Phase 4.5)
        # ====================================================================
        
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
            
            # Grid stress factor
            if self.infrastructure:
                grid_stress = self.infrastructure.get_grid_stress_factor()
                if grid_stress > 1.0:
                    time_norm *= grid_stress
                    cost_norm *= grid_stress
        
        # ====================================================================
        # PRIORITY ADJUSTMENTS (Phase 4.5)
        # ====================================================================
        
        priority = context.get('priority', 'normal')
        
        if priority == 'emergency':
            w_time = 1.0
            w_cost = 0.0
            w_risk = 0.0
        elif priority == 'commercial':
            w_time = 0.7
            w_cost = 0.5
        
        # ====================================================================
        # Calculate total cost
        # ====================================================================
        
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
            
            # Calculate breakdown for explainability (optional)
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
        
        if mode == 'ev':
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
        """
        Explain why an action was chosen (XAI).
        """
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
        if mode == 'ev' and 'charger_wait_min' in chosen.params:
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