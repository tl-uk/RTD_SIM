# RTD_SIM — Session Handoff Document
**Date:** 2026-03-20 | **Version:** v0.10.0 | **Repo:** https://github.com/tl-uk/RTD_SIM

---

## What to say to Claude (new chat)

**Message 1 — paste verbatim, upload this file:**
> "I am continuing development of RTD_SIM, a BDI + System Dynamics digital twin for transport decarbonisation. This document is your handoff briefing. Please read it fully before responding."

**Message 2 — the active bug:**
> "The Social Influence Network in the Agent Cognition tab renders nodes but zero edge lines, even though the simulation log confirms 500 agents and 2050+ ties. Please fix the edge rendering loop in `ui/tabs/cognition_tab.py` — the exact fix is in the handoff doc under 'Current Active Bug'."

Upload with Message 2: **your current `cognition_tab.py`**

---

## Project Overview

**RTD_SIM** — Real-Time Transport Decarbonisation Simulator  
**Stack:** Python 3.10+, asyncio, OSMnx, Streamlit, pyvis, SHAP, scikit-learn, OLMo 2 via Ollama  
**Location:** `/Users/theolim/AppDev/RTD_SIM/`  
**Run:** `streamlit run ui/streamlit_app.py`  
**Ollama:** `ollama serve` (OLMo 2 13B, Apache 2.0, ~8GB)

**Architecture:**
- BDI agents (Beliefs, Desires, Intentions) with Bayesian belief updating and Markov habit formation
- Streaming System Dynamics (logistic growth + feedbacks, data-assimilated stocks)
- Homophily social network (500 agents, ~2050 ties per run)
- Story-driven agents: user stories × job stories (whitelist-filtered combinations)
- Three-tier LLM fallback: OLMo 2 → static YAML seed library → Anthropic Claude
- Phase 7: Temporal engine, synthetic events, combined policy scenarios

---

## Phase Status

| Phase | Status | Description |
|-------|--------|-------------|
| 1–7 | ✅ Complete | Core BDI+SD simulation, OSM routing, story agents, social network, temporal engine, synthetic events |
| 8 | ✅ Complete | Analytics, SHAP, sensitivity analysis, SD validation |
| 9 | ✅ Complete | Story ingestion service, OLMo 2 integration (code delivered, **OLMo testing pending**) |
| 10 | ❌ Not started | Generalised spatial environment + ODTP containerisation (revised scope — see below) |
| 10b | ❌ Not started | New agent types: FreightOperatorAgent, FerryPassengerAgent, PolicyAgent + central MODES registry |
| 11–12 | ✅ Complete | Policy diagnostics, combination report, agent combinations |
| 13 | ❌ Not started | Digital twin federation: Eclipse Ditto real-time layer + ODTP batch layer (revised scope — see below) |

---

## Current Active Bug — Cognition Tab Network Edges

**File:** `ui/tabs/cognition_tab.py` → `_render_influence_network()`

**Root cause:** `node_meta` is built from `agents[:40]` (8% of 500 agents). The edge guard requires BOTH endpoints in `node_meta`. Since each agent has ~8 ties and 92% of neighbours are outside the focal set, ~92% of edges are silently dropped. Nodes render; no edges appear.

**Do NOT change** `_peer_edges()` or the `node_meta` building loop.

**Find (lines 256–261):**
```python
            for e in edges:
                # Only add edges where both endpoints are in the node set.
                # Neighbors outside agents[:40] were never added to pyvis and
                # cause "non existent node" NetworkXError.
                if e['source'] in node_meta and e['target'] in node_meta:
                    net.add_edge(e['source'], e['target'], width=1.0)
```

**Replace with:**
```python
            # Ghost-node pass: add small grey unlabelled nodes for targets
            # outside the focal set — avoids "non existent node" crash while
            # showing the actual peer connections.
            ghost_ids: set = set()
            for e in edges:
                if e['source'] not in node_meta:
                    continue
                if e['target'] in node_meta or e['target'] in ghost_ids:
                    continue
                ghost_label = e['target'].rsplit('_', 2)[0][-22:]
                net.add_node(
                    e['target'],
                    label='',
                    title=f"<span style='font-size:11px'>{ghost_label}</span>",
                    color='#9e9e9e',
                    size=5,
                )
                ghost_ids.add(e['target'])

            # Edge pass: source must be focal; target must be focal or ghost
            for e in edges:
                if e['source'] not in node_meta:
                    continue
                if e['target'] not in node_meta and e['target'] not in ghost_ids:
                    continue
                width = 1.5 if e['target'] in node_meta else 0.7
                net.add_edge(e['source'], e['target'], width=width)
```

