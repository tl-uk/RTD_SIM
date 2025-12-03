# RTD_SIM Phase 2.2: Route Enhancement

## 🎯 Overview

**Status**: Starting Phase 2.2  
**Phase 2.1**: ✅ Complete (OSM integration, elevation data)  
**Current Goal**: Advanced routing capabilities and dynamic factors

## 📋 Phase 2.2 Features

### 1. Multi-Modal Routing 🚌🚶
**Objective**: Enable agents to combine transport modes in a single journey

**Features**:
- Walk + Bus combinations
- Park & Ride (drive to hub, then bus)
- First/Last mile connections
- Transfer points and waiting times
- Mode-specific access/egress

**Implementation**:
- `compute_multimodal_route()` in SpatialEnvironment
- Transfer node detection
- Time penalties for mode switches
- Route segment labeling by mode

**Complexity**: High (requires graph modification or multi-stage routing)

---

### 2. Route Alternatives 🔀
**Objective**: Provide multiple route options per origin-destination pair

**Features**:
- **Shortest route**: Minimize distance
- **Fastest route**: Minimize travel time
- **Safest route**: Minimize risk (avoid high-speed roads for bikes)
- **Greenest route**: Minimize emissions
- **Scenic route**: Prefer parks/paths (quality-of-life)

**Implementation**:
- Multiple weight functions for NetworkX shortest_path
- `compute_route_alternatives()` method
- Route scoring and ranking
- Agent choice model to select preferred route

**Complexity**: Medium (mostly different weight functions)

---

### 3. Dynamic Congestion 🚗📈
**Objective**: Model traffic congestion that affects travel times

**Features**:
- Edge-level traffic counters
- Speed reduction based on vehicle density
- Dynamic travel time updates
- Congestion spillback effects
- Time-of-day patterns

**Implementation**:
- `TrafficManager` class
- Edge traffic counters (vehicles per edge per timestep)
- Congestion-adjusted speed calculations
- Integration with route computation

**Complexity**: High (requires state management and performance optimization)

---

### 4. Public Transport Schedules 🚌⏰
**Objective**: Realistic bus schedules with frequency and headways

**Features**:
- Bus line definitions (routes + stops)
- Service frequency by time of day
- Waiting time at stops
- Transfer penalties
- Bus capacity limits (future)

**Implementation**:
- `TransitSchedule` class
- Bus stop nodes in graph
- Schedule-aware routing for bus mode
- Waiting time calculation

**Complexity**: High (new data structures and routing logic)

---

## 🎯 Recommended Implementation Order

### **Option A: Incremental (Low Risk)**
Start with features that build on Phase 2.1 without major architectural changes:

1. **Route Alternatives** (1-2 days)
   - Easy wins with different weight functions
   - Immediately useful for agent choice modeling
   - Foundation for Phase 3 logit choice

2. **Dynamic Congestion** (2-3 days)
   - Critical for realistic simulation
   - Moderate complexity
   - Can start simple and enhance later

3. **Public Transport Schedules** (3-4 days)
   - Complex but isolated subsystem
   - Can be developed independently
   - Essential for multi-modal routing

4. **Multi-Modal Routing** (3-4 days)
   - Highest complexity
   - Depends on transit schedules
   - Save for last

**Total Time**: 9-13 days

---

### **Option B: High-Impact First (Aggressive)**
Start with the most impactful features for realistic simulation:

1. **Dynamic Congestion** (2-3 days)
   - Biggest realism boost
   - Affects all agents immediately
   - Foundation for interesting emergent behavior

2. **Route Alternatives** (1-2 days)
   - Quick addition
   - Enables agent diversity
   - Pairs well with congestion

3. **Public Transport Schedules** (3-4 days)
   - Makes bus mode realistic
   - Required for multi-modal

4. **Multi-Modal Routing** (3-4 days)
   - Capstone feature
   - Unlocks new agent behaviors

**Total Time**: 9-13 days

---

### **Option C: MVP Focus (Fastest)**
Minimum viable implementation to unlock Phase 3:

1. **Route Alternatives** (1 day MVP)
   - Just shortest/fastest distinction
   - Skip safest/greenest/scenic for now

2. **Simple Congestion** (1 day MVP)
   - Basic speed reduction on busy edges
   - No spillback or time-of-day patterns

3. **Skip Multi-Modal and Transit for now**
   - Can be added later as Phase 2.3 or 2.4
   - Not essential for Phase 3 logit choice model

**Total Time**: 2 days → Move to Phase 3 faster

---

## 🔨 Detailed Implementation: Route Alternatives (Start Here)

Since this is the easiest and most immediately useful, let's start here.

### Architecture

