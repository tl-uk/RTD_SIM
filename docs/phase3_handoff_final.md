# RTD_SIM Phase 3 Handoff Document

**Project:** Real-Time Decarbonization Simulator  
**Status:** Phase 1-2 Complete, Starting Phase 3  
**Date:** December 2024  
**Developer:** Solo researcher  
**Timeline:** 18-month nationally funded research project  
**Platform:** macOS (Apple Silicon M3), Python 3.13

---

## 🎯 Current Status Summary

**Completed:** ✅ Phase 1 (BDI Architecture), Phase 2.1 (OSM Integration), Phase 2.2 (Route Alternatives), Phase 2.2b (Congestion), Phase 2.3 (Visualization)

**Next:** Phase 3 - User/Job Story Framework + BDI Integration

**All Tests:** 18/18 passing (6+6+6 across Phase 2.1, 2.2, 2.2b)

---

## 📋 What's Been Achieved

### Phase 1: Core BDI Architecture ✅
- BDI (Belief-Desire-Intention) cognitive agents
- Event bus for pub/sub communication
- Basic simulation controller with multi-agent support
- Agent movement along routes
- Emissions tracking and CSV export

**Files:**
- `agent/cognitive_abm.py` (270 lines) - BDI agent implementation
- `agent/bdi_planner.py` (120 lines) - Route planning with desires
- `simulation/controller.py` (130 lines) - Multi-agent orchestration
- `simulation/event_bus.py` (50 lines) - Event system

### Phase 2.1: OSM Integration & Elevation ✅
- Real street networks via OpenStreetMap
- Mode-specific networks (walk/bike/drive)
- Graph caching system (22.9x speedup)
- OpenTopoData elevation API integration
- Elevation-aware energy consumption models
- **Performance:** <2s cached, 18-20s first download
- **Tests:** 6/6 passing

### Phase 2.2: Route Alternatives ✅
- 5 route variants: shortest, fastest, safest, greenest, scenic
- Route scoring with multiple objectives
- Pareto-optimal filtering
- Comprehensive metrics: distance, time, cost, emissions, comfort, risk, elevation
- **Tests:** 6/6 passing

### Phase 2.2b: Dynamic Congestion ✅
- Real-time edge-level traffic tracking
- 3 congestion models: Linear, BPR, Exponential
- Time-of-day patterns (rush hour modeling)
- Road capacity by highway type
- Congestion-aware routing (fastest routes avoid traffic)
- **Performance:** Only 12.2% overhead
- **Tests:** 6/6 passing

### Phase 2.3: Advanced Visualization ✅ (Functionally Complete)
- Real-time agent visualization using pydeck (deck.gl)
- Interactive map with Carto basemaps (Mapbox requires token)
- Manual animation via slider + step buttons (auto-play has Streamlit rerun issue)
- Congestion heatmap rendering
- Layer management (agents, routes, congestion toggles)
- Real-time metrics dashboard
- Time series charts (Plotly)
- **Status:** Manual step-through working perfectly, sufficient for research

---

## 🏗️ Current Architecture

### Project Structure
```
RTD_SIM/
├── agent/
│   ├── cognitive_abm.py           # BDI agents (270 lines)
│   ├── bdi_planner.py             # Route planning (120 lines)
│   └── social_network.py          # Social influence (100 lines)
├── simulation/
│   ├── spatial/
│   │   ├── __init__.py
│   │   ├── coordinate_utils.py    # Haversine, distances (150 lines)
│   │   ├── metrics_calculator.py  # Travel metrics (200 lines)
│   │   ├── graph_manager.py       # OSM loading/cache (250 lines)
│   │   ├── router.py              # Multi-route planning (250 lines)
│   │   └── congestion_manager.py  # Traffic tracking (400 lines)
│   ├── spatial_environment.py     # Main facade (120 lines)
│   ├── route_alternative.py       # Route data class (150 lines)
│   ├── controller.py              # Simulation orchestrator (130 lines)
│   ├── event_bus.py               # Pub/sub events (50 lines)
│   ├── data_adapter.py            # CSV export
│   └── elevation_provider.py      # OpenTopoData API (300 lines)
├── visualiser/
│   ├── __init__.py
│   ├── style_config.py            # Colors & styling (120 lines)
│   ├── data_adapters.py           # Sim → viz format (290 lines)
│   └── animation_controller.py    # Playback state (260 lines)
├── ui/
│   ├── streamlit_app.py           # Original Phase 2.1 UI
│   └── streamlit_viz_app.py       # Phase 2.3 advanced viz
├── test_phase2_routing.py         # 6/6 passing
├── test_phase2.2_route_alternatives.py  # 6/6 passing
├── test_phase2.2b_congestion.py   # 6/6 passing
└── handoff_phase23.md             # Previous handoff doc
```

