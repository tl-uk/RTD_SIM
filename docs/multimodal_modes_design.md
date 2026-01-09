# Phase 4.5G: Multi-Modal Transport Expansion

## Overview

Extends RTD_SIM to cover ALL decarbonization-relevant transport modes for comprehensive what-if analysis.

**Goals:**
1. Enable realistic multi-modal journey planning
2. Capture modal shift cascades (e.g., congestion → rail adoption)
3. Prepare for Phase 5 system dynamics (grid stress, infrastructure planning)
4. Support long-distance scenarios (Edinburgh → London, Glasgow → Aberdeen)

---

## 🚊 New Transport Modes

### Public Transport (Rail & Tram)

#### Local Rail
```python
'local_train': {
    'type': 'rail',
    'electrified': True,
    'range_km': 150,
    'avg_speed_kmh': 60,
    'cost_per_km': 0.12,
    'emissions_g_per_km': 35,  # Electric rail (grid carbon intensity)
    'comfort': 0.8,
    'capacity': 400,  # passengers per service
    'accessibility': 0.9,  # wheelchair accessible
    'frequency_per_hour': 2,
}
```

**Use cases:**
- Commuter rail (Edinburgh - Glasgow: 80 km, 50 min)
- Regional connections (Aberdeen - Inverness)
- Alternative to car for medium distance

#### Intercity Rail (High-Speed)
```python
'intercity_train': {
    'type': 'rail',
    'electrified': True,
    'range_km': 800,
    'avg_speed_kmh': 120,
    'cost_per_km': 0.15,
    'emissions_g_per_km': 25,  # Highly efficient electric
    'comfort': 0.85,
    'capacity': 600,
    'accessibility': 0.95,
    'frequency_per_hour': 1,
}
```

**Use cases:**
- Edinburgh - London (640 km, 4.5 hours)
- Major city connections
- Business travel alternative to air

#### Tram/Light Rail
```python
'tram': {
    'type': 'light_rail',
    'electrified': True,
    'range_km': 25,
    'avg_speed_kmh': 25,
    'cost_per_km': 0.08,
    'emissions_g_per_km': 30,
    'comfort': 0.75,
    'capacity': 200,
    'accessibility': 1.0,  # Level boarding
    'frequency_per_hour': 6,
}
```

**Use cases:**
- Edinburgh tram system
- Urban corridors (higher capacity than bus)
- Car-free city center access

### Maritime (Ferries & Coastal)

#### Ferry (Diesel)
```python
'ferry_diesel': {
    'type': 'maritime',
    'electrified': False,
    'range_km': 200,
    'avg_speed_kmh': 35,
    'cost_per_km': 0.25,
    'emissions_g_per_km': 120,  # Per passenger
    'comfort': 0.65,
    'capacity': 500,
    'weather_dependent': True,
}
```

**Use cases:**
- Island connections (Scottish Highlands & Islands)
- Coastal routes (alternative to long road journeys)
- Tourism

#### Ferry (Electric/Hybrid)
```python
'ferry_electric': {
    'type': 'maritime',
    'electrified': True,
    'range_km': 50,
    'avg_speed_kmh': 30,
    'cost_per_km': 0.20,
    'emissions_g_per_km': 40,  # Battery-electric or hybrid
    'comfort': 0.7,
    'capacity': 300,
    'weather_dependent': True,
}
```

**Use cases:**
- Short island hops
- Urban water transport (potential for Edinburgh-Leith)
- Zero-emission coastal corridors

### Aviation

#### Domestic Flight (Conventional)
```python
'flight_domestic': {
    'type': 'aviation',
    'electrified': False,
    'range_km': 1000,
    'avg_speed_kmh': 450,
    'cost_per_km': 0.20,
    'emissions_g_per_km': 250,  # High per passenger
    'comfort': 0.6,
    'capacity': 150,
    'min_distance_km': 100,  # Not viable for short trips
    'airport_access_time_min': 90,  # Check-in, security, boarding
}
```

**Use cases:**
- Edinburgh - London alternative (faster than train)
- Scottish island connections (Orkney, Shetland)
- International connections