```python
class RouteAlternative:
    """Represents one route option."""
    def __init__(self, route, mode, variant):
        self.route = route              # List[(lon, lat)]
        self.mode = mode                # 'walk', 'bike', 'car', etc.
        self.variant = variant          # 'shortest', 'fastest', 'safest', etc.
        self.metrics = {}               # Distance, time, cost, emissions, etc.
    
    def compute_metrics(self, env):
        """Calculate all metrics for this route."""
        self.metrics['distance'] = env._distance(self.route)
        self.metrics['time'] = env.estimate_travel_time(self.route, self.mode)
        self.metrics['cost'] = env.estimate_monetary_cost(self.route, self.mode)
        self.metrics['emissions'] = env.estimate_emissions_with_elevation(self.route, self.mode)
        self.metrics['comfort'] = env.estimate_comfort(self.route, self.mode)
        self.metrics['risk'] = env.estimate_risk(self.route, self.mode)

class SpatialEnvironment:
    
    def compute_route_alternatives(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str,
        variants: List[str] = None
    ) -> List[RouteAlternative]:
        """
        Compute multiple route options for the same origin-destination pair.
        
        Args:
            agent_id: Agent identifier
            origin: Starting point (lon, lat)
            dest: Destination (lon, lat)
            mode: Transport mode
            variants: Which route types to compute (default: ['shortest', 'fastest'])
        
        Returns:
            List of RouteAlternative objects, sorted by preference
        """
        variants = variants or ['shortest', 'fastest']
        alternatives = []
        
        for variant in variants:
            route = self._compute_route_variant(origin, dest, mode, variant)
            if route:
                alt = RouteAlternative(route, mode, variant)
                alt.compute_metrics(self)
                alternatives.append(alt)
        
        return alternatives
    
    def _compute_route_variant(
        self,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str,
        variant: str
    ) -> List[Tuple[float, float]]:
        """Compute a specific route variant."""
        
        network_type = self.mode_network_types.get(mode, 'all')
        graph = self.mode_graphs.get(network_type, self.G)
        
        if graph is None:
            return None
        
        try:
            orig_node = self._get_nearest_node(origin, network_type)
            dest_node = self._get_nearest_node(dest, network_type)
            
            # Choose weight function based on variant
            if variant == 'shortest':
                weight = 'length'
            elif variant == 'fastest':
                weight = self._add_time_weights(graph, mode)
            elif variant == 'safest':
                weight = self._add_safety_weights(graph, mode)
            elif variant == 'greenest':
                weight = self._add_emission_weights(graph, mode)
            elif variant == 'scenic':
                weight = self._add_scenic_weights(graph, mode)
            else:
                weight = 'length'
            
            route_nodes = nx.shortest_path(graph, orig_node, dest_node, weight=weight)
            coords = [(float(graph.nodes[n]['x']), float(graph.nodes[n]['y'])) 
                     for n in route_nodes]
            
            return coords
            
        except Exception as e:
            logger.warning(f"Route variant {variant} failed: {e}")
            return None
    
    def _add_time_weights(self, graph, mode):
        """Add travel time as edge weights."""
        speed_m_per_s = self.get_speed_km_min(mode) * 1000 / 60
        
        for u, v, data in graph.edges(data=True):
            length = data.get('length', 0)
            data['time_weight'] = length / speed_m_per_s if speed_m_per_s > 0 else 1e9
        
        return 'time_weight'
    
    def _add_safety_weights(self, graph, mode):
        """Add safety-based weights (prefer low-speed roads for bikes/walk)."""
        for u, v, data in graph.edges(data=True):
            length = data.get('length', 0)
            
            # OSM maxspeed or highway type
            maxspeed = data.get('maxspeed', 50)
            highway_type = data.get('highway', 'residential')
            
            # Higher speeds = higher risk for vulnerable modes
            if mode in ['walk', 'bike']:
                if highway_type in ['motorway', 'motorway_link', 'trunk']:
                    risk_factor = 10.0  # Avoid highways
                elif highway_type in ['primary', 'secondary']:
                    risk_factor = 2.0   # Prefer not to use
                else:
                    risk_factor = 1.0   # Residential/tertiary OK
            else:
                risk_factor = 1.0
            
            data['safety_weight'] = length * risk_factor
        
        return 'safety_weight'
    
    def _add_emission_weights(self, graph, mode):
        """Add emission-based weights (prefer flat routes)."""
        for u, v, data in graph.edges(data=True):
            length = data.get('length', 0)
            
            # Get elevation change
            if self.has_elevation:
                u_elev = graph.nodes[u].get('elevation', 0)
                v_elev = graph.nodes[v].get('elevation', 0)
                elev_change = abs(v_elev - u_elev)
                
                # Penalize elevation changes (uphill costs energy)
                elev_penalty = 1.0 + (elev_change / 100.0)  # +1% per meter elevation change
            else:
                elev_penalty = 1.0
            
            data['emission_weight'] = length * elev_penalty
        
        return 'emission_weight'
    
    def _add_scenic_weights(self, graph, mode):
        """Add scenic/quality weights (prefer green spaces)."""
        for u, v, data in graph.edges(data=True):
            length = data.get('length', 0)
            
            # OSM tags for parks, paths, etc.
            highway_type = data.get('highway', 'residential')
            surface = data.get('surface', 'asphalt')
            
            # Prefer paths, tracks, green spaces
            if highway_type in ['path', 'footway', 'cycleway', 'track']:
                scenic_factor = 0.5  # Prefer these
            elif highway_type in ['residential', 'living_street']:
                scenic_factor = 0.8  # OK
            else:
                scenic_factor = 1.0  # Neutral
            
            data['scenic_weight'] = length * scenic_factor
        
        return 'scenic_weight'
```

