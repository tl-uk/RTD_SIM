# RTD_SIM Phase 4.5G Handoff Document

**Date**: January 10, 2026  
**From**: Phase 4.5F (Expanded Freight Modes) - Complete ✅  
**To**: Phase 4.5G (Multi-Modal Transport Expansion)  
**Status**: Phase 4.5F validated, ready for 4.5G implementation

---

## 🎯 Current System Status

### ✅ Phase 4.5F Achievements
1. **13 Transport Modes Working**: walk, bike, bus, car, ev, cargo_bike, van_electric, van_diesel, truck_electric, truck_diesel, hgv_electric, hgv_diesel, hgv_hydrogen
2. **Hierarchical Freight Classification**: 4 vehicle types (micro_mobility, commercial, medium_freight, heavy_freight)
3. **Context-Driven Mode Selection**: BDI planner correctly filters modes by vehicle_type
4. **Infrastructure Integration**: Grid tracking, charging stations, time-of-day pricing
5. **17 Scenarios Loaded**: All freight + personal transport scenarios working
6. **Distance Constraints Fixed**: E-scooter bug resolved (line 165 in bdi_planner.py)
7. **Grid Utilization Chart Added**: Now shows historical utilization with thresholds

### 📊 Baseline Validation Results
```
Freight Distribution (realistic baseline):
- Van Diesel: 44.2%
- Truck Diesel: 52.9%
- Truck Electric: 1.9%
- HGV Diesel: 1.0%

Total Freight Adoption: 86%
Grid Utilization: ~0% (minimal EVs without subsidies)
Charging Ports: 204 available
```

---

## 🚀 Phase 4.5G Objectives (8 hours)

### New Transport Modes to Add (8 modes)
1. **Rail**: `local_train`, `intercity_train`
2. **Tram**: `tram` (light rail for urban corridors)
3. **Maritime**: `ferry_diesel`, `ferry_electric`
4. **Aviation**: `flight_domestic`, `flight_electric`
5. **Micro-mobility**: `e_scooter` (partially added, needs completion)

### New User Stories (5 personas)
1. `long_distance_commuter` - Edinburgh-Glasgow rail
2. `island_resident` - Ferry-dependent travel
3. `business_traveler` - Intercity flight/rail choice
4. `accessibility_user` - Wheelchair-dependent
5. `tourist_visitor` - Multi-modal scenic journeys

### New Job Stories (7 scenarios)
1. `intercity_train_commute` - Daily rail commute (80-120 km)
2. `island_ferry_trip` - Island-mainland connection (10-150 km)
3. `business_flight` - Urgent intercity travel (300-900 km)
4. `accessible_tram_journey` - Level boarding required (2-20 km)
5. `tourist_scenic_rail` - Leisure rail travel (50-250 km)
6. `last_mile_scooter` - Station to office (1-5 km)
7. `multi_modal_commute` - Combined bike+train+walk (stages)

---

## ⚠️ Issues Found & Fixes Needed

### Issue 1: Gig Economy Jobs Using Trucks ❌
**Current Behavior:**
```
Agent 1: eco_warrior_gig_economy_delivery_9823
Mode: truck_diesel (9.5 km)
vehicle_type: commercial
```

**Problem**: Gig economy delivery (9.5 km urban) should use **van** or **cargo_bike**, not a 7.5-tonne truck!

**Root Cause**: `job_contexts.yaml` line for `gig_economy_delivery`:
```yaml
gig_economy_delivery:
  parameters:
    vehicle_type: commercial  # ← Too generic!
```

**Fix**:
```yaml
gig_economy_delivery:
  parameters:
    vehicle_type: micro_mobility  # ← For short urban trips (<15 km)
    # OR set conditional logic based on typical_distance_km
```

**Alternative Fix**: Add distance-based vehicle_type selection in `story_driven_agent.py`:
```python
def _extract_agent_context(self) -> Dict:
    # If job is gig_economy_delivery and distance < 15km, override to micro_mobility
    if self.job_story_id == 'gig_economy_delivery':
        trip_distance = haversine_km(self.origin, self.dest)
        if trip_distance < 15:
            context['vehicle_type'] = 'micro_mobility'
        else:
            context['vehicle_type'] = 'commercial'
```

