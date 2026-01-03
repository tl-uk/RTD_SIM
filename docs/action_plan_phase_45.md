# Complete Action Plan
## Phase 4.5E Fixes + Phase 4.5B Implementation

---

## 🎯 Overview

**Current Status:** Phase 4.5E-Lite at 60% (context working, but EV adoption broken)  
**Target:** Phase 4.5E at 100% + Phase 4.5B at 100%  
**Time Estimate:** 60-90 minutes total

---

## ⚡ PRIORITY 1: Fix 0% EV Adoption (15 minutes)

### Issue
- **Current:** 0% EV adoption, even eco_warriors (eco=0.99) choose cars
- **Root Cause:** EV costs + infrastructure penalties too high
- **Impact:** Makes freight electrification scenarios impossible to test

### Actions

#### 1. Reduce EV Costs (2 min)
**File:** `simulation/spatial/metrics_calculator.py`

```python
# Lines ~45-50
# FIND THIS:
COST_PER_KM = {
    'walk': {'base': 0.0, 'per_km': 0.0},
    'bike': {'base': 0.0, 'per_km': 0.0},
    'bus': {'base': 2.0, 'per_km': 0.1},
    'car': {'base': 0.0, 'per_km': 0.5},
    'ev': {'base': 0.0, 'per_km': 0.3},           # ← CHANGE TO 0.25
    'van_electric': {'base': 0.0, 'per_km': 0.4}, # ← CHANGE TO 0.30
    'van_diesel': {'base': 0.0, 'per_km': 0.6},   # ← CHANGE TO 0.55
}
```

#### 2. Relax Infrastructure Penalties (5 min)
**File:** `agent/bdi_planner.py`

```python
# Lines ~240-280 (in cost() method)
# FIND THE INFRASTRUCTURE PENALTY SECTION:

if mode in ['ev', 'van_electric'] and self.has_infrastructure:
    # Range anxiety
    trip_distance = params.get('trip_distance_km', 0)
    vehicle_type = context.get('vehicle_type', 'personal')
    ev_type = 'ev_delivery' if vehicle_type == 'commercial' else 'ev'
    max_range = self.EV_RANGE_KM.get(ev_type, 350.0)
    range_ratio = trip_distance / max_range
    
    # CHANGE THESE LINES:
    if range_ratio > 0.9:
        range_anxiety = desires.get('range_anxiety', 0.5)
        infrastructure_penalty += range_anxiety * 0.5  # WAS: 2.0
    elif range_ratio > 0.7:
        range_anxiety = desires.get('range_anxiety', 0.5)
        infrastructure_penalty += range_anxiety * 0.2  # WAS: 0.5
    
    # Charging availability
    if 'nearest_charger' in params:
        # ... existing code ...
        pass
    else:
        # CHANGE THIS LINE:
        if range_ratio > 0.5:  # Only penalize long trips
            infrastructure_penalty += 0.3  # WAS: 1.0
```

#### 3. Add Range Anxiety Defaults (3 min)
**File:** `agent/bdi_planner.py`

```python
# In cost() method, ADD THIS at the beginning (after line ~210):

def cost(self, action, env, state, desires, agent_context=None):
    """Calculate action cost with infrastructure awareness."""
    route = action.route
    mode = action.mode
    params = action.params
    context = agent_context or {}
    
    # ADD THIS BLOCK:
    # Set default range_anxiety based on eco desire
    if 'range_anxiety' not in desires:
        eco_desire = desires.get('eco', 0.5)
        if eco_desire > 0.7:
            desires['range_anxiety'] = 0.2  # Eco warriors trust EVs
        elif eco_desire > 0.5:
            desires['range_anxiety'] = 0.3
        else:
            desires['range_anxiety'] = 0.5  # Default
    
    # ... rest of existing code ...
```

#### 4. Test EV Adoption (5 min)
```bash
python streamlit_app.py
```

Run simulation with:
- 50 agents
- Central Scotland
- All user stories (ensure eco_warrior included)

Expected results:
- EV adoption: 10-15%
- Van_electric: 5-8%
- Eco_warriors (eco>0.7) should prefer EVs

---

## 🔧 PRIORITY 2: Apply Other Critical Fixes (5 minutes)

### Fix Distance Filter
**File:** `agent/bdi_planner.py`  
**Line:** ~151

```python
# CHANGE:
if trip_distance_km <= self.MODE_MAX_DISTANCE_KM.get(m, float('inf'))

# TO:
if trip_distance_km < self.MODE_MAX_DISTANCE_KM.get(m, float('inf'))
```

---