#### Electric/Hybrid Aircraft (Future)
```python
'flight_electric': {
    'type': 'aviation',
    'electrified': True,
    'range_km': 500,
    'avg_speed_kmh': 350,
    'cost_per_km': 0.15,
    'emissions_g_per_km': 50,  # Battery or hydrogen
    'comfort': 0.65,
    'capacity': 50,  # Smaller aircraft
    'min_distance_km': 50,
    'airport_access_time_min': 60,  # Smaller airports
    'availability': 0.1,  # Limited availability (emerging tech)
}
```

**Use cases:**
- Regional air mobility (emerging market)
- Island connections (replace diesel flights)
- Business travel (Edinburgh - Aberdeen)

### Active & Micro-Mobility

#### E-Scooter
```python
'e_scooter': {
    'type': 'micro_mobility',
    'electrified': True,
    'range_km': 30,
    'avg_speed_kmh': 20,
    'cost_per_km': 0.25,  # Rental model
    'emissions_g_per_km': 0,
    'comfort': 0.4,  # Weather-dependent
    'accessibility': 0.3,  # Limited to able-bodied
    'weather_dependent': True,
}
```

**Use cases:**
- Last-mile connections
- Urban exploration
- Train station → city center

---

## 📖 New User & Job Stories

### Long-Distance Commuter
```yaml
long_distance_commuter:
  persona_type: professional
  description: Lives in Edinburgh, works in Glasgow (or vice versa)
  
  beliefs:
    - text: "Train is more productive than driving"
      confidence: 0.8
    - text: "Parking in city center is expensive and stressful"
      confidence: 0.9
  
  desires:
    time: 0.7
    cost: 0.5
    comfort: 0.8
    eco: 0.6
    productivity: 0.9  # Can work on train
  
  constraints:
    - "Must arrive by 9am"
    - "Prefers not to drive in rush hour"
```

### Island Resident
```yaml
island_resident:
  persona_type: rural
  description: Lives on Scottish island, occasional mainland trips
  
  beliefs:
    - text: "Ferry schedules dictate life"
      confidence: 1.0
    - text: "Weather can cancel ferries"
      confidence: 0.9
    - text: "Electric ferries would reduce costs"
      confidence: 0.7
  
  desires:
    time: 0.4  # Flexible, used to ferry delays
    cost: 0.8  # High ferry costs are burden
    reliability: 0.9
    eco: 0.7
  
  constraints:
    - "Must book ferry in advance"
    - "Weather-dependent travel"
```

### Business Traveler
```yaml
business_traveler:
  persona_type: executive
  description: Frequent intercity travel for meetings
  
  beliefs:
    - text: "Time is money"
      confidence: 1.0
    - text: "Flight fastest for Edinburgh-London"
      confidence: 0.8
    - text: "High-speed rail competitive for medium distance"
      confidence: 0.7
  
  desires:
    time: 0.95
    cost: 0.3  # Expense account
    comfort: 0.9
    eco: 0.4  # Lower priority
    productivity: 0.85
  
  constraints:
    - "Meeting times non-negotiable"
    - "Same-day return trips common"
```

### Accessibility User
```yaml
accessibility_user:
  persona_type: disabled
  description: Wheelchair user requiring accessible transport
  
  beliefs:
    - text: "Trams are most accessible public transport"
      confidence: 0.9
    - text: "Many buses lack proper accessibility"
      confidence: 0.7
    - text: "Active transport modes exclude me"
      confidence: 1.0
  
  desires:
    accessibility: 1.0
    comfort: 0.8
    reliability: 0.9
    time: 0.5
    cost: 0.6
  
  constraints:
    - "Requires level boarding or ramps"
    - "Cannot use bikes, scooters, or most micro-mobility"
```

### Tourist (Multi-Modal)
```yaml
tourist_visitor:
  persona_type: visitor
  description: Exploring Scotland via multiple transport modes
  
  beliefs:
    - text: "Scenic routes add to experience"
      confidence: 0.9
    - text: "Public transport is environmentally friendly"
      confidence: 0.8
    - text: "Trying local transport is part of travel"
      confidence: 0.9
  
  desires:
    eco: 0.8
    comfort: 0.6
    scenic: 0.95
    cost: 0.5  # Budget conscious but flexible
    time: 0.3  # Leisure travel
  
  constraints:
    - "No car available"
    - "Luggage limits bike/scooter use"
```

