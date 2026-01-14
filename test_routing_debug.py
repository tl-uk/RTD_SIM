"""
test_routing_debug.py - Diagnose routing failure for freight agents

Run this to see exactly where the routing is failing.
"""

import sys
from pathlib import Path
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(name)s - %(message)s'
)

# Add parent directory to path
parent_dir = Path(__file__).resolve().parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from simulation.spatial_environment import SpatialEnvironment
from agent.bdi_planner import BDIPlanner
from simulation.infrastructure.infrastructure_manager import InfrastructureManager


def test_single_freight_agent():
    """Test a single freight agent end-to-end."""
    
    print("\n" + "="*80)
    print("FREIGHT ROUTING DIAGNOSTIC TEST")
    print("="*80 + "\n")
    
    # 1. Load graph
    print("📍 Step 1: Loading OSM graph for Central Scotland...")
    env = SpatialEnvironment()
    
    bbox = (-4.50, 55.70, -2.90, 56.10)  # Central Scotland
    env.load_osm_graph(bbox=bbox, network_type='drive', use_cache=True)
    
    if not env.graph_loaded:
        print("❌ FAILED: Graph not loaded")
        return
    
    print(f"✅ Graph loaded: {env.G.number_of_nodes()} nodes, {env.G.number_of_edges()} edges\n")
    
    # 2. Setup infrastructure
    print("📍 Step 2: Initializing infrastructure...")
    infra = InfrastructureManager(env)
    infra.initialize_charging_network(num_chargers=50, charger_types=['dcfast', 'level2'])
    print(f"✅ Infrastructure ready: {len(infra.charging_stations)} chargers\n")
    
    # 3. Create BDI planner
    print("📍 Step 3: Creating BDI planner...")
    planner = BDIPlanner(infrastructure_manager=infra)
    print(f"✅ Planner created (infrastructure-aware: {planner.has_infrastructure})\n")
    
    # 4. Test coordinates (Edinburgh → Glasgow)
    print("📍 Step 4: Setting up test route...")
    origin = (-3.1883, 55.9533)  # Edinburgh
    dest = (-4.2518, 55.8642)    # Glasgow
    
    print(f"   Origin: Edinburgh {origin}")
    print(f"   Dest: Glasgow {dest}")
    
    from simulation.spatial.coordinate_utils import haversine_km
    straight_line = haversine_km(origin, dest)
    print(f"   Straight-line distance: {straight_line:.1f} km\n")
    
    # 5. Test different vehicle types
    test_cases = [
        {
            'name': 'Heavy Freight (HGV)',
            'context': {
                'vehicle_required': True,
                'cargo_capacity': True,
                'vehicle_type': 'heavy_freight',
                'priority': 'commercial'
            },
            'expected_modes': ['hgv_diesel', 'hgv_electric', 'truck_diesel']
        },
        {
            'name': 'Medium Freight (Truck)',
            'context': {
                'vehicle_required': True,
                'cargo_capacity': True,
                'vehicle_type': 'medium_freight',
                'priority': 'commercial'
            },
            'expected_modes': ['truck_diesel', 'truck_electric', 'van_diesel']
        },
        {
            'name': 'Light Commercial (Van)',
            'context': {
                'vehicle_required': True,
                'cargo_capacity': True,
                'vehicle_type': 'commercial',
                'priority': 'commercial'
            },
            'expected_modes': ['van_electric', 'van_diesel', 'cargo_bike']
        },
    ]
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n{'='*80}")
        print(f"TEST CASE {i}: {test['name']}")
        print(f"{'='*80}")
        
        context = test['context']
        print(f"\n📋 Agent Context:")
        for key, value in context.items():
            print(f"   {key}: {value}")
        
        # Test mode filtering
        print(f"\n🔍 Testing BDI Planner mode filtering...")
        modes = planner._filter_modes_by_context(context, straight_line)
        print(f"   Modes offered: {modes}")
        print(f"   Expected: {test['expected_modes']}")
        
        if not modes:
            print(f"   ❌ FAILED: No modes returned!")
            continue
        
        # Check if expected modes are present
        found_expected = any(m in modes for m in test['expected_modes'])
        if found_expected:
            print(f"   ✅ PASS: At least one expected mode found")
        else:
            print(f"   ⚠️ WARNING: Expected modes not found")
        
        # Test routing for each mode
        print(f"\n🗺️ Testing route computation for each mode...")
        
        for mode in modes[:3]:  # Test first 3 modes
            print(f"\n   Testing {mode}:")
            
            # Create dummy state
            class DummyState:
                agent_id = f"test_agent_{mode}"
            
            state = DummyState()
            
            # Try to compute route
            route = env.compute_route(
                agent_id=state.agent_id,
                origin=origin,
                dest=dest,
                mode=mode
            )
            
            if not route or len(route) < 2:
                print(f"      ❌ Route computation FAILED")
                continue
            
            from simulation.spatial.coordinate_utils import route_distance_km
            route_dist = route_distance_km(route)
            
            if route_dist == 0.0:
                print(f"      ❌ Route has 0.0 km distance")
                continue
            
            print(f"      ✅ Route computed: {len(route)} waypoints, {route_dist:.1f} km")
            
            # Test action generation
            print(f"      Testing action generation...")
            actions = planner.actions_for(env, state, origin, dest, context)
            
            if not actions:
                print(f"      ❌ No actions generated")
            else:
                print(f"      ✅ {len(actions)} actions generated")
                for action in actions:
                    action_dist = route_distance_km(action.route)
                    print(f"         - {action.mode}: {action_dist:.1f} km")
    
    print("\n" + "="*80)
    print("DIAGNOSTIC COMPLETE")
    print("="*80 + "\n")


