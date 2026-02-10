# Manual Installation Guide

## Quick Install (Copy-Paste Commands)

```bash
# 1. Navigate to RTD_SIM directory
cd /path/to/RTD_SIM

# 2. Backup existing config (optional but recommended)
cp -r simulation/config simulation/config.backup.$(date +%Y%m%d)

# 3. Copy new config files (replace /path/to/outputs with actual path)
cp /path/to/outputs/simulation_config.py simulation/config/
cp /path/to/outputs/infrastructure_config.py simulation/config/
cp /path/to/outputs/agent_config.py simulation/config/
cp /path/to/outputs/analytics_config.py simulation/config/
cp /path/to/outputs/environmental_config.py simulation/config/
cp /path/to/outputs/policy_config.py simulation/config/
cp /path/to/outputs/presets.py simulation/config/
cp /path/to/outputs/config__init__.py simulation/config/__init__.py

# 4. Copy UI component
cp /path/to/outputs/sidebar_presets.py ui/

# 5. Test installation
python3 -c "from simulation.config.presets import ConfigurationPresets; print('✅ Installation successful!'); print('Available presets:', list(ConfigurationPresets.list_presets().keys()))"
```

## Files to Copy

| Source File | Destination | Purpose |
|------------|-------------|---------|
| `simulation_config.py` | `simulation/config/` | Core config (refactored) |
| `infrastructure_config.py` | `simulation/config/` | Grid, charging, depots |
| `agent_config.py` | `simulation/config/` | Agent behavior, social network |
| `analytics_config.py` | `simulation/config/` | Analytics settings |
| `environmental_config.py` | `simulation/config/` | Weather, emissions |
| `policy_config.py` | `simulation/config/` | Policy thresholds |
| `presets.py` | `simulation/config/` | **NEW** - Preset configurations |
| `config__init__.py` | `simulation/config/__init__.py` | Module exports |
| `sidebar_presets.py` | `ui/` | **NEW** - UI preset selector |

## Verification

After installation, verify everything works:

```python
# Test 1: Import config
from simulation.config import SimulationConfig
config = SimulationConfig()
print("✓ SimulationConfig imports")

# Test 2: Import presets
from simulation.config.presets import ConfigurationPresets
presets = ConfigurationPresets.list_presets()
print(f"✓ Found {len(presets)} presets")

# Test 3: Load a preset
config = ConfigurationPresets.high_ev_demand()
print(f"✓ Loaded preset: {config.num_agents} agents, {config.infrastructure.grid_capacity_mw}MW grid")

# Test 4: Backward compatibility
config = SimulationConfig()
config.grid_capacity_mw = 50  # Old-style access
assert config.infrastructure.grid_capacity_mw == 50
print("✓ Backward compatibility works")
```

Expected output:
```
✓ SimulationConfig imports
✓ Found 8 presets
✓ Loaded preset: 100 agents, 30.0MW grid
✓ Backward compatibility works
```

## Troubleshooting

### Import Error: "No module named 'infrastructure_config'"

**Cause:** Files not in correct location

**Fix:**
```bash
# Check files are in simulation/config/
ls -la simulation/config/*.py

# Should see:
# __init__.py
# simulation_config.py
# infrastructure_config.py
# agent_config.py
# analytics_config.py
# environmental_config.py
# policy_config.py
# presets.py
```

### Import Error: "cannot import name 'ConfigurationPresets'"

**Cause:** `__init__.py` not updated

**Fix:**
```bash
# Make sure you copied config__init__.py to __init__.py
cp /path/to/outputs/config__init__.py simulation/config/__init__.py
```

### AttributeError: "'InfrastructureConfig' object has no attribute 'X'"

**Cause:** Using old config file

**Fix:**
```bash
# Verify you have the new file:
head -n 5 simulation/config/infrastructure_config.py

# Should show:
# """
# simulation/config/infrastructure_config.py
# 
# Infrastructure-specific configuration.
```

## Rollback (If Needed)

If something goes wrong, restore from backup:

```bash
# Remove new files
rm simulation/config/presets.py
rm ui/sidebar_presets.py

# Restore from backup
cp simulation/config.backup.YYYYMMDD/* simulation/config/
```

## Success!

Once installed, you can use presets like this:

```python
from simulation.config.presets import ConfigurationPresets

# Load preset
config = ConfigurationPresets.high_ev_demand()

# Run simulation
from simulation.simulation_runner import run_simulation
results = run_simulation(config)
```

Or in the UI, use the preset selector in the sidebar!
