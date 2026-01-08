# RTD_SIM Development Handoff - January 2026

**Date:** January 8, 2026  
**Project:** Real-Time Transport Decarbonization Simulator  
**Status:** Phase 4.5E Complete, Ready for Phase 4.5F/5.0

---

## 🎯 Current System Status

### Completed Phases ✅

#### Phase 4.5E: Freight Electrification Context (100%)
- ✅ Story-driven agents with freight context propagation
- ✅ BDI planner receives and respects `vehicle_required` context
- ✅ Van modes (`van_electric`, `van_diesel`) fully functional
- ✅ Freight agents (91.7%) correctly choosing van modes
- ✅ Cost function with commercial priority bonuses
- ✅ Infrastructure-aware routing for electric vans

#### Phase 4.5B: Policy Scenario Framework (100%)
- ✅ 5 working YAML scenarios in `scenarios/configs/`
- ✅ Scenario manager with runtime policy injection
- ✅ Scenario comparison utilities
- ✅ All tests passing

#### Phase 4 Refactoring: Modular Architecture (100%)
- ✅ `simulation_runner.py`: 1194 lines → 150 lines (orchestrator)
- ✅ Modular packages: `config/`, `setup/`, `execution/`, `routing/`, `analysis/`
- ✅ TimeSeries wrapper for backward compatibility
- ✅ Clean separation of concerns

---

## 📊 Current Performance Metrics

### Baseline Simulation Results (Central Scotland)
```
Mode Distribution:
- bus:          26 (52%) - High for regional trips
- van_diesel:   11 (22%) - ✅ Freight working!
- bike:          8 (16%)
- car:           3 (6%)
- ev:            2 (4%)
- van_electric:  0 (0%) - Awaiting subsidy scenario
- walk:          0 (0%)

Freight Performance:
- Agents: 12/50 (24%)
- Using vans: 11/12 (91.7%) ✅
- Context propagation: 100% working
```

### Infrastructure Metrics
```
Charging Stations: 50 regional
Depots: 2 (Glasgow, Edinburgh)
Total Ports: 202
Grid Capacity: 1000 MW
Utilization: <1%
```

---

## 🗂️ Project Structure

```
RTD_SIM/
├── agent/
│   ├── bdi_planner.py              # ✅ Infrastructure-aware, freight bonuses
│   ├── cognitive_abm.py            # ✅ Context propagation
│   ├── story_driven_agent.py       # ✅ Forced freight context (TEMP)
│   ├── job_contexts.yaml           # Freight job definitions
│   └── personas.yaml               # User story definitions
├── simulation/
│   ├── config/
│   │   └── simulation_config.py    # SimulationConfig, SimulationResults
│   ├── setup/
│   │   ├── environment_setup.py    # OSM + infrastructure initialization
│   │   ├── agent_creation.py       # Story-driven agent creation
│   │   └── network_setup.py        # Social network setup
│   ├── execution/
│   │   ├── simulation_loop.py      # Main simulation loop
│   │   └── timeseries.py           # TimeSeries wrapper
│   ├── routing/
│   │   └── route_diversity.py      # Route diversity strategies
│   ├── analysis/
│   │   └── scenario_comparison.py  # Scenario analysis tools
│   └── simulation_runner.py        # ✅ 150-line orchestrator
├── scenarios/
│   ├── scenario_manager.py         # ✅ Policy injection system
│   └── configs/
│       ├── ev_subsidy_30.yaml
│       ├── congestion_charge.yaml
│       ├── bus_rapid_transit.yaml
│       ├── freight_electrification.yaml  # ← Ready to test!
│       └── car_free_zone.yaml
├── ui/
│   ├── streamlit_app.py            # ✅ Main interface
│   ├── diagnostics_panel.py        # ✅ Shows freight debug info
│   └── main_tabs.py                # ✅ Fixed deprecation warnings
└── visualiser/
    └── visualization.py            # ✅ Van colors added
```

---

## 🔧 Key Technical Details

### 1. Freight Context Propagation

**Flow:** `job_contexts.yaml` → `StoryDrivenAgent._extract_agent_context()` → `agent.agent_context` → `BDIPlanner.actions_for()`

**Current Implementation (TEMPORARY FIX):**
```python
# story_driven_agent.py line 84
if 'freight' in self.job_story_id or 'delivery' in self.job_story_id:
    logger.info(f"FORCING freight context for {self.job_story_id}")
    context['vehicle_required'] = True
    context['cargo_capacity'] = True
    context['vehicle_type'] = 'commercial'
    context['priority'] = 'commercial'
```

**TODO:** Update `job_contexts.yaml` with proper parameters, then remove forced context.

### 2. Van Cost Bonus

**Location:** `agent/bdi_planner.py` lines 287-315

