# Configuration System Refactoring Guide

## Overview

The simulation configuration has been refactored from a monolithic `SimulationConfig` class into a modular, maintainable system with preset configurations.

**Problem Solved:** 140-line config file mixing all concerns → Clean separation with presets

---

## New Structure

```
simulation/config/
├── __init__.py                    # Exports for backward compatibility
├── simulation_config.py           # Core config (50 lines)
├── infrastructure_config.py       # Grid, charging, depots
├── agent_config.py               # Agent behavior, social network
├── analytics_config.py           # Analytics & tracking
├── environmental_config.py       # Weather, emissions, air quality
├── policy_config.py              # Policy thresholds, feedback loops
└── presets.py                    # Pre-configured scenarios
```

---

## Usage

### **Option 1: Use Presets (Recommended)**

```python
from simulation.config.presets import ConfigurationPresets

# Load a preset
config = ConfigurationPresets.high_ev_demand()

# Or by name
config = ConfigurationPresets.get_preset('grid_stress_test')

# List available presets
presets = ConfigurationPresets.list_presets()
```

### **Option 2: Build Custom Config**

```python
from simulation.config.presets import ConfigurationPresets

config = ConfigurationPresets.custom_from_params(
    grid_capacity_mw=50,
    eco_desire_mean=0.8,
    num_agents=100,
    initial_ev_adoption=0.25
)
```

### **Option 3: Manual Configuration (Advanced)**

```python
from simulation.config import (
    SimulationConfig,
    InfrastructureConfig,
    AgentConfig,
    AgentBehaviorConfig
)

config = SimulationConfig()

# Configure infrastructure
config.infrastructure = InfrastructureConfig(
    grid_capacity_mw=30.0,
    num_chargers=40,
    allow_dynamic_expansion=True
)

# Configure agents
config.agents.behavior = AgentBehaviorConfig(
    eco_desire_mean=0.8,
    initial_ev_adoption=0.25
)
```

---

## Available Presets

### **1. high_ev_demand** 🔥
**Use When:** You want to see policy actions trigger

**Configuration:**
- Grid: 30 MW (LOW - will trigger expansion)
- Chargers: 30 (limited)
- Agents: 100 with high eco desire (0.8)
- Initial EV: 25%

**Guaranteed Triggers:**
- Grid intervention
- Infrastructure expansion
- Dynamic pricing

---

### **2. grid_stress_test** ⚡
**Use When:** Testing infrastructure resilience

**Configuration:**
- Grid: 20 MW (VERY LOW)
- Chargers: 20 (sparse: 0.5x density)
- Agents: 150 with moderate EV (20%)

**Guaranteed Triggers:**
- Grid critical alerts
- Load balancing
- Surge pricing (3x multiplier)

---

### **3. budget_constrained** 💰
**Use When:** Testing cost-effective decisions

**Configuration:**
- Budget: £500k (tight)
- Expansion cost: £50k per charger (expensive)
- Agents: Mixed cost sensitivity (0.7)
- ROI tracking: Enabled with 8% hurdle rate

**Tests:**
- Budget warnings
- ROI calculations
- Selective expansion
- Cost recovery

---

### **4. rapid_adoption** 🚀
**Use When:** Testing tipping points and feedback loops

**Configuration:**
- Network density: 0.15 (dense social network)
- Social decay: 0.05 (very slow - strong influence)
- Initial EV: 15% (at critical mass threshold)
- Agents: 200

**Tests:**
- Tipping point detection
- Network effects
- Social cascades
- Feedback loops

---

### **5. congestion_management** 🚦
**Use When:** Testing congestion pricing

**Configuration:**
- Congestion enabled
- Transit adoption: 20% initial
- Time sensitivity: 0.7 (high)
- Agents: 150

**Tests:**
- Congestion charges
- Transit investment
- Mode shift

---

### **6. winter_weather_impact** ❄️
**Use When:** Testing weather effects on EVs

**Configuration:**
- Temperature: -10°C adjustment
- Month: January (forced)
- Extra chargers: 70 (1.5x density for range anxiety)
- Comfort desire: 0.7 (high)

**Tests:**
- Range adjustments
- Charging frequency
- Comfort trade-offs

---

### **7. policy_comparison_baseline** 📊
**Use When:** Creating baseline for comparisons

**Configuration:**
- Minimal intervention
- No dynamic expansion
- Current market (5% EV)
- Scenario comparison enabled

---

## Integration with UI

### **Sidebar Integration**

```python
# In sidebar_config.py

from ui.sidebar_presets import render_preset_selector

def build_config():
    # Check if preset is selected
    use_preset, preset_config = render_preset_selector()
    
    if use_preset and preset_config:
        # Use preset configuration
        return preset_config
    else:
        # Build config from individual sliders (existing code)
        config = SimulationConfig()
        # ... configure manually
        return config
```

### **Preset Selector Widget**

The `render_preset_selector()` function provides:
- ✅ Preset dropdown with descriptions
- ✅ Parameter preview
- ✅ Optional overrides
- ✅ Policy trigger warnings

---

## Backward Compatibility

**All existing code continues to work!**