**Also update pyvis physics options (lines 233–240):**
```python
            net.set_options("""
            {
              "physics": {
                "stabilization": {"iterations": 150},
                "barnesHut": {"gravitationalConstant": -3000, "springLength": 120}
              },
              "nodes": {"shape": "dot", "scaling": {"min": 10, "max": 24}},
              "edges": {"color": {"opacity": 0.5}, "smooth": {"type": "continuous"}},
              "interaction": {"hover": true, "tooltipDelay": 100}
            }
            """)
```

---

## Pending Patches — Apply in Order

### 🔴 High Priority

**1. `simulation_loop.py` — Move `record_step()` outside all guards**

`record_step` is nested inside `if agents and policy_impact_analyzer and policy_engine:` → `if network and SOCIAL_AVAILABLE:` → `if influence_system and not agent.state.arrived:`. This means it fires for almost no agents. Find the current block (lines ~933–936) and move it directly before `agent_states.append()`, outside all three guards:

```python
        # Phase 3: Markov record_step — unconditional per step
        _mc = getattr(agent, 'mode_chain', None)
        if _mc is not None:
            try:
                _mc_mode = getattr(agent.state, 'mode', None)
                if _mc_mode:
                    _mc_sat = satisfaction_by_mode.get(_mc_mode, [0.6])[-1] \
                        if satisfaction_by_mode.get(_mc_mode) else 0.6
                    _mc.record_step(_mc_mode, _mc_sat)
            except Exception as _mce:
                logger.debug("Markov record_step failed: %s", _mce)
```

**2. `analytics/shap_analysis.py` — Fix two feature formulas**

In `prepare_shap_features()`:

```python
# Bug A: social_effect uses s*EV² — WRONG (no saturation)
# Fix:
'social_effect': social_feedback * ev_adoption * (1.0 - ev_adoption / K) if K > 0 else 0,

# Bug B: infrastructure_effect applies EV*(1-EV/K) — WRONG (infra is flat)
# Fix:
'infrastructure_effect': infra_feedback * entry.get('infrastructure_capacity_normalised', 0.5),
```

Also add to `system_dynamics.py` history dict in `update()`:
```python
'infrastructure_capacity_normalised': self.state.infrastructure_capacity_stock / 100.0,
```

### 🟡 Medium Priority

**3. `agent/story_driven_agent.py` — Phase 3 Gap 1**

After line 109, add:
```python
self.agent_context['mode_chain'] = self.mode_chain
```

**4. `agent/bdi_planner.py` — Phase 3 Markov habit discount**

In `cost()` method, before the stochastic noise line:
```python
habit_discount = 0.12 * prior.get(mode, 0.0)
total_cost *= (1.0 - habit_discount)
```

**5. `agent/contextual_plan_generator.py` — OLMo wiring (4 changes)**

See `PATCH_contextual_plan_generator_llm.py` in outputs for exact locations.

**6. `system_dynamics.py` — Expose infrastructure capacity in history**

In `update()` → `self.history.append({...})`, add:
```python
'infrastructure_capacity_normalised': self.state.infrastructure_capacity_stock / 100.0,
'ev_growth_rate_r': self.state.ev_growth_rate_r,
'ev_carrying_capacity_K': self.state.ev_carrying_capacity_K,
```

---

### Cognition Tab — Edge Rendering (this session)
- **Root cause:** `node_meta` was built from `agents[:40]` (list-index order) while `_peer_edges()` selected `focal_agents` by within-story connection count — two different sets. Every edge hit `if e['source'] not in node_meta: continue`, so `ghost_ids` stayed empty and no edges rendered.
- **Fix:** Call `_peer_edges()` first; derive `focal_source_ids = dict.fromkeys(e['source'] for e in edges)`; build `node_meta` from those IDs via `agent_by_id` dict. focal set now always mirrors what `_peer_edges()` selected.
- **Tooltip fix:** pyvis/vis.js escapes arbitrary HTML in `title` attribute as raw text. Replaced `<table>` HTML with `"\n".join(tip_lines)` plain string. Same fix applied to ghost node tooltips (was `<span style=...>`). **Rule: pyvis titles are plain strings only.**
- **Label fix:** Removed canvas labels entirely (`label=' '`). Graph is too dense (40 focal + ~80 ghost nodes in 480px). Tooltip on hover carries full agent ID + metadata.

