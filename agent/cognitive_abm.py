"""
agent/cognitive_abm.py

This module defines a simple cognitive agent for the ABM, with integrated planning and 
movement logic.

Cognitive model is a toy implementation with attention, working memory, stress, and 
performance variables that evolve over time. The planner is integrated to allow the agent
to choose routes and modes based on its desires and the environment. Movement logic 
advances the agent along its route and tracks travel time, distance, emissions, and dwell time.

"""
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

    # Travel accounting
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
    action_params: Dict[str, Any] = field(default_factory=dict)

    # Per-segment colour metadata from compute_route_with_segments().
    # Each item: {'path': [(lon,lat),...], 'mode': str, 'label': str}
    route_segments: List[Dict] = field(default_factory=list)

    # Full multimodal itinerary — updated on every BDI replan.
    # None until the first successful plan; visualiser reads route_segments
    # from trip_chain.route_segments when present.
    trip_chain: Optional[Any] = None   # TripChain | None (imported lazily)

    # Origin / destination labels for tooltip display.
    origin_name: str = ''
    destination_name: str = ''

    # PT service / stop metadata for tooltip display.
    service_id: str = ''
    destination_stop: str = ''

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
        agent_context: Optional[Dict] = None,
        simulation_results=None,  # SimulationResults — for routing_fallback_count
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
        self._replan_period = 20  # steps between replans
        
        # Store agent context for infrastructure queries
        self.agent_context = agent_context or {}
        
        # Store origin/dest for diagnostics
        self.origin = origin
        self.dest = dest

        # Reference to SimulationResults for data-quality counters.
        # None in unit tests; set by agent_creation.py in production.
        self._simulation_results = simulation_results

    # This function applies a habit bonus to the costs of modes that have been used recently,
    # making them more likely to be chosen again. This simulates the real-world tendency for
    # people to stick with familiar modes. The bonus is applied as a 20% cost reduction to 
    # the most frequently used mode in the last 3 trips, if that mode is present in the 
    # current cost evaluation. This can help the agent develop "habits" over time, which is
    # a common aspect of human behavior in transportation mode choice.
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

    # This function checks if the agent needs to plan a new route and, if so, calls the 
    # planner to evaluate possible actions and choose the best one. The planner is passed 
    # the current environment, the agent's state, desires, location, and destination, as 
    # well as the agent context which can include information about infrastructure and other 
    # relevant factors.
    def _maybe_plan(self, env) -> None:
        s = self.state
        if env is None or self.planner is None or s.arrived:
            return
        # Agent replans if it's the first step, if it has no route, or every _replan_period 
        # steps to adapt to changes.
        need_plan = (self.t % self._replan_period == 1) or (not s.route)
        if need_plan:
            # MUST Pass agent_context to planner!
            scores = self.planner.evaluate_actions(
                env, 
                s, 
                self.desires, 
                s.location, 
                s.destination,
                agent_context=self.agent_context # Critical for infrastructure-aware planning 
            )
            best = self.planner.choose_action(scores)
            
            # Only update route if we got a valid one
            if best.route and len(best.route) > 0:
                s.route = [(float(x), float(y)) for (x, y) in best.route]
                s.route_index = 0
                s.route_offset_km = 0.0
                s.mode = best.mode
                
                # Store the cost evaluation for social influence
                s.mode_costs = {score.action.mode: score.cost for score in scores}
                
                # Store infrastructure params
                s.action_params = best.params

                # Per-segment colour metadata for the visualiser
                s.route_segments = best.params.get('route_segments', [])
                # Promote TripChain from params when available
                tc = best.params.get('trip_chain')
                if tc is not None:
                    s.trip_chain = tc
                    # Keep route_segments in sync for backward-compat
                    if hasattr(tc, 'route_segments'):
                        s.route_segments = tc.route_segments
                s.service_id       = best.params.get('service_id', '')
                s.destination_stop = best.params.get('destination_stop', '')
                
                if s.departed_at_step is None:
                    s.departed_at_step = self.t
            else:
                # ⚠️ No valid route returned — keep existing route if we have one
                route_pts = len(best.route) if best.route else 0
                logger.warning(
                    f"{s.agent_id}: No valid route from planner "
                    f"(got {route_pts} points) — mode={s.mode}"
                )
                if not s.route or len(s.route) == 0:
                    # Increment data-quality counter so the final summary
                    # reports how many agents fell back to walk.
                    if self._simulation_results is not None:
                        self._simulation_results.routing_fallback_count += 1

                    # Really stuck — check if we're already at destination
                    try:
                        from simulation.spatial.coordinate_utils import haversine_km
                        dist = haversine_km(s.location, s.destination)

                        if dist < 0.05:  # Within 50 m — already there
                            s.arrived = True
                            s.arrived_at_step = self.t
                            logger.info(f"{s.agent_id}: Already at destination!")
                        else:
                            # Straight-line walk fallback — biases mode-share data
                            logger.warning(
                                f"{s.agent_id}: Routing fallback — "
                                f"straight-line walk ({dist:.2f} km). "
                                f"Check OD-pair connectivity for mode={s.mode}."
                            )
                            s.route = [s.location, s.destination]
                            s.route_index = 0
                            s.route_offset_km = 0.0
                            s.mode = 'walk'
                    except Exception as e:
                        logger.warning(f"{s.agent_id}: Fallback with error: {e}")
                        s.route = [s.location, s.destination]
                        s.route_index = 0
                        s.route_offset_km = 0.0

    # This function calculates the dwell time to be added whenever the agent finishes a 
    # segment of its route, based on the mode of transportation. Different modes have 
    # different typical dwell times (e.g., bus passengers may have longer dwell times 
    # due to stops and boarding, while car drivers may have minimal dwell time). This
    # adds realism to the simulation by accounting for the time spent not just moving 
    # but also waiting or stopping, which can be significant in certain modes.
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

    # This function advances the agent along its route based on the environment's routing logic. 
    # It updates the agent's location and route index. It also calculates the distance traveled, 
    # time taken, emissions generated, and dwell time accumulated based on the movement. 
    # The function checks for arrival at the destination and updates the agent's state accordingly. 
    # This is a critical part of the ABM as it simulates the actual movement of the agent 
    # through the environment and tracks key metrics that can be used for analysis and visualisation.
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

    # Main function that advances the agent's state by one step. It first updates the
    # cognitive variables (attention, working memory, stress, performance) based on a 
    # simple model. Then it calls the planning function to potentially update the route 
    # and mode, and finally calls the movement function to advance the agent along its 
    # route. The function returns a dictionary of the agent's state variables for logging
    # or analysis. 
    # Debug logging included to track the route status at the start and end of the first 
    # few steps to help identify issues with route planning and movement early on in 
    # the simulation.
    def step(self, env=None) -> Dict[str, Any]:
        s = self.state
        self.t += 1
        
        # Route-status trace — useful during development; kept at DEBUG so it
        # doesn't appear in production logs even for the first few steps.
        if self.t <= 3:
            route_info = f"{len(s.route)} points" if s.route else "None"
            logger.debug(f"🔍 {s.agent_id} step {self.t} START: route={route_info}, arrived={s.arrived}")

        # Cognitive updates with some randomness to simulate variability in attention and stress. 
        # The agent's attention is influenced by a random stimulus and its current stress level. 
        # Working memory is a combination of attention and some randomness. Performance is a 
        # function of attention, working memory, and stress. Stress increases if performance is low.
        # This simple cognitive model allows the agent's internal state to evolve over time, which can
        # affect its decision-making and movement in a more realistic way than a purely rational agent.
        # Arbitrary parameters and equations used here and can be tuned to achieve different behaviors.
        stimulus = self.rng.uniform(-0.1, 0.1)
        s.attention = _clip(s.attention + 0.05 * stimulus - 0.02 * s.stress)
        s.working_memory = _clip(0.6 * s.working_memory + 0.4 * s.attention + self.rng.uniform(-0.05, 0.05))
        perf_raw = 0.5 * s.attention + 0.5 * s.working_memory - 0.4 * s.stress
        s.performance = _clip(perf_raw)
        s.stress = _clip(0.8 * s.stress + 0.2 * (0.6 - s.performance))

        # Planning & movement
        self._maybe_plan(env)
        self._move(env)
        
        if self.t <= 3:
            route_info = f"{len(s.route)} points" if s.route else "None"
            logger.debug(f"🔍 {s.agent_id} step {self.t} END: route={route_info}, distance={s.distance_km:.1f}km, arrived={s.arrived}")

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
            # Route geometry and per-segment colour data for visualization
            'route':            s.route,
            'route_segments':   s.route_segments,
            # Full multimodal itinerary (TripChain) — visualiser uses this
            'trip_chain':       s.trip_chain.to_dict() if s.trip_chain is not None and hasattr(s.trip_chain, 'to_dict') else None,
            # Origin/destination labels for map tooltips
            'origin_name':      s.origin_name,
            'destination_name': s.destination_name,
            # PT service info for map tooltips
            'service_id':       s.service_id,
            'destination_stop': s.destination_stop,
        }

# Utility function to clip values between a lower and upper bound, used for cognitive 
# variable updates. This ensures that attention, working memory, stress, and performance 
# values remain within a reasonable range (0.0 to 1.0) to prevent unrealistic values that
# could arise from the random updates in the cognitive model. This is a common technique 
# in cognitive modeling to maintain stability in the variables and ensure they reflect 
# plausible human-like states.
def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))