```python
# Priority adjustments
if priority == 'commercial':
    w_time = 0.7
    w_cost = 0.2  # Less sensitive to cost

# Calculate total cost
total_cost = (
    w_time * time_norm +
    w_cost * cost_norm +
    w_comfort * comfort_penalty +
    w_risk * risk +
    w_eco * emissions_norm +
    infrastructure_penalty
)

# Apply van preference bonus AFTER calculating cost
if priority == 'commercial' and mode in ['van_electric', 'van_diesel']:
    total_cost *= 0.7  # 30% discount for freight agents
```

### 3. Mode Distance Constraints

```python
MODE_MAX_DISTANCE_KM = {
    'walk': 5.0,
    'bike': 20.0,
    'bus': 100.0,
    'car': 500.0,
    'ev': 350.0,
    'van_electric': 200.0,
    'van_diesel': 500.0,
}
```

### 4. Logging Configuration

**Location:** `ui/streamlit_app.py` lines 1-15

```python
from __future__ import annotations  # MUST BE FIRST!

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s',
    force=True
)
```

This enables console logging for debugging.

---

## 🚀 Next Development Phases

### Phase 4.5F: Expanded Freight Modes (Recommended Next)

**Goal:** Add comprehensive freight vehicle types for complete supply chain simulation.

#### New Freight Modes to Add:

**First Mile / Warehouse:**
- `hgv_diesel` - Heavy Goods Vehicle (diesel, 44 tonnes)
- `hgv_electric` - Electric HGV (e-truck, limited range ~300km)
- `hgv_hydrogen` - Hydrogen fuel cell HGV (future tech)

**Middle Mile / Inter-city:**
- `truck_diesel` - Medium truck (7.5-18 tonnes)
- `truck_electric` - Electric truck (e-cargo)

**Last Mile / Urban Delivery:**
- `cargo_bike` - Electric cargo bike (urban, <5km)
- `van_electric` - ✅ Already implemented
- `van_diesel` - ✅ Already implemented

**Specialized:**
- `refrigerated_truck` - Cold chain logistics
- `flatbed_truck` - Construction/manufacturing

#### Implementation Steps:

1. **Add to `bdi_planner.py`:**
   ```python
   MODE_MAX_DISTANCE_KM = {
       # Existing modes...
       'cargo_bike': 10.0,
       'hgv_diesel': 800.0,
       'hgv_electric': 300.0,
       'hgv_hydrogen': 600.0,
       'truck_diesel': 600.0,
       'truck_electric': 250.0,
   }
   
   EV_RANGE_KM = {
       'ev': 350.0,
       'ev_delivery': 200.0,
       'hgv_electric': 300.0,
       'truck_electric': 250.0,
       'cargo_bike': 50.0,
   }
   ```

2. **Update `metrics_calculator.py`:**
   ```python
   COST_PER_KM = {
       'cargo_bike': {'base': 0.0, 'per_km': 0.15},
       'hgv_diesel': {'base': 5.0, 'per_km': 0.80},
       'hgv_electric': {'base': 8.0, 'per_km': 0.50},
       'hgv_hydrogen': {'base': 10.0, 'per_km': 0.60},
       'truck_diesel': {'base': 3.0, 'per_km': 0.60},
       'truck_electric': {'base': 4.0, 'per_km': 0.35},
   }
   
   EMISSIONS_G_PER_KM = {
       'cargo_bike': 0,
       'hgv_diesel': 800,
       'hgv_electric': 0,
       'hgv_hydrogen': 0,
       'truck_diesel': 400,
       'truck_electric': 0,
   }
   ```

3. **Add freight job types to `job_contexts.yaml`:**
   ```yaml
   long_haul_freight:
     job_type: freight
     parameters:
       vehicle_required: true
       cargo_capacity: true
       vehicle_type: heavy_freight
       recurring: true
       urgency: medium
     vehicle_constraints:
       type: heavy_freight
       min_capacity_kg: 10000
       max_range_km: 800
   
   urban_micro_delivery:
     job_type: delivery
     parameters:
       vehicle_required: true
       cargo_capacity: false
       vehicle_type: micro_mobility
       recurring: true
       urgency: high
     vehicle_constraints:
       type: micro_mobility
       max_distance_km: 10
   ```

4. **Update mode filtering in `bdi_planner.py`:**
   ```python
   def _filter_modes_by_context(self, context: Dict, trip_distance_km: float = 0.0) -> List[str]:
       vehicle_type = context.get('vehicle_type', 'personal')
       
       if vehicle_type == 'heavy_freight':
           if trip_distance_km > 400:
               modes = ['hgv_diesel', 'hgv_electric', 'hgv_hydrogen']
           else:
               modes = ['truck_diesel', 'truck_electric', 'van_diesel', 'van_electric']
       elif vehicle_type == 'micro_mobility':
           modes = ['cargo_bike', 'bike']
       elif vehicle_type == 'commercial':
           modes = ['van_electric', 'van_diesel', 'truck_electric', 'truck_diesel']
       # ... existing logic
   ```

