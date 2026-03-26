"""
agent/contextual_plan_generator.py

Extracts executable plans from user story + job story context.

This is the missing piece that enables:
- Same persona + different jobs → different plans
- Context-aware mode filtering
- Emergent behavior from story constraints

Implementation:
- Rule-based extraction (always available)
- LLM-based extraction (optional enhancement)
- Graceful fallback: LLM → rules → defaults

"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Any
import logging
import json
import re

# Import LLM
try:
    from services.llm_client import LLMClient
    _LLM_CLIENT_AVAILABLE = True
except ImportError:
    _LLM_CLIENT_AVAILABLE = False
    LLMClient = None
    
logger = logging.getLogger(__name__)

# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class ExtractedPlan:
    """
    Plan extracted from user story + job story context.
    
    This represents the "WHAT" and "HOW" of the agent's task,
    extracted from the narrative context rather than hardcoded.
    """
    plan_type: str  # 'point_to_point', 'multi_stop', 'scheduled', 'flexible'
    
    # ========================================================================
    # TEMPORAL CONSTRAINTS
    # ========================================================================
    schedule_fixed: bool = False
    """Is this trip on a fixed schedule? (e.g., school run, shift work)"""
    
    time_window_start: Optional[str] = None
    """Start of time window (HH:MM format)"""
    
    time_window_end: Optional[str] = None
    """End of time window (HH:MM format)"""
    
    recurring_pattern: Optional[str] = None
    """Recurring pattern: 'daily', 'weekly', None"""
    
    # ========================================================================
    # SPATIAL CONSTRAINTS
    # ========================================================================
    waypoints: List[Tuple[float, float]] = field(default_factory=list)
    """Intermediate waypoints for multi-stop trips"""
    
    avoid_areas: List[str] = field(default_factory=list)
    """Areas to avoid (e.g., 'busy roads', 'construction zones')"""
    
    # ========================================================================
    # OPTIMIZATION OBJECTIVES
    # ========================================================================
    primary_objective: str = 'minimize_time'
    """Primary optimization goal: 'minimize_time', 'minimize_carbon', 'minimize_cost'"""
    
    secondary_objectives: List[str] = field(default_factory=list)
    """Secondary objectives (e.g., ['maximize_safety', 'maximize_comfort'])"""
    
    # ========================================================================
    # REGULATORY/POLICY CONSTRAINTS
    # ========================================================================
    must_comply_with: List[str] = field(default_factory=list)
    """Regulatory constraints (e.g., ['low_emission_zone', 'driver_hours_regulation'])"""
    
    # ========================================================================
    # OPERATIONAL REQUIREMENTS
    # ========================================================================
    reliability_critical: bool = False
    """Operational reliability constraint (freight/blue-light only).
    Passenger narrative keywords set this flag as a PREFERENCE — it influences
    cost weighting but does NOT trigger the BDI hard EV block (which is restricted
    to commercial/heavy_freight vehicle types only)."""

    asi_tier: str = 'improve'
    """ASI intent tier: 'avoid' | 'shift' | 'improve'. Computed from persona/job."""

    ev_viability_belief_hint: float = 0.5
    """Persona-calibrated EV adoption threshold. Freight:0.65-0.70. Eco:0.35. Critical:0.85."""

    """Is reliability paramount? (e.g., children present, time-critical delivery)"""
    
    flexibility_allowed: bool = True
    """Can this trip be rescheduled or delayed?"""
    
    weather_sensitive: bool = False
    """Is this trip affected by weather? (e.g., cycling with children)"""
    
    # ========================================================================
    # METADATA
    # ========================================================================
    extraction_method: str = 'rule_based'
    """How was this plan extracted? 'rule_based', 'llm', 'hybrid'"""
    
    confidence: float = 1.0
    """Confidence in extraction (0-1)"""
    
    reasoning: Optional[str] = None
    """Explanation of why this plan was extracted (for XAI)"""
    
    def __repr__(self) -> str:
        return (
            f"ExtractedPlan(type={self.plan_type}, "
            f"objective={self.primary_objective}, "
            f"fixed={self.schedule_fixed}, "
            f"critical={self.reliability_critical})"
        )

# ============================================================================
# CONTEXTUAL PLAN GENERATOR
# ============================================================================

class ContextualPlanGenerator:
    """
    Extract executable plans from user story + job story context.
    
    This is the CORE INNOVATION that enables:
    - Dynamic plan generation from narrative context
    - Same persona behaving differently in different contexts
    - Emergent behavior from story constraints
    
    Usage:
        generator = ContextualPlanGenerator()
        plan = generator.extract_plan_from_context(
            user_story=eco_warrior,
            job_story=school_run,
            origin=(lon, lat),
            dest=(lon, lat)
        )
        
        # Use plan to filter modes in BDI planner
        if plan.primary_objective == 'minimize_carbon':
            candidate_modes = ['walk', 'bike', 'bus', 'ev']
    """
    
    def __init__(
        self, 
        llm_backend: str = 'rule_based',
        llm_config: Optional[Dict] = None
    ):
        """
        Initialize plan generator.
        
        Args:
            llm_backend: 'rule_based', 'olmo', 'claude'
            llm_config: Config for LLM clients (if using LLM)
        """
        self.backend = llm_backend
        self.config = llm_config or {}
        
        # LLM client (optional)
        self.llm = None
        if llm_backend in ['olmo', 'claude']:
            self.llm = self._init_llm_client(llm_backend)
        
        logger.info(f"ContextualPlanGenerator initialized: backend={llm_backend}")
    
    # ---- LLM Client -------------------------------------------------
    def _init_llm_client(self, backend: str):
        """
        Initialise shared LLMClient (OLMo primary, Anthropic fallback).
 
        Reads config/ingestion.yaml automatically so URL, model, and
        timeout stay consistent with the Phase 9 ingestion service.
        Falls back to defaults if config is absent.
        """
        if not _LLM_CLIENT_AVAILABLE:
            logger.warning(
                "ContextualPlanGenerator: LLMClient not available "
                "(services/llm_client.py missing), using rule_based"
            )
            return None
 
        client = LLMClient.from_config_file()
 
        # Override backend if caller explicitly requested anthropic
        if backend == "anthropic":
            client.backend = "anthropic"
 
        logger.info(
            "ContextualPlanGenerator: LLMClient ready "
            "(backend=%s, model=%s, ollama=%s)",
            client.backend,
            client.olmo_model,
            "✅" if client.is_available() else "⚠️ not reachable",
        )
        return client
    
    
    # ========================================================================
    # MAIN ENTRY POINT
    # ========================================================================
    
    def extract_plan_from_context(
        self,
        user_story: Any,  # UserStory object
        job_story: Any,   # JobStory object
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        csv_data: Optional[Dict] = None
    ) -> ExtractedPlan:
        """
        Main entry point: Extract plan from stories.
        
        Args:
            user_story: UserStory object (WHO)
            job_story: JobStory object (WHAT)
            origin: Origin coordinates (lon, lat)
            dest: Destination coordinates (lon, lat)
            csv_data: Optional CSV data with additional parameters
        
        Returns:
            ExtractedPlan with all constraints and objectives
        
        Example:
            user: "concerned_parent" - wants to reduce carbon, children's safety
            job: "school_run" - fixed schedule, 5km, daily
            
            → ExtractedPlan(
                schedule_fixed=True,
                primary_objective='minimize_carbon',
                reliability_critical=True,
                weather_sensitive=True
            )
        """
        
        # Try LLM extraction first (if available)
        if self.llm:
            try:
                plan = self._extract_with_llm(
                    user_story, job_story, origin, dest, csv_data
                )
                logger.info(f"LLM extraction successful: {plan}")
                return plan
            except Exception as e:
                logger.warning(f"LLM extraction failed: {e}, falling back to rules")
        
        # Fallback to rule-based extraction
        plan = self._extract_with_rules(
            user_story, job_story, origin, dest, csv_data
        )
        
        logger.debug(f"Extracted plan: {plan}")
        return plan
    
    # ========================================================================
    # RULE-BASED EXTRACTION (Always Available)
    # ========================================================================
    
    def _extract_with_rules(
        self,
        user_story: Any,
        job_story: Any,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        csv_data: Optional[Dict]
    ) -> ExtractedPlan:
        """
        Rule-based plan extraction using keyword matching and heuristics.
        
        This is the fallback method that always works.
        """
        
        # Initialize plan
        plan = ExtractedPlan(
            plan_type='point_to_point',
            extraction_method='rule_based'
        )
        
        # Extract from job story (WHAT constraints)
        plan = self._extract_from_job_story(plan, job_story)
        
        # Extract from user story (WHO preferences)
        plan = self._extract_from_user_story(plan, user_story)
        
        # Apply CSV overrides (if provided)
        if csv_data:
            plan = self._apply_csv_data(plan, csv_data)
        
        # Generate reasoning
        plan.reasoning = self._generate_reasoning(plan, user_story, job_story)
        
        return plan
    
    def _extract_from_job_story(
        self, 
        plan: ExtractedPlan, 
        job_story: Any
    ) -> ExtractedPlan:
        """Extract constraints from job story (WHAT task)."""
        
        # ====================================================================
        # TEMPORAL CONSTRAINTS
        # ====================================================================
        
        if hasattr(job_story, 'time_window') and job_story.time_window:
            tw = job_story.time_window
            
            # Schedule fixed if flexibility is low
            plan.schedule_fixed = tw.flexibility in ['none', 'very_low', 'low']
            
            # Time window
            plan.time_window_start = tw.start
            plan.time_window_end = tw.end
            
            logger.debug(
                f"Time window: {tw.start}-{tw.end}, "
                f"fixed={plan.schedule_fixed} (flexibility={tw.flexibility})"
            )
        
        # Recurring pattern
        if hasattr(job_story, 'parameters') and job_story.parameters.get('recurring'):
            freq = job_story.parameters.get('frequency', '5/week')
            # Use job_id or job_type as fallback text — job_story has no .context attr
            job_text = (
                getattr(job_story, 'job_id', '')
                or getattr(job_story, 'story_id', '')
                or getattr(job_story, 'job_type', '')
            ).lower()

            if '5/week' in str(freq) or 'daily' in job_text:
                plan.recurring_pattern = 'daily'
                logger.debug("Recurring: daily (from parameters)")
            elif 'weekly' in str(freq):
                plan.recurring_pattern = 'weekly'

            logger.debug(f"Recurring: {plan.recurring_pattern}")
        
        # ====================================================================
        # MULTI-STOP DETECTION
        # ====================================================================
        
        if hasattr(job_story, 'delivery_params') and job_story.delivery_params:
            num_stops = job_story.delivery_params.get('num_stops', [1])
            if isinstance(num_stops, list):
                num_stops = num_stops[0]
            
            if num_stops > 1:
                plan.plan_type = 'multi_stop'
                logger.debug(f"Multi-stop trip: {num_stops} stops")
        
        # ====================================================================
        # OPTIMIZATION OBJECTIVE FROM JOB TYPE
        # ====================================================================
        
        job_type = getattr(job_story, 'job_type', 'general')
        
        if job_type in ['freight', 'delivery', 'gig_delivery']:
            # Freight: Cost optimization
            plan.primary_objective = 'minimize_cost'
        elif 'commute' in job_type:
            # Commute: Time optimization
            plan.primary_objective = 'minimize_time'
        
        # Urgency override
        if hasattr(job_story, 'parameters'):
            urgency = job_story.parameters.get('urgency', 'medium')

            if urgency == 'critical':
                # True emergency: lock objective so persona preferences cannot override
                plan.primary_objective = 'minimize_time'
                plan.reliability_critical = True
                plan.flexibility_allowed = False
            elif urgency == 'high':
                # High urgency (school run, tight delivery window): time priority but NOT
                # reliability_critical=True — that flag is for operational-critical freight
                # (ambulance, blue-light) which triggers the BDI hard EV block.
                # Passenger jobs with urgency='high' get strong time preference but can
                # still consider EV — the cost function handles the time weighting.
                plan.primary_objective = 'minimize_time'
                plan.time_sensitive = True  # weaker flag: influences cost weights only
        
        # ====================================================================
        # REGULATORY CONSTRAINTS FROM PLAN CONTEXT
        # ====================================================================
        
        if hasattr(job_story, 'plan_context') and job_story.plan_context:
            for context_hint in job_story.plan_context:
                hint_lower = context_hint.lower()
                
                # Detect regulatory constraints
                if any(word in hint_lower for word in ['compliance', 'regulation', 'mandate', 'policy']):
                    plan.must_comply_with.append(context_hint)
                    logger.debug(f"Regulatory constraint: {context_hint}")
                
                # Detect reliability requirements
                if any(word in hint_lower for word in ['critical', 'essential', 'must arrive']):
                    plan.reliability_critical = True
        
        # ====================================================================
        # DESIRE OVERRIDES (Emergency, etc.)
        # ====================================================================
        
        if hasattr(job_story, 'desire_overrides') and job_story.desire_overrides:
            # Emergency jobs override everything
            if job_story.desire_overrides.get('time', 0) > 0.9:
                plan.primary_objective = 'minimize_time'
                plan.reliability_critical = True
                plan.flexibility_allowed = False
                logger.debug("Emergency job detected: time-critical")
        
        return plan
    
    def _extract_from_user_story(
        self, 
        plan: ExtractedPlan, 
        user_story: Any
    ) -> ExtractedPlan:
        """Augment plan with user story preferences (WHO personality)."""
        
        narrative = getattr(user_story, 'narrative', '').lower()
        
        # ====================================================================
        # PRIMARY OBJECTIVE FROM NARRATIVE
        # ====================================================================
        
        # Carbon-conscious users (override job default)
        if any(word in narrative for word in ['carbon', 'emission', 'environment', 'eco', 'climate', 'decarboni']):
            # Only block eco override for a true emergency
            # (flexibility_allowed is False only for urgency='critical' or desire_overrides.time > 0.9)
            if plan.flexibility_allowed:
                eco_desire   = getattr(user_story, 'desires', {}).get('eco',  0.0)
                cost_desire  = getattr(user_story, 'desires', {}).get('cost', 0.0)
                persona_type = getattr(user_story, 'persona_type', 'passenger')
                # Freight personas: eco keyword may appear in business context ("decarbonisation
                # strategy") — only let eco win if the persona's eco desire clearly exceeds
                # their cost desire
                if persona_type == 'freight' and cost_desire >= eco_desire:
                    pass  # cost mandate takes precedence
                else:
                    plan.primary_objective = 'minimize_carbon'
                    logger.debug("Eco-conscious user: minimize_carbon")
        
        # Budget-conscious users
        if any(word in narrative for word in ['budget', 'afford', 'cheap', 'cost', 'money']):
            if plan.primary_objective not in ['minimize_time', 'minimize_carbon']:
                plan.primary_objective = 'minimize_cost'
                logger.debug("Budget-conscious user: minimize_cost")
        
        # ====================================================================
        # RELIABILITY REQUIREMENTS
        # ====================================================================
        
        # Safety-conscious users (children, elderly, disabled)
        # Phase 10c fix: narrative safety keywords indicate a PREFERENCE, not a hard
        # operational constraint. reliability_critical=True is reserved for freight/
        # blue-light agents where the BDI hard EV block must fire. Passenger agents
        # with safety concerns get maximize_safety as a secondary objective and
        # weather_sensitive=True, which influences cost weighting without blocking EV.
        if any(word in narrative for word in ['safety', 'safe', 'children', 'child', 'kids', 'elderly', 'disabled']):
            plan.weather_sensitive = True
            plan.time_sensitive = True   # prefer reliable services without hard block
            if 'safety' not in [obj.lower() for obj in plan.secondary_objectives]:
                plan.secondary_objectives.append('maximize_safety')
            logger.debug("Safety-conscious user: maximize_safety preference set")
        
        # ====================================================================
        # WEATHER SENSITIVITY
        # ====================================================================
        
        # Parents with children
        if 'parent' in narrative or 'children' in narrative:
            plan.weather_sensitive = True
        
        # Disability/accessibility needs
        if any(word in narrative for word in ['wheelchair', 'mobility', 'disabled', 'accessibility']):
            plan.reliability_critical = True
            plan.secondary_objectives.append('require_accessibility')
        
        # ====================================================================
        # COMFORT PREFERENCES
        # ====================================================================
        
        if 'comfort' in narrative:
            plan.secondary_objectives.append('maximize_comfort')
        
        # ====================================================================
        # BELIEFS INFLUENCE CONSTRAINTS
        # ====================================================================
        
        if hasattr(user_story, 'beliefs'):
            for belief in user_story.beliefs[:3]:  # Top 3 beliefs
                belief_text = belief.text.lower()
                
                # Strong beliefs about public transport
                if 'public transport' in belief_text and belief.strength > 0.7:
                    if 'unreliable' in belief_text:
                        # Don't rely on public transport
                        pass  # Mode filtering will handle this
                    elif 'green' in belief_text or 'emission' in belief_text:
                        # Prefer public transport
                        if plan.primary_objective not in ['minimize_time']:
                            plan.primary_objective = 'minimize_carbon'
        
        # ── Phase 10c: ASI tier + ev_viability_belief_hint ─────────────
        persona_type = getattr(user_story, 'persona_type', 'passenger')
        if plan.reliability_critical and persona_type == 'freight':
            plan.asi_tier = 'improve'
            plan.ev_viability_belief_hint = 0.85   # blue-light: near-universal proof required
        elif plan.primary_objective == 'minimize_carbon':
            plan.asi_tier = 'shift'
            plan.ev_viability_belief_hint = 0.35   # eco: early adopter, low barrier
        elif persona_type == 'freight' and not plan.schedule_fixed:
            plan.asi_tier = 'avoid'
            plan.ev_viability_belief_hint = 0.65   # flexible freight: try consolidation first
        elif persona_type == 'freight':
            plan.asi_tier = 'shift'
            plan.ev_viability_belief_hint = 0.70   # fixed freight: shift but high bar
        else:
            plan.asi_tier = 'improve'
            plan.ev_viability_belief_hint = 0.50

        logger.debug(
            "ASI tier: %s | ev_hint=%.2f | persona=%s | objective=%s",
            plan.asi_tier, plan.ev_viability_belief_hint, persona_type, plan.primary_objective,
        )

        return plan

    def _apply_csv_data(
        self, 
        plan: ExtractedPlan, 
        csv_data: Dict
    ) -> ExtractedPlan:
        """Apply CSV overrides (waypoints, explicit constraints)."""
        
        # Explicit waypoints from CSV
        if 'waypoint_1_lat' in csv_data and 'waypoint_1_lon' in csv_data:
            waypoint = (
                float(csv_data['waypoint_1_lon']),
                float(csv_data['waypoint_1_lat'])
            )
            plan.waypoints.append(waypoint)
            plan.plan_type = 'multi_stop'
            logger.debug(f"CSV waypoint: {waypoint}")
        
        # Explicit time window override
        if 'preferred_arrival' in csv_data:
            plan.time_window_end = csv_data['preferred_arrival']
        
        # Explicit constraints
        if 'avoid_area' in csv_data:
            plan.avoid_areas.append(csv_data['avoid_area'])
        
        return plan
    
    def _generate_reasoning(
        self, 
        plan: ExtractedPlan, 
        user_story: Any, 
        job_story: Any
    ) -> str:
        """Generate human-readable explanation of plan (XAI)."""
        
        reasoning_parts = []
        
        # Objective reasoning
        if plan.primary_objective == 'minimize_carbon':
            reasoning_parts.append(
                f"Minimizing carbon emissions because user is eco-conscious "
                f"({user_story.story_id})"
            )
        elif plan.primary_objective == 'minimize_time':
            # Safely extract urgency from parameters dict
            params = getattr(job_story, 'parameters', {})
            urgency = params.get('urgency', 'medium') if isinstance(params, dict) else 'medium'
            reasoning_parts.append(
                f"Minimizing time because task is time-critical "
                f"({getattr(job_story, 'job_type', 'unknown')}, urgency={urgency})"
            )
        elif plan.primary_objective == 'minimize_cost':
            reasoning_parts.append(
                f"Minimizing cost because user is budget-conscious or task is freight"
            )
        
        # Schedule reasoning
        if plan.schedule_fixed:
            reasoning_parts.append(
                f"Fixed schedule because time window flexibility is low "
                f"({plan.time_window_start}-{plan.time_window_end})"
            )
        
        # Reliability reasoning
        if plan.reliability_critical:
            reasoning_parts.append(
                "Reliability critical because of safety concerns or urgency"
            )
        
        # Compliance reasoning
        if plan.must_comply_with:
            reasoning_parts.append(
                f"Must comply with: {', '.join(plan.must_comply_with[:2])}"
            )
        
        return "; ".join(reasoning_parts)
    

    # ========================================================================
    # MODE FILTERING — The BDI Integration Bridge
    # ========================================================================

    def get_candidate_modes(
        self,
        plan: "ExtractedPlan",
        available_modes: list,
        distance_km: float = 5.0,
        weather_conditions: dict = None,
    ) -> list:
        """
        Translate an ExtractedPlan into a filtered list of candidate modes.

        This is the integration bridge between contextual plan extraction and
        the BDI planner. The planner passes its full available_modes list; this
        method returns the contextually appropriate subset. The BDI planner then
        scores within that subset using desire weights, preserving individuality.

        Filtering logic (applied in order):
          1. Objective filter  — remove modes contradicting primary_objective
          2. Reliability filter — remove fragile modes when reliability_critical
          3. Compliance filter  — remove non-compliant modes (e.g. diesel in LEZ)
          4. Weather filter     — remove unsafe active modes in bad weather
          5. Distance guardrail — remove modes clearly outside their range
          6. Fallback           — always keep ≥1 mode to prevent empty returns

        Args:
            plan:              ExtractedPlan from extract_plan_from_context()
            available_modes:   Modes offered by _filter_modes_by_context()
            distance_km:       Straight-line trip distance
            weather_conditions: Optional dict with 'ice_warning', 'precipitation'

        Returns:
            Filtered list of mode strings, length >= 1.
        """
        weather = weather_conditions or {}
        modes   = list(available_modes)   # work on a copy

        # ── 1. Objective filter ──────────────────────────────────────────────
        if plan.primary_objective == 'minimize_carbon':
            # Prefer zero/low emission modes; remove high-emission diesel freight
            # unless no alternatives exist (freight agents may have no choice).
            _HIGH_EMISSION = {
                'car', 'van_diesel', 'truck_diesel',
                'hgv_diesel', 'hgv_hydrogen',   # hydrogen still combustion
            }
            filtered = [m for m in modes if m not in _HIGH_EMISSION]
            if filtered:
                modes = filtered
                logger.debug("Objective filter (carbon): removed high-emission modes")

        elif plan.primary_objective == 'minimize_cost':
            # Keep cheapest modes; remove aviation and long-distance rail
            _EXPENSIVE = {'flight_domestic', 'flight_electric', 'intercity_train'}
            filtered = [m for m in modes if m not in _EXPENSIVE]
            if filtered:
                modes = filtered
                logger.debug("Objective filter (cost): removed expensive modes")

        elif plan.primary_objective == 'minimize_time':
            # Remove very slow modes for time-critical trips > 3km
            if distance_km > 3.0:
                _SLOW = {'walk'}
                filtered = [m for m in modes if m not in _SLOW]
                if filtered:
                    modes = filtered
                    logger.debug("Objective filter (time): removed walk for long trip")

        # ── 2. Reliability filter ────────────────────────────────────────────
        if plan.reliability_critical and distance_km > 2.0:
            # Remove modes that are unreliable or unsafe when reliability matters
            # (children present, disability, time-critical delivery).
            # Keep bikes for short trips (<2km) as they are reliable there.
            _UNRELIABLE = {'e_scooter', 'cargo_bike'}
            if weather.get('ice_warning') or weather.get('precipitation', 0) > 5:
                _UNRELIABLE |= {'bike', 'walk'}   # active modes unsafe in ice/heavy rain
            filtered = [m for m in modes if m not in _UNRELIABLE]
            if filtered:
                modes = filtered
                logger.debug("Reliability filter: removed fragile modes")

        # ── 3. Compliance filter ─────────────────────────────────────────────
        if plan.must_comply_with:
            compliance_text = ' '.join(plan.must_comply_with).lower()
            if any(w in compliance_text for w in ['emission zone', 'lez', 'ulez', 'zero emission']):
                _NON_COMPLIANT = {
                    'car', 'van_diesel', 'truck_diesel',
                    'hgv_diesel', 'hgv_hydrogen',
                }
                filtered = [m for m in modes if m not in _NON_COMPLIANT]
                if filtered:
                    modes = filtered
                    logger.debug("Compliance filter (LEZ): removed diesel/petrol modes")

        # ── 4. Weather filter ────────────────────────────────────────────────
        if plan.weather_sensitive:
            if weather.get('ice_warning'):
                _ICY = {'bike', 'e_scooter', 'cargo_bike', 'walk'}
                filtered = [m for m in modes if m not in _ICY]
                if filtered:
                    modes = filtered
                    logger.debug("Weather filter (ice): removed active modes")

        # ── 5. Distance guardrail ────────────────────────────────────────────
        # Remove modes clearly outside their practical range.
        _MODE_MAX_KM = {
            'walk': 5.0, 'bike': 20.0, 'cargo_bike': 12.0, 'e_scooter': 10.0,
        }
        if distance_km > 2.0:   # only apply for non-trivial distances
            filtered = [
                m for m in modes
                if distance_km <= _MODE_MAX_KM.get(m, 9999)
            ]
            if filtered:
                modes = filtered

        # ── 6. Fallback guarantee ────────────────────────────────────────────
        if not modes:
            logger.warning(
                "get_candidate_modes: all modes filtered out — reverting to available_modes. "
                "Plan: %s | Distance: %.1fkm", plan, distance_km
            )
            return list(available_modes)

        logger.debug(
            "get_candidate_modes: %d → %d modes (objective=%s, critical=%s)",
            len(available_modes), len(modes),
            plan.primary_objective, plan.reliability_critical
        )
        return modes

    # ========================================================================
    # LLM-BASED EXTRACTION (Optional Enhancement)
    # ========================================================================
    
    def _extract_with_llm(
        self,
        user_story: Any,
        job_story: Any,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        csv_data: Optional[Dict],
    ) -> ExtractedPlan:
        """
        Extract plan using LLMClient (OLMo 2 primary, Anthropic fallback).
 
        The prompt requests JSON for speed and reliability.
        Parsing failures raise ValueError so extract_plan_from_context()
        can catch and fall back to rule-based extraction cleanly.
        """
        if not self.llm:
            raise RuntimeError("LLM client not initialized")
 
        prompt = self._construct_llm_prompt(user_story, job_story)
        response = self.llm.complete(prompt, temperature=0.1)
 
        plan_data = self._parse_llm_response(response)
        plan = self._llm_data_to_plan(plan_data)
 
        # Merge temporal constraints from job story (rule-based is more
        # reliable for structured fields than LLM inference)
        if hasattr(job_story, "time_window") and job_story.time_window:
            plan.time_window_start = job_story.time_window.start
            plan.time_window_end = job_story.time_window.end
 
        plan.extraction_method = "llm"
        plan.reasoning = plan_data.get("reasoning", "LLM extraction")
 
        logger.info(
            "LLM plan extraction: objective=%s, fixed=%s, critical=%s — %s",
            plan.primary_objective,
            plan.schedule_fixed,
            plan.reliability_critical,
            plan.reasoning,
        )
        return plan
    
    def _construct_llm_prompt(self, user_story: Any, job_story: Any) -> str:
        """Construct prompt for LLM extraction."""
        
        # Get top beliefs
        beliefs_text = ""
        if hasattr(user_story, 'beliefs') and user_story.beliefs:
            beliefs_text = "\n".join(
                f"- {b.text}" for b in user_story.beliefs[:3]
            )
        
        # Get plan context
        plan_context_text = ""
        if hasattr(job_story, 'plan_context') and job_story.plan_context:
            plan_context_text = "\n".join(
                f"- {c}" for c in job_story.plan_context[:5]
            )
        
        prompt = f"""Extract the travel plan from this user story and job context.

                    USER STORY:
                    {user_story.narrative}

                    Key beliefs:
                    {beliefs_text}

                    JOB CONTEXT:
                    {job_story.context}
                    {job_story.goal}
                    {job_story.outcome}

                    Plan context:
                    {plan_context_text}

                    Based on this context, extract:
                    1. Is this a scheduled trip with fixed times? (yes/no)
                    2. What is the primary optimization objective? (minimize_time/minimize_carbon/minimize_cost)
                    3. Is reliability critical? (yes/no)
                    4. Are there regulatory constraints? (list any)
                    5. Is weather a concern? (yes/no)

                    Respond in JSON format:
                    {{
                        "schedule_fixed": true/false,
                        "primary_objective": "minimize_time",
                        "reliability_critical": true/false,
                        "regulatory_constraints": ["list", "of", "constraints"],
                        "weather_sensitive": true/false,
                        "reasoning": "brief explanation"
                    }}"""
        
        # Append JSON schema reminder — OLMo needs explicit format instruction
        prompt += """
 
                    Respond ONLY with a JSON object — no markdown, no explanation:
                    {
                    \"schedule_fixed\": true or false,
                    \"primary_objective\": \"minimize_time\" or \"minimize_carbon\" or \"minimize_cost\",
                    \"reliability_critical\": true or false,
                    \"weather_sensitive\": true or false,
                    \"regulatory_constraints\": [],
                    \"reasoning\": \"one sentence\"
                    }"""
        
        return prompt
    
    def _parse_llm_response(self, response: str) -> Dict:
        """Parse LLM response into dict."""
        
        # Try direct JSON parse
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass
        
        # Try to extract JSON from markdown
        json_match = re.search(r'```json\n(.*?)\n```', response, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))
        
        # Try without code fences
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
        
        raise ValueError(f"Could not parse LLM response as JSON: {response[:100]}")
    
    def _llm_data_to_plan(self, plan_data: Dict) -> ExtractedPlan:
        """Convert LLM response dict to ExtractedPlan."""
        
        plan = ExtractedPlan(
            plan_type='point_to_point',
            schedule_fixed=plan_data.get('schedule_fixed', False),
            primary_objective=plan_data.get('primary_objective', 'minimize_time'),
            reliability_critical=plan_data.get('reliability_critical', False),
            weather_sensitive=plan_data.get('weather_sensitive', False),
            must_comply_with=plan_data.get('regulatory_constraints', [])
        )
        
        return plan