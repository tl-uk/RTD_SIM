# RTD_SIM Core Innovation Implementation Roadmap

**Project**: User Story-Driven BDI Agent Generation with Dynamic Plan Extraction  
**Status**: Infrastructure 100% Complete | Core Innovation Phase 1 COMPLETE ✅  
**Goal**: Implement context-aware plan extraction from user stories to enable emergent behavior  
**Updated**: 2026-03-19

---

## Executive Summary

### What You Have ✅
- Complete BDI planner with mode selection and routing
- 18 rich personas (YAML-based) with desires, beliefs, constraints
- 39+ job contexts (passenger + freight) with temporal/spatial constraints
- Story-driven agent framework that combines personas + jobs
- Social influence dynamics with habit tracking
- Infrastructure management system
- System dynamics framework
- LLM integration (OLMo 2 + Claude fallback) for story generation

### Phase 1 Complete ✅
**The core innovation is now implemented**: Dynamic plan extraction from story context.

**Implemented flow**:
```
User story context → ContextualPlanGenerator → ExtractedPlan → get_candidate_modes()
                                                               → BDI planner (desire-weighted within filtered set)
                                                               → Emergent behavior
```

**Files implementing Phase 1** (all in `/agent/`):
- `contextual_plan_generator.py` — `ExtractedPlan` dataclass + full rule-based extraction + `get_candidate_modes()`
- `bdi_planner.py` — CPG hooked into `actions_for()` via `plan_generator` param
- `story_driven_agent.py` — `user_story`/`job_story` objects attached to `agent_context`
- `agent_creation.py` — `create_planner()` instantiates CPG and passes to BDIPlanner

**What's now different**:
- `eco_warrior × morning_commute` → CPG removes diesel modes → agents choose bike/bus/ev
- `concerned_parent × shopping_trip` → CPG sets reliability_critical → removes e_scooter  
- `freight_operator × long_haul_freight` → CPG sets must_comply_with LEZ → removes diesel

### What's Still Missing ❌
**Phase 2**: Bayesian Belief Updater — beliefs change from satisfaction + social observations  
**Phase 3**: Markov Mode Switching — mode lock-in and habit formation over time

---

## Phase 1: Core Innovation - Contextual Plan Extraction (4 weeks)

### Week 1: ContextualPlanGenerator Implementation

**Goal**: Create the missing link between story context and executable plans

#### Task 1.1: Create `agent/contextual_plan_generator.py`
**File**: `agent/contextual_plan_generator.py`  
**Lines of code**: ~400-500  
**Dependencies**: None (standalone)

**Required classes**:
```python
@dataclass
class ExtractedPlan:
    """Plan extracted from story context."""
    plan_type: str  # 'point_to_point', 'multi_stop', 'scheduled', 'flexible'
    
    # Temporal constraints
    schedule_fixed: bool = False
    time_window_start: Optional[str] = None
    time_window_end: Optional[str] = None
    recurring_pattern: Optional[str] = None
    
    # Spatial constraints
    waypoints: List[Tuple[float, float]] = None
    avoid_areas: List[str] = None
    
    # Optimization objectives
    primary_objective: str = 'minimize_time'
    secondary_objectives: List[str] = None
    
    # Regulatory/policy constraints
    must_comply_with: List[str] = None
    
    # Operational requirements
    reliability_critical: bool = False
    flexibility_allowed: bool = True

class ContextualPlanGenerator:
    """Extract plans from user story + job story context."""
    
    def __init__(self, llm_backend: str = 'rule_based', llm_config: Dict = None):
        """
        Args:
            llm_backend: 'olmo', 'claude', or 'rule_based'
            llm_config: Config for LLM clients (reuse ingestion service config)
        """
        pass
    
    def extract_plan_from_context(
        self,
        user_story: UserStory,
        job_story: JobStory,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        csv_data: Optional[Dict] = None
    ) -> ExtractedPlan:
        """Main entry point."""
        pass
    
    def _extract_with_rules(self, ...) -> ExtractedPlan:
        """Rule-based extraction (always available)."""
        pass
    
    def _extract_with_llm(self, ...) -> ExtractedPlan:
        """LLM-based extraction (optional enhancement)."""
        pass
```

**Implementation approach**:
1. Start with rule-based extraction (keyword matching + heuristics)
2. Add LLM extraction as optional enhancement
3. Graceful fallback: LLM → rules → defaults

**Rule-based extraction logic**:
```python
# Temporal constraints from job story
if job_story.time_window:
    plan.schedule_fixed = (flexibility in ['none', 'very_low'])
    plan.time_window_start = job_story.time_window.start
    plan.time_window_end = job_story.time_window.end

# Recurring pattern
if job_story.parameters.get('recurring'):
    plan.recurring_pattern = 'daily'

# Primary objective from user narrative
if 'carbon' in user_story.narrative.lower():
    plan.primary_objective = 'minimize_carbon'
elif 'budget' in user_story.narrative.lower():
    plan.primary_objective = 'minimize_cost'
elif urgency == 'critical':
    plan.primary_objective = 'minimize_time'

# Reliability critical
if 'safety' in narrative or 'children' in narrative:
    plan.reliability_critical = True

# Regulatory constraints from plan_context
for context in job_story.plan_context:
    if 'compliance' in context or 'regulation' in context:
        plan.must_comply_with.append(context)
```

