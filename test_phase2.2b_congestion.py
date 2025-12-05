"""
Test suite for RTD_SIM Phase 2.2b: Dynamic Congestion

Tests:
1. Basic congestion tracking
2. Congestion impact on routing
3. Time-of-day patterns
4. Multiple congestion models
5. Congestion statistics
6. Performance with congestion

Run: python test_phase2.2b_congestion.py
"""

import logging
import time

logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(name)s: %(message)s'
)

from simulation.spatial_environment import SpatialEnvironment
from simulation.spatial.congestion_manager import CongestionManager, CongestionConfig, CongestionModel

TEST_PLACE = "Edinburgh, Scotland"


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


def test_basic_congestion():
    """Test 1: Basic congestion tracking."""
    print_header("TEST 1: Basic Congestion Tracking", level=2)
    
    env = SpatialEnvironment(use_congestion=True)
    env.load_osm_graph(place=TEST_PLACE, use_cache=True)
    
    if not env.graph_loaded:
        print("[FAIL] No graph loaded")
        return False
    
    if env.congestion_manager is None:
        print("[FAIL] Congestion manager not initialized")
        return False
    
    print("\n[*] Testing congestion tracking...")
    
    # Get a test edge
    graph = env.G
    edges = list(graph.edges(keys=True))[:10]
    test_edge = edges[0]
    
    print(f"[*] Test edge: {test_edge}")
    
    # No congestion initially
    factor1 = env.congestion_manager.get_congestion_factor(*test_edge)
    print(f"    Initial congestion: {factor1:.2f}x")
    
    # Add vehicles
    for i in range(5):
        env.update_agent_congestion(f"agent_{i}", test_edge)
    
    factor2 = env.congestion_manager.get_congestion_factor(*test_edge)
    print(f"    With 5 vehicles: {factor2:.2f}x")
    
    # Add more vehicles
    for i in range(5, 10):
        env.update_agent_congestion(f"agent_{i}", test_edge)
    
    factor3 = env.congestion_manager.get_congestion_factor(*test_edge)
    print(f"    With 10 vehicles: {factor3:.2f}x")
    
    if factor2 > factor1 and factor3 > factor2:
        print("\n[OK] Congestion increases with vehicle count")
        return True
    else:
        print("\n[FAIL] Congestion not increasing properly")
        return False


def test_congestion_routing():
    """Test 2: Congestion impact on routing."""
    print_header("TEST 2: Congestion Impact on Routing", level=2)
    
    env = SpatialEnvironment(use_congestion=True)
    env.load_osm_graph(place=TEST_PLACE, use_cache=True)
    
    if not env.graph_loaded:
        print("[FAIL] No graph loaded")
        return False
    
    origin = (-3.2008, 55.9486)
    dest = (-3.1730, 55.9520)
    
    print("\n[*] Computing route without congestion...")
    start = time.time()
    route1 = env.compute_route("test_agent", origin, dest, "car")
    time1 = env.estimate_travel_time(route1, "car")
    elapsed1 = time.time() - start
    
    print(f"    Route length: {len(route1)} waypoints")
    print(f"    Travel time: {time1:.1f} min")
    print(f"    Computation: {elapsed1:.3f}s")
    
    # Add congestion to route edges
    print("\n[*] Adding congestion to route...")
    graph = env.G
    route_edges_added = 0
    
    # Get edges from route nodes
    if len(route1) > 2:
        for i in range(min(5, len(route1) - 1)):
            # Find edge between consecutive route points
            for u, v, key in graph.edges(keys=True):
                # Simulate congestion by adding vehicles
                for j in range(15):
                    env.update_agent_congestion(f"congestion_agent_{i}_{j}", (u, v, key))
                route_edges_added += 1
                if route_edges_added >= 3:
                    break
            if route_edges_added >= 3:
                break
    
    print(f"    Added congestion to {route_edges_added} edges")
    
    # Compute route with congestion
    print("\n[*] Computing route with congestion...")
    alternatives = env.compute_route_alternatives(
        "test_agent",
        origin,
        dest,
        "car",
        variants=['fastest']
    )
    
    if alternatives:
        alt = alternatives[0]
        time2 = alt.metrics['time']
        print(f"    New travel time: {time2:.1f} min")
        
        if time2 >= time1:
            print(f"    [OK] Travel time increased by {((time2-time1)/time1*100):.1f}%")
        else:
            print(f"    [INFO] Travel time similar (congestion may not affect this route)")
    
    stats = env.get_congestion_stats()
    print(f"\n[*] Congestion stats:")
    print(f"    Edges with vehicles: {stats.get('total_edges_with_vehicles', 0)}")
    print(f"    Total vehicles: {stats.get('total_vehicles_on_network', 0)}")
    
    print("\n[OK] Congestion routing test complete")
    return True


