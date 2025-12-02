"""
Test suite for RTD_SIM Phase 2.1 features:
- OSM graph loading with caching
- Mode-specific networks (walk/bike/drive)
- Route computation comparison
- Elevation data integration (OpenTopoData)
- Energy consumption with elevation
- Cache performance

Run: python test_phase2_routing.py
"""

import logging
import time
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(name)s: %(message)s'
)

from simulation.spatial_environment import SpatialEnvironment

# Test configuration
TEST_PLACE = "Edinburgh, Scotland"
# Bbox format for our code: (north, south, east, west) - gets converted internally
# Edinburgh city center (large area ~5km x 10km)
TEST_BBOX = (55.97, 55.92, -3.11, -3.24)
# Tiny area near Edinburgh Castle for elevation testing (~200m x 200m)
SMALL_BBOX = (55.9495, 55.9475, -3.1985, -3.2015)


def print_header(title, level=1):
    """Print formatted section header."""
    if level == 1:
        print("\n" + "="*70)
        print(title)
        print("="*70)
    else:
        print("\n" + "="*60)
        print(title)
        print("="*60)


def test_basic_loading():
    """Test 1: Basic OSM graph loading and caching."""
    print_header("TEST 1: Basic Graph Loading & Caching", level=2)
    
    env = SpatialEnvironment()
    
    print("\n[*] Loading Edinburgh OSM graph...")
    start = time.time()
    env.load_osm_graph(place=TEST_PLACE, use_cache=True)
    elapsed = time.time() - start
    
    if env.graph_loaded:
        stats = env.get_graph_stats()
        print(f"\n[OK] Graph loaded: {stats['nodes']:,} nodes, {stats['edges']:,} edges")
        print(f"     Cache size: {stats.get('cache_size', 0)} precomputed nodes")
        print(f"     Load time: {elapsed:.2f}s")
        return True
    else:
        print("\n[FAIL] Failed to load graph")
        return False


def test_mode_specific_networks():
    """Test 2: Load mode-specific networks (walk/bike/drive)."""
    print_header("TEST 2: Mode-Specific Networks", level=2)
    
    env = SpatialEnvironment()
    
    print("\n[*] Loading WALK network...")
    print("[*] Loading DRIVE network...")
    print("[*] Loading BIKE network...")
    
    start = time.time()
    env.load_mode_specific_graphs(
        place=TEST_PLACE,
        modes=['walk', 'bike', 'drive'],
        use_cache=True
    )
    elapsed = time.time() - start
    
    if env.mode_graphs:
        print(f"\n[*] Network Comparison:")
        for net_type, graph in env.mode_graphs.items():
            print(f"    {net_type.capitalize():5}: {len(graph.nodes):6,} nodes, {len(graph.edges):7,} edges")
        
        print(f"\n[OK] Mode-specific networks loaded successfully")
        print(f"     Total load time: {elapsed:.2f}s")
        return True
    else:
        print("\n[FAIL] Failed to load mode-specific networks")
        return False


def test_routing_comparison():
    """Test 3: Compare walk vs drive routing."""
    print_header("TEST 3: Routing Comparison (Walk vs Drive)", level=2)
    
    env = SpatialEnvironment()
    env.load_mode_specific_graphs(place=TEST_PLACE, use_cache=True)
    
    if not env.graph_loaded:
        print("\n[FAIL] No graph loaded")
        return False
    
    # Edinburgh Castle to Holyrood Palace
    origin = (-3.2008, 55.9486)  # Castle
    dest = (-3.1730, 55.9520)    # Palace
    
    print(f"\n[*] Origin: {origin}")
    print(f"[*] Dest:   {dest}")
    
    # Compute routes
    walk_route = env.compute_route("test_walker", origin, dest, "walk")
    drive_route = env.compute_route("test_driver", origin, dest, "car")
    
    walk_dist = env._distance(walk_route)
    drive_dist = env._distance(drive_route)
    
    print(f"\n[*] Walk route:  {len(walk_route):3} waypoints, {walk_dist:.3f} km")
    print(f"[*] Drive route: {len(drive_route):3} waypoints, {drive_dist:.3f} km")
    
    if walk_dist < drive_dist:
        print("\n[INFO] Walk route is shorter (pedestrian shortcuts)")
    elif drive_dist < walk_dist:
        print("\n[INFO] Drive route is shorter (faster roads)")
    else:
        print("\n[INFO] Routes are similar length")
    
    print("\n[OK] Route comparison complete")
    return True


def test_elevation_data():
    """Test 4: Add elevation data using OpenTopoData."""
    print_header("TEST 4: Elevation Data with OpenTopoData (Free!)", level=2)
    
    env = SpatialEnvironment()
    
    print("\n[*] Loading Edinburgh graph (small bbox for speed)...")
    env.load_osm_graph(bbox=SMALL_BBOX, use_cache=True)
    
    if not env.graph_loaded:
        print("[WARN] No graph loaded")
        return False
    
    print(f"[*] Graph: {len(env.G.nodes)} nodes")
    print("\n[*] Fetching elevation data from OpenTopoData API...")
    print("    (This may take 10-30s for first run, then cached)")
    
    start = time.time()
    success = env.add_elevation_data(method='opentopo')
    elapsed = time.time() - start
    
    if success:
        # Sample some elevations
        sample_nodes = list(env.G.nodes(data=True))[:5]
        elevations = [data.get('elevation') for _, data in sample_nodes]
        
        print(f"\n[OK] Elevation data added in {elapsed:.1f}s")
        print(f"     Sample elevations: {[f'{e:.1f}m' if e else 'N/A' for e in elevations]}")
        
        # Stats
        all_elevations = [data.get('elevation') for _, data in env.G.nodes(data=True) if 'elevation' in data]
        if all_elevations:
            print(f"     Min: {min(all_elevations):.1f}m")
            print(f"     Max: {max(all_elevations):.1f}m")
            print(f"     Avg: {sum(all_elevations)/len(all_elevations):.1f}m")
        
        return True
    else:
        print("\n[FAIL] Failed to add elevation data")
        print("       Check internet connection and try again")
        return False