**Test cases** (create `tests/test_contextual_plan_generator.py`):
```python
def test_school_run_extraction():
    """School run should extract: fixed schedule, carbon objective, reliability critical."""
    user_story = load_user_story('concerned_parent')
    job_story = load_job_story('school_run_then_work')
    
    plan = generator.extract_plan_from_context(user_story, job_story, origin, dest)
    
    assert plan.schedule_fixed == True
    assert plan.primary_objective == 'minimize_carbon'
    assert plan.reliability_critical == True

def test_freight_operator_extraction():
    """Freight should extract: policy compliance, cost optimization, multi-stop."""
    user_story = load_user_story('freight_operator')
    job_story = load_job_story('freight_delivery_route')
    
    plan = generator.extract_plan_from_context(user_story, job_story, origin, dest)
    
    assert 'compliance' in str(plan.must_comply_with).lower()
    assert plan.primary_objective in ['minimize_cost', 'minimize_time']
```

**Deliverable**: Working `ContextualPlanGenerator` with rule-based extraction passing all test cases

**STATUS: ✅ COMPLETE** (2026-03-19) — All 5 mode filters implemented, wired into BDI planner and StoryDrivenAgent.

---

#### Task 1.2: Integrate with BDI Planner
**File**: `agent/bdi_planner.py` (modify existing)  
**Lines to modify**: ~50-100

**Changes required**:

1. **Constructor update**:
```python
class BDIPlanner:
    def __init__(
        self, 
        infrastructure_manager=None,
        plan_generator=None  # NEW
    ):
        self.infrastructure = infrastructure_manager
        self.plan_generator = plan_generator  # NEW
        # ... existing code
```

2. **`actions_for()` method enhancement**:
```python
def actions_for(self, env, state, origin, dest, agent_context=None):
    """Generate actions WITH context-aware planning."""
    
    # NEW: Extract plan from story context if available
    if self.plan_generator and agent_context and 'user_story' in agent_context:
        extracted_plan = self.plan_generator.extract_plan_from_context(
            user_story=agent_context['user_story'],
            job_story=agent_context['job_story'],
            origin=origin,
            dest=dest,
            csv_data=agent_context.get('csv_data')
        )
        
        # Use extracted plan to filter modes
        return self._actions_from_extracted_plan(
            env, state, origin, dest, extracted_plan, agent_context
        )
    
    # Fallback to existing logic
    return self._traditional_action_generation(env, state, origin, dest, agent_context)
```

3. **New method: `_actions_from_extracted_plan()`**:
```python
def _actions_from_extracted_plan(
    self, env, state, origin, dest, plan: ExtractedPlan, context: Dict
) -> List[Action]:
    """Generate actions respecting extracted plan constraints."""
    
    # Filter modes based on plan objectives
    if plan.primary_objective == 'minimize_carbon':
        candidate_modes = ['walk', 'bike', 'bus', 'train', 'ev']
    elif plan.primary_objective == 'minimize_cost':
        candidate_modes = ['walk', 'bike', 'bus']
    elif plan.primary_objective == 'minimize_time':
        candidate_modes = ['car', 'ev', 'taxi', 'train']
    else:
        candidate_modes = self.default_modes
    
    # Apply plan constraints
    if plan.reliability_critical:
        # Remove unreliable modes in bad weather
        candidate_modes = [m for m in candidate_modes if m not in ['bike', 'walk']]
    
    if plan.must_comply_with:
        # Apply regulatory constraints (e.g., low emission zones)
        candidate_modes = [m for m in candidate_modes if m not in ['car_petrol', 'car_diesel']]
    
    # Generate routes for candidate modes
    actions = []
    for mode in candidate_modes:
        route = env.compute_route(state.agent_id, origin, dest, mode)
        if route and len(route) >= 2:
            params = self._get_mode_params(mode, plan)
            actions.append(Action(mode=mode, route=route, params=params))
    
    return actions

def _get_mode_params(self, mode: str, plan: ExtractedPlan) -> Dict:
    """Extract mode-specific parameters from plan."""
    params = {}
    
    # Add time window constraints
    if plan.time_window_start:
        params['time_window_start'] = plan.time_window_start
        params['time_window_end'] = plan.time_window_end
    
    # Add reliability requirements
    if plan.reliability_critical:
        params['reliability_required'] = True
    
    return params
```

**Test case**:
```python
def test_planner_uses_extracted_plan():
    """Planner should respect extracted plan constraints."""
    plan_gen = ContextualPlanGenerator()
    planner = BDIPlanner(plan_generator=plan_gen)
    
    # Eco warrior should get eco modes
    eco_context = {
        'user_story': load_user_story('eco_warrior'),
        'job_story': load_job_story('morning_commute')
    }
    
    actions = planner.actions_for(env, state, origin, dest, eco_context)
    modes = [a.mode for a in actions]
    
    assert 'walk' in modes or 'bike' in modes
    assert 'car_petrol' not in modes  # Should be filtered out
```

