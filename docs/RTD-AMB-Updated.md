# Transport Decarbonisation ABM — Project Brief (Revised)

> **Document status:** Living specification. This revision supersedes the original implementation phases and incorporates decisions made during Phase 5–7 development. C++ hybrid layer is retained as a long-term target but is explicitly deferred until a working Python prototype is stable and domain-agnostic.

---

## Vision Statement

Build a real-time, multi-agent simulation framework that combines BDI (Belief-Desire-Intention) cognitive architecture with System Dynamics to model, analyse, and predict transport decarbonisation pathways across rural-urban-city corridors, revealing emergent behaviours and testing policy interventions.

The framework must be **domain-agnostic**: deployable against any operational domain (ports, airports, NHS logistics, freight networks, urban transport) by uploading a domain brief, not by changing code.

---

## What We Are Building

A lightweight, real-time capable digital twin that simulates:

- Individual transport decisions using BDI cognitive agents (micro-level)
- System-level dynamics using System Dynamics (macro-level)
- Social influence and habit formation through agent networks
- Policy interventions with live injection and A/B testing
- Environmental impacts including biodiversity and ecosystem effects
- Infrastructure evolution and capacity constraints

### Why This Matters

- **Reveals emergent behaviours:** Social cascades, tipping points, modal shifts
- **Tests transition pathways:** Policy effectiveness before real-world implementation
- **Realistic human factors:** Conflicting goals, habits, social norms, learning
- **Real-time capable:** Integration with IoT, digital twins, CPS systems
- **Explainable:** BDI agents can articulate their reasoning
- **Domain-portable:** Same codebase, different story library per deployment

---

## Core Design Philosophy

**Lean Real-Time Digital Twin — not a traditional batch ABM.**

An event-driven, streaming system that:

- Accepts real-time MQTT/IoT data feeds
- Updates incrementally (not fixed time steps)
- Maintains SD model validity through continuous data assimilation
- Allows live policy injection while running
- Scales through adaptive agent sampling
- Loads domain configuration at runtime, not compile time

---

## Architecture Overview

### Three-Layer System

```
┌────────────────────────────────────────────────────────────────────┐
│  LAYER 3: BDI AGENTS  (Bounded Rationality + Trust-Weighted)       │
│  · Perception radius: 5–50 km (persona-dependent)                  │
│  · Belief confidence: Decays over time                             │
│  · Trust-weighted peer reports                                     │
│  · Event-driven replanning (not periodic)                          │
│  · Graceful degradation on plan failure                            │
│  · Loaded from domain story library at runtime                     │
└──────────────────────────┬─────────────────────────────────────────┘
                           │ Agent actions aggregate back to...
                           ▼
┌────────────────────────────────────────────────────────────────────┐
│  LAYER 2: EVENT BUS  (Pub-Sub + Spatial Index + Service Router)    │
│  · R-tree spatial index for fast radius queries                    │
│  · Event types: PolicyChange, InfrastructureFailure, Weather, ...  │
│  · MQTT bridge: Real-time IoT feeds → Events                       │
│  · Routing table: EventType → InMemory | Microservice URL          │
│  · Fire-and-forget async queue (simulation loop never blocks)      │
│  · Schema contract enforcement per EventType                       │
└──────────────────────────┬─────────────────────────────────────────┘
                           │ Stock crossing thresholds → Discrete events
                           ▼
┌────────────────────────────────────────────────────────────────────┐
│  LAYER 1: STREAMING SYSTEM DYNAMICS  (Incremental Updates)         │
│  · Stocks: EV_adoption, Grid_load, Emissions                       │
│  · Flows: Computed on events (not continuous ODE)                  │
│  · Data assimilation: Kalman-like from MQTT/IoT sensors            │
│  · Feedback controllers: Carbon budget → Policy stringency         │
│  · Domain stocks configurable via YAML at runtime                  │
└────────────────────────────────────────────────────────────────────┘
```

### Event Bus Deployment Modes

The event bus is the integration seam between simulation and production. It supports three modes, switchable via configuration alone — no code changes required:

| Mode | Backend | Use Case |
|---|---|---|
| 1 — Pure Simulation | `InMemoryEventBus` | All development and offline research runs |
| 2 — Simulation + Live Services | `MicroserviceEventBus` with per-EventType routing | Integration testing; partial digitisation deployments |
| 3 — Pure Production | `MicroserviceEventBus` fully routed | Live Digital Twin against real infrastructure |

**Mode 2 is not a stepping stone — it is a permanent operational mode.** In any real-world deployment, not all infrastructure will be digitised at day one. The fallback to `InMemory` for unimplemented services is a durable feature, not scaffolding.

---

## Key Components

### 1. BDI Agent System

**Beliefs** — what agents know (with confidence levels that decay):
- Factual: "Train takes 30 minutes"
- Normative: "I should reduce emissions"
- Epistemic: "Others think public transport is good"
- Temporal: "It's rush hour"

**Desires** — what agents want (often conflicting):
- Minimise carbon emissions
- Minimise cost
- Minimise travel time
- Maximise comfort
- Conform to social norms

**Intentions** — committed plans to achieve desires:
- Selected from plan library
- Have fallback mechanisms
- Can be dropped if commitment wanes

**Plan Library** — action sequences with preconditions:
- Expected outcomes (cost, time, CO2, comfort, etc.)
- Historical success rates
- Fallback chains

**Domain Portability:** Personas, job stories, and compatibility rules are loaded from a runtime story library, not hardcoded. A domain brief (PDF or Word document) is ingested by the Story Ingestion Service to produce a story library YAML consumed unchanged by the existing `create_realistic_agent_pool` pipeline.

### 2. System Dynamics State Manager

**Streaming SD** (not batch ODE solving):
- Incremental stock updates on events
- Continuous data assimilation (Kalman-like)
- Online parameter calibration
- Anomaly detection
- Confidence tracking

**Feedback Loops as Controllers:**
- Carbon budget → Policy stringency → Agent costs → Behaviour change
- Infrastructure capacity → Congestion → Mode attractiveness
- Social norms → Individual beliefs → Collective action

Continuous dynamics:
```
dEV_adoption/dt  = f(policy, infrastructure, social_influence)
dGrid_load/dt    = g(charging_demand, generation)
dEmissions/dt    = h(mode_shares, distances)
```

Discrete events trigger when stocks cross thresholds:
```
grid_utilization > 0.85  →  "emergency mode" event
EV_adoption > 0.30       →  unlock new charging infrastructure event
```

### 3. Social Network and Emergence

- Agent-to-agent influence
- Social cascade detection
- Habit formation (strengthens with repetition)
- Collective behaviour patterns
- Tipping point identification

### 4. Policy Transition Tester

- Live injection: Introduce policies while system runs
- Baseline capture: Record state before intervention
- Continuous monitoring: Track deviation and anomalies
- Automatic rollback: If high-severity issues detected
- A/B comparison: Multiple scenarios side-by-side

### 5. Story Ingestion Service (New — Phase 8)

An LLM-powered microservice that:
- Accepts a domain brief (PDF or Word) as input
- Extracts user personas, job stories, and compatibility rules
- Validates coverage and flags gaps
- Publishes a `StoryLibraryGenerated` event to the event bus
- The simulation subscribes and reloads without restart

This service itself runs as a microservice behind the event bus from day one — demonstrating the bus integration pattern before any real infrastructure services are connected.

---

## Key Design Principles

### Bounded Rationality
Agents do not have perfect information — only what they perceive within their radius.

### Heterogeneous Perception
- Freight operators: larger perception radius (fleet management systems)
- Personal vehicles: local observation + peer reports
- Public transit agents: centralised updates

### Trust-Weighted Information
Peer reports are weighted by trust scores based on historical accuracy.

### Graceful Degradation
If replanning fails, the agent continues with its current plan but increases perception and replanning frequency.

### Domain Agnosticism
No domain-specific logic is hardcoded. All personas, job stories, compatibility rules, spatial bounding boxes, and SD stock definitions are runtime configuration. The same binary runs Edinburgh transport, Port of Dover, NHS logistics, and airport ground operations.