def test_router_mode_mapping():
    """Test if router has all mode mappings."""
    
    print("\n" + "="*80)
    print("ROUTER MODE MAPPING TEST")
    print("="*80 + "\n")
    
    from simulation.spatial.router import Router
    from simulation.spatial.graph_manager import GraphManager
    
    graph_manager = GraphManager()
    router = Router(graph_manager)
    
    all_modes = [
        # Active
        'walk', 'bike', 'cargo_bike', 'e_scooter',
        # Passenger
        'bus', 'car', 'ev',
        # Freight
        'van_electric', 'van_diesel',
        'truck_electric', 'truck_diesel',
        'hgv_electric', 'hgv_diesel', 'hgv_hydrogen',
        # Public transport
        'tram', 'local_train', 'intercity_train',
        # Maritime
        'ferry_diesel', 'ferry_electric',
        # Aviation
        'flight_domestic', 'flight_electric',
    ]
    
    print("Checking mode_network_types mapping:")
    print("-" * 80)
    
    missing_modes = []
    for mode in all_modes:
        network = router.mode_network_types.get(mode, None)
        speed = router.speeds_km_min.get(mode, None)
        
        if network is None:
            missing_modes.append(mode)
            print(f"❌ {mode:20s} - NOT MAPPED")
        else:
            speed_str = f"{speed:.2f} km/min" if speed else "NO SPEED"
            print(f"✅ {mode:20s} → {network:10s} ({speed_str})")
    
    print("-" * 80)
    
    if missing_modes:
        print(f"\n❌ MISSING MAPPINGS: {missing_modes}")
        return False
    else:
        print(f"\n✅ ALL {len(all_modes)} MODES MAPPED CORRECTLY")
        return True


if __name__ == "__main__":
    print("\n🔧 RTD_SIM Routing Diagnostic Tool\n")
    
    # First test router mappings
    print("=" * 80)
    print("PHASE 1: Router Mode Mapping Check")
    print("=" * 80)
    
    mapping_ok = test_router_mode_mapping()
    
    if not mapping_ok:
        print("\n❌ Router mappings incomplete - fix router.py first!")
        sys.exit(1)
    
    # Then test actual routing
    print("\n\n" + "=" * 80)
    print("PHASE 2: End-to-End Freight Routing Test")
    print("=" * 80)
    
    test_single_freight_agent()
    
    print("\n✅ Diagnostic complete - check output above for failures\n")