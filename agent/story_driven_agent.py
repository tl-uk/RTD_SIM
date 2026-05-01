"""
agent/story_driven_agent.py

This module implements the StoryDrivenAgent class, which creates agents based on user stories 
and job stories. It extracts relevant context from the stories to inform the agent's beliefs, 
desires, and intentions (BDI). The agent can also perceive events such as policy changes 
and infrastructure failures, allowing for dynamic replanning. Additionally, there are batch 
generation functions to create multiple agents from combinations of user and job stories, 
with options for balanced generation across story combinations.

NOTE: May not handle simple parameters and vehicle_constraints structure perfectly yet - 
we can adjust as we see what stories are generated and how they behave in the simulation.
"""

from __future__ import annotations
from typing import Dict, Any, Tuple, Optional, List
from pathlib import Path
import random
import logging

from agent.cognitive_abm import CognitiveAgent
from agent.user_stories import UserStoryParser, UserStory
from agent.job_stories import JobStoryParser, JobStory

logger = logging.getLogger(__name__)
 
# PersonaFusion — synthesises FusedIdentity from user+job story
try:
    from agent.persona_fusion import PersonaFusion, FusedIdentity
    _FUSION_AVAILABLE = True
    _FUSION = PersonaFusion()
except ImportError:
    _FUSION_AVAILABLE = False
    FusedIdentity = None
    logger.warning("PersonaFusion not available — fused identity disabled")