5. **Add colors to `visualization.py`:**
   ```python
   MODE_COLORS_RGB = {
       # Existing colors...
       'cargo_bike': [34, 197, 94],      # Green
       'hgv_diesel': [75, 85, 99],       # Dark gray
       'hgv_electric': [52, 211, 153],   # Bright green
       'hgv_hydrogen': [96, 165, 250],   # Light blue
       'truck_diesel': [107, 114, 128],  # Gray
       'truck_electric': [74, 222, 128], # Green
   }
   ```

---

### Phase 4.5C: Time-of-Day Pricing (Optional)

**Goal:** Dynamic electricity pricing and smart charging optimization.

**Features:**
- Peak/off-peak electricity rates
- Time-dependent charging costs
- Smart charging scheduling
- Grid load balancing

**Estimated Time:** 2-3 hours

---

### Phase 5: System Dynamics & Carbon Budgets (Future)

**Goal:** Long-term carbon tracking and feedback loops.

**Features:**
- Carbon budget tracking over time
- Tipping point detection
- Policy effectiveness metrics
- Multi-year simulation support

**Estimated Time:** 1 week

---

## 🐛 Known Issues & TODOs

### High Priority

1. **Remove Forced Freight Context**
   - **Location:** `agent/story_driven_agent.py` line 84
   - **Action:** Update `job_contexts.yaml` with proper `vehicle_required: true` parameters
   - **Impact:** Currently using temporary workaround

2. **Fix Streamlit Deprecation Warnings**
   - **Issue:** `use_container_width` deprecated
   - **Action:** Replace with `width='stretch'` in remaining files
   - **Files:** Check `diagnostics_panel.py`, any other visualization files

3. **Test Freight Electrification Scenario**
   - **File:** `scenarios/configs/freight_electrification.yaml`
   - **Expected:** 40% van_electric subsidy → 50%+ electric van adoption
   - **Status:** Not yet tested

### Medium Priority

4. **Add van_electric Adoption**
   - **Issue:** Currently 0% van_electric (all freight uses van_diesel)
   - **Cause:** Base costs favor diesel, need policy intervention
   - **Solution:** Test "Freight Electrification" scenario

5. **Improve EV Adoption (Non-Freight)**
   - **Current:** 4% EV, 6% car
   - **Target:** 15-20% EV
   - **Action:** Reduce EV infrastructure penalties further

6. **Add More Freight Job Stories**
   - **Current:** Only `gig_economy_delivery` and `freight_delivery_route`
   - **Needed:** Long-haul, last-mile, construction, etc.

### Low Priority

7. **Optimize Agent Creation**
   - **Issue:** Loads user/job story parsers 50+ times (once per agent)
   - **Impact:** Slows initialization by ~5 seconds
   - **Solution:** Share parser instances across agents

8. **Add Scenario Selector to Streamlit**
   - **Status:** Scenarios exist but no UI dropdown yet
   - **Action:** Add to sidebar_config.py

---

## 📝 Important Code Locations

### Critical Files (Don't Break These!)

1. **`agent/bdi_planner.py`**
   - Lines 287-315: Van cost bonus (CRITICAL)
   - Lines 108-120: Freight mode filtering
   - Lines 48-60: Distance constraints

2. **`agent/story_driven_agent.py`**
   - Lines 84-95: Forced freight context (TEMPORARY)
   - Line 71: Context passed to parent class

3. **`agent/cognitive_abm.py`**
   - Line 135: Context passed to planner (CRITICAL)
   - Line 98: Agent context storage

4. **`simulation/execution/simulation_loop.py`**
   - Line 276: TimeSeries data structure
   - Lines 110-115: Freight agent detection

5. **`ui/streamlit_app.py`**
   - Lines 1-15: Logging configuration (CRITICAL for debugging)

---

## 🧪 Testing Checklist

### Before Next Session

- [ ] Verify logging still works (check console output)
- [ ] Confirm freight agents still use vans (>20% van usage)
- [ ] Test "Freight Electrification" scenario
- [ ] Check van_electric adoption increases with subsidy
- [ ] Ensure no Python crashes or errors

### For New Freight Modes

- [ ] Add all new modes to `MODE_MAX_DISTANCE_KM`
- [ ] Add costs to `metrics_calculator.py`
- [ ] Add emissions to `metrics_calculator.py`
- [ ] Add colors to `visualization.py`
- [ ] Update mode filtering logic
- [ ] Test with freight agents
- [ ] Verify routing works for all new modes

---

## 📚 Development Environment

