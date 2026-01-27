# Weather Perturbation Feature Design
## Making RTD_SIM a True Scenario Testing Platform

---

## 🎯 Why Weather Perturbation is Powerful

### Current State: Realistic but Static
- Weather API fetches real/historical data
- Users can't test "what if" scenarios
- Limited to actual weather patterns

### With Perturbation: Scenario Testing Platform
- **Test extreme events**: "What if we had a 2-week snowstorm?"
- **Stress test policies**: "Can our grid handle a heatwave?"
- **Plan for climate change**: "What if winters get 2°C warmer?"
- **Emergency preparedness**: "What if ice warning lasts 3 days?"

---

## 🔧 Proposed Implementation

### Option 1: Simple Multipliers (Easiest - 1 hour)

Add to sidebar:

```python
# In sidebar_config.py
if config.weather_enabled:
    st.subheader("🌡️ Weather Perturbations")
    
    temp_adjust = st.slider(
        "Temperature Adjustment (°C)",
        min_value=-10.0,
        max_value=+10.0,
        value=0.0,
        step=0.5,
        help="Add/subtract from actual temperature"
    )
    
    precip_mult = st.slider(
        "Precipitation Multiplier",
        min_value=0.0,
        max_value=3.0,
        value=1.0,
        step=0.1,
        help="1.0 = normal, 2.0 = double rainfall"
    )
    
    wind_mult = st.slider(
        "Wind Speed Multiplier",
        min_value=0.5,
        max_value=2.0,
        value=1.0,
        step=0.1,
        help="1.5 = 50% stronger winds"
    )
    
    # Apply to config
    config.weather_temp_adjustment = temp_adjust
    config.weather_precip_multiplier = precip_mult
    config.weather_wind_multiplier = wind_mult
```

Then in `weather_api.py`:

```python
def update_weather(self, step: int, time_of_day: float) -> Dict:
    """Update weather with optional perturbations."""
    # Get base weather
    self._update_conditions_from_data(hourly_data)
    
    # Apply perturbations
    if hasattr(self, 'temp_adjustment'):
        self.current_conditions['temperature'] += self.temp_adjustment
    
    if hasattr(self, 'precip_multiplier'):
        self.current_conditions['precipitation'] *= self.precip_multiplier
    
    if hasattr(self, 'wind_multiplier'):
        self.current_conditions['wind_speed'] *= self.wind_multiplier
    
    # Recalculate ice warning with adjusted temp
    self.current_conditions['ice_warning'] = self._check_ice_conditions(
        self.current_conditions
    )
    
    return self.current_conditions
```

**Time to implement**: 1 hour  
**Value**: HIGH - Immediate scenario testing capability

---

### Option 2: Extreme Event Presets (Better - 2 hours)

Add preset extreme events:

```python
# In sidebar_config.py
if config.weather_enabled:
    st.subheader("🌩️ Extreme Weather Events")
    
    event = st.selectbox(
        "Simulate Extreme Event",
        [
            "None (Actual Weather)",
            "❄️ Severe Winter Storm",
            "🌊 Heavy Flooding",
            "🌡️ Heatwave",
            "💨 High Winds",
            "🧊 Prolonged Ice",
            "🌧️ Week-Long Rain",
        ]
    )
    
    if event != "None (Actual Weather)":
        duration = st.slider(
            "Event Duration (hours)",
            min_value=6,
            max_value=168,  # 1 week
            value=24,
            step=6
        )
    
    # Store in config
    config.weather_extreme_event = event
    config.weather_event_duration = duration if event != "None" else 0
```

Preset conditions:

```python
EXTREME_EVENTS = {
    "❄️ Severe Winter Storm": {
        'temperature': -8.0,
        'precipitation': 5.0,  # mm/h
        'snow_depth': 15.0,   # cm
        'wind_speed': 50.0,   # km/h
        'ice_warning': True,
    },
    "🌊 Heavy Flooding": {
        'temperature': 10.0,
        'precipitation': 20.0,  # Extreme rain
        'wind_speed': 40.0,
    },
    "🌡️ Heatwave": {
        'temperature': 35.0,
        'precipitation': 0.0,
        'wind_speed': 5.0,
    },
    # ... etc
}
```

**Time to implement**: 2 hours  
**Value**: VERY HIGH - Realistic emergency scenarios

---

### Option 3: Interactive Weather Timeline (Best - 4 hours)

Allow users to **script weather changes** over simulation:

```python
# In sidebar_config.py
if config.weather_enabled:
    st.subheader("📅 Weather Timeline")
    
    use_timeline = st.checkbox("Use Custom Weather Timeline")
    
    if use_timeline:
        num_events = st.number_input("Number of Events", 1, 10, 3)
        
        events = []
        for i in range(num_events):
            with st.expander(f"Event {i+1}"):
                start_step = st.number_input(f"Start Step", 0, config.steps, i*50, key=f"start_{i}")
                end_step = st.number_input(f"End Step", 0, config.steps, (i+1)*50, key=f"end_{i}")
                
                temp = st.slider(f"Temperature", -20, 40, 10, key=f"temp_{i}")
                precip = st.slider(f"Precipitation (mm/h)", 0.0, 20.0, 0.0, key=f"precip_{i}")
                wind = st.slider(f"Wind (km/h)", 0, 100, 10, key=f"wind_{i}")
                
                events.append({
                    'start': start_step,
                    'end': end_step,
                    'temperature': temp,
                    'precipitation': precip,
                    'wind_speed': wind,
                })
        
        config.weather_timeline = events
```

Example use case:

```
Event 1 (Steps 0-100): Normal winter (5°C, light rain)
Event 2 (Steps 100-200): Snowstorm (-5°C, heavy snow)
Event 3 (Steps 200-300): Recovery (2°C, clearing)
```

**Time to implement**: 4 hours  
**Value**: EXTREME - Full scenario control

---

## 📊 Use Cases Enabled by Perturbation

### 1. Policy Stress Testing
**Question**: "Can our emergency transit plan handle 3 days of ice?"

**Setup**:
```
Event: "🧊 Prolonged Ice"
Duration: 72 hours
Policies: Emergency transit activated
```

**Metrics**: 
- Transit ridership increase
- Mode shift from bike/walk to bus
- Grid stress from heating demand

---

### 2. Climate Change Scenarios
**Question**: "What if Scotland's winters warm by 3°C by 2050?"

**Setup**:
```
Temperature Adjustment: +3.0°C
Season: Winter (January)
Duration: Full simulation
```

**Results**:
- Less snow → more bike adoption
- Higher EV ranges → more EV adoption
- Lower grid heating load

---

### 3. Infrastructure Resilience
**Question**: "Do we have enough chargers for a summer heatwave?"

**Setup**:
```
Event: "🌡️ Heatwave"
Temperature: 35°C
Duration: 7 days
```

**Watch For**:
- EV charging demand spike (A/C use)
- Grid stress during peak hours
- Charger utilization hotspots

---

### 4. Freight Disruption Analysis
**Question**: "How does flooding affect delivery schedules?"

**Setup**:
```
Event: "🌊 Heavy Flooding"
Precipitation: 15 mm/h
Duration: 48 hours
```

**Metrics**:
- Freight delivery delays
- Mode shift to higher vehicles
- Economic impact (late deliveries)

---

## 🎨 UI Design Mockup

```
┌─────────────────────────────────────────┐
│ 🌤️ Weather Settings                     │
├─────────────────────────────────────────┤
│                                         │
│ ☑️ Enable Weather System                │
│                                         │
│ Weather Source:                         │
│ ● Live Forecast (Open-Meteo API)       │
│ ○ Historical Data (Jan 2024)           │
│ ○ Synthetic Pattern                    │
│                                         │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ │
│                                         │
│ 🌡️ Weather Perturbations               │
│                                         │
│ Preset Events:                          │
│ [None (Actual Weather) ▼]              │
│                                         │
│ OR Custom Adjustments:                  │
│                                         │
│ Temperature: [-10°C ●━━━━━━━ +10°C]   │
│ Current: +2.0°C warmer                 │
│                                         │
│ Precipitation: [0x ━━━●━━━━ 3x]       │
│ Current: 1.5x normal                   │
│                                         │
│ Wind Speed: [0.5x ━●━━━━━━ 2.0x]      │
│ Current: 1.0x normal                   │
│                                         │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ │
│                                         │
│ 📊 Preview Impact:                      │
│ • Bike speed: -30% (heavy rain)        │
│ • EV range: -15% (cold)                │
│ • Bus demand: +20% (weather shelter)   │
│                                         │
└─────────────────────────────────────────┘
```

---

## ✅ Recommendation: Start with Option 1, Upgrade to Option 2

**Phase 1** (1 hour - do this first!):
- Simple sliders for temp, precip, wind
- Immediate value for testing
- Easy to implement

**Phase 2** (add 1 hour later):
- Add extreme event presets
- Pre-configure realistic scenarios
- Better UX for common cases

**Phase 3** (future enhancement):
- Weather timeline scripting
- Save/load weather scenarios
- Weather scenario library

---

## 🎯 Strategic Value

This feature transforms RTD_SIM from a **simulation** into a **decision support tool**:

**Before**: "Here's what happened with realistic weather"  
**After**: "Here's what WOULD HAPPEN IF we had X weather"

Perfect for:
- **Policy makers**: Test resilience before investing
- **Emergency planners**: Scenario wargaming
- **Climate researchers**: Future climate impacts
- **Infrastructure designers**: Stress testing

**Bottom Line**: This is a **1-hour investment** for **10x** user value.

---

## 📝 Code Snippet to Get Started (15 min)

```python
# 1. Add to SimulationConfig (simulation_config.py)
@dataclass
class SimulationConfig:
    # ... existing fields ...
    
    # Weather perturbations
    weather_temp_adjustment: float = 0.0
    weather_precip_multiplier: float = 1.0
    weather_wind_multiplier: float = 1.0

# 2. Add to sidebar (ui/sidebar_config.py)
if weather_enabled:
    with st.expander("🌡️ Perturb Weather (Optional)", expanded=False):
        config.weather_temp_adjustment = st.slider(
            "Temperature Adjustment (°C)", -10.0, 10.0, 0.0, 0.5
        )
        config.weather_precip_multiplier = st.slider(
            "Precipitation Multiplier", 0.0, 3.0, 1.0, 0.1
        )
        config.weather_wind_multiplier = st.slider(
            "Wind Speed Multiplier", 0.5, 2.0, 1.0, 0.1
        )

# 3. Apply in weather_api.py (WeatherManager.update_weather)
if hasattr(config, 'weather_temp_adjustment'):
    self.current_conditions['temperature'] += config.weather_temp_adjustment
if hasattr(config, 'weather_precip_multiplier'):
    self.current_conditions['precipitation'] *= config.weather_precip_multiplier
if hasattr(config, 'weather_wind_multiplier'):
    self.current_conditions['wind_speed'] *= config.weather_wind_multiplier
```

**That's it! 15 minutes for powerful scenario testing.**