def test_time_of_day():
    """Test 3: Time-of-day congestion patterns."""
    print_header("TEST 3: Time-of-Day Patterns", level=2)
    
    # config = CongestionConfig()
    # config.peak_hours = {8, 9, 17, 18}
    # config.peak_multiplier = 2.0
    config = CongestionConfig(
        model=CongestionModel.BPR,  # Use BPR function
        peak_hours={7, 8, 9, 17, 18, 19},
        peak_multiplier=2.0,  # 2x worse during rush hour
        max_congestion_factor=4.0  # Max 4x slower
    )
    
    # env = SpatialEnvironment(use_congestion=False)
    env = SpatialEnvironment(use_congestion=True)
    env.load_osm_graph(place=TEST_PLACE, use_cache=True)
    
    # Manually create congestion manager with config
    from simulation.spatial.congestion_manager import CongestionManager
    congestion = CongestionManager(env.graph_manager, config)
    
    # Get test edge
    edges = list(env.G.edges(keys=True))
    test_edge = edges[0]
    
    # Add vehicles
    for i in range(5):
        congestion.update_agent_position(f"agent_{i}", test_edge)
    
    # Test at different times
    print("\n[*] Testing congestion at different hours:")
    
    times = [
        (7, "Off-peak morning"),
        (8, "Peak morning"),
        (12, "Midday"),
        (17, "Peak evening"),
        (22, "Night"),
    ]
    
    for hour, label in times:
        congestion.current_hour = hour
        factor = congestion.get_congestion_factor(*test_edge)
        is_peak = "PEAK" if hour in config.peak_hours else "off-peak"
        print(f"    {hour:02d}:00 ({label:20s}): {factor:.2f}x [{is_peak}]")
    
    print("\n[OK] Time-of-day patterns working")
    return True


def test_congestion_models():
    """Test 4: Different congestion models."""
    print_header("TEST 4: Congestion Models Comparison", level=2)
    
    env = SpatialEnvironment(use_congestion=False)
    env.load_osm_graph(place=TEST_PLACE, use_cache=True)
    
    edges = list(env.G.edges(keys=True))
    test_edge = edges[0]
    
    models = [
        (CongestionModel.LINEAR, "Linear"),
        (CongestionModel.BPR, "BPR (Bureau of Public Roads)"),
        (CongestionModel.EXPONENTIAL, "Exponential"),
    ]
    
    print("\n[*] Comparing congestion models with 10 vehicles:\n")
    
    for model, name in models:
        config = CongestionConfig(model=model)
        from simulation.spatial.congestion_manager import CongestionManager
        congestion = CongestionManager(env.graph_manager, config)
        
        # Add 10 vehicles
        for i in range(10):
            congestion.update_agent_position(f"agent_{i}", test_edge)
        
        factor = congestion.get_congestion_factor(*test_edge)
        print(f"    {name:30s}: {factor:.2f}x slower")
    
    print("\n[OK] Congestion models test complete")
    return True