---

## 🎯 Job Stories for Multi-Modal Scenarios

### Intercity Business Trip
```yaml
intercity_business_trip:
  context: "When traveling to another city for same-day business meeting"
  goal: "I want fast, reliable transport that allows me to work en route"
  outcome: "So I arrive prepared and return home same day"
  
  job_type: business_travel
  
  time_window:
    start: "07:00"
    end: "09:00"
    flexibility: very_low
    return_trip: true
    return_by: "19:00"
  
  destination_type: city_center_office
  typical_distance_km: [80, 650]
  
  parameters:
    vehicle_required: false
    recurring: true
    urgency: high
    luggage_present: false
    work_while_traveling: true
  
  mode_preferences:
    preferred: ['intercity_train', 'flight_domestic']
    acceptable: ['local_train', 'car']
    avoid: ['bus', 'bike']
  
  desire_overrides:
    time: 0.95
    productivity: 0.9
```

### Island Ferry Commute
```yaml
island_ferry_commute:
  context: "When traveling from island home to mainland for work/services"
  goal: "I want reliable ferry connection despite weather"
  outcome: "So I can maintain work commitments and access services"
  
  job_type: island_travel
  
  time_window:
    start: "06:00"
    end: "10:00"
    flexibility: medium  # Must work around ferry schedule
  
  destination_type: mainland_town
  typical_distance_km: [10, 100]  # Ferry + onward travel
  
  parameters:
    vehicle_required: false
    recurring: true
    urgency: medium
    weather_dependent: true
    ferry_booking_required: true
  
  mode_preferences:
    required: ['ferry_diesel', 'ferry_electric', 'flight_domestic']
    onward_connection: ['bus', 'car', 'bike']
  
  constraints:
    - "Ferry schedule is fixed"
    - "Weather can cancel sailings"
    - "Vehicle booking may be required"
```

### Accessible City Journey
```yaml
accessible_city_journey:
  context: "When traveling around city as wheelchair user"
  goal: "I want guaranteed accessible transport"
  outcome: "So I can reach my destination independently and safely"
  
  job_type: accessible_travel
  
  time_window:
    start: "09:00"
    end: "17:00"
    flexibility: medium
  
  destination_type: urban
  typical_distance_km: [1, 15]
  
  parameters:
    vehicle_required: false
    recurring: true
    urgency: medium
    accessibility_required: true
  
  mode_preferences:
    preferred: ['tram', 'bus', 'car']  # Level boarding preferred
    acceptable: ['accessible_taxi']
    avoid: ['bike', 'walk', 'e_scooter', 'ferry']
  
  accessibility_requirements:
    level_boarding: true
    wheelchair_space: true
    audio_visual_announcements: true
```

### Tourist Scenic Journey
```yaml
tourist_scenic_route:
  context: "When exploring Scotland's landscapes via public transport"
  goal: "I want scenic, sustainable travel that's part of the experience"
  outcome: "So I enjoy the journey as much as the destination"
  
  job_type: tourism
  
  time_window:
    start: "09:00"
    end: "18:00"
    flexibility: very_high
  
  destination_type: scenic_attraction
  typical_distance_km: [20, 200]
  
  parameters:
    vehicle_required: false
    recurring: false
    urgency: low
    luggage_present: true
    scenic_preference: 0.95
  
  mode_preferences:
    preferred: ['local_train', 'ferry_diesel', 'ferry_electric', 'bus']
    acceptable: ['intercity_train', 'e_scooter']
    avoid: ['flight_domestic', 'car']
  
  constraints:
    - "No rental car booked"
    - "Prefer eco-friendly options"
    - "Window seat desired"
```

