# Preset Configuration Quick Reference

## 🚀 One-Line Usage

```python
from simulation.config.presets import ConfigurationPresets
config = ConfigurationPresets.PRESET_NAME()
```

---

## 📋 Available Presets

### 1️⃣ **high_ev_demand** - GUARANTEED POLICY TRIGGERS 🔥

**When to use:** Want to see policy actions in action

```python
config = ConfigurationPresets.high_ev_demand()
```

| Parameter | Value | Why |
|-----------|-------|-----|
| Grid | 30 MW | LOW - triggers expansion |
| Chargers | 30 | Limited supply |
| Agents | 100 | High load |
| Eco Desire | 0.8 | Very eco-conscious |
| Initial EV | 25% | High adoption |

**Triggers:**
- ✅ Grid intervention @ 60% utilization
- ✅ Infrastructure expansion
- ✅ Dynamic pricing

---

### 2️⃣ **grid_stress_test** - INFRASTRUCTURE LIMITS ⚡

**When to use:** Testing grid resilience

```python
config = ConfigurationPresets.grid_stress_test()
```

| Parameter | Value | Why |
|-----------|-------|-----|
| Grid | 20 MW | VERY LOW - stress test |
| Chargers | 20 (0.5x density) | Sparse |
| Agents | 150 | High load |
| EV Adoption | 20% | Moderate |

**Triggers:**
- ✅ Grid critical alerts
- ✅ Load balancing
- ✅ Surge pricing (3x)

---

### 3️⃣ **budget_constrained** - COST OPTIMIZATION 💰

**When to use:** Testing ROI and cost-effective decisions

```python
config = ConfigurationPresets.budget_constrained()
```

| Parameter | Value | Why |
|-----------|-------|-----|
| Budget | £500k | Tight constraints |
| Expansion Cost | £50k/charger | Expensive |
| Cost Sensitivity | 0.7 | Agents care about cost |
| ROI Hurdle Rate | 8% | High bar |

**Tests:**
- ✅ Budget warnings
- ✅ ROI calculations
- ✅ Selective expansion
- ✅ Cost recovery tracking

---

### 4️⃣ **rapid_adoption** - TIPPING POINTS 🚀

**When to use:** Testing social cascades and feedback loops

```python
config = ConfigurationPresets.rapid_adoption()
```

| Parameter | Value | Why |
|-----------|-------|-----|
| Agents | 200 | Large population |
| Network Density | 0.15 | Dense connections |
| Social Decay | 0.05 | Strong influence |
| Initial EV | 15% | At critical mass |
| Eco Variance | 0.25 | HIGH - diverse opinions |

**Tests:**
- ✅ Tipping point detection
- ✅ Network effects
- ✅ Social cascades
- ✅ Feedback loops

---

### 5️⃣ **congestion_management** - TRAFFIC & TRANSIT 🚦

**When to use:** Congestion pricing scenarios

```python
config = ConfigurationPresets.congestion_management()
```

| Parameter | Value | Why |
|-----------|-------|-----|
| Congestion | Enabled | Main feature |
| Transit Adoption | 20% | Baseline |
| Time Sensitivity | 0.7 | Agents care about time |
| Agents | 150 | Urban density |

**Triggers:**
- ✅ Congestion charges @ 75%
- ✅ Transit investment
- ✅ Mode shift

---

### 6️⃣ **winter_weather_impact** - COLD WEATHER ❄️

**When to use:** Testing EV range in winter

```python
config = ConfigurationPresets.winter_weather_impact()
```

| Parameter | Value | Why |
|-----------|-------|-----|
| Temperature | -10°C | Cold weather |
| Month | January | Winter |
| Chargers | 70 (1.5x) | Range anxiety mitigation |
| Comfort Desire | 0.7 | Important in winter |

**Tests:**
- ✅ Range adjustments
- ✅ Charging frequency
- ✅ Comfort trade-offs

---

### 7️⃣ **policy_comparison_baseline** - BUSINESS AS USUAL 📊

**When to use:** Creating comparison baseline

```python
config = ConfigurationPresets.policy_comparison_baseline()
```

| Parameter | Value | Why |
|-----------|-------|-----|
| Expansion | Disabled | No intervention |
| EV Adoption | 5% | Current market |
| Eco Desire | 0.4 | Average |

**Use for:**
- Baseline scenario
- Policy impact comparison
- Before/after analysis

---

### 8️⃣ **default** - STANDARD CONFIG 📐

**When to use:** Balanced starting point

```python
config = ConfigurationPresets.default()
# Same as: config = SimulationConfig()
```

---

## 🎨 Custom Configuration

Build from parameters:

```python
config = ConfigurationPresets.custom_from_params(
    grid_capacity_mw=50,
    num_agents=100,
    eco_desire_mean=0.8,
    initial_ev_adoption=0.25,
    grid_intervention_threshold=0.6
)
```

**Supported parameters:**
- `grid_capacity_mw`
- `num_chargers`
- `charger_density_multiplier`
- `eco_desire_mean`
- `cost_sensitivity_mean`
- `initial_ev_adoption`
- `grid_intervention_threshold`
- `ev_adoption_target`
- `budget_limit`
- `num_agents`
- `steps`

---

## 🔧 Modifying Presets

Load preset, then override:

```python
config = ConfigurationPresets.high_ev_demand()

# Override specific values
config.num_agents = 200
config.infrastructure.grid_capacity_mw = 40
config.agents.behavior.eco_desire_mean = 0.9
```

---

## 📊 Preset Comparison Matrix

| Preset | Grid | Agents | Initial EV | Eco | Purpose |
|--------|------|--------|-----------|-----|---------|
| **high_ev_demand** | 30 MW | 100 | 25% | 0.8 | Policy triggers |
| **grid_stress** | 20 MW | 150 | 20% | 0.6 | Infrastructure stress |
| **budget_constrained** | 100 MW | 50 | 15% | 0.5 | Cost optimization |
| **rapid_adoption** | 150 MW | 200 | 15% | 0.7 | Social cascades |
| **congestion** | 100 MW | 150 | 10% | 0.6 | Traffic management |
| **winter** | 100 MW | 50 | 20% | 0.6 | Weather impact |
| **baseline** | 100 MW | 50 | 5% | 0.4 | Comparison |
| **default** | 1000 MW | 50 | 5% | 0.5 | Standard |

---

## 💡 Tips

**Want policy actions to trigger?**
→ Use `high_ev_demand` or `grid_stress_test`

**Want to test social influence?**
→ Use `rapid_adoption`

**Want to test ROI?**
→ Use `budget_constrained`

**Want realistic baseline?**
→ Use `policy_comparison_baseline`

**Not sure?**
→ Start with `default`, then switch to specific preset

---

## 🔍 Listing Presets Programmatically

```python
from simulation.config.presets import ConfigurationPresets

# Get all presets with descriptions
presets = ConfigurationPresets.list_presets()
for name, description in presets.items():
    print(f"{name}: {description}")

# Load by name
config = ConfigurationPresets.get_preset('high_ev_demand')
```

---

## ✅ Quick Start Recipe

```python
# 1. Import
from simulation.config.presets import ConfigurationPresets

# 2. Choose preset
config = ConfigurationPresets.high_ev_demand()

# 3. (Optional) Tweak
config.num_agents = 150

# 4. Run simulation
from simulation.simulation_runner import run_simulation
results = run_simulation(config)

# 5. See policies trigger! 🎉
```