### Issue 2: Missing Grid Utilization Fluctuations
**Expected**: Grid utilization should show peaks/valleys based on:
- Time of day (morning/evening charging)
- Number of EVs charging
- Charging rate (fast vs slow)

**Current**: Shows flat ~0% because only 2 truck_electric agents (1.9% of fleet)

**Not a Bug**: This is correct for baseline! With minimal electric adoption and no subsidies, low charging is realistic.

**Will Fix Itself**: When you test "Complete Supply Chain Electrification" scenario with 30-40% electric adoption, you'll see fluctuations.

**To Verify Fix Works**: Run scenario and check Infrastructure tab shows varying utilization over time.

---

## 📂 Files to Bring to New Chat Window

### Core Implementation Files (Must Have)
1. **`agent/bdi_planner.py`** - Mode filtering logic (needs rail/tram/ferry additions)
2. **`agent/job_contexts.yaml`** - Job definitions (needs 7 new job stories)
3. **`agent/personas.yaml`** - User stories (needs 5 new personas)
4. **`simulation/metrics_calculator.py`** - Costs/speeds/emissions for new modes
5. **`visualiser/visualization.py`** - Mode colors for new modes
6. **`simulation/infrastructure_manager.py`** - For reference (already working)
7. **`agent/story_driven_agent.py`** - Context extraction (may need gig_economy fix)

### Reference Documents (Nice to Have)
8. **`multimodal_modes_design.md`** - Complete design spec for Phase 4.5G
9. **`phase_45g_implementation.md`** - Step-by-step implementation guide
10. **`scenarios/scenario_manager.py`** - Already working, but may need multi-modal scenarios
11. **`simulation/execution/simulation_loop.py`** - Infrastructure policy application (already fixed)

### Optional (For Context)
12. **`scenarios/configs/freight_electrification.yaml`** - Example of working multi-document YAML
13. **`phase_45f_final_validation.md`** - What was achieved in 4.5F
14. **`ui/main_tabs.py`** - For infrastructure tab updates
15. **`ui/sidebar_config.py`** - For test scenario selection

---

## 🎯 Implementation Priority for Phase 4.5G

### Tier 1: High Impact, Easy (Do First - 4 hours)
1. **Add 8 mode definitions** to `bdi_planner.py` MODE_MAX_DISTANCE_KM (see code snippet below)
2. **Add costs/speeds/emissions** to `metrics_calculator.py` (see code snippet below)
3. **Add mode colors** to `visualization.py` MODE_COLORS_RGB (see code snippet below)
4. **Create 5 new user stories** in `personas.yaml` (see template below)
5. **Create 7 new job stories** in `job_contexts.yaml` (see template below)

### Tier 2: Testing & Validation (Do Second - 2 hours)
6. **Test Edinburgh-Glasgow scenario** (80 km, should offer local_train)
7. **Test Edinburgh-London scenario** (640 km, should offer intercity_train + flight_domestic)
8. **Test island ferry routes** (should require ferry, then onward connection)
9. **Validate accessibility modes** (tram should be preferred for wheelchair users)
10. **Fix gig_economy_delivery vehicle selection** (use vans, not trucks for short trips)

### Tier 3: Scenarios & Documentation (Do Third - 2 hours)
11. **Create 2-3 multi-modal scenarios** (e.g., "Rail Enhancement", "Island Electrification")
12. **Update README** with new mode list
13. **Test grid utilization chart** with high EV adoption scenario
14. **Update UI for test case selection** (see UI Updates section below)

---

## 🔧 Code Snippets Ready to Use

### 1. Add to `bdi_planner.py` (Line 60-80)
```python
# Distance-based mode constraints - EXPANDED
MODE_MAX_DISTANCE_KM = {
    'walk': 5.0,
    'bike': 20.0,
    'cargo_bike': 10.0,
    'bus': 100.0,
    'car': 500.0,
    'ev': 350.0,
    
    # Freight modes (existing)
    'van_electric': 200.0,
    'van_diesel': 500.0,
    'truck_electric': 250.0,
    'truck_diesel': 600.0,
    'hgv_electric': 300.0,
    'hgv_diesel': 800.0,
    'hgv_hydrogen': 600.0,
    
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
}
```