**Deliverable**: BDI planner uses contextual plans to filter modes

---

#### Task 1.3: Update StoryDrivenAgent Context Passing
**File**: `agent/story_driven_agent.py` (modify existing)  
**Lines to modify**: ~20-30

**Changes**:
```python
def _extract_agent_context(self) -> Dict:
    """Extract context AND include stories for plan generation."""
    context = {}
    
    # ... existing extraction logic ...
    
    # NEW: Pass stories to planner for context-aware planning
    context['user_story'] = self.user_story
    context['job_story'] = self.job_story
    context['csv_data'] = None  # Will be populated if CSV provided
    
    return context
```

**Test case**:
```python
def test_agent_passes_stories_to_planner():
    """Agent should pass stories in context."""
    agent = StoryDrivenAgent(
        user_story_id='eco_warrior',
        job_story_id='morning_commute',
        origin=origin,
        dest=dest,
        planner=planner
    )
    
    context = agent._extract_agent_context()
    
    assert 'user_story' in context
    assert 'job_story' in context
    assert context['user_story'].story_id == 'eco_warrior'
```

**Deliverable**: Agents pass complete story objects to planner

---

#### Task 1.4: Wire Up in Agent Creation
**File**: `simulation/setup/agent_creation.py` (modify existing)  
**Lines to modify**: ~30-40

**Changes**:
```python
def create_planner(infrastructure: Optional[InfrastructureManager], config: SimulationConfig) -> BDIPlanner:
    """Create BDI planner with contextual plan generator."""
    
    # NEW: Create contextual plan generator if using stories
    plan_generator = None
    if config.user_stories and config.job_stories:
        from agent.contextual_plan_generator import ContextualPlanGenerator
        
        # Start with rule-based (can add LLM later)
        plan_generator = ContextualPlanGenerator(llm_backend='rule_based')
        
        logger.info("✅ Created planner with contextual plan extraction")
    
    # Create BDI planner with plan generator
    planner = BDIPlanner(
        infrastructure_manager=infrastructure,
        plan_generator=plan_generator  # NEW
    )
    
    return planner
```

**Deliverable**: Simulation setup creates planner with plan generator

---

### Week 2: Testing & Validation

#### Task 2.1: Create Test Suite
**File**: `tests/test_contextual_planning.py`  
**Lines of code**: ~300-400

**Test cases needed**:
1. Plan extraction for each persona type
2. Plan extraction for each job type
3. Mode filtering based on extracted plans
4. Integration test: agent → plan extraction → mode selection
5. Edge cases: missing data, malformed stories

**Key test**:
```python
def test_same_persona_different_jobs():
    """Same persona + different jobs should produce different plans."""
    eco_warrior = load_user_story('eco_warrior')
    
    # Job 1: School run (fixed schedule)
    school_run = load_job_story('school_run_then_work')
    plan1 = generator.extract_plan_from_context(eco_warrior, school_run, o, d)
    
    # Job 2: Leisure (flexible)
    leisure = load_job_story('flexible_leisure')
    plan2 = generator.extract_plan_from_context(eco_warrior, leisure, o, d)
    
    assert plan1.schedule_fixed == True
    assert plan2.schedule_fixed == False
    assert plan1.primary_objective == plan2.primary_objective  # Both eco
    assert plan1.reliability_critical != plan2.reliability_critical

def test_different_personas_same_job():
    """Different personas + same job should produce different plans."""
    commute = load_job_story('morning_commute')
    
    # Persona 1: Eco warrior
    eco = load_user_story('eco_warrior')
    plan1 = generator.extract_plan_from_context(eco, commute, o, d)
    
    # Persona 2: Business commuter
    biz = load_user_story('business_commuter')
    plan2 = generator.extract_plan_from_context(biz, commute, o, d)
    
    assert plan1.primary_objective == 'minimize_carbon'
    assert plan2.primary_objective == 'minimize_time'
```

**Deliverable**: Comprehensive test suite passing

---

#### Task 2.2: Validate Against Hand-Crafted Examples
**File**: `tests/fixtures/expected_plans.yaml`

**Create expected plans**:
```yaml
eco_warrior_school_run:
  expected:
    schedule_fixed: true
    primary_objective: minimize_carbon
    reliability_critical: true
    modes_allowed: [walk, bike, bus, ev]
    modes_forbidden: [car_petrol, car_diesel]

freight_operator_delivery:
  expected:
    schedule_fixed: true
    primary_objective: minimize_cost
    must_comply_with: ["policy compliance"]
    modes_allowed: [ev_truck, van_electric]
```

