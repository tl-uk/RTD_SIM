# RTD_SIM — Session Handoff Document
**Date:** 2026-03-28 | **Version:** v0.13.0 | **Repo:** https://github.com/tl-uk/RTD_SIM

---

## What to say to Claude (new chat)

**Message 1 — paste verbatim, upload this file:**
> "I am continuing development of RTD_SIM, a BDI + System Dynamics digital twin for transport decarbonisation. This document is your handoff briefing. Please read it fully before responding."

**Message 2 — the active work:**
> "All four routing bugs from the 2026-03-27 run are now fixed. The next priorities are: (1) confirm the fix with a 50-agent run and upload the log, (2) implement the GTFS sidebar config fields so users can load a transit feed, (3) begin Phase 10b new agent types."

Upload with Message 2: **the new simulation log** (from `RTD_SIM/logs/`)

---

## Project Overview

**RTD_SIM** — Real-Time Transport Decarbonisation Simulator
**Stack:** Python 3.10+, asyncio, OSMnx, Streamlit, pyvis, SHAP, scikit-learn, OLMo 2 via Ollama
**Location:** `/Users/theo/Dev/Python/RTD_SIM/`
**Run:** `streamlit run ui/streamlit_app.py`
**Ollama:** `ollama serve` (OLMo 2 13B, Apache 2.0, ~8GB)

**Architecture:**
- BDI agents (Beliefs, Desires, Intentions) with Bayesian belief updating and Markov habit formation
- Streaming System Dynamics (logistic growth + feedbacks, data-assimilated stocks)
- Homophily social network (~500 agents, ~2500 ties, cross_persona_prob=0.25)
- Story-driven agents: user stories × job stories (whitelist-filtered)
- Three-tier LLM fallback: OLMo 2 → static YAML seed library → Claude
- Phase 7: Temporal engine, synthetic events, combined policy scenarios
- Phase 9: Story ingestion service, OLMo 2 integration
- Phase 10: Rail/GTFS intermodal routing (10b complete), GTFS analytics tab (complete)

---

## Phase Status

| Phase | Status | Description |
|-------|--------|-------------|
| 1–9 | ✅ Complete | Core BDI+SD, OSM routing, story agents, social network, temporal engine, analytics, OLMo 2 |
| 10a | ✅ Complete | Spatial generalisation — runtime city config, charger placement from graph bounds |
| 10b | ✅ Complete | Rail intermodal routing, GTFS loader/graph/analytics, NaPTAN loader, tram spine |
| 10c | ✅ Complete | ASI intent hierarchy, Complex Contagion belief threshold, Markov habit discount |
| 11–12 | ✅ Complete | Policy diagnostics, combination report, SHAP, sensitivity analysis |
| 13 | ❌ Not started | Digital twin federation: Eclipse Ditto / ODTP containerisation |

---

## Active Bugs Fixed (2026-03-28) — Deploy Immediately

### Deployment

```bash
cp outputs/route_diversity.py    simulation/routing/
cp outputs/story_driven_agent.py agent/
cp outputs/bdi_planner.py        agent/
cp outputs/rail_spine.py         simulation/spatial/

# Clear OSM cache if routes still appear as straight lines
rm -rf ~/.rtd_sim_cache/osm_graphs/

streamlit run ui/streamlit_app.py
```

### Bug 1 — CRITICAL: 100% straight lines (`route_diversity.py`)

**Root cause:** All three diversity wrapper inner functions had signature
`(agent_id, origin, dest, mode='drive')`. `bdi_planner.py` calls
`env.compute_route(..., policy_context=context)`, which raised:
```
TypeError: ultra_fast_diverse_route() got an unexpected keyword argument 'policy_context'
```
Every road-mode routing call failed. Every agent got 0 viable actions, fell
back to `walk`, and rendered as a straight line. 50/50 agents in the 2026-03-27
log showed `NO VIABLE ACTIONS`.

**Fix applied:** All three inner functions (`diversified_compute_route`,
`k_shortest_compute_route`, `ultra_fast_diverse_route`) now accept
`policy_context=None, **kwargs`. All fallback `original_compute_route(...)` calls
now forward `policy_context=policy_context`. Non-road modes (rail, transit, ferry,
air) are delegated directly to the real router rather than the drive-graph path.