### 2. Add to `bdi_planner.py` - EV_RANGE_KM
```python
EV_RANGE_KM = {
    'ev': 350.0,
    'van_electric': 200.0,
    'cargo_bike': 50.0,
    'truck_electric': 250.0,
    'hgv_electric': 300.0,
    'hgv_hydrogen': 600.0,
    'e_scooter': 30.0,
    'ferry_electric': 50.0,      # NEW
    'flight_electric': 500.0,    # NEW (future tech)
}
```

### 3. Add to `bdi_planner.py` - _filter_modes_by_context() (Line 177-182)
```python
# Add public transport modes for longer trips
if trip_distance_km > 30 and not vehicle_required:
    if trip_distance_km > 80:
        modes.extend(['intercity_train', 'flight_domestic'])
    modes.extend(['local_train', 'tram'])

# Add ferry for coastal/island routes
if context.get('coastal_route') or context.get('island_destination'):
    modes.extend(['ferry_diesel', 'ferry_electric'])

# E-scooter for short urban trips
if trip_distance_km < 15 and not cargo_capacity:
    modes.append('e_scooter')
```

### 4. Add to `metrics_calculator.py` - Costs
```python
self.cost = {
    # Existing modes...
    'walk': {'base': 0, 'per_km': 0},
    'bike': {'base': 0, 'per_km': 0},
    'bus': {'base': 2.5, 'per_km': 0.10},
    'car': {'base': 1.0, 'per_km': 0.40},
    'ev': {'base': 1.0, 'per_km': 0.15},
    
    # Freight (existing)
    'cargo_bike': {'base': 0.5, 'per_km': 0.05},
    'van_electric': {'base': 2.0, 'per_km': 0.20},
    'van_diesel': {'base': 2.0, 'per_km': 0.35},
    'truck_electric': {'base': 5.0, 'per_km': 0.40},
    'truck_diesel': {'base': 5.0, 'per_km': 0.60},
    'hgv_electric': {'base': 10.0, 'per_km': 0.80},
    'hgv_diesel': {'base': 10.0, 'per_km': 1.20},
    'hgv_hydrogen': {'base': 10.0, 'per_km': 1.00},
    
    # NEW: Public transport
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
    'e_scooter': {'base': 1.0, 'per_km': 0.25},
}
```

### 5. Add to `metrics_calculator.py` - Speeds
```python
self.speed = {
    # Existing modes...
    'walk': {'city': 5, 'highway': 5},
    'bike': {'city': 15, 'highway': 15},
    'bus': {'city': 20, 'highway': 60},
    'car': {'city': 30, 'highway': 100},
    'ev': {'city': 30, 'highway': 100},
    
    # Freight (existing)
    'cargo_bike': {'city': 15, 'highway': 15},
    'van_electric': {'city': 35, 'highway': 90},
    'van_diesel': {'city': 35, 'highway': 90},
    'truck_electric': {'city': 30, 'highway': 80},
    'truck_diesel': {'city': 30, 'highway': 80},
    'hgv_electric': {'city': 25, 'highway': 70},
    'hgv_diesel': {'city': 25, 'highway': 80},
    'hgv_hydrogen': {'city': 25, 'highway': 80},
    
    # NEW: Public transport
    'tram': {'city': 25, 'highway': 25},
    'local_train': {'city': 60, 'highway': 60},
    'intercity_train': {'city': 120, 'highway': 120},
    
    # NEW: Maritime
    'ferry_diesel': {'city': 35, 'highway': 35},
    'ferry_electric': {'city': 30, 'highway': 30},
    
    # NEW: Aviation
    'flight_domestic': {'city': 450, 'highway': 450},
    'flight_electric': {'city': 350, 'highway': 350},
    
    # NEW: Micro-mobility
    'e_scooter': {'city': 20, 'highway': 20},
}
```

