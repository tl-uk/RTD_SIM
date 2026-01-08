# Phase 4.5F + 4.5C Testing and Validation Guide

## 🎯 Overview

This guide covers testing for:
- **Phase 4.5F**: Expanded freight modes (cargo bikes, trucks, HGVs, hydrogen)
- **Phase 4.5C**: Time-of-day pricing and smart charging

---

## 📦 Phase 4.5F: Expanded Freight Modes

### Installation Steps

1. **Replace `agent/bdi_planner.py`** with the expanded version
2. **Update `simulation/metrics_calculator.py`** with new costs/emissions
3. **Replace `agent/job_contexts.yaml`** with expanded freight jobs
4. **Update `visualiser/visualization.py`** with new mode colors
5. **Add new scenario files** to `scenarios/configs/`

### Testing Freight Modes

#### Test 1: Micro-Delivery (Cargo Bikes)
```python
# Expected behavior:
- Agents with job_story_id='urban_food_delivery' should use 'cargo_bike'
- Distance < 10km only
- High time priority (urgency=high)

# To test:
1. Create agents with 'urban_food_delivery' job
2. Check mode distribution: expect 60-80% cargo_bike for these agents
3. Verify distance constraint: no cargo bikes on trips > 10km
```

#### Test 2: Medium Freight (Trucks)
```python
# Expected behavior:
- Agents with 'regional_distribution' job should use trucks
- Distance 50-300km range
- Mix of electric and diesel based on subsidies

# To test:
1. Create agents with 'regional_distribution' job
2. Check mode split: expect 30-40% truck_electric with subsidy
3. Verify no trucks on short trips < 20km
```

#### Test 3: Heavy Freight (HGVs)
```python
# Expected behavior:
- Agents with 'long_haul_freight' job should use HGVs
- Distance > 400km for long haul
- Diesel dominant without subsidy
- Hydrogen viable with 45% subsidy

# To test:
1. Create agents with 'long_haul_freight' job
2. Baseline: expect 95%+ hgv_diesel
3. With hydrogen subsidy: expect 10-15% hgv_hydrogen
4. With e-HGV subsidy: expect 15-20% hgv_electric
```

### Validation Metrics

#### Mode Distribution Check
```python
# After running simulation with freight agents:

freight_agents = [a for a in agents if a.agent_context.get('vehicle_required')]
mode_counts = Counter(a.state.mode for a in freight_agents)

# Expected ranges (with no policies):
assert mode_counts['van_diesel'] > mode_counts['van_electric']  # Diesel cheaper
assert mode_counts['hgv_diesel'] > mode_counts['hgv_electric']  # Much cheaper
assert mode_counts['truck_diesel'] > mode_counts['truck_electric']  # Cheaper

# Expected ranges (with freight electrification scenario):
assert mode_counts['van_electric'] > mode_counts['van_diesel']  # Electric subsidized
assert mode_counts['truck_electric'] >= mode_counts['truck_diesel'] * 0.5  # Competitive
```

#### Distance Constraint Check
```python
# Verify modes respect distance limits:

for agent in agents:
    distance = agent.state.distance_km
    mode = agent.state.mode
    
    if mode == 'cargo_bike':
        assert distance < 10.0, f"Cargo bike exceeded range: {distance}km"
    
    if mode == 'van_electric':
        assert distance < 200.0, f"E-van exceeded range: {distance}km"
    
    if mode == 'hgv_electric':
        assert distance < 300.0, f"E-HGV exceeded range: {distance}km"
```

#### Cost Function Check
```python
# Verify freight bonus is applied:

from agent.bdi_planner import BDIPlanner

planner = BDIPlanner()
context = {'priority': 'commercial', 'vehicle_type': 'commercial'}

# Create mock action for van_electric
scores = planner.evaluate_actions(env, state, desires, origin, dest, context)

# Find van_electric score
van_score = next(s for s in scores if s.action.mode == 'van_electric')

# Check that commercial freight gets 30% discount
# (This is implicit in the cost function, harder to test directly)
```

---

## ⚡ Phase 4.5C: Time-of-Day Pricing

### Installation Steps

1. **Create** `simulation/infrastructure/time_of_day_pricing.py`
2. **Update** `simulation/infrastructure/infrastructure_manager.py` with new methods
3. **Add** time-of-day scenario YAML files
4. **Update** `simulation_runner.py` to enable TOD pricing flag

### Testing Time-of-Day Pricing