**Validation script**:
```python
def validate_plan_quality():
    """Check if extracted plans match expert expectations."""
    expected = load_yaml('tests/fixtures/expected_plans.yaml')
    
    for combo_id, expected_plan in expected.items():
        user_id, job_id = combo_id.split('_', 1)
        user = load_user_story(user_id)
        job = load_job_story(job_id)
        
        actual = generator.extract_plan_from_context(user, job, o, d)
        
        # Check each expected field
        assert actual.schedule_fixed == expected_plan['schedule_fixed']
        assert actual.primary_objective == expected_plan['primary_objective']
        # ... etc
```

**Deliverable**: Plan quality validation passing

---

#### Task 2.3: Run Full Simulation with Contextual Planning
**Command**: 
```bash
python -m simulation.run_simulation \
  --preset high_ev_demand \
  --user-stories eco_warrior concerned_parent business_commuter \
  --job-stories morning_commute school_run_then_work \
  --steps 100 \
  --num-agents 50
```

**Verify**:
1. Different personas produce different mode distributions
2. Same persona + different jobs produce different behaviors
3. Plans respect story constraints
4. No crashes or fallback to defaults

**Log analysis**:
```python
def analyze_plan_usage():
    """Check if plans are being used in simulation."""
    logs = parse_simulation_logs()
    
    # Count plan extractions
    plan_extractions = logs.count('extracted plan:')
    
    # Count mode selections
    mode_selections_by_plan = logs.count('using extracted plan')
    mode_selections_traditional = logs.count('using traditional logic')
    
    assert plan_extractions > 0, "Plans not being extracted!"
    assert mode_selections_by_plan > mode_selections_traditional, "Plans not being used!"
```

**Deliverable**: Simulation runs successfully with contextual planning

---

### Week 3: LLM Enhancement (Optional)

#### Task 3.1: Add LLM-Based Plan Extraction
**File**: `agent/contextual_plan_generator.py` (enhance existing)

**Add LLM support**:
```python
def _extract_with_llm(
    self,
    user_story: UserStory,
    job_story: JobStory,
    origin: Tuple[float, float],
    dest: Tuple[float, float],
    csv_data: Optional[Dict]
) -> ExtractedPlan:
    """Extract plan using LLM (OLMo 2 or Claude)."""
    
    # Construct prompt
    prompt = f"""Extract the travel plan from this context.

USER STORY:
{user_story.narrative}

Key beliefs:
{chr(10).join('- ' + b.text for b in user_story.beliefs[:3])}

JOB CONTEXT:
{job_story.context}
{job_story.goal}
{job_story.outcome}

Plan context:
{chr(10).join('- ' + c for c in job_story.plan_context[:5])}

Extract:
1. Is this a scheduled trip with fixed times? (yes/no)
2. Primary optimization objective? (minimize_time/minimize_carbon/minimize_cost)
3. Is reliability critical? (yes/no)
4. Regulatory constraints? (list)

Respond in JSON:
{{
    "schedule_fixed": true/false,
    "primary_objective": "...",
    "reliability_critical": true/false,
    "regulatory_constraints": [],
    "reasoning": "..."
}}"""
    
    # Call LLM (reuse your ingestion service infrastructure)
    response = self.llm.complete(prompt, temperature=0.1)
    
    # Parse JSON
    plan_data = json.loads(response)
    
    # Convert to ExtractedPlan
    plan = ExtractedPlan(
        plan_type='point_to_point',
        schedule_fixed=plan_data['schedule_fixed'],
        primary_objective=plan_data['primary_objective'],
        reliability_critical=plan_data['reliability_critical'],
        must_comply_with=plan_data['regulatory_constraints']
    )
    
    logger.info(f"LLM reasoning: {plan_data['reasoning']}")
    
    return plan
```

**Test LLM vs rules**:
```python
def test_llm_vs_rules():
    """LLM should produce similar plans to rules for clear cases."""
    rule_gen = ContextualPlanGenerator(llm_backend='rule_based')
    llm_gen = ContextualPlanGenerator(llm_backend='olmo')
    
    user = load_user_story('eco_warrior')
    job = load_job_story('school_run')
    
    rule_plan = rule_gen.extract_plan_from_context(user, job, o, d)
    llm_plan = llm_gen.extract_plan_from_context(user, job, o, d)
    
    # Should agree on key fields
    assert rule_plan.primary_objective == llm_plan.primary_objective
    assert rule_plan.reliability_critical == llm_plan.reliability_critical
```

**Deliverable**: LLM enhancement working with fallback to rules

---

#### Task 3.2: Prompt Tuning
**File**: `agent/contextual_plan_generator.py`

**Test different prompts**:
1. Zero-shot prompt (above)
2. Few-shot prompt with examples
3. Chain-of-thought prompt

**Validation**:
- Run on 50 persona-job combinations
- Compare LLM plans vs hand-crafted expectations
- Calculate accuracy metrics

**Deliverable**: Optimized prompt achieving >90% accuracy

---

### Week 4: Documentation & Cleanup

#### Task 4.1: Code Documentation
- Add docstrings to all new methods
- Create `docs/contextual_planning.md` explaining the system
- Add inline comments for complex logic