### 6. Add to `metrics_calculator.py` - Emissions
```python
self.emissions = {
    # Zero emission
    'walk': 0,
    'bike': 0,
    'cargo_bike': 0,
    'e_scooter': 0,
    'ev': 0,
    
    # NEW: Electric public transport (grid carbon)
    'tram': 30,
    'local_train': 35,
    'intercity_train': 25,
    'ferry_electric': 40,
    'flight_electric': 50,
    
    # Combustion
    'bus': 80,
    'car': 180,
    'van_diesel': 250,
    'truck_diesel': 400,
    'hgv_diesel': 800,
    'hgv_hydrogen': 100,  # Some emissions from hydrogen production
    
    # NEW: High-emission modes
    'ferry_diesel': 120,
    'flight_domestic': 250,
}
```

### 7. Add to `visualization.py` (Line 40-80)
```python
MODE_COLORS_RGB = {
    # Personal transport
    'walk': [34, 197, 94],      # Green
    'bike': [59, 130, 246],     # Blue
    'bus': [245, 158, 11],      # Orange
    'car': [239, 68, 68],       # Red
    'ev': [168, 85, 245],       # Purple
    
    # Micro-delivery
    'cargo_bike': [34, 197, 94],      # Bright green
    
    # Light freight (vans)
    'van_electric': [16, 185, 129],   # Teal green
    'van_diesel': [107, 114, 128],    # Gray
    
    # Medium freight (trucks)
    'truck_electric': [74, 222, 128],  # Light green
    'truck_diesel': [120, 113, 108],   # Brown-gray
    
    # Heavy freight (HGVs)
    'hgv_electric': [52, 211, 153],    # Aqua green
    'hgv_diesel': [75, 85, 99],        # Dark gray
    'hgv_hydrogen': [96, 165, 250],    # Light blue
    
    # NEW: Public transport
    'tram': [255, 193, 7],        # Amber/Yellow (Edinburgh trams)
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
    'walk': '#22c55e',
    'bike': '#3b82f6',
    'bus': '#f59e0b',
    'car': '#ef4444',
    'ev': '#a855f7',
    'cargo_bike': '#22c55e',
    'van_electric': '#10b981',
    'van_diesel': '#6b7280',
    'truck_electric': '#4ade80',
    'truck_diesel': '#78716c',
    'hgv_electric': '#34d399',
    'hgv_diesel': '#4b5563',
    'hgv_hydrogen': '#60a5fa',
    
    # NEW modes
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

### 8. Add to `visualization.py` - render_mode_adoption_chart()
```python
def render_mode_adoption_chart(
    adoption_history: Dict[str, List[float]],
    current_step: int,
    height: int = 400
) -> go.Figure:
    """Render mode adoption over time chart with all modes."""
    fig = go.Figure()
    
    # ALL MODES (updated)
    all_modes = [
        'walk', 'bike', 'cargo_bike', 'e_scooter',
        'bus', 'car', 'ev',
        'tram', 'local_train', 'intercity_train',  # NEW
        'ferry_diesel', 'ferry_electric',  # NEW
        'flight_domestic', 'flight_electric',  # NEW
        'van_electric', 'van_diesel',
        'truck_electric', 'truck_diesel',
        'hgv_electric', 'hgv_diesel', 'hgv_hydrogen'
    ]
    
    for mode in all_modes:
        if mode in adoption_history and adoption_history[mode]:
            fig.add_trace(go.Scatter(
                x=list(range(len(adoption_history[mode]))),
                y=[v * 100 for v in adoption_history[mode]],
                mode='lines',
                name=mode.replace('_', ' ').title(),
                line=dict(width=3, color=MODE_COLORS_HEX.get(mode, '#808080'))
            ))
    
    fig.add_vline(x=current_step, line_dash="dash", line_color="red",
                 annotation_text="Now")
    
    fig.update_layout(
        xaxis_title="Time Step",
        yaxis_title="Adoption Rate (%)",
        hovermode='x unified',
        height=height,
        legend=dict(
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="left",
            x=1.02
        )
    )
    
    return fig
```

---

## 📝 User Story Templates

### Add to `personas.yaml`

```yaml
# ============================================================================
# PHASE 4.5G: Multi-Modal User Stories
# ============================================================================