class StoryDrivenAgent(CognitiveAgent):
    """
    Agent created from user + job stories.
    
    Combines:
    - User story (WHO): personality, beliefs, desires
    - Job story (WHAT): task, constraints, context
    
    Result: Fully parameterized BDI agent with realistic behavior.
    """
    
    def __init__(
        self,
        user_story_id: str,
        job_story_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        agent_id: Optional[str] = None,
        planner = None,
        seed: Optional[int] = None,
        user_stories_path: Optional[Path] = None,
        job_stories_path: Optional[Path] = None,
        csv_data: Optional[Dict[str, Any]] = None,
        conflict_resolution: str = 'dynamic',
        apply_variance: bool = True
    ):
        """Initialize story-driven agent."""
        # Store story IDs for reference
        self.user_story_id = user_story_id
        self.job_story_id = job_story_id
        self.conflict_resolution = conflict_resolution
        
        # Parse stories
        user_parser = UserStoryParser(user_stories_path)
        job_parser = JobStoryParser(job_stories_path)
        
        self.user_story = user_parser.load_from_yaml(user_story_id)
        self.job_story = job_parser.load_from_yaml(job_story_id)
        self.csv_data = csv_data  # <- persist for _extract_agent_context()
        
        # Generate task context FIRST (needed for agent_context extraction)
        self.task_context = self.job_story.to_task_context(origin, dest, csv_data)
        
        # NOW extract agent_context (uses self.task_context and self.job_story)
        agent_context = self._extract_agent_context()

        # ── Fused Identity ─────────────────────────────────────────────────
        # Compute the combined persona-profession profile from both story
        # sources.  The result is stored in agent_context so BDIPlanner can
        # read it through the context dict it already receives in actions_for()
        # and _filter_modes_by_context() — no constructor signature changes.
        #
        # FusedIdentity provides:
        #   .allowed_modes          → hard mode constraint (replaces vehicle_type
        #                             branching for all abstract rail/ferry/air jobs)
        #   .abstract_modes         → modes that need synthetic routing
        #   .beliefs                → calibrated BDI priors
        #   .desires                → merged desire weights
        #   .asi_tier               → 'avoid'|'shift'|'improve'
        #   .ev_viability_threshold → Complex Contagion gate
        if _FUSION_AVAILABLE:
            self.fused_identity = _FUSION.fuse(self.user_story, self.job_story)
            agent_context['fused_identity']          = self.fused_identity
            agent_context['fused_beliefs']           = self.fused_identity.beliefs
            # Seed the ASI and EV keys already read by existing bdi_planner logic
            # (lines ~404-405 of actions_for).  FusedIdentity values override the
            # CPG defaults; CPG values from _extracted_plan will refine further.
            agent_context.setdefault('asi_tier_hint', self.fused_identity.asi_tier)
            agent_context.setdefault(
                'ev_viability_threshold',
                self.fused_identity.ev_viability_threshold,
            )
            logger.debug(
                "FusedIdentity: %s → asi=%s ev_thr=%.2f modes=%s",
                self.fused_identity.agent_label,
                self.fused_identity.asi_tier,
                self.fused_identity.ev_viability_threshold,
                self.fused_identity.allowed_modes,
            )
        else:
            self.fused_identity = None

        # Resolve desires (combine user + job)
        desires = self._resolve_desires()
        
        # Apply stochastic variance
        if apply_variance:
            desires = self._apply_variance(desires, seed)
        
        # Generate agent ID if not provided
        if agent_id is None:
            agent_id = f"{user_story_id}_{job_story_id}_{random.randint(1000, 9999)}"
        
        # Initialize parent CognitiveAgent
        super().__init__(
            seed=seed,
            agent_id=agent_id,
            agent_context=agent_context,
            desires=desires,
            planner=planner,
            origin=origin,
            dest=dest
        )
        
        # DEBUG: Log context immediately after creation
        logger.info(f"Created {agent_id}: job={job_story_id}, "
                   f"vehicle_required={agent_context.get('vehicle_required')}, "
                   f"vehicle_type={agent_context.get('vehicle_type')}")
        
        # Phase 3: Markov mode switching — personality-driven habit formation
        try:
            from agent.markov_mode_switching import PersonalityMarkovChain
            self.mode_chain = PersonalityMarkovChain( 
                persona_id=user_story_id,
                available_modes=None,  # uses ALL_MODES; planner filters at runtime
                seed=seed,Z
            )
        except Exception as _e:
            self.mode_chain = None
            logger.debug("MarkovModeSwitching not available: %s", _e)

        # Expose mode_chain via agent_context so bdi_planner.cost() can read
        # get_prior() without holding a reference to the agent object.
        # The dict is already held by the parent CognitiveAgent; mutating it
        # here keeps both self.agent_context and the planner's copy in sync.
        self.agent_context['mode_chain'] = self.mode_chain   # ← NEW
        # Logic (hack):
        #   cost() receives agent_context (a dict), not the agent.
        #   Adding mode_chain to the dict is the smallest possible change —
        #   one line, no new parameters, no API breakage.
        #   If mode_chain is None (import failed), cost() handles it gracefully.

        # Event perception (optional - Phase 7)
        self.perceived_policies = {}  # {parameter: value}
        self.perceived_failures = []  # List of infrastructure failures
        self.event_perception_enabled = False
    
    def _extract_agent_context(self) -> Dict:
        """
        Extract infrastructure-relevant context from stories.
        
        Checks both parameters and vehicle_constraints sections.
        """
        context = {} # Start with empty context
        
        # === STEP 1: Extract from parameters (simple format) ===
        params = self.task_context.parameters
        
        context['vehicle_required'] = params.get('vehicle_required', False)
        context['cargo_capacity'] = params.get('cargo_capacity', False)
        context['recurring'] = params.get('recurring', False)
        context['luggage_present'] = params.get('luggage_present', False)
        
        # === STEP 2: Extract vehicle_type from parameters OR vehicle_constraints ===
        # First try parameters (simple format)
        vehicle_type_param = params.get('vehicle_type', None)
        
        if vehicle_type_param:
            # Map to standard types
            if vehicle_type_param in ['micro_mobility']:
                context['vehicle_type'] = 'micro_mobility'
            elif vehicle_type_param in ['commercial', 'light_freight']:
                context['vehicle_type'] = 'commercial'
            elif vehicle_type_param in ['medium_freight']:
                context['vehicle_type'] = 'medium_freight'
            elif vehicle_type_param in ['heavy_freight']:
                context['vehicle_type'] = 'heavy_freight'
            elif vehicle_type_param in ['transit']:
                context['vehicle_type'] = 'transit'
            else:
                context['vehicle_type'] = 'personal'
        
        # If not in parameters, try vehicle_constraints (detailed format)
        elif self.job_story.vehicle_constraints:
            vc_type = self.job_story.vehicle_constraints.get('type', 'personal')

            # Map constraint types to vehicle_type
            if vc_type in ['micro_mobility']:
                context['vehicle_type'] = 'micro_mobility'
            elif vc_type in ['light_freight', 'freight']:
                context['vehicle_type'] = 'commercial'
            elif vc_type in ['medium_freight']:
                context['vehicle_type'] = 'medium_freight'
            elif vc_type in ['heavy_freight']:
                context['vehicle_type'] = 'heavy_freight'
            elif vc_type in ['transit']:
                context['vehicle_type'] = 'transit'
            else:
                context['vehicle_type'] = 'personal'
        else:
            context['vehicle_type'] = 'personal'
        
        # === STEP 3: Determine priority ===
        urgency = params.get('urgency', 'medium')

        if self.job_story.desire_overrides:
            # Emergency jobs (desire_overrides present)
            context['priority'] = 'emergency'
        elif self.job_story.job_type in [
            'delivery', 'freight', 'gig_delivery',
            # Phase 10 job types — previously fell through to 'normal'
            'rail_freight',         # rail_operations.yaml
            'multimodal_freight',   # heavy_freight.yaml (ferry_freight_roro etc.)
            'business_travel',      # multimodal.yaml, aviation.yaml
            'service',              # light_commercial.yaml (service_engineer, trades)
                                    # fleet_operators.yaml (nhs_patient_transport)
            'air_freight',          # aviation.yaml (air_cargo_express)
            'taxi_service',         # taxi_operations.yaml
        ]:
            # Commercial / professional jobs — always commercial priority
            context['priority'] = 'commercial'
        elif urgency == 'critical':
            # Critical urgency always escalates to emergency regardless of job type
            context['priority'] = 'emergency'
        elif urgency == 'high' and context.get('vehicle_type', 'personal') not in ('personal', 'transit'):
            # High urgency only escalates to commercial for non-passenger vehicle types.
            # Passenger commutes (morning_commute urgency=high) must remain 'normal'
            # so that bdi_planner._filter_modes_by_context does not restrict them
            # to freight/commercial vehicles.
            context['priority'] = 'commercial'
        else:
            context['priority'] = 'normal'
        
        # === STEP 4: Log for debugging ===
        logger.debug(f"Extracted context for {self.job_story_id}: "
                    f"vehicle_required={context['vehicle_required']}, "
                    f"vehicle_type={context['vehicle_type']}, "
                    f"priority={context['priority']}")
        
        # Attach story objects so BDI planner can pass them to
        # ContextualPlanGenerator without re-parsing YAML.
        context["user_story"] = self.user_story
        context["job_story"]  = self.job_story
        context["csv_data"]   = getattr(self, "csv_data", None)

        return context
    
    # Conflict resolution between user desires and job context
    def _resolve_desires(self) -> Dict[str, float]:
        """Resolve desires from user story + job story."""
        # Get base desires from user story
        user_desires = self.user_story.to_bdi_desires()
        
        # Check if job story has desire overrides (e.g., emergency)
        if self.job_story.desire_overrides:
            desires = user_desires.copy()
            for key, value in self.job_story.desire_overrides.items():
                desires[key] = value
            logger.debug(f"Applied job story overrides: {self.job_story.desire_overrides}")
            return desires
        
        # Apply conflict resolution strategy
        if self.conflict_resolution == 'user_priority':
            return user_desires
        elif self.conflict_resolution == 'job_priority':
            return self._apply_job_context_weights(user_desires)
        elif self.conflict_resolution == 'dynamic':
            return self._dynamic_weighting(user_desires)
        else:
            logger.warning(f"Unknown conflict resolution: {self.conflict_resolution}")
            return user_desires
    
    def _apply_job_context_weights(self, desires: Dict[str, float]) -> Dict[str, float]:
        """Modify desires based on job context."""
        modified = desires.copy()
        
        # Urgency affects time desire
        urgency = self.job_story.parameters.get('urgency', 'medium')
        if urgency == 'critical':
            modified['time'] = min(1.0, modified.get('time', 0.5) + 0.3)
        elif urgency == 'high':
            modified['time'] = min(1.0, modified.get('time', 0.5) + 0.2)
        
        # Recurring trips increase reliability desire
        if self.job_story.parameters.get('recurring'):
            modified['reliability'] = min(1.0, modified.get('reliability', 0.5) + 0.2)
        
        # Time window flexibility
        if self.job_story.time_window:
            if self.job_story.time_window.flexibility in ['none', 'very_low']:
                modified['time'] = min(1.0, modified.get('time', 0.5) + 0.2)
        
        return modified
    
    def _dynamic_weighting(self, desires: Dict[str, float]) -> Dict[str, float]:
        """Dynamic weighting: blend user + job based on importance."""
        modified = self._apply_job_context_weights(desires)
        
        # Blend with original
        blended = {}
        for key in desires:
            user_val = desires.get(key, 0.5)
            job_val = modified.get(key, 0.5)
            # 70% user, 30% job
            blended[key] = 0.7 * user_val + 0.3 * job_val
        
        return blended
 
    def _apply_variance(
        self, 
        desires: Dict[str, float], 
        seed: Optional[int]
    ) -> Dict[str, float]:
        """Apply stochastic variance to desires."""
        variance = self.user_story.desire_variance
        rng = random.Random(seed)
        
        varied = {}
        for key, value in desires.items():
            # Apply ±variance% noise
            noise = rng.uniform(-variance, variance)
            varied[key] = max(0.0, min(1.0, value + noise))
        
        return varied
    
    def get_story_context(self) -> Dict[str, Any]:
        """Get full story context for this agent."""
        return {
            'user_story_id': self.user_story_id,
            'job_story_id': self.job_story_id,
            'persona_type': self.user_story.persona_type,
            'job_type': self.job_story.job_type,
            'desires': self.desires,
            'beliefs': [b.text for b in self.user_story.beliefs],
            'constraints': self.user_story.constraints + self.task_context.constraints,
            'conflict_resolution': self.conflict_resolution,
        }
    
    def explain_decision(self, action: str) -> str:
        """Explain why agent chose this action (for explainability)."""
        context = self.get_story_context()
        
        explanation = (
            f"As a {self.user_story_id} performing {self.job_story_id}, "
            f"I chose {action} because:\n"
        )
        
        # Top 3 desires
        top_desires = sorted(self.desires.items(), key=lambda x: x[1], reverse=True)[:3]
        explanation += f"- My priorities are: {', '.join(f'{k}={v:.2f}' for k, v in top_desires)}\n"
        
        # Relevant beliefs
        if self.user_story.beliefs:
            explanation += f"- I believe: {self.user_story.beliefs[0].text}\n"
        
        # Constraints
        if context['constraints']:
            explanation += f"- I must respect: {', '.join(context['constraints'][:2])}\n"
        
        return explanation
    
    def __repr__(self) -> str:
        return (f"StoryDrivenAgent(id={self.state.agent_id}, "
                f"user={self.user_story_id}, job={self.job_story_id})")
    
    # ===============================================================================
    # Event Perception (Optional but necessary when we want dynamic replanning based 
    # on events tying in with the story context - e.g., if a policy change affects a constraint in the job story,
    # the agent can perceive this and replan accordingly).
    # Needed for Phase 7, but we can implement the subscription and perception logic 
    # here in Phase 6.2b.
    # ===============================================================================
    def subscribe_to_events(self, event_bus):
        """
        Subscribe agent to relevant events (OPTIONAL).
        
        This method enables dynamic event perception for replanning.
        Without calling this, agent works normally.
        
        Args:
            event_bus: SafeEventBus instance
        """
        if not event_bus or not event_bus.is_available():
            logger.debug(f"{self.state.agent_id}: Event bus unavailable")
            return
        
        from events.event_types import EventType
        
        # Subscribe to policy changes
        def handle_policy_change(event):
            param = event.payload['parameter']
            new_value = event.payload['new_value']
            old_value = event.payload['old_value']
            
            # Store in beliefs
            self.perceived_policies[param] = new_value
            
            logger.debug(
                f"{self.state.agent_id} perceived policy: {param} "
                f"{old_value} → {new_value}"
            )
            
            # TODO Phase 7: Trigger replanning if needed
            # if self._policy_affects_plan(param):
            #     self.trigger_replan()
        
        # Subscribe to infrastructure failures
        def handle_infrastructure_failure(event):
            infra_type = event.payload['infrastructure_type']
            infra_id = event.payload['infrastructure_id']
            
            failure_info = {
                'type': infra_type,
                'id': infra_id,
                'reason': event.payload['failure_reason'],
                'timestamp': event.timestamp,
                'location': (event.spatial.latitude, event.spatial.longitude)
            }
            self.perceived_failures.append(failure_info)
            
            logger.debug(f"{self.state.agent_id} perceived failure: {infra_id}")
            
            # TODO Phase 7: Trigger replanning if on route
        
        try:
            # Subscribe with spatial filtering
            event_bus.subscribe_spatial(
                self.state.agent_id,
                EventType.POLICY_CHANGE,
                handle_policy_change
            )
            
            event_bus.subscribe_spatial(
                self.state.agent_id,
                EventType.INFRASTRUCTURE_FAILURE,
                handle_infrastructure_failure
            )
            
            self.event_perception_enabled = True
            logger.debug(f"✅ {self.state.agent_id}: Event perception enabled")
            
        except Exception as e:
            logger.debug(f"Event subscription failed: {e}")

    # Getters for perceived events (for testing and diagnostics)
    def get_perceived_policies(self):
        """Get all policies this agent has perceived."""
        return self.perceived_policies.copy()
    
    def get_perceived_failures(self):
        """Get all failures this agent has perceived."""
        return self.perceived_failures.copy()
    
