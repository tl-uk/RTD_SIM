# Phase 4.5G Implementation Guide
## Multi-Modal Transport Expansion (8 hours)

---

## 🎯 Goals

1. Add 8 new transport modes (rail, tram, ferry, air, e-scooter)
2. Create diverse user/job stories for realistic travel patterns
3. Enable Edinburgh-Glasgow, Edinburgh-London, and island scenarios
4. Prepare infrastructure for Phase 5 system dynamics

---

## 📝 Step-by-Step Implementation

### Step 1: Update BDI Planner (1 hour)

**File:** `agent/bdi_planner.py`

Add to `MODE_MAX_DISTANCE_KM`:
```python
MODE_MAX_DISTANCE_KM = {
    # Existing modes...
    'walk': 5.0,
    'bike': 20.0,
    'cargo_bike': 10.0,
    
    # NEW: Public transport
    'tram': 25.0,
    'local_train': 150.0,
    'intercity_train': 800.0,
    
    # NEW: Maritime
    'ferry_diesel': 200.0,
    'ferry_electric': 50.0,
    
    # NEW: Aviation
    'flight_domestic': 1000.0,
    'flight_electric': 500.0,
    
    # NEW: Micro-mobility
    'e_scooter': 30.0,
    
    # Existing freight...
}
```

Add to `EV_RANGE_KM` (for electric modes):
```python
EV_RANGE_KM = {
    'ev': 350.0,
    'van_electric': 200.0,
    'cargo_bike': 50.0,
    'truck_electric': 250.0,
    'hgv_electric': 300.0,
    'hgv_hydrogen': 600.0,
    'e_scooter': 30.0,          # NEW
    'ferry_electric': 50.0,      # NEW
    'flight_electric': 500.0,    # NEW (future tech)
}
```

Update `_filter_modes_by_context()` to handle new mode types:
```python
def _filter_modes_by_context(self, context: Dict, trip_distance_km: float = 0.0) -> List[str]:
    # ... existing code ...
    
    # Add public transport modes for longer trips
    if trip_distance_km > 30 and not vehicle_required:
        if trip_distance_km > 80:
            modes.extend(['intercity_train', 'flight_domestic'])
        modes.extend(['local_train', 'tram'])
    
    # Add ferry for coastal/island routes (would need geography check)
    if context.get('coastal_route') or context.get('island_destination'):
        modes.extend(['ferry_diesel', 'ferry_electric'])
    
    # E-scooter for short urban trips
    if trip_distance_km < 15 and not cargo_capacity:
        modes.append('e_scooter')
    
    # ... rest of existing logic ...
```

---

### Step 2: Update Metrics Calculator (1 hour)

**File:** `simulation/metrics_calculator.py`

Add costs for new modes:
```python
self.cost = {
    # Existing modes...
    
    # NEW: Public transport (per trip or per km)
    'tram': {'base': 2.0, 'per_km': 0.08},
    'local_train': {'base': 3.0, 'per_km': 0.12},
    'intercity_train': {'base': 10.0, 'per_km': 0.15},
    
    # NEW: Maritime
    'ferry_diesel': {'base': 15.0, 'per_km': 0.25},
    'ferry_electric': {'base': 12.0, 'per_km': 0.20},
    
    # NEW: Aviation
    'flight_domestic': {'base': 50.0, 'per_km': 0.20},
    'flight_electric': {'base': 60.0, 'per_km': 0.15},
    
    # NEW: Micro-mobility
    'e_scooter': {'base': 1.0, 'per_km': 0.25},  # Rental model
}
```

Add speeds:
```python
self.speed = {
    # Existing modes...
    
    # NEW modes
    'tram': {'city': 25, 'highway': 25},
    'local_train': {'city': 60, 'highway': 60},
    'intercity_train': {'city': 120, 'highway': 120},
    'ferry_diesel': {'city': 35, 'highway': 35},
    'ferry_electric': {'city': 30, 'highway': 30},
    'flight_domestic': {'city': 450, 'highway': 450},  # Cruise speed
    'flight_electric': {'city': 350, 'highway': 350},
    'e_scooter': {'city': 20, 'highway': 20},
}
```