long_distance_commuter:
  persona_type: professional
  description: "Lives in Edinburgh, works in Glasgow daily (80 km commute)"
  
  beliefs:
    - text: "Train is more productive than driving"
      confidence: 0.8
    - text: "Parking in city center is expensive and stressful"
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
    - "Must catch 8:15 train to arrive by 9am"
    - "Need reliable return train after 5pm"
  
  desire_variance: 0.10

island_resident:
  persona_type: rural
  description: "Lives on Scottish island, occasional mainland trips"
  
  beliefs:
    - text: "Ferry schedules dictate my life"
      confidence: 1.0
    - text: "Weather delays are common and unavoidable"
      confidence: 0.9
    - text: "Electric ferries would help the environment"
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
    - text: "Flight is fastest for Edinburgh-London"
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
    - text: "Trams are most accessible public transport"
      confidence: 0.9
    - text: "Level boarding is essential for independence"
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
  description: "Tourist exploring Scotland sustainably via public transport"
  
  beliefs:
    - text: "Scenic routes are part of the travel experience"
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

## 📋 Job Story Templates

### Add to `job_contexts.yaml`

```yaml
# ============================================================================
# PHASE 4.5G: Multi-Modal Job Stories
# ============================================================================

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
  
  csv_columns:
    required: ["origin_lat", "origin_lon", "dest_lat", "dest_lon"]
    optional: ["train_preference", "season_ticket"]

island_ferry_trip:
  context: "When traveling to/from island via ferry"
  goal: "I want reliable ferry service despite weather conditions"
  outcome: "So I can access mainland services and maintain connections"
  
  job_type: island_travel
  
  time_window:
    start: "06:00"
    end: "20:00"
    flexibility: high
  
  destination_type: mainland_town
  typical_distance_km: [10, 150]
  
  parameters:
    vehicle_required: false
    recurring: true
    urgency: medium
    weather_dependent: true
    ferry_booking_required: true
    island_destination: true  # Triggers ferry mode
  
  mode_preferences:
    required_first_leg: ['ferry_diesel', 'ferry_electric', 'flight_domestic']
    onward_modes: ['bus', 'car', 'local_train']
  
  plan_context:
    - "Ferry schedule is fixed (e.g., 3 sailings/day)"
    - "Weather can cancel sailings"
    - "Vehicle booking costs extra"
    - "May need to stay overnight if ferry canceled"
  
  csv_columns:
    required: ["island_lat", "island_lon", "mainland_lat", "mainland_lon"]
    optional: ["ferry_operator", "sailing_time"]

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
  
  csv_columns:
    required: ["origin_lat", "origin_lon", "dest_lat", "dest_lon"]
    optional: ["meeting_time", "flexibility"]

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
    wheelchair_accessible: true
  
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
  
  csv_columns:
    required: ["origin_lat", "origin_lon", "dest_lat", "dest_lon"]
    optional: ["accessibility_features"]

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
  
  csv_columns:
    required: ["origin_lat", "origin_lon", "dest_lat", "dest_lon"]
    optional: ["scenic_route_name", "attractions"]

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
  
  csv_columns:
    required: ["station_lat", "station_lon", "dest_lat", "dest_lon"]
    optional: ["scooter_available"]

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
  
  csv_columns:
    required: ["home_lat", "home_lon", "work_lat", "work_lon"]
    optional: ["station_lat", "station_lon"]
```

---

## 🧪 Test Cases for Validation

### Test Configuration Requirements

To conduct these tests, the UI needs to support:
1. **Custom origin/destination selection** (lat/lon or place names)
2. **Specific user story selection** (not random)
3. **Specific job story selection** (not random)
4. **Expected mode display** (show what modes were offered vs chosen)

### UI Updates Needed

#### 1. Add Test Mode to Sidebar (`ui/sidebar_config.py`)

