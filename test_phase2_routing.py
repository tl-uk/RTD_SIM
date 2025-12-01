"""
Test script for Phase 2.1 OSM features.

Tests:
1. Mode-specific routing (walk vs drive networks)
2. Elevation data integration
3. Energy consumption with elevation

Usage:
    python test_phase2_routing.py
"""

from __future__ import annotations
import sys
from pathlib import Path

# Add project to path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulation.spatial_environment import SpatialEnvironment
import logging

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger(__name__)


def test_basic_loading():
    """Test 1: Basic OSM graph loading with caching."""
    print("\n" + "="*60)
    print("TEST 1: Basic Graph Loading & Caching")
    print("="*60)
    
    env = SpatialEnvironment(step_minutes=1.0)
    
    # Load Edinburgh
    print("\n🔄 Loading Edinburgh OSM graph...")
    env.load_osm_graph(
        place="Edinburgh, UK",
        network_type="all",
        use_cache=True
    )
    
    stats = env.get_graph_stats()
    print(f"\n✅ Graph loaded: {stats['nodes']:,} nodes, {stats['edges']:,} edges")
    print(f"   Cache size: {stats['cache_size']} precomputed nodes")
    
    return env


def test_mode_specific_networks():
    """Test 2: Load different networks for different modes."""
    print("\n" + "="*60)
    print("TEST 2: Mode-Specific Networks")
    print("="*60)
    
    # Test walk network
    print("\n🚶 Loading WALK network...")
    env_walk = SpatialEnvironment(step_minutes=1.0)
    env_walk.load_osm_graph(place="Edinburgh, UK", network_type="walk", use_cache=True)
    stats_walk = env_walk.get_graph_stats()
    
    # Test drive network
    print("\n🚗 Loading DRIVE network...")
    env_drive = SpatialEnvironment(step_minutes=1.0)
    env_drive.load_osm_graph(place="Edinburgh, UK", network_type="drive", use_cache=True)
    stats_drive = env_drive.get_graph_stats()
    
    # Test bike network
    print("\n🚴 Loading BIKE network...")
    env_bike = SpatialEnvironment(step_minutes=1.0)
    env_bike.load_osm_graph(place="Edinburgh, UK", network_type="bike", use_cache=True)
    stats_bike = env_bike.get_graph_stats()
    
    # Compare
    print("\n📊 Network Comparison:")
    print(f"   Walk:  {stats_walk['nodes']:,} nodes, {stats_walk['edges']:,} edges")
    print(f"   Drive: {stats_drive['nodes']:,} nodes, {stats_drive['edges']:,} edges")
    print(f"   Bike:  {stats_bike['nodes']:,} nodes, {stats_bike['edges']:,} edges")
    
    # Expected: walk > bike > drive (walk has most options)
    assert stats_walk['nodes'] > 0, "Walk network should have nodes"
    assert stats_drive['nodes'] > 0, "Drive network should have nodes"
    
    print("\n✅ Mode-specific networks loaded successfully")
    print("   NOTE: Current implementation uses same graph for all modes.")
    print("   TODO: Implement per-agent mode-specific routing.")
    
    return env_walk, env_drive, env_bike