Add emissions (g CO2/km):
```python
self.emissions = {
    # Zero emission
    'walk': 0,
    'bike': 0,
    'cargo_bike': 0,
    'e_scooter': 0,
    'ev': 0,
    'tram': 30,              # NEW: Electric (grid carbon)
    'local_train': 35,       # NEW: Electric rail
    'intercity_train': 25,   # NEW: High-efficiency electric
    'ferry_electric': 40,    # NEW: Battery ferry
    'flight_electric': 50,   # NEW: Future e-aviation
    
    # Combustion
    'bus': 80,
    'car': 180,
    'ferry_diesel': 120,     # NEW: Per passenger
    'flight_domestic': 250,  # NEW: High emissions per passenger-km
    'van_diesel': 250,
    'truck_diesel': 400,
    'hgv_diesel': 800,
}
```

---

### Step 3: Add User Stories (1.5 hours)

**File:** `agent/personas.yaml`

Add 5 new user story types:

```yaml
long_distance_commuter:
  persona_type: professional
  description: "Lives in Edinburgh, works in Glasgow daily"
  
  beliefs:
    - text: "Train is more productive than driving"
      confidence: 0.8
    - text: "Parking costs make train economical"
      confidence: 0.85
    - text: "I can work on the train"
      confidence: 0.9
  
  desires:
    time: 0.7
    cost: 0.5
    comfort: 0.8
    eco: 0.6
    productivity: 0.9
    reliability: 0.85
  
  constraints:
    - "Must catch 8:15 train"
    - "Return train after 17:00"
  
  desire_variance: 0.10

island_resident:
  persona_type: rural
  description: "Lives on Scottish island, occasional mainland trips"
  
  beliefs:
    - text: "Ferry schedules dictate my life"
      confidence: 1.0
    - text: "Weather delays are common"
      confidence: 0.9
    - text: "Electric ferries would help environment"
      confidence: 0.8
  
  desires:
    time: 0.4
    cost: 0.8
    reliability: 0.9
    eco: 0.7
    flexibility: 0.3
  
  constraints:
    - "Must book ferry in advance"
    - "Weather-dependent travel"
  
  desire_variance: 0.15

business_traveler:
  persona_type: executive
  description: "Frequent intercity travel for business meetings"
  
  beliefs:
    - text: "Time is money"
      confidence: 1.0
    - text: "First class is worth it for productivity"
      confidence: 0.8
    - text: "Flight is fastest for long distances"
      confidence: 0.85
  
  desires:
    time: 0.95
    cost: 0.3
    comfort: 0.9
    productivity: 0.9
    eco: 0.4
  
  constraints:
    - "Meeting times are fixed"
    - "Prefer same-day returns"
  
  desire_variance: 0.08

accessibility_user:
  persona_type: disabled
  description: "Wheelchair user requiring accessible transport"
  
  beliefs:
    - text: "Trams are most accessible"
      confidence: 0.9
    - text: "Level boarding is essential"
      confidence: 1.0
    - text: "Many transport options exclude me"
      confidence: 0.8
  
  desires:
    accessibility: 1.0
    comfort: 0.8
    reliability: 0.9
    independence: 0.95
    time: 0.5
    cost: 0.6
  
  constraints:
    - "Requires level boarding or ramps"
    - "Cannot use stairs"
  
  desire_variance: 0.05

tourist_visitor:
  persona_type: visitor
  description: "Tourist exploring Scotland sustainably"
  
  beliefs:
    - text: "Scenic routes are part of the experience"
      confidence: 0.95
    - text: "Public transport is eco-friendly"
      confidence: 0.85
    - text: "I want to minimize my carbon footprint"
      confidence: 0.8
  
  desires:
    eco: 0.9
    scenic: 0.95
    cost: 0.6
    comfort: 0.6
    time: 0.3
    experience: 0.95
  
  constraints:
    - "No car rental"
    - "Luggage limits active transport"
  
  desire_variance: 0.12
```

