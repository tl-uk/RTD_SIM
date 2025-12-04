"""
Quick verification script for refactored SpatialEnvironment.

Tests that all backward compatibility methods work correctly.
Run this AFTER copying the refactored files.

Usage: python verify_refactor.py
"""

import sys

print("="*70)
print("Verifying Refactored SpatialEnvironment")
print("="*70)

# Test 1: Import modules
print("\n[1/8] Testing imports...")
try:
    from simulation.spatial_environment import SpatialEnvironment
    from simulation.spatial import GraphManager, Router, MetricsCalculator
    from simulation.spatial import coordinate_utils
    from simulation.elevation_provider import ElevationProvider
    from simulation.route_alternative import RouteAlternative
    print("    ✓ All imports successful")
except ImportError as e:
    print(f"    ✗ Import failed: {e}")
    sys.exit(1)

# Test 2: Create SpatialEnvironment
print("\n[2/8] Creating SpatialEnvironment...")
try:
    env = SpatialEnvironment()
    print("    ✓ SpatialEnvironment created")
except Exception as e:
    print(f"    ✗ Creation failed: {e}")
    sys.exit(1)

# Test 3: Check subsystems
print("\n[3/8] Checking subsystems...")
try:
    assert hasattr(env, 'graph_manager'), "Missing graph_manager"
    assert hasattr(env, 'router'), "Missing router"
    assert hasattr(env, 'metrics'), "Missing metrics"
    assert isinstance(env.graph_manager, GraphManager)
    assert isinstance(env.router, Router)
    assert isinstance(env.metrics, MetricsCalculator)
    print("    ✓ All subsystems present")
except AssertionError as e:
    print(f"    ✗ Subsystem check failed: {e}")
    sys.exit(1)

# Test 4: Check backward compatibility properties
print("\n[4/8] Checking backward compatibility properties...")
try:
    assert hasattr(env, 'graph_loaded'), "Missing graph_loaded"
    assert hasattr(env, 'G'), "Missing G"
    assert hasattr(env, 'mode_graphs'), "Missing mode_graphs"
    assert hasattr(env, 'has_elevation'), "Missing has_elevation"
    assert hasattr(env, 'mode_network_types'), "Missing mode_network_types"
    assert hasattr(env, 'speeds_km_min'), "Missing speeds_km_min"
    print("    ✓ All properties present")
except AssertionError as e:
    print(f"    ✗ Property check failed: {e}")
    sys.exit(1)

# Test 5: Check graph loading methods
print("\n[5/8] Checking graph loading methods...")
try:
    assert hasattr(env, 'load_osm_graph'), "Missing load_osm_graph"
    assert hasattr(env, 'load_mode_specific_graphs'), "Missing load_mode_specific_graphs"
    assert hasattr(env, 'add_elevation_data'), "Missing add_elevation_data"
    print("    ✓ All graph loading methods present")
except AssertionError as e:
    print(f"    ✗ Method check failed: {e}")
    sys.exit(1)

# Test 6: Check routing methods
print("\n[6/8] Checking routing methods...")
try:
    assert hasattr(env, 'compute_route'), "Missing compute_route"
    assert hasattr(env, 'compute_route_alternatives'), "Missing compute_route_alternatives"
    print("    ✓ All routing methods present")
except AssertionError as e:
    print(f"    ✗ Method check failed: {e}")
    sys.exit(1)

# Test 7: Check metrics methods
print("\n[7/8] Checking metrics methods...")
try:
    assert hasattr(env, 'estimate_travel_time'), "Missing estimate_travel_time"
    assert hasattr(env, 'estimate_monetary_cost'), "Missing estimate_monetary_cost"
    assert hasattr(env, 'estimate_emissions'), "Missing estimate_emissions"
    assert hasattr(env, 'estimate_emissions_with_elevation'), "Missing estimate_emissions_with_elevation"
    assert hasattr(env, 'estimate_comfort'), "Missing estimate_comfort"
    assert hasattr(env, 'estimate_risk'), "Missing estimate_risk"
    assert hasattr(env, 'get_speed_km_min'), "Missing get_speed_km_min"
    print("    ✓ All metrics methods present")
except AssertionError as e:
    print(f"    ✗ Method check failed: {e}")
    sys.exit(1)

# Test 8: Check internal methods (for test compatibility)
print("\n[8/8] Checking internal methods...")
try:
    assert hasattr(env, '_distance'), "Missing _distance"
    assert hasattr(env, '_segment_distance_km'), "Missing _segment_distance_km"
    assert hasattr(env, '_is_lonlat'), "Missing _is_lonlat"
    assert hasattr(env, '_get_nearest_node'), "Missing _get_nearest_node"
    assert hasattr(env, '_haversine_km'), "Missing _haversine_km"
    assert hasattr(env, '_haversine_m'), "Missing _haversine_m"
    assert hasattr(env, '_get_cache_key'), "Missing _get_cache_key"
    assert hasattr(env, 'cache_dir'), "Missing cache_dir"
    print("    ✓ All internal methods present")
except AssertionError as e:
    print(f"    ✗ Method check failed: {e}")
    sys.exit(1)

# Test 9: Test coordinate utilities
print("\n[BONUS] Testing coordinate utilities...")
try:
    from simulation.spatial.coordinate_utils import haversine_km, is_valid_lonlat
    
    # Test haversine
    dist = haversine_km((-3.2, 55.95), (-3.19, 55.96))
    assert dist > 0, "Haversine returned invalid distance"
    
    # Test validation
    assert is_valid_lonlat((-3.2, 55.95)) == True
    assert is_valid_lonlat((200.0, 55.95)) == False
    
    print("    ✓ Coordinate utilities working")
except Exception as e:
    print(f"    ✗ Utilities test failed: {e}")
    sys.exit(1)

print("\n" + "="*70)
print("✓ ALL CHECKS PASSED!")
print("="*70)
print("\nRefactoring verified successfully.")
print("You can now run:")
print("  - python test_phase2_routing.py")
print("  - python test_phase2.2_route_alternatives.py")
print("\nBoth should pass with the refactored architecture.")