```python
def render_sidebar_config():
    """Render sidebar configuration."""
    st.header("⚙️ Simulation Configuration")
    
    # NEW: Test Mode Toggle
    test_mode = st.checkbox(
        "🧪 Enable Test Mode",
        value=False,
        help="Manually select origin, destination, user story, and job story for testing"
    )
    
    if test_mode:
        return render_test_mode_config()
    else:
        return render_standard_config()

def render_test_mode_config():
    """Render test mode configuration."""
    st.subheader("🎯 Test Configuration")
    
    # Test case selection
    test_case = st.selectbox(
        "Select Test Case",
        [
            "Custom",
            "Edinburgh-Glasgow Rail (80km)",
            "Edinburgh-London Flight/Rail (640km)",
            "Island Ferry Route (50km)",
            "Accessible Tram Journey (10km)",
            "Tourist Scenic Rail (150km)",
            "Last Mile Scooter (3km)",
            "Multi-Modal Commute (50km)"
        ]
    )
    
    if test_case == "Custom":
        # Manual configuration
        origin_name = st.text_input("Origin (place name)", "Edinburgh")
        dest_name = st.text_input("Destination (place name)", "Glasgow")
        
        # User/Job story selection
        user_story = st.selectbox("User Story", [
            "long_distance_commuter", "island_resident", "business_traveler",
            "accessibility_user", "tourist_visitor"
        ])
        job_story = st.selectbox("Job Story", [
            "intercity_train_commute", "island_ferry_trip", "business_flight",
            "accessible_tram_journey", "tourist_scenic_rail", "last_mile_scooter"
        ])
        
    else:
        # Pre-configured test case
        origin_name, dest_name, user_story, job_story = get_test_case_config(test_case)
        st.info(f"📍 **Origin**: {origin_name} → **Destination**: {dest_name}")
        st.info(f"👤 **User**: {user_story} | 📋 **Job**: {job_story}")
    
    # Create config
    config = SimulationConfig(
        steps=100,
        num_agents=1,  # Single agent for testing
        place=None,
        use_osm=True,
        extended_bbox=True,  # Use Edinburgh-Glasgow region
        enable_infrastructure=True,
        enable_social=False,
        user_story_ids=[user_story],
        job_story_ids=[job_story],
        test_mode=True,
        test_origin=origin_name,
        test_destination=dest_name
    )
    
    run_btn = st.button("🧪 Run Test", type="primary", key="test_run")
    
    return config, run_btn

def get_test_case_config(test_case: str) -> tuple:
    """Get origin, destination, user, and job for test case."""
    configs = {
        "Edinburgh-Glasgow Rail (80km)": (
            "Edinburgh", "Glasgow",
            "long_distance_commuter", "intercity_train_commute"
        ),
        "Edinburgh-London Flight/Rail (640km)": (
            "Edinburgh", "London",
            "business_traveler", "business_flight"
        ),
        "Island Ferry Route (50km)": (
            "Isle of Arran", "Glasgow",
            "island_resident", "island_ferry_trip"
        ),
        "Accessible Tram Journey (10km)": (
            "Edinburgh Waverley", "Edinburgh Airport",
            "accessibility_user", "accessible_tram_journey"
        ),
        "Tourist Scenic Rail (150km)": (
            "Fort William", "Mallaig",
            "tourist_visitor", "tourist_scenic_rail"
        ),
        "Last Mile Scooter (3km)": (
            "Edinburgh Waverley", "Edinburgh Castle",
            "long_distance_commuter", "last_mile_scooter"
        ),
        "Multi-Modal Commute (50km)": (
            "Livingston", "Glasgow",
            "long_distance_commuter", "multi_modal_commute"
        ),
    }
    return configs.get(test_case, ("Edinburgh", "Glasgow", "long_distance_commuter", "intercity_train_commute"))
```

#### 2. Add Test Results Display (`ui/diagnostics_panel.py`)