---

### Step 4: Add Job Stories (2 hours)

**File:** `agent/job_contexts.yaml`

Add 7 new job story types:

```yaml
intercity_train_commute:
  context: "When commuting between cities daily by train"
  goal: "I want reliable train service that allows productive travel time"
  outcome: "So I maintain work-life balance and avoid driving stress"
  
  job_type: commute
  
  time_window:
    start: "07:00"
    end: "09:00"
    flexibility: low
    return_trip: true
    return_start: "17:00"
  
  destination_type: city_office
  typical_distance_km: [70, 120]
  
  parameters:
    vehicle_required: false
    recurring: true
    urgency: medium
    work_while_traveling: true
  
  mode_preferences:
    preferred: ['local_train', 'intercity_train']
    acceptable: ['car', 'ev']
    avoid: ['bike', 'walk']
  
  plan_context:
    - "Train delays affect arrival time"
    - "Can work on laptop during journey"
    - "Station parking may be needed"
    - "Season ticket offers savings"

island_ferry_trip:
  context: "When traveling to/from island via ferry"
  goal: "I want reliable ferry service despite weather conditions"
  outcome: "So I can access mainland services and maintain connections"
  
  job_type: island_travel
  
  time_window:
    start: "06:00"
    end: "20:00"
    flexibility: high  # Must work around ferry schedule
  
  destination_type: mainland_town
  typical_distance_km: [10, 150]  # Ferry + onward
  
  parameters:
    vehicle_required: false
    recurring: true
    urgency: medium
    weather_dependent: true
    ferry_booking_required: true
  
  mode_preferences:
    required_first_leg: ['ferry_diesel', 'ferry_electric', 'flight_domestic']
    onward_modes: ['bus', 'car', 'local_train']
  
  plan_context:
    - "Ferry schedule is fixed (e.g., 3 sailings/day)"
    - "Weather can cancel sailings"
    - "Vehicle booking costs extra"
    - "May need to stay overnight if ferry canceled"

business_flight:
  context: "When flying for urgent business meeting"
  goal: "I want fastest possible travel to maximize work time"
  outcome: "So I attend meeting and return same day"
  
  job_type: business_travel
  
  time_window:
    start: "06:00"
    end: "10:00"
    flexibility: very_low
    return_trip: true
    return_by: "20:00"
  
  destination_type: city_center
  typical_distance_km: [300, 900]
  
  parameters:
    vehicle_required: false
    recurring: false
    urgency: high
    luggage_minimal: true
  
  mode_preferences:
    preferred: ['flight_domestic', 'intercity_train']
    acceptable: ['car', 'ev']
    avoid: ['bus', 'ferry']
  
  desire_overrides:
    time: 0.95
    cost: 0.2
  
  plan_context:
    - "Airport security adds 90+ minutes"
    - "Flight faster for long distances"
    - "Train competitive under 400km"
    - "Same-day return required"

accessible_tram_journey:
  context: "When traveling as wheelchair user using accessible transport"
  goal: "I want guaranteed accessible boarding and space"
  outcome: "So I travel independently and with dignity"
  
  job_type: accessible_travel
  
  time_window:
    start: "09:00"
    end: "17:00"
    flexibility: medium
  
  destination_type: urban
  typical_distance_km: [2, 20]
  
  parameters:
    vehicle_required: false
    recurring: true
    urgency: medium
    accessibility_required: true
  
  mode_preferences:
    preferred: ['tram', 'accessible_bus']
    acceptable: ['car', 'accessible_taxi']
    avoid: ['bike', 'walk', 'e_scooter', 'ferry', 'flight']
  
  accessibility_requirements:
    level_boarding: true
    wheelchair_space: true
    audio_announcements: true
  
  plan_context:
    - "Trams have level boarding (ideal)"
    - "Not all buses have working ramps"
    - "Crowded vehicles may lack space"
    - "Apps don't always show accessibility info"

tourist_scenic_rail:
  context: "When exploring Scotland via scenic rail routes"
  goal: "I want beautiful journeys that are environmentally friendly"
  outcome: "So travel becomes part of the experience, not just transport"
  
  job_type: tourism
  
  time_window:
    start: "09:00"
    end: "18:00"
    flexibility: very_high
  
  destination_type: scenic_attraction
  typical_distance_km: [50, 250]
  
  parameters:
    vehicle_required: false
    recurring: false
    urgency: low
    luggage_present: true
    scenic_preference: 0.95
  
  mode_preferences:
    preferred: ['local_train', 'intercity_train', 'ferry_diesel']
    acceptable: ['bus', 'e_scooter']
    avoid: ['car', 'flight_domestic']
  
  plan_context:
    - "Scenic routes like West Highland Line"
    - "Time is not critical, views matter"
    - "Prefer window seats"
    - "Eco-conscious travel choices"

last_mile_scooter:
  context: "When covering last mile from train station to destination"
  goal: "I want quick, convenient connection from station"
  outcome: "So I complete journey efficiently without needing a car"
  
  job_type: last_mile
  
  time_window:
    start: "07:00"
    end: "20:00"
    flexibility: medium
  
  destination_type: urban_office
  typical_distance_km: [1, 5]
  
  parameters:
    vehicle_required: false
    recurring: true
    urgency: medium
    weather_dependent: true
  
  mode_preferences:
    preferred: ['e_scooter', 'bike', 'walk']
    acceptable: ['tram', 'bus']
    avoid: ['car', 'ev']
  
  plan_context:
    - "Train station to office ~2km"
    - "Scooter rental available at station"
    - "Weather affects scooter viability"
    - "Bike share alternative"

multi_modal_commute:
  context: "When combining bike + train + walk for commute"
  goal: "I want seamless multi-modal journey"
  outcome: "So I commute sustainably and enjoy the variety"
  
  job_type: commute
  
  stages:
    - stage_id: 1
      mode: ['bike', 'e_scooter']
      destination: train_station
      typical_distance_km: [3, 7]
      bike_parking_required: true
    
    - stage_id: 2
      mode: ['local_train']
      destination: city_center_station
      typical_distance_km: [40, 80]
    
    - stage_id: 3
      mode: ['walk', 'tram', 'e_scooter']
      destination: workplace
      typical_distance_km: [0.5, 3]
  
  time_window:
    start: "07:30"
    end: "09:00"
    flexibility: low
  
  parameters:
    vehicle_required: false
    recurring: true
    urgency: medium
    multi_stage: true
  
  plan_context:
    - "Bike parking must be available at station"
    - "Cannot miss train connection"
    - "Weather affects first mile choice"
    - "Fold-up bike alternative"
```