### Bug 2 — `priority=commercial` on passenger commutes (`story_driven_agent.py`)

**Root cause:** `story_driven_agent.py` line 249–250:
```python
elif urgency == 'high':
    context['priority'] = 'commercial'
```
`morning_commute` in `transit_passenger.yaml` has `urgency: high`, triggering
`priority=commercial`. Downstream in `bdi_planner._filter_modes_by_context`,
`priority=commercial` restricts the mode list to freight/commercial vehicles for
passenger commuters. The 2026-03-27 log confirmed this:
```
Extracted context for morning_commute: vehicle_required=False, vehicle_type=personal, priority=commercial
```

**Fix applied:** `urgency=high` now only escalates to `commercial` when
`vehicle_type` is not `personal` or `transit`. Passenger commutes, shopping
trips, and transit journeys always remain `normal` priority regardless of urgency.
`taxi_service` job type added to the commercial whitelist.

### Bug 3 — Tram agents get straight lines (`bdi_planner.py`)

**Root cause:** The abstract mode guard checked
`if get_network(mode) == 'rail'` to route via `route_via_stations()`.
Since `modes.py` now has `tram: network='tram'`, trams fell into the
`else` branch and received `make_synthetic_route()` — a straight diagonal.

**Fix applied:** Check widened to `if get_network(mode) in ('rail', 'tram'):`
so trams dispatch to `route_via_stations()`, which in turn calls
`route_via_tram_stops()` for the Edinburgh tram line.

### Bug 4 — No tram stops in `route_via_stations` (`rail_spine.py`)

**Root cause:** Even after Bug 3 was fixed, `route_via_stations('tram')` would
fail because there were no `tram_stop` type entries in `STATIONS`, and
`route_via_stations` had no tram dispatch branch.

**Fix applied:**
- `route_via_stations()` now dispatches `mode='tram'` to `route_via_tram_stops()`
  immediately (before the rail station lookup path).
- 16 Edinburgh tram stops added to `STATIONS` with `type='tram_stop'` or
  `type='tram_terminus'` (Airport, Ingliston P&R, Gogar, Bankhead, Stenhouse,
  Balgreen, Murrayfield, Roseburn, West End, Princes Street, St Andrew Square,
  York Place, Picardy Place, McDonald Road, Balfour Street, Newhaven).
- Note: `TRAM_STOPS` dict and `route_via_tram_stops()` already existed in the
  spine — they just weren't being called.

---

## GTFS Integration — Complete Architecture

### What's deployed

| File | Destination | Status |
|------|-------------|--------|
| `simulation/gtfs/gtfs_loader.py` | Parse 7-file GTFS static feed | ✅ |
| `simulation/gtfs/gtfs_graph.py` | Build NetworkX transit graph | ✅ |
| `simulation/gtfs/__init__.py` | Package with `load_gtfs()` convenience fn | ✅ |
| `simulation/gtfs/gtfs_analytics.py` | 4 research analytics functions | ✅ |
| `simulation/spatial/naptan_loader.py` | NaPTAN transfer node loader | ✅ |
| `simulation/spatial/router.py` | `_compute_gtfs_route()`, `_TRANSIT_MODES` | ✅ |
| `simulation/spatial_environment.py` | `load_gtfs_graph()`, `get_transit_graph()` | ✅ |
| `simulation/setup/environment_setup.py` | GTFS load hook after drive graph | ✅ |
| `simulation/config/simulation_config.py` | 5 GTFS fields in `__init__` | ✅ |
| `simulation/execution/simulation_loop.py` | GTFS analytics call + full mode tracking | ✅ |
| `ui/tabs/gtfs_analytics_tab.py` | 4-panel Streamlit tab | ✅ |
| `ui/components/gtfs_visualizer.py` | Service PathLayer + stops ScatterplotLayer | ✅ |
| `visualiser/visualization.py` | `show_gtfs`, `show_gtfs_stops`, `gtfs_electric_only` | ✅ |
| `ui/tabs/map_tab.py` | GTFS sidebar checkboxes, env threading | ✅ |
| `scenarios/combined_configs/gtfs_frequency_doubling.yaml` | Frequency lever scenario | ✅ |
| `scenarios/combined_configs/gtfs_bus_electrification.yaml` | Electrification scenario | ✅ |