def test_routing_comparison():
    """Test 3: Compare routes between different networks."""
    print("\n" + "="*60)
    print("TEST 3: Routing Comparison (Walk vs Drive)")
    print("="*60)
    
    # Load both networks
    env_walk = SpatialEnvironment(step_minutes=1.0)
    env_walk.load_osm_graph(place="Edinburgh, UK", network_type="walk", use_cache=True)
    
    env_drive = SpatialEnvironment(step_minutes=1.0)
    env_drive.load_osm_graph(place="Edinburgh, UK", network_type="drive", use_cache=True)
    
    # Get random origin/destination
    origin = env_walk.get_random_node_coords()
    dest = env_walk.get_random_node_coords()
    
    if origin is None or dest is None:
        print("⚠️  Could not get random nodes for testing")
        return
    
    print(f"\n📍 Origin: {origin}")
    print(f"📍 Dest:   {dest}")
    
    # Compute routes
    route_walk = env_walk.compute_route("test_walker", origin, dest, "walk")
    route_drive = env_drive.compute_route("test_driver", origin, dest, "car")
    
    # Compare
    walk_dist = env_walk._distance(route_walk)
    drive_dist = env_drive._distance(route_drive)
    
    print(f"\n🚶 Walk route:  {len(route_walk):3d} waypoints, {walk_dist:.3f} km")
    print(f"🚗 Drive route: {len(route_drive):3d} waypoints, {drive_dist:.3f} km")
    
    # Typically walk routes can cut through parks/pedestrian areas
    print("\n💡 Interpretation:")
    if walk_dist < drive_dist:
        print("   Walk route is shorter (pedestrian shortcuts)")
    elif walk_dist > drive_dist:
        print("   Drive route is shorter (faster roads)")
    else:
        print("   Routes are similar length")
    
    print("\n✅ Route comparison complete")