### Tech Stack (All Installed & Working)
- Python 3.13, OSMnx 1.9.4, NetworkX 3.4.2
- Streamlit 1.40.1, pydeck 0.9.1, Plotly 5.24.1
- pandas 2.2.3, numpy 2.1.3
- All in virtual environment (venv)

---

## 🎯 True Project Vision (CRITICAL)

### From RTD-AMB.docx Project Brief

**This is NOT a traditional batch ABM simulation.**

**It IS:**
- ✅ **Real-time digital twin** (event-driven, not fixed timesteps)
- ✅ **Streaming System Dynamics** (incremental stock updates, not ODE solving)
- ✅ **MQTT/IoT integration** (live data feeds - Phase 5)
- ✅ **BDI cognitive agents** (explainable decisions, conflicting goals)
- ✅ **User + Job Story driven** (stories → agent behavior)
- ✅ **Social cascades & emergence** (tipping points, viral adoption)
- ✅ **Live policy injection** (A/B test interventions while running)
- ✅ **Multi-scale system:** Freight + passengers, rural-urban-city, regional-national-international

### Core Innovation (Research Contribution)

**PRIMARY FOCUS:** Story-driven BDI agents for transport decarbonization

**Key contributions:**
1. User stories → BDI desires/beliefs (formal mapping)
2. Job stories → transport tasks/constraints
3. Combined stories → realistic agent behavior
4. Social influence → cascades & tipping points
5. Real-time belief updating from observations
6. Streaming SD integration (not batch)