### What still needs doing

**GTFS sidebar config** — `sidebar_config.py` has no GTFS feed path input.
Add after the scenario section:
```python
st.subheader("GTFS Transit Data")
gtfs_path = st.text_input(
    "GTFS feed path",
    value="",
    placeholder="/path/to/gtfs.zip or leave blank",
    help="Path to GTFS .zip or directory. Enables accurate bus/tram/ferry routing."
)
if gtfs_path:
    gtfs_date = st.text_input("Service date (YYYYMMDD)", value="",
                               placeholder="e.g. 20250401")
    config.gtfs_feed_path    = gtfs_path.strip()
    config.gtfs_service_date = gtfs_date.strip() or None

config.run_gtfs_analytics = st.checkbox(
    "Run GTFS analytics after simulation",
    value=False,
)
```

**GTFS tab wiring in `streamlit_app.py`** — add to `tab_configs`:
```python
from ui.tabs.gtfs_analytics_tab import render_gtfs_analytics_tab

# In tab_configs list:
tab_configs.append(("🚌 GTFS Transit", render_gtfs_analytics_tab))

# In the tab render loop (special case — needs env):
elif tab_name == "🚌 GTFS Transit":
    render_func(
        results=results,
        agents=results.agents or [],
        env=results.env,
    )
```

**UK GTFS feeds** (all free):
- Traveline National Dataset (Scotland): `travelinedata.org.uk`
- ScotRail: `raildeliverygroup.com/gtfs`
- Bus Open Data Service: `data.bus-data.dft.gov.uk`

---

## Phase 10b — New Agent Types (Next Priority)

**Prerequisite:** Confirm Bug 1–4 fix with a successful 50-agent run log.

1. `simulation/config/modes.py` — canonical mode registry (emissions_g_km, network, range_km) ✅ done
2. `agent/agent_types/freight_operator_agent.py` — vehicle_type=heavy_freight, cargo_capacity
3. `agent/agent_types/ferry_passenger_agent.py` — ferry_dependent flag
4. `agent/agent_types/policy_agent.py` — high-degree hub (k_policy=15) in social network
5. Add `freight_rail`, `ferry_diesel`, `ferry_electric` proper routing (GTFS for ferry when feed loaded)

---

## Key Architecture Rules (for Claude)

### Route diversity wrapper rule
All three wrapper inner functions MUST accept `policy_context=None, **kwargs`. Any call to `original_compute_route(...)` inside them MUST forward `policy_context=policy_context`. Breaking either causes 100% routing failure.

### Priority escalation rule
`urgency=high` MUST NOT set `priority=commercial` for `vehicle_type` of `personal` or `transit`. Passenger job types always stay `normal` — only commercial/freight vehicle_types escalate with urgency.

### Tram routing rule
`modes.py` has `tram: network='tram', routeable=False`. The abstract guard in `bdi_planner` dispatches `network in ('rail', 'tram')` to `route_via_stations()`. `route_via_stations('tram', ...)` immediately dispatches to `route_via_tram_stops()`. Never route tram on the drive graph.

### SD Equation (corrected)
```
dEV/dt = r·EV·(1 - EV/K)         ← logistic
        + cap·infra_strength       ← FLAT infrastructure boost
        + s·EV·(1 - EV/K)         ← social (peaks at EV=K/2)
```

### Generalised cost formula (router.py + GTFS)
```
gen_cost = (travel_time_h + headway_h/2) × VoT
         + dist_km × energy_price
         + dist_km × (emissions_g_km / 1000) × carbon_tax
```
The `headway/2` term is only present for GTFS transit edges. Without it transit
would always be cheaper than car on short trips because there's no waiting penalty.

### Complex Contagion thresholds (bayesian_belief_updater.py)
`_COMPLEX_CONTAGION_THRESHOLDS`: eco_warrior=0.10, freight=0.40, paramedic=0.60.
EV beliefs only update when `peer_ev_rate >= threshold` — frozen otherwise.

