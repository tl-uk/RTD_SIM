from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple
import random
import logging

logger = logging.getLogger(__name__)

@dataclass
class AgentState:
    attention: float = 0.5
    working_memory: float = 0.5
    stress: float = 0.3
    performance: float = 0.5
    location: Tuple[float, float] | None = None
    destination: Tuple[float, float] | None = None
    mode: str = 'walk'
    route: List[Tuple[float, float]] = None
    agent_id: str = 'agent'

class CognitiveAgent:
    """Cognitive agent with toy dynamics + Phase 2 planning hooks."""
    def __init__(self, seed: int | None = None, agent_id: str | None = None,
                 desires: Dict[str, float] | None = None, planner=None,
                 origin: Tuple[float, float] | None = None, dest: Tuple[float, float] | None = None):
        self.rng = random.Random(seed)
        self.state = AgentState(agent_id=agent_id or f'agent_{abs(self.rng.randint(1, 9999))}')
        self.state.location = origin if origin is not None else (0.0, 0.0)
        self.state.destination = dest if dest is not None else (1.0, 1.0)
        self.state.route = []
        self.desires = desires or {'eco': 0.6, 'time': 0.5, 'cost': 0.3, 'comfort': 0.3, 'risk': 0.3}
        self.planner = planner
        self.t = 0
        self._replan_period = 10

    def reset(self) -> None:
        aid = self.state.agent_id
        self.state = AgentState(agent_id=aid, location=self.state.location, destination=self.state.destination)
        self.state.mode = 'walk'
        self.state.route = []
        self.t = 0

    def step(self, env=None) -> Dict[str, Any]:
        s = self.state
        self.t += 1
        stimulus = self.rng.uniform(-0.1, 0.1)
        s.attention = _clip(s.attention + 0.05 * stimulus - 0.02 * s.stress)
        s.working_memory = _clip(0.6 * s.working_memory + 0.4 * s.attention + self.rng.uniform(-0.05, 0.05))
        perf_raw = 0.5 * s.attention + 0.5 * s.working_memory - 0.4 * s.stress
        s.performance = _clip(perf_raw)
        s.stress = _clip(0.8 * s.stress + 0.2 * (0.6 - s.performance))

        if env is not None and self.planner is not None and (self.t % self._replan_period == 1 or not s.route):
            scores = self.planner.evaluate_actions(env, s, self.desires, s.location, s.destination)
            best = self.planner.choose_action(scores)
            s.mode = best.mode
            s.route = best.route

        # Movement: teleport to destination in stub
        if s.route and s.destination is not None:
            s.location = s.destination

        return {
            't': self.t,
            'agent_id': s.agent_id,
            'attention': round(s.attention, 4),
            'working_memory': round(s.working_memory, 4),
            'stress': round(s.stress, 4),
            'performance': round(s.performance, 4),
            'mode': s.mode,
            'location': s.location,
            'destination': s.destination,
        }

def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
