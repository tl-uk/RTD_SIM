# SpatialEnvironment Refactoring Plan

## 🚨 Current Problem

`spatial_environment.py` has become a **monolith** with multiple responsibilities:

### Current Responsibilities (SRP Violations):
1. **Graph Loading** - OSM download, caching, mode-specific networks
2. **Elevation Management** - Adding elevation data, caching
3. **Routing** - Basic routing, route alternatives, weight functions
4. **Movement** - Agent movement along routes, densification
5. **Metrics** - Distance, time, cost, emissions, comfort, risk calculations
6. **Utilities** - Haversine, coordinate validation, nearest nodes

**Current Size**: ~650 lines (estimate)  
**Phase 2.2b would add**: ~300 more lines (congestion tracking, speed adjustments)  
**Result**: 950+ line monolith ❌

---

## ✅ Proposed Architecture

Apply Single Responsibility Principle: "A class should have one, and only one, reason to change"

### New Structure:

```
simulation/
├── spatial/
│   ├── __init__.py
│   ├── graph_manager.py          # Graph loading & caching
│   ├── elevation_manager.py       # Elevation data (wraps ElevationProvider)
│   ├── router.py                  # All routing logic
│   ├── movement_engine.py         # Agent movement mechanics
│   ├── metrics_calculator.py      # Distance, time, cost, emissions
│   └── coordinate_utils.py        # Haversine, validation utilities
├── spatial_environment.py         # Orchestrator (thin facade)
├── route_alternative.py           # Data class (already separate ✓)
└── elevation_provider.py          # Already separate ✓
```

---

## 📋 Refactored Classes

### 1. `GraphManager` - Graph Loading & Caching
**Responsibility**: Manage OSM graph lifecycle

```python
class GraphManager:
    """Handles OSM graph loading, caching, and management."""
    
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.graphs: Dict[str, Any] = {}  # mode_type -> graph
        self.primary_graph = None
    
    def load_graph(self, place=None, bbox=None, network_type='all', use_cache=True)
    def load_mode_specific_graphs(self, place=None, bbox=None, modes=None, use_cache=True)
    def get_graph(self, mode: str) -> Optional[Any]
    def clear_cache(self)
    def get_stats(self) -> dict
```

**Lines**: ~200

---

### 2. `Router` - Routing Logic
**Responsibility**: Compute routes and alternatives

```python
class Router:
    """Handles route computation with multiple variants."""
    
    def __init__(self, graph_manager: GraphManager):
        self.graph_manager = graph_manager
        self._node_cache: Dict[str, Dict] = {}
    
    def compute_route(self, origin, dest, mode) -> List[Tuple[float, float]]
    def compute_alternatives(self, origin, dest, mode, variants) -> List[RouteAlternative]
    
    # Private methods
    def _compute_route_variant(self, origin, dest, mode, variant)
    def _get_weight_attribute(self, graph, mode, variant) -> str
    def _add_time_weights(self, graph, mode) -> str
    def _add_safety_weights(self, graph, mode) -> str
    def _add_emission_weights(self, graph, mode) -> str
    def _add_scenic_weights(self, graph, mode) -> str
    def _get_nearest_node(self, coord, network_type) -> Optional[int]
```

**Lines**: ~250

---

### 3. `MetricsCalculator` - Performance Metrics
**Responsibility**: Calculate route/trip metrics

```python
class MetricsCalculator:
    """Calculates distance, time, cost, emissions, comfort, risk."""
    
    def __init__(self, speeds_km_min: dict):
        self.speeds_km_min = speeds_km_min
    
    def calculate_distance(self, route: List[Tuple]) -> float
    def calculate_travel_time(self, route: List[Tuple], mode: str) -> float
    def calculate_cost(self, route: List[Tuple], mode: str) -> float
    def calculate_emissions(self, route: List[Tuple], mode: str) -> float
    def calculate_emissions_with_elevation(self, route, mode, graph_manager) -> float
    def calculate_comfort(self, route: List[Tuple], mode: str) -> float
    def calculate_risk(self, route: List[Tuple], mode: str) -> float
```

**Lines**: ~150

---

### 4. `MovementEngine` - Agent Movement
**Responsibility**: Handle agent movement along routes

```python
class MovementEngine:
    """Manages agent movement mechanics along routes."""
    
    def __init__(self, metrics_calculator: MetricsCalculator):
        self.metrics = metrics_calculator
    
    def advance_along_route(self, route, current_index, offset_km, mode, step_minutes)
    def densify_route(self, route, step_meters=20.0) -> List[Tuple[float, float]]
```

**Lines**: ~50

---

### 5. `ElevationManager` - Elevation Orchestration
**Responsibility**: Simplify elevation data integration

```python
class ElevationManager:
    """Manages elevation data for graphs (wrapper around ElevationProvider)."""
    
    def __init__(self, cache_dir: Path):
        self.provider = ElevationProvider(cache_dir)
        self.has_elevation = False
    
    def add_to_graph(self, graph, method='opentopo', **kwargs) -> bool
    def get_elevation_for_route(self, route, graph) -> List[Optional[float]]
```

**Lines**: ~50

---

### 6. `SpatialEnvironment` - Orchestrator (Facade)
**Responsibility**: Coordinate all spatial subsystems

