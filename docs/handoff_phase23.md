# RTD_SIM Phase 2.3 Development Context

## 📋 Project Overview

**Project Name:** RTD_SIM (Real-Time Decarbonization Simulator)  
**Current Phase:** Ready to Start Phase 2.3 - Advanced Visualization  
**Tech Stack:** Python 3.13, OSMnx, NetworkX, Streamlit, Folium (current), deck.gl (planned)  
**Platform:** macOS (Apple Silicon), VS Code  
**Environment:** Virtual environment (venv)

---

## ✅ Completed Phases

### Phase 1: Core BDI Architecture ✅ (Complete)
- BDI (Belief-Desire-Intention) agent architecture
- Event bus for pub/sub communication
- Basic simulation controller
- Agent movement, emissions tracking
- CSV export, basic Streamlit UI

**Key Files:**
- `agent/cognitive_abm.py` - BDI agents
- `agent/bdi_planner.py` - Route planning with desires
- `simulation/controller.py` - Simulation orchestration
- `simulation/event_bus.py` - Event system
- `main_phase1.py` - Clean baseline (no OSM)

---

### Phase 2.1: OSM Integration & Elevation ✅ (Complete)
- Real street networks via OpenStreetMap
- Mode-specific networks (walk/bike/drive)
- Graph caching (22.9x speedup)
- OpenTopoData elevation integration (free API)
- Elevation-aware energy consumption

**Test Results:** 6/6 tests passing  
**Performance:** <2s cached graph loading, 18-20s first download

---

### Phase 2.2: Route Alternatives ✅ (Complete)
- 5 route variants:
  - **Shortest**: Minimum distance
  - **Fastest**: Minimum time
  - **Safest**: Avoids high-speed roads (bikes/pedestrians)
  - **Greenest**: Minimizes emissions (prefers flat terrain)
  - **Scenic**: Prefers paths, parks, quiet streets
- Route scoring and ranking
- Pareto-optimal filtering
- Full metrics per route (distance, time, cost, emissions, comfort, risk, elevation profile)

**Test Results:** 6/6 tests passing

---

### Phase 2.2b: Dynamic Congestion ✅ (Complete)
- Real-time traffic tracking on network edges
- 3 congestion models: Linear, BPR, Exponential
- Time-of-day patterns (rush hour: 2x worse congestion)
- Road capacity by highway type
- Congestion-aware routing (fastest routes avoid traffic)
- Statistics and heatmaps

**Test Results:** 6/6 tests passing  
**Performance Overhead:** Only 12.2% with congestion enabled

---

### Phase 2.x: Architecture Refactoring ✅ (Complete)
Successfully refactored 650-line monolith into clean modular architecture:

```
simulation/
├── spatial/
│   ├── __init__.py
│   ├── coordinate_utils.py (150 lines) - Pure utility functions
│   ├── metrics_calculator.py (200 lines) - Performance metrics
│   ├── graph_manager.py (250 lines) - Graph loading & caching
│   ├── router.py (250 lines) - Routing logic
│   └── congestion_manager.py (400 lines) - Traffic congestion
├── spatial_environment.py (120 lines) - Thin facade
├── elevation_provider.py (300 lines) - OpenTopoData integration
└── route_alternative.py (150 lines) - Route data class
```

**Benefits:**
- Each file has single responsibility
- Easy to test in isolation
- Easy to extend (proved with congestion addition)
- 100% backward compatible

---

## 📂 Current File Structure

```
RTD_SIM/
├── agent/
│   ├── cognitive_abm.py           # BDI agents
│   └── bdi_planner.py             # Route planning
├── simulation/
│   ├── spatial/
│   │   ├── __init__.py
│   │   ├── coordinate_utils.py
│   │   ├── metrics_calculator.py
│   │   ├── graph_manager.py
│   │   ├── router.py
│   │   └── congestion_manager.py
│   ├── spatial_environment.py     # Main facade
│   ├── elevation_provider.py      # Elevation data
│   ├── route_alternative.py       # Route data class
│   ├── controller.py              # Simulation controller
│   ├── event_bus.py               # Event system
│   └── data_adapter.py            # Data export
├── ui/
│   ├── main_ui.py                 # Tkinter UI (not actively used)
│   └── streamlit_app.py           # Current Streamlit UI (Phase 2.1)
├── visualiser/                    # Empty - Phase 2.3 target
├── config/                        # Empty
├── main.py                        # CLI entry point
├── main_phase1.py                 # Phase 1 baseline
├── test_phase2_routing.py         # Phase 2.1 tests (6/6 passing)
├── test_phase2.2_route_alternatives.py  # Phase 2.2 tests (6/6 passing)
├── test_phase2.2b_congestion.py   # Phase 2.2b tests (6/6 passing)
└── verify_refactor.py             # Refactoring verification
```

