"""
Route Visualization Diagnostic Script

Run this to diagnose route visualization issues.
"""

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

total_agents = len(results.agents)

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
    
if route_quality['good_routes'] > total_agents * 0.7:
    print("✅ GOOD: Most routes have proper waypoints")
    print("   → If still seeing straight lines in UI, check:")
    print("     1. Is 'Show Routes' toggle enabled?")
    print("     2. Are routes being filtered out by visualization?")

print(f"{'='*70}\n")

# Print detailed example
if results.agents:
    print("DETAILED EXAMPLE (First Agent):")
    print("="*70)
    agent = results.agents[0]
    route = agent.state.route
    print(f"Agent ID: {agent.state.agent_id}")
    print(f"Mode: {agent.state.mode}")
    print(f"Origin: {agent.origin}")
    print(f"Destination: {agent.dest}")
    if route:
        print(f"Route waypoints: {len(route)}")
        print(f"First 3 waypoints: {route[:3]}")
        print(f"Last 3 waypoints: {route[-3:]}")
        
        # Calculate route distance
        from simulation.spatial.coordinate_utils import route_distance_km
        try:
            route_dist = route_distance_km(route)
            from simulation.spatial.coordinate_utils import haversine_km
            straight_dist = haversine_km(agent.origin, agent.dest)
            print(f"Route distance: {route_dist:.2f} km")
            print(f"Straight-line distance: {straight_dist:.2f} km")
            print(f"Detour factor: {route_dist/straight_dist:.2f}x")
        except:
            print("Could not calculate distances")
    else:
        print("Route: None")
    print("="*70)