```python
def render_test_mode_diagnostics(results):
    """Render detailed diagnostics for test mode."""
    st.subheader("🧪 Test Results")
    
    if not results.agents or len(results.agents) == 0:
        st.warning("No agents in test")
        return
    
    agent = results.agents[0]
    
    # Test agent details
    with st.expander("🎯 Test Agent Details", expanded=True):
        col1, col2 = st.columns(2)
        
        with col1:
            st.write(f"**User Story**: {agent.user_story_id}")
            st.write(f"**Job Story**: {agent.job_story_id}")
            st.write(f"**Mode Chosen**: {agent.state.mode}")
            st.write(f"**Distance**: {agent.state.distance_km:.1f} km")
        
        with col2:
            st.write(f"**Arrived**: {agent.state.arrived}")
            st.write(f"**Travel Time**: {agent.state.travel_time_min:.1f} min")
            st.write(f"**Emissions**: {agent.state.emissions_g:.0f} g CO₂")
            st.write(f"**Cost**: ${agent.state.action_params.get('cost', 0):.2f}")
    
    # Modes considered
    with st.expander("🚦 Modes Considered", expanded=True):
        if hasattr(agent.state, 'mode_costs') and agent.state.mode_costs:
            costs_df = pd.DataFrame([
                {"Mode": mode, "Cost": cost, "Selected": mode == agent.state.mode}
                for mode, cost in agent.state.mode_costs.items()
            ]).sort_values('Cost')
            
            st.dataframe(costs_df, use_container_width=True)
        else:
            st.info("Mode costs not available")
    
    # Expected vs Actual
    with st.expander("✅ Validation", expanded=True):
        expected_modes = get_expected_modes_for_test(agent.job_story_id, agent.state.distance_km)
        
        if agent.state.mode in expected_modes:
            st.success(f"✅ Mode '{agent.state.mode}' is in expected modes: {expected_modes}")
        else:
            st.error(f"❌ Mode '{agent.state.mode}' NOT in expected modes: {expected_modes}")

def get_expected_modes_for_test(job_story_id: str, distance_km: float) -> list:
    """Get expected modes for validation."""
    expectations = {
        "intercity_train_commute": ["local_train", "intercity_train", "car", "ev"],
        "island_ferry_trip": ["ferry_diesel", "ferry_electric"],
        "business_flight": ["flight_domestic", "intercity_train"],
        "accessible_tram_journey": ["tram", "bus", "car"],
        "tourist_scenic_rail": ["local_train", "intercity_train", "ferry_diesel"],
        "last_mile_scooter": ["e_scooter", "bike", "walk", "tram"],
        "multi_modal_commute": ["local_train", "bike", "e_scooter"],
    }
    return expectations.get(job_story_id, ["walk", "bike", "bus", "car"])
```

### Test Case Execution Steps

#### Test 1: Edinburgh-Glasgow Rail (80 km)
**Setup:**
1. Enable Test Mode in sidebar
2. Select "Edinburgh-Glasgow Rail (80km)" from dropdown
3. Click "Run Test"

**Expected Result:**
```
Modes Offered: local_train, intercity_train, car, ev, bus
Mode Chosen: local_train (70-80% probability)
Reasoning: Distance 80km, train most efficient for this corridor
```

**Validation Checks:**
- ✅ local_train or intercity_train in modes offered
- ✅ Agent chooses train (unless has very high time desire AND train slow)
- ✅ Travel time ~50-60 minutes
- ✅ Emissions < 50g CO₂/km

#### Test 2: Edinburgh-London Flight/Rail (640 km)
**Setup:**
1. Select "Edinburgh-London Flight/Rail (640km)"
2. Run with business_traveler (time: 0.95)

**Expected Result:**
```
Modes Offered: intercity_train, flight_domestic
Mode Chosen: flight_domestic (if time > 0.8)
             OR intercity_train (if eco > 0.7)
Reasoning: Flight faster (1.5h + airport time vs 4.5h train)
```

**Validation Checks:**
- ✅ Both flight_domestic AND intercity_train offered
- ✅ Business traveler chooses flight (time=0.95)
- ✅ Eco warrior chooses train (eco=0.9)

#### Test 3: Island Ferry Route (50 km)
**Setup:**
1. Select "Island Ferry Route (50km)"
2. Run with island_resident

**Expected Result:**
```
Modes Offered: ferry_diesel, ferry_electric (REQUIRED)
              + bus/car for onward journey
Mode Chosen: ferry_diesel (weather permitting)
Reasoning: No alternative for island-mainland connection
```

**Validation Checks:**
- ✅ Ferry mode is REQUIRED (no other option for island)
- ✅ context.island_destination = True triggers ferry
- ✅ Weather-dependent flag acknowledged

#### Test 4: Accessible Tram Journey (10 km)
**Setup:**
1. Select "Accessible Tram Journey (10km)"
2. Run with accessibility_user