### Computational Efficiency
- Event bus uses spatial indexing (R-tree) for fast radius queries
- Belief updates are incremental, not full recalculations
- Forecasting uses sampling (not all agents recompute every step)
- Event bus publish is fire-and-forget (simulation loop never blocks on network I/O)

---

## Key Design Decisions and Rationale

### 1. BDI Agents Over Simple Utility Agents
Captures conflicting goals, explains behaviour, models habits and inertia, handles plan failures gracefully, and learns from experience. More complex than utility maximisation but far more realistic.

### 2. User and Job Stories Drive Agent Behaviour
Natural specification format that maps perfectly to BDI: persona → beliefs, goal → desires, benefit → desires. Stakeholder-friendly and testable.

### 3. Lean Real-Time Digital Twin (Not Traditional ABM)
Real-time data integration, event-driven, lightweight through agent sampling. Suitable for operational decision support at 10–100× the speed of full ABM tools like MATSim or SUMO.

### 4. Custom Framework (Not PySD, Pynsim, or Mesa)
- PySD: Batch-oriented ODE solvers, no real-time capability
- Pynsim: No SD support, stagnant development
- Mesa: Synchronous, requires heavy modification for async

Custom build gives full control, async-native design, and exact fit for requirements. PySD retained for offline validation only.

### 5. OpenStreetMap
Free, open, globally portable, with mature OSMnx integration. Spatial bounding box is runtime configuration — not hardcoded to Edinburgh.

### 6. No Jupyter Notebooks
asyncio conflicts, version control noise, inability to run long simulations in the background, and debugger limitations. Rich CLI for interactive exploration; Streamlit for dashboards.

### 7. Multi-Modal Transport
Freight (road, rail, ship, air), passengers (car, EV, bus, rail, bike, walk, taxi, rideshare), infrastructure (charging, transit stops, bike lanes), and last-mile (micro-mobility, walking).

### 8. C++ Hybrid — Deferred
A Python-to-C++ hybrid layer via pybind11/nanobind is planned for the long term, offering BDI reasoning, network algorithms, SD state updates, and massive parallelisation at native speed. **This is explicitly deferred until the Python prototype is working, stable, and domain-agnostic.** Premature optimisation at the C++ boundary would introduce significant refactoring cost before the architecture is settled.

---

## Technology Stack

### Core Platform
- Language: Python 3.10+
- Concurrency: asyncio (event-driven, non-blocking)
- Development: macOS / Windows, VS Code

### Scientific Computing
- numpy: Vectorised numerical operations
- pandas / polars: Data manipulation
- scipy: Optimisation, statistics

### Agent-Based Modelling
- Custom BDI Framework: Purpose-built for transport
- networkx: Graph algorithms, agent networks

### System Dynamics
- Custom streaming SD: Event-driven stock updates
- pysd (optional): Offline validation against Vensim models

### Geospatial
- OSMnx: OpenStreetMap network extraction and analysis
- geopandas: Geospatial data structures
- shapely: Geometric operations
- folium / pydeck: Interactive and WebGL visualisation

### Visualisation and UI
- Streamlit: Interactive dashboards
- Plotly: Interactive charts
- Rich: Terminal output

### Real-Time Integration
- paho-mqtt / asyncio-mqtt: MQTT client for IoT
- redis: State caching and pub/sub (Mode 2/3 event bus)
- TimescaleDB / InfluxDB: Time-series storage

### Microservices Layer (Mode 2 / 3)
- FastAPI: Story Ingestion Service and domain configuration endpoints
- Anthropic API: LLM-powered story extraction (Story Ingestion Service)
- OpenAPI / JSON Schema: Shared event contracts between sim and real services
- Docker: Service containerisation

### Data and Configuration
- pyyaml: Configuration files and story libraries
- pydantic: Data validation and settings
- python-dotenv: Environment variables

### Development Tools
- pytest / pytest-asyncio: Testing
- black, flake8, mypy: Formatting, linting, type checking

