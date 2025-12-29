# agent/cognitive_abm.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any, List, Tuple, Optional
import random
import logging

logger = logging.getLogger(__name__)

# NOTE: Environment (OSMnx) uses (lon, lat) for all spatial tuples.
#       ABM state keeps (lon, lat) as well. The UI flips to (lat, lon)
#       only at render-time for Folium/Leaflet.

@dataclass
class AgentState:
    attention: float = 0.5
    working_memory: float = 0.5
    stress: float = 0.3
    performance: float = 0.5

    # Spatial tuples are (lon, lat) throughout ABM to match environment.
    location: Tuple[float, float] | None = None
    destination: Tuple[float, float] | None = None
    mode: str = 'walk'
    route: List[Tuple[float, float]] = None  # list of (lon, lat) vertices

    agent_id: str = 'agent'
    route_index: int = 0            # segment index along route
    route_offset_km: float = 0.0    # distance progressed on current segment

    # Travel accounting (Phase 2)
    arrived: bool = False
    departed_at_step: int | None = None
    arrived_at_step: int | None = None
    travel_time_min: float = 0.0
    distance_km: float = 0.0
    emissions_g: float = 0.0
    dwell_time_min: float = 0.0  # cumulative dwell time (stops, lights, boarding)

    mode_history: List[str] = field(default_factory=list)
    mode_costs: Dict[str, float] = field(default_factory=dict)
    consecutive_same_mode: int = 0
    action_params: Dict[str, Any] = field(default_factory=dict)  # NEW: Store action params