```python
class SpatialEnvironment:
    """
    Main spatial environment - orchestrates all spatial subsystems.
    Thin facade providing backward-compatible API.
    """
    
    def __init__(self, step_minutes=1.0, cache_dir=None):
        self.step_minutes = step_minutes
        
        # Subsystems
        self.graph_manager = GraphManager(cache_dir)
        self.router = Router(self.graph_manager)
        self.metrics = MetricsCalculator(speeds_km_min={...})
        self.movement = MovementEngine(self.metrics)
        self.elevation = ElevationManager(cache_dir)
    
    # Delegate to subsystems
    def load_osm_graph(self, ...):
        return self.graph_manager.load_graph(...)
    
    def compute_route(self, ...):
        return self.router.compute_route(...)
    
    def compute_route_alternatives(self, ...):
        return self.router.compute_alternatives(...)
    
    def estimate_emissions(self, ...):
        return self.metrics.calculate_emissions(...)
    
    # ... etc
```

**Lines**: ~100 (mostly delegation)

---

## 📊 Before vs After

### Before (Current):
```
spatial_environment.py: ~650 lines
├── Graph loading (150 lines)
├── Elevation (50 lines)
├── Routing (250 lines)
├── Metrics (100 lines)
├── Movement (50 lines)
└── Utils (50 lines)
```

**Problems**:
- Hard to test individual features
- Changes to routing affect graph loading
- 650+ lines in one file
- Will grow to 950+ with congestion

### After (Refactored):
```
spatial/
├── graph_manager.py: 200 lines
├── router.py: 250 lines
├── metrics_calculator.py: 150 lines
├── movement_engine.py: 50 lines
├── elevation_manager.py: 50 lines
├── coordinate_utils.py: 50 lines
└── spatial_environment.py: 100 lines (facade)
```

**Benefits**:
- Each class <300 lines
- Clear separation of concerns
- Easy to test in isolation
- Easy to extend (add congestion to router, not environment)
- Backward compatible (same API)

---

## 🎯 Migration Strategy

### Phase 1: Extract Without Breaking (Low Risk)
**Time**: 1-2 hours

1. Create `simulation/spatial/` directory
2. Extract `coordinate_utils.py` (pure functions, no dependencies)
3. Extract `metrics_calculator.py` (only depends on coordinate_utils)
4. Run tests - should still pass ✓

### Phase 2: Extract Core Components
**Time**: 2-3 hours

5. Extract `graph_manager.py` (contains graph loading logic)
6. Extract `router.py` (depends on graph_manager)
7. Update `spatial_environment.py` to delegate
8. Run tests - should still pass ✓

### Phase 3: Extract Remaining
**Time**: 1 hour

9. Extract `movement_engine.py`
10. Extract `elevation_manager.py`
11. Final cleanup
12. Run all tests ✓

**Total Time**: 4-6 hours

---

## 🔬 Testing Strategy

### Unit Tests (New)
```python
# test_graph_manager.py
def test_load_graph()
def test_cache_performance()

# test_router.py
def test_compute_route()
def test_route_alternatives()
def test_weight_functions()

# test_metrics_calculator.py
def test_distance_calculation()
def test_emissions_with_elevation()
```

### Integration Tests (Existing)
```python
# test_phase2_routing.py - should still pass
# test_phase2.2_route_alternatives.py - should still pass
```

---

## 🚀 Benefits for Phase 2.2b (Congestion)

With refactored architecture, adding congestion becomes easy:

### Option A: Add to Router
```python
# In router.py
class Router:
    def __init__(self, graph_manager, congestion_manager=None):
        self.congestion = congestion_manager
    
    def _add_time_weights(self, graph, mode):
        for u, v, key, data in graph.edges(...):
            base_time = data['length'] / speed
            
            # Apply congestion if available
            if self.congestion:
                congestion_factor = self.congestion.get_congestion_factor(u, v)
                data['time_weight'] = base_time * congestion_factor
            else:
                data['time_weight'] = base_time
```

### Option B: Separate CongestionManager
```python
# simulation/spatial/congestion_manager.py
class CongestionManager:
    """Tracks and manages traffic congestion."""
    
    def __init__(self, graph_manager):
        self.edge_traffic = defaultdict(int)  # (u,v) -> vehicle count
        self.graph_manager = graph_manager
    
    def add_agent_to_edge(self, u, v):
        self.edge_traffic[(u, v)] += 1
    
    def get_congestion_factor(self, u, v) -> float:
        count = self.edge_traffic.get((u, v), 0)
        # Simple congestion model: +10% travel time per additional vehicle
        return 1.0 + (count * 0.1)
```

**New code**: ~200 lines in separate file  
**Changes to existing files**: Minimal (just dependency injection)

---

## 🤔 Decision Point

**Do you want to refactor now (before Phase 2.2b)?**

### Option A: Refactor Now ⭐ Recommended
- **Time**: 4-6 hours
- **Benefit**: Clean foundation for Phase 2.2b and beyond
- **Risk**: Low (tests verify nothing breaks)
- **Long-term**: Much easier to maintain

### Option B: Continue Without Refactoring
- **Time**: 0 hours now, but technical debt accumulates
- **Phase 2.2b**: Add 300 lines to monolith (950 total)
- **Future**: Will need to refactor eventually (harder with more code)
- **Risk**: High (harder to test, harder to understand)

### Option C: Minimal Refactoring
- **Time**: 1-2 hours
- **Extract**: Just routing logic to separate file
- **Keep**: Everything else as-is
- **Compromise**: Prevents worst of monolith

---

## 💡 My Recommendation

**Refactor now (Option A)** because:

1. Tests pass now - you have a safety net
2. Preventing over-architecture is important, but 650+ lines in one class is a clear violation
3. Phase 2.2b will be **much easier** with clean architecture
4. Following SRP upfront is a daunting task, but efforts pay off as project grows
5. You're adding features (Phases 2.3, 3, 4) - now is the time

**What do you think?** Should we refactor before Phase 2.2b?