#### Test 1: Price Variation
```python
from simulation.infrastructure.time_of_day_pricing import TimeOfDayPricingManager

pricing = TimeOfDayPricingManager(base_price_per_kwh=0.16)

# Test price at different times
night_price = pricing.get_price_at_time(3)    # 3 AM
peak_price = pricing.get_price_at_time(18)    # 6 PM
midday_price = pricing.get_price_at_time(12)  # Noon

assert night_price < midday_price < peak_price
assert night_price == 0.08  # 0.5x base
assert peak_price == 0.28   # 1.75x base
assert midday_price == 0.16  # 1.0x base

print(f"✅ Price variation working: Night={night_price}, Peak={peak_price}")
```

#### Test 2: Charging Cost Calculation
```python
# Test multi-hour charging cost

energy_kwh = 50.0  # 50 kWh battery
start_hour = 22    # 10 PM
duration_hours = 8  # Charge overnight

cost = pricing.calculate_charging_cost(energy_kwh, start_hour, duration_hours)

# Should be cheaper than peak charging
peak_cost = energy_kwh * peak_price

assert cost < peak_cost
print(f"✅ Overnight charging cheaper: £{cost:.2f} vs £{peak_cost:.2f}")
```

#### Test 3: Smart Charging Optimization
```python
from simulation.infrastructure.time_of_day_pricing import SmartChargingOptimizer

optimizer = SmartChargingOptimizer(pricing_manager=pricing)

# Schedule charging session
session = optimizer.schedule_charging(
    agent_id='agent_001',
    vehicle_mode='ev',
    energy_needed_kwh=50.0,
    charging_rate_kw=7.0,
    urgency='flexible',
    earliest_hour=18,  # Available from 6 PM
    latest_hour=8      # Need by 8 AM
)

# Should schedule for night hours (cheapest)
assert session.scheduled_start >= 22 or session.scheduled_start <= 6
print(f"✅ Smart charging scheduled for: {session.scheduled_start:02d}:00")
print(f"   Estimated cost: £{session.estimated_cost:.2f}")
```

#### Test 4: Cost Savings
```python
# Compare immediate vs optimal charging

immediate_cost = pricing.calculate_charging_cost(50.0, 18, 8)  # Start at 6 PM
optimal_start, optimal_cost = pricing.find_optimal_charging_window(
    energy_kwh=50.0,
    charging_rate_kw=7.0,
    earliest_hour=18,
    latest_hour=23,
    required_completion_hour=8
)

savings = immediate_cost - optimal_cost
savings_pct = (savings / immediate_cost) * 100

assert savings > 0
assert optimal_start >= 22  # Should start at night

print(f"✅ Cost savings: £{savings:.2f} ({savings_pct:.1f}%)")
print(f"   Immediate: £{immediate_cost:.2f} at 18:00")
print(f"   Optimal: £{optimal_cost:.2f} at {optimal_start:02d}:00")
```

### Validation Metrics

#### Grid Load Profile Check
```python
# After running simulation with smart charging:

load_profile = optimizer.get_load_profile(hours_ahead=24)

# Verify load shifted to off-peak
night_load = sum(load_profile[h] for h in range(0, 6))
peak_load = sum(load_profile[h] for h in range(17, 20))

assert night_load > peak_load, "Load should shift to off-peak"
print(f"✅ Load shifting working: Night={night_load:.1f}kW, Peak={peak_load:.1f}kW")
```

#### Agent Behavior Check
```python
# Verify agents with low cost sensitivity use smart charging

flexible_agents = [a for a in agents if a.desires.get('cost', 0) > 0.6]
scheduled_charging = [a for a in flexible_agents if hasattr(a, 'charging_scheduled')]

adoption_rate = len(scheduled_charging) / len(flexible_agents)

assert adoption_rate > 0.5, "At least 50% of cost-sensitive agents should use smart charging"
print(f"✅ Smart charging adoption: {adoption_rate:.1%}")
```

---

## 🧪 Comprehensive Integration Tests

### Test Scenario 1: Complete Supply Chain Electrification
```bash
# Run scenario:
scenario_name = "Complete Supply Chain Electrification"

# Expected outcomes:
- Van electric: 60%+ adoption
- Truck electric: 35%+ adoption
- HGV electric: 20%+ adoption
- Cargo bike: 70%+ for micro-delivery jobs
- Total freight emissions: -50%
```

### Test Scenario 2: Combined Freight + Smart Charging
```bash
# Run scenario:
scenario_name = "Combined Freight Electrification + Smart Charging"

# Expected outcomes:
- Van electric: 70%+ adoption
- Overnight charging: 80%+ of sessions
- Cost savings: 35%+ vs immediate charging
- Grid efficiency: +30%
```

### Test Scenario 3: Hydrogen HGV Pilot
```bash
# Run scenario:
scenario_name = "Hydrogen HGV Pilot Program"

# Expected outcomes:
- HGV hydrogen: 10-15% adoption
- HGV electric: 15-20% adoption
- Long-haul emissions: -30%
- Technology comparison data available
```

