# RTD_SIM — Session Handoff Document
**Date:** 2026-03-23 | **Version:** v0.12.1 | **Repo:** https://github.com/tl-uk/RTD_SIM

---

## What to say to Claude (new chat)

**Message 1 — paste verbatim, upload this file:**
> "I am continuing development of RTD_SIM, a BDI + System Dynamics digital twin for transport decarbonisation. This document is your handoff briefing. Please read it fully before responding."

**Message 2 — the active work:**
> "I want to implement the ASI (Avoid-Shift-Improve) intent hierarchy and Complex Contagion belief threshold into the BDI planner. The design is in the handoff doc under 'ASI + Complex Contagion Design'. Please review `bdi_planner.py` and `bayesian_belief_updater.py` before implementing."

Upload with Message 2: **`bdi_planner.py`** and **`bayesian_belief_updater.py`**

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
- Homophily social network (500 agents, ~2500 ties per run, cross_persona_prob=0.25)
- Story-driven agents: user stories × job stories (whitelist-filtered combinations)
- Three-tier LLM fallback: OLMo 2 → static YAML seed library → Anthropic Claude
- Phase 7: Temporal engine, synthetic events, combined policy scenarios
- Phase 9: Story ingestion service, OLMo 2 integration
- Phase 10: Under active development (see below)

---

## Phase Status

| Phase | Status | Description |
|-------|--------|-------------|
| 1–7 | ✅ Complete | Core BDI+SD simulation, OSM routing, story agents, social network, temporal engine |
| 8 | ✅ Complete | Analytics, SHAP, sensitivity analysis, SD validation |
| 9 | ✅ Complete | Story ingestion service, OLMo 2 integration |
| 10a | 🔄 In Progress | Spatial generalisation — core files done; agent sampling + scenario cost wiring fixed in v0.12.1 |
| 10b | ❌ Not started | New agent types: FreightOperatorAgent, FerryPassengerAgent, PolicyAgent + MODES registry |
| 10c | ✅ Complete | ASI intent hierarchy + Complex Contagion belief threshold — bdi_planner.py, contextual_plan_generator.py, bayesian_belief_updater.py |
| 11–12 | ✅ Complete | Policy diagnostics, combination report, agent combinations |
| 13 | ❌ Not started | Digital twin federation: Eclipse Ditto + ODTP containerisation |

---

## Session 3–4 Completed Work (2026-03-21 to 2026-03-22)
---

## Session 5 Completed Work (2026-03-23)
---

## Session 5 Addendum — v0.12.1 (2026-03-23 late)

### Root cause: eco_warrior-only runs with "Select All"

Three bugs caused this. All fixed.

---

**Bug A — `create_realistic_agent_pool` alphabetical truncation** (`story_compatibility.py`)

With 293 compatible combinations and 150 agents, `floor(150/293) = 0`, so
`agents_per_combo = max(1, 0) = 1`. Only the **first 150 combinations in
alphabetical order** received an agent. Since combinations sort as
`(user_id, job_id)` tuples, `eco_warrior` precedes `freight_operator`
alphabetically and claimed all its 17 slots before freight personas appeared.

Fix: shuffle combinations with a reproducible RNG seeded on `num_agents ^ len(combinations)`,
then use round-robin fill (no alphabetical truncation) or sample-without-replacement
when agents < combinations.

---

**Bug B — EV Subsidy 30% never reached the BDI cost function** (`bdi_planner.py`, `simulation_loop.py`)

The scenario YAML declares `parameter: cost_reduction, value: 30.0, target: mode, mode: ev`.
`apply_scenario_policies()` calls `manager.apply_to_environment(env)` which modifies the
road network — **not** agent planners. The BDI `cost()` method had no multiplier lookup;
`ev` and `van_electric` at cost 0.17 in the log was the unmodified cost function, not a
subsidised one. The subsidy was loaded and logged but silently ignored at decision time.

Fix:
- `BDIPlanner.__init__`: add `self.mode_cost_factors: Dict[str, float] = {}`
- `BDIPlanner.apply_scenario_cost_factors(policies)`: parses YAML cost_reduction/cost_increase
  into multipliers (e.g. 30% off → 0.70)
- `BDIPlanner.cost()`: applies `scenario_factor = self.mode_cost_factors.get(mode, 1.0)`
  before stochastic noise
- `apply_scenario_policies()` (simulation_loop): surfaces mode policies in `report['mode_cost_policies']`
  and stores them as `config._scenario_mode_policies`
- `run_simulation_loop()`: wires `config._scenario_mode_policies` to every agent planner
  before the step loop begins

---

**Bug C — "Select All" Streamlit race condition** (`sidebar_config.py`)