### Social Network — Cross-Persona Bridging Ties (this session)
- **Root cause:** `_build_homophily` sorted all candidates by desire similarity, took top `k*2`, all same-persona. Cross-persona agents never entered the selection pool. Result: isolated per-persona star graphs, zero inter-group edges.
- **Fix in `social_network.py`:** `_build_homophily` now splits per agent into `same_pool` / `cross_pool`, allocates `cross_slots = round(k * cross_persona_prob)` from cross pool. Default `cross_persona_prob=0.25`.
- **Fix in `network_setup.py`:** `setup_social_network` reads `config.cross_persona_prob` (default 0.25) and passes to `build_network`. Logged in both influence paths.
- **TODO:** Add `cross_persona_prob` to `SimulationConfig` and sidebar slider.

---



### Simulation Log Capture
- `ui/log_capture.py` — routes all `logging.getLogger()` to `RTD_SIM/logs/simulation_YYYYMMDD_HHMMSS.log`
- `streamlit_app.py` — initialises in session state, shows log path in sidebar

### Markov Logging (`simulation_loop.py`)
- Periodic Markov snapshot every 50 steps, end-of-run summary table

### Sidebar — Story Selection Select All (`sidebar_config.py`)
- `_render_story_selection()` moved outside `st.form()`
- Two-run cycle: sentinel `"── Select All ──"` → `_pending` flag → `st.rerun()` → key pre-populated
- No `default=` on keyed `st.multiselect` (Streamlit conflict rule)

### Route Diversity Sidebar Control
- `_render_advanced_features()`: `🛣️ Route Diversity` expander, toggle + radio, wired into `SimulationConfig()`

### Cognition Tab — Tooltip Fix
- `<br/>` → `<table><tr><td>` (vis.js serialisation issue)
- CSS injection for centering in iframe

### Cognition Tab — Markov Habit Table
- "Warming up" table when no habits yet; `active_modes` broadened to include `mode_history`

### Peer Signal Fix (`bayesian_belief_updater.py`)
- `SocialNetwork.get_agent()` replaced with `agent_index` dict
- `rebuild_agent_index(agents)` called once before step loop

### System Dynamics — Validation (`sd_validation_metrics.py`)
- Old: closed-form logistic → MAE 42%, R²=-1
- New: one-step-ahead `predicted[t+1] = actual[t] + flow[t]` → MAE ~3%

### System Dynamics — Social Term (`system_dynamics.py`)
- `s*EV*(1-EV)` → `s*EV*(1-EV/K)` — peak now at EV=K/2, responsive to user's K slider

### System Dynamics — Chart (`system_dynamics_tab.py`)
- Three injection points (A/B/C): closed-form logistic replaced with one-step-ahead from `ev_adoption_flow`

### Sensitivity Analysis — Four Bugs Fixed (`sd_derivative_analysis.py`, `sensitivity_analysis_tab.py`)
- `'total': 1.0` filtered from `max()` (Dominant Driver was always "Total")
- `df/d(social)`: `EV*(1-EV)` → `EV*(1-EV/K)` (ε(social): 0.224→0.203)
- `df/dK`: missing social contribution added — `(r+s)*EV*(EV/K²)` (ε(K): 0.171→0.273, +60%)
- `compute_feature_contributions` social term corrected

---

## Phase 9 — OLMo Testing (NOT YET DONE)

### Prerequisites
```bash
ollama serve           # terminal 1 — leave running
ollama pull olmo2:13b  # one-time, ~8GB
```

### Quick connectivity test (5 seconds)
```bash
cd /Users/theolim/AppDev/RTD_SIM
python -c "
from services.llm_client import LLMClient
client = LLMClient()
print('Ollama reachable:', client.is_available())
if client.is_available():
    r = client.complete('Say hello in JSON: {\"message\": \"...\"}', temperature=0.1)
    print('Response:', r)
"
```

### Enable OLMo in simulation