---

### Step 5: Update Visualization (1 hour)

**File:** `visualiser/visualization.py`

Add colors for new modes:
```python
MODE_COLORS_RGB = {
    # Existing modes...
    
    # NEW: Public transport
    'tram': [255, 193, 7],        # Amber/Yellow (like Edinburgh trams)
    'local_train': [33, 150, 243], # Blue
    'intercity_train': [63, 81, 181], # Indigo
    
    # NEW: Maritime
    'ferry_diesel': [0, 150, 136],   # Teal
    'ferry_electric': [0, 188, 212], # Cyan
    
    # NEW: Aviation
    'flight_domestic': [244, 67, 54], # Red
    'flight_electric': [233, 30, 99], # Pink
    
    # NEW: Micro-mobility
    'e_scooter': [139, 195, 74],   # Light green
}

MODE_COLORS_HEX = {
    # ... corresponding hex values ...
    'tram': '#ffc107',
    'local_train': '#2196f3',
    'intercity_train': '#3f51b5',
    'ferry_diesel': '#009688',
    'ferry_electric': '#00bcd4',
    'flight_domestic': '#f44336',
    'flight_electric': '#e91e63',
    'e_scooter': '#8bc34a',
}
```

---

### Step 6: Test with Edinburgh-Glasgow Scenario (1 hour)

