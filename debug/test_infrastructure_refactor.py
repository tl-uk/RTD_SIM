"""
test_infrastructure_simple.py

Test infrastructure refactoring WITHOUT pytest.
Uses only standard library - no dependencies needed.

Run with: python test_infrastructure_simple.py
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from simulation.infrastructure import InfrastructureManager


class TestRunner:
    """Simple test runner without pytest."""
    
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
    
    def assert_equal(self, actual, expected, message=""):
        """Assert two values are equal."""
        if actual != expected:
            raise AssertionError(
                f"{message}\n  Expected: {expected}\n  Got: {actual}"
            )
    
    def assert_true(self, condition, message=""):
        """Assert condition is true."""
        if not condition:
            raise AssertionError(f"{message}\n  Expected True, got False")
    
    def assert_in(self, item, container, message=""):
        """Assert item is in container."""
        if item not in container:
            raise AssertionError(
                f"{message}\n  {item} not found in {container}"
            )
    
    def assert_not_none(self, value, message=""):
        """Assert value is not None."""
        if value is None:
            raise AssertionError(f"{message}\n  Expected non-None value")
    
    def run_test(self, test_func, test_name):
        """Run a single test."""
        try:
            test_func()
            self.passed += 1
            print(f"✅ PASS: {test_name}")
            return True
        except AssertionError as e:
            self.failed += 1
            self.errors.append((test_name, str(e)))
            print(f"❌ FAIL: {test_name}")
            print(f"   {e}")
            return False
        except Exception as e:
            self.failed += 1
            self.errors.append((test_name, f"ERROR: {e}"))
            print(f"❌ ERROR: {test_name}")
            print(f"   {e}")
            return False
    
    def print_summary(self):
        """Print test summary."""
        total = self.passed + self.failed
        print("\n" + "="*60)
        print(f"Test Results: {self.passed}/{total} passed")
        print("="*60)
        
        if self.errors:
            print("\n❌ Failed Tests:")
            for test_name, error in self.errors:
                print(f"  - {test_name}")
                print(f"    {error}")
        
        if self.failed == 0:
            print("\n🎉 All tests passed!")
            return 0
        else:
            print(f"\n⚠️  {self.failed} test(s) failed")
            return 1


def test_initialization(runner):
    """Test basic initialization."""
    infra = InfrastructureManager(grid_capacity_mw=100.0)
    
    runner.assert_equal(
        infra.grid.regions['default'].capacity_mw,
        100.0,
        "Grid capacity should be 100 MW"
    )
    runner.assert_equal(
        len(infra.stations.stations),
        0,
        "Should start with no stations"
    )


def test_add_charging_station(runner):
    """Test adding charging station."""
    infra = InfrastructureManager()
    
    infra.add_charging_station(
        station_id="test_station",
        location=(-3.19, 55.95),
        charger_type='level2',
        num_ports=4,
        power_kw=7.0
    )
    
    runner.assert_in(
        "test_station",
        infra.charging_stations,
        "Station should be added"
    )
    runner.assert_equal(
        infra.charging_stations["test_station"].num_ports,
        4,
        "Should have 4 ports"
    )


def test_find_nearest_charger(runner):
    """Test finding nearest charger."""
    infra = InfrastructureManager()
    
    infra.add_charging_station("s1", (-3.19, 55.95), num_ports=2)
    infra.add_charging_station("s2", (-3.20, 55.96), num_ports=4)
    
    nearest = infra.find_nearest_charger(
        location=(-3.195, 55.955),
        max_distance_km=10.0
    )
    
    runner.assert_not_none(nearest, "Should find a station")
    
    station_id, distance = nearest
    runner.assert_true(
        station_id in ["s1", "s2"],
        f"Found station should be s1 or s2, got {station_id}"
    )
    runner.assert_true(
        distance < 10.0,
        f"Distance should be < 10km, got {distance}"
    )


def test_reserve_and_release_charger(runner):
    """Test charging session workflow."""
    infra = InfrastructureManager()
    
    infra.add_charging_station("s1", (-3.19, 55.95), num_ports=2)
    
    # Reserve charger
    success = infra.reserve_charger("agent_001", "s1", duration_min=60.0)
    runner.assert_true(success, "Should successfully reserve charger")
    
    # Check state
    runner.assert_in(
        "agent_001",
        infra.agent_charging_state,
        "Agent should be in charging state"
    )
    runner.assert_equal(
        infra.charging_stations["s1"].currently_occupied,
        1,
        "Station should have 1 occupied port"
    )
    
    # Release charger
    infra.release_charger("agent_001")
    runner.assert_true(
        "agent_001" not in infra.agent_charging_state,
        "Agent should be removed from charging state"
    )
    runner.assert_equal(
        infra.charging_stations["s1"].currently_occupied,
        0,
        "Station should have 0 occupied ports"
    )


def test_grid_load_tracking(runner):
    """Test grid load tracking."""
    infra = InfrastructureManager(grid_capacity_mw=100.0)
    
    infra.add_charging_station("s1", (-3.19, 55.95), power_kw=50.0)
    infra.reserve_charger("agent_001", "s1", duration_min=60.0)
    infra.sessions.start_charging("agent_001", step=0)
    
    infra.update_grid_load(step=0)
    
    grid_load = infra.grid.get_load()
    runner.assert_equal(
        grid_load,
        0.05,  # 50 kW = 0.05 MW
        "Grid load should be 0.05 MW"
    )


def test_get_infrastructure_metrics(runner):
    """Test metrics aggregation."""
    infra = InfrastructureManager()
    
    infra.add_charging_station("s1", (-3.19, 55.95), num_ports=4)
    infra.add_charging_station("s2", (-3.20, 55.96), num_ports=2)
    
    metrics = infra.get_infrastructure_metrics()
    
    runner.assert_equal(
        metrics['charging_stations'],
        2,
        "Should have 2 stations"
    )
    runner.assert_equal(
        metrics['total_ports'],
        6,
        "Should have 6 total ports"
    )
    runner.assert_in(
        'grid_utilization',
        metrics,
        "Should include grid utilization"
    )


def test_ev_range_adjustment(runner):
    """Test EV range weather adjustments."""
    infra = InfrastructureManager()
    
    # Base range
    base_range = infra.get_base_ev_range('ev')
    runner.assert_equal(base_range, 350.0, "Base range should be 350km")
    
    # Adjust for cold weather
    infra.set_adjusted_ev_range('ev', 262.5)  # 75% of base
    
    adjusted = infra.get_adjusted_ev_range('ev')
    runner.assert_equal(adjusted, 262.5, "Adjusted range should be 262.5km")


def test_populate_edinburgh(runner):
    """Test quick Edinburgh setup."""
    infra = InfrastructureManager()
    
    infra.populate_edinburgh_chargers(num_public=50, num_depot=5)
    
    # Should have ~60 stations (50 level2 + ~10 dcfast)
    runner.assert_true(
        len(infra.charging_stations) >= 50,
        f"Should have at least 50 stations, got {len(infra.charging_stations)}"
    )
    
    # Should have 5 depots
    runner.assert_equal(
        len(infra.depots.depots),
        5,
        "Should have 5 depots"
    )


def test_load_balancer_optional(runner):
    """Test load balancer is optional."""
    # Without load balancing
    infra1 = InfrastructureManager(enable_load_balancing=False)
    runner.assert_true(
        infra1.load_balancer is None,
        "Load balancer should be None when disabled"
    )
    
    # With load balancing
    infra2 = InfrastructureManager(enable_load_balancing=True)
    runner.assert_true(
        infra2.load_balancer is not None,
        "Load balancer should exist when enabled"
    )


def test_backward_compatibility(runner):
    """Test backward compatibility with old API."""
    infra = InfrastructureManager()
    
    # Old API should still work
    runner.assert_true(
        hasattr(infra, 'charging_stations'),
        "Should expose charging_stations attribute"
    )
    runner.assert_true(
        hasattr(infra, 'agent_charging_state'),
        "Should expose agent_charging_state attribute"
    )
    runner.assert_true(
        hasattr(infra, 'grid_regions'),
        "Should expose grid_regions attribute"
    )


def main():
    """Run all tests."""
    print("="*60)
    print("Infrastructure Refactoring Tests")
    print("="*60)
    print()
    
    runner = TestRunner()
    
    # Run all tests
    tests = [
        (test_initialization, "Initialization"),
        (test_add_charging_station, "Add Charging Station"),
        (test_find_nearest_charger, "Find Nearest Charger"),
        (test_reserve_and_release_charger, "Reserve and Release Charger"),
        (test_grid_load_tracking, "Grid Load Tracking"),
        (test_get_infrastructure_metrics, "Infrastructure Metrics"),
        (test_ev_range_adjustment, "EV Range Adjustment"),
        (test_populate_edinburgh, "Populate Edinburgh"),
        (test_load_balancer_optional, "Load Balancer Optional"),
        (test_backward_compatibility, "Backward Compatibility"),
    ]
    
    for test_func, test_name in tests:
        runner.run_test(lambda: test_func(runner), test_name)
    
    # Print summary
    exit_code = runner.print_summary()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()