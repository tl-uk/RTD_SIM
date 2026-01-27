# Infrastructure Manager Hotfix
## Fixing AttributeError: 'historical_utilization'

**Date**: January 27, 2026  
**Issue**: Refactored InfrastructureManager missing historical tracking attributes  
**Status**: ✅ Fixed

---

## 🐛 The Problem

After refactoring `infrastructure_manager.py` into modular subsystems, the visualization code (`visualization.py`) encountered this error:

```
AttributeError: 'InfrastructureManager' object has no attribute 'historical_utilization'
```

**Root Cause**: The refactored code removed historical tracking attributes that the visualization layer depends on.

---

## ✅ The Fix

### 1. Added Historical Tracking Attributes

In `__init__()` method, added three tracking lists:

```python
# Historical tracking for visualization
self.historical_utilization = []
self.historical_load = []
self.historical_occupancy = []
```

### 2. Updated Grid Load Tracking

Modified `update_grid_load()` to populate historical data:

```python
def update_grid_load(self, step: int) -> None:
    """Update grid load from active charging sessions."""
    # ... existing load calculation ...
    
    # Track historical data for visualization
    utilization = self.grid.get_utilization()
    self.historical_utilization.append(utilization)
    self.historical_load.append(self.grid.get_load())
    
    # Calculate occupancy rate
    total_ports = sum(s.num_ports for s in self.stations.stations.values())
    occupied = sum(s.currently_occupied for s in self.stations.stations.values())
    occupancy = occupied / max(1, total_ports)
    self.historical_occupancy.append(occupancy)
```

---

## 📊 What Gets Tracked

### 1. `historical_utilization` (List[float])
- **Purpose**: Grid capacity utilization over time
- **Values**: 0.0 to 1.0 (0% to 100%)
- **Updated**: Every simulation step
- **Used by**: Infrastructure tab charts showing grid stress

### 2. `historical_load` (List[float])
- **Purpose**: Actual grid load in MW over time
- **Values**: 0.0 to grid_capacity_mw
- **Updated**: Every simulation step
- **Used by**: Load profile visualizations

### 3. `historical_occupancy` (List[float])
- **Purpose**: Charging port occupancy rate over time
- **Values**: 0.0 to 1.0 (0% to 100%)
- **Updated**: Every simulation step
- **Used by**: Charger utilization metrics

---

## 🔧 Implementation Steps

### Step 1: Apply the Fix

Replace your current `simulation/infrastructure/infrastructure_manager.py` with the fixed version:

```bash
# Backup current file
cp simulation/infrastructure/infrastructure_manager.py \
   simulation/infrastructure/infrastructure_manager_backup.py

# Copy fixed version
cp infrastructure_manager.py simulation/infrastructure/
```

### Step 2: Verify the Fix

Run a quick test:

```python
# Test script
from simulation.infrastructure import InfrastructureManager

infra = InfrastructureManager()

# Check attributes exist
assert hasattr(infra, 'historical_utilization')
assert hasattr(infra, 'historical_load')
assert hasattr(infra, 'historical_occupancy')

# Verify they're lists
assert isinstance(infra.historical_utilization, list)
assert isinstance(infra.historical_load, list)
assert isinstance(infra.historical_occupancy, list)

print("✅ All historical tracking attributes present!")
```

### Step 3: Run the Simulation

```bash
streamlit run ui/streamlit_app.py
```

Navigate to the Infrastructure tab and verify:
- Grid utilization chart displays correctly
- Load profile shows over time
- No AttributeError appears

---

## 🎯 Why This Matters

### Backward Compatibility
The refactoring maintained most backward compatibility, but missed these visualization-specific attributes. This fix ensures:
- Existing visualization code works unchanged
- Historical data is tracked for analysis
- Charts and metrics display correctly

### Design Pattern: Facade + History
The refactored architecture uses the **Facade Pattern** to delegate to subsystems, but the facade ALSO needs to:
1. **Aggregate data** from subsystems (e.g., `get_infrastructure_metrics()`)
2. **Track history** for time-series visualization
3. **Expose legacy attributes** for backward compatibility

---

## 📈 Example Usage in Visualization

The visualization code uses these attributes like this:

```python
def render_infrastructure_metrics(infrastructure_manager):
    """Render infrastructure metrics in Streamlit UI."""
    
    # Check if historical data exists
    if infrastructure_manager.historical_utilization:
        # Plot grid utilization over time
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            y=infrastructure_manager.historical_utilization,
            mode='lines',
            name='Grid Utilization'
        ))
        st.plotly_chart(fig)
    
    # Plot load profile
    if infrastructure_manager.historical_load:
        st.line_chart(infrastructure_manager.historical_load)
    
    # Show occupancy rate
    if infrastructure_manager.historical_occupancy:
        current_occupancy = infrastructure_manager.historical_occupancy[-1]
        st.metric("Charger Occupancy", f"{current_occupancy:.1%}")
```

---

## 🧪 Testing Checklist

After applying the fix, verify:

- [ ] Simulation runs without AttributeError
- [ ] Infrastructure tab displays correctly
- [ ] Grid utilization chart shows data
- [ ] Load profile chart shows data
- [ ] Charger occupancy metrics display
- [ ] Historical data accumulates over simulation
- [ ] No performance degradation

---

## 🔍 Alternative Solutions Considered

### Option 1: Fix Visualization to Use Subsystem APIs ❌
**Why not**: Would require rewriting visualization layer; breaks existing code

### Option 2: Add Historical Tracking to GridCapacityManager ❌
**Why not**: Mixing concerns; grid manager shouldn't track occupancy

### Option 3: Add History Tracking to Facade ✅ **CHOSEN**
**Why yes**: 
- Minimal code changes
- Maintains clean subsystem separation
- Provides single source of truth for UI
- Backward compatible

---

## 📝 Lessons Learned

### 1. Backward Compatibility Is Critical
When refactoring, must inventory ALL attributes/methods used by dependent code, not just public API methods.

### 2. Visualization Has Special Needs
UI layers often need:
- Historical time-series data
- Aggregated metrics across subsystems
- Real-time updates

### 3. Facade Pattern Extensions
A proper facade for a complex system needs to:
```python
class Facade:
    # 1. Delegate operations to subsystems
    def operation(self): return subsystem.operation()
    
    # 2. Aggregate data from subsystems
    def get_metrics(self): return {**sub1.metrics(), **sub2.metrics()}
    
    # 3. Track historical data for visualization
    def update(self): 
        subsystem.update()
        self.history.append(subsystem.state())
    
    # 4. Expose legacy attributes for compatibility
    self.legacy_attr = subsystem.new_attr
```

---

## 🚀 Future Enhancements

### 1. Configurable History Buffer Size
Currently unlimited; could grow large in long simulations:

```python
self.historical_utilization = collections.deque(maxlen=1000)
```

### 2. History Sampling
Don't need every step; sample every N steps:

```python
if step % 5 == 0:  # Every 5 steps
    self.historical_utilization.append(utilization)
```

### 3. History Export
Save historical data for post-simulation analysis:

```python
def export_history(self, filepath: str):
    """Export historical data to CSV."""
    pd.DataFrame({
        'utilization': self.historical_utilization,
        'load_mw': self.historical_load,
        'occupancy': self.historical_occupancy,
    }).to_csv(filepath)
```

### 4. Metrics Subsystem
Extract history tracking to dedicated `MetricsTracker`:

```python
class MetricsTracker:
    """Tracks time-series metrics for visualization."""
    
    def __init__(self):
        self.metrics = defaultdict(list)
    
    def record(self, metric_name: str, value: float):
        self.metrics[metric_name].append(value)
    
    def get_history(self, metric_name: str) -> List[float]:
        return self.metrics[metric_name]
```

---

## ✅ Resolution Status

**Status**: ✅ **RESOLVED**

The fixed `infrastructure_manager.py` now includes:
- ✅ Historical utilization tracking
- ✅ Historical load tracking
- ✅ Historical occupancy tracking
- ✅ Updated on every `update_grid_load()` call
- ✅ Backward compatible with visualization code

**Next Steps**:
1. Apply the fixed file to your RTD_SIM installation
2. Run tests to verify
3. Continue with Phase 5.2 weather integration

---

## 📞 Support

If you encounter issues after applying this fix:

1. **Check Python version**: Requires Python 3.7+
2. **Verify imports**: Ensure all subsystem modules are present
3. **Check file paths**: Ensure file is in correct location
4. **Review logs**: Look for import errors or missing modules

**Common Issues**:

```python
# Issue: Empty historical lists
# Solution: Ensure update_grid_load() is called in simulation loop

# Issue: AttributeError still occurs
# Solution: Restart Streamlit to reload modules
```

---

**Hotfix Version**: 1.0  
**Compatible With**: RTD_SIM Phase 5.2  
**Tested On**: Python 3.13, Streamlit 1.40+

**End of Hotfix Documentation**