### Integration with BDI Planner

```python
# In bdi_planner.py

def generate_route_options(self, origin, dest, mode):
    """Generate multiple route options for agent to consider."""
    alternatives = self.env.compute_route_alternatives(
        self.agent_id,
        origin,
        dest,
        mode,
        variants=['shortest', 'fastest', 'safest']
    )
    
    # Rank alternatives based on agent desires
    scored = []
    for alt in alternatives:
        score = self._score_route_alternative(alt)
        scored.append((score, alt))
    
    scored.sort(reverse=True)  # Highest score first
    return [alt for score, alt in scored]

def _score_route_alternative(self, alt: RouteAlternative) -> float:
    """Score a route based on agent desires."""
    score = 0.0
    
    # Weight by desires
    if 'minimize_time' in self.desires:
        score -= alt.metrics['time'] * self.desires['minimize_time']
    
    if 'minimize_cost' in self.desires:
        score -= alt.metrics['cost'] * self.desires['minimize_cost']
    
    if 'minimize_emissions' in self.desires:
        score -= alt.metrics['emissions'] * self.desires['minimize_emissions']
    
    if 'maximize_comfort' in self.desires:
        score += alt.metrics['comfort'] * self.desires['maximize_comfort']
    
    if 'minimize_risk' in self.desires:
        score -= alt.metrics['risk'] * self.desires['minimize_risk']
    
    return score
```

---

## 📊 Testing Strategy

### Unit Tests
```python
def test_route_alternatives():
    env = SpatialEnvironment()
    env.load_osm_graph(place="Edinburgh, Scotland")
    
    origin = (-3.2008, 55.9486)
    dest = (-3.1730, 55.9520)
    
    alternatives = env.compute_route_alternatives(
        "test_agent",
        origin,
        dest,
        "bike",
        variants=['shortest', 'fastest', 'safest']
    )
    
    assert len(alternatives) >= 1
    assert alternatives[0].variant in ['shortest', 'fastest', 'safest']
    assert 'distance' in alternatives[0].metrics
    assert 'time' in alternatives[0].metrics
    
    # Shortest should have minimum distance
    shortest = [a for a in alternatives if a.variant == 'shortest'][0]
    for alt in alternatives:
        assert shortest.metrics['distance'] <= alt.metrics['distance']
```

### Integration Test
```python
def test_agent_chooses_route():
    env = SpatialEnvironment()
    env.load_osm_graph(place="Edinburgh, Scotland")
    
    agent = BDIAgent("test_agent", desires={
        'minimize_time': 0.8,
        'minimize_risk': 0.3
    })
    
    origin, dest = env.get_random_origin_dest()
    alternatives = env.compute_route_alternatives("test_agent", origin, dest, "bike")
    
    chosen = agent.choose_route(alternatives)
    assert chosen is not None
    assert chosen.variant in ['shortest', 'fastest', 'safest']
```

---

## 🎯 Success Criteria for Phase 2.2

- [ ] Route alternatives working (shortest/fastest/safest)
- [ ] Weight functions correctly implement routing logic
- [ ] Agent can choose between alternatives
- [ ] Metrics accurately computed for each alternative
- [ ] Test suite passes
- [ ] Streamlit UI shows route options
- [ ] Documentation updated

---

## 🚀 Next Steps

**Please confirm**:
1. Do you want to start with **Route Alternatives** (easiest, quickest)?
2. Or prefer **Dynamic Congestion** (more impactful but harder)?
3. Or the **MVP approach** (2 days → Phase 3)?

I'll create the implementation artifacts once you choose the direction!
