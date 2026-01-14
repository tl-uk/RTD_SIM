"""
test_edinburgh_freight.py - Quick test with Edinburgh (known working)

This bypasses the regional bbox and uses Edinburgh city only.
Should complete in <2 minutes if cached.
"""

import sys
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

parent_dir = Path(__file__).resolve().parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from simulation.spatial_environment import SpatialEnvironment
from agent.bdi_planner import BDIPlanner
from simulation.infrastructure.infrastructure_manager import InfrastructureManager
from agent.story_driven_agent import StoryDrivenAgent

print("\n" + "="*80)
print("EDINBURGH FREIGHT TEST - Quick Diagnostic")
print("="*80 + "\n")

# 1. Load Edinburgh (small, cached)
print("📍 Step 1: Loading Edinburgh graph (cached)...")
env = SpatialEnvironment()
env.load_osm_graph(place="Edinburgh, UK", network_type='drive', use_cache=True)

if not env.graph_loaded:
    print("❌ FAILED: Graph not loaded")
    sys.exit(1)

stats = env.get_graph_stats()
print(f"✅ Graph: {stats['nodes']:,} nodes, {stats['edges']:,} edges\n")

# 2. Setup infrastructure
print("📍 Step 2: Setting up infrastructure...")
infra = InfrastructureManager()
infra.populate_edinburgh_chargers(num_public=50, num_depot=5)
print(f"✅ Infrastructure: {len(infra.charging_stations)} stations\n")

# 3. Create BDI planner
print("📍 Step 3: Creating BDI planner...")
planner = BDIPlanner(infrastructure_manager=infra)
print(f"✅ Planner ready (infrastructure-aware: {planner.has_infrastructure})\n")

# 4. Create a freight agent
print("📍 Step 4: Creating freight agent...")

# Edinburgh city center coordinates
origin = (-3.1883, 55.9533)  # Edinburgh center
dest = (-3.0883, 55.9633)    # 10km east (Leith area)

print(f"   Origin: {origin}")
print(f"   Dest: {dest}\n")

# Create agent with van delivery job
try:
    agent = StoryDrivenAgent(
        user_story_id='business_commuter',
        job_story_id='service_engineer_call',  # Van delivery job
        origin=origin,
        dest=dest,
        planner=planner,
        seed=42
    )
    
    print(f"✅ Agent created: {agent.state.agent_id}")
    print(f"   Context: {agent.agent_context}")
    print(f"   Mode: {agent.state.mode}")
    print(f"   Route points: {len(agent.state.route)}")
    print(f"   Distance: {agent.state.distance_km:.1f} km\n")
    
    # Check if routing worked
    if agent.state.mode == 'walk' and agent.state.distance_km == 0.0:
        print("❌ FAILED: Agent stuck on walk with 0km")
        print("\nDebugging info:")
        print(f"   - Graph loaded: {env.graph_loaded}")
        print(f"   - Agent context: {agent.agent_context}")
        print(f"   - Route: {agent.state.route[:3]}... (showing first 3 points)")
        
        # Try manual route computation
        print("\n🔍 Testing manual route computation...")
        manual_route = env.compute_route(
            agent_id="test",
            origin=origin,
            dest=dest,
            mode="van_diesel"
        )
        
        print(f"   Manual route points: {len(manual_route)}")
        if len(manual_route) > 2:
            from simulation.spatial.coordinate_utils import route_distance_km
            dist = route_distance_km(manual_route)
            print(f"   Manual route distance: {dist:.1f} km")
            print("   ✅ Manual routing WORKS - issue is in agent creation/BDI")
        else:
            print("   ❌ Manual routing FAILED - issue is in router")
    
    elif agent.state.mode != 'walk':
        print(f"✅ SUCCESS! Agent using {agent.state.mode}")
        print(f"   Distance: {agent.state.distance_km:.1f} km")
        print(f"   Emissions: {agent.state.emissions_g:.0f}g CO2")
    
    else:
        print(f"⚠️ Agent on walk but has route ({agent.state.distance_km:.1f} km)")

except Exception as e:
    print(f"❌ EXCEPTION: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*80)
print("TEST COMPLETE")
print("="*80)