Create test scenario file:

**File:** `scenarios/configs/edinburgh_glasgow_rail.yaml`

```yaml
name: Edinburgh-Glasgow Rail Enhancement
description: Improve rail service between Edinburgh and Glasgow to reduce car usage
policies:
  # Increase train frequency (reduce wait times)
  - parameter: frequency_multiplier
    value: 2.0
    target: mode
    mode: local_train
  
  # Reduce rail costs
  - parameter: cost_reduction
    value: 20.0
    target: mode
    mode: local_train
  
  # Add parking at stations
  - parameter: station_parking_capacity
    value: 500
    target: infrastructure
  
  # Congestion charge on M8 (car route)
  - parameter: cost_multiplier
    value: 1.5
    target: mode
    mode: car

duration: 100
expected_outcomes:
  train_adoption: 0.45
  car_reduction: 0.30
  emissions_reduction: 0.25
  
metadata:
  policy_type: public_transport_enhancement
  corridor: edinburgh_glasgow
  distance_km: 80
```

**Test:**
1. Select user stories: `long_distance_commuter`, `business_traveler`, `budget_student`
2. Select job stories: `intercity_train_commute`, `business_flight`
3. Region: **Central Scotland (Edinburgh-Glasgow)**
4. Scenario: **Edinburgh-Glasgow Rail Enhancement**
5. Run simulation

**Expected results:**
```
local_train: 35-45%  ← Should be high
car: 15-25%          ← Should decrease
ev: 10-15%
bus: 10-15%
```

---

### Step 7: Documentation (0.5 hours)

Update README and handoff docs with:
- List of new modes
- Distance suitability matrix
- Example user/job stories
- How to test multi-modal scenarios

---

## 🧪 Validation Tests

### Test 1: Short Urban Trip (< 5km)
**Modes expected:** walk, bike, e_scooter, tram
**Jobs:** last_mile_scooter, shopping_trip
**Result:** ✓ Active/micro-mobility dominant

### Test 2: Edinburgh-Glasgow (80km)
**Modes expected:** local_train, car, ev, bus
**Jobs:** intercity_train_commute
**Result:** ✓ Train competitive with car

### Test 3: Edinburgh-London (640km)
**Modes expected:** intercity_train, flight_domestic
**Jobs:** business_flight, tourist_scenic_rail
**Result:** ✓ Flight vs train tradeoff

### Test 4: Island Route (10-50km)
**Modes expected:** ferry_diesel, ferry_electric
**Jobs:** island_ferry_trip
**Result:** ✓ Ferry required, weather affects choice

### Test 5: Accessible Journey
**Modes expected:** tram (preferred), accessible_bus, car
**Jobs:** accessible_tram_journey
**Result:** ✓ Level boarding modes only

---

## ✅ Success Criteria

- [ ] 8 new modes added to bdi_planner.py
- [ ] Costs, speeds, emissions defined for all modes
- [ ] 5 new user stories in personas.yaml
- [ ] 7 new job stories in job_contexts.yaml
- [ ] Mode colors added to visualization
- [ ] Edinburgh-Glasgow test scenario working
- [ ] Train adoption 35%+ with rail enhancement scenario
- [ ] Accessibility modes working (tram preferred)
- [ ] Island ferry routes functional
- [ ] Documentation updated

---

## 🚀 Ready for Phase 5 After This

With multi-modal foundation in place, Phase 5 can add:
- System dynamics (mode shift cascades)
- Environmental impact (air quality zones)
- Infrastructure optimization (charger placement algorithms)
- Long-term carbon budgets
- Grid stress feedback loops

**Estimated completion: 8 hours → Ready for comprehensive decarbonization analysis**
