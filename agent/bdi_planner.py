from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, List

@dataclass
class Action:
    mode: str
    route: List[Any]
    params: Dict[str, Any]

@dataclass
class ActionScore:
    action: Action
    cost: float

class BDIPlanner:
    """Lightweight BDI-like planner stub.
    - Generates a simple action set (transport modes) with placeholder routes.
    - Computes a weighted cost using desires.
    - Picks the min-cost action.
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
        route = action.route
        mode = action.mode
        t = env.estimate_travel_time(route, mode)
        money = env.estimate_monetary_cost(route, mode)
        comfort = env.estimate_comfort(route, mode)
        risk = env.estimate_risk(route, mode)
        emissions = env.estimate_emissions(route, mode)

        w_time = desires.get('time', 0.5)
        w_cost = desires.get('cost', 0.3)
        w_comfort = desires.get('comfort', 0.2)
        w_risk = desires.get('risk', 0.2)
        w_eco = desires.get('eco', 0.6)

        comfort_penalty = max(0.0, 1.0 - comfort)  # comfort in [0,1]

        return (
            w_time * t +
            w_cost * money +
            w_comfort * comfort_penalty +
            w_risk * risk +
            w_eco * emissions
        )

    def evaluate_actions(self, env, state, desires: Dict[str, float], origin, dest) -> List[ActionScore]:
        actions = self.actions_for(env, state, origin, dest)
        scores: List[ActionScore] = []
        for a in actions:
            c = self.cost(a, env, state, desires)
            scores.append(ActionScore(action=a, cost=c))
        return scores

    def choose_action(self, scores: List[ActionScore]) -> Action:
        if not scores:
            return Action(mode='walk', route=[], params={})
        return min(scores, key=lambda s: s.cost).action