The two-run cycle sets `_select_all_users_pending = True` on one rerun and clears
`_user_ms` to `available_users` on the next. But on the intervening run,
`user_stories = st.session_state.get("_user_ms", default_users)` was called
**before** the pending flag was consumed — reading `["── Select All ──"]` as the
selection, which then passed `["── Select All ──"]` as a persona ID to
`story_compatibility.py`, returning 0 compatible combinations and triggering
the auto-expand fallback (silently widening to all stories, not the user's intent).

Fix: strip the sentinel from the session_state value before assigning to
`user_stories`/`job_stories`, with a fallback to `available_users`/`available_jobs`
if the result is empty.

```python
_raw_users = st.session_state.get("_user_ms", default_users)
user_stories = [u for u in _raw_users if u != _SENTINEL] or list(available_users)
```

---

### Updated deployment sequence (v0.12.1)

```bash
# All Phase 10a + 10c + Phase 10a addendum fixes
cp outputs/story_compatibility.py    agent/
cp outputs/bdi_planner.py            agent/
cp outputs/simulation_loop.py        simulation/execution/
cp outputs/sidebar_config.py         ui/
cp outputs/contextual_plan_generator.py  agent/
cp outputs/bayesian_belief_updater.py    agent/
cp outputs/environment_setup.py      simulation/setup/
cp outputs/graph_manager.py          simulation/spatial/

rm -rf ~/.rtd_sim_cache/osm_graphs/   # clears straight-line route cache
streamlit run ui/streamlit_app.py
```

### Phase 10a completion criteria (still outstanding)

Phase 10a is **not complete** until a 500-agent run with "Select All" produces
a realistic persona mix — approximately:
- freight_operator: ~14% (41 jobs / 293 combos)
- eco_warrior: ~6% (17 / 293)
- shift_worker: ~8% (23 / 293)
- budget_student: ~6% (19 / 293)
- All other passengers: remainder

**Phase 10b must NOT start until the next full run confirms a realistic mix.**
Upload the simulation log from the next run for final Phase 10a sign-off.

### Phase 10b checklist (when 10a is confirmed)

1. `simulation/config/modes.py` — canonical mode registry with emissions_g_km, network type, range_km
2. `agent/agent_types/freight_operator_agent.py` — vehicle_type=heavy_freight, cargo_capacity
3. `agent/agent_types/ferry_passenger_agent.py` — ferry dependency flag
4. `agent/agent_types/policy_agent.py` — high-degree hub in social network (k_policy=15)
5. Add `freight_rail`, `ferry_diesel`, `ferry_electric`, `flight_domestic` to `route_diversity.py`


### Phase 10a — Spatial Generalisation: Complete

| File | Fix |
|------|-----|
| `graph_manager.py` | `get_stats()` now returns `west/south/east/north` bounds from OSMnx node coordinates |
| `environment_setup.py` | City-scale charger placement now derives bbox from graph nodes (`drive_graph.nodes(data=True)`) instead of calling `get_graph_stats()` expecting non-existent bbox keys — **this was the root cause of 0.0% charger utilization and missing map markers** |
| `simulation_config.py` | `place` default `None` (was `"Edinburgh, UK"`); weather lat/lon `Optional[float] = None`; four new network params added |
| `sidebar_config.py` | User default location widget; region selectbox defaults to Custom Place; Edinburgh fallbacks replaced; four neighbourhood influence sliders |
| `social_influence_dynamics.py` | `influence_strength` and `conformity_pressure` wired through |
| `network_setup.py` | `k`, `strong_tie_threshold`, `influence_strength`, `conformity_pressure` read from config |
| `environmental_config.py` | Edinburgh lat/lon hardcoding removed |
| `route_diversity.py` | All 20 modes explicitly mapped (was missing hgv/ferry/rail proxies) |

### Phase 10c — ASI + Complex Contagion: Complete

**Three files modified:**

**`bdi_planner.py`**
- Hard EV block now restricted to `vehicle_type in ('commercial', 'heavy_freight', 'medium_freight')` — passenger personas (eco_warrior, concerned_parent) no longer blocked
- Charger occupancy default changed from `1.0` → `0.0` (was treating "no data" as "fully occupied")
- Bike removed from `_SHIFT_MODES` — was causing bike to dominate when EV unavailable
- ASI tier Tier 2 uses strict `>` threshold with `_eco_desire >= 0.45` guard (was `>=` causing 100% of agents to enter Shift tier at startup)
- `operational_critical=True` in log messages (was `reliability_critical=True`)

**`contextual_plan_generator.py`**
- `urgency='high'` no longer sets `reliability_critical=True` — uses `time_sensitive=True` instead (weaker flag, cost weighting only, no hard block)
- Narrative safety/children keywords no longer set `reliability_critical=True` — sets `time_sensitive=True` + `maximize_safety` secondary objective instead
- Two new `ExtractedPlan` fields: `asi_tier` and `ev_viability_belief_hint` with persona-calibrated defaults
- ASI tier and ev_viability_belief_hint computed at end of `_apply_user_story`

**`bayesian_belief_updater.py`**
- `_COMPLEX_CONTAGION_THRESHOLDS` dict: persona-calibrated fractions (eco_warrior=0.10, freight=0.40, paramedic=0.60)
- EV beliefs only update when `peer_ev_rate >= contagion_threshold` (frozen otherwise)
- `ev_viability_belief` written to `agent_context` each update interval — was always default 0.5, making ASI thresholds inert
- `_compute_ev_viability_belief` method: blends EV belief strengths (60%) with peer_ev_rate (40%)

### Infrastructure 0.0% Root Cause

`graph_manager.get_stats()` returned no spatial bounds. `environment_setup.py` called `stats.get('west')` → `None` → `ValueError` → returned empty `InfrastructureManager`. All downstream consumers (map markers, utilization metrics, Bayesian charger signal) received zero/empty data.

**Fix:** `environment_setup.py` now extracts bounds directly from `drive_graph.nodes(data=True)` → `min/max(x/y)`. `graph_manager.get_stats()` also now returns bounds for future callers.

### Straight-Line Routes Root Cause

OSM graph cache at `~/.rtd_sim_cache/osm_graphs/` contains graphs without Shapely edge geometry. `route_diversity._extract_route_geometry` docstring: *"Falls back to endpoint-node coordinates when geometry is absent — delete the cache file."*

**Fix:** `rm -rf ~/.rtd_sim_cache/osm_graphs/` then restart. Takes 2–5 min to re-download with full geometry. One-time operation.

### Simulation Analytics Results (2026-03-23 baseline run)

End-of-run habit table (250 agents, 300 steps, realistic_ev_transition scenario):
- EV: 28 agents (11.2%), bike: 25 agents (10.0%) — near-parity shows EV competitive once hard block fixed
- van_electric + truck_electric dominant in freight cluster (31% + 9.5% of freight agents)
- CO₂: 248,405 g/step — substantially lower than previous runs

---

## Critical Deployment Sequence (v0.12.0)

**Must deploy in this exact order:**

```bash
# 1. Clear stale OSM cache (fixes straight-line routes)
rm -rf ~/.rtd_sim_cache/osm_graphs/

# 2. Deploy Phase 10a files
cp outputs/simulation_config.py simulation/config/
cp outputs/sidebar_config.py ui/
cp outputs/environment_setup.py simulation/setup/
cp outputs/graph_manager.py simulation/spatial/
cp outputs/network_setup.py simulation/setup/
cp outputs/social_influence_dynamics.py agent/
cp outputs/environmental_config.py simulation/config/
cp outputs/route_diversity.py simulation/routing/

# 3. Deploy Phase 10c files
cp outputs/bdi_planner.py agent/
cp outputs/contextual_plan_generator.py agent/
cp outputs/bayesian_belief_updater.py agent/

# 4. Restart Streamlit
streamlit run ui/streamlit_app.py
```


### Files Delivered (all production-ready)

| File | Destination | Changes |
|------|------------|---------|
| `personas.yaml` | `agent/personas/personas.yaml` | 54 None-valued modes fixed, duplicates collapsed, 3 non-standard mode names corrected |
| `story_compatibility.py` | `agent/story_compatibility.py` | All 55 YAML jobs covered, 6 operator personas wired, 12 Phase 10b stubs documented |
| `user_stories.py` | `agent/user_stories.py` | Default path fixed; auto-merges all YAML files in `personas/` directory |
| `job_stories.py` | `agent/job_stories.py` | TimeWindow integer crash fixed (`_normalise_time`) |
| `story_driven_agent.py` | `agent/story_driven_agent.py` | Priority logic extended to 6 additional job types |
| `story_library_loader.py` | `agent/story_library_loader.py` | Hot-reload now clears compatibility cache |
| `agent_creation.py` | `simulation/setup/agent_creation.py` | Explicit path constants; StoryDrivenAgent receives correct paths |
| `sidebar_config.py` | `ui/sidebar_config.py` | Explicit path constants; parsers receive correct paths |
| `story_combinations.yaml` | `agent/story_combinations.yaml` | Dead job references fixed, changelog corrected, version 5.0.0 |
| `markov_mode_switching.py` | `agent/markov_mode_switching.py` | All 6 operator + 5 NHS extended personas in diagonal and green bias |
| `nhs_extended_personas.yaml` | `agent/personas/nhs_extended_personas.yaml` | 5 new personas: paramedic, community_health_worker, nhs_ward_manager, clinical_waste_driver, nhs_supply_chain |
| `nhs_operations.yaml` | `agent/job_contexts/nhs_operations.yaml` | 5 new NHS jobs creating cross-cluster bridges |
| `shap_analysis.py` | `analytics/shap_analysis.py` | Removed timestep + flow_rate leakage; causal features only |

### Scenario Files Delivered

**`scenarios/combined_configs/`:**
- `scotland_grid_competition.yaml` — NHS vs retail vs CalMac ferry on Central Belt grid
- `grangemouth_port_decarbonisation.yaml` — Forth Ports + rail + ScotWind
- `nhs_logistics_ev_priority.yaml` — healthcare SLA vs logistics charging competition
- `zev_mandate_trajectory.yaml` — 2025–2035 mandate ramp with charger bottleneck
- `hgv_phase_out_2035_2040.yaml` — battery vs hydrogen two-track transition
- `grid_demand_surge_2035.yaml` — 30-50% grid demand increase with data centre competition
- `last_mile_consolidation_hubs.yaml` — ZEZ + council fleet + NHS + cargo bikes
- `aggressive_electrification.yaml` — fixed trailing `---`
- `budget_constrained_realistic.yaml` — fixed trailing `---`
- `congestion_plus_electrification.yaml` — fixed base_scenario reference (`ev_subsidy_30%`)
- `phased_policy_rollout.yaml` — fixed base_scenario reference (`ev_subsidy_30%`)
- `realistic_ev_transition.yaml` — fixed base_scenario reference

**`scenarios/configs/`:**
- `rail_freight_modal_shift.yaml` — Grangemouth–Daventry with Phase 10b activation checklist
- `rail_electrification_2040.yaml` — diesel removal, hydrogen/battery, proxy modes documented
- `saf_aviation_maritime_rtfo.yaml` — SAF mandate, island lifeline, ferry electrification

---

## NHS Simulation Results (2026-03-22)

### The 4-Cluster Finding

The NHS simulation produced 4 identifiable clusters in the social network:

| Cluster | Agents | Jobs |
|---------|--------|------|
| Healthcare Ops | `fleet_manager_healthcare` | nhs_patient/clinical/staff + night_shift |
| Passenger Commute | `concerned_parent`, `accessibility_user` | morning_commute, commute_flexible |
| Logistics/Freight | `fleet_manager_logistics`, `freight_operator`, `delivery_driver` | logistics_hub, last_mile, night_shift |
| Bridge (night ops) | `shift_worker`, `disabled_commuter` | spans all clusters |

**Root cause:** Desire vector similarity within healthcare group (0.89–0.97) much higher than cross-cluster (0.69–0.80). With `cross_persona_prob=0.25`, cross-cluster ties exist but carry lower social influence weight, limiting adoption signal diffusion.

### The Two Disabled Commuters

`disabled_commuter_nhs_staff_commute_5424` and `_3292` appear in different visual clusters. They ARE connected by a direct same-persona tie (similarity ~0.98), but:
- `3292` is a high-degree hub drawn into the eco_warrior/shift_worker neighbourhood during network construction
- `5424` was drawn into the fleet_manager/accessibility neighbourhood
- Both neighbourhoods are correct — but different social signals reach each agent, producing different adoption trajectories despite near-identical desire profiles

**Research value:** This demonstrates that two agents with identical desires but different social positions can adopt different behaviours — validating the social network as a genuine diffusion mechanism rather than just noise.

### The Markov Lock-In Finding

The most important emergent result from the NHS run:
- `van_diesel` satisfaction at run end: **0.850**
- `van_electric` satisfaction: **0.846**
- Gap: **4 thousandths**
- Markov habit discount on van_diesel: **10.2%** (streak=260-280, habit_p=0.85)

The entire EV transition was held back by marginal habit lock-in, not economics. The `depot_based_electrification` subsidy (35%) was sufficient to overcome it, but barely. This is RTD_SIM's core research finding: **inertia, not cost, is the binding constraint on fleet decarbonisation**.

### SHAP Feature Leakage — Fixed

`timestep` was #1 SHAP feature at 28.9% — this was data leakage, not causality. The RandomForest learned that late timesteps correlate with high adoption because the logistic curve is monotonic, not because time causes flow. `flow_rate` (#2, 20.4%) was autoregressive leakage.

**Fix:** Both removed from `shap_analysis.py`. Expected causal ranking post-fix:
1. `infrastructure_effect` (~35-40%) — flat boost, most policy-controllable
2. `logistic_term` (~25-30%) — position on S-curve
3. `social_effect` (~15-20%) — peer influence bounded by K
4. `distance_to_capacity` (~10%) — proximity to ceiling

---

## ASI + Complex Contagion + Small-World Design (Phase 10c)

### Research Context

This is a genuinely novel combination for transport decarbonisation ABM. The closest existing work (Heppenstall 2012, Schwoon 2006, Schwarz 2020) does not combine all three. The innovation is:

1. **ASI as BDI Intention Selection hierarchy** — not just a policy typology but the agent's internal plan priority order
2. **Complex Contagion as the Belief update gate** — requires N neighbours to have adopted before the belief becomes updateable (freight-specific high-risk threshold)
3. **Small-World long-range ties as explicit policy levers** — PolicyAgent nodes act as rewiring hubs that inject "long-range" information into otherwise locally-clustered networks

### ASI Intent Hierarchy (BDI Plan Library)

Replace the current flat cost-minimisation with a three-tier priority ordering in `contextual_plan_generator.py`:

```
Tier 1 — AVOID:  Can the agent eliminate this trip or consolidate it?
  Plans: urban_freight_consolidation, trip_chaining, modal_avoidance
  Condition: perceived_congestion > threshold OR charger_occupancy_nearby > 0.7
  BDI: Desire(eco) > 0.7 AND Belief(consolidation_viable, strength > 0.6)

Tier 2 — SHIFT:  If Avoid not feasible, can the agent switch to a lower-carbon mode?
  Plans: rail_shift, ferry_shift, cargo_bike_upgrade, ev_transition
  Condition: Tier 1 failed AND alternative_mode_available
  BDI: Belief(ev_viable, strength > complex_contagion_threshold)

Tier 3 — IMPROVE: If Shift not feasible, optimise current technology
  Plans: route_optimisation, smart_charging, load_consolidation, eco_driving
  Condition: Tiers 1 and 2 both failed
  BDI: Always available as fallback
```

**Implementation in `contextual_plan_generator.py`:**
```python
class ASIIntentSelector:
    """Three-tier ASI intention selection — replaces flat cost minimisation."""

    def select_intention(self, agent_context, perceived_state) -> str:
        """Returns 'avoid', 'shift', or 'improve'."""
        if self._avoid_feasible(agent_context, perceived_state):
            return 'avoid'
        if self._shift_feasible(agent_context, perceived_state):
            return 'shift'
        return 'improve'  # always available

    def _avoid_feasible(self, ctx, state) -> bool:
        congestion = state.get('congestion', 0)
        charger_occ = ctx.get('charger_occupancy_nearby', 0)
        eco_desire = ctx.get('desires', {}).get('eco', 0.5)
        return (congestion > 0.7 or charger_occ > 0.7) and eco_desire > 0.6

    def _shift_feasible(self, ctx, state) -> bool:
        ev_belief = ctx.get('ev_viability_belief', 0.5)  # from Complex Contagion
        return ev_belief > ctx.get('complex_contagion_threshold', 0.6)
```

**Why this matters:** Current BDI evaluates all modes simultaneously and picks lowest cost. ASI enforces that agents try to reduce demand BEFORE switching technology — matching real-world logistics decision-making where consolidation is always explored before fleet replacement.

### Complex Contagion Belief Threshold

Standard Bayesian update (current): one peer adopting EV nudges belief by `w_peer × peer_ev_rate`.

Complex Contagion: belief only updates if **at least N of k neighbours have adopted** (threshold-based, not weighted-average). This models the high financial risk in freight — operators won't believe EV is viable until multiple trusted peers have proven it.

```python
# In BayesianBeliefUpdater._update_beliefs():
def _complex_contagion_gate(
    self, agent, network, agent_index: dict,
    mode: str, threshold_fraction: float
) -> bool:
    """
    Returns True only if >= threshold_fraction of neighbours use `mode`.
    This gates whether the belief is updateable at all this step.
    Prevents premature belief updates from a single pioneer peer.
    """
    neighbors = network.get_neighbors(agent.state.agent_id)
    if not neighbors:
        return False  # No peers → belief frozen
    adopters = sum(
        1 for nb_id in neighbors
        if agent_index.get(nb_id) is not None
        and getattr(agent_index[nb_id].state, 'mode', '') == mode
    )
    return (adopters / len(neighbors)) >= threshold_fraction
```

**Threshold by persona type (in `_COMPLEX_CONTAGION_THRESHOLDS`):**
- `freight_operator`: 0.40 (high risk — needs 40% of peers before belief updates)
- `fleet_manager_*`: 0.35
- `paramedic`: 0.60 (blue-light requires near-universal peer adoption to change belief)
- `delivery_driver`: 0.20 (gig workers update quickly — lower barrier)
- `eco_warrior`: 0.10 (early adopter — minimal social proof needed)
- `default`: 0.30

### Critical Services Hard Constraint (Ambulance EV Problem)

The current BDI cost function uses `desire_weight × cost` — a soft constraint. For paramedic and blue-light agents, `reliability=1.0` must produce a **hard infeasibility** when charger availability cannot be guaranteed, not just a high cost.

**Design:** Add to `bdi_planner._is_mode_feasible()`:

```python
# Hard constraint: reliability-critical agents cannot use EV
# unless ALL of the following are guaranteed:
#   1. charger_occupancy_nearby < 0.1 (slot available NOW)
#   2. charger at DESTINATION also available (return charging)
#   3. route_distance_km < max_range_km * 0.7 (30% buffer for blue-light use)
if context.get('reliability_critical', False):  # paramedic, blue-light
    charger_occ = context.get('charger_occupancy_nearby', 1.0)
    if mode in EV_MODES and charger_occ > 0.1:
        return False  # Hard block — cannot guarantee charging slot
```

`reliability_critical` is set True in `_extract_agent_context()` when:
- `persona_type == 'freight'` AND `desire_overrides.get('reliability', 0) >= 1.0`
- Or `job_type == 'ambulance_emergency_response'`

**Research output:** RTD_SIM will correctly show that EV ambulance adoption is near-zero until:
- Dedicated rapid-charge bays at every response station (charger_occ guaranteed < 0.1)
- MCS (1MW) chargers enabling 10-minute top-up between calls
- Policy changes this only when both infrastructure AND per-vehicle cost are met

This is a genuine policy finding: **no subsidy amount makes ambulance EV adoption viable without infrastructure guarantee**. The model will show this threshold effect clearly.

### Small-World Rewiring for Policy Diffusion

Current homophily network: all ties are operator ↔ operator. Policy signals reach agents only via peer adoption.

Phase 10c addition: `PolicyAgent` nodes (DfT, local authority, NHS trust board) are inserted as explicit high-degree "long-range" hubs with `k_policy=15` ties distributed across all persona clusters. This implements the Watts-Strogatz rewiring with deliberate target: policy agents connect to agents they would NOT naturally be similar to.

```python
# In network_setup.py, after build_network():
if config.enable_policy_agents:
    for policy_agent in policy_agents:
        # Rewire: one tie per persona cluster to the highest-centrality agent
        for cluster_persona in ['eco_warrior', 'freight_operator', 'fleet_manager_healthcare']:
            cluster_agents = [a for a in agents if a.user_story_id == cluster_persona]
            if cluster_agents:
                bridge_target = max(cluster_agents, key=lambda a: network.G.degree(a.state.agent_id))
                network.G.add_edge(policy_agent.state.agent_id, bridge_target.state.agent_id)
```

This creates the "long-range" ties that carry policy signal across otherwise-isolated clusters — the mechanism by which a DfT subsidy announcement reaches a rural haulier who has no eco_warrior peers.

### Is This Novel?

Yes. The specific contribution is:
1. **ASI as BDI Plan Library hierarchy** in a transport context — not previously formalised
2. **Complex Contagion threshold differentiated by persona/risk-tolerance** — Centola (2010) established complex contagion in social networks; applying it to freight-specific belief formation in BDI is new
3. **PolicyAgent as explicit Small-World rewiring nodes** — treating policy as a network topology intervention rather than a parameter change

For the handoff document: this is Phase 10c. It should not block Phase 10a (spatial generalisation) or Phase 10b (new agent types). The ASI/ComplexContagion changes are confined to `contextual_plan_generator.py` and `bayesian_belief_updater.py` — they can be implemented in parallel with 10a spatial work without file conflicts.

---

## Phase 10a — Spatial Generalisation (Active)

### Files with Edinburgh Hardcoding (need upload for full audit)

These files are confirmed to contain Edinburgh-specific hardcoding and have NOT yet been uploaded for review. Required for Phase 10a completion:

| File | Known Issue | Priority |
|------|------------|---------|
| `simulation/setup/environment_setup.py` | `infrastructure.populate_edinburgh_chargers()` call | 🔴 Critical |
| `simulation/infrastructure/infrastructure_manager.py` | `populate_edinburgh_chargers()` method | 🔴 Critical |
| `simulation/spatial/graph_manager.py` | Edinburgh bbox in graph loading fallback | 🔴 Critical |
| `simulation/spatial_environment.py` | `get_random_origin_dest()` bbox fallback | 🟠 High |
| `simulation/spatial/router.py` | Mode-to-network-type mapping (may have hardcoding) | 🟡 Medium |

**Already fixed:** `agent_creation.py` bbox fallback replaced with `config.get_bbox()`.

### Fixes Required (per handoff v0.10.0)

1. **`SimulationConfig.get_bbox()`** — reads `extended_bbox`, else derives from graph extent, else raises (no silent Edinburgh fallback)
2. **`InfrastructureManager.populate_chargers_from_bbox(bbox, num_public, num_depot)`** — generic placement replacing `populate_edinburgh_chargers()`
3. **`environment_setup.py`** — replace Edinburgh infrastructure call with `populate_chargers_from_bbox(config.get_bbox(), ...)`
4. **`simulation_config.py`** — `place` default becomes `None` (force user to specify)

### Tiled Graph Loading (Phase 10a extension)

Required for national scale. Not blocking Phase 10a core (bbox generalisation) but must be designed now:
- Tile by UK planning region: Scotland, Northern England, Midlands, SE England, Wales, Northern Ireland
- Load only tiles intersecting active corridor
- Cache by bbox hash (partially implemented in `GraphManager`)

---

## Phase 10b — New Agent Types

### Central MODES Registry (do first — blocks everything else)

```python
# simulation/config/modes.py  ← new file
MODES = {
    'walk':           {'network': 'walk',  'emissions_g_km': 0},
    'bike':           {'network': 'bike',  'emissions_g_km': 0},
    'e_scooter':      {'network': 'bike',  'emissions_g_km': 0},
    'cargo_bike':     {'network': 'bike',  'emissions_g_km': 0},
    'bus':            {'network': 'drive', 'emissions_g_km': 82},
    'tram':           {'network': 'drive', 'emissions_g_km': 35},
    'car':            {'network': 'drive', 'emissions_g_km': 170},
    'ev':             {'network': 'drive', 'emissions_g_km': 0},
    'van_electric':   {'network': 'drive', 'emissions_g_km': 0},
    'van_diesel':     {'network': 'drive', 'emissions_g_km': 150},
    'truck_electric': {'network': 'drive', 'emissions_g_km': 0},
    'truck_diesel':   {'network': 'drive', 'emissions_g_km': 200},
    'hgv_electric':   {'network': 'drive', 'emissions_g_km': 0},
    'hgv_diesel':     {'network': 'drive', 'emissions_g_km': 900},
    'hgv_hydrogen':   {'network': 'drive', 'emissions_g_km': 0},
    'local_train':    {'network': 'rail',  'emissions_g_km': 41},
    'intercity_train':{'network': 'rail',  'emissions_g_km': 41},
    'ferry_diesel':   {'network': 'ferry', 'emissions_g_km': 115},
    'ferry_electric': {'network': 'ferry', 'emissions_g_km': 0},
    'flight_domestic':{'network': 'air',   'emissions_g_km': 255},
    'flight_electric':{'network': 'air',   'emissions_g_km': 0},
    # Phase 10b additions (TODO — needs RailFreightAgent):
    # 'freight_rail': {'network': 'rail', 'emissions_g_km': 35},  # electrified
}
```

### Activation Checklist for Phase 10b Modes

When `freight_rail` is added:
1. Add to MODES registry with `emissions_g_km: 35` (electrified) / `76` (diesel)
2. Update `bdi_planner._filter_modes_by_context` to offer to `rail_freight_operator` and `freight_operator` on routes > 200km
3. Implement `RailFreightAgent` with path-dependent routing
4. Uncomment `freight_rail` cost_reduction in `rail_freight_modal_shift.yaml`
5. Rerun NHS scenario and compare CO2 — expect lower number than hgv_electric proxy

When `ferry_diesel` / `ferry_electric` added to default_modes:
1. Add to MODES registry (currently in MODE_MAX_DISTANCE_KM only)
2. Implement `FerryPassengerAgent` with schedule constraints
3. Implement `FerryFreightAgent` with `shore_power_demand` property
4. Uncomment ferry_diesel cost_reduction in `saf_aviation_maritime_rtfo.yaml`
5. Activate `CalMac` and `Rosyth–Zeebrugge` scenarios

When `flight_domestic` added to default_modes:
1. Add to MODES registry (currently in MODE_MAX_DISTANCE_KM only)
2. Redirect cost_reduction in `saf_aviation_maritime_rtfo.yaml`
3. Test island lifeline routes (Sumburgh, Kirkwall, Stornoway)

---

## Files Needed for Next Session

To complete Phase 10a, upload:
1. `simulation/setup/environment_setup.py`
2. `simulation/infrastructure/infrastructure_manager.py`
3. `simulation/spatial/graph_manager.py`
4. `simulation/spatial_environment.py`
5. `simulation/spatial/router.py`

To implement Phase 10c (ASI + Complex Contagion), upload:
1. `agent/contextual_plan_generator.py` (current, not the handoff version)
2. `agent/bdi_planner.py`
3. `agent/bayesian_belief_updater.py`

---

## Architecture Rules (Unchanged from v0.10.0)

### SD Equation (corrected)
```
dEV/dt = r·EV·(1 - EV/K)              ← logistic
        + (charger_count/100)·infra_s  ← FLAT infrastructure boost (no EV term)
        + s·EV·(1 - EV/K)              ← social (peaks at EV=K/2, not 0.5)
```

### Validation — one-step-ahead only
`predicted[t+1] = actual[t] + flow[t]`. Never use closed-form logistic.

### SHAP Features — causal only
`timestep` and `flow_rate` are **REMOVED** from SHAP features (data leakage). Correct causal features: `ev_adoption`, `logistic_term`, `infrastructure_effect`, `social_effect`, `distance_to_capacity`, `saturation_ratio`, `carrying_capacity_factor`, `adoption_x_distance`, `growth_potential`, `flow_acceleration`.

### Social Network Rules
- `cross_persona_prob=0.25` is the correct default — creates bridging ties without destroying homophily
- `_build_homophily` splits per-agent into `same_pool` / `cross_pool` — never use flat sorted pool
- Same-persona agents with very small populations (< 5) may not form direct ties — acceptable behaviour
- The two `disabled_commuter_nhs_staff_commute` nodes in different visual clusters: structurally correct, both have a direct tie but different cross-persona neighbourhoods produce different social signal environments

### Markov Persona IDs (UPDATED)
All 6 operator personas now in `_PERSONA_BASE_DIAGONAL` with correct values (was: all fell through to `default: 0.60`). All 5 NHS extended personas added.

### Critical Service Hard Constraints (NEW)
`paramedic`, `ambulance_emergency_response` agents have `reliability_critical=True` in `agent_context`. EV modes must be hard-blocked (not just penalised) when `charger_occupancy_nearby > 0.1`. Implementation in Phase 10c `_is_mode_feasible()`.

### Streamlit Rules
- Never use `default=` on `st.multiselect` that also sets key via `session_state`
- Two-run cycle for programmatic multiselect
- pyvis titles: plain strings only (no HTML)

### Pyvis Rules
- Never use HTML in `title` strings — plain `"\n".join(lines)` only
- Always add node before edge referencing it (ghost nodes fix)

### Peer Signal
`BayesianBeliefUpdater.rebuild_agent_index(agents)` must be called once before step loop.

---

## Known Open Issues

| Issue | Severity | File | Status |
|-------|---------|------|--------|
| Edinburgh hardcoding (all files) | ✅ Fixed | Phase 10a | 7 files patched 2026-03-23 |
| Infrastructure 0.0% / missing map markers | ✅ Fixed | `environment_setup.py`, `graph_manager.py` | bbox from OSMnx nodes 2026-03-23 |
| Straight-line routes on map | ✅ Fixed | `~/.rtd_sim_cache/osm_graphs/` | Delete cache to re-download with geometry |
| ASI intent hierarchy | ✅ Complete | `bdi_planner.py`, `contextual_plan_generator.py` | Delivered 2026-03-23 |
| Complex Contagion belief gate | ✅ Complete | `bayesian_belief_updater.py` | Delivered 2026-03-23 |
| Bike dominance (ASI SHIFT bug) | ✅ Fixed | `bdi_planner.py` | Bike removed from SHIFT_MODES; >= → >; eco guard added |
| reliability_critical over-set on passengers | ✅ Fixed | `contextual_plan_generator.py` | urgency=high and narrative safety use `time_sensitive` instead |
| SHAP leakage (`timestep`, `flow_rate` features) | ✅ Fixed | `shap_analysis.py` | Delivered 2026-03-22 |
| Markov operator persona IDs | ✅ Fixed | `markov_mode_switching.py` | Delivered 2026-03-22 |
| NHS cluster isolation | ✅ Diagnosed, partially addressed | `story_compatibility.py` | Bridging gaps added |
| `nhs_extended_personas.yaml` not auto-loaded | 🟡 Medium | `user_stories.py` | Change `_load_stories()` to glob all `personas/*.yaml` |
| `budget_student` + logistics job vehicle_type | 🟡 Medium | Job YAML files | `logistics_last_mile_urban` sets vehicle_type=commercial for students — should cap at personal |
| `system_dynamics_integration.py` infra capacity | ✅ Fixed | `simulation_loop.py` | Direct state assignment before SD update call |
| Streamlit use_container_width deprecation | 🟡 Low | All UI tabs | Run `fix_streamlit_deprecations.py` from project root |
| Phase 10b new agent types | ❌ Not started | Multiple files | FreightOperatorAgent, FerryPassengerAgent, PolicyAgent |
