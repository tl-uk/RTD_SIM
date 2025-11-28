from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, List

import numpy as np

@dataclass
class Action:
    mode: str
    route: List[Any]
    params: Dict[str, Any]

@dataclass
class ActionScore:
    action: Action
    cost: float

class TripContext:
    weather: str  # 'sunny', 'rain', 'snow'
    time_of_day: str  # 'peak', 'off_peak', 'night'
    day_of_week: str  # 'weekday', 'weekend'
    trip_purpose: str  # 'commute', 'leisure', 'shopping', 'school'
    has_luggage: bool
    traveling_with: str  # 'alone', 'children', 'elderly'

class BDIPlanner:
    """Lightweight BDI-like planner with fixed cost calculation.
    
    Key fix: Normalize and scale metrics so desires actually influence choice.
    """
    def __init__(self) -> None:
        self.default_modes = ['walk', 'bike', 'bus', 'car', 'ev']

    def actions_for(self, env, state, origin, dest) -> List[Action]:
        actions: List[Action] = []
        for m in self.default_modes:
            route = env.compute_route(agent_id=getattr(state, 'agent_id', 'agent'), origin=origin, dest=dest, mode=m)
            actions.append(Action(mode=m, route=route, params={}))
        return actions

    def cost(self, action: Action, env, state, desires: Dict[str, float]) -> float:
        """Calculate weighted cost with proper normalization.
        
        The bug was that raw metrics (time in minutes, money in dollars, emissions in grams)
        were on completely different scales, so desires couldn't influence the choice properly.
        
        Fix: Normalize all metrics to [0,1] range before weighting.
        """
        route = action.route
        mode = action.mode
        
        # Get raw metrics
        time_min = env.estimate_travel_time(route, mode)
        money = env.estimate_monetary_cost(route, mode)
        comfort = env.estimate_comfort(route, mode)      # Already [0,1]
        risk = env.estimate_risk(route, mode)            # Already [0,1]
        emissions_g = env.estimate_emissions(route, mode)
        
        # Get desire weights
        w_time = desires.get('time', 0.5)
        w_cost = desires.get('cost', 0.3)
        w_comfort = desires.get('comfort', 0.2)
        w_risk = desires.get('risk', 0.2)
        w_eco = desires.get('eco', 0.6)
        
        # Normalize metrics to [0,1] scale using reasonable ranges
        # (These represent typical urban trip ranges)
        time_norm = min(1.0, time_min / 60.0)          # Normalize to 0-60 min
        cost_norm = min(1.0, money / 5.0)              # Normalize to 0-5 currency
        emissions_norm = min(1.0, emissions_g / 500.0) # Normalize to 0-500g CO2
        
        # For comfort and risk: higher comfort is better, so invert it to cost
        comfort_penalty = 1.0 - comfort  # Higher comfort = lower penalty
        
        # Calculate weighted sum (all components now on same [0,1] scale)
        total_cost = (
            w_time * time_norm +
            w_cost * cost_norm +
            w_comfort * comfort_penalty +
            w_risk * risk +
            w_eco * emissions_norm
        )
        
        # Debug logging (uncomment to see calculations)
        # print(f"{mode:6s} | T:{time_norm:.2f} C:{cost_norm:.2f} E:{emissions_norm:.2f} | Cost:{total_cost:.2f}")
        
        return total_cost

    def evaluate_actions(self, env, state, desires: Dict[str, float], origin, dest) -> List[ActionScore]:
        actions = self.actions_for(env, state, origin, dest)
        scores: List[ActionScore] = []
        
        # Debug: Show what desires this agent has
        # print(f"\nAgent desires: eco={desires.get('eco'):.1f} time={desires.get('time'):.1f} cost={desires.get('cost'):.1f}")
        
        for a in actions:
            c = self.cost(a, env, state, desires)
            scores.append(ActionScore(action=a, cost=c))
        
        # Debug: Show all scores
        # for s in sorted(scores, key=lambda x: x.cost):
        #     print(f"  {s.action.mode:6s}: {s.cost:.3f}")
        
        return scores

    def logit_choice(costs: dict, temperature: float = 1.0) -> str:
        """
        Probabilistic mode choice using softmax.
        
        Args:
            costs: {mode: cost} dictionary
            temperature: Higher = more random, lower = more deterministic
        
        Returns:
            Chosen mode (sampled probabilistically)
        """
        modes = list(costs.keys())
        utilities = [-c / temperature for c in costs.values()]
        exp_utils = np.exp(utilities - np.max(utilities))  # Numerical stability
        probs = exp_utils / exp_utils.sum()
        return np.random.choice(modes, p=probs)
    
    def adjust_desires_for_context(base_desires: dict, context: TripContext) -> dict:
        desires = base_desires.copy()
        
        # Weather effects
        if context.weather == 'rain':
            desires['comfort'] *= 1.5  # Higher comfort weight in rain
            # This makes covered modes (bus, car, EV) more attractive
        
        # Time of day effects
        if context.time_of_day == 'peak':
            desires['time'] *= 1.3  # Time matters more during rush hour
        
        # Trip purpose effects
        if context.trip_purpose == 'commute':
            desires['cost'] *= 0.7  # Less cost-sensitive for work trips
        
        # Luggage effects
        if context.has_luggage:
            desires['comfort'] *= 2.0  # Comfort critical with luggage
        
        return desires