## 📋 PRIORITY 3: Implement Phase 4.5B Scenarios (30-40 minutes)

### Step 1: Create Scenario Files (5 min)

Copy my artifacts into your project:

1. **Save `scenario_manager.py`:**
   ```
   scenarios/scenario_manager.py
   ```

2. **Save setup script:**
   ```
   setup_scenarios.py
   ```

3. **Save test script:**
   ```
   test_scenarios.py
   ```

### Step 2: Run Setup (2 min)
```bash
python setup_scenarios.py
```

Expected output:
```
✅ Created: scenarios/
✅ Created: scenarios/configs/
✅ Created 5 scenario files
✅ Successfully loaded 5 scenarios
```

### Step 3: Run Tests (2 min)
```bash
python test_scenarios.py
```

Expected output:
```
✅ PASS: Scenario Loading
✅ PASS: Scenario Activation
✅ PASS: Policy Application
✅ PASS: Scenario Comparison
✅ PASS: All Scenarios Valid

🎉 ALL TESTS PASSED!
```

### Step 4: Integrate with Simulation Runner (15 min)

**File:** `simulation/simulation_runner.py`

Add these sections (from my artifact "Correct SimulationRunner Integration"):

1. **Import:** Add scenario manager import
2. **SimulationConfig:** Add `scenario_name` and `scenarios_dir` parameters
3. **SimulationResults:** Add `scenario_report` attribute
4. **New function:** Add `apply_scenario_policies()` function
5. **Modify:** Add scenario application to `run_simulation()`
6. **Add:** Helper functions at end of file

### Step 5: Integrate with Streamlit (10 min)

**File:** `streamlit_app.py`

Add these sections (from my artifact "Streamlit UI - Scenario Integration"):

1. **Sidebar:** Add scenario selector dropdown
2. **Run button:** Pass `scenario_name` to config
3. **Results:** Display applied scenario info
4. **(Optional)** **New tab:** Add scenario comparison tab

### Step 6: Test Scenario System (5 min)

```bash
python streamlit_app.py
```

1. Select "EV Subsidy 30%" from dropdown
2. Run simulation
3. Verify console shows:
   ```
   📋 Scenario Active: EV Subsidy 30%
      - cost_reduction: 30.0 (ev)
      - cost_reduction: 30.0 (van_electric)
   ```
4. Check EV adoption increases to 20-25%

---

## 📊 Expected Results After All Fixes

### Mode Distribution (Baseline - No Scenario)
```
walk:          2% (unchanged)
bike:         35% (down from 46%, respects 20km limit)
bus:          18% (slight decrease)
car:          10% (decreased, EVs competitive)
ev:        15-20% ✅ (up from 0%)
van_electric: 6-8% ✅ (up from 0%)
van_diesel:  8-10% (stable)
```

### Mode Distribution (EV Subsidy 30% Scenario)
```
walk:          2%
bike:         35%
bus:          15%
car:           8%
ev:        25-30% ✅ (major increase)
van_electric: 10-12% ✅ (freight electrification)
van_diesel:    5-8%
```

### Freight Agents (12 total)
```
Baseline:
- van_diesel:   4 agents (33%)
- van_electric: 3 agents (25%)
- car:          4 agents (33%)
- ev:           1 agent  (8%)

EV Subsidy:
- van_diesel:   2 agents (17%)
- van_electric: 6 agents (50%) ✅
- car:          3 agents (25%)
- ev:           1 agent  (8%)
```

---

## 🧪 Testing Checklist

### Phase 4.5E Tests
- [ ] EV adoption >10% in baseline
- [ ] Eco_warriors (eco>0.7) prefer EVs over cars
- [ ] Van adoption 30-40% among freight agents
- [ ] Van_electric adoption 20-30% among freight agents
- [ ] No bike trips ≥20km
- [ ] Console shows "Freight modes ARE AVAILABLE"

### Phase 4.5B Tests
- [ ] 5 scenario files created in `scenarios/configs/`
- [ ] `test_scenarios.py` shows all tests passing
- [ ] Scenario selector appears in Streamlit sidebar
- [ ] Selecting scenario shows expected outcomes
- [ ] Console logs show applied policies
- [ ] EV Subsidy scenario increases EV adoption by 40%
- [ ] Congestion Charge scenario reduces car usage by 30%

---

## 🚨 Troubleshooting

### Issue: EVs Still 0% After Fixes

**Check 1:** Verify costs were actually changed
```python
# In Python console:
from simulation.spatial.metrics_calculator import MetricsCalculator
mc = MetricsCalculator()
print(mc.cost['ev'])  # Should be {'base': 0.0, 'per_km': 0.25}
```