**NOT primarily about:** Multi-scale freight optimization (that's application context)

### Three-Layer Architecture (From Project Doc)

**Layer 1: BDI Agent System (Micro)** ← Phase 1-2 complete
- Individual transport decisions
- Cognitive reasoning with conflicting goals
- Plan library with fallbacks
- Habit formation and social influence

**Layer 2: System Dynamics (Macro)** ← Phase 4
- Streaming SD (not batch ODE)
- Feedback loops: carbon budget → policy → behavior
- Aggregate stocks/flows updated on events
- Continuous data assimilation (Kalman-like)

**Layer 3: Policy Controller** ← Phase 5-6
- Live policy injection while running
- Baseline capture + A/B comparison
- Automatic rollback on anomalies
- Scenario testing framework

---

## 📚 Publication Strategy (Mandatory Deliverables)

### Paper 1: Transportation Science (Methodology)
**Title:** "Real-Time Story-Driven BDI Agents for Transport Digital Twins"

**Novel contributions:**
1. Formal mapping: user/job stories → BDI architecture
2. Real-time belief updating from observations
3. Streaming SD integration (not batch)
4. Social cascade detection mechanisms

**Target submission:** Month 10 (after social cascades work)

### Paper 2: Transportation Research Part D (Application + Environment)
**Title:** "Emergent Decarbonization: Social Cascades in a Real-Time Transport Digital Twin"

**Novel contributions:**
1. Social influence in mode choice
2. Tipping point identification
3. Policy injection during runtime
4. Environmental feedback loops
5. Scotland case study validation

**Target submission:** Month 14 (after validation)

### Paper 3: Environmental Modelling & Software (Tool)
**Title:** "RTD_SIM: An Open-Source Real-Time Transport Decarbonization Digital Twin"

**Novel contributions:**
1. Lean digital twin architecture (not traditional ABM)
2. Story-driven agent generation framework
3. Event-driven vs. batch comparison
4. MQTT/IoT integration patterns
5. Reproducibility + extensions

**Target submission:** Month 17 (after documentation)

---

## 🚀 Phase 3: User/Job Story Framework (NEXT)

### Goals (Months 3-4, ~4 weeks)

**Core objective:** Implement story-driven agent generation system

**Deliverables:**
1. Story specification format (YAML)
2. Story-to-BDI parser implementation
3. Library of 10+ user personas
4. Library of 10+ job contexts
5. Generate 100 agents from 10×10 story combinations
6. Validation: agent behavior matches story intent

### Story Framework Concepts

#### User Stories → BDI Desires

**Example:**
```yaml
# agent/personas.yaml
eco_warrior:
  narrative: "As an environmental activist, I want to minimize my carbon footprint..."
  desires:
    eco: 0.9        # High environmental concern
    time: 0.3       # Less concerned about time
    cost: 0.4       # Moderate cost sensitivity
    comfort: 0.2    # Low comfort priority
    safety: 0.5     # Moderate safety concern
  beliefs:
    - "Public transport reduces carbon emissions"
    - "Cycling is healthy and sustainable"
    - "EVs are better than petrol cars"
  
busy_parent:
  narrative: "As a working parent, I need reliable transport for complex trips..."
  desires:
    reliability: 0.9
    time: 0.8
    flexibility: 0.7
    safety: 0.9
    cost: 0.5
  constraints:
    - "School pickup by 3pm"
    - "No mode switches with kids"
```

#### Job Stories → Task Context

**Example:**
```yaml
# agent/job_contexts.yaml
morning_commute:
  context: "When commuting to work during rush hour"
  goal: "I want to arrive on time without stress"
  outcome: "So I can be productive at work"
  parameters:
    time_window: [07:00, 09:00]
    destination_type: "workplace"
    flexibility: "low"
    typical_distance: "5-15 km"
  
school_run_then_work:
  context: "When doing school drop-off then going to work"
  goal: "I want a safe, reliable multi-stage trip"
  outcome: "So everyone arrives safely and on time"
  parameters:
    multi_stage: true
    stages:
      - {destination_type: "school", time_window: [08:00, 08:45]}
      - {destination_type: "workplace", time_window: [09:00, 09:30]}
    constraints: ["child_safety", "time_critical"]
    flexibility: "very_low"
```

#### Combined → Agent Instance

**Code example:**
```python
# Generate agent from stories
agent = StoryDrivenAgent(
    user_story="eco_warrior",
    job_story="morning_commute",
    origin=(-3.19, 55.95),  # Edinburgh coordinates
    dest=(-3.15, 55.97)
)

# Results in agent with:
# - High eco concern (0.9) from user story
# - Time pressure from job context (rush hour)
# - Morning commute constraints
# - Will prefer bike/bus over car (eco + time balance)
```

### Implementation Plan

#### Week 1: Design & Specification

**Day 1-2: Story Format Design**
- Finalize YAML schema for user stories
- Finalize YAML schema for job stories  
- Define mapping rules: story fields → BDI parameters
- Create validation criteria (completeness checks)

**Day 3-4: Story Library Creation**
- Write 10 user personas:
  - eco_warrior, busy_parent, budget_student, business_traveler
  - disabled_commuter, elderly_resident, delivery_driver, tourist
  - shift_worker, remote_worker
- Write 10 job contexts:
  - morning_commute, school_run, shopping_trip, leisure_travel
  - delivery_route, night_shift, airport_trip, multi_stop
  - emergency_trip, flexible_visit
- Document 20+ realistic combined scenarios

**Day 5: Architecture Design**
- Design StoryParser class structure
- Design StoryDrivenAgent class (extends CognitiveAgent)
- Plan integration with existing code
- Write test specification

**Deliverable:** `docs/STORY_FRAMEWORK.md` with complete design

#### Week 2: Implementation & Testing

**Day 6-7: Parser Implementation**

Create new files:
```python
# agent/user_stories.py
class UserStoryParser:
    @staticmethod
    def load_from_yaml(story_id: str) -> UserStory:
        """Load user story from personas.yaml"""
        pass
    
    def to_bdi_desires(self) -> Dict[str, float]:
        """Map story → desire parameters"""
        pass

# agent/job_stories.py
class JobStoryParser:
    @staticmethod
    def load_from_yaml(job_id: str) -> JobStory:
        """Load job story from contexts.yaml"""
        pass
    
    def to_task_context(self) -> TaskContext:
        """Extract origin, dest, time_window, constraints"""
        pass

# agent/story_driven_agent.py
class StoryDrivenAgent(CognitiveAgent):
    """Agent created from user + job stories."""
    
    def __init__(self, user_story_id: str, job_story_id: str, 
                 origin: Tuple[float, float], dest: Tuple[float, float]):
        # Load stories
        user_story = UserStoryParser.load_from_yaml(user_story_id)
        job_story = JobStoryParser.load_from_yaml(job_story_id)
        
        # Extract parameters
        desires = user_story.to_bdi_desires()
        task_context = job_story.to_task_context()
        
        # Initialize parent
        super().__init__(
            desires=desires,
            origin=origin,
            dest=dest,
            time_window=task_context.time_window
        )
```

**Day 8-9: Integration & Testing**
- Unit tests for parsers
- Integration tests with simulation
- Generate 100 agents from 10×10 combinations
- Run test simulations

**Day 10: Validation**
- Qualitative: Do agent behaviors match story intent?
- Compare mode choices across different personas
- Validate time-of-day patterns from job contexts
- Check edge cases and conflicts

**Deliverables:**
- Working story framework
- 20+ documented stories
- 100-agent test simulation
- `test_phase3_stories.py` (all passing)

---

## 📊 Key Design Decisions Made

### 1. Visualization: Streamlit (Keep for Phase 3-4)
**Decision:** Stay with Streamlit, add Grafana in Phase 5
**Reasoning:** 
- Fast iteration for research
- Good enough for development/analysis
- Manual animation acceptable (step-through works)
- Grafana better for real-time ops (Phase 5+)

### 2. Architecture: Modular Components
**Decision:** Build separate but integrated systems
**Components:**
- RTD_SIM Core (BDI + stories) ← Current focus (Phase 1-3)
- Social Network Layer ← Phase 3-4
- System Dynamics ← Phase 4
- StratFreight (strategic freight) ← Phase 4-5
- EcoModel (environmental) ← Phase 5-6
- Policy Layer (interventions) ← Phase 6

### 3. Story-First Approach
**Decision:** User/Job stories are PRIMARY driver, not optional
**Reasoning:**
- Core research contribution (novel)
- Enables stakeholder engagement
- Natural specification format
- Testable with acceptance criteria
- Maps directly to BDI architecture

### 4. No Jupyter Notebooks
**Decision:** Use Python scripts + Streamlit, no notebooks
**Reasoning:**
- Asyncio conflicts in notebooks
- Poor version control (ipynb files)
- Can't run long simulations in background
- Better debugging in VS Code

---

## 🐛 Known Issues & Status

### Resolved Issues ✅
- ✅ Map loading (use Carto basemaps, not Mapbox)
- ✅ OSM performance (caching working, 22.9x speedup)
- ✅ Elevation integration (OpenTopoData API stable)
- ✅ Congestion overhead (only 12.2%, acceptable)
- ✅ Pydeck compatibility (working with deck.gl)

### Accepted Limitations
- ⚠️ **Auto-play animation** (Streamlit `st.rerun()` issue)
  - **Status:** Manual step-through working perfectly
  - **Workaround:** Step Forward button + slider = functional
  - **Decision:** Good enough for Phase 3-4 research
  - **Future:** Will fix with Grafana (Phase 5)

### Not Yet Implemented (Phase 3+)
- ❌ User/Job story framework ← Phase 3
- ❌ Social network layer ← Phase 3-4
- ❌ System Dynamics integration ← Phase 4
- ❌ MQTT/IoT real-time feeds ← Phase 5
- ❌ Policy injection system ← Phase 6

---

## 💡 Critical Context & Constraints

### Time & Resources
- **Timeline:** 18 months total (2-3 months spent on Phase 1-2)
- **Developer:** Solo (manage scope carefully)
- **Funding:** Nationally funded research (stakeholder deliverables)
- **Publications:** 3 papers mandatory

### Design Philosophy to Maintain
- **Modular:** Each component independent, testable
- **Event-driven:** Not fixed timesteps (async-ready)
- **Story-first:** User/job stories drive all behavior
- **Explainable:** BDI agents articulate reasoning
- **Lean:** Fast enough for real-time (not MATSim scale)
- **Real-world:** Scotland case study focus

### Validation Strategy
- Edinburgh travel survey (modal split comparison)
- Transport Scotland statistics (aggregate validation)
- Stakeholder interviews (story resonance)
- Qualitative + quantitative methods

---

## 🔑 Phase 3 Success Criteria

**Phase 3 complete when:**

- [ ] Story specification format defined (YAML schema)
- [ ] 10+ user personas documented
- [ ] 10+ job contexts documented
- [ ] Story parser implemented & tested
- [ ] StoryDrivenAgent class working
- [ ] 100 agents generated from 10×10 stories
- [ ] Agents exhibit different behaviors based on stories
- [ ] Behavior qualitatively matches story intent
- [ ] Integration tests passing
- [ ] Documentation complete (`docs/STORY_FRAMEWORK.md`)

---

## 📁 Files to Create in Phase 3

### Story Library
```
agent/personas.yaml          # 10+ user story definitions
agent/job_contexts.yaml      # 10+ job story definitions
```

### Implementation
```
agent/user_stories.py        # UserStory parser class
agent/job_stories.py         # JobStory parser class  
agent/story_driven_agent.py  # StoryDrivenAgent class
stories/__init__.py          # Story module
stories/parser.py            # Combined parsing logic
stories/validator.py         # Story validation
stories/generator.py         # Bulk agent generation
```

### Testing & Documentation
```
test_phase3_stories.py       # Story framework tests
docs/STORY_FRAMEWORK.md      # Complete specification
examples/story_examples.py   # Usage examples
```

---

## 🎯 Phase 3 Week-by-Week Plan

### Week 1: Design & Specification
- **Output:** Complete story format specification
- **Deliverable:** `docs/STORY_FRAMEWORK.md`
- **Contains:** YAML schemas, mapping rules, 20+ stories

### Week 2: Implementation
- **Output:** Working story-driven agent generation
- **Deliverable:** Code + tests + 100-agent demo
- **Validates:** Behavior matches story intent

### Validation Criteria
1. **Eco_warrior + morning_commute** → Prefers bike/bus despite time
2. **Busy_parent + school_run** → Prioritizes safety + reliability over speed
3. **Budget_student + flexible_travel** → Chooses walk/bus to minimize cost
4. **Business_traveler + airport_trip** → Values time + comfort, accepts higher cost

---

## 🚀 Research Questions (Phase 3)

### Primary Questions
1. Can user stories generate realistic desire parameters?
2. Do job stories capture task constraints adequately?
3. Does combining stories produce diverse, believable agents?
4. Can we generate 1000+ unique agents from 20 base stories?

### Validation Questions
5. Do story-based agents match Edinburgh survey modal split?
6. Do stakeholders recognize themselves in the stories?
7. Is behavior explainable (can agents articulate reasoning)?
8. Better than random desire assignment?

---

## 📞 How to Start New Session

### Copy this entire file and say:

> "I'm continuing development of RTD_SIM, a real-time transport decarbonization simulator. I've attached the Phase 3 handoff document with complete project context.
> 
> **Current status:** Phase 1-2 complete (BDI agents, OSM routing, visualization all working). Ready to start Phase 3: User/Job Story Framework.
> 
> **Next task:** Design the story specification format and create the first 10 user personas + 10 job contexts.
> 
> Please review the handoff document and help me:
> 1. Design the YAML story format
> 2. Create the first 10 user persona stories
> 3. Create the first 10 job context stories
> 
> Let's start with the story format design."

### Alternative shorter prompt:

> "Continuing RTD_SIM Phase 3 - User/Job Story Framework. Phase 1-2 complete (see attached handoff). Ready to design story specification format and create persona/context libraries. Please review handoff doc and let's begin with story format design."

---

## 🎉 Summary

**Achievements:** 
- ✅ Solid BDI foundation with modular architecture
- ✅ Real OSM routing with 5 alternatives + congestion
- ✅ Working visualization (manual animation sufficient)
- ✅ 18/18 tests passing, performance optimized

**Ready for:** 
- 🚀 User/Job story framework (Phase 3)
- 📖 Core research contribution begins
- 📝 Paper 1 methodology foundation

**Timeline:** On track for 18-month completion with 3 publications

**Confidence:** HIGH - foundation is solid, clear path forward

---

**End of Handoff Document**

*Last updated: December 2024*  
*Version: 2.3.0 → 3.0.0*  
*Next: Phase 3 - Story Framework Design*