# ============================================================================
# Batch Generation Functions
# ============================================================================

def generate_agents_from_stories(
    user_story_ids: List[str],
    job_story_ids: List[str],
    origin_dest_pairs: List[Tuple[Tuple[float, float], Tuple[float, float]]],
    planner = None,
    seed: Optional[int] = None,
    user_stories_path: Optional[Path] = None,
    job_stories_path: Optional[Path] = None
) -> List[StoryDrivenAgent]:
    """Generate multiple agents from story combinations."""
    from agent.story_compatibility import filter_compatible_combinations
    
    agents = []
    rng = random.Random(seed)
    
    # Filter to only compatible combinations
    compatible_combos = filter_compatible_combinations(user_story_ids, job_story_ids)
    
    if not compatible_combos:
        logger.warning("⚠️ No compatible combinations found! Using all combinations (may create nonsensical agents)")
        compatible_combos = [(u, j) for u in user_story_ids for j in job_story_ids]
    else:
        logger.info(f"✅ Using {len(compatible_combos)} compatible story combinations (filtered from {len(user_story_ids) * len(job_story_ids)} total)")
    
    for i, (origin, dest) in enumerate(origin_dest_pairs):
        # Pick random COMPATIBLE user + job story
        user_story, job_story = rng.choice(compatible_combos)
        
        agent = StoryDrivenAgent(
            user_story_id=user_story,
            job_story_id=job_story,
            origin=origin,
            dest=dest,
            planner=planner,
            seed=seed + i if seed else None,
            user_stories_path=user_stories_path,
            job_stories_path=job_stories_path
        )
        agents.append(agent)
    
    logger.info(f"Generated {len(agents)} agents from compatible stories")
    return agents

