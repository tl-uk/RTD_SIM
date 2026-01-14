"""
check_graph_loaded.py - Quick check if graph is loaded in simulation

This will tell us if the issue is graph loading or routing logic.
"""

import sys
from pathlib import Path

parent_dir = Path(__file__).resolve().parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))


def check_graph_in_simulation():
    """Check if graph loads correctly with the simulation config."""
    
    print("\n" + "="*80)
    print("GRAPH LOADING CHECK")
    print("="*80 + "\n")
    
    from simulation.spatial_environment import SpatialEnvironment
    
    # Test 1: Edinburgh City (smaller area)
    print("Test 1: Edinburgh City (place name)")
    print("-" * 80)
    
    env1 = SpatialEnvironment()
    env1.load_osm_graph(place="Edinburgh, UK", network_type='drive', use_cache=True)
    
    if env1.graph_loaded:
        print(f"✅ Graph loaded successfully")
        print(f"   Nodes: {env1.G.number_of_nodes():,}")
        print(f"   Edges: {env1.G.number_of_edges():,}")
        
        # Test a simple route
        origin = (-3.1883, 55.9533)  # Edinburgh city center
        dest = (-3.2218, 55.9486)    # 3km west
        
        route = env1.compute_route("test", origin, dest, "car")
        
        if route and len(route) > 2:
            from simulation.spatial.coordinate_utils import route_distance_km
            dist = route_distance_km(route)
            print(f"   Test route: {len(route)} waypoints, {dist:.1f} km")
            print(f"   ✅ Routing works!")
        else:
            print(f"   ❌ Routing failed: route has {len(route) if route else 0} points")
    else:
        print(f"❌ Graph NOT loaded")
    
    print()
    
    # Test 2: Central Scotland (bbox)
    print("Test 2: Central Scotland (bbox)")
    print("-" * 80)
    
    env2 = SpatialEnvironment()
    bbox = (-4.50, 55.70, -2.90, 56.10)
    
    print(f"Loading bbox: {bbox}")
    print("This may take a while if not cached...")
    
    env2.load_osm_graph(bbox=bbox, network_type='drive', use_cache=True)
    
    if env2.graph_loaded:
        print(f"✅ Graph loaded successfully")
        print(f"   Nodes: {env2.G.number_of_nodes():,}")
        print(f"   Edges: {env2.G.number_of_edges():,}")
        
        # Test Edinburgh → Glasgow route
        origin = (-3.1883, 55.9533)  # Edinburgh
        dest = (-4.2518, 55.8642)    # Glasgow
        
        route = env2.compute_route("test", origin, dest, "hgv_diesel")
        
        if route and len(route) > 2:
            from simulation.spatial.coordinate_utils import route_distance_km
            dist = route_distance_km(route)
            print(f"   Test HGV route Edinburgh→Glasgow: {len(route)} waypoints, {dist:.1f} km")
            print(f"   ✅ Freight routing works!")
        else:
            print(f"   ❌ Routing failed: route has {len(route) if route else 0} points")
    else:
        print(f"❌ Graph NOT loaded")
    
    print()
    
    # Test 3: Check what your simulation is actually doing
    print("Test 3: Checking simulation config")
    print("-" * 80)
    
    from simulation.config.simulation_config import SimulationConfig
    
    # Recreate your simulation config
    config = SimulationConfig(
        steps=100,
        num_agents=50,
        place=None,  # You're using bbox, not place
        extended_bbox=(-4.30, 55.80, -3.10, 56.00),
        use_osm=True,
        user_stories=['eco_warrior', 'budget_student'],
        job_stories=['long_haul_freight', 'port_to_warehouse'],
        enable_infrastructure=True,
        num_chargers=50
    )
    
    print(f"Config:")
    print(f"   use_osm: {config.use_osm}")
    print(f"   place: {config.place}")
    print(f"   extended_bbox: {config.extended_bbox}")
    
    if config.use_osm:
        print(f"   ✅ OSM enabled")
    else:
        print(f"   ❌ OSM disabled - this would cause 0km routes!")
    
    print("\n" + "="*80)
    print("DIAGNOSIS")
    print("="*80 + "\n")
    
    if not env1.graph_loaded and not env2.graph_loaded:
        print("❌ PROBLEM: Graphs not loading at all")
        print("   This would cause all agents to have 0km routes.")
        print("   Check if OSMnx is installed: pip install osmnx")
    elif env2.graph_loaded:
        print("✅ Graphs load correctly")
        print("   The issue must be in the BDI planner or agent creation.")
        print("   Next: Check that your simulation is actually loading the graph.")
    
    print()


def check_simulation_execution():
    """Check if simulation loads graph during execution."""
    
    print("\n" + "="*80)
    print("SIMULATION EXECUTION CHECK")
    print("="*80 + "\n")
    
    print("Looking for simulation execution code...")
    
    # Check if there's a main simulation file
    main_files = [
        'main.py',
        'app.py',
        'run_simulation.py',
        'simulation/run.py'
    ]
    
    for filepath in main_files:
        path = Path(filepath)
        if path.exists():
            print(f"\nFound: {filepath}")
            print("Check if it calls:")
            print("   env.load_osm_graph(...)")
            print("   OR")
            print("   env.load_mode_specific_graphs(...)")
            print()
            print("If not, add this BEFORE creating agents:")
            print()
            print("   if config.use_osm:")
            print("       if config.extended_bbox:")
            print("           env.load_osm_graph(bbox=config.extended_bbox, network_type='drive')")
            print("       else:")
            print("           env.load_osm_graph(place=config.place, network_type='drive')")
            print()


if __name__ == "__main__":
    check_graph_in_simulation()
    check_simulation_execution()
    
    print("="*80)
    print("NEXT STEPS:")
    print("="*80)
    print()
    print("1. If graphs load correctly above, check your main simulation code")
    print("2. Ensure it calls env.load_osm_graph() BEFORE creating agents")
    print("3. If graphs don't load, there's an OSMnx installation issue")
    print()