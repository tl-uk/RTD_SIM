# RTD_SIM Configuration Refactoring Package

**Version:** 1.0  
**Date:** February 10, 2026  
**Phase:** 5.2 - Interactive Policy Configuration

---

## 📦 What's in This Package

This package refactors the RTD_SIM configuration system from a monolithic 140-line file into a modular, maintainable structure with 8 preset configurations.

### **Problem Solved**
- ❌ 140-line `SimulationConfig` mixing all concerns
- ❌ Difficult to maintain and extend
- ❌ No easy way to configure scenarios that trigger policies
- ❌ Users don't know why policies aren't triggering

### **Solution**
- ✅ 6 focused config modules (infrastructure, agents, analytics, environment, policy)
- ✅ 8 pre-configured presets
- ✅ Full backward compatibility
- ✅ UI preset selector component

---

## 🚀 Quick Start

### Option 1: Automated Install (Recommended)

```bash
# 1. Extract package
unzip config_refactor_package.zip -d config_refactor

# 2. Run installer
cd /path/to/RTD_SIM
bash config_refactor/install_config_refactor.sh
```

### Option 2: Manual Install

See `MANUAL_INSTALL.md` for step-by-step instructions.

---

## 📁 Package Contents

| File | Purpose |
|------|---------|
| **Code Files** | |
| `simulation_config.py` | Core config (refactored, 50 lines) |
| `infrastructure_config.py` | Grid, charging, depot settings |
| `agent_config.py` | Agent behavior, social network |
| `analytics_config.py` | Analytics & tracking settings |
| `environmental_config.py` | Weather, emissions, air quality |
| `policy_config.py` | Policy thresholds, feedback loops |
| `presets.py` | **8 preset configurations** ⭐ |
| `config__init__.py` | Module exports |
| `sidebar_presets.py` | UI component for sidebar |
| **Installation** | |
| `install_config_refactor.sh` | Automated installer |
| **Documentation** | |
| `CONFIG_REFACTORING_GUIDE.md` | Complete guide (10,000 words) |
| `MANUAL_INSTALL.md` | Step-by-step manual install |
| `PRESET_QUICK_REFERENCE.md` | Preset cheat sheet |
| `README.md` | This file |

---

## 🎯 Available Presets

1. **high_ev_demand** 🔥 - Guaranteed policy triggers (30MW grid, 25% EV)
2. **grid_stress_test** ⚡ - Infrastructure limits (20MW grid, sparse chargers)
3. **budget_constrained** 💰 - Cost optimization (£500k budget, 8% hurdle rate)
4. **rapid_adoption** 🚀 - Social cascades (dense network, strong influence)
5. **congestion_management** 🚦 - Traffic & transit (congestion pricing)
6. **winter_weather_impact** ❄️ - Cold weather (-10°C, range reduction)
7. **policy_comparison_baseline** 📊 - Business as usual (5% EV, no intervention)
8. **default** 📐 - Standard balanced config

---

## ✅ Features

### **Modular Structure**
```
Before: 1 file × 140 lines = Hard to maintain
After:  7 files × ~30 lines each = Easy to navigate
```

### **Preset System**
```python
# Instead of this:
config = SimulationConfig()
config.grid_capacity_mw = 30
config.num_chargers = 40
config.num_agents = 100
config.eco_desire_mean = 0.8
# ... 15 more lines

# Do this:
config = ConfigurationPresets.high_ev_demand()
```

### **UI Integration**
```python
# In sidebar_config.py:
from ui.sidebar_presets import render_preset_selector

use_preset, config = render_preset_selector()
if use_preset:
    # User selected a preset!
    run_simulation(config)
```

### **Backward Compatible**
```python
# Old code still works!
config = SimulationConfig()
config.grid_capacity_mw = 50  # ✅ Still works via @property
```

---

## 📖 Documentation

### **For Installation**
→ Read `MANUAL_INSTALL.md`

### **For Understanding the Refactoring**
→ Read `CONFIG_REFACTORING_GUIDE.md`

### **For Quick Preset Usage**
→ Read `PRESET_QUICK_REFERENCE.md`

---

## 🧪 Testing After Install

```python
# Test 1: Import
from simulation.config import SimulationConfig
print("✓ Config imports")

# Test 2: Presets
from simulation.config.presets import ConfigurationPresets
presets = ConfigurationPresets.list_presets()
print(f"✓ Found {len(presets)} presets")

# Test 3: Load preset
config = ConfigurationPresets.high_ev_demand()
print(f"✓ Loaded: {config.num_agents} agents, {config.infrastructure.grid_capacity_mw}MW")

# Test 4: Backward compatibility
config = SimulationConfig()
config.grid_capacity_mw = 50
assert config.infrastructure.grid_capacity_mw == 50
print("✓ Backward compatibility works")
```

Expected output:
```
✓ Config imports
✓ Found 8 presets
✓ Loaded: 100 agents, 30.0MW
✓ Backward compatibility works
```

---

## 🔧 Customization

### Modify a Preset
```python
config = ConfigurationPresets.high_ev_demand()
config.num_agents = 200  # Override
config.infrastructure.grid_capacity_mw = 40
```

### Create Custom Config
```python
config = ConfigurationPresets.custom_from_params(
    grid_capacity_mw=50,
    eco_desire_mean=0.8,
    num_agents=100
)
```

### Add Your Own Preset
Edit `presets.py`:
```python
@staticmethod
def my_custom_preset() -> SimulationConfig:
    config = SimulationConfig()
    # ... configure ...
    return config
```

---

## 🎁 Benefits

| Before | After |
|--------|-------|
| 140-line monolithic file | 7 focused modules |
| Hard to find settings | Clear organization |
| No reusable configs | 8 presets |
| Manual parameter tweaking | One-line preset loading |
| Users confused why policies don't trigger | Presets guaranteed to trigger |

---

## 🚀 Phase 5.2 Integration

This refactoring is **Phase 5.2: Interactive Policy Configuration**

### Next Steps
1. ✅ Install this package
2. 📝 Add preset selector to sidebar
3. 🎨 Add "Why no triggers?" diagnostic
4. 📊 Test with different presets
5. 🎯 Proceed to Phase 5.3 (System Dynamics)

The preset system makes Phase 5.3 much easier - you can now test feedback loops and system dynamics with different initial conditions via simple preset selection!

---

## 📞 Support

**Problems?**
- Check `MANUAL_INSTALL.md` for troubleshooting
- Verify Python imports work
- Check file permissions

**Questions?**
- Read `CONFIG_REFACTORING_GUIDE.md` for detailed explanations
- Check `PRESET_QUICK_REFERENCE.md` for preset details

---

## 📄 License

Same as RTD_SIM project.

---

## ✨ Summary

**Install this package to:**
- ✅ Clean up your config system
- ✅ Get 8 ready-to-use presets
- ✅ Enable UI preset selection
- ✅ Make Phase 5.3 development easier
- ✅ Help users understand policy triggers

**Total time:** ~10 minutes to install and test

**Backward compatible:** Yes - all existing code works

**Ready to use:** Immediately after installation

---

🎉 **Happy Simulating!**
