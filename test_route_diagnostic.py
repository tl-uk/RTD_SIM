# Route Visualization Diagnostic

## Good News!

Your `simulation_loop.py` **line 653** already includes routes:

```python
agent_states.append({
    'agent_id': agent.state.agent_id,
    'location': agent.state.location,
    'mode': agent.state.mode,
    'arrived': agent.state.arrived,
    'route': agent.state.route,  # ← Line 653 - Already there!
    'distance_km': agent.state.distance_km,
    'emissions_g': agent.state.emissions_g,
})
```

AND your `visualization.py` lines 157-192 already renders routes with PathLayer!

## So Why Straight Lines?

There are three possible reasons:

### Reason 1: Routes Are Empty or None

Agents might have `route=None` or `route=[]` in their state.

### Reason 2: Routes Have Only 2 Points (Origin→Dest)

When OSMnx routing fails, it falls back to `[origin, dest]` which looks like a straight line.

### Reason 3: UI Show Routes Toggle Is Off

The routes exist but aren't being displayed because `show_routes=False`.

---

## Diagnostic Test

Run this to see what's actually happening:

```python
# test_route_diagnostic.py
from simulation.simulation_runner import run_simulation
from simulation.config.simulation_config import SimulationConfig

config = SimulationConfig(
    steps=20,
    num_agents=10,
    place='Edinburgh, UK',
    enable_analytics=True,
)

results = run_simulation(config)

print("="*70)
print("ROUTE DIAGNOSTIC REPORT")
print("="*70)

# Check agents
print(f"\n📊 Total agents: {len(results.agents)}")

route_quality = {
    'good_routes': 0,      # 5+ waypoints
    'short_routes': 0,     # 3-4 waypoints  
    'straight_lines': 0,   # 2 waypoints
    'no_routes': 0,        # None or empty
}

for i, agent in enumerate(results.agents):
    route = agent.state.route
    agent_id = agent.state.agent_id
    mode = agent.state.mode
    
    if not route:
        route_quality['no_routes'] += 1
        print(f"❌ {agent_id} ({mode}): NO ROUTE")
    elif len(route) == 2:
        route_quality['straight_lines'] += 1
        print(f"⚠️  {agent_id} ({mode}): 2 waypoints (straight line)")
    elif len(route) <= 4:
        route_quality['short_routes'] += 1
        print(f"⚠️  {agent_id} ({mode}): {len(route)} waypoints (short route)")
    else:
        route_quality['good_routes'] += 1
        print(f"✅ {agent_id} ({mode}): {len(route)} waypoints")

print(f"\n{'='*70}")
print("SUMMARY:")
print(f"  Good routes (5+ points): {route_quality['good_routes']}")
print(f"  Short routes (3-4 points): {route_quality['short_routes']}")
print(f"  Straight lines (2 points): {route_quality['straight_lines']}")
print(f"  No routes: {route_quality['no_routes']}")
print(f"{'='*70}")

# Check time series
if results.time_series and len(results.time_series.data) > 0:
    print(f"\n📈 Time Series Check:")
    sample_step = results.time_series.data[10]  # Step 10
    agent_states = sample_step['agent_states']
    
    print(f"  Step 10 has {len(agent_states)} agent states")
    
    sample_agent = agent_states[0]
    print(f"  Sample agent keys: {list(sample_agent.keys())}")
    print(f"  Has 'route' key: {'route' in sample_agent}")
    
    if 'route' in sample_agent:
        route = sample_agent['route']
        if route:
            print(f"  Route has {len(route)} waypoints")
            print(f"  First 2 points: {route[:2]}")
        else:
            print(f"  Route is None/empty")

print(f"\n{'='*70}")
print("RECOMMENDATIONS:")
print(f"{'='*70}")

if route_quality['straight_lines'] > route_quality['good_routes']:
    print("⚠️  HIGH: Most routes are straight lines (2 waypoints)")
    print("   → OSMnx routing is failing for most agents")
    print("   → Possible fixes:")
    print("     1. Check if OSM network is loaded correctly")
    print("     2. Increase routing distance tolerance")
    print("     3. Improve fallback routing logic")

if route_quality['no_routes'] > 0:
    print("⚠️  MEDIUM: Some agents have no routes at all")
    print("   → Check agent initialization")
    
if route_quality['good_routes'] > len(results.agents) * 0.7:
    print("✅ GOOD: Most routes have proper waypoints")
    print("   → If still seeing straight lines in UI, check:")
    print("     1. Is 'Show Routes' toggle enabled?")
    print("     2. Are routes being filtered out by visualization?")

print(f"{'='*70}\n")
```

---

## Expected Output

### If Routing Works:
```
✅ agent_1 (ev): 15 waypoints
✅ agent_2 (bike): 23 waypoints
✅ agent_3 (bus): 18 waypoints
⚠️  agent_4 (walk): 2 waypoints (straight line)
✅ agent_5 (car): 12 waypoints

SUMMARY:
  Good routes (5+ points): 8
  Short routes (3-4 points): 1
  Straight lines (2 points): 1
  No routes: 0
```

### If Routing Fails:
```
⚠️  agent_1 (ev): 2 waypoints (straight line)
⚠️  agent_2 (bike): 2 waypoints (straight line)
⚠️  agent_3 (bus): 2 waypoints (straight line)
❌ agent_4 (walk): NO ROUTE
⚠️  agent_5 (car): 2 waypoints (straight line)

SUMMARY:
  Good routes (5+ points): 0
  Short routes (3-4 points): 0
  Straight lines (2 points): 4
  No routes: 1
```

---

## Next Steps Based on Results

### If Most Routes Are Good (5+ waypoints):
→ **UI Issue**: Check if "Show Routes" toggle is enabled in Streamlit
→ **Verify**: Run your simulation and enable routes in the map settings

### If Most Routes Are Straight Lines (2 waypoints):
→ **Routing Issue**: OSMnx is failing and falling back to straight lines
→ **Fix**: Need to improve the routing in `spatial_environment.py`

### If Routes Are None/Empty:
→ **Agent Issue**: Routes aren't being created during planning
→ **Fix**: Check BDI planner route assignment

---

## Quick UI Check

In your Streamlit app, make sure routes are enabled:

```python
# In sidebar or settings
st.session_state.show_routes = True  # Make sure this is True!
```

Or in your map_tab.py:
```python
deck = render_map(
    agent_states=agent_states,
    show_agents=st.session_state.show_agents,
    show_routes=True,  # ← Force enable for testing
    show_infrastructure=st.session_state.show_infrastructure,
    infrastructure_manager=results.infrastructure,
)
```

---

## The Real Question

Run the diagnostic and tell me which scenario you see:

1. ✅ "Good routes" > 70% → It's a UI toggle issue
2. ⚠️ "Straight lines" > 70% → It's an OSMnx routing issue
3. ❌ "No routes" > 30% → It's an agent planning issue

Then we'll know exactly what to fix!