In `agent/agent_creation.py` line 62:
```python
# Change from:
plan_generator = ContextualPlanGenerator(llm_backend="rule_based")
# To:
plan_generator = ContextualPlanGenerator(llm_backend="olmo")
```

### Sidebar settings for OLMo testing (keep minimal — LLM adds ~2-5s per agent)
```
Agents:   10
Steps:    50
Personas: eco_warrior, concerned_parent
Jobs:     morning_commute, shopping_trip
OSM:      ON
Everything else: OFF
```

### What to watch in the log
Each agent should show:
```
INFO LLM plan extraction: objective=minimize_carbon, fixed=False, critical=True — school run context
```

- `CPG extraction failed` → OLMo returned unparseable output — check log for raw response
- `OLMo failed ... using rule_based fallback` → Ollama not reachable

### Recommended test order
1. Quick connectivity test above
2. 10 agents / 50 steps with `llm_backend="olmo"` — confirm LLM extraction log lines
3. 50 agents / 150 steps with `llm_backend="rule_based"` — confirm `mode_chain.summary()` populated
4. 100 agents / 200 steps full run — confirm Analytics tab shows smooth belief drift

### Bayesian belief updater (already wired — verify visually)
```
Agents:   100
Steps:    200   ← beliefs update every 5 steps; need enough cycles
Social:   ON
Analytics: ON
```
Look at mode share over time in Analytics tab. Correct behaviour: gradual drift in EV adoption curve (Bayesian weight smoothing). Incorrect: sudden step change (suggests direct `agent.state.mode` overwrite still occurring).

### OLMo Test Results — TO BE FILLED IN
```
Connectivity test:  [ PASS / FAIL ]
LLM extraction:     [ confirmed / CPG extraction failed / OLMo fallback ]
Raw response sample:
  (paste first LLM log line here)
Latency per agent:  ~__ s
Plan quality notes:
  (did extracted objective/mode match job story context?)
Decision:
  [ proceed with olmo backend / stay rule_based / hybrid threshold ]
```
**If OLMo works:** enables LLM-driven plan generation for FreightOperatorAgent,
FerryPassengerAgent, and PolicyAgent in Phase 10b without bespoke Python rules per type.
**If OLMo fails:** each new agent type needs explicit rule-based plan logic — significantly
more implementation work per agent type.

---

## Phase 10 — Generalised Spatial Environment + ODTP Containerisation (Revised Scope)

### Background
RTD_SIM's full ambition is UK-wide: Dover→Aberdeen freight corridors, CalMac ferry routes, Highlands & Islands communities, real-time policy agent behaviour from DfT and local authorities. "Abstract the Edinburgh bbox" is necessary but not sufficient — done naively it just makes the wrong architecture configurable. Phase 10 must lay the foundation for national-scale operation.

### 10a — Spatial generalisation (surgical, do first)

**Hardcoded Edinburgh locations to remove — four files:**

| File | Line | Hardcoding |
|------|------|-----------|
| `agent_creation.py` | 138 | `west, south, east, north = -3.35, 55.85, -3.05, 56.00` — OD bbox fallback |
| `environment_setup.py` | city-scale else branch | `infrastructure.populate_edinburgh_chargers()` |
| `infrastructure_manager.py` | `populate_edinburgh_chargers()` | Delegates to Edinburgh-specific subsystems |
| `simulation_config.py` | defaults | `place="Edinburgh, UK"`, `latitude=55.9533`, `longitude=-3.1883` |

**Fixes:**
- Add `SimulationConfig.get_bbox() → (west, south, east, north)` — reads `extended_bbox`, else derives from loaded graph extent, else raises (no silent Edinburgh fallback)
- Add `InfrastructureManager.populate_chargers_from_bbox(bbox, num_public, num_depot)` — generic placement. Keep `populate_edinburgh_chargers()` as one-line backward-compat wrapper
- `agent_creation.py` line 138: replace hardcoded bbox with `config.get_bbox()`
- `environment_setup.py`: replace Edinburgh infrastructure call with `populate_chargers_from_bbox(config.get_bbox(), ...)`
- `simulation_config.py`: remove Edinburgh lat/lon defaults; `place` default becomes `None` (force user to specify)