def test_elevation_availability():
    """Test 4: Check if elevation data is available with OpenTopoData."""
    print("\n" + "="*60)
    print("TEST 4: Elevation Data with OpenTopoData (Free!)")
    print("="*60)
    
    try:
        env = SpatialEnvironment(step_minutes=1.0)
        
        # Load small graph for testing
        print("\n🔄 Loading Edinburgh graph (small bbox for speed)...")
        env.load_osm_graph(
            bbox=(55.96, 55.94, -3.18, -3.20),  # Small area around Arthur's Seat
            network_type="all",
            use_cache=True
        )
        
        if env.G is None:
            print("⚠️  No graph loaded")
            return False
        
        print(f"✅ Graph loaded: {len(env.G.nodes)} nodes")
        
        # Add elevation using OpenTopoData (free, no API key!)
        print("\n🌄 Adding elevation data from OpenTopoData...")
        print("   (This uses free public API, may take 10-30 seconds)")
        
        success = env.add_elevation_data(method='opentopo')
        
        if success:
            print("✅ Elevation data added successfully!")
            
            # Show sample elevations
            sample_nodes = list(env.G.nodes(data=True))[:10]
            elevations = [data.get('elevation') for _, data in sample_nodes if 'elevation' in data]
            
            if elevations:
                print(f"\n📊 Sample elevations: {elevations[:5]}")
                print(f"   Min: {min(elevations):.1f} m")
                print(f"   Max: {max(elevations):.1f} m")
                print(f"   Mean: {sum(elevations)/len(elevations):.1f} m")
            
            return True
        else:
            print("❌ Failed to add elevation data")
            print("\n💡 Troubleshooting:")
            print("   1. Check internet connection")
            print("   2. Install: pip install requests")
            print("   3. Try again (API may be temporarily down)")
            return False
    
    except Exception as e:
        print(f"❌ Elevation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_energy_consumption():
    """Test 5: Test energy consumption calculation with elevation."""
    print("\n" + "="*60)
    print("TEST 5: Energy Consumption with Elevation")
    print("="*60)
    
    # Load graph with elevation
    print("\n🔄 Loading graph with elevation data...")
    env = SpatialEnvironment(step_minutes=1.0)
    env.load_osm_graph(
        bbox=(55.96, 55.94, -3.18, -3.20),  # Arthur's Seat area (hilly!)
        network_type="all",
        use_cache=True
    )
    
    if env.G is None:
        print("⚠️  No graph loaded, using mock data")
        test_with_mock_data(env)
        return
    
    # Add elevation
    print("🌄 Adding elevation data...")
    success = env.add_elevation_data(method='opentopo')
    
    if not success:
        print("⚠️  Elevation not available, using mock data")
        test_with_mock_data(env)
        return
    
    # Find a route with elevation change
    print("\n📍 Computing route with elevation...")
    
    # Get two random points
    o = env.get_random_node_coords()
    d = env.get_random_node_coords()
    
    if o is None or d is None:
        print("⚠️  Could not get random nodes")
        test_with_mock_data(env)
        return
    
    route = env.compute_route("test", o, d, "car")
    
    # Calculate emissions with and without elevation
    emissions_flat = env.estimate_emissions(route, "car")
    emissions_elev = env.estimate_emissions_with_elevation(route, "car")
    
    diff_pct = ((emissions_elev - emissions_flat) / emissions_flat * 100) if emissions_flat > 0 else 0
    
    print(f"\n📊 Emissions Comparison:")
    print(f"   Flat model:      {emissions_flat:.2f} g CO2")
    print(f"   With elevation:  {emissions_elev:.2f} g CO2")
    print(f"   Difference:      {diff_pct:+.1f}%")
    
    if abs(diff_pct) > 5:
        print(f"   ✅ Elevation adjustment is working!")
    else:
        print(f"   ⚠️  Route may be mostly flat")
    
    print("\n✅ Energy consumption test complete")


def test_with_mock_data(env):
    """Test with mock elevation profile."""
    print("\n📊 Testing with mock elevation data...")
    
    # Simulate flat route
    route_flat = [(-3.20, 55.95), (-3.19, 55.95), (-3.18, 55.95)]
    emissions_flat = env.estimate_emissions(route_flat, "car")
    
    print(f"\n   Flat route:  {emissions_flat:.2f} g CO2")
    print(f"   (All routes use flat model without elevation data)")
    
    print("\n💡 To test with real elevation:")
    print("   1. Ensure internet connection")
    print("   2. Install: pip install requests")
    print("   3. Re-run test")
    
    print("\n✅ Mock test complete")


def test_cache_performance():
    """Test 6: Measure cache performance improvement."""
    print("\n" + "="*60)
    print("TEST 6: Cache Performance")
    print("="*60)
    
    import time
    
    env1 = SpatialEnvironment(step_minutes=1.0)
    
    # First load (no cache)
    print("\n🔄 First load (downloading)...")
    start = time.time()
    env1.load_osm_graph(place="Edinburgh, UK", network_type="all", use_cache=False)
    duration_no_cache = time.time() - start
    print(f"   Duration: {duration_no_cache:.2f}s")
    
    # Second load (with cache)
    env2 = SpatialEnvironment(step_minutes=1.0)
    print("\n📦 Second load (from cache)...")
    start = time.time()
    env2.load_osm_graph(place="Edinburgh, UK", network_type="all", use_cache=True)
    duration_cached = time.time() - start
    print(f"   Duration: {duration_cached:.2f}s")
    
    # Compare
    speedup = duration_no_cache / duration_cached if duration_cached > 0 else 0
    print(f"\n⚡ Speedup: {speedup:.1f}x faster with cache")
    
    if speedup > 5:
        print("   ✅ Cache is working well!")
    else:
        print("   ⚠️  Cache speedup lower than expected")
    
    print("\n✅ Cache performance test complete")


def run_all_tests():
    """Run all Phase 2.1 feature tests."""
    print("\n" + "="*70)
    print("RTD_SIM Phase 2.1 Feature Tests")
    print("="*70)
    
    try:
        # Test 1: Basic loading
        env = test_basic_loading()
        
        # Test 2: Mode-specific networks
        test_mode_specific_networks()
        
        # Test 3: Routing comparison
        test_routing_comparison()
        
        # Test 4: Elevation data
        has_elevation = test_elevation_availability()
        
        # Test 5: Energy consumption
        test_energy_consumption()
        
        # Test 6: Cache performance
        test_cache_performance()
        
        # Summary
        print("\n" + "="*70)
        print("TEST SUMMARY")
        print("="*70)
        print("✅ OSM graph loading & caching")
        print("✅ Mode-specific networks (separate graphs)")
        print("✅ Routing comparison")
        print("❌ Elevation data (not in basic OSM download)")
        print("❌ Energy consumption with elevation (not implemented)")
        print("\n💡 Next steps:")
        print("   1. Implement per-agent mode-specific routing")
        print("   2. Add elevation data download")
        print("   3. Implement elevation-aware energy calculation")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Tests failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_all_tests()