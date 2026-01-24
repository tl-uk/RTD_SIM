# debug/debug_agent_routing.py
import secrets
import random
from simulation.spatial_environment import SpatialEnvironment
from simulation.infrastructure.infrastructure_manager import InfrastructureManager
from agent.bdi_planner import BDIPlanner
from agent.story_driven_agent import StoryDrivenAgent

# Setup
env = SpatialEnvironment()
env.load_osm_graph(place="Edinburgh, Scotland", network_type='all')

infrastructure = InfrastructureManager(grid_capacity_mw=20)
infrastructure.populate_edinburgh_chargers(num_public=50, num_depot=5)

planner = BDIPlanner(infrastructure_manager=infrastructure)

# Create a cargo bike agent (like the problematic one)
origin = (-3.19, 55.95)  # Edinburgh center
dest = (-3.40, 55.98)    # West Edinburgh

print(f"\n{'='*60}")
print("Creating cargo bike agent...")
print(f"{'='*60}\n")

agent = StoryDrivenAgent(
    user_story_id='eco_warrior',
    job_story_id='van_warehouse_transfer_generated_9798',
    origin=origin,
    dest=dest,
    planner=planner,
    seed=secrets.randbits(32),
    apply_variance=True
)

print(f"Agent ID: {agent.state.agent_id}")
print(f"Job: {agent.job_story_id}")
print(f"Mode: {agent.state.mode}")
print(f"Vehicle type: {agent.agent_context.get('vehicle_type')}")
print(f"Vehicle required: {agent.agent_context.get('vehicle_required')}")

print(f"\n{'='*60}")
print("Initial route check...")
print(f"{'='*60}\n")

if agent.state.route:
    print(f"✅ Route assigned: {len(agent.state.route)} waypoints")
    print(f"   First 3 points: {agent.state.route[:3]}")
    print(f"   Last 3 points: {agent.state.route[-3:]}")
    
    # Check if straight line
    from simulation.spatial.coordinate_utils import haversine_km
    straight_dist = haversine_km(origin, dest)
    
    if len(agent.state.route) == 2:
        route_dist = haversine_km(agent.state.route[0], agent.state.route[1])
        if abs(straight_dist - route_dist) < 0.1:
            print(f"   ❌ STRAIGHT LINE DETECTED!")
            print(f"      Straight distance: {straight_dist:.1f}km")
            print(f"      Route distance: {route_dist:.1f}km")
        else:
            print(f"   ✅ Valid 2-point route")
    else:
        from simulation.spatial.coordinate_utils import route_distance_km
        route_dist = route_distance_km(agent.state.route)
        print(f"   Straight distance: {straight_dist:.1f}km")
        print(f"   Route distance: {route_dist:.1f}km")
        print(f"   Detour: +{((route_dist/straight_dist - 1) * 100):.1f}%")
else:
    print(f"❌ NO ROUTE ASSIGNED!")

print(f"\n{'='*60}")
print("Stepping agent once...")
print(f"{'='*60}\n")

state = agent.step(env=env)

print(f"After step:")
print(f"  Mode: {state['mode']}")
print(f"  Location: {state['location']}")
print(f"  Route waypoints: {len(agent.state.route) if agent.state.route else 0}")

if agent.state.route:
    print(f"  Route still has {len(agent.state.route)} waypoints")
else:
    print(f"  ❌ Route was lost/cleared!")