### Multi-Modal Commute
```yaml
multi_modal_commute:
  context: "When combining multiple transport modes for daily commute"
  goal: "I want seamless connection between transport modes"
  outcome: "So I reach work efficiently using sustainable options"
  
  job_type: commute
  
  stages:
    - stage_id: 1
      mode: ['bike', 'e_scooter', 'walk']
      destination: train_station
      typical_distance_km: [2, 5]
    
    - stage_id: 2
      mode: ['local_train', 'tram']
      destination: city_center
      typical_distance_km: [15, 40]
    
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
    connection_time_critical: true
  
  constraints:
    - "Cannot miss train connection"
    - "Bike parking at station required"
    - "Weather affects first/last mile choice"
```

---

## 🔄 Multi-Modal Integration Points for Phase 5

### 1. System Dynamics Feedback Loops

**Grid Stress Cascade:**
```
EV Adoption ↑ → Grid Stress ↑ → Charging Costs ↑ → 
Rail Adoption ↑ (electrified) → Grid Stress ↑ (trains use electricity) →
Policy: Add renewable capacity
```

**Congestion Cascade:**
```
Car Usage ↑ → Congestion ↑ → Travel Time ↑ →
Modal Shift to Rail/Tram → Reduced Road Emissions →
Remaining Drivers: Faster Journeys → Slight Return to Cars
(Equilibrium)
```

### 2. Environmental Impact Modeling

**Air Quality Zones:**
```python
class AirQualityZone:
    def __init__(self, location, radius_km):
        self.pm25_level = 0.0  # μg/m³
        self.no2_level = 0.0   # μg/m³
        self.sources = []  # List of emission sources
    
    def update_from_transport(self, mode_counts, emissions_factors):
        """Calculate transport contribution to air pollution"""
        for mode, count in mode_counts.items():
            self.pm25_level += count * emissions_factors[mode]['pm25']
            self.no2_level += count * emissions_factors[mode]['no2']
    
    def exceeds_limits(self) -> bool:
        """Check if WHO air quality limits exceeded"""
        return self.pm25_level > 10.0 or self.no2_level > 40.0
```

**Ecological Impact:**
```python
class EcologicalImpactZone:
    def __init__(self, habitat_type):
        self.noise_level_db = 0.0
        self.habitat_fragmentation = 0.0
        self.wildlife_corridors_blocked = []
    
    def assess_transport_impact(self, mode_volumes):
        """Assess impact on wildlife and ecosystems"""
        # Road noise impacts birds, mammals
        # Rail corridors fragment habitats
        # Air traffic disturbs migration routes
        pass
```

### 3. Infrastructure Planning Algorithms

**Optimal Charger Placement:**
```python
def optimize_charger_placement(
    demand_heatmap: np.ndarray,
    grid_capacity_map: np.ndarray,
    budget: float,
    target_coverage: float = 0.95
) -> List[ChargingStation]:
    """
    Use spatial optimization to place chargers where:
    1. EV demand is high
    2. Grid capacity exists
    3. Coverage gaps are filled
    4. Budget constraints met
    """
    # Gravity model + grid constraints + coverage optimization
    pass
```

**Transport Network Optimization:**
```python
def suggest_new_rail_lines(
    od_demand_matrix: pd.DataFrame,
    congestion_zones: List[Zone],
    carbon_budget: float
) -> List[RailProposal]:
    """
    Identify where new rail connections would:
    1. Reduce car journeys most
    2. Alleviate congestion
    3. Achieve carbon targets
    """
    pass
```

---

## 📊 Distance Suitability Matrix