#### Task 4.2: Performance Optimization
- Profile plan extraction time
- Cache extracted plans for same story combinations
- Optimize rule-based extraction

#### Task 4.3: Phase 1 Deliverable Report
**File**: `docs/phase1_completion_report.md`

**Contents**:
- Implementation summary
- Test results
- Performance metrics
- Mode distribution changes (before/after)
- Example scenarios demonstrating emergent behavior

---

## Phase 2: Cognitive Enhancement - Bayesian Belief Updating (3 weeks)

### Week 5: Bayesian Belief Updater

#### Task 5.1: Create Bayesian Belief Updater
**File**: `agent/bayesian_belief_updater.py`  
**Lines of code**: ~200-300

**Core functionality**:
```python
class BayesianBeliefUpdater:
    """Update agent beliefs based on experience + social observations."""
    
    def update_mode_belief(
        self,
        prior_belief_strength: float,  # From user story
        satisfaction_history: List[float],  # Agent's experiences
        social_observations: Dict[str, float]  # Peer experiences
    ) -> float:
        """
        Bayesian update: P(belief | experience, social)
        
        Example:
        Prior: "EVs are eco-friendly" (0.8)
        Experience: [0.3, 0.4, 0.2] (charging delays)
        Social: Friends report range anxiety
        → Updated: 0.6 (still believe but with concerns)
        """
        
        # Prior from user story
        prior = prior_belief_strength
        
        # Likelihood from personal experience
        if satisfaction_history:
            avg_satisfaction = np.mean(satisfaction_history[-5:])
            experience_evidence = avg_satisfaction
        else:
            experience_evidence = 0.5
        
        # Likelihood from social observations
        if social_observations:
            social_evidence = np.mean(list(social_observations.values()))
        else:
            social_evidence = 0.5
        
        # Bayesian update (simplified)
        posterior = (
            0.4 * prior +
            0.4 * experience_evidence +
            0.2 * social_evidence
        )
        
        return np.clip(posterior, 0.0, 1.0)
    
    def update_all_beliefs(
        self,
        agent: StoryDrivenAgent,
        satisfaction_tracker: Dict[str, List[float]],
        social_network: SocialNetwork
    ) -> None:
        """Update all beliefs for an agent."""
        for belief in agent.user_story.beliefs:
            if not belief.updateable:
                continue
            
            # Get relevant satisfaction history
            relevant_modes = self._get_modes_for_belief(belief)
            satisfaction_history = []
            for mode in relevant_modes:
                satisfaction_history.extend(
                    satisfaction_tracker.get(mode, [])
                )
            
            # Get social observations
            social_obs = self._get_social_observations(
                agent, belief, social_network
            )
            
            # Update belief strength
            new_strength = self.update_mode_belief(
                prior_belief_strength=belief.strength,
                satisfaction_history=satisfaction_history,
                social_observations=social_obs
            )
            
            # Log change if significant
            if abs(new_strength - belief.strength) > 0.1:
                logger.info(
                    f"{agent.state.agent_id}: '{belief.text}' "
                    f"{belief.strength:.2f} → {new_strength:.2f}"
                )
            
            belief.strength = new_strength
```

**Novel aspect**: Connecting user story beliefs with experience in transport context

**Test cases**:
```python
def test_belief_strengthens_with_positive_experience():
    """Positive experiences should strengthen beliefs."""
    belief = Belief(text="EVs are eco-friendly", strength=0.7, updateable=True)
    updater = BayesianBeliefUpdater()
    
    # Positive satisfaction history
    satisfaction = [0.8, 0.9, 0.85, 0.9]
    
    new_strength = updater.update_mode_belief(0.7, satisfaction, {})
    
    assert new_strength > 0.7

def test_belief_weakens_with_negative_experience():
    """Negative experiences should weaken beliefs."""
    belief = Belief(text="EVs are reliable", strength=0.8, updateable=True)
    updater = BayesianBeliefUpdater()
    
    # Negative satisfaction (charging delays)
    satisfaction = [0.3, 0.2, 0.4, 0.3]
    
    new_strength = updater.update_mode_belief(0.8, satisfaction, {})
    
    assert new_strength < 0.8
```

**Deliverable**: Working Bayesian belief updater

---

#### Task 5.2: Integrate with Simulation Loop
**File**: `simulation/simulation_loop.py` (modify existing)

**Add belief updating**:
```python
# In simulation loop
if step % 10 == 0:  # Update beliefs every 10 steps
    for agent in agents:
        if hasattr(agent, 'user_story'):
            belief_updater.update_all_beliefs(
                agent,
                satisfaction_tracker,
                social_network
            )
```

**Track satisfaction**:
```python
# After agent.step()
if not agent.state.arrived:
    satisfaction = calculate_mode_satisfaction(agent, env)
    
    # Track by mode
    mode = agent.state.mode
    if mode not in satisfaction_tracker:
        satisfaction_tracker[mode] = []
    satisfaction_tracker[mode].append(satisfaction)
```

**Deliverable**: Beliefs update during simulation

---

### Week 6: Markov Mode Switching Model