**Tiled graph loading (required for national scale):**
- Single OSM graph for all of UK will not fit in memory (~5M nodes, ~12M edges)
- Tile by UK planning region: Scotland, Northern England, Midlands, SE England, Wales, Northern Ireland
- Load only tiles that intersect the active corridor
- Cache by bbox hash (already partially implemented in `GraphManager`)
- `SpatialEnvironment` gains `load_regional_tiles(corridor_bbox)` — loads and stitches adjacent tiles

**Intermodal network stitching:**
- Road + rail + ferry must be a unified graph with transfer nodes at ports, stations, terminals
- Transfer nodes carry penalty costs (boarding time, schedule wait, ticket cost)
- Required before FreightOperatorAgent and FerryPassengerAgent can be built (Phase 10b)
- OSM has railway and ferry route data — use `network_type='all'` and filter by edge type

### 10b — ODTP Containerisation (do after 10a)

RTD_SIM is a natural ODTP component: Python, Streamlit, Docker-containerisable, clear parameter interface. ODTP provides the research reproducibility and publication layer (scenario runs, S3 snapshots, Zoo publication). Wrapping as an ODTP component forces the config API to be fully serialisable — which directly enforces 10a's spatial generalisation.

**Files to create:**
```
odtp-rtd-sim/
├── Dockerfile              # Python 3.10, OSMnx, Streamlit, all deps
├── requirements.txt
├── odtp.yml                # Component metadata + parameter schema
├── .env.dist               # All SimulationConfig params as env vars
├── app/
│   └── app.sh              # Clone RTD_SIM, run streamlit
└── odtp-component-client/  # Git submodule from odtp-org/odtp-component-template
```

**`odtp.yml` parameter schema must cover:**
- `REGION_BBOX` — `west,south,east,north` as comma-separated string
- `REGION_NAME` — human-readable label
- `NUM_AGENTS`, `NUM_STEPS`
- `CROSS_PERSONA_PROB` — social network bridging (0.0–0.6)
- `SD_GROWTH_RATE_R`, `SD_CARRYING_CAPACITY_K`, `SD_SOCIAL_INFLUENCE`, `SD_INFRA_FEEDBACK`
- `ENABLE_SOCIAL`, `ENABLE_INFRASTRUCTURE`, `ENABLE_ROUTE_DIVERSITY`
- `LLM_BACKEND` — `rule_based` | `olmo` | `claude`
- `USER_STORIES`, `JOB_STORIES` — comma-separated lists

**Port mapping:** Streamlit runs on 8501. ODTP docker run must include `-p 8501:8501`.

**Input/output:**
- `/odtp/odtp-input/` — OSM cache, YAML story files, scenario configs, sensor snapshots
- `/odtp/odtp-output/` — simulation logs, time series CSV, SHAP outputs, network snapshots, Ditto protocol JSON

**Publish to ODTP Zoo** after first successful containerised run. Use semantic versioning: `v0.10.0` for first containerised release.

### 10c — New Agent Types (Phase 10b in roadmap)

Required before national-scale corridors are meaningful. Each agent type is a new BDI structure, not just a new persona in `StoryDrivenAgent`.

**Central MODES registry — do this first:**
```python
# simulation/config/modes.py  ← new file
MODES = {
    'walk':      {'network': 'walk',  'emissions_g_km': 0},
    'bike':      {'network': 'bike',  'emissions_g_km': 0},
    'car':       {'network': 'drive', 'emissions_g_km': 170},
    'ev':        {'network': 'drive', 'emissions_g_km': 0},
    'bus':       {'network': 'drive', 'emissions_g_km': 82},
    'rail':      {'network': 'rail',  'emissions_g_km': 41},
    'ferry':     {'network': 'ferry', 'emissions_g_km': 115},
    'hgv':       {'network': 'drive', 'emissions_g_km': 900},
    'ev_hgv':    {'network': 'drive', 'emissions_g_km': 0},
    'av':        {'network': 'drive', 'emissions_g_km': 0},
}
```
Every mode string across BDI planner, SHAP features, Markov chains, SD social term must reference this dict. No ad hoc string literals.

**FreightOperatorAgent:**
- Depot-anchored (fixed origin = depot location)
- Vehicle-typed (HGV, van, refrigerated — from job story)
- Route-constrained by HGV restrictions in OSM edge attributes
- Cost-minimising BDI: fuel/charge cost dominates over time and comfort
- Charging behaviour: depot overnight + opportunity charging at motorway services