### SHAP feature formulas (corrected)
```python
'social_effect':         s * EV * (1 - EV/K)          # NOT s*EV² or s*EV*(1-EV)
'infrastructure_effect': cap * infra_strength           # FLAT — no EV term
'logistic_term':         r * EV * (1 - EV/K)
'saturation_ratio':      EV / K
'distance_to_capacity':  K - EV
```
All K-dependent features read `entry.get('ev_carrying_capacity_K', 0.80)` — never hardcode.

### Streamlit rules
- Never use `default=` on a `st.multiselect` that also sets its key via `session_state`
- Widgets inside `st.form()` cannot trigger reruns — move interactive widgets outside the form
- Two-run cycle for programmatic multiselect: sentinel → pending flag → `st.rerun()` → pre-populate

### OSM cache note
Straight-line routes after a cache clear are normal — the cache stores graphs
without Shapely edge geometry. `rm -rf ~/.rtd_sim_cache/osm_graphs/` forces a
full re-download with geometry. One-time, takes ~2–5 min.

---

## Previously Completed Work (Sessions 1–5)

### Session 1–2
- BDI agents, Bayesian belief updating, Markov habit formation
- System Dynamics streaming integration
- Social network (pyvis + NetworkX)
- Story-driven agent framework (YAML personas × job contexts)

### Session 3–4
- Phase 10a: Spatial generalisation (runtime city config)
- Phase 10c: ASI intent hierarchy, Complex Contagion
- story_compatibility.py: full 55-job whitelist, 6 operator personas
- SHAP leakage fix, SD equation corrections
- NHS simulation 4-cluster finding documented

### Session 5 (v0.12.1)
- Bug A: `create_realistic_agent_pool` alphabetical truncation → reproducible shuffle
- Bug B: EV Subsidy 30% never reached BDI cost → `mode_cost_factors` multiplier dict
- Bug C: "Select All" Streamlit race condition → sentinel strip before assignment
- markov_mode_switching.py: all operator + NHS personas added
- nhs_extended_personas.yaml + nhs_operations.yaml: 5 new personas, 5 new jobs

### Session 6–7 (v0.13.0 — this session)
- Phase 10b rail routing: `modes.py` rail → `routeable=True`, `graph_manager.py` JIT spine,
  `router.py` intermodal + GTFS, `route_diversity.py` non-road delegation
- GTFS loader, graph builder, analytics (transit deserts, electrification ranking,
  modal shift thresholds, emissions hotspots)
- NaPTAN loader with DfT API + rail_spine fallback
- `simulation_loop.py`: full 20-mode adoption tracking (was missing transit/rail modes)
- `gtfs_analytics_tab.py`: 4-panel research tab
- 4 routing bugs fixed (2026-03-28): route_diversity policy_context, priority=commercial,
  tram network check, tram stop dispatch

---

## Research Findings to Date

### The Markov Lock-In Finding (NHS run, 2026-03-22)
- van_diesel satisfaction: 0.850 vs van_electric: 0.846 — gap of 4 thousandths
- Markov habit discount on van_diesel: 10.2% (streak=260–280, habit_p=0.85)
- Full EV transition held back by inertia, not economics
- `depot_based_electrification` subsidy (35%) sufficient to overcome it — barely
- **Core research finding: inertia, not cost, is the binding constraint on fleet decarbonisation**

### The 4-Cluster NHS Network Finding
Healthcare Ops | Passenger Commute | Logistics/Freight | Bridge (night ops)
Desire vector similarity within-cluster 0.89–0.97 vs cross-cluster 0.69–0.80.
Two disabled commuters in different social positions → different adoption trajectories
despite near-identical desire profiles. Validates social network as genuine diffusion mechanism.

### Expected GTFS Research Outputs (once feed loaded)
1. Transit desert map: % of agents whose origins lack walkable, frequent service
2. Electrification ranking: top diesel routes by tCO₂/yr saving
3. Modal shift threshold: headway reduction needed to flip car users (expect 25–40% within 5 min)
4. Emissions hotspot: 500m grid cells by CO₂ burden, with mode breakdown