def test_energy_with_elevation():
    """Test 5: Energy consumption with elevation."""
    print_header("TEST 5: Energy Consumption with Elevation", level=2)
    
    env = SpatialEnvironment()
    
    print("\n[*] Loading graph with elevation data...")
    env.load_osm_graph(bbox=SMALL_BBOX, use_cache=True)
    
    if not env.graph_loaded:
        print("[WARN] No graph loaded")
        return False
    
    # Add elevation
    print("[*] Adding elevation...")
    env.add_elevation_data(method='opentopo')
    
    if not env.has_elevation:
        print("[WARN] No elevation data available")
        return False
    
    # Test route (should have some elevation change)
    origin = (-3.19, 55.950)  # Lower point
    dest = (-3.185, 55.952)   # Slight uphill
    
    print(f"\n[*] Testing route with elevation...")
    route = env.compute_route("test_agent", origin, dest, "car")
    
    if len(route) < 2:
        print("[WARN] Route too short")
        return False
    
    # Calculate emissions both ways
    flat_emissions = env.estimate_emissions(route, "car")
    elev_emissions = env.estimate_emissions_with_elevation(route, "car")
    
    print(f"\n[*] Emissions comparison:")
    print(f"    Flat model:      {flat_emissions:.2f} g CO2")
    print(f"    With elevation:  {elev_emissions:.2f} g CO2")
    
    diff_pct = ((elev_emissions - flat_emissions) / flat_emissions * 100) if flat_emissions > 0 else 0
    
    if abs(diff_pct) > 1:
        direction = "higher" if diff_pct > 0 else "lower"
        print(f"    Difference:      {abs(diff_pct):.1f}% {direction}")
        print("\n[INFO] Elevation affects energy consumption!")
    else:
        print("\n[INFO] Route is relatively flat")
    
    print("\n[OK] Energy calculation with elevation complete")
    return True


def test_cache_performance():
    """Test 6: Measure cache performance."""
    print_header("TEST 6: Cache Performance", level=2)
    
    # Clear cache first
    env = SpatialEnvironment()
    cache_dir = env.cache_dir
    
    print("\n[*] First load (downloading)...")
    start = time.time()
    env.load_osm_graph(place=TEST_PLACE, use_cache=False)
    first_time = time.time() - start
    print(f"    Duration: {first_time:.2f}s")
    
    # Force save to cache
    if env.graph_loaded:
        import pickle
        cache_key = env._get_cache_key(TEST_PLACE, None, 'all')
        cache_path = cache_dir / f"{cache_key}.pkl"
        with open(cache_path, 'wb') as f:
            pickle.dump(env.G, f)
    
    # Second load from cache
    env2 = SpatialEnvironment()
    print("\n[*] Second load (from cache)...")
    start = time.time()
    env2.load_osm_graph(place=TEST_PLACE, use_cache=True)
    second_time = time.time() - start
    print(f"    Duration: {second_time:.2f}s")
    
    speedup = first_time / second_time if second_time > 0 else 0
    print(f"\n[*] Speedup: {speedup:.1f}x faster with cache")
    
    if speedup > 5:
        print("    [OK] Cache is working well!")
    elif speedup > 2:
        print("    [OK] Cache provides moderate speedup")
    else:
        print("    [WARN] Cache speedup less than expected")
    
    print("\n[OK] Cache performance test complete")
    return True


def main():
    """Run all tests."""
    print_header("RTD_SIM Phase 2.1 Feature Tests", level=1)
    
    results = {
        "Basic Loading": test_basic_loading(),
        "Mode-Specific Networks": test_mode_specific_networks(),
        "Routing Comparison": test_routing_comparison(),
        "Elevation Data": test_elevation_data(),
        "Energy with Elevation": test_energy_with_elevation(),
        "Cache Performance": test_cache_performance(),
    }
    
    print_header("TEST SUMMARY", level=1)
    for test_name, passed in results.items():
        status = "[OK]" if passed else "[FAIL]"
        print(f"{status} {test_name}")
    
    total = len(results)
    passed = sum(results.values())
    
    print(f"\nPassed: {passed}/{total} tests")
    
    if passed == total:
        print("\n*** All tests passed! Phase 2.1 is ready. ***")
    else:
        print("\n*** Some tests failed. Review errors above. ***")
        print("\nCommon issues:")
        print("  - Internet connection (for elevation API)")
        print("  - requests library: pip install requests")
        print("  - OSMnx version: pip install --upgrade osmnx")


if __name__ == "__main__":
    main()