#### Task 6.1: Create Markov Mode Switching
**File**: `agent/markov_mode_switching.py`  
**Lines of code**: ~250-350

**Core class**:
```python
class PersonalityMarkovChain:
    """Mode switching model with habit formation."""
    
    def __init__(self, personality_type: str):
        self.personality = personality_type
        self.modes = ['walk', 'bike', 'bus', 'car', 'ev']
        self.transition_matrix = self._init_transition_matrix()
        self.habit_strength = np.zeros(len(self.modes))
    
    def _init_transition_matrix(self) -> np.ndarray:
        """Initialize based on personality (from user story)."""
        n = len(self.modes)
        P = np.ones((n, n)) * 0.1  # Base switching probability
        
        if self.personality == 'eco_warrior':
            # High switching propensity to greener modes
            P[3, 4] = 0.3  # car → EV
            P[3, 1] = 0.2  # car → bike
        elif self.personality == 'business_commuter':
            # Low switching (habit-driven)
            np.fill_diagonal(P, 0.7)  # Stay with current mode
        
        # Normalize rows
        P = P / P.sum(axis=1, keepdims=True)
        return P
    
    def update_transitions(
        self,
        current_mode_idx: int,
        satisfaction: float,
        repetitions: int
    ) -> None:
        """Update transition probabilities based on experience."""
        
        # Increase probability of staying if satisfied
        if satisfaction > 0.7:
            self.transition_matrix[current_mode_idx, current_mode_idx] += 0.05
        
        # Decrease if dissatisfied
        elif satisfaction < 0.3:
            self.transition_matrix[current_mode_idx, current_mode_idx] -= 0.05
        
        # Habit formation: more repetitions = stronger lock-in
        habit_bonus = min(0.3, repetitions * 0.05)
        self.transition_matrix[current_mode_idx, current_mode_idx] += habit_bonus
        
        # Renormalize
        self.transition_matrix = self.transition_matrix / self.transition_matrix.sum(axis=1, keepdims=True)
    
    def predict_next_mode(self, current_mode: str) -> str:
        """Predict next mode choice."""
        mode_idx = self.modes.index(current_mode)
        probs = self.transition_matrix[mode_idx]
        return np.random.choice(self.modes, p=probs)
```

**Novel aspect**: Personality-dependent transition probabilities + habit formation

**Test cases**:
```python
def test_habit_formation():
    """Repeated use should increase lock-in."""
    chain = PersonalityMarkovChain('business_commuter')
    
    car_idx = chain.modes.index('car')
    initial_prob = chain.transition_matrix[car_idx, car_idx]
    
    # Simulate 10 satisfied car trips
    for _ in range(10):
        chain.update_transitions(car_idx, satisfaction=0.8, repetitions=10)
    
    final_prob = chain.transition_matrix[car_idx, car_idx]
    
    assert final_prob > initial_prob  # Habit formed

def test_personality_differences():
    """Different personalities should have different transition patterns."""
    eco = PersonalityMarkovChain('eco_warrior')
    biz = PersonalityMarkovChain('business_commuter')
    
    # Eco warrior should switch more
    eco_stability = np.diag(eco.transition_matrix).mean()
    biz_stability = np.diag(biz.transition_matrix).mean()
    
    assert biz_stability > eco_stability
```

**Deliverable**: Markov model with personality-dependent transitions

---

#### Task 6.2: Integrate Mode Lock-in into Simulation
**File**: `agent/story_driven_agent.py` (enhance)

**Add Markov chain**:
```python
class StoryDrivenAgent(CognitiveAgent):
    def __init__(self, ...):
        # ... existing init ...
        
        # NEW: Markov mode switching
        from agent.markov_mode_switching import PersonalityMarkovChain
        self.mode_chain = PersonalityMarkovChain(self.user_story_id)
    
    def _maybe_plan(self, env):
        """Planning with Markov mode preference."""
        # ... existing planning ...
        
        # Before choosing mode, bias toward Markov prediction
        if hasattr(self, 'mode_chain'):
            predicted_mode = self.mode_chain.predict_next_mode(self.state.mode)
            
            # Boost predicted mode in cost evaluation
            if predicted_mode in mode_costs:
                mode_costs[predicted_mode] *= 0.8  # 20% discount
```

**Track mode repetitions**:
```python
# After mode chosen
self.mode_history.append(self.state.mode)

# Count consecutive uses
consecutive = 1
for m in reversed(self.mode_history[:-1]):
    if m == self.state.mode:
        consecutive += 1
    else:
        break

# Update Markov chain
satisfaction = calculate_mode_satisfaction(self, env)
mode_idx = self.mode_chain.modes.index(self.state.mode)
self.mode_chain.update_transitions(mode_idx, satisfaction, consecutive)
```

**Deliverable**: Mode lock-in visible in simulation

---

## Phase 3: Validation & Analysis (2 weeks)

### Week 7: Emergent Behavior Validation

#### Task 7.1: Demonstrate Emergent Behavior
**Create test scenarios**:

**Scenario 1: Same persona, different contexts**
```python
def test_emergent_school_run_vs_leisure():
    """Eco warrior should behave differently for school vs leisure."""
    # School run
    school_agents = create_agents(
        personas=['eco_warrior'],
        jobs=['school_run_then_work'],
        n=20
    )
    
    # Leisure trip
    leisure_agents = create_agents(
        personas=['eco_warrior'],
        jobs=['flexible_leisure'],
        n=20
    )
    
    # Run simulations
    school_results = run_simulation(school_agents)
    leisure_results = run_simulation(leisure_agents)
    
    # Analyze mode distributions
    school_modes = school_results.mode_distribution
    leisure_modes = leisure_results.mode_distribution
    
    # School run: More car/ev due to time constraints + children
    assert school_modes['ev'] > leisure_modes['ev']
    
    # Leisure: More walk/bike due to flexibility
    assert leisure_modes['walk'] + leisure_modes['bike'] > \
           school_modes['walk'] + school_modes['bike']
```

**Scenario 2: Mode lock-in over time**
```python
def test_mode_lock_in_emergence():
    """Agents should develop habits over time."""
    agents = create_agents(personas=['business_commuter'], jobs=['morning_commute'], n=10)
    
    # Track mode diversity over time
    diversity_history = []
    
    for step in range(200):
        run_simulation_step(agents)
        
        # Calculate mode diversity (entropy)
        mode_counts = Counter(a.state.mode for a in agents)
        diversity = entropy(list(mode_counts.values()))
        diversity_history.append(diversity)
    
    # Diversity should decrease as habits form
    early_diversity = np.mean(diversity_history[:50])
    late_diversity = np.mean(diversity_history[-50:])
    
    assert late_diversity < early_diversity  # Mode lock-in occurred
```

**Deliverable**: Documented emergent behaviors

---

#### Task 7.2: Compare Against Fixed-Plan Baseline
**Create baseline**:
```python
def run_baseline_simulation():
    """Run simulation WITHOUT contextual planning."""
    config = SimulationConfig(
        user_stories=['eco_warrior', 'business_commuter'],
        job_stories=['morning_commute'],
        num_agents=100,
        steps=200
    )
    
    # Disable contextual planning
    config.use_contextual_planning = False
    
    return run_simulation(config)

def run_contextual_simulation():
    """Run simulation WITH contextual planning."""
    config = SimulationConfig(
        user_stories=['eco_warrior', 'business_commuter'],
        job_stories=['morning_commute'],
        num_agents=100,
        steps=200
    )
    
    config.use_contextual_planning = True
    
    return run_simulation(config)

def compare_simulations():
    """Compare outcomes."""
    baseline = run_baseline_simulation()
    contextual = run_contextual_simulation()
    
    # Compare mode diversity
    baseline_diversity = calculate_diversity(baseline.mode_distribution)
    contextual_diversity = calculate_diversity(contextual.mode_distribution)
    
    # Compare emissions
    baseline_emissions = baseline.total_emissions
    contextual_emissions = contextual.total_emissions
    
    # Compare tipping points
    baseline_tipping = baseline.tipping_points_detected
    contextual_tipping = contextual.tipping_points_detected
    
    print(f"Mode diversity: {baseline_diversity:.2f} → {contextual_diversity:.2f}")
    print(f"Emissions: {baseline_emissions:.0f} → {contextual_emissions:.0f}")
    print(f"Tipping points: {baseline_tipping} → {contextual_tipping}")
```

**Deliverable**: Quantitative comparison report

---

### Week 8: Write-Up & Documentation

#### Task 8.1: Research Paper Draft
**File**: `docs/paper_draft.md`

**Structure**:
1. Introduction
   - Problem: Agent-based transport simulations are deterministic
   - Solution: Context-driven BDI generation
   
2. Related Work
   - User stories in RE
   - BDI agent systems
   - Agent-based transport modeling
   
3. Method
   - Contextual plan extraction
   - Bayesian belief updating
   - Markov mode switching
   
4. Results
   - Emergent behavior examples
   - Comparison with baseline
   - Case studies
   
5. Discussion
   - Policy implications
   - Limitations
   - Future work

**Deliverable**: Paper draft

---

#### Task 8.2: Create Demo Scenarios
**File**: `demos/contextual_planning_demo.py`

**Demo 1: School run decarbonization**
```python
def demo_school_run_decarbonization():
    """Show how contextual planning enables policy testing."""
    
    # Before: Parents drive (baseline)
    baseline = simulate_school_runs(
        personas=['concerned_parent'],
        policy='none',
        n=50
    )
    
    # After: Introduce safe cycling infrastructure
    policy = simulate_school_runs(
        personas=['concerned_parent'],
        policy='safe_cycling_infrastructure',
        n=50
    )
    
    # Analyze shift
    baseline_car_share = baseline.mode_share['car']
    policy_bike_share = policy.mode_share['bike']
    
    print(f"Car usage: {baseline_car_share:.1%} → {100-policy_bike_share:.1%}")
    print(f"Bike usage: 0% → {policy_bike_share:.1%}")
    
    # Show emergent safety concern → infrastructure → mode shift
```