---

## Project Structure (Current)

```
RTD_SIM/
├── agent/
│   └── story_driven_agent.py       # BDI transport agent
├── analytics/
│   └── mode_share_analyzer.py      # Mode share and transition analysis
├── simulation/
│   └── execution/
│       ├── simulation_loop.py      # Main simulation loop
│       └── simulation_runner.py    # Runner / entry point
├── ui/
│   ├── sidebar_config.py           # Streamlit sidebar + compatibility check
│   └── tabs/
│       └── analytics_tab.py        # Analytics dashboard tab
├── events/
│   └── event_bus_safe.py          # Event bus (InMemory + Safe wrappers)
├── config/                         # YAML configuration
└── outputs/                        # Logs, reports, maps
```

---

## Recommended Implementation Phases

> These phases are sequenced for **minimum disruptive refactoring**. Each phase leaves the existing working simulation fully operational. No phase requires breaking changes to the phases that precede it.

---

### Phase 7 — Simulation Core Hardening ✅ (Complete)
*Stabilise the working Edinburgh prototype before any architectural expansion.*

- Fix analytics tab crashes (0-agent run guards, Plotly column errors, palette cycling)
- Fix sidebar default selection (0/25 compatibility problem)
- Fix `simulation_loop.py` event bus call signature
- Fix `story_driven_agent.py` vehicle type extraction
- Fix `mode_share_analyzer.py` Sankey self-loop
- Add live compatibility counter to sidebar
- Add auto-expand fallback for zero-compatible configurations
- Document inline GOTCHAs (ID vs display label drift, whitelist gaps)

**Exit criterion:** 500-agent run completes with >15,000 journeys, all analytics tabs render without crash.

---

### Phase 8 — Event Bus Extension (Dual-Mode Transport Layer)
*Extend the event bus to support microservice routing without touching simulation logic.*

**8.1 — Routing Table and MicroserviceEventBus Skeleton**

Add to `event_bus_safe.py`:

- `RoutingTable`: config-driven map from `EventType` → backend (`InMemory` or service URL)
- `MicroserviceEventBus`: implements the same `publish(event)` / `subscribe(event_type, callback)` interface as `InMemoryEventBus`
- `AsyncPublishQueue`: fire-and-forget queue; background thread drains to real service; simulation loop never blocks
- Fallback: if microservice endpoint is unreachable, route to `InMemory` and log a warning

No changes to `simulation_loop.py` — the `SafeEventBus` wrapper is unchanged; only the backend is swapped via config.

**8.2 — JSON Schema Contract Enforcement**

- Define a JSON Schema per `EventType` (initially just `InfrastructureFailure`, `PolicyChange`, `WeatherDisruption`)
- Validate outbound events before publish
- This schema becomes the shared contract that prevents simulation drifting from production services

**8.3 — Deployment Mode Config**

```yaml
# config/event_bus.yaml
mode: simulation          # simulation | hybrid | production
routing:
  INFRASTRUCTURE_FAILURE: InMemory
  POLICY_CHANGE:          InMemory
  WEATHER_DISRUPTION:     InMemory
  STORY_LIBRARY_GENERATED: InMemory
```

Switching a route to a real URL (Mode 2) requires only a config edit.

**Exit criterion:** Simulation runs identically in Mode 1. Mode 2 config can be set with all routes still pointing `InMemory` — verified by test. Schema validation catches a malformed event in a unit test.

---

### Phase 9 — Story Ingestion Service
*Make the framework domain-agnostic via an LLM-powered brief ingestion pipeline.*

**9.1 — Story Ingestion API (FastAPI)**

A standalone microservice (`services/story_ingestion/`):

- `POST /ingest` — accepts PDF or Word document
- Calls Anthropic API with a structured prompt to extract:
  - User personas with belief/desire profiles
  - Job stories with situational triggers
  - Compatibility rules (rule-based, not enumerated dict)
- Returns a validated story library YAML
- Publishes `StoryLibraryGenerated` event to the event bus

**9.2 — Rule-Based Compatibility Engine**