**FerryPassengerAgent:**
- Schedule-constrained — boarding only at scheduled departure times
- Island origin/destination — CalMac routes, Orkney, Shetland, Hebrides
- Captive mode: ferry is the only option; BDI choice is *to/from* the ferry terminal
- Emergent behaviour: full ferry = cascading delay affecting island communities

**PolicyAgent (base class):**
- Not a traveller — acts on the environment, not on routes
- DfT: adjusts subsidies, speed limits, EV incentives as beliefs about adoption change
- Local authority: manages infrastructure investment within budget constraint
- Network Rail / port authority: responds to demand signals with capacity changes
- BDI structure: beliefs = current adoption/congestion metrics; intentions = policy actions

---

## Phase 13 — Digital Twin Federation (Revised Scope)

### Vision
RTD_SIM is itself a digital twin, not a tool that feeds one. It must federate with other twins (port authority, Network Rail, National Grid, local authority smart city platforms) in real-time and publish reproducible batch runs for research.

### Two-layer architecture

```
┌─────────────────────────────────────────────────────┐
│  ODTP (batch / research / reproducibility layer)    │
│  Parameterised scenario runs, S3 snapshots,         │
│  Zoo publication, federation via shared outputs     │
└────────────────────┬────────────────────────────────┘
                     │ checkpoint snapshots
┌────────────────────▼────────────────────────────────┐
│  RTD_SIM simulation loop  (real-time step clock)    │
│  BDI agents read/write Ditto Thing state each step  │
└────────────────────┬────────────────────────────────┘
                     │ Ditto Protocol (HTTP/WebSocket)
┌────────────────────▼────────────────────────────────┐
│  Eclipse Ditto  (real-time twin state layer)        │
│  Thing = agent | charger | ferry | policy actor     │
│  Live channel ← MQTT sensor feeds                   │
│  Twin channel = persisted state                     │
│  W3C WoT = federation with external twins           │
└────────────────────┬────────────────────────────────┘
                     │ W3C Web of Things / NGSI-LD
         ┌───────────┴───────────┐
         ▼                       ▼
  Port authority twin     Network Rail twin
  (CalMac capacity,        (timetable, capacity,
   ferry schedules)         electrification status)
```

### Eclipse Ditto — key facts
- Apache 2.0, Eclipse Foundation-backed, Docker/Kubernetes native
- **Thing model:** each RTD_SIM agent = one Ditto Thing with persistent state
- **Live channel:** real sensor data (EV charger occupancy, ferry capacity, traffic counts) updates Thing state via MQTT — simulation reads back as agent belief updates
- **Twin channel:** persisted representation — decoupled from live feed rate
- **W3C WoT:** standards-based federation with any compliant twin platform
- **Kafka integration:** connects to FIWARE/NGSI-LD platforms used by UK local authorities

### OpenTwins
- Builds on Eclipse Ditto; adds FMI simulation integration and 3D visualisation
- RTD_SIM's System Dynamics component could wrap as an FMI model inside OpenTwins
- 3D layer would render UK transport network with live agent positions
- **Currently pre-production** — suitable for research, not production deployments yet
- Watch: https://github.com/ertis-research/OpenTwins

### What NOT to use
- **NDTP (National Digital Twin Programme):** API specifications for data exchange contracts between existing systems. Not a twin platform — no twin state management, no real-time sync, no simulation layer. Useful only for interoperability contracts if RTD_SIM needs to talk to NDTP-compliant systems.
- **FIWARE as primary platform:** Smart city data exchange ecosystem, not a simulation platform. Use only as a translation layer if federating with FIWARE-based local authority twins.

### Implementation plan

**Phase 13a — Eclipse Ditto integration:**
- `SimulationConfig` → Ditto Thing Description (JSON-LD schema). Design this in Phase 10 — cheap now, expensive to retrofit
- Simulation loop step output serialisable to Ditto Protocol JSON
- `DittoSyncLayer` class: pushes agent state to Ditto at each step; pulls sensor updates back into agent beliefs
- MQTT subscriber replaces current synthetic event generator when broker available (Paho-MQTT)
- Docker Compose: RTD_SIM container + Ditto container + MQTT broker (Mosquitto) as single stack