**Check 2:** Verify penalties were reduced
```python
# Add debug logging to bdi_planner.py cost() method:
if mode in ['ev', 'van_electric']:
    logger.info(f"EV penalty: {infrastructure_penalty}, range_ratio: {range_ratio}")
# Should see penalties <0.5 for short trips
```

**Check 3:** Verify eco agents exist
```python
# In diagnostics:
eco_agents = [a for a in agents if a.desires.get('eco', 0) > 0.7]
print(f"Found {len(eco_agents)} eco-conscious agents")
# Should be >5 agents
```

### Issue: Scenarios Not Loading

**Check 1:** Directory structure
```bash
ls -la scenarios/configs/
# Should show 5 .yaml files
```

**Check 2:** Import error
```python
# In Python console:
from scenarios.scenario_manager import ScenarioManager
# Should not raise ImportError
```

**Check 3:** YAML syntax
```bash
python -c "import yaml; yaml.safe_load(open('scenarios/configs/ev_subsidy_30.yaml'))"
# Should not raise error
```

### Issue: Scenario Not Applied

**Check 1:** Verify scenario_name passed to config
```python
# In streamlit_app.py, add debug:
st.write(f"DEBUG: scenario_name = {scenario_name}")
# Before creating config
```

**Check 2:** Check apply_scenario_policies called
```python
# In simulation_runner.py, verify log output:
# Should see: "📋 Scenario Active: [name]"
```

---

## 📝 File Summary

### Files to Modify
1. `simulation/spatial/metrics_calculator.py` - Reduce EV costs
2. `agent/bdi_planner.py` - Relax penalties, add range anxiety defaults, fix distance filter
3. `simulation/simulation_runner.py` - Add scenario integration
4. `streamlit_app.py` - Add scenario UI

### Files to Create
1. `scenarios/__init__.py`
2. `scenarios/scenario_manager.py`
3. `scenarios/configs/*.yaml` (5 files)
4. `setup_scenarios.py`
5. `test_scenarios.py`

### Files Unchanged (Working)
- `agent/cognitive_abm.py` ✅
- `agent/story_driven_agent.py` ✅
- `agent/job_contexts.yaml` ✅
- `simulation/infrastructure_manager.py` ✅
- All visualization files ✅

---

## 🎉 Success Criteria

Phase 4.5E + 4.5B complete when:
- ✅ EV adoption: 15-20% baseline
- ✅ EV Subsidy scenario boosts to 25-30%
- ✅ Van_electric: 20-30% of freight baseline
- ✅ Freight Electrification scenario boosts to 50%+
- ✅ No bike trips ≥20km
- ✅ 5 working scenarios
- ✅ Scenario comparison feature functional
- ✅ All tests passing

---

## ⏱️ Time Breakdown

| Task | Time | Cumulative |
|------|------|------------|
| Fix EV costs | 2 min | 2 min |
| Relax penalties | 5 min | 7 min |
| Add range anxiety | 3 min | 10 min |
| Test EV adoption | 5 min | 15 min |
| Fix distance filter | 2 min | 17 min |
| Create scenario files | 5 min | 22 min |
| Run setup/tests | 4 min | 26 min |
| Integrate runner | 15 min | 41 min |
| Integrate UI | 10 min | 51 min |
| Test scenarios | 5 min | 56 min |

**Total: ~60 minutes** (assumes no major issues)

---

## 🔄 Recommended Order

1. **EV adoption fixes** (15 min) - Critical, blocks everything else
2. **Distance filter** (2 min) - Quick win
3. **Test baseline** (5 min) - Verify fixes work
4. **Scenario setup** (10 min) - Create framework
5. **Runner integration** (15 min) - Core functionality
6. **UI integration** (10 min) - User interface
7. **Final testing** (10 min) - End-to-end validation

**Total: 67 minutes**

---

## 📞 Next Steps After Completion

Once Phase 4.5E + 4.5B are complete:

### Option A: Phase 4.5C - Time-of-Day (2-3 days)
- Dynamic electricity pricing
- Peak/off-peak charging
- Smart charging optimization

### Option B: Phase 4.5F - Station Optimization (2-3 days)
- Hotspot detection
- Optimal placement algorithms
- Gap analysis

### Option C: Phase 5 - System Dynamics (1 week)
- Carbon budget tracking
- Feedback loops
- Tipping point detection

**My Recommendation:** Complete 4.5E + 4.5B, then write research paper. Scenarios enable policy analysis without additional features.
