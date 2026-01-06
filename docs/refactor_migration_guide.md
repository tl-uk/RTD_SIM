# Simulation Runner Refactoring - Migration Guide

## Overview

Refactoring `simulation_runner.py` from **1194 lines** to **modular architecture** (150 lines orchestrator + 6 modules).

**Time Required:** 30 minutes

---

## File Structure

### Create These Directories
```bash
cd simulation/
mkdir -p config setup routing execution analysis
touch config/__init__.py
touch setup/__init__.py  
touch routing/__init__.py
touch execution/__init__.py
touch analysis/__init__.py
```

### Module Mapping

| New Module | Lines | Purpose | Extracted From |
|------------|-------|---------|----------------|
| `config/simulation_config.py` | 100 | Config classes | SimulationConfig, SimulationResults |
| `routing/route_diversity.py` | 150 | Route strategies | 3 route diversity functions |
| `setup/environment_setup.py` | 200 | Env & infra setup | setup_environment, setup_infrastructure |
| `setup/agent_creation.py` | 250 | Agent population | create_agents, create_planner |
| `setup/network_setup.py` | 100 | Social network | setup_social_network |
| `execution/simulation_loop.py` | 300 | Main loop | run_simulation loop code |
| `analysis/scenario_comparison.py` | 150 | Scenarios | list_scenarios, compare_scenarios |

---

## Migration Steps

### Step 1: Backup Current File (1 min)
```bash
cd simulation/
cp simulation_runner.py simulation_runner.py.backup
```

### Step 2: Create Module Files (5 min)

I've provided these artifacts:
1. ✅ `config/simulation_config.py` 
2. ✅ `routing/route_diversity.py`
3. ✅ `setup/environment_setup.py`

**Still need to create:**
4. `setup/agent_creation.py` - Extract `create_agents()` and `create_planner()`
5. `setup/network_setup.py` - Extract `setup_social_network()`
6. `execution/simulation_loop.py` - Extract main simulation loop
7. `analysis/scenario_comparison.py` - Extract scenario functions

### Step 3: Copy Functions to Modules (10 min)

#### A. Create `setup/agent_creation.py`
Copy these functions from `simulation_runner.py`:
- `create_planner()`
- `create_agents()`

Add imports at top:
```python
import secrets
import random
import logging
from typing import List, Dict, Tuple, Any

from agent.bdi_planner import BDIPlanner
from simulation.config.simulation_config import SimulationConfig
```

#### B. Create `setup/network_setup.py`
Copy this function:
- `setup_social_network()`

Add imports:
```python
import logging
from typing import List, Tuple, Optional, Any

from simulation.config.simulation_config import SimulationConfig
```

#### C. Create `execution/simulation_loop.py`
Copy these functions:
- Main loop code from `run_simulation()` (the `for step in range(config.steps):` section)
- `apply_scenario_policies()`

Create new function:
```python
def run_simulation_loop(
    config, agents, env, infrastructure, network, influence_system, progress_callback=None
) -> dict:
    """Execute main simulation loop and return results."""
    # ... paste loop code here ...
    
    return {
        'time_series': time_series,
        'adoption_history': adoption_history,
        'cascade_events': cascade_events
    }
```

#### D. Create `analysis/scenario_comparison.py`
Copy these functions:
- `list_available_scenarios()`
- `get_scenario_info()`
- `compare_scenarios()`

### Step 4: Create New Orchestrator (5 min)

Replace `simulation_runner.py` with:

```python
"""
simulation/simulation_runner.py

Main simulation orchestrator - delegates to specialized modules.
"""

from simulation.config.simulation_config import SimulationConfig, SimulationResults
from simulation.setup.environment_setup import setup_environment, setup_infrastructure
from simulation.setup.agent_creation import create_agents, create_planner
from simulation.setup.network_setup import setup_social_network
from simulation.execution.simulation_loop import run_simulation_loop, apply_scenario_policies
from simulation.routing.route_diversity import apply_route_diversity
from simulation.analysis.scenario_comparison import (
    list_available_scenarios,
    get_scenario_info,
    compare_scenarios
)

import logging
logger = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = [
    'SimulationConfig',
    'SimulationResults',
    'run_simulation',
    'list_available_scenarios',
    'get_scenario_info',
    'compare_scenarios'
]


def run_simulation(config: SimulationConfig, progress_callback=None) -> SimulationResults:
    """
    Execute complete simulation (orchestrator only).
    
    Delegates to specialized modules for each phase.
    """
    results = SimulationResults()
    
    try:
        # 1. Setup environment
        env = setup_environment(config, progress_callback)
        results.env = env
        
        # 2. Apply route diversity
        if config.use_osm and config.enable_route_diversity:
            env = apply_route_diversity(env, mode=config.route_diversity_mode)
            logger.info(f"✅ Route diversity: {config.route_diversity_mode}")
        
        # 3. Setup infrastructure
        infrastructure = setup_infrastructure(config, progress_callback)
        results.infrastructure = infrastructure
        
        # 4. Create planner
        planner = create_planner(infrastructure)
        
        # 5. Apply scenario policies
        scenario_report = apply_scenario_policies(config, env, progress_callback)
        results.scenario_report = scenario_report
        
        # 6. Create agents
        agents, desire_std = create_agents(config, env, planner, progress_callback)
        results.desire_std = desire_std
        results.agents = agents
        
        # 7. Setup social network
        network, influence_system = setup_social_network(config, agents, progress_callback)
        results.network = network
        results.influence_system = influence_system
        
        # 8. Run simulation loop
        loop_results = run_simulation_loop(
            config, agents, env, infrastructure, network, influence_system, progress_callback
        )
        
        # 9. Collect results
        results.time_series = loop_results['time_series']
        results.adoption_history = loop_results['adoption_history']
        results.cascade_events = loop_results['cascade_events']
        results.success = True
        
        logger.info(f"✅ Simulation complete: {len(results.cascade_events)} cascades detected")
        
    except Exception as e:
        logger.exception(f"Simulation failed: {e}")
        results.success = False
        results.error_message = str(e)
    
    return results
```

### Step 5: Update `__init__.py` Files (2 min)

#### `simulation/config/__init__.py`
```python
from simulation.config.simulation_config import SimulationConfig, SimulationResults

__all__ = ['SimulationConfig', 'SimulationResults']
```

#### `simulation/setup/__init__.py`
```python
from simulation.setup.environment_setup import setup_environment, setup_infrastructure
from simulation.setup.agent_creation import create_agents, create_planner
from simulation.setup.network_setup import setup_social_network

__all__ = [
    'setup_environment',
    'setup_infrastructure', 
    'create_agents',
    'create_planner',
    'setup_social_network'
]
```

#### `simulation/routing/__init__.py`
```python
from simulation.routing.route_diversity import apply_route_diversity

__all__ = ['apply_route_diversity']
```

### Step 6: Test Imports (2 min)

```bash
cd RTD_SIM/
python -c "from simulation.simulation_runner import SimulationConfig, run_simulation"
```

Should complete without errors.

### Step 7: Test Full Simulation (5 min)

```bash
python ui/streamlit_app.py
```

Run a small simulation (10 agents, 20 steps) to verify everything works.

---

## Verification Checklist

- [ ] Directories created with `__init__.py` files
- [ ] All 7 module files created
- [ ] Functions correctly extracted (no missing imports)
- [ ] New `simulation_runner.py` in place
- [ ] Import test passes
- [ ] Full simulation runs successfully
- [ ] All original functionality preserved

---

## Rollback Plan

If issues occur:

```bash
cd simulation/
rm -rf config/ setup/ routing/ execution/ analysis/
cp simulation_runner.py.backup simulation_runner.py
```

---

## Benefits After Refactoring

### Before
```
simulation_runner.py: 1194 lines
- All code in one file
- Hard to navigate
- Mixed responsibilities
- Difficult to test
```

### After
```
simulation_runner.py: 150 lines (orchestrator)
+ config/simulation_config.py: 100 lines
+ routing/route_diversity.py: 150 lines
+ setup/environment_setup.py: 200 lines
+ setup/agent_creation.py: 250 lines
+ setup/network_setup.py: 100 lines
+ execution/simulation_loop.py: 300 lines
+ analysis/scenario_comparison.py: 150 lines

Total: Same 1194 lines, but modular!
```

**Benefits:**
- ✅ Easy to find code (know which module)
- ✅ Can test modules independently
- ✅ Clear separation of concerns
- ✅ Easier to add new features
- ✅ Lower cognitive load per module

---

## Next: Phase 4.5C

After refactoring is complete, we'll add:
- Time-of-day electricity pricing
- Peak/off-peak grid capacity
- Smart charging optimization
- Dynamic pricing in BDI planner

Estimated time: 2-3 hours