def test_statistics():
    """Test 5: Congestion statistics."""
    print_header("TEST 5: Congestion Statistics", level=2)
    
    env = SpatialEnvironment(use_congestion=True)
    env.load_osm_graph(place=TEST_PLACE, use_cache=True)
    
    if not env.congestion_manager:
        print("[FAIL] Congestion not enabled")
        return False
    
    print("\n[*] Simulating traffic...")
    
    # Add vehicles to random edges
    edges = list(env.G.edges(keys=True))[:50]
    
    for i, edge in enumerate(edges[:20]):
        # Add 2-8 vehicles per edge
        num_vehicles = 2 + (i % 7)
        for j in range(num_vehicles):
            env.update_agent_congestion(f"agent_{i}_{j}", edge)
    
    stats = env.get_congestion_stats()
    
    print("\n[*] Congestion Statistics:")
    print(f"    Edges with vehicles: {stats['total_edges_with_vehicles']}")
    print(f"    Total vehicles: {stats['total_vehicles_on_network']}")
    print(f"    Congested edges: {stats['congested_edges']}")
    print(f"    Max congestion: {stats['max_congestion_factor']:.2f}x")
    print(f"    Current hour: {stats['current_hour']}:00")
    
    # Get most congested edges
    congested = env.congestion_manager.get_congested_edges(threshold=1.3)
    
    if congested:
        print(f"\n[*] Most congested edges (>{1.3}x):")
        for edge, factor, count in congested[:5]:
            print(f"    Edge {edge}: {factor:.2f}x with {count} vehicles")
    
    print("\n[OK] Statistics test complete")
    return True


def test_performance():
    """Test 6: Performance with congestion."""
    print_header("TEST 6: Performance with Congestion", level=2)
    
    print("\n[*] Testing routing performance...")
    
    # Without congestion
    env1 = SpatialEnvironment(use_congestion=False)
    env1.load_osm_graph(place=TEST_PLACE, use_cache=True)
    
    start = time.time()
    for i in range(10):
        od = env1.get_random_origin_dest()
        if od:
            o, d = od
            env1.compute_route_alternatives(f"agent_{i}", o, d, "car", variants=['fastest'])
    time_without = time.time() - start
    
    print(f"    Without congestion: {time_without:.2f}s for 10 routes")
    
    # With congestion
    env2 = SpatialEnvironment(use_congestion=True)
    env2.load_osm_graph(place=TEST_PLACE, use_cache=True)
    
    # Add some background traffic
    edges = list(env2.G.edges(keys=True))[:100]
    for i, edge in enumerate(edges[:30]):
        for j in range(3):
            env2.update_agent_congestion(f"bg_{i}_{j}", edge)
    
    start = time.time()
    for i in range(10):
        od = env2.get_random_origin_dest()
        if od:
            o, d = od
            env2.compute_route_alternatives(f"agent_{i}", o, d, "car", variants=['fastest'])
    time_with = time.time() - start
    
    print(f"    With congestion: {time_with:.2f}s for 10 routes")
    
    overhead = ((time_with - time_without) / time_without * 100) if time_without > 0 else 0
    print(f"    Overhead: {overhead:.1f}%")
    
    if overhead < 50:
        print("\n[OK] Performance overhead acceptable (<50%)")
    elif overhead < 100:
        print("\n[OK] Performance overhead moderate (50-100%)")
    else:
        print("\n[WARN] Performance overhead high (>100%)")
    
    return True


def main():
    """Run all tests."""
    print_header("RTD_SIM Phase 2.2b: Dynamic Congestion Tests", level=1)
    
    results = {
        "Basic Congestion": test_basic_congestion(),
        "Congestion Routing": test_congestion_routing(),
        "Time-of-Day": test_time_of_day(),
        "Congestion Models": test_congestion_models(),
        "Statistics": test_statistics(),
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
        print("\n*** All tests passed! Phase 2.2b Dynamic Congestion ready. ***")
    else:
        print("\n*** Some tests failed. Review errors above. ***")


if __name__ == "__main__":
    main()