Replace the enumerated whitelist dict with a rule engine:

```python
# Example rule: "ferry_captain compatible with any job where vehicle_type = vessel"
Rule(persona="ferry_captain", condition=lambda job: job.vehicle_type == "vessel")
```

This eliminates the fragile `[:5]` slice problem permanently and scales to arbitrary domain combinations without manual whitelist maintenance.

**9.3 — Streamlit Upload UI**

Add an "Upload Domain Brief" button to the sidebar. On upload, fires the `POST /ingest` request, waits for `StoryLibraryGenerated` event, reloads agent pool.

**Exit criterion:** Upload the Edinburgh transport brief → simulation runs with same personas. Upload a fabricated Port of Dover brief → simulation runs with port personas, no code changes.

---

### Phase 10 — Generalised Spatial Environment
*Abstract OSM loading from the Edinburgh bounding box to runtime configuration.*

- Move bbox, CRS, and transport mode registry to `config/spatial.yaml`
- `network.py` reads spatial config at startup rather than hardcoded constants
- Test with at least two bounding boxes (Edinburgh + one other) without code changes

**Exit criterion:** Change `config/spatial.yaml` bbox → simulation runs in new geography.

---

### Phase 11 — Generalised Policy Scenarios
*Move scenario definitions from hardcoded Python to uploaded YAML.*

- Policy scenario schema: name, parameter overrides, timing, rollback conditions
- `policy_engine.py` loads scenarios from `config/scenarios/` at runtime
- Streamlit UI allows upload of custom scenario YAML

**Exit criterion:** A novel policy scenario defined in YAML runs without code changes.

---

### Phase 12 — ROI Optimisation Output
*N-way scenario comparison with cost-per-tonne across time horizon.*

- Run N scenarios in parallel (async subprocess or thread pool)
- Compare: total carbon reduction, cost-effectiveness, equity effects, adoption trajectory
- Export: PDF report + CSV data per scenario
- Streamlit UI: side-by-side scenario comparison panel

**Exit criterion:** Three concurrent scenarios complete and produce comparative report.

---

### Phase 13 — Real-Time IoT Integration (Mode 2 Activation)
*Connect at least one live data feed through the event bus.*

- MQTT bridge: subscribe to a live feed (e.g., National Rail open data, TfL API, port AIS feed)
- Map inbound MQTT messages to `BaseEvent` objects
- Route through `MicroserviceEventBus` (Mode 2) — first real service connection
- SD data assimilation: Kalman-like update when live observation diverges from model

**Exit criterion:** Live feed data updates SD stocks in real time. Manual disconnection falls back to simulation gracefully.

---

### Phase 14 — Production Hardening and API Layer
*Prepare for client-facing deployment.*

- REST API (FastAPI): expose simulation control, scenario management, story ingestion
- Authentication and multi-tenancy (per-client story library isolation)
- Docker Compose: all services (simulation, story ingestion, event bus Redis backend) containerised
- CI/CD pipeline
- Performance profiling: identify bottlenecks in 1,000+ agent runs

**Exit criterion:** Deployable Docker Compose stack. API passes load test at target agent count.

---

### Phase 15 — C++ Hybrid Core (Long-Term)
*Performance optimisation via Python/C++ boundary — only after prototype is stable.*

Python layer (unchanged interface):
- Configuration and setup
- Visualisation (OSMnx, pydeck, Streamlit)
- Analysis and reporting
- Interactive CLI

C++ core (via pybind11 or nanobind):
- BDI agent reasoning (fast)
- Network path algorithms (fast)
- SD state updates (fast)
- Agent interactions (fast)
- Massive parallelisation

**This phase is deferred until Phases 8–14 are complete.** The Python prototype must be architecturally stable and domain-proven before the C++ boundary is introduced. Premature C++ migration would lock in design decisions that are still evolving.

---

## Emergent Behaviours to Observe

**Social Cascades**
One agent switches to public transport → shares positive experience → influence spreads → reaches tipping point → rapid modal shift.

**Habit Formation and Breaking**
Repeated successful actions strengthen habits. Strong habits resist change. Policy changes can break habits. New habits form around new infrastructure.

