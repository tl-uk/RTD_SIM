"""
agent/bdi_planner.py

This class implements a BDI (Belief-Desire-Intention) planner that generates and 
evaluates possible actions for agents based on their context and desires. 

The planner has been enhanced to include a wider range of freight vehicle types, 
such as cargo bikes for urban micro-delivery, medium freight trucks (both electric 
and diesel), and heavy goods vehicles (including hydrogen-powered options).

Implementation Logic for BDI Agents
To implement these in a BDI system for transport/freight decarbonisation, we would 
map them as follows:
- ASI as the "Intention Selection" Logic:
    * Avoid: If the agent perceives high congestion (Belief), its primary Desire is to 
    reduce trips. It selects the "Avoid" Plan first (e.g., Urban Freight Consolidation).
    * Shift: If "Avoid" is not feasible, the agent shifts to a Desire for 
    low-carbon modes (e.g., Rail/Water instead of Road).
    * Improve: As a final tier, the agent Intends to improve current tech (e.g., 
    Zero-emission vehicles (ZEV)).
- Complex Contagion as the "Belief Update" Function:
  The agent does not update its belief that "Electric Trucks are viable" until 
  number of its neighbors (in its Small-World Network) have already adopted them. 
  This models the high financial risk inherent in freight logistics.
- Small-World as the "Social Environment":
  A multi-agent system (MAS) should be structured so that local haulier agents are 
  clustered, but also have "long-range" links to policy-maker agents or tech-innovator 
  agents. This prevents the "homophily trap" and accelerates the "Shift" and 
  "Improve" tiers of the ASI framework. 

How to extend the planner with new modes:
1. Add new modes to the default mode list and distance constraints, e.g. 'cargo_bike', 
   'truck_electric', 'hgv_hydrogen'.
2. Update the mode filtering logic to better handle freight contexts and allow
   cargo bikes for longer trips.
3. Enhance the cost function to include preferences for freight modes when relevant.
4. Add infrastructure checks for new EV types if infrastructure awareness is enabled.
5. Update the explanation function to provide insights into why freight modes were 
   chosen.
6. Ensure that the planner never returns an empty mode list, and implements intelligent 
   fallbacks based on context.
7. Add detailed logging to help debug mode filtering and routing issues, especially for
   freight contexts.
8. Test the planner with a variety of freight scenarios to ensure the new modes are 
   being offered and evaluated correctly.
9. Monitor the distribution of chosen modes in freight contexts to verify that the new
   modes are being utilized as intended.
10. Continuously refine the mode selection and cost evaluation logic based on observed 
    outcomes and feedback from the simulation runs, especially focusing on freight 
    delivery scenarios.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple

import random
import logging

logger = logging.getLogger(__name__)

# ── Modes registry — abstract routing guard ───────────────────────────────────
# is_routeable() → False for rail/ferry/air; those modes must use
# make_synthetic_route() instead of env.compute_route() (OSMnx drive graph).
try:
    from simulation.config.modes import (
        is_routeable, get_network,
        abstract_distance_km, make_synthetic_route,
        ABSTRACT_MODES,
    )
except ImportError:
    ABSTRACT_MODES = frozenset({
        'local_train', 'intercity_train',
        'ferry_diesel', 'ferry_electric',
        'flight_domestic', 'flight_electric',
    })
    def is_routeable(m: str) -> bool:
        return m not in ABSTRACT_MODES
    def get_network(m: str) -> str:
        if m in ('local_train', 'intercity_train'):     return 'rail'
        if m in ('ferry_diesel', 'ferry_electric'):     return 'ferry'
        if m in ('flight_domestic', 'flight_electric'): return 'air'
        return 'drive'
    def abstract_distance_km(o, d, m) -> float:
        import math
        try:
            # NOTE: (lon, lat) order
            lon1, lat1 = float(o[0]), float(o[1])
            lon2, lat2 = float(d[0]), float(d[1])
        except Exception:
            return 0.0
        R = 6371.0
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = (math.sin(dp / 2) ** 2
             + math.cos(math.radians(lat1))
             * math.cos(math.radians(lat2))
             * math.sin(dl / 2) ** 2)
        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a)) * 1.1
    def make_synthetic_route(o, d, m) -> list:
        # NOTE: return 2-tuples
        return [tuple(o), tuple(d)]

# ----- Metrics (CPG instrumentation) -----
try:
    from telemetry_metrics import inc, get
except Exception:  # fallback if module not available
    def inc(*args, **kwargs):
        return 0
    def get(*args, **kwargs):
        return 0


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

# BDI Planner with expanded freight modes and improved mode filtering logic.
class BDIPlanner:
    """BDI planner with expanded freight modes."""
    
    # EV constraints - EXPANDED
    EV_RANGE_KM = {
        'ev': 350.0,
        'van_electric': 200.0,
        'cargo_bike': 50.0,
        'truck_electric': 250.0,
        'hgv_electric': 300.0,
        'hgv_hydrogen': 600.0,
        'e_scooter': 30.0,
        'ferry_electric': 50.0,
        'flight_electric': 500.0,
        'taxi_ev': 300.0,     # <-- ADD THIS
    }

    CHARGING_TIME_MIN = {
        'level2': 240.0,
        'dcfast': 30.0,
        'depot': 480.0,
        'hgv_depot': 720.0,
    }
    
    # Distance-based mode constraints - EXPANDED  
    MODE_MAX_DISTANCE_KM = {
        'walk': 3.0,  # Realistic walking distance
        'bike': 10.0,  # Regular bike comfortable range
        'cargo_bike': 20.0,  # E-cargo bike urban delivery range (realistic for Edinburgh)
        'bus': 100.0,
        'car': 500.0,
        'ev': 350.0,
        'taxi_ev': 400.0,     # <-- ADD THIS
        'taxi_diesel': 600.0, # <-- ADD THIS
        
        # Freight modes
        'van_electric': 200.0,
        'van_diesel': 500.0,
        'truck_electric': 250.0,
        'truck_diesel': 600.0,
        'hgv_electric': 300.0,
        'hgv_diesel': 800.0,
        'hgv_hydrogen': 600.0,
        
        # Public transport
        'tram': 25.0,
        'local_train': 150.0,
        'intercity_train': 800.0,
        
        # Maritime
        'ferry_diesel': 200.0,
        'ferry_electric': 50.0,
        
        # Aviation
        'flight_domestic': 1000.0,
        'flight_electric': 500.0,
        
        # Micro-mobility
        'e_scooter': 30.0,
    }
    
    # Distance-based mode constraints - EXPANDED  
    MODE_MAX_DISTANCE_KM = {
        'walk': 3.0,  # Realistic walking distance
        'bike': 10.0,  # Regular bike comfortable range
        'cargo_bike': 20.0,  # E-cargo bike urban delivery range (realistic for Edinburgh)
        'bus': 100.0,
        'car': 500.0,
        'ev': 350.0,
        
        # Freight modes
        'van_electric': 200.0,
        'van_diesel': 500.0,
        'truck_electric': 250.0,
        'truck_diesel': 600.0,
        'hgv_electric': 300.0,
        'hgv_diesel': 800.0,
        'hgv_hydrogen': 600.0,
        
        # Public transport
        'tram': 25.0,
        'local_train': 150.0,
        'intercity_train': 800.0,
        
        # Maritime
        'ferry_diesel': 200.0,
        'ferry_electric': 50.0,
        
        # Aviation
        'flight_domestic': 1000.0,
        'flight_electric': 500.0,
        
        # Micro-mobility
        'e_scooter': 30.0,
    }
    
    def __init__(
        self,
        infrastructure_manager: Optional[Any] = None,
        plan_generator=None,  # ContextualPlanGenerator — optional
        ev_feasibility=None,
    ) -> None:
        """Initialize planner with expanded freight modes."""
        self.plan_generator = plan_generator
        self.default_modes = [
            'walk', 'bike', 'bus', 
            'car', 'ev',
            'taxi_ev', 'taxi_diesel',
            'van_electric', 'van_diesel',
            'cargo_bike',
            'truck_electric', 'truck_diesel',
            'hgv_electric', 'hgv_diesel', 'hgv_hydrogen',
        ]
        self.infrastructure = infrastructure_manager

        # --- EV feasibility tuning (optional; override via ev_feasibility dict) ---
        self.ev_params = {
            "default_charger_occupancy": 0.0,      # realistic default when unknown
            "occ_threshold_block": 0.85,           # block if area appears saturated
            "route_factor": 1.35,                  # straight-line → likely route multiplier
            "short_trip_km": 8.0,                  # short trips rarely need en-route charging
            "dest_nearby_radius_km": 2.0,          # "near" radius around destination for charger
            "require_dest_nearby_if_long": True,   # enforce nearby charger for long trips
            "nominal_ranges_km": {                 # conservative nominal ranges
                "ev": 280.0,
                "van_electric": 200.0,
                "truck_electric": 220.0,
                "hgv_electric": 300.0,
            },
        }
        if isinstance(ev_feasibility, dict):
            self.ev_params.update(ev_feasibility)

        # mode_cost_factors: multipliers applied to the final cost of each mode.
        # Set via apply_scenario_cost_factors() when a scenario YAML declares
        # parameter: cost_reduction / cost_increase for a specific mode.
        # Example: {'ev': 0.70, 'van_electric': 0.70} for EV Subsidy 30%.
        # Default 1.0 (no adjustment) for all modes.
        self.mode_cost_factors: Dict[str, float] = {}

        if self.infrastructure:
            logger.info("BDI planner: infrastructure-aware (Expanded Freight)")
        else:
            logger.info("BDI planner: basic mode (Expanded Freight)")

    def apply_scenario_cost_factors(self, scenario_policies: list) -> None:
        """
        Parse scenario YAML policies and store mode cost multipliers.

        Called by simulation_runner or apply_scenario_policies() after the
        scenario is loaded. Translates YAML cost_reduction / cost_increase
        parameters into multipliers stored in self.mode_cost_factors so the
        BDI cost function applies them at decision time.

        Example YAML policy:
            parameter: cost_reduction
            value: 30.0
            target: mode
            mode: ev
        → stores {'ev': 0.70}

        Args:
            scenario_policies: list of policy dicts from the YAML 'policies' key
        """
        for policy in (scenario_policies or []):
            if policy.get('target') != 'mode':
                continue
            mode = policy.get('mode')
            param = policy.get('parameter', '')
            value = float(policy.get('value', 0.0))
            if not mode:
                continue

            if param == 'cost_reduction':
                factor = 1.0 - (value / 100.0)          # 30% off → 0.70
            elif param == 'cost_increase':
                factor = 1.0 + (value / 100.0)          # 20% on  → 1.20
            elif param == 'cost_factor':
                factor = value                          # direct multiplier
            else:
                continue

            self.mode_cost_factors[mode] = max(0.05, factor)  # floor at 5%
            logger.info(
                "BDI cost factor set: %s × %.2f (from %s %.1f%%)",
                mode, self.mode_cost_factors[mode], param, value,
            )
    
    @property
    def has_infrastructure(self) -> bool:
        """Check if infrastructure awareness is enabled."""
        return self.infrastructure is not None
    
    # Ensures freight modes are properly selected and never returns empty list
    def actions_for(
        self,
        env,
        state,
        origin,
        dest,
        agent_context: Optional[Dict] = None
    ) -> List[Action]:
        """Generate possible actions with ENHANCED debugging."""
        actions: List[Action] = []
        context = agent_context or {}
        
        # Calculate straight-line distance
        from simulation.spatial.coordinate_utils import haversine_km
        straight_line_distance = haversine_km(origin, dest)
        
        # Get candidate modes from context filter
        available_modes = self._filter_modes_by_context(context, straight_line_distance)
        
        # CPG metrics snapshot (before contextual narrowing)
        cpg_pre_modes_len = len(available_modes)

        # Define agent_id here so it's available in CPG block AND debug logging below
        agent_id = getattr(state, 'agent_id', 'unknown')

        # ── Contextual Plan Extraction (Phase 1 Core Innovation) ──────────
        # If a ContextualPlanGenerator is attached and the agent carries its
        # user/job story objects, extract a plan and narrow the mode list.
        # Falls back to unfiltered available_modes if extraction fails.
        if self.plan_generator and context.get("user_story") and context.get("job_story"):
            try:
                _extracted_plan = self.plan_generator.extract_plan_from_context(
                    user_story=context["user_story"],
                    job_story=context["job_story"],
                    origin=origin,
                    dest=dest,
                    csv_data=context.get("csv_data"),
                )

                # Guard against None returns from CPG (avoids later NoneType errors)
                if _extracted_plan is None:
                    raise ValueError("CPG returned None plan")

                # NOTE: Write the extracted ASI and EV hints back to context
                if hasattr(_extracted_plan, 'asi_tier'):
                    context['asi_tier_hint'] = _extracted_plan.asi_tier
                if hasattr(_extracted_plan, 'ev_viability_belief_hint'):
                    context['ev_viability_threshold'] = _extracted_plan.ev_viability_belief_hint

                # CPG metrics snapshot
                cpg_pre_modes_len = len(available_modes)

                available_modes = self.plan_generator.get_candidate_modes(
                    plan=_extracted_plan,
                    available_modes=available_modes,
                    distance_km=straight_line_distance,
                    weather_conditions=context.get("weather"),
                )

                # Instrumentation: did CPG empty the candidate set? — KEEP THIS
                try:
                    if cpg_pre_modes_len > 0 and not available_modes:
                        total = inc('cpg_empty_count')
                        agent_key = agent_id
                        try:
                            job_obj = context.get('job_story')
                            job_key = getattr(job_obj, 'job_type', getattr(job_obj, 'name', 'unknown_job'))
                        except Exception:
                            job_key = 'unknown_job'
                        inc(f'cpg_empty_by_agent:{agent_key}')
                        inc(f'cpg_empty_by_job:{job_key}')
                        logger.debug('CPG empty (count=%d) — agent=%s job=%s', total, agent_key, job_key)
                except Exception as _metric_err:
                    logger.debug('CPG metrics failed: %s', _metric_err)

                # Hardened CPG summary: avoid AttributeError on missing plan fields
                logger.debug(
                    "CPG: %s → %s (objective=%s, critical=%s, reasoning=%s)",
                    agent_id, available_modes,
                    getattr(_extracted_plan, 'primary_objective', '?'),
                    getattr(_extracted_plan, 'reliability_critical', '?'),
                    getattr(_extracted_plan, 'reasoning', '?'),
                )

            except Exception as _cpg_err:
                logger.debug("CPG extraction failed for %s: %s", agent_id, _cpg_err)
                # Conservative defaults — only set on failure
                context.setdefault('reliability_critical', False)
                context.setdefault('asi_tier_hint', 'improve')
                context.setdefault('ev_viability_threshold', 0.5)
                try:
                    inc('cpg_error_count')
                    inc(f'cpg_error_by_agent:{agent_id}')
                except Exception:
                    pass

                
        # Debug logging — agent_id already defined above
        vehicle_required = context.get('vehicle_required', False)
        vehicle_type = context.get('vehicle_type', 'personal')
        
        logger.debug(f"   BDI PLANNING: {agent_id}")
        logger.debug(f"   Context: vehicle_type={vehicle_type}, vehicle_required={vehicle_required}")
        logger.debug(f"   Distance: {straight_line_distance:.1f}km (straight-line)")
        logger.debug(f"   Modes offered: {available_modes}")
        
        if not available_modes:
            logger.error(f"âŒ NO MODES OFFERED - this will cause fallback to walk!")
            return []
        
        # Track routing attempts
        routing_results = {}
        # ── Phase 10c: ASI Intent Tier Selection ─────────────────────────
        # BUG FIX: bike removed from _SHIFT_MODES — bike is Tier 3 (Improve).
        # Including bike caused it to dominate; "Realistic EV Transition" showed
        # bike as most popular because ASI SHIFT left only bike available.
        # BUG FIX: charger_occupancy default 0.0 in _is_mode_feasible (not 1.0).
        # BUG FIX: reliability_critical hard block restricted to freight vehicles.

        _congestion   = context.get('congestion', 0.0)
        _charger_occ  = context.get('charger_occupancy_nearby', 0.0)
        _eco_desire   = (context.get('desires') or {}).get('eco', 0.5)
        _ev_belief    = context.get('ev_viability_belief', 0.5)
        _ev_threshold = context.get('ev_viability_threshold', 0.5)
        _asi_hint     = context.get('asi_tier_hint', 'improve')

        _AVOID_MODES = {'cargo_bike', 'walk', 'e_scooter', 'bike'}
        _SHIFT_MODES = {'ev', 'van_electric', 'truck_electric', 'hgv_electric',
                        'local_train', 'intercity_train', 'bus', 'tram'}

        _tier1 = (
            ((_congestion > 0.7 or _charger_occ > 0.7) or _asi_hint == 'avoid')
            and _eco_desire > 0.6
            and bool(_AVOID_MODES & set(available_modes))
        )
        _tier2 = (
            not _tier1
            and (
                # Live EV belief must strictly exceed the persona threshold
                # (>= caused every agent to shift at startup when ev_belief==threshold==0.5)
                _ev_belief > _ev_threshold
                or (
                    # CPG hint alone is not enough — also require some eco motivation
                    # to prevent non-eco personas (budget_student, shift_worker) from
                    # being forced into Tier 2 when their CPG returns asi_hint='shift'
                    _asi_hint == 'shift'
                    and _eco_desire >= 0.45
                )
            )
            and bool(_SHIFT_MODES & set(available_modes))
        )

        if _tier1:
            _asi_tier = 'avoid'
            available_modes = [m for m in available_modes if m in _AVOID_MODES] or available_modes
        elif _tier2:
            _asi_tier = 'shift'
            available_modes = [m for m in available_modes if m in _SHIFT_MODES] or available_modes
        else:
            _asi_tier = 'improve'

        if _asi_tier != 'improve':
            logger.debug(
                "ASI %s: %s — congestion=%.2f, eco=%.2f, ev_belief=%.2f, modes=%s",
                _asi_tier.upper(), agent_id, _congestion, _eco_desire,
                _ev_belief, available_modes,
            )

        for mode in available_modes:
            logger.debug(f"   Testing mode: {mode}")

            # ── Abstract mode guard ─────────────────────────────────────────
            # Ferry/air modes are truly abstract (no network graph) → 2-point
            # straight-line route via make_synthetic_route().
            #
            # Rail modes (local_train, intercity_train, freight_rail) route
            # via the Edinburgh/UK station spine so they appear on the map
            # travelling through real stations (Waverley → Haymarket → …)
            # rather than a single diagonal line.
            #
            # modes.py sets rail routeable=True so this guard only fires for
            # ferry/air.  If for any reason rail still reaches here (e.g. rail
            # graph unavailable), it falls back to the spine gracefully.
            if not is_routeable(mode):
                try:
                    origin_pos = (float(origin[0]), float(origin[1]))
                    dest_pos   = (float(dest[0]),   float(dest[1]))
                except Exception:
                    origin_pos, dest_pos = (0.0, 0.0), (0.0, 0.0)

                dist_km = abstract_distance_km(origin_pos, dest_pos, mode)

                if get_network(mode) in ('rail', 'tram'):
                    # Rail and tram — route via the station/stop spine so the agent
                    # travels through real stop locations rather than a diagonal.
                    # route_via_stations returns None for tram when origin/dest are
                    # outside the tram corridor catchment (>1.5km from any stop).
                    # In that case, skip tram entirely — it's not a viable mode.
                    try:
                        from simulation.spatial.rail_spine import route_via_stations
                        route = route_via_stations(origin_pos, dest_pos, mode)
                    except Exception:
                        route = make_synthetic_route(origin_pos, dest_pos, mode)

                    # None = tram outside catchment — don't offer this mode
                    if route is None:
                        logger.debug("   Tram skipped: origin/dest outside 1.5km catchment")
                        routing_results[mode] = "outside_tram_catchment"
                        continue
                else:
                    # Ferry / air — straight line is correct
                    route = make_synthetic_route(origin_pos, dest_pos, mode)

                logger.debug(
                    "   Abstract route: %s (%s) %.1fkm via %d waypoints",
                    mode, get_network(mode), dist_km, len(route),
                )
                routing_results[mode] = f"abstract: {dist_km:.1f}km"
                actions.append(Action(
                    mode=mode,
                    route=route,
                    params={
                        'trip_distance_km': dist_km,
                        'abstract':         True,
                        'network':          get_network(mode),
                    },
                ))
                continue
            # ── End abstract mode guard ──────────────────────────────────────

            # Infrastructure feasibility check
            if not self._is_mode_feasible(mode, origin, dest, state, context):
                logger.debug(f"      âŒ Not feasible (infrastructure)")
                routing_results[mode] = "infrastructure_failed"
                continue
            
            # Compute actual route — prefer compute_route_with_segments() when
            # available so per-leg colour metadata flows to the visualiser.
            try:
                if hasattr(env, 'compute_route_with_segments'):
                    route, _segments = env.compute_route_with_segments(
                        agent_id=agent_id,
                        origin=origin,
                        dest=dest,
                        mode=mode,
                        policy_context=context,
                    )
                else:
                    route = env.compute_route(
                        agent_id=agent_id,
                        origin=origin,
                        dest=dest,
                        mode=mode,
                        policy_context=context,
                    )
                    _segments = []
            except Exception as e:
                logger.error(f"         Routing exception: {e}")
                routing_results[mode] = f"exception: {e}"
                continue
            
            # Check route validity
            if not route or len(route) < 2:
                logger.warning(f"         No route computed ({len(route) if route else 0} points)")
                routing_results[mode] = "no_route_computed"
                continue

            # A 2-point route (just [origin, dest]) means routing failed and
            # returned a bare straight line.  Accept it only for very short
            # trips where a straight line IS a reasonable approximation.
            # For trips >0.5km a 2-point route indicates the mode is not
            # reachable (no tram stop within catchment, no GTFS path, etc.)
            # and must be rejected so the BDI planner skips it.
            if len(route) == 2 and straight_line_distance > 0.5:
                logger.warning(
                    f"         ⚠️  Rejecting 2-point route for {mode} "
                    f"({straight_line_distance:.1f}km trip — mode not reachable)"
                )
                routing_results[mode] = "unreachable_2pt_route"
                continue
                
            # Check actual route distance
            from simulation.spatial.coordinate_utils import route_distance_km
            actual_route_distance = route_distance_km(route)
            
            if actual_route_distance == 0.0:
                logger.warning(f"         Zero-distance route")
                routing_results[mode] = "zero_distance"
                continue
            
            # Apply strict distance constraint
            max_distance = self.MODE_MAX_DISTANCE_KM.get(mode, float('inf'))
            if actual_route_distance >= max_distance:
                logger.debug(f"        Route too long: {actual_route_distance:.1f}km >= {max_distance}km")
                routing_results[mode] = f"too_long: {actual_route_distance:.1f}km"
                continue
            
            # Detour ratio check - route should be reasonably direct
            # (Only for active modes where circuitous routes are exhausting)
            if mode in ['walk', 'bike', 'cargo_bike'] and straight_line_distance > 0:
                detour_ratio = actual_route_distance / straight_line_distance
                
                # Relaxed detour thresholds based on distance
                max_detour = 3.0 if straight_line_distance < 1.0 else 2.5  # Allow more detour for short trips
                
                if detour_ratio > max_detour:
                    logger.debug(f"        Route too circuitous: {detour_ratio:.1f}x (max {max_detour}x)")
                    routing_results[mode] = f"too_circuitous: {detour_ratio:.1f}x"
                    continue
            
            # For walking specifically, check if trip is extremely long
            # (This prevents Cramond→Balerno 12km+ straight-line walks, but allows 3-6km walks)
            if mode == 'walk' and straight_line_distance > 8.0:
                logger.debug(f"        Straight-line way too far for walking: {straight_line_distance:.1f}km")
                routing_results[mode] = f"unrealistic_walk: {straight_line_distance:.1f}km straight"
                continue
            
            # SUCCESS! Track the successful route and generate action
            logger.info(f"         SUCCESS: {actual_route_distance:.1f}km route")
            routing_results[mode] = f"success: {actual_route_distance:.1f}km"
            
            params = {}
            if mode in self.EV_RANGE_KM and self.has_infrastructure:
                params = self._get_ev_params(origin, dest, route, context)
            if _segments:
                params['route_segments'] = _segments
            actions.append(Action(mode=mode, route=route, params=params))
        
        # Final summary
        if not actions:
            logger.error(f"   NO VIABLE ACTIONS for {agent_id}!")
            logger.error(f"   Routing results:")
            for mode, result in routing_results.items():
                logger.error(f"     {mode}: {result}")
            
            # If vehicle required, this is CRITICAL
            if vehicle_required:
                logger.error(f"   CRITICAL: vehicle_required=True but no vehicle modes worked!")
                logger.error(f"   This agent will fall back to walk despite needing a vehicle.")
        else:
            logger.info(f"âœ… Generated {len(actions)} viable actions for {agent_id}")
            for action in actions:
                # Abstract routes store distance in params; OSMnx routes need calculation
                if action.params.get('abstract'):
                    dist = action.params.get('trip_distance_km', 0.0)
                else:
                    from simulation.spatial.coordinate_utils import route_distance_km
                    dist = route_distance_km(action.route)
                logger.info(f"     - {action.mode}: {dist:.1f}km")
        
        return actions
    
    # Revised mode filtering logic
    def _filter_modes_by_context(self, context: Dict, trip_distance_km: float = 0.0) -> List[str]:
        """Fixed version with better cargo_bike handling."""
        
        vehicle_required = context.get('vehicle_required', False)
        cargo_capacity = context.get('cargo_capacity', False)
        vehicle_type = context.get('vehicle_type', 'personal')
        priority = context.get('priority', 'normal')

        # DEBUG: Log initial context
        logger.debug(f"🔍 _filter_modes_by_context called:")
        logger.debug(f"   vehicle_type={vehicle_type}")
        logger.debug(f"   vehicle_required={vehicle_required}")
        logger.debug(f"   trip_distance_km={trip_distance_km:.1f}")
        
        modes = []

        # ── FusedIdentity override (Phase 10) ────────────────────────────────
        # If agent_context carries a FusedIdentity (set by StoryDrivenAgent via
        # PersonaFusion.fuse()), its allowed_modes is the authoritative hard
        # constraint — encodes persona + job mode restrictions including abstract
        # rail/ferry/air modes.  We bypass STEP 1 vehicle_type branching and
        # STEP 2 multi-modal extension.  STEP 3 distance filter and STEP 3.5
        # non-vehicle removal still apply.
        _fused = context.get('fused_identity')
        _fused_allowed = (
            _fused is not None
            and getattr(_fused, 'allowed_modes', None) is not None
            and len(_fused.allowed_modes) > 0
        )

        if _fused_allowed:
            modes = list(dict.fromkeys(_fused.allowed_modes))  # ordered, no dups
            logger.debug(
                "FusedIdentity mode override for %s: %s",
                getattr(_fused, 'agent_label', '?'), modes,
            )
            original_modes = modes.copy()

        else:
            # STEP 1: Initial mode selection (legacy path — no FusedIdentity)
            if context.get('operator_type') == 'taxi':
                modes = ['taxi_ev', 'taxi_diesel', 'ev', 'car']
                logger.debug(f"Taxi context: initial modes {modes}")

            elif vehicle_type == 'micro_mobility':
                if trip_distance_km > 20:
                    modes = ['cargo_bike', 'van_electric', 'van_diesel']
                    logger.warning(
                        f"Micro-mobility trip {trip_distance_km:.1f}km > 20km → "
                        f"allowing van backup: {modes}"
                    )
                else:
                    modes = ['cargo_bike', 'bike', 'ebike']
                    logger.debug(f"Micro-mobility context: initial modes {modes}")

            elif vehicle_type == 'heavy_freight':
                modes = ['hgv_diesel', 'hgv_electric', 'hgv_hydrogen', 'truck_diesel', 'truck_electric']
                logger.debug(f"Heavy freight context: initial modes {modes}")

            elif vehicle_type == 'medium_freight':
                modes = ['truck_electric', 'truck_diesel', 'van_diesel', 'van_electric']
                logger.debug(f"Medium freight context: initial modes {modes}")

            elif vehicle_type == 'commercial':
                modes = ['van_electric', 'van_diesel', 'cargo_bike']
                logger.debug(f"Commercial context: initial modes {modes}")

            elif vehicle_type == 'transit':
                modes = [
                    'local_train', 'intercity_train', 'tram', 'bus',
                    'ferry_diesel', 'ferry_electric',
                    'walk', 'bike', 'e_scooter', 'ev', 'car'
                ]
                logger.debug(f"Transit context: initial modes {modes}")

            elif priority == 'emergency':
                modes = ['car', 'ev', 'bus']
            elif context.get('luggage_present') or context.get('wheelchair_accessible'):
                modes = ['car', 'ev', 'bus', 'tram']
            else:
                modes = self.default_modes.copy()

            original_modes = modes.copy()

            # STEP 2: Multi-modal options (legacy path only)
            if trip_distance_km > 0 and not vehicle_required:
                if trip_distance_km > 80:
                    modes.extend(['intercity_train', 'flight_domestic'])
                elif trip_distance_km > 30:
                    modes.extend(['local_train', 'tram'])

                if context.get('coastal_route') or context.get('island_destination'):
                    modes.extend(['ferry_diesel', 'ferry_electric'])

                if trip_distance_km < 15 and not cargo_capacity:
                    modes.append('e_scooter')
        
        # STEP 3: Distance filtering with RELAXED safety margin for cargo_bike
        if trip_distance_km > 0:
            filtered_modes = []
            
            for m in modes:
                max_distance = self.MODE_MAX_DISTANCE_KM.get(m, float('inf'))
                
                # SPECIAL CASE: Cargo bike gets 0.9x margin instead of 0.65x
                # This allows up to 45km trips (50km * 0.9) instead of 32.5km (50km * 0.65)
                if m == 'cargo_bike':
                    safety_factor = 0.9  # More generous for cargo bikes
                else:
                    safety_factor = 0.65  # Standard safety margin
                
                if trip_distance_km < (max_distance * safety_factor):
                    filtered_modes.append(m)
            
            removed = set(modes) - set(filtered_modes)
            if removed:
                logger.debug(f"Distance filter ({trip_distance_km:.1f}km): removed {removed}")
            
            modes = filtered_modes

            logger.debug(f"🔍 Before STEP 3.5: modes={modes}, vehicle_required={vehicle_required}")

        # STEP 3.5 — Remove non-vehicle modes if vehicle_required
        if vehicle_required:
            non_vehicle_modes = ['walk', 'bike', 'e_scooter']
            before = len(modes)
            modes = [m for m in modes if m not in non_vehicle_modes]
            removed = before - len(modes)
            if removed > 0:
                logger.debug(f"Removed {removed} non-vehicle modes (vehicle_required=True)")

        # STEP 3.6 — Remove freight modes for personal agents
        # SKIP when FusedIdentity override is active — it already made this call.
        _FREIGHT_MODES = {
            'van_electric', 'van_diesel',
            'truck_electric', 'truck_diesel',
            'hgv_electric', 'hgv_diesel', 'hgv_hydrogen',
            'taxi_ev', 'taxi_diesel',
        }
        if not _fused_allowed and vehicle_type == 'personal' and not vehicle_required:
            before_set = set(modes)
            modes = [m for m in modes if m not in _FREIGHT_MODES]
            removed_freight = before_set - set(modes)
            if removed_freight:
                logger.debug(
                    "Personal agent filter: removed freight modes %s",
                    removed_freight,
                )
       
        # STEP 4: Intelligent fallback (NEVER RETURN EMPTY!)
        if not modes:
            logger.warning(f"âš ï¸ No modes after filtering! Original: {original_modes}, distance: {trip_distance_km:.1f}km")
            
            if vehicle_type == 'heavy_freight':
                modes = ['hgv_diesel']
                logger.warning(f"Fallback: Using {modes} for heavy freight")
            elif vehicle_type == 'medium_freight':
                modes = ['truck_diesel']
                logger.warning(f"Fallback: Using {modes} for medium freight")
            elif vehicle_type == 'commercial':
                modes = ['van_diesel']
                logger.warning(f"Fallback: Using {modes} for commercial")
            elif vehicle_type == 'transit':
                modes = ['bus', 'car']
                logger.warning(f"Fallback: Using {modes} for transit (bus or car)")
            elif vehicle_type == 'micro_mobility':
                # Upgrade to van if we're in fallback (means too long)
                modes = ['van_diesel', 'van_electric']
                logger.warning(f"Fallback: Upgrading micro-mobility to VAN (trip too long for cargo bike)")
            else:
                if trip_distance_km > 200:
                    modes = ['car', 'bus', 'intercity_train']
                elif trip_distance_km > 50:
                    modes = ['car', 'bus', 'local_train']
                else:
                    modes = ['car', 'bike', 'walk']
                logger.warning(f"Fallback: Using {modes} for {trip_distance_km:.1f}km trip")
        
        logger.debug(
            "Final modes for vehicle_type=%s, distance=%.1fkm: %s",
            vehicle_type, trip_distance_km, modes,
        )
        return modes
    
    def _is_mode_feasible(
        self,
        mode: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        state,
        context: Dict
    ) -> bool:
        """
        Check if mode is feasible (infrastructure check for EVs).

        Phase 10c — Hard reliability constraint for operational-critical agents:
        Agents with reliability_critical=True AND persona_type='freight' (or
        job urgency='critical') are HARD-BLOCKED from EV modes when charger
        availability cannot be guaranteed. This applies to paramedics, ambulances,
        and freight operators with SLA obligations — NOT to passenger personas whose
        narrative contains safety/children vocabulary (those use soft cost weighting).

        Passenger personas (eco_warrior, concerned_parent) with reliability_critical
        set by narrative keywords are deliberately excluded from the hard block —
        they should still consider EV; their 'safety' concern is a preference, not
        an operational constraint. Only vehicle_type='commercial'/'heavy_freight'
        agents face the hard block.
        """
        # ── Phase 10c: Hard block — operational reliability only ──────────
        # reliability_critical is set by CPG for:
        #   - ambulance_emergency_response job (urgency='critical')
        #   - any agent whose desire_overrides.reliability >= 1.0 (paramedic)
        #   - passenger narratives mentioning safety/children (EXCLUDED from hard block)
        #
        # Only freight persona_type agents get the hard block.
        # Passenger agents with reliability_critical=True use soft cost weighting only.
        vehicle_type = context.get('vehicle_type', 'personal')
        is_operational_critical = (
            context.get('reliability_critical', False)
            and vehicle_type in ('commercial', 'heavy_freight', 'medium_freight')
        )
        if is_operational_critical and mode in self.EV_RANGE_KM:
            # BUG FIX: default 0.0 (available) not 1.0 (full) — most runs have no
            # real charger occupancy signal, defaulting to 1.0 falsely blocked ALL EVs.
            charger_occ = context.get('charger_occupancy_nearby', 0.0)
            if charger_occ > 0.1:
                logger.debug(
                    "%s HARD BLOCKED from %s: operational_critical=True, "
                    "charger_occupancy_nearby=%.2f (>0.1 threshold)",
                    getattr(state, 'agent_id', '?'), mode, charger_occ,
                )
                return False
            # Enforce 70% range buffer for operational-critical agents
            from simulation.spatial.coordinate_utils import haversine_km
            trip_distance = haversine_km(origin, dest)
            # Route realism: multiply straight-line by a route factor (default 1.35)
            route_factor = float(context.get('route_factor', 1.35))
            trip_distance *= route_factor
            # Effect: operationally critical agents (freight/ambulance) evaluate a more realistic 
            # trip length before the 70% buffer check.

            max_range = self.EV_RANGE_KM.get(mode, 350.0)
            if trip_distance > max_range * 0.7:
                logger.debug(
                    "%s HARD BLOCKED from %s: operational_critical=True, "
                    "%.1fkm > %.1fkm (70%% range buffer)",
                    getattr(state, 'agent_id', '?'), mode,
                    trip_distance, max_range * 0.7,
                )
                return False
        # Only check infrastructure for VEHICLE EVs
        # Cargo bikes and e-scooters don't use charging infrastructure
        non_infrastructure_evs = ['cargo_bike', 'e_scooter', 'bike']
        
        if mode in non_infrastructure_evs:
            # These modes don't need charging stations
            return True
        
        # Only check infrastructure for vehicle electric modes
        if not self.has_infrastructure or mode not in self.EV_RANGE_KM:
            return True
        
        # Calculate trip distance
        from simulation.spatial.coordinate_utils import haversine_km
        trip_distance = haversine_km(origin, dest)

        # Estimate route length (straight-line × route_factor)
        route_factor = float(context.get('route_factor', 1.35))
        est_trip_km = trip_distance * route_factor

        # Local saturation realism for EVs (soft feasibility)
        # Prefer infrastructure signals; fallback to context; unknown => 0.0 (available)
        occ_threshold = float(context.get('occ_threshold_block', 0.85))    # block if ≥ 85% utilized
        short_trip_km = float(context.get('short_trip_km', 8.0))           # short trips ignore saturation
        radius_km     = float(context.get('dest_nearby_radius_km', 2.0))   # also used later for near-range check

        occ = context.get('charger_occupancy_nearby', None)
        if occ is None:
            # Try to read live utilization from the charging registry via InfrastructureManager
            reg = getattr(self.infrastructure, 'charging_registry', None) \
                or getattr(self.infrastructure, 'charging_station_registry', None)
            if reg is not None and hasattr(reg, 'average_utilization_near'):
                try:
                    occ = float(reg.average_utilization_near(origin, radius_km=radius_km))
                except Exception:
                    occ = 0.0
        if occ is None:
            occ = 0.0

        # Local saturation realism (soft feasibility)
        if mode in self.EV_RANGE_KM and occ >= occ_threshold and est_trip_km > short_trip_km:
            logger.debug(
                "%s not feasible: local charger utilization=%.2f >= %.2f and "
                "est_trip=%.1fkm > short_trip_km=%.1f",
                mode, occ, occ_threshold, est_trip_km, short_trip_km
            )
            return False
        #  Effect: even when context doesn’t set charger_occupancy_nearby, planner can block EV 
        # in locally saturated areas based on the live registry.

        # Local saturation realism for EVs (soft feasibility)
        # Defaults are conservative and can be overridden from `context`.
        charger_occ = float(context.get('charger_occupancy_nearby', 0.0))  # unknown => 0.0 (available)
        occ_threshold = float(context.get('occ_threshold_block', 0.85))    # block if ≥ 85% utilized
        short_trip_km = float(context.get('short_trip_km', 8.0))           # short trips can ignore saturation

        if mode in self.EV_RANGE_KM and charger_occ >= occ_threshold and trip_distance > short_trip_km:
            logger.debug(
                "%s not feasible: local charger utilization=%.2f ≥ %.2f and trip=%.1fkm > short_trip_km=%.1f",
                mode, charger_occ, occ_threshold, trip_distance, short_trip_km
            )
            return False
        
        # Get range for this EV type
        max_range = self.EV_RANGE_KM.get(mode, 350.0)
        
        # Range check with 90% safety margin
        if trip_distance > max_range * 0.9:
            logger.debug(f"{mode} not feasible: {trip_distance:.1f}km > {max_range*0.9:.1f}km range")
            return False

        # All remaining checks require a live infrastructure manager.
        # Running without infrastructure (tests, no InfrastructureManager) → skip charger checks.
        if not self.has_infrastructure or self.infrastructure is None:
            return True

        # Near-range realism: trips approaching range limit require a charger near destination.
        if mode in self.EV_RANGE_KM:
            dest_nearby_km = float(context.get('dest_nearby_radius_km', 2.0))
            if est_trip_km > max_range * 0.8:
                nearest = self.infrastructure.find_nearest_charger(dest, max_distance_km=dest_nearby_km)
                if nearest is None:
                    logger.debug(
                        f"{mode} not feasible: near-range (est_trip {est_trip_km:.1f}km ≈ {max_range:.1f}km) "
                        f"and no charger within {dest_nearby_km:.1f}km of destination"
                    )
                    return False

        if trip_distance > max_range * 0.8:
            dest_nearby_km = float(context.get('dest_nearby_radius_km', 2.0))
            nearest = self.infrastructure.find_nearest_charger(dest, max_distance_km=dest_nearby_km)
            if nearest is None:
                logger.debug(
                    f"{mode} not feasible: near-range ({trip_distance:.1f}km ≈ {max_range:.1f}km) "
                    f"and no charger within {dest_nearby_km:.1f}km of destination"
                )
                return False

        # Long-trip charger availability (5 km radius)
        if trip_distance > max_range * 0.5:
            nearest = self.infrastructure.find_nearest_charger(dest, max_distance_km=5.0)
            if nearest is None:
                logger.debug(f"{mode} not feasible: no charger within 5km of destination")
                return False

        return True

    
    # This function gathers detailed parameters about the EV trip, including distance, 
    # nearest charger info, and grid stress factors.
    # This allows the cost function to make more informed decisions about EV feasibility 
    # and costs.
    # This is especially important for freight modes, where range and charging logistics 
    # are critical factors in mode choice.
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

        # BUG FIX 1: Defensive guard against None infrastructure
        if not getattr(self, 'has_infrastructure', False) or self.infrastructure is None:
            return params
        
        # BUG FIX 2: Utilize 'context' to make the search dynamic rather than a hardcoded 2.0km.
        search_radius = float(context.get('dest_nearby_radius_km', 2.0))
        nearest = self.infrastructure.find_nearest_charger(
            dest, charger_type='any', max_distance_km=search_radius
        )

        # Implement the intended logic: Freight modes may be more tolerant of detours
        if not nearest and context.get('vehicle_type') in ['commercial', 'medium_freight', 'heavy_freight']:
            nearest = self.infrastructure.find_nearest_charger(
                dest, charger_type='any', max_distance_km=search_radius * 3.0  # Expand to 6km for freight
            )

        # If no charger found within 2km, try a wider search for freight modes, which may be more tolerant of detours
        if nearest:
            station_id, distance_to_charger = nearest
            params['nearest_charger'] = station_id
            params['charger_distance_km'] = distance_to_charger
            
            availability = self.infrastructure.get_charger_availability(station_id)
            params['charger_available'] = availability.get('available', False)
            params['charger_wait_min'] = availability.get('estimated_wait_min', 0)
            params['charging_cost_kwh'] = availability.get('cost_per_kwh', 0.15)
        
        return params
    
    # Enhanced cost function to include freight mode preference bonuses, 
    # which lower the cost of freight modes when the agent context indicates a freight 
    # delivery. Logic is based on the agent's vehicle type and priority, allowing for 
    # more nuanced mode selection that better reflects the needs of freight deliveries 
    # while still considering the agent's desires and the trip characteristics.
    def cost(
        self,
        action: Action,
        env,
        state,
        desires: Dict[str, float],
        agent_context: Optional[Dict] = None
    ) -> float:
        """
        Calculate action cost with freight mode bonuses and Markov habit discount.
 
        Markov: if the agent carries a PersonalityMarkovChain
        (exposed via agent_context['mode_chain']), habitual modes receive a
        small cost discount proportional to their self-transition probability.
 
        The discount is intentionally modest (max 12%) so the BDI desire
        weights still dominate — habit nudges rather than locks.
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

        # ── Abstract mode schedule-risk adjustment ────────────────────────────
        # Rail/ferry/air services run on fixed schedules.  If an agent misses a
        # train there is a wait cost that does not exist for car/bike/EV.
        # This is separate from the boarding_penalty (already in MetricsCalculator)
        # and captures the agent's *preference* response to that risk.
        #
        # Only applied to abstract modes — routeable modes have no schedule risk.
        _ABSTRACT_MODES = {
            'local_train', 'intercity_train', 'freight_rail',
            'ferry_diesel', 'ferry_electric',
            'flight_domestic', 'flight_electric',
        }
        schedule_risk_penalty = 0.0
        if mode in _ABSTRACT_MODES:
            # Agents who value reliability penalise scheduled modes more
            w_reliability = desires.get('reliability', desires.get('maximize_reliability', 0.5))
            # Read scenario-tuned boarding penalty if available; else use defaults
            _DEFAULT_BOARD = {'local_train': 20, 'intercity_train': 25,
                              'freight_rail': 30, 'ferry_diesel': 35,
                              'ferry_electric': 35, 'flight_domestic': 75,
                              'flight_electric': 75}
            boarding_min = float(
                context.get('boarding_penalty_min')
                or _DEFAULT_BOARD.get(mode, 20)
            )
            # Normalise penalty: 20 min → 0.33, 75 min → 1.25
            schedule_risk_penalty = w_reliability * (boarding_min / 60.0) * 0.5
            logger.debug(
                "Schedule risk penalty for %s: %.3f (reliability=%.2f, board=%dmin)",
                mode, schedule_risk_penalty, w_reliability, boarding_min,
            )

        # Infrastructure adjustments
        infrastructure_penalty = 0.0

        if mode in self.EV_RANGE_KM and self.has_infrastructure:
            trip_distance = params.get('trip_distance_km', 0)
            max_range = self.EV_RANGE_KM.get(mode, 350.0)
            range_ratio = trip_distance / max_range
 
            if range_ratio > 0.9:
                range_anxiety = desires.get('range_anxiety', 0.5)
                infrastructure_penalty += range_anxiety * 2.0
            elif range_ratio > 0.7:
                range_anxiety = desires.get('range_anxiety', 0.5)
                infrastructure_penalty += range_anxiety * 0.5
 
            if 'nearest_charger' in params:
                if not params.get('charger_available', False):
                    wait_time = params.get('charger_wait_min', 30)
                    time_norm += (wait_time / 60.0) * w_time
 
                    if w_time > 0.7:
                        infrastructure_penalty += 0.3
 
                charging_cost_kwh = params.get('charging_cost_kwh', 0.15)
                charging_cost = (trip_distance * 0.2) * charging_cost_kwh
                cost_norm += (charging_cost / 5.0) * w_cost
 
                detour_km = params.get('charger_distance_km', 0)
                if detour_km > 0.5:
                    time_norm += (detour_km / 30.0)
            else:
                infrastructure_penalty += 1.0
 
            if self.infrastructure:
                grid_stress = self.infrastructure.get_grid_stress_factor()
                if grid_stress > 1.0:
                    time_norm *= grid_stress
                    cost_norm *= grid_stress
 
        # Priority adjustments
        priority = context.get('priority', 'normal')
        vehicle_type = context.get('vehicle_type', 'personal')

        if priority == 'emergency':
            w_time = 1.0
            w_cost = 0.0
            w_risk = 0.0
        elif priority == 'commercial' or vehicle_type in [
            'commercial', 'medium_freight', 'heavy_freight', 'micro_mobility'
        ]:
            w_time = 0.7
            w_cost = 0.2

        # Calculate total cost. Total cost is a weighted sum of normalized time, cost, 
        # comfort penalty, risk, and emissions, plus any infrastructure penalties. 
        # Freight mode preference bonuses are applied after the initial cost calculation 
        # to ensure that they influence the final mode choice effectively.
        total_cost = (
            w_time * time_norm
            + w_cost * cost_norm
            + w_comfort * comfort_penalty
            + w_risk * risk
            + w_eco * emissions_norm
            + infrastructure_penalty
            + schedule_risk_penalty   # abstract mode schedule/reliability cost
        )

        # Apply freight mode preference bonuses
        freight_modes = [
            'van_electric', 'van_diesel',
            'cargo_bike',
            'truck_electric', 'truck_diesel',
            'hgv_electric', 'hgv_diesel', 'hgv_hydrogen',
        ]
        # Freight modes get a cost reduction bonus if the agent context indicates a freight delivery,
        # with the size of the bonus depending on the specific vehicle type. This encourages the planner 
        # to select freight-appropriate modes when the agent is in a freight context, while still allowing
        # for other modes to be chosen if they are significantly better in terms of the base cost metrics.
        if (
            priority == 'commercial'
            or vehicle_type in [
                'commercial', 'medium_freight', 'heavy_freight', 'micro_mobility'
            ]
        ) and mode in freight_modes:
            if vehicle_type == 'micro_mobility' and mode == 'cargo_bike':
                total_cost *= 0.6
            elif vehicle_type in ['heavy_freight', 'medium_freight']:
                total_cost *= 0.65
            else:
                total_cost *= 0.7

        # ── Phase 3: Markov habit discount ───────────────────────────────────
        # If the agent has a PersonalityMarkovChain, habitual modes cost less.
        # The discount is proportional to the self-transition probability P(mode|mode)
        # capped at 12% so desires still dominate the decision.
        #
        # Example: eco_warrior who has cycled 8 consecutive days has
        #   habit_strength(bike) ≈ 0.72  →  discount ≈ 8.6%
        # A brand-new agent has habit_strength ≈ 0.45  →  discount ≈ 5.4%
        # No mode_chain (import failed) → discount = 0, no effect.
        _mode_chain = context.get('mode_chain')
        if _mode_chain is not None:
            try:
                current_mode = getattr(state, 'mode', mode)
                prior = _mode_chain.get_prior(current_mode)
                habit_p = prior.get(mode, 0.0)
 
                # Discount: up to 12% for fully habitual mode (habit_p → 1.0)
                _MAX_HABIT_DISCOUNT = 0.12
                habit_discount = _MAX_HABIT_DISCOUNT * habit_p
                total_cost *= (1.0 - habit_discount)
 
                if habit_discount > 0.05:
                    logger.debug(
                        "Markov habit discount %.1f%% on %s for agent %s "
                        "(habit_p=%.2f, streak=%d)",
                        habit_discount * 100,
                        mode,
                        getattr(state, 'agent_id', '?'),
                        habit_p,
                        _mode_chain.habit_counts.get(mode, 0),
                    )
            except Exception as _me:
                logger.debug("Markov discount failed: %s", _me)
            # ── End Phase 3 Markov ───────────────────────────────────────────────────────
 
        # Apply scenario cost factor (e.g. EV Subsidy 30% → factor=0.70)
        # mode_cost_factors is populated by apply_scenario_cost_factors() when a
        # scenario YAML declares cost_reduction/cost_increase for a specific mode.
        # Without this, scenario YAML policies targeting mode costs had no effect
        # on the BDI decision — the subsidy was loaded but silently ignored.
        scenario_factor = self.mode_cost_factors.get(mode, 1.0)
        if scenario_factor != 1.0:
            total_cost *= scenario_factor
            logger.debug(
                "Scenario factor %.2f applied to %s: cost %.3f → %.3f",
                scenario_factor, mode, total_cost / scenario_factor, total_cost,
            )

        # Add stochastic noise (±15%)
        total_cost += random.uniform(-0.15, 0.15)
        
        return total_cost
    
    # This function evaluates all feasible actions by calculating their costs and optionally 
    # providing a detailed cost breakdown for XAI purposes. The cost breakdown includes 
    # time, monetary cost, comfort penalty, risk, emissions, and any infrastructure-related 
    # factors such as charging wait times or range anxiety for EVs. This detailed breakdown 
    # allows the planner to explain its choices in a more transparent way, especially when 
    # freight modes are involved and the decision may be influenced by specific parameters 
    # related to freight deliveries.
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
        # Evaluate each action and calculate cost, including detailed breakdown for XAI
        for action in actions:
            cost = self.cost(action, env, state, desires, agent_context)
            
            breakdown = None
            if self.has_infrastructure:
                breakdown = self._calculate_cost_breakdown(action, env, desires, agent_context)
            # The breakdown provides insights into the specific factors contributing to the cost of each action, 
            # which can be used for explaining the planner's choices to users or for debugging purposes. 
            # This is especially important for freight modes, where factors like charging logistics and 
            # range anxiety can play a significant role in mode choice.
            scores.append(ActionScore(action=action, cost=cost, breakdown=breakdown))
        
        return scores
    
    # This function calculates a detailed cost breakdown for a given action, including 
    # time, monetary cost, comfort penalty, risk, emissions, and any infrastructure-related 
    # factors such as charging wait times or range anxiety for EVs. This breakdown is used 
    # for explainability purposes, allowing the planner to provide insights into why certain 
    # modes were chosen over others, especially in freight contexts where specific parameters 
    # can heavily influence the decision.
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
        # The breakdown includes the key cost components that contribute to the overall 
        # cost of the action, allowing for a more transparent explanation of the planner's
        # choices. This is particularly valuable for freight modes, where factors like 
        # charging logistics and range anxiety can be significant and may not be immediately 
        # obvious to users.
        breakdown = {
            'time': env.estimate_travel_time(route, mode) / 60.0,
            'cost': env.estimate_monetary_cost(route, mode),
            'comfort': 1.0 - env.estimate_comfort(route, mode),
            'risk': env.estimate_risk(route, mode),
            'emissions': env.estimate_emissions(route, mode) / 500.0,
        }
        # Logic here is to add specific breakdown components related to EV infrastructure 
        # when evaluating EV modes, which can be critical factors in the cost and mode choice, 
        # especially for freight deliveries where range and charging logistics are important 
        # considerations.
        if mode in self.EV_RANGE_KM:
            breakdown['charging_wait'] = action.params.get('charger_wait_min', 0) / 60.0
            breakdown['range_anxiety'] = action.params.get('trip_distance_km', 0) / self.EV_RANGE_KM.get(mode, 350.0)
        
        return breakdown
    
    # This function selects the best action based on the lowest cost from the evaluated scores.
    # It includes enhanced logging to provide insights into the decision-making process, which is
    # especially useful for debugging and understanding mode choice in freight contexts where the
    # decision may be influenced by specific parameters related to freight deliveries.
    def choose_action(self, scores: List[ActionScore]) -> Action:
        """Choose best action (lowest cost)."""
        if not scores:
            logger.error("❌ NO SCORES TO CHOOSE FROM - RETURNING WALK FALLBACK")
            return Action(mode='walk', route=[], params={})
        # By bets we mean the action with the lowest cost, which is the most preferred 
        # action according to the planner's evaluation.
        best = min(scores, key=lambda s: s.cost)
        logger.info(f"✅ Chose {best.action.mode} with cost {best.cost:.2f}")
        return best.action
    # This function generates an explanation for why a particular action was chosen, based on the
    # evaluated scores and the agent's desires. The explanation includes insights into the 
    # agent's priorities, the cost breakdown of the chosen action, and any specific factors 
    # that influenced the decision. This is particularly important for freight modes, where 
    # the choice may be influenced by specific parameters related to freight deliveries, 
    # such as charging logistics and range anxiety.
    def explain_choice(
        self,
        chosen: Action,
        all_scores: List[ActionScore],
        desires: Dict[str, float]
    ) -> str:
        """Explain why an action was chosen (XAI)."""
        mode = chosen.mode
        # The explanation provides a detailed rationale for why the chosen mode was selected, 
        # including the agent's priorities and the specific cost components that influenced 
        # the decision. Useful for freight modes, where factors like charging logistics and 
        # range anxiety can play a significant role in mode choice and may not be immediately 
        # obvious to users.
        chosen_score = next((s for s in all_scores if s.action.mode == mode), None)
        if not chosen_score:
            return f"Chose {mode} (no explanation available)"
        
        top_desires = sorted(desires.items(), key=lambda x: x[1], reverse=True)[:3]
        desire_str = ', '.join(f'{k}={v:.1f}' for k, v in top_desires)
        
        explanation = (
            f"Chose {mode} because:\n"
            f"  My priorities: {desire_str}\n"
            f"  Total cost: {chosen_score.cost:.2f}\n"
        )
        
        if mode in self.EV_RANGE_KM and 'charger_wait_min' in chosen.params:
            wait = chosen.params['charger_wait_min']
            if wait > 0:
                explanation += f"  (Charging wait: {wait:.0f} min)\n"
        # Include the cost breakdown in the explanation to provide insights into the specific 
        # factors that contributed to the cost of the chosen action, which can help users 
        # understand why certain modes were preferred over others, especially in freight 
        # contexts where specific parameters can heavily influence the decision.
        if chosen_score.breakdown:
            breakdown = chosen_score.breakdown
            top_costs = sorted(breakdown.items(), key=lambda x: x[1], reverse=True)[:3]
            cost_str = ', '.join(f'{k}={v:.2f}' for k, v in top_costs)
            explanation += f"  Main costs: {cost_str}\n"
        
        return explanation