### Python Version
```
Python 3.13
```

### Key Dependencies
```
streamlit
networkx
osmnx
pydeck
plotly
pandas
numpy
```

### Running the Application
```bash
streamlit run ui/streamlit_app.py
```

### Cache Location
```
~/.rtd_sim_cache/osm_graphs/
```

---

## 🎓 Research Context

### Current Research Questions

1. **Freight Electrification Feasibility**
   - Can electric vans handle urban delivery routes?
   - What infrastructure density is needed?
   - Cost parity timeline?

2. **Policy Impact**
   - How much subsidy needed to achieve 50% e-van adoption?
   - Does congestion charging accelerate electrification?
   - Optimal charging infrastructure placement?

3. **System Dynamics**
   - Network effects in freight electrification?
   - Tipping points in adoption curves?
   - First-mover advantages?

### Potential Paper Sections

1. **Agent-Based Freight Simulation**
   - Story-driven agents with realistic freight context
   - BDI decision-making with infrastructure awareness
   - Multi-modal routing with distance constraints

2. **Policy Scenario Testing**
   - YAML-based scenario framework
   - Runtime policy injection
   - Comparative analysis methodology

3. **Results & Analysis**
   - Baseline freight patterns (22% van usage)
   - Scenario comparison (baseline vs. subsidy)
   - Network effects and cascades

---

## 💡 Recommendations for Next Session

### Immediate Next Steps (30 minutes)

1. **Test Freight Electrification Scenario**
   ```
   - Select "Freight Electrification" from dropdown
   - Run 50 agents, 100 steps
   - Compare van_electric adoption vs baseline
   - Expected: 0% → 8-12%
   ```

2. **Clean Up Forced Context**
   ```
   - Update job_contexts.yaml with vehicle_required
   - Remove forced context from story_driven_agent.py
   - Verify freight agents still work
   ```

### Phase 4.5F Implementation (2-3 hours)

1. **Add HGV Modes** (1 hour)
   - Add to distance constraints
   - Add costs and emissions
   - Test with long-distance freight jobs

2. **Add Cargo Bike Mode** (30 minutes)
   - Add micro-mobility mode
   - Create urban delivery jobs
   - Test last-mile scenarios

3. **Create Comprehensive Scenarios** (1 hour)
   - "Complete Supply Chain Electrification"
   - "Urban Freight Consolidation"
   - "Hydrogen Truck Pilot"

### Research Paper Focus

**Title Suggestion:** *"Agent-Based Modeling of Freight Electrification: A Policy Scenario Framework for Urban Transport Decarbonization"*

**Key Contributions:**
1. Story-driven freight agent architecture
2. Infrastructure-aware BDI planning
3. Policy scenario framework with runtime injection
4. Empirical results from Scotland case study

---

## 🔗 Useful Resources

### Documentation
- OSMnx: https://osmnx.readthedocs.io/
- Streamlit: https://docs.streamlit.io/
- NetworkX: https://networkx.org/documentation/

### Related Research
- Urban freight electrification
- Last-mile delivery optimization
- Agent-based transport modeling
- BDI agent architectures

---

## 📞 Handoff Notes

### What's Working Perfectly ✅
- Freight context propagation
- Van mode selection for freight agents
- Infrastructure-aware routing
- Scenario framework
- Modular architecture
- Logging and debugging

### What Needs Attention ⚠️
- Forced freight context (temporary workaround)
- Van_electric adoption (needs scenario testing)
- General EV adoption (needs tuning)
- Streamlit deprecation warnings

### What's Ready to Build 🚀
- Expanded freight modes (HGV, cargo bikes, trucks)
- Time-of-day pricing
- Multi-year simulations
- Advanced policy scenarios

---

**End of Handoff**

*Good luck with the next development phase! The freight system is solid and ready for expansion.* 🚚✨

---

## Appendix: Quick Reference Commands

```bash
# Run simulation
streamlit run ui/streamlit_app.py

# Run scenario tests
python test_scenarios.py

# Clear Python cache
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

# Check freight agent logs
# Look for: "FORCING freight context" and "FREIGHT AGENT:"
```

## Appendix: Key Metrics to Track

```python
# Freight Performance
freight_agents = sum(1 for a in agents if a.agent_context.get('vehicle_required'))
van_users = sum(1 for a in agents if a.state.mode in ['van_electric', 'van_diesel'])
freight_van_adoption = van_users / freight_agents  # Target: >80%

# Electrification Progress
ev_adoption = sum(1 for a in agents if a.state.mode == 'ev') / len(agents)
van_electric_adoption = sum(1 for a in agents if a.state.mode == 'van_electric') / van_users

# Infrastructure Utilization
charging_utilization = occupied_ports / total_ports
grid_stress = current_load_mw / grid_capacity_mw
```