**Conflicting Goal Resolution**
- Eco-conscious commuter: high `env_concern` → prefers low-carbon despite time cost
- Business traveller: high `time_sensitivity` → uses car until train is much faster
- Budget student: high `price_sensitivity` → bikes even in bad weather
- Busy parent: high `reliability_need` → complex fallback plans

**Adaptive Learning**
Agent expects train: 30 min. Actual: 45 min (construction). Updates beliefs and plan success rates. Switches to alternative. Returns when conditions improve.

**Network Effects**
Workplace carpooling, neighbourhood EV adoption influence, school-run coordination, peer pressure for sustainable choices.

---

## Policy Interventions to Test

- **Carbon Pricing:** Variable carbon tax by mode; revenue-neutral with rebates; dynamic peak/off-peak pricing
- **Infrastructure Investment:** EV charging expansion; public transport frequency and speed; bike lane construction; last-mile connectivity
- **Regulatory Changes:** Low-emission zones; parking restrictions; modal priority (bus lanes); company car tax reforms
- **Behavioural Interventions:** Social marketing; workplace mobility programmes; gamification; default choice architecture
- **Integrated Packages:** Combined interventions with timing, sequencing, and stakeholder coordination

---

## Key Metrics and Outputs

**System-Level**
Total carbon emissions (tonnes CO2), modal shares, energy consumption by mode, infrastructure utilisation, biodiversity impact indices.

**Agent-Level**
Individual satisfaction levels, habit strength distributions, belief confidence over time, plan success rates, social influence patterns.

**Emergent Patterns**
Social cascade frequency and magnitude, tipping point identification, mode shift trajectories, habit persistence vs change, network clustering effects.

**Policy Effectiveness**
Carbon reduction per intervention, cost-effectiveness ratios, public satisfaction impact, equity and accessibility effects, implementation feasibility.

---

## Key Concepts Glossary

| Term | Definition |
|---|---|
| BDI Architecture | Belief-Desire-Intention cognitive model for agent reasoning |
| Belief | Agent's knowledge about the world (with confidence level) |
| Desire | Agent's goals or aspirations (can be conflicting) |
| Intention | Committed plan the agent will execute |
| Plan Library | Collection of action sequences with preconditions and expected outcomes |
| System Dynamics (SD) | Macro-level modelling using stocks, flows, and feedback loops |
| Streaming SD | Event-driven SD updates (not batch ODE solving) |
| Data Assimilation | Reconciling model predictions with observations (Kalman-like) |
| Digital Twin | Real-time virtual replica synchronised with physical system |
| Lean Digital Twin | Lightweight, event-driven version optimised for speed |
| Social Cascade | Behaviour spreading virally through social network |
| Habit Formation | Strengthening of behavioural patterns through repetition |
| Policy Injection | Introducing interventions while simulation is running |
| Transition Testing | A/B testing of policy scenarios |
| Modal Shift | Change in transport mode usage patterns |
| User Story | "As a [persona], I want [goal] so that [benefit]" |
| Job Story | "When [situation], I want [motivation], so I can [outcome]" |
| Story Library | Runtime domain configuration: personas, job stories, compatibility rules |
| Routing Table | Config-driven map from EventType to InMemory or microservice URL |
| Fire-and-Forget | Async publish pattern: simulation loop never blocks on network I/O |
| Domain Agnostic | Framework loads domain config at runtime; no domain-specific code |

---

## Future Enhancements

**Short-term**
- Machine learning for parameter calibration
- Multi-region coordination
- Enhanced biodiversity impact modelling

**Medium-term**
- Cloud deployment (AWS / Azure)
- API for external integration
- Mobile app for data collection

**Long-term**
- Multi-city coordination
- International freight corridors
- Climate scenario integration
- Economic impact modelling
- C++ hybrid core for production-scale performance (Phase 15)

---

*Last revised: March 2026 — incorporates Phase 7 completed fixes, event bus dual-mode architecture, domain-agnostic design decisions, and revised phase sequencing.*
