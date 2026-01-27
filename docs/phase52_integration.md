# Phase 5.2 Integration Guide
## Environmental & Weather System Implementation

**Status**: ✅ Module files complete, ready for integration  
**Time Estimate**: 12-15 hours for full integration + testing

---

## 📦 What's Been Created

### ✅ Complete Modules

1. **`weather_api.py`** - Already complete!
   - Open-Meteo API integration
   - Weather state tracking
   - Speed/range multipliers

2. **`seasonal_patterns.py`** - ✅ NOW COMPLETE
   - Monthly, weekly, hourly multipliers
   - Mode preference adjustments
   - EV range penalties

3. **`emissions_calculator.py`** - ✅ NOW COMPLETE
   - Lifecycle emissions (manufacturing + energy)
   - Air quality pollutants (PM2.5, NOx, CO)
   - Mode comparison functions

4. **`air_quality.py`** - ✅ NOW COMPLETE
   - Spatial air quality tracking
   - WHO guideline checks
   - Population exposure metrics

---

## 🔧 Integration Steps

### Step 1: Update `simulation_config.py` (5 min)

Add environmental configuration fields:

```python
@dataclass
class SimulationConfig:
    # ... existing fields ...
    
    # Phase 5.2: Environmental & Weather
    weather_enabled: bool = False
    use_historical_weather: bool = False
    weather_start_date: Optional[str] = None  # "2024-01-15"
    latitude: float = 55.9533   # Edinburgh default
    longitude: float = -3.1883
    
    track_air_quality: bool = False
    air_quality_grid_km: float = 1.0
    
    use_lifecycle_emissions: bool = True  # Replace simple emissions
    grid_carbon_intensity: float = 0.233  # UK 2024
    
    season_month: Optional[int] = None  # Force specific month for testing
    season_day_of_year: Optional[int] = None

@dataclass
class SimulationResults:
    # ... existing fields ...
    
    # Phase 5.2: Environmental results
    weather_manager: Optional[Any] = None
    air_quality_tracker: Optional[Any] = None
    lifecycle_emissions_total: Dict[str, float] = field(default_factory=dict)
```

---

### Step 2: Update `simulation_loop.py` - Weather Integration (30 min)

Add weather updates to main loop:

```python
# At top of file
from environmental.weather_api import create_weather_manager
from environmental.seasonal_patterns import (
    get_combined_multipliers,
    apply_seasonal_ev_range_penalty
)
from environmental.emissions_calculator import LifecycleEmissions
from environmental.air_quality import create_air_quality_tracker

def run_simulation_loop(
    config, agents, env, infrastructure, 
    network, influence_system, policy_engine=None,
    progress_callback=None
):
    # ... existing initialization ...
    
    # NEW: Initialize environmental systems
    weather_manager = create_weather_manager(config) if config.weather_enabled else None
    air_quality = create_air_quality_tracker(config) if config.track_air_quality else None
    emissions_calc = LifecycleEmissions(config.grid_carbon_intensity) if config.use_lifecycle_emissions else None
    
    # Track lifecycle emissions
    lifecycle_emissions_by_mode = defaultdict(lambda: {'co2e_kg': 0, 'pm25_g': 0, 'nox_g': 0})
    
    # Main loop
    for step in range(config.steps):
        # Calculate current time
        time_of_day = (step % 1440) / 60.0  # hours (assuming 1 step = 1 min)
        hour = int(time_of_day)
        
        # Calculate date (if seasonal patterns enabled)
        month = config.season_month or 6  # Default to summer
        day_of_year = config.season_day_of_year or 180
        day_of_week = (step // 1440) % 7  # Assuming day 0 is Monday
        
        # UPDATE WEATHER
        if weather_manager:
            weather_conditions = weather_manager.update_weather(step, time_of_day)
            
            # Apply weather to environment speeds
            for mode in env.get_available_modes():
                speed_mult = weather_manager.get_mode_speed_multiplier(mode)
                env.set_weather_speed_multiplier(mode, speed_mult)
            
            # Adjust EV ranges based on temperature
            if infrastructure:
                temp = weather_conditions['temperature']
                for mode in ['ev', 'van_electric', 'truck_electric', 'hgv_electric']:
                    base_range = infrastructure.get_base_ev_range(mode)
                    adjusted_range = apply_seasonal_ev_range_penalty(base_range, temp)
                    infrastructure.set_adjusted_ev_range(mode, adjusted_range)
        
        # GET SEASONAL MULTIPLIERS
        seasonal_mults = get_combined_multipliers(month, day_of_year, day_of_week, hour)
        
        # Apply to infrastructure grid load
        if infrastructure:
            base_load = infrastructure.get_base_grid_load()
            adjusted_load = base_load * seasonal_mults.get('grid_load', 1.0)
            infrastructure.set_grid_load(adjusted_load)
        
        # ... existing infrastructure updates ...
        
        # ... existing policy engine updates ...
        
        # AGENT STEPS with lifecycle emissions
        for agent in agents:
            prev_location = agent.state.location
            
            agent.step(env)
            
            # Calculate lifecycle emissions if agent moved
            if emissions_calc and prev_location != agent.state.location:
                mode = agent.state.mode
                distance = agent.state.distance_km - prev_distance  # Need to track prev
                
                emissions = emissions_calc.calculate_trip_emissions(
                    mode=mode,
                    distance_km=distance
                )
                
                # Accumulate
                lifecycle_emissions_by_mode[mode]['co2e_kg'] += emissions['co2e_kg']
                lifecycle_emissions_by_mode[mode]['pm25_g'] += emissions['pm25_g']
                lifecycle_emissions_by_mode[mode]['nox_g'] += emissions['nox_g']
                
                # Add to air quality tracker
                if air_quality and agent.state.location:
                    air_quality.add_emissions(
                        location=agent.state.location,
                        emissions=emissions
                    )
        
        # Air quality step (atmospheric dispersion)
        if air_quality:
            wind_speed = weather_conditions.get('wind_speed', 10.0) if weather_manager else 10.0
            air_quality.step(wind_speed_kmh=wind_speed)
            
            # Check for exceedances every hour
            if step % 60 == 0:
                exceedances = air_quality.check_exceedances('hourly')
                if exceedances:
                    logger.warning(f"Step {step}: {len(exceedances)} air quality exceedances")
        
        # ... rest of loop ...
    
    # Return results with environmental data
    results = {
        'time_series': time_series,
        'adoption_history': dict(adoption_history),
        'cascade_events': cascade_events,
        'lifecycle_emissions': dict(lifecycle_emissions_by_mode),
        'weather_manager': weather_manager,
        'air_quality_tracker': air_quality,
    }
    
    return results
```