**Phase 13b — Federation:**
- W3C WoT Thing Descriptions for RTD_SIM's externally visible Things (corridors, policy actors, infrastructure)
- CalMac ferry schedule integration (real timetable data → ferry agent schedules)
- National Grid carbon intensity API → SD grid_carbon_intensity parameter updated in real-time
- OpenTwins FMI wrapper for System Dynamics component (optional, research milestone)

**Phase 13c — ODTP + Ditto bridge:**
- ODTP checkpoint: snapshot Ditto twin state to S3 at scenario boundaries
- Reproducible playback: restore Ditto state from S3 snapshot to replay a past run
- Zoo publication of complete RTD_SIM component with Ditto integration

---

## Key Architecture Rules (for Claude)

### SD Equation (corrected)
```
dEV/dt = r·EV·(1 - EV/K)              ← logistic
        + (charger_count/100)·infra_s  ← FLAT infrastructure boost (no EV term)
        + s·EV·(1 - EV/K)              ← social (peaks at EV=K/2, not 0.5)
```

### Validation — one-step-ahead only
`predicted[t+1] = actual[t] + flow[t]`. Never use closed-form logistic. Stocks are data-assimilated from agents; the SD only predicts the incremental flow.

### Under-Prediction is the Research Finding
SD predicts more growth than BDI agents achieve. The gap quantifies how BDI cognitive constraints (mode competition, Markov habits, routing friction, charger bottlenecks) suppress adoption vs macro-level predictions. Not a bug.

### Social Peak
`s·EV·(1-EV/K)` peaks at `EV = K/2`. K=0.80 → peak at 40%. Never use `s·EV·(1-EV)` — that always peaks at 50% regardless of K.

### Streamlit Rules
- Never use `default=` on a `st.multiselect` that also sets its key via `session_state`
- Widgets inside `st.form()` cannot trigger reruns — move interactive widgets outside the form
- Two-run cycle for programmatic multiselect: set pending flag → `st.rerun()` → pre-populate key before widget renders

### Social Network Topology Rules
- `_calculate_similarity()` uses desire-vector Euclidean distance. Desires are persona-initialised, so same-persona similarity ≈ 0.9, cross-persona ≈ 0.2.
- **Never use an unmodified homophily builder** — the top-`k*2` candidate pool is always same-persona, producing isolated per-persona stars with zero inter-group edges. Real adoption diffusion requires cross-persona bridging ties.
- **Fix:** `_build_homophily` splits candidates into `same_pool` and `cross_pool` and allocates `cross_persona_prob` (default 0.25) of each agent's `k` slots from `cross_pool`. Exposed via `config.cross_persona_prob` and passed through `setup_social_network` → `build_network`.
- **TODO (Phase 10):** Add `cross_persona_prob` slider to sidebar (0.0 = pure homophily / echo chambers, 1.0 = random). Sweeping this is a policy variable — a socially integrated city diffuses EV adoption faster.
- The SD social term `s·EV·(1-EV/K)` aggregates the whole population. If BDI peer signal stays siloed within personas, the two models describe different social structures — the gap between them loses research validity.


### Pyvis Rules
- Never use `<br/>` in `title` strings — use `<table><tr><td>` rows
- **Do NOT use `<table>` or any HTML in `title` strings either — pyvis/vis.js escapes arbitrary HTML as raw text in the tooltip popup. Use plain `"\n".join(lines)` strings only.**
- Always add a node to pyvis before adding any edge referencing it (ghost nodes fix)
- CSS inject into `<head>` after `net.save_graph()` to centre the iframe canvas

### Peer Signal
`BayesianBeliefUpdater.rebuild_agent_index(agents)` must be called once before the step loop. Replaces the broken `network.get_agent()` with a plain dict lookup.

### SHAP Feature Formulas (correct versions)
```python
'social_effect':        s * EV * (1 - EV/K)          # NOT s*EV² or s*EV*(1-EV)
'infrastructure_effect': cap * infra_strength          # NOT infra*EV*(1-EV/K) — flat!
'logistic_term':        r * EV * (1 - EV/K)          # correct
'saturation_ratio':     EV / K                        # correct
'distance_to_capacity': K - EV                        # correct
```

All K-dependent features must read `entry.get('ev_carrying_capacity_K', 0.80)` from history — never hardcode K=0.80.