---

## 📊 Key Performance Indicators (KPIs)

### Freight Electrification (Phase 4.5F)
```python
# Calculate KPIs:

freight_modes = ['van_electric', 'van_diesel', 'truck_electric', 'truck_diesel', 
                'hgv_electric', 'hgv_diesel', 'hgv_hydrogen', 'cargo_bike']

freight_agents = [a for a in agents if a.state.mode in freight_modes]

electric_freight = [a for a in freight_agents 
                    if 'electric' in a.state.mode or a.state.mode == 'cargo_bike']

electrification_rate = len(electric_freight) / len(freight_agents)

print(f"Freight Electrification Rate: {electrification_rate:.1%}")
# Target: 40-50% with aggressive policies
```

### Smart Charging (Phase 4.5C)
```python
# Calculate KPIs:

tod_metrics = infrastructure.get_tod_pricing_metrics()

print(f"Off-peak charging: {tod_metrics['smart_charging']['offpeak_percentage']:.1%}")
print(f"Cost savings: £{tod_metrics['smart_charging']['savings']:.2f}")
print(f"Grid stress reduction: {tod_metrics['grid_stress_reduction']:.1%}")

# Targets:
# - Off-peak charging: 60%+
# - Cost savings: 25%+
# - Grid stress reduction: 20%+
```

---

## 🐛 Common Issues and Fixes

### Issue 1: Freight agents not using freight modes
```python
# Debug:
for agent in agents[:10]:
    print(f"{agent.state.agent_id}: job={agent.job_story_id}, "
          f"context={agent.agent_context}, mode={agent.state.mode}")

# Fix: Check that job_contexts.yaml has vehicle_required: true
```

### Issue 2: No cost variation with TOD pricing
```python
# Debug:
print(f"TOD pricing enabled: {infrastructure.enable_tod_pricing}")
print(f"Current hour: {infrastructure.current_hour}")
print(f"Current price: {infrastructure.tod_pricing.get_price_at_time(infrastructure.current_hour)}")

# Fix: Ensure update_time() is called in simulation loop
```

### Issue 3: All agents charging immediately
```python
# Debug:
print(f"Smart charging enabled: {infrastructure.smart_charging is not None}")

# Fix: Ensure use_smart_charging=True when calling charge_vehicle()
```

---

## ✅ Final Validation Checklist

### Before Considering Phase 4.5F Complete:
- [ ] All 8 freight modes working (cargo_bike, van_electric, van_diesel, truck_electric, truck_diesel, hgv_electric, hgv_diesel, hgv_hydrogen)
- [ ] Distance constraints enforced for all modes
- [ ] Freight agents correctly filtered by vehicle_type
- [ ] Cost bonuses applied to freight modes
- [ ] All mode colors showing in visualization
- [ ] At least 3 comprehensive freight scenarios working
- [ ] Mode adoption matches expected ranges

### Before Considering Phase 4.5C Complete:
- [ ] Time-of-day pricing varying correctly (0.5x to 1.75x base)
- [ ] Smart charging optimizer scheduling off-peak
- [ ] Cost savings measurable (20%+ for flexible agents)
- [ ] Grid load shifting observable
- [ ] Integration with freight modes working
- [ ] At least 3 TOD pricing scenarios working
- [ ] Metrics dashboard showing TOD data

---

## 🚀 Next Steps After Validation

Once both Phase 4.5F and 4.5C are validated:

1. **Combine policies** for comprehensive testing
2. **Run sensitivity analysis** on subsidy levels
3. **Generate research outputs** (charts, tables, reports)
4. **Document findings** for academic paper
5. **Proceed to Phase 5**: Long-term carbon budgets and system dynamics

---

## 📚 Quick Reference

### Mode Hierarchy (First Mile → Last Mile)
```
Inbound Freight:        Port → hgv_diesel/electric/hydrogen → Warehouse
Regional Distribution:  Warehouse → truck_diesel/electric → Distribution Center
Urban Delivery:         Distribution Center → van_diesel/electric → Store
Last Mile:              Store/Depot → cargo_bike → Customer
```

### Cost Hierarchy (Cheapest → Most Expensive)
```
Nighttime:     £0.08/kWh (0.5x)
Off-peak:      £0.12/kWh (0.75x)
Standard:      £0.16/kWh (1.0x)
Peak:          £0.28/kWh (1.75x)
```

### Testing Priority Order
```
1. Mode distance constraints (critical)
2. Freight mode selection (critical)
3. Cost function bonuses (important)
4. Time-of-day price variation (important)
5. Smart charging optimization (nice to have)
6. Grid load shifting (nice to have)
```