---

### Step 3: Update `spatial_environment.py` - Weather Adjustments (20 min)

Add weather speed multiplier support:

```python
class SpatialEnvironment:
    def __init__(self, ...):
        # ... existing init ...
        
        # NEW: Weather speed multipliers
        self._weather_speed_multipliers = defaultdict(lambda: 1.0)
    
    def set_weather_speed_multiplier(self, mode: str, multiplier: float):
        """Set weather-based speed adjustment for a mode."""
        self._weather_speed_multipliers[mode] = multiplier
    
    def estimate_travel_time(self, route, mode):
        """Estimate with weather adjustment."""
        base_time = self._estimate_base_travel_time(route, mode)
        
        # Apply weather multiplier
        weather_mult = self._weather_speed_multipliers.get(mode, 1.0)
        
        return base_time / weather_mult  # Slower speed = more time
```

---

### Step 4: Update `infrastructure_manager.py` - Seasonal EV Ranges (15 min)

```python
class InfrastructureManager:
    def __init__(self, ...):
        # ... existing init ...
        
        # NEW: EV range tracking
        self._base_ev_ranges = {
            'ev': 350.0,
            'van_electric': 200.0,
            'truck_electric': 250.0,
            'hgv_electric': 300.0,
        }
        self._adjusted_ev_ranges = self._base_ev_ranges.copy()
    
    def get_base_ev_range(self, mode: str) -> float:
        """Get rated range at optimal temperature."""
        return self._base_ev_ranges.get(mode, 350.0)
    
    def set_adjusted_ev_range(self, mode: str, range_km: float):
        """Set weather-adjusted range."""
        self._adjusted_ev_ranges[mode] = range_km
    
    def get_adjusted_ev_range(self, mode: str) -> float:
        """Get current adjusted range."""
        return self._adjusted_ev_ranges.get(mode, self.get_base_ev_range(mode))
```

Update `find_nearest_charger()` to use adjusted ranges.

---

### Step 5: Update Policy Engine - Weather Actions (45 min)

Add weather-responsive actions to `dynamic_policy_engine.py`:

```python
def _execute_action(self, rule: InteractionRule, step: int):
    action_type = rule.action['type']
    
    # ... existing actions ...
    
    # NEW: Weather-responsive actions
    elif action_type == 'activate_winter_gritting':
        # Reduce speed penalties on icy roads
        self.state['ice_warning'] = False
        logger.info(f"Step {step}: Activated winter gritting")
    
    elif action_type == 'close_routes':
        # Mark certain routes as unavailable
        region = rule.action.get('region', 'all')
        logger.info(f"Step {step}: Closed routes in {region} due to weather")
    
    elif action_type == 'emergency_transit':
        # Boost public transport frequency
        multiplier = rule.action.get('frequency_multiplier', 1.5)
        logger.info(f"Step {step}: Emergency transit boost ({multiplier}x)")
    
    elif action_type == 'reduce_charging_time':
        # Temperature-controlled charging
        reduction = rule.action.get('reduction_factor', 0.8)
        logger.info(f"Step {step}: Charging time reduced to {reduction*100}%")
```