**Expected Result:**
```
Modes Offered: tram (level boarding), bus, car
NOT Offered: bike, e_scooter, walk (accessibility filtered)
Mode Chosen: tram (accessibility: 1.0 desire)
Reasoning: Level boarding essential for wheelchair
```

**Validation Checks:**
- ✅ context.wheelchair_accessible = True
- ✅ Active transport modes (bike, e_scooter) NOT offered
- ✅ Tram chosen due to accessibility: 1.0 desire
- ✅ Level boarding mentioned in reasoning

#### Test 5: Tourist Scenic Rail (150 km)
**Setup:**
1. Select "Tourist Scenic Rail (150km)"
2. Run with tourist_visitor

**Expected Result:**
```
Modes Offered: local_train, intercity_train, ferry_diesel, bus
Mode Chosen: local_train (scenic routes preferred)
Reasoning: Time not critical (time: 0.3), scenic: 0.95, eco: 0.9
```

**Validation Checks:**
- ✅ Train modes offered for 150km distance
- ✅ Tourist chooses rail despite longer time
- ✅ scenic_preference = 0.95 influences choice
- ✅ Low time desire (0.3) allows slower modes

#### Test 6: Last Mile Scooter (3 km)
**Setup:**
1. Select "Last Mile Scooter (3km)"
2. Run from "Edinburgh Waverley" to "Edinburgh Castle"

**Expected Result:**
```
Modes Offered: e_scooter, bike, walk, tram
Mode Chosen: e_scooter (convenience + speed for 3km)
Reasoning: Short distance, urban, no cargo
```

**Validation Checks:**
- ✅ Distance < 15km triggers e_scooter offer
- ✅ No cargo_capacity requirement
- ✅ E-scooter chosen for 3km (sweet spot)
- ✅ Walk not chosen (distance too far)

#### Test 7: Multi-Modal Commute (50 km)
**Setup:**
1. Select "Multi-Modal Commute (50km)"
2. Run from "Livingston" to "Glasgow"

**Expected Result:**
```
Stage 1 (Home → Station, 5km): bike, e_scooter
Stage 2 (Station → City, 40km): local_train
Stage 3 (City → Office, 2km): walk, tram, e_scooter

CURRENT LIMITATION: BDI planner doesn't support multi-stage yet!
This will be Phase 5.1 feature.
```

**Validation Checks:**
- ⚠️ Currently will only plan single-mode journey
- ✅ For now, validates that train is offered for 50km total
- 🚀 Full multi-modal chaining = Phase 5.1

---

## 📋 Post-Phase 4.5G: Freight Weight Multiplier

Once Phase 4.5G is validated and working, implement freight weight impact on charging:

### Add to `infrastructure_manager.py`

```python
def calculate_freight_charging_time(
    vehicle_mode: str,
    cargo_weight_kg: float,
    distance_traveled_km: float
) -> float:
    """
    Calculate charging time based on freight weight and distance.
    
    Heavier loads drain battery faster, requiring longer charging.
    
    Args:
        vehicle_mode: Vehicle type
        cargo_weight_kg: Cargo weight in kilograms
        distance_traveled_km: Distance traveled
    
    Returns:
        Charging time in minutes
    """
    # Base charging times (empty vehicle)
    base_charging_min = {
        'van_electric': 60,      # 1 hour
        'truck_electric': 120,   # 2 hours
        'hgv_electric': 180,     # 3 hours
    }
    
    base_time = base_charging_min.get(vehicle_mode, 60)
    
    # Weight multiplier (heavier = more energy used)
    # +10% charging time per tonne above 500kg
    if cargo_weight_kg > 500:
        weight_multiplier = 1 + ((cargo_weight_kg - 500) / 10000)
    else:
        weight_multiplier = 1.0
    
    # Distance multiplier (longer trips = more charging needed)
    # +10% per 100km traveled
    distance_multiplier = 1 + (distance_traveled_km / 1000)
    
    return base_time * weight_multiplier * distance_multiplier
```

### Add cargo_weight_kg to job stories

```yaml
long_haul_freight:
  parameters:
    vehicle_type: heavy_freight
    cargo_weight_kg: 15000  # 15 tonnes (near max for HGV)