# =============================================================================
# Balanced Generation Function
# 
# This function generates a balanced population of agents with even distribution across 
# story combinations, which is useful for controlled experiments and diagnostics.
# =============================================================================
def generate_balanced_population(
    num_agents: int,
    user_story_ids: List[str],
    job_story_ids: List[str],
    origin_dest_generator,
    planner = None,
    seed: Optional[int] = None,
    user_stories_path: Optional[Path] = None,
    job_stories_path: Optional[Path] = None
) -> List[StoryDrivenAgent]:
    """Generate balanced population with even story distribution."""
    from agent.story_compatibility import filter_compatible_combinations
    
    agents = []
    rng = random.Random(seed)
    
    # Filter to only compatible combinations
    compatible_combos = filter_compatible_combinations(user_story_ids, job_story_ids)
    
    if not compatible_combos:
        logger.warning("⚠️ No compatible combinations found! Using all combinations")
        compatible_combos = [(u, j) for u in user_story_ids for j in job_story_ids]
    
    # Calculate agents per combination
    agents_per_combo = max(1, num_agents // len(compatible_combos))
    
    logger.info(f"✅ Generating {agents_per_combo} agents per combination ({len(compatible_combos)} compatible combinations)")
    
    for user_story, job_story in compatible_combos:
        for i in range(agents_per_combo):
            origin, dest = origin_dest_generator()
            
            agent = StoryDrivenAgent(
                user_story_id=user_story,
                job_story_id=job_story,
                origin=origin,
                dest=dest,
                planner=planner,
                seed=seed + len(agents) if seed else None,
                user_stories_path=user_stories_path,
                job_stories_path=job_stories_path
            )
            agents.append(agent)
            
            if len(agents) >= num_agents:
                break
        if len(agents) >= num_agents:
            break
    
    logger.info(f"Generated {len(agents)} balanced agents")
    return agents