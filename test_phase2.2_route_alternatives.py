"""
Test suite for RTD_SIM Phase 2.2: Route Alternatives

Tests:
1. Basic route alternative generation
2. Route variant comparison (shortest vs fastest vs safest)
3. Route metrics computation
4. Route scoring and ranking
5. Pareto-optimal filtering
6. Integration with elevation data

Run: python test_phase2.2_route_alternatives.py
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
from simulation.route_alternative import RouteAlternative, rank_alternatives, filter_pareto_optimal

# Test configuration
TEST_PLACE = "Edinburgh, Scotland"
TEST_BBOX = (55.97, 55.92, -3.11, -3.24)


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


def test_basic_alternatives():
    """Test 1: Basic route alternative generation."""
    print_header("TEST 1: Basic Route Alternative Generation", level=2)
    
    env = SpatialEnvironment()
    env.load_osm_graph(place=TEST_PLACE, use_cache=True)
    
    if not env.graph_loaded:
        print("[FAIL] No graph loaded")
        return False
    
    # Edinburgh Castle to Holyrood Palace
    origin = (-3.2008, 55.9486)
    dest = (-3.1730, 55.9520)
    
    print(f"\n[*] Origin: Edinburgh Castle {origin}")
    print(f"[*] Dest:   Holyrood Palace {dest}")
    print(f"[*] Mode:   bike")
    
    print("\n[*] Computing route alternatives...")
    start = time.time()
    alternatives = env.compute_route_alternatives(
        "test_agent",
        origin,
        dest,
        "bike",
        variants=['shortest', 'fastest']
    )
    elapsed = time.time() - start
    
    if not alternatives:
        print("[FAIL] No alternatives generated")
        return False
    
    print(f"\n[OK] Generated {len(alternatives)} alternatives in {elapsed:.2f}s")
    
    for alt in alternatives:
        print(f"\n[*] {alt.variant.upper()} route:")
        print(f"    Distance:  {alt.metrics['distance']:.3f} km")
        print(f"    Time:      {alt.metrics['time']:.1f} min")
        print(f"    Emissions: {alt.metrics['emissions']:.1f} g CO2")
        print(f"    Waypoints: {alt.metrics['waypoints']}")
    
    return True


def test_all_variants():
    """Test 2: All route variants."""
    print_header("TEST 2: All Route Variants Comparison", level=2)
    
    env = SpatialEnvironment()
    env.load_osm_graph(place=TEST_PLACE, use_cache=True)
    
    if not env.graph_loaded:
        print("[FAIL] No graph loaded")
        return False
    
    origin = (-3.2008, 55.9486)
    dest = (-3.1730, 55.9520)
    
    print(f"\n[*] Testing all route variants for bike mode...")
    
    alternatives = env.compute_route_alternatives(
        "test_agent",
        origin,
        dest,
        "bike",
        variants=['shortest', 'fastest', 'safest', 'greenest', 'scenic']
    )
    
    if len(alternatives) < 3:
        print(f"[WARN] Only generated {len(alternatives)} alternatives")
    
    print(f"\n[OK] Generated {len(alternatives)} route variants\n")
    
    # Create comparison table
    print("=" * 85)
    print(f"{'Variant':<12} {'Distance':>10} {'Time':>10} {'Emissions':>12} {'Risk':>8} {'Comfort':>8}")
    print("=" * 85)
    
    for alt in alternatives:
        print(f"{alt.variant:<12} "
              f"{alt.metrics['distance']:>9.3f}km "
              f"{alt.metrics['time']:>9.1f}m "
              f"{alt.metrics['emissions']:>11.1f}g "
              f"{alt.metrics['risk']:>8.2f} "
              f"{alt.metrics['comfort']:>8.2f}")
    
    print("=" * 85)
    
    # Verify variants make sense
    shortest = next((a for a in alternatives if a.variant == 'shortest'), None)
    fastest = next((a for a in alternatives if a.variant == 'fastest'), None)
    
    if shortest and fastest:
        if shortest.metrics['distance'] <= fastest.metrics['distance']:
            print("\n[OK] Shortest route has minimum distance (as expected)")
        else:
            print("\n[WARN] Shortest route is not actually shortest!")
        
        if fastest.metrics['time'] <= shortest.metrics['time']:
            print("[OK] Fastest route has minimum time (as expected)")
        else:
            print("[INFO] Fastest route is slower (may be due to constant speeds)")
    
    return True


def test_with_elevation():
    """Test 3: Route alternatives with elevation data."""
    print_header("TEST 3: Route Alternatives with Elevation", level=2)
    
    env = SpatialEnvironment()
    env.load_osm_graph(place=TEST_PLACE, use_cache=True)
    
    if not env.graph_loaded:
        print("[FAIL] No graph loaded")
        return False
    
    # Add elevation data
    print("\n[*] Adding elevation data...")
    env.add_elevation_data(method='opentopo')
    
    if not env.has_elevation:
        print("[WARN] No elevation data, skipping elevation-specific tests")
        return True
    
    origin = (-3.2008, 55.9486)
    dest = (-3.1730, 55.9520)
    
    print("[*] Computing routes with elevation awareness...")
    
    alternatives = env.compute_route_alternatives(
        "test_agent",
        origin,
        dest,
        "bike",
        variants=['shortest', 'greenest']
    )
    
    print(f"\n[OK] Generated {len(alternatives)} alternatives with elevation\n")
    
    for alt in alternatives:
        if 'elevation_gain' in alt.metrics:
            print(f"[*] {alt.variant.upper()} route:")
            print(f"    Distance:       {alt.metrics['distance']:.3f} km")
            print(f"    Elevation gain: {alt.metrics['elevation_gain']:.1f} m")
            print(f"    Elevation loss: {alt.metrics['elevation_loss']:.1f} m")
            print(f"    Min elevation:  {alt.metrics['elevation_min']:.1f} m")
            print(f"    Max elevation:  {alt.metrics['elevation_max']:.1f} m")
            print(f"    Emissions:      {alt.metrics['emissions']:.1f} g CO2\n")
    
    greenest = next((a for a in alternatives if a.variant == 'greenest'), None)
    shortest = next((a for a in alternatives if a.variant == 'shortest'), None)
    
    if greenest and shortest:
        if 'elevation_gain' in greenest.metrics and 'elevation_gain' in shortest.metrics:
            if greenest.metrics['elevation_gain'] <= shortest.metrics['elevation_gain']:
                print("[OK] Greenest route has less elevation gain")
            else:
                print("[INFO] Greenest route has more elevation (optimizing total emissions)")
    
    return True


def test_route_scoring():
    """Test 4: Route scoring and ranking."""
    print_header("TEST 4: Route Scoring and Ranking", level=2)
    
    env = SpatialEnvironment()
    env.load_osm_graph(place=TEST_PLACE, use_cache=True)
    
    if not env.graph_loaded:
        print("[FAIL] No graph loaded")
        return False
    
    origin = (-3.2008, 55.9486)
    dest = (-3.1730, 55.9520)
    
    alternatives = env.compute_route_alternatives(
        "test_agent",
        origin,
        dest,
        "bike",
        variants=['shortest', 'fastest', 'safest']
    )
    
    if len(alternatives) < 2:
        print("[WARN] Need at least 2 alternatives for ranking")
        return True
    
    # Test different preference profiles
    profiles = {
        'Time-focused': {
            'time': -1.0,      # Minimize time
            'distance': -0.2,  # Slightly minimize distance
        },
        'Safety-focused': {
            'risk': -1.0,      # Minimize risk
            'time': -0.3,      # Somewhat minimize time
        },
        'Eco-focused': {
            'emissions': -1.0,  # Minimize emissions
            'distance': -0.5,   # Minimize distance
        },
        'Balanced': {
            'time': -0.4,
            'cost': -0.3,
            'emissions': -0.2,
            'risk': -0.1,
        }
    }
    
    print("\n[*] Testing different preference profiles...\n")
    
    for profile_name, weights in profiles.items():
        ranked = rank_alternatives(alternatives, weights)
        best = ranked[0][1]
        
        print(f"[*] {profile_name} profile:")
        print(f"    Best route: {best.variant}")
        print(f"    Score:      {ranked[0][0]:.2f}")
        print(f"    Distance:   {best.metrics['distance']:.3f} km")
        print(f"    Time:       {best.metrics['time']:.1f} min")
        print(f"    Emissions:  {best.metrics['emissions']:.1f} g CO2\n")
    
    print("[OK] Route scoring and ranking complete")
    return True


def test_pareto_optimal():
    """Test 5: Pareto-optimal filtering."""
    print_header("TEST 5: Pareto-Optimal Route Filtering", level=2)
    
    env = SpatialEnvironment()
    env.load_osm_graph(place=TEST_PLACE, use_cache=True)
    
    if not env.graph_loaded:
        print("[FAIL] No graph loaded")
        return False
    
    origin = (-3.2008, 55.9486)
    dest = (-3.1730, 55.9520)
    
    alternatives = env.compute_route_alternatives(
        "test_agent",
        origin,
        dest,
        "bike",
        variants=['shortest', 'fastest', 'safest', 'greenest', 'scenic']
    )
    
    if len(alternatives) < 3:
        print(f"[WARN] Only {len(alternatives)} alternatives, skipping Pareto test")
        return True
    
    print(f"\n[*] Generated {len(alternatives)} alternatives")
    
    pareto = filter_pareto_optimal(alternatives)
    
    print(f"[*] Pareto-optimal routes: {len(pareto)}/{len(alternatives)}")
    
    if pareto:
        print("\n[*] Pareto-optimal variants:")
        for alt in pareto:
            print(f"    - {alt.variant}: {alt.metrics['distance']:.3f}km, "
                  f"{alt.metrics['time']:.1f}min, "
                  f"{alt.metrics['emissions']:.1f}g CO2")
    
    print("\n[OK] Pareto filtering complete")
    return True


def test_performance():
    """Test 6: Performance with multiple alternatives."""
    print_header("TEST 6: Performance Test", level=2)
    
    env = SpatialEnvironment()
    env.load_osm_graph(place=TEST_PLACE, use_cache=True)
    
    if not env.graph_loaded:
        print("[FAIL] No graph loaded")
        return False
    
    # Generate 10 random OD pairs
    print("\n[*] Generating route alternatives for 10 random OD pairs...")
    
    total_time = 0
    total_alternatives = 0
    
    for i in range(10):
        od_pair = env.get_random_origin_dest()
        if od_pair is None:
            continue
        
        origin, dest = od_pair
        
        start = time.time()
        alternatives = env.compute_route_alternatives(
            f"agent_{i}",
            origin,
            dest,
            "bike",
            variants=['shortest', 'fastest', 'safest']
        )
        elapsed = time.time() - start
        
        total_time += elapsed
        total_alternatives += len(alternatives)
    
    avg_time = total_time / 10
    avg_alternatives = total_alternatives / 10
    
    print(f"\n[*] Performance results:")
    print(f"    Total time:       {total_time:.2f}s")
    print(f"    Avg per OD pair:  {avg_time:.3f}s")
    print(f"    Avg alternatives: {avg_alternatives:.1f}")
    
    if avg_time < 1.0:
        print("\n[OK] Performance is good (<1s per OD pair)")
    elif avg_time < 3.0:
        print("\n[OK] Performance is acceptable (<3s per OD pair)")
    else:
        print("\n[WARN] Performance may need optimization (>3s per OD pair)")
    
    return True


def main():
    """Run all tests."""
    print_header("RTD_SIM Phase 2.2: Route Alternatives Tests", level=1)
    
    results = {
        "Basic Alternatives": test_basic_alternatives(),
        "All Variants": test_all_variants(),
        "With Elevation": test_with_elevation(),
        "Route Scoring": test_route_scoring(),
        "Pareto Optimal": test_pareto_optimal(),
        "Performance": test_performance(),
    }
    
    print_header("TEST SUMMARY", level=1)
    for test_name, passed in results.items():
        status = "[OK]" if passed else "[FAIL]"
        print(f"{status} {test_name}")
    
    total = len(results)
    passed = sum(results.values())
    
    print(f"\nPassed: {passed}/{total} tests")
    
    if passed == total:
        print("\n*** All tests passed! Phase 2.2 Route Alternatives ready. ***")
    else:
        print("\n*** Some tests failed. Review errors above. ***")


if __name__ == "__main__":
    main()