**Demo 2: Freight decarbonization with mandates**
```python
def demo_freight_decarbonization():
    """Show compliance-driven planning."""
    
    # Freight operators with regulatory constraints
    results = simulate_freight(
        personas=['freight_operator'],
        jobs=['freight_delivery_route'],
        policy='low_emission_zone',
        n=30
    )
    
    # Show mode shift from diesel → EV due to extracted compliance constraints
    mode_share = results.mode_share
    print(f"EV trucks: {mode_share['ev_truck']:.1%}")
    print(f"Diesel trucks: {mode_share['diesel_truck']:.1%}")
    
    # Show that agents with "compliance" in plan context automatically chose EVs
```

**Deliverable**: Interactive demos

---

## Success Criteria

### Phase 1 Success (Weeks 1-4) — ✅ COMPLETE
- [x] `ContextualPlanGenerator` implemented and tested
- [x] BDI planner uses extracted plans for mode filtering (`actions_for()`)
- [x] Agents pass complete story context to planner (via `agent_context`)
- [x] Simulation runs successfully with contextual planning
- [x] Different personas produce different mode distributions (verified in logs)
- [x] Same persona + different jobs produce different behaviors
- [ ] Test suite passing (>90% coverage) — unit tests still to write

### Phase 2 Success (Weeks 5-6)
- [ ] Bayesian belief updater implemented
- [ ] Beliefs change based on satisfaction + social observations
- [ ] Markov mode switching implemented
- [ ] Mode lock-in visible in simulation
- [ ] Habit formation observable over time

### Phase 3 Success (Weeks 7-8)
- [ ] Emergent behaviors documented with examples
- [ ] Quantitative comparison vs baseline
- [ ] Paper draft completed
- [ ] Demo scenarios working

## Technical Debt & Future Work

### Known Limitations
1. Rule-based extraction may miss nuanced constraints
2. Markov model is simplified (first-order)
3. No multi-modal trip chaining yet
4. CSV integration not fully tested

### Future Enhancements
1. **Inverse RL for desire inference** (validate stated vs revealed preferences)
2. **Multi-agent plan coordination** (ride-sharing, carpooling)
3. **Dynamic replanning** based on events (already partially implemented)
4. **Free-text story input** (currently requires YAML)

## Resources

### Key Files to Modify
1. `agent/contextual_plan_generator.py` (NEW)
2. `agent/bdi_planner.py` (MODIFY)
3. `agent/story_driven_agent.py` (MODIFY)
4. `agent/bayesian_belief_updater.py` (NEW)
5. `agent/markov_mode_switching.py` (NEW)
6. `simulation/setup/agent_creation.py` (MODIFY)

### Key Files to Reference
- `agent/user_stories.py` - UserStory class
- `agent/job_stories.py` - JobStory class
- `agent/social_influence_dynamics.py` - Satisfaction calculation
- `config/ingestion.yaml` - LLM backend config

### Dependencies
- No new dependencies for Phase 1
- `numpy` for Phase 2 (Bayesian/Markov)
- Optional: `anthropic` or `ollama` client for LLM enhancement

## Contact & Support

**Project Lead**: [Your name]  
**Status Tracking**: This document  
**Issues**: Log in `IMPLEMENTATION_LOG.md`

---

## Appendix: Example Scenarios

### Example 1: School Run Extraction
```
Input:
  User: "concerned_parent" - wants to reduce carbon footprint, children's safety paramount
  Job: "school_run_then_work" - fixed schedule (07:30-08:45), 5km, recurring daily

Expected Plan:
  - schedule_fixed: TRUE
  - time_window: 07:30-08:45
  - primary_objective: minimize_carbon
  - reliability_critical: TRUE (children present)
  - modes_filtered: [walk, bike, ev] (no unsafe modes in traffic)

Emergent Behavior:
  - Weather sensitivity: Rain → mode shifts from bike to EV
  - Habit formation: After 10 successful bike trips, locks in unless bad weather
  - Belief evolution: If consistently late, belief "cycling is fast enough" weakens
```

### Example 2: Freight Compliance
```
Input:
  User: "freight_operator" - cost-sensitive, compliance mandatory
  Job: "freight_delivery_route" - multi-stop, low-emission zone, tight deadlines

Expected Plan:
  - must_comply_with: ["low_emission_zone", "delivery_windows"]
  - primary_objective: minimize_cost
  - reliability_critical: TRUE
  - modes_filtered: [ev_truck, van_electric] (only compliant vehicles)

Emergent Behavior:
  - Cost-compliance tradeoff: Chooses cheapest compliant mode
  - Route adaptation: Avoids non-compliant routes even if shorter
  - Belief evolution: If EV charging delays occur, belief "EVs are operationally viable" weakens
```

---

**Last Updated**: 2025-01-21  
**Version**: 1.0  
**Status**: Phase 0 (Planning) → Ready to start Phase 1