Old code:
```python
config = SimulationConfig()
config.grid_capacity_mw = 50  # Still works
config.num_chargers = 30      # Still works
config.eco_desire_mean = 0.8  # Still works (via @property)
```

Properties automatically delegate to sub-configs:
```python
config.grid_capacity_mw  # → config.infrastructure.grid_capacity_mw
config.eco_desire_mean   # → config.agents.behavior.eco_desire_mean
```

---

## Migration Guide

### **For Existing Code (No Changes Needed)**

All existing code using `SimulationConfig` will continue to work without modification.

### **For New Code (Use Presets)**

Instead of:
```python
config = SimulationConfig()
config.grid_capacity_mw = 30
config.num_agents = 100
config.eco_desire_mean = 0.8
# ... 20 more lines
```

Use:
```python
config = ConfigurationPresets.high_ev_demand()
```

### **For Advanced Customization**

```python
config = ConfigurationPresets.high_ev_demand()

# Override specific parameters
config.num_agents = 200
config.infrastructure.grid_capacity_mw = 40
```

---

## Benefits

### **Before (Problems)**
- ❌ 140-line monolithic config
- ❌ All concerns mixed together
- ❌ Hard to find specific settings
- ❌ No reusable configurations
- ❌ Difficult to maintain

### **After (Solutions)**
- ✅ Modular structure (6 focused files)
- ✅ Clear separation of concerns
- ✅ Easy to navigate
- ✅ 8 pre-configured presets
- ✅ Easy to extend

### **Lines of Code**

| Component | Before | After | Change |
|-----------|--------|-------|--------|
| Core config | 140 | 50 | -64% |
| Infrastructure | Mixed | 38 | New |
| Agent behavior | Mixed | 50 | New |
| Analytics | Mixed | 25 | New |
| Environmental | Mixed | 70 | New |
| Policy | Mixed | 50 | New |
| **Presets** | **0** | **350** | **NEW** |

**Result:** Same functionality + 8 presets, better organized

---

## Testing

### **Test Preset Loading**

```python
from simulation.config.presets import ConfigurationPresets

# Test each preset loads without error
for preset_name in ConfigurationPresets.list_presets():
    config = ConfigurationPresets.get_preset(preset_name)
    assert config is not None
    assert config.num_agents > 0
    assert config.infrastructure.grid_capacity_mw > 0
```

### **Test Backward Compatibility**

```python
from simulation.config import SimulationConfig

config = SimulationConfig()

# Old-style access should still work
config.grid_capacity_mw = 50
assert config.infrastructure.grid_capacity_mw == 50

config.eco_desire_mean = 0.8
assert config.agents.behavior.eco_desire_mean == 0.8
```

---

## Next Steps

### **Phase 5.2 Integration**

1. **Add preset selector to sidebar** ✅ (use `sidebar_presets.py`)
2. **Update main UI to use presets**
3. **Add "Why no triggers?" diagnostic** (uses preset info)
4. **Document presets in UI**

### **Future Enhancements**

1. **User-defined presets** - Save custom configs
2. **Preset comparison** - Compare multiple presets side-by-side
3. **Preset validation** - Check if config will trigger policies
4. **Export/import** - Share configs as YAML files

---

## File Installation

### **Step 1: Replace Core Config**

```bash
cd RTD_SIM
cp /path/to/outputs/simulation_config.py simulation/config/
```

### **Step 2: Add Sub-Configs**

```bash
cp /path/to/outputs/infrastructure_config.py simulation/config/
cp /path/to/outputs/agent_config.py simulation/config/
cp /path/to/outputs/analytics_config.py simulation/config/
cp /path/to/outputs/environmental_config.py simulation/config/
cp /path/to/outputs/policy_config.py simulation/config/
```

### **Step 3: Add Presets**

```bash
cp /path/to/outputs/presets.py simulation/config/
```

### **Step 4: Update __init__.py**

```bash
cp /path/to/outputs/config__init__.py simulation/config/__init__.py
```

### **Step 5: Add UI Component**

```bash
cp /path/to/outputs/sidebar_presets.py ui/
```

### **Step 6: Test**

```bash
python -c "from simulation.config.presets import ConfigurationPresets; print(ConfigurationPresets.list_presets())"
```

Should output:
```
{'default': 'Standard balanced configuration', 'high_ev_demand': 'High EV adoption - guaranteed policy triggers', ...}
```

---

## Questions?

**Q: Will this break existing code?**  
A: No - full backward compatibility via @property delegation

**Q: Do I have to use presets?**  
A: No - manual configuration still works

**Q: Can I modify a preset?**  
A: Yes - load preset, then override specific parameters

**Q: How do I add a new preset?**  
A: Add a new @staticmethod to ConfigurationPresets class

**Q: Can I save my own presets?**  
A: Not yet - planned for future enhancement

---

## Summary

✅ **Cleaner code** - Modular structure  
✅ **Easier maintenance** - Focused files  
✅ **Better UX** - Presets for common scenarios  
✅ **Backward compatible** - No code changes needed  
✅ **Phase 5.2 ready** - Integrates with UI controls  

This refactoring sets the foundation for Phase 5.2 interactive controls while making the codebase more maintainable long-term.