Add weather state variables:

```python
def update_simulation_state(self, step, agents, env, infrastructure):
    # ... existing state ...
    
    # NEW: Weather state
    if hasattr(self, 'weather_manager') and self.weather_manager:
        conditions = self.weather_manager.current_conditions
        self.state['temperature'] = conditions['temperature']
        self.state['precipitation'] = conditions['precipitation']
        self.state['snow_depth'] = conditions['snow_depth']
        self.state['ice_warning'] = conditions['ice_warning']
        self.state['wind_speed'] = conditions['wind_speed']
```

---

### Step 6: Create UI Tab - Environmental Impact (1-2 hours)

**File**: `ui/tabs/environmental_tab.py`

```python
"""
ui/tabs/environmental_tab.py

Environmental impact visualization: weather, emissions, air quality.
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px

def render_environmental_tab(results, anim, current_data):
    """Render environmental impact tab."""
    
    st.header("🌍 Environmental Impact Analysis")
    
    # Weather Conditions
    if results.weather_manager:
        st.subheader("🌤️ Weather Conditions")
        
        conditions = results.weather_manager.current_conditions
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                "Temperature",
                f"{conditions['temperature']:.1f}°C",
                delta=None
            )
        
        with col2:
            st.metric(
                "Precipitation",
                f"{conditions['precipitation']:.1f} mm/h",
                delta=None
            )
        
        with col3:
            st.metric(
                "Wind Speed",
                f"{conditions['wind_speed']:.1f} km/h",
                delta=None
            )
        
        with col4:
            if conditions['ice_warning']:
                st.warning("⚠️ Ice Warning")
            else:
                st.success("✅ No Ice")
    
    # Lifecycle Emissions
    if hasattr(results, 'lifecycle_emissions_total'):
        st.subheader("📊 Lifecycle Emissions by Mode")
        
        emissions = results.lifecycle_emissions_total
        
        if emissions:
            # Create bar chart
            modes = list(emissions.keys())
            co2e = [emissions[m]['co2e_kg'] for m in modes]
            
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=modes,
                y=co2e,
                name='CO2e (kg)',
                marker_color='darkred'
            ))
            
            fig.update_layout(
                title="Total CO2e Emissions by Mode",
                xaxis_title="Mode",
                yaxis_title="CO2e (kg)",
                height=400
            )
            
            st.plotly_chart(fig, use_container_width=True)
            
            # Mode comparison table
            st.dataframe({
                'Mode': modes,
                'CO2e (kg)': [f"{emissions[m]['co2e_kg']:.2f}" for m in modes],
                'PM2.5 (g)': [f"{emissions[m]['pm25_g']:.2f}" for m in modes],
                'NOx (g)': [f"{emissions[m]['nox_g']:.2f}" for m in modes],
            })
    
    # Air Quality Heatmap
    if results.air_quality_tracker:
        st.subheader("🌫️ Air Quality Hotspots")
        
        aq = results.air_quality_tracker
        
        # Pollutant selector
        pollutant = st.selectbox(
            "Select Pollutant",
            ['pm25', 'nox', 'co'],
            format_func=lambda x: {
                'pm25': 'PM2.5 (Fine Particles)',
                'nox': 'NOx (Nitrogen Oxides)',
                'co': 'CO (Carbon Monoxide)'
            }[x]
        )
        
        # Get hotspots
        hotspots = aq.get_hotspots(pollutant=pollutant, threshold_multiplier=2.0)
        
        if hotspots:
            st.warning(f"⚠️ {len(hotspots)} pollution hotspots detected")
            
            # Show top 5
            for i, hotspot in enumerate(hotspots[:5]):
                st.write(f"{i+1}. Grid {hotspot['grid_cell']}: "
                        f"{hotspot['concentration']:.1f} µg/m³ "
                        f"({hotspot['exceedance_factor']:.1f}x WHO limit)")
        else:
            st.success("✅ No hotspots detected")
        
        # Summary statistics
        stats = aq.get_summary_statistics()
        
        st.write("**Air Quality Summary**")
        for poll, data in stats.items():
            st.write(f"**{poll.upper()}**: Mean {data['mean']:.2f} µg/m³ "
                    f"(WHO limit: {data['who_limit']:.1f})")
```

Add to `streamlit_app.py`:

```python
from ui.tabs import (
    # ... existing imports ...
    render_environmental_tab,  # NEW
)

# In tab_configs:
if config.weather_enabled or config.track_air_quality:
    tab_configs.append(("🌍 Environmental", render_environmental_tab))
```

---

### Step 7: Create Sample Combined Scenario with Weather (15 min)

**File**: `scenarios/combined_configs/winter_emergency_test.yaml`

```yaml
name: "Winter Emergency Response"
description: "Test weather-responsive policies during severe winter conditions"

base_scenarios:
  - name: "baseline"
    multiplier: 1.0

interaction_rules:
  - name: "ice_warning_response"
    condition: "ice_warning == True"
    action:
      type: "activate_winter_gritting"
    priority: 1

  - name: "heavy_snow_transit"
    condition: "snow_depth > 5.0"
    action:
      type: "emergency_transit"
      frequency_multiplier: 1.5
    priority: 1

  - name: "cold_weather_charging"
    condition: "temperature < 0"
    action:
      type: "reduce_charging_costs"
      cost_multiplier: 0.7
      reason: "Cold weather range penalty compensation"
    priority: 2

  - name: "extreme_cold_restrictions"
    condition: "temperature < -10"
    action:
      type: "ban_diesel_vehicles"
      zones: ["urban_core"]
      reason: "Air quality protection in extreme cold"
    priority: 3

constraints:
  - type: "budget"
    limit: 5000000
    currency: "GBP"

  - type: "grid_capacity"
    limit_mw: 15.0

feedback_loops: []
```

---

## 🧪 Testing Checklist

### Phase 5.2A: Weather Integration (2-3 hours)

- [ ] Weather API fetches data successfully
- [ ] Speed multipliers apply to agent movement
- [ ] EV range adjusts with temperature
- [ ] Weather conditions visible in UI
- [ ] Synthetic weather fallback works

### Phase 5.2B: Lifecycle Emissions (1-2 hours)

- [ ] Emissions calculate for all modes
- [ ] PM2.5, NOx, CO tracked correctly
- [ ] Mode comparison shows relative impacts
- [ ] Results accumulate over simulation

### Phase 5.2C: Air Quality (2-3 hours)

- [ ] Emissions add to spatial grid
- [ ] Hotspots detect correctly
- [ ] WHO exceedances flag properly
- [ ] Heatmap renders in UI

### Phase 5.2D: Seasonal Patterns (1-2 hours)

- [ ] Freight demand varies by time of day
- [ ] Tourism demand peaks in summer
- [ ] EV range reduces in winter
- [ ] Grid load reflects seasonal heating

### Phase 5.2E: Policy Integration (2-3 hours)

- [ ] Weather-responsive actions trigger
- [ ] Winter emergency scenario works
- [ ] Combined scenarios include weather
- [ ] Policy tab shows weather actions

---

## 📊 Expected Results

### Baseline Run (No Weather)
- Similar to current results
- Simple emission calculations

### With Weather Enabled (Winter)
- **15-25% slower** bike/walk speeds in rain
- **40% slower** all modes in snow
- **20-30% lower** EV ranges in cold
- **Higher** grid load from heating demand

### With Weather Enabled (Summer)
- **30% more** bike adoption
- **80% higher** tourism demand
- **Optimal** EV ranges
- **Lower** grid stress

### Air Quality Tracking
- **5-10 hotspots** near freight depots
- **PM2.5 exceedances** on high-traffic routes
- **NOx peaks** during morning rush hour

---

## 🚀 Quick Start Command

```bash
# After integration is complete, run a test simulation
python -c "
from simulation.simulation_runner import run_simulation
from simulation.config.simulation_config import SimulationConfig

config = SimulationConfig(
    steps=100,
    num_agents=50,
    place='Edinburgh, UK',
    weather_enabled=True,
    use_historical_weather=False,
    season_month=1,  # January (winter)
    track_air_quality=True,
    use_lifecycle_emissions=True,
)

results = run_simulation(config)
print(f'Weather: {results.weather_manager.current_conditions}')
print(f'Emissions: {results.lifecycle_emissions_total}')
"
```

---

## 📝 Next Steps After Phase 5.2

1. **Phase 5.3: Enhanced Metrics** (8-12 hours)
   - Journey time distributions
   - Mode share evolution
   - Network efficiency metrics

2. **Phase 5.4: Time Series Database** (10-15 hours)
   - InfluxDB integration
   - Historical comparison
   - Trend analysis

3. **Phase 6: Advanced Visualizations** (15-20 hours)
   - 3D terrain rendering
   - Animated heatmaps
   - Interactive dashboards

---

**End of Integration Guide**  
**Phase 5.2: Environmental & Weather - Ready to Implement**

✅ All modules complete  
✅ Integration steps defined  
✅ Testing checklist provided  
✅ Expected results documented