class CognitiveAgent:
    """Toy cognitive agent + planner + movement + arrival + dwell tracking.

    Contract:
      - ABM keeps all spatial tuples as (lon, lat) to match SpatialEnvironment.
      - UI (Streamlit/Folium) flips to (lat, lon) ONLY at render time.
    """
    def __init__(
        self,
        seed: int | None = None,
        agent_id: str | None = None,
        desires: Dict[str, float] | None = None,
        planner=None,
        origin: Tuple[float, float] | None = None,
        dest: Tuple[float, float] | None = None,
        agent_context: Optional[Dict] = None
    ):
        self.rng = random.Random(seed)
        self.state = AgentState(agent_id=agent_id or f'agent_{abs(self.rng.randint(1, 9999))}')
        # Defaults remain small only for unit tests; production runs seed from OSM or Edinburgh bbox.
        self.state.location = origin if origin is not None else (0.0, 0.0)  # (lon, lat)
        self.state.destination = dest if dest is not None else (1.0, 1.0)   # (lon, lat)
        self.state.route = []
        self.desires = desires or {'eco': 0.6, 'time': 0.5, 'cost': 0.3, 'comfort': 0.3, 'risk': 0.3}
        self.planner = planner
        self.t = 0
        self._replan_period = 10  # steps between replans
        
        # CRITICAL FIX: Store agent context for infrastructure queries
        self.agent_context = agent_context or {}
        
        # Store origin/dest for diagnostics
        self.origin = origin
        self.dest = dest


    def _apply_habit_bonus(self, costs: dict) -> dict:
        """Add habit discount to recently used modes."""
        if len(self.state.mode_history) < 3:
            return costs  # Not enough history
        
        # Get mode used in last 3 trips
        recent_mode = max(set(self.state.mode_history[-3:]), 
                         key=self.state.mode_history[-3:].count)
        
        # Apply habit discount (20% cost reduction)
        adjusted_costs = costs.copy()
        if recent_mode in adjusted_costs:
            adjusted_costs[recent_mode] *= 0.8
        
        return adjusted_costs
    
    def reset(self) -> None:
        aid = self.state.agent_id
        self.state = AgentState(
            agent_id=aid,
            location=self.state.location,
            destination=self.state.destination
        )
        self.state.mode = 'walk'
        self.state.route = []
        self.t = 0

    def _maybe_plan(self, env) -> None:
        s = self.state
        if env is None or self.planner is None or s.arrived:
            return
        need_plan = (self.t % self._replan_period == 1) or (not s.route)
        if need_plan:
            # CRITICAL FIX: Pass agent_context to planner
            scores = self.planner.evaluate_actions(
                env, 
                s, 
                self.desires, 
                s.location, 
                s.destination,
                agent_context=self.agent_context  # ← ADDED THIS LINE!
            )
            best = self.planner.choose_action(scores)
            s.mode = best.mode
            
            # Store the cost evaluation for social influence
            s.mode_costs = {score.action.mode: score.cost for score in scores}
            
            # Store infrastructure params
            s.action_params = best.params
            
            # Route assignment...
            s.route = [(float(x), float(y)) for (x, y) in (best.route or [])]
            s.route_index = 0
            s.route_offset_km = 0.0
            if s.departed_at_step is None:
                s.departed_at_step = self.t

    def _dwell_per_segment(self, mode: str) -> float:
        """Dwell time (minutes) applied whenever the agent finishes a segment."""
        dwell_lookup = {
            'walk': 0.00,
            'bike': 0.05,
            'bus': 0.50,
            'car': 0.00,
            'ev': 0.00,
        }
        return dwell_lookup.get(mode, 0.0)

    def _move(self, env) -> None:
        s = self.state
        if env is None or not s.route or len(s.route) < 2 or s.arrived:
            return

        prev_loc = s.location
        prev_idx = s.route_index

        # Environment returns (lon, lat)
        i, off, new_loc = env.advance_along_route(s.route, s.route_index, s.route_offset_km, s.mode)
        s.route_index, s.route_offset_km, s.location = i, off, new_loc

        # accumulate distance/time/emissions if movement occurred
        if prev_loc is not None and s.location is not None and s.location != prev_loc:
            try:
                d_km = env._segment_distance_km(prev_loc, s.location)
            except Exception:
                from math import hypot
                d_km = hypot(s.location[0] - prev_loc[0], s.location[1] - prev_loc[1])
            s.distance_km += d_km

            # per-tick time (movement component)
            step_min = float(getattr(env, 'step_minutes', 1.0))
            s.travel_time_min += step_min

            # per-tick emissions over moved segment
            try:
                s.emissions_g += float(env.estimate_emissions([prev_loc, s.location], s.mode))
            except Exception:
                pass

        # dwell if we crossed one or more segment boundaries
        delta_segments = max(0, s.route_index - prev_idx)
        if delta_segments > 0:
            dwell_added = self._dwell_per_segment(s.mode) * delta_segments
            s.dwell_time_min += dwell_added
            s.travel_time_min += dwell_added

        # arrival check with epsilon (~10 m)
        if s.route and s.location is not None:
            last = s.route[-1]
            try:
                remaining_km = env._segment_distance_km(s.location, last)
            except Exception:
                from math import hypot
                remaining_km = hypot(s.location[0] - last[0], s.location[1] - last[1])
            if remaining_km <= 0.01:
                s.arrived = True
                if s.arrived_at_step is None:
                    s.arrived_at_step = self.t

    def step(self, env=None) -> Dict[str, Any]:
        s = self.state
        self.t += 1

        # Cognitive updates (same as Phase 1)
        stimulus = self.rng.uniform(-0.1, 0.1)
        s.attention = _clip(s.attention + 0.05 * stimulus - 0.02 * s.stress)
        s.working_memory = _clip(0.6 * s.working_memory + 0.4 * s.attention + self.rng.uniform(-0.05, 0.05))
        perf_raw = 0.5 * s.attention + 0.5 * s.working_memory - 0.4 * s.stress
        s.performance = _clip(perf_raw)
        s.stress = _clip(0.8 * s.stress + 0.2 * (0.6 - s.performance))

        # Planning & movement
        self._maybe_plan(env)
        self._move(env)

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
            'arrived': s.arrived,
            'departed_at_step': s.departed_at_step,
            'arrived_at_step': s.arrived_at_step,
            'travel_time_min': round(s.travel_time_min, 3),
            'distance_km': round(s.distance_km, 4),
            'emissions_g': round(s.emissions_g, 3),
            'dwell_time_min': round(s.dwell_time_min, 3),
        }

def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))