---

## 🎯 Current Capabilities

### What Works Now:

1. **Realistic Street Networks**
   - Load any location via OpenStreetMap
   - Separate networks for walk/bike/drive
   - Disk caching for fast reloads

2. **Smart Routing**
   - 5 route variants with different objectives
   - Elevation-aware (uphill = higher emissions)
   - Congestion-aware (avoids traffic)
   - Per-mode routing (walkers use pedestrian paths)

3. **Dynamic Traffic**
   - Real-time vehicle tracking
   - Congestion calculation (Linear/BPR/Exponential models)
   - Rush hour patterns (configurable peak times)
   - Statistics and monitoring

4. **Rich Metrics**
   - Distance, time, cost, emissions, comfort, risk
   - Elevation gain/loss, min/max elevation
   - Per-route and per-alternative metrics

5. **Agent Modeling**
   - BDI cognitive architecture
   - Desire-based mode choice
   - Route planning with preferences

---

## 🎨 Current Visualization (Streamlit + Folium)

**Location:** `ui/streamlit_app.py`

**Features:**
- Basic 2D map (Folium)
- Agent markers color-coded by mode
- Route visualization
- KPI dashboard (arrivals, emissions, distance, etc.)
- Modal share bar chart
- Travel time/distance distributions
- CSV export

**Limitations (why Phase 2.3 is needed):**
- ❌ Static map (no real-time updates)
- ❌ No animations (can't see agents move)
- ❌ No congestion visualization
- ❌ Poor performance with many agents
- ❌ No 3D visualization
- ❌ Limited interactivity

---

## 🚀 Phase 2.3: Advanced Visualization - Goals

### Primary Objectives:

1. **Real-Time Animated Maps**
   - See agents move along routes
   - Live position updates
   - Smooth animations

2. **Congestion Heatmaps**
   - Color edges by traffic density
   - Real-time congestion updates
   - Historical congestion playback

3. **3D Visualization**
   - Building heights
   - Elevation profiles
   - 3D routes with elevation

4. **Performance at Scale**
   - Handle 100+ agents smoothly
   - Efficient rendering
   - GPU acceleration

5. **Rich Interactivity**
   - Click agents for details
   - Hover for info
   - Time slider for playback
   - Layer toggles

### Technology Recommendations:

**Option A: deck.gl (Recommended)**
- WebGL-based (GPU accelerated)
- Designed for large datasets
- 3D support built-in
- Great for geospatial data
- Python binding: pydeck

**Option B: Plotly/Dash**
- More familiar to Python devs
- Good for dashboards
- Less performant at scale

**Option C: Custom Leaflet**
- Stay with Folium ecosystem
- Add animation plugins
- More limited than deck.gl

---

## 🎯 Phase 2.3 Feature Breakdown

### Must-Have (MVP):
1. ✅ Animated agent movement
2. ✅ Congestion heatmap
3. ✅ Time slider/playback controls
4. ✅ Real-time KPI updates
5. ✅ Better performance (100+ agents)

### Should-Have:
6. ⭐ 3D buildings/elevation
7. ⭐ Route alternative comparison view
8. ⭐ Agent detail panel (click to inspect)
9. ⭐ Layer toggles (agents/routes/congestion/elevation)

### Nice-to-Have:
10. 💫 Historical playback (save/load simulation state)
11. 💫 Emission plumes visualization
12. 💫 Network analysis views (degree centrality, etc.)
13. 💫 Multiple simulation comparison

---

## 📊 Data Available for Visualization

### Agent Data (per timestep):
```python
{
    'agent_id': 'agent_1',
    'position': (lon, lat),
    'mode': 'bike',
    'route': [(lon, lat), ...],
    'current_index': 5,
    'offset_km': 0.02,
    'emissions_total': 120.5,
    'distance_traveled': 2.3,
    'status': 'moving',  # or 'arrived'
}
```

### Congestion Data (per edge):
```python
{
    (u, v, key): {
        'vehicle_count': 5,
        'congestion_factor': 1.75,  # 1.75x slower
        'capacity': 10,
    }
}
```

### Route Alternative Data:
```python
{
    'route': [(lon, lat), ...],
    'variant': 'fastest',
    'metrics': {
        'distance': 2.3,
        'time': 12.5,
        'emissions': 45.2,
        'elevation_gain': 15.0,
        # ... etc
    }
}
```

### Network Data:
- Graph with 62K+ nodes, 160K+ edges (Edinburgh)
- Edge attributes: highway type, length, speed limit
- Node attributes: coordinates, elevation

---

## 🔧 Technical Constraints

### Environment:
- Python 3.13
- macOS (Apple Silicon M3)
- Virtual environment active
- All dependencies already installed:
  - osmnx, networkx, streamlit, folium
  - pandas, plotly, numpy, requests

### Performance Requirements:
- Support 100-500 agents
- Smooth animations (30+ FPS target)
- Real-time updates (< 100ms per frame)

### Integration Requirements:
- Must work with existing `SpatialEnvironment` API
- Should integrate with Streamlit (or standalone)
- Minimal changes to simulation core
- Backward compatible with existing UI

---

## 📦 Key Dependencies

### Already Installed:
```
osmnx==1.9.4
networkx==3.4.2
streamlit==1.40.1
folium==0.18.0
streamlit-folium==0.22.2
pandas==2.2.3
plotly==5.24.1
numpy==2.1.3
requests==2.32.3
```

### May Need to Install for Phase 2.3:
```
pydeck==0.9.1         # For deck.gl
dash==2.18.2          # If using Dash
dash-leaflet==1.0.15  # If using custom Leaflet
```

---

## 🎯 Success Criteria for Phase 2.3

Phase 2.3 is complete when:

- [ ] Agents animate smoothly along routes
- [ ] Congestion visible as colored heatmap
- [ ] Time slider allows playback control
- [ ] Performance acceptable with 100+ agents
- [ ] KPIs update in real-time
- [ ] Documentation complete
- [ ] At least one "wow factor" feature (3D, or stunning heatmap, etc.)

---

## 🚦 Recommended Implementation Approach

### Option 1: Iterative (Lower Risk)
1. **Week 1:** Basic pydeck integration, static map with agents
2. **Week 2:** Add animation, time slider
3. **Week 3:** Congestion heatmap, performance optimization
4. **Week 4:** 3D features, polish, documentation

### Option 2: MVP-First (Faster)
1. **Days 1-2:** Get pydeck working, show agents moving
2. **Day 3:** Add congestion heatmap
3. **Days 4-5:** Time controls, KPIs, polish

### Option 3: Prototype-Then-Build
1. **Day 1:** Create proof-of-concept with pydeck (just 10 agents)
2. **Days 2-3:** If good, build full system; if not, pivot to alternative
3. **Days 4-5:** Complete feature set

---

## 🎨 Visualization Architecture Proposal

```
RTD_SIM/
├── visualiser/
│   ├── __init__.py
│   ├── map_renderer.py         # Core map rendering
│   ├── animation_controller.py # Animation state management
│   ├── layer_manager.py        # Toggle layers (agents/routes/congestion)
│   ├── style_config.py         # Colors, sizes, styles
│   └── data_adapters.py        # Convert sim data to viz format
├── ui/
│   └── streamlit_viz_app.py    # New Streamlit app with deck.gl
```

### Key Classes:

```python
class MapRenderer:
    """Renders map using deck.gl/pydeck."""
    def render_agents(self, positions, modes)
    def render_routes(self, routes, colors)
    def render_heatmap(self, edge_data, values)
    def render_3d_buildings(self, building_data)

class AnimationController:
    """Manages animation state and playback."""
    def play()
    def pause()
    def step_forward()
    def step_backward()
    def seek(timestep)
    def set_speed(multiplier)

class LayerManager:
    """Manages visibility of map layers."""
    def toggle_agents()
    def toggle_routes()
    def toggle_congestion()
    def toggle_elevation()
```

---

## 💡 Design Decisions to Consider

### 1. Real-Time vs. Replay
- **Real-Time:** Simulation runs, visualization updates live
- **Replay:** Simulation completes, then replay with full controls
- **Recommendation:** Start with replay (simpler), add real-time later

### 2. Integration Strategy
- **Option A:** Separate Streamlit app (visualiser only)
- **Option B:** Extend existing streamlit_app.py
- **Option C:** Standalone app (no Streamlit)
- **Recommendation:** Option A (clean separation)

### 3. Data Storage for Playback
- **Option A:** Store all timesteps in memory (simple, memory-heavy)
- **Option B:** Write to SQLite/file, read on demand (complex, disk I/O)
- **Option C:** Downsample for long simulations (tradeoff)
- **Recommendation:** Start with A, optimize to C if needed

---

## 📚 Reference Materials

### Existing Code Patterns:

**How to run a simulation:**
```python
from simulation.spatial_environment import SpatialEnvironment
from simulation.controller import SimulationController

env = SpatialEnvironment(use_congestion=True)
env.load_osm_graph(place="Edinburgh, Scotland")

controller = SimulationController(env, num_agents=100)
controller.run(num_steps=500)

# Access results
results = controller.get_results()
```

**How to get agent positions:**
```python
for agent in controller.agents:
    position = agent.current_position  # (lon, lat)
    mode = agent.current_mode
    route = agent.current_route
```

**How to get congestion:**
```python
if env.congestion_manager:
    heatmap = env.get_congestion_heatmap()
    # heatmap = {(u, v, key): congestion_factor}
```

### External Resources:
- pydeck docs: https://deckgl.readthedocs.io/
- deck.gl examples: https://deck.gl/examples
- Streamlit pydeck: https://docs.streamlit.io/library/api-reference/charts/st.pydeck_chart

---

## 🐛 Known Issues to Be Aware Of

1. **Folium Performance:** Current UI struggles with >50 agents
2. **Memory Usage:** Storing all timesteps can use significant RAM
3. **MacOS/M3 Compatibility:** Some viz libraries have ARM issues
4. **Streamlit Reruns:** Can cause flickering if not handled carefully

---

## 🎯 Quick Start for Phase 2.3

### Immediate Next Steps:

1. **Install pydeck:**
   ```bash
   pip install pydeck
   ```

2. **Create proof-of-concept:**
   ```python
   import pydeck as pdk
   import pandas as pd
   
   # Test with Edinburgh coordinates
   data = pd.DataFrame({
       'lat': [55.9533, 55.9486, 55.9445],
       'lon': [-3.1883, -3.2008, -3.1619],
       'color': [[255,0,0], [0,255,0], [0,0,255]]
   })
   
   layer = pdk.Layer(
       'ScatterplotLayer',
       data,
       get_position='[lon, lat]',
       get_color='color',
       get_radius=100,
   )
   
   view_state = pdk.ViewState(
       latitude=55.95,
       longitude=-3.19,
       zoom=12,
       pitch=0,
   )
   
   r = pdk.Deck(layers=[layer], initial_view_state=view_state)
   r.to_html('test_map.html')
   ```

3. **Verify it works**, then build from there

---

## 📞 Questions for New Session

When you start Phase 2.3, please confirm:

1. **Visualization approach:** deck.gl (pydeck) vs. alternatives?
2. **Real-time or replay first?** (Recommendation: replay)
3. **Standalone or integrated?** (Recommendation: new Streamlit app)
4. **Priority features:** Which are most important to you?
   - Animations
   - Congestion heatmap
   - 3D visualization
   - Performance
   - Interactivity

---

## 🎉 What You've Accomplished

You have built a sophisticated multi-agent transport simulation with:
- ✅ Real street networks from any city
- ✅ Intelligent routing with 5 variants
- ✅ Dynamic traffic congestion
- ✅ Elevation-aware energy modeling
- ✅ Clean, modular architecture
- ✅ Comprehensive test coverage
- ✅ 12.2% overhead for full congestion tracking

**Now it's time to make it look amazing! 🚀**

---

**Session End State:** All Phase 2.2b tests passing. Architecture clean. Ready for Phase 2.3 visualization development.
