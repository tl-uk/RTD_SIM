# Quick Freight Mode Additions (Option A)

## Files to Update (3 files, ~10 minutes)

### 1. `agent/bdi_planner.py`

**Line 46** - Add freight modes to default_modes:

```python
def __init__(
    self,
    infrastructure_manager: Optional[Any] = None
) -> None:
    """Initialize planner."""
    # OLD: self.default_modes = ['walk', 'bike', 'bus', 'car', 'ev']
    
    # NEW: Add freight modes
    self.default_modes = [
        'walk', 'bike', 'bus', 
        'car', 'ev',
        'van_electric', 'van_diesel',  # NEW: Freight modes
    ]
    
    self.infrastructure = infrastructure_manager
    # ... rest unchanged
```

**Line 155** - Update EV range constraints:

```python
# In _is_mode_feasible() method, around line 155
def _is_mode_feasible(...):
    if not self.has_infrastructure or mode not in ['ev', 'van_electric']:  # NEW: Add van_electric
        return True
    
    # Calculate trip distance
    from simulation.spatial.coordinate_utils import haversine_km
    trip_distance = haversine_km(origin, dest)
    
    # Get vehicle type
    vehicle_type = context.get('vehicle_type', 'personal')
    
    # NEW: Determine EV type with freight support
    if mode == 'van_electric' or vehicle_type == 'commercial':
        ev_type = 'ev_delivery'
    else:
        ev_type = 'ev'
    
    max_range = self.EV_RANGE_KM.get(ev_type, 350.0)
    # ... rest unchanged
```

**Line 195** - Update EV params for freight:

```python
# In _get_ev_params() method, update the mode check:
def _get_ev_params(...):
    # OLD: if mode != 'ev':
    
    # NEW: Support both EV types
    if mode not in ['ev', 'van_electric']:
        return {}
    
    # ... rest unchanged
```

**Line 230** - Update infrastructure penalty:

```python
# In cost() method, around line 230
def cost(...):
    # ... existing code ...
    
    infrastructure_penalty = 0.0
    
    # NEW: Apply to both EV types
    if mode in ['ev', 'van_electric'] and self.has_infrastructure:
        # ... existing infrastructure logic unchanged ...
```

---

### 2. `simulation/spatial/metrics_calculator.py`

**Line 22** - Add freight speeds:

```python
def __init__(self):
    """Initialize with default mode speeds and parameters."""
    # Speed in km per minute
    self.speeds_km_min = {
        'walk': 0.083,
        'bike': 0.25,
        'bus': 0.33,
        'car': 0.5,
        'ev': 0.5,
        'van_electric': 0.45,   # NEW: Slightly slower due to weight
        'van_diesel': 0.45,     # NEW: Same speed as EV van
    }
```

**Line 34** - Add freight emissions:

```python
# Base emissions in grams CO2 per km
self.emissions_grams_per_km = {
    'walk': 0.0,
    'bike': 0.0,
    'bus': 80.0,
    'car': 180.0,
    'ev': 60.0,
    'van_electric': 90.0,    # NEW: Heavier than car EV
    'van_diesel': 250.0,     # NEW: Worse than car diesel
}
```

**Line 43** - Add freight costs:

```python
# Monetary cost (base fare + per km)
self.cost_params = {
    'walk': {'base': 0.0, 'per_km': 0.0},
    'bike': {'base': 0.0, 'per_km': 0.0},
    'bus': {'base': 1.5, 'per_km': 0.0},
    'car': {'base': 0.0, 'per_km': 0.5},
    'ev': {'base': 0.0, 'per_km': 0.3},
    'van_electric': {'base': 0.0, 'per_km': 0.4},   # NEW: Cheaper than diesel
    'van_diesel': {'base': 0.0, 'per_km': 0.6},     # NEW: Expensive fuel
}
```

**Line 54** - Add freight comfort:

```python
# Comfort scores (0-1, higher = more comfortable)
self.comfort_scores = {
    'walk': 0.5,
    'bike': 0.6,
    'bus': 0.7,
    'car': 0.8,
    'ev': 0.85,
    'van_electric': 0.7,  # NEW: Commercial vehicle
    'van_diesel': 0.7,    # NEW: Same comfort
}
```

**Line 64** - Add freight risk:

```python
# Risk scores (0-1, higher = more risky)
self.risk_scores = {
    'walk': 0.2,
    'bike': 0.3,
    'bus': 0.15,
    'car': 0.25,
    'ev': 0.20,
    'van_electric': 0.25,  # NEW: Larger vehicle
    'van_diesel': 0.25,    # NEW: Same risk
}
```

---

### 3. `simulation/spatial/router.py`

**Line 29** - Add freight routing:

```python
# Mode to network type mapping
self.mode_network_types = {
    'walk': 'walk',
    'bike': 'bike',
    'bus': 'drive',
    'car': 'drive',
    'ev': 'drive',
    'van_electric': 'drive',  # NEW: Use drive network
    'van_diesel': 'drive',    # NEW: Use drive network
}
```

**Line 39** - Add freight speeds:

```python
# Speed in km per minute for time-based routing
self.speeds_km_min = {
    'walk': 0.083,
    'bike': 0.25,
    'bus': 0.33,
    'car': 0.5,
    'ev': 0.5,
    'van_electric': 0.45,  # NEW
    'van_diesel': 0.45,    # NEW
}
```

---

### 4. `simulation/simulation_runner.py`

**Line 482** - Track freight modes:

```python
# In run_simulation(), around line 482
mode_counts = Counter(a.state.mode for a in agents)

# NEW: Track all modes including freight
for mode in ['walk', 'bike', 'bus', 'car', 'ev', 'van_electric', 'van_diesel']:
    adoption_history[mode].append(mode_counts.get(mode, 0) / len(agents))
```

---

### 5. `visualiser/visualization.py`

**Line 12** - Add freight colors:

```python
MODE_COLORS_RGB = {
    'walk': [34, 197, 94],
    'bike': [59, 130, 246],
    'bus': [245, 158, 11],
    'car': [239, 68, 68],
    'ev': [168, 85, 245],
    'van_electric': [16, 185, 129],   # NEW: Green for electric van
    'van_diesel': [107, 114, 128],    # NEW: Gray for diesel van
}

MODE_COLORS_HEX = {
    'walk': '#22c55e',
    'bike': '#3b82f6',
    'bus': '#f59e0b',
    'car': '#ef4444',
    'ev': '#a855f7',
    'van_electric': '#10b981',  # NEW
    'van_diesel': '#6b7280',    # NEW
}
```

**Line 140** - Track freight in charts:

```python
# In render_mode_adoption_chart(), update mode list:
for mode in ['walk', 'bike', 'bus', 'car', 'ev', 'van_electric', 'van_diesel']:  # NEW
    if mode in adoption_history and adoption_history[mode]:
        # ... existing code ...
```

---

## 🧪 Testing the Freight Modes

After making these changes, run with:

1. **Region:** Central Scotland (Edinburgh-Glasgow)
2. **Agents:** 50
3. **Infrastructure:** Enabled
4. **Grid Capacity:** 500 MW (to see stress)

**Expected results:**
- `van_electric` adoption for long trips (>20km)
- `van_diesel` initially dominant (lower capital cost)
- EVs chosen by high-eco agents
- Grid load increases as EV vans charge

---

## 📊 Next: Real Charging Station Data

Once freight modes are working, add real data loader:

```python
# simulation/infrastructure_loader.py

import requests
import logging

logger = logging.getLogger(__name__)

def load_opencharge_map_stations(
    bbox: Tuple[float, float, float, float],
    infrastructure_manager: InfrastructureManager
) -> int:
    """
    Load real charging stations from OpenChargeMap API.
    
    Args:
        bbox: (west, south, east, north)
        infrastructure_manager: InfrastructureManager to populate
    
    Returns:
        Number of stations loaded
    """
    west, south, east, north = bbox
    
    # OpenChargeMap API
    url = "https://api.openchargemap.io/v3/poi/"
    params = {
        'output': 'json',
        'boundingbox': f"({south},{west}),({north},{east})",
        'maxresults': 500,
        'compact': True,
        'verbose': False,
    }
    
    try:
        logger.info(f"Fetching real charging stations from OpenChargeMap...")
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        stations = response.json()
        count = 0
        
        for station in stations:
            # Extract location
            lat = station['AddressInfo']['Latitude']
            lon = station['AddressInfo']['Longitude']
            
            # Extract charger info
            connections = station.get('Connections', [])
            if not connections:
                continue
            
            # Get fastest charger type
            max_power = max([c.get('PowerKW', 7) for c in connections if c.get('PowerKW')])
            
            if max_power >= 50:
                charger_type = 'dcfast'
            else:
                charger_type = 'level2'
            
            num_ports = len(connections)
            
            # Add to infrastructure
            infrastructure_manager.add_charging_station(
                station_id=f"real_{station['ID']}",
                location=(lon, lat),
                charger_type=charger_type,
                num_ports=num_ports,
                power_kw=max_power,
                cost_per_kwh=0.15 if charger_type == 'level2' else 0.25,
                owner_type='real'  # Mark as real
            )
            
            count += 1
        
        logger.info(f"✅ Loaded {count} real charging stations")
        return count
        
    except Exception as e:
        logger.warning(f"Failed to load real stations: {e}")
        return 0

# Usage in setup_infrastructure():
def setup_infrastructure(config, progress_callback=None):
    # ... existing code ...
    
    infrastructure = InfrastructureManager(...)
    
    # Load real stations first
    if config.use_real_chargers and config.extended_bbox:
        real_count = load_opencharge_map_stations(
            config.extended_bbox,
            infrastructure
        )
        
        # Add synthetic stations to fill gaps
        synthetic_needed = max(0, config.num_chargers - real_count)
        if synthetic_needed > 0:
            logger.info(f"Adding {synthetic_needed} synthetic stations")
            # ... add synthetic stations ...
    else:
        # All synthetic
        infrastructure.populate_edinburgh_chargers(...)
    
    return infrastructure
```

Then in streamlit, add checkbox:
```python
use_real_chargers = st.checkbox(
    "Use Real Charging Stations (OpenChargeMap)",
    value=False,
    help="Load actual charging station locations"
)
```

---

## 🎯 Summary

**Do NOW (Option A):**
1. ✅ Add 7 freight mode entries (10 min)
2. ✅ Test Glasgow-Edinburgh freight
3. ✅ See EV van adoption for long trips

**Do NEXT (Real Data):**
4. Add OpenChargeMap loader (30 min)
5. Color-code real vs synthetic on map
6. Identify infrastructure gaps

**Do LATER (Phase 4.5F - Optimization):**
7. Hotspot detection → suggest locations
8. Flow analysis → optimal placement
9. Coverage optimization algorithms

Ready to add the freight modes? Just copy the code snippets into the 5 files!