| Mode | Optimal Range (km) | Max Range | Edinburgh-Glasgow | Edinburgh-London | Island Hops |
|------|-------------------|-----------|-------------------|------------------|-------------|
| Walk | 0-3 | 5 | ❌ | ❌ | ✓ (within island) |
| Bike | 2-15 | 20 | ❌ | ❌ | ✓ |
| E-Scooter | 1-10 | 30 | ❌ | ❌ | ✓ |
| Cargo Bike | 1-8 | 10 | ❌ | ❌ | ✓ |
| Bus | 3-40 | 100 | ✓ | ❌ | ✓ |
| Tram | 1-20 | 25 | ❌ | ❌ | ❌ |
| Car | 5-200 | 500 | ✓ | ✓ | ✓ (with ferry) |
| EV | 5-150 | 350 | ✓ | ✓ | ✓ |
| Van (electric) | 10-100 | 200 | ✓ | ❌ | ✓ |
| Truck (electric) | 20-150 | 250 | ✓ | ❌ | ✓ |
| HGV (electric) | 50-200 | 300 | ✓ | ❌ | ❌ |
| HGV (hydrogen) | 100-500 | 600 | ✓ | ✓ | ❌ |
| **Local Train** | 10-100 | 150 | ✓ | ❌ | ❌ |
| **Intercity Train** | 80-600 | 800 | ✓ | ✓ | ❌ |
| **Ferry (diesel)** | 5-150 | 200 | ❌ | ❌ | ✓ |
| **Ferry (electric)** | 3-40 | 50 | ❌ | ❌ | ✓ |
| **Flight (domestic)** | 100-800 | 1000 | ✓ | ✓ | ✓ |
| **Flight (electric)** | 50-400 | 500 | ✓ | ✓ (future) | ✓ |

---

## 🎯 Implementation Priority

### Tier 1: High Impact, Easy (Do in Phase 4.5G)
1. **Local Train** - Critical for Edinburgh-Glasgow, high ridership
2. **Tram** - Edinburgh has existing system, easy to model
3. **E-Scooter** - Last-mile solution, growing adoption
4. **Ferry (diesel)** - Essential for Scottish islands

### Tier 2: High Impact, Moderate (Phase 4.5G or early Phase 5)
5. **Intercity Train** - Needed for long-distance scenarios
6. **Ferry (electric)** - Key decarbonization target
7. **Flight (domestic)** - Major emissions source, important comparison

### Tier 3: Future/Emerging (Phase 5+)
8. **Flight (electric)** - Emerging technology, future scenarios
9. **Hydrogen rail** - Alternative to electric rail
10. **Autonomous shuttles** - Future urban mobility

---

## 🧪 Testing Scenarios (Post-Implementation)

### Scenario 1: "Central Belt Rail Enhancement"
- Increase train frequency Edinburgh-Glasgow 2x
- Reduce costs by 20%
- Expected: 30% shift from car to rail

### Scenario 2: "Island Electrification"
- Replace diesel ferries with electric (subsidy 50%)
- Add EV chargers at ferry terminals
- Expected: 60% emissions reduction on island routes

### Scenario 3: "Urban Tram Expansion"
- Add tram lines in Edinburgh/Glasgow
- Integrate with bike-share for last mile
- Expected: 25% reduction in urban car trips

### Scenario 4: "Flight Replacement (Rail)"
- Carbon tax on domestic flights (£50/ton)
- High-speed rail subsidy 30%
- Expected: 40% shift from air to rail (under 500km)

---

## 💡 Research Questions Enabled

With multi-modal expansion, RTD_SIM can answer:

1. **Modal Shift Tipping Points:** At what congestion level do commuters switch to rail?
2. **Island Decarbonization:** What combination of electric ferries + EVs achieves net zero?
3. **Grid Capacity Planning:** How much renewable capacity needed for electrified transport?
4. **Accessibility Equity:** Do e-mobility options exclude disabled users?
5. **Tourism Sustainability:** Can Scotland achieve zero-emission tourism?
6. **Freight Consolidation:** Do multi-modal freight hubs reduce HGV kilometers?
7. **Air Quality Improvements:** Which policy mix achieves WHO air quality targets?
8. **Cost-Benefit Analysis:** What's the ROI of tram vs. bus rapid transit?

---

## 📅 Recommended Timeline

**Phase 4.5G (8 hours):**
- Add 8 new modes (rail, tram, ferry, air)
- Create 10 new user stories
- Create 10 new job stories  
- Update BDI planner for multi-modal
- Add to visualization

**Phase 5.0 (2-3 weeks):**
- System dynamics (feedback loops)
- Environmental impact modeling
- Infrastructure optimization algorithms
- Long-term carbon tracking
- Policy effectiveness metrics

**Phase 5.1+ (Future):**
- Real-time grid integration
- Machine learning for demand prediction
- Autonomous vehicle simulation
- Hyperloop/future tech scenarios
