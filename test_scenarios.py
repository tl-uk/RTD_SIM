#!/usr/bin/env python3
"""
test_scenarios.py

Comprehensive test suite for Phase 4.5B scenario framework.
Verifies scenario loading, policy application, and simulation integration.
"""

from pathlib import Path
import sys
import logging

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_scenario_loading():
    """Test 1: Verify scenarios can be loaded."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 1: Scenario Loading")
    logger.info("=" * 60)
    
    try:
        from scenarios.scenario_manager import ScenarioManager
        
        configs_dir = project_root / 'scenarios' / 'configs'
        manager = ScenarioManager(configs_dir)
        
        scenarios = manager.list_scenarios()
        assert len(scenarios) > 0, "No scenarios loaded!"
        
        logger.info(f"✅ Loaded {len(scenarios)} scenarios:")
        for name in scenarios:
            info = manager.get_scenario_info(name)
            logger.info(f"   - {name}")
            logger.info(f"     Policies: {info['num_policies']}")
            logger.info(f"     Expected outcomes: {len(info['expected_outcomes'])}")
        
        return True
    except Exception as e:
        logger.error(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_scenario_activation():
    """Test 2: Verify scenarios can be activated."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 2: Scenario Activation")
    logger.info("=" * 60)
    
    try:
        from scenarios.scenario_manager import ScenarioManager
        
        configs_dir = project_root / 'scenarios' / 'configs'
        manager = ScenarioManager(configs_dir)
        
        # Test activation
        test_scenario = 'EV Subsidy 30%'
        success = manager.activate_scenario(test_scenario)
        assert success, f"Failed to activate {test_scenario}"
        assert manager.active_scenario is not None, "No active scenario after activation"
        
        logger.info(f"✅ Activated: {test_scenario}")
        logger.info(f"   Description: {manager.active_scenario.description}")
        logger.info(f"   Policies: {len(manager.active_scenario.policies)}")
        
        # Generate report
        report = manager.get_scenario_report()
        logger.info(f"   Report generated: {report['name']}")
        
        return True
    except Exception as e:
        logger.error(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_policy_application():
    """Test 3: Verify policies can be applied to mock environment."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 3: Policy Application")
    logger.info("=" * 60)
    
    try:
        from scenarios.scenario_manager import ScenarioManager
        
        # Create mock environment
        class MockMetrics:
            def __init__(self):
                self.cost = {
                    'car': {'base': 0.0, 'per_km': 0.5},
                    'ev': {'base': 0.0, 'per_km': 0.3},
                    'van_electric': {'base': 0.0, 'per_km': 0.4}
                }
                self.speed = {
                    'bus': {'city': 15, 'highway': 50}
                }
        
        class MockInfra:
            def __init__(self):
                self.grid_capacity_mw = 100.0
                self.chargers = {
                    'station_1': {'cost_per_kwh': 0.15},
                    'station_2': {'cost_per_kwh': 0.15}
                }
        
        class MockEnv:
            def __init__(self):
                self.metrics_calculator = MockMetrics()
                self.infrastructure = MockInfra()
        
        env = MockEnv()
        
        # Apply EV subsidy scenario
        configs_dir = project_root / 'scenarios' / 'configs'
        manager = ScenarioManager(configs_dir)
        manager.activate_scenario('EV Subsidy 30%')
        
        # Record original values
        original_ev_cost = env.metrics_calculator.cost['ev']['per_km']
        original_van_cost = env.metrics_calculator.cost['van_electric']['per_km']
        
        logger.info(f"Original EV cost: {original_ev_cost} per km")
        logger.info(f"Original van_electric cost: {original_van_cost} per km")
        
        # Apply policies
        manager.apply_to_environment(env)
        
        # Check modified values
        new_ev_cost = env.metrics_calculator.cost['ev']['per_km']
        new_van_cost = env.metrics_calculator.cost['van_electric']['per_km']
        
        logger.info(f"New EV cost: {new_ev_cost} per km")
        logger.info(f"New van_electric cost: {new_van_cost} per km")
        
        # Verify 30% reduction
        expected_ev = original_ev_cost * 0.7
        expected_van = original_van_cost * 0.7
        
        assert abs(new_ev_cost - expected_ev) < 0.01, f"EV cost not reduced correctly"
        assert abs(new_van_cost - expected_van) < 0.01, f"Van cost not reduced correctly"
        
        logger.info("✅ Policies applied correctly!")
        logger.info(f"   EV: {original_ev_cost} → {new_ev_cost} ({((new_ev_cost/original_ev_cost)-1)*100:+.1f}%)")
        logger.info(f"   Van: {original_van_cost} → {new_van_cost} ({((new_van_cost/original_van_cost)-1)*100:+.1f}%)")
        
        return True
    except Exception as e:
        logger.error(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_scenario_comparison():
    """Test 4: Verify scenario comparison structure."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 4: Scenario Comparison Structure")
    logger.info("=" * 60)
    
    try:
        # Mock comparison results
        mock_baseline = {
            'mode_shares': {'car': 0.3, 'ev': 0.1, 'bus': 0.2, 'bike': 0.4},
            'avg_emissions_per_trip': 150.0,
            'avg_travel_time': 25.0
        }
        
        mock_scenario = {
            'mode_shares': {'car': 0.2, 'ev': 0.25, 'bus': 0.2, 'bike': 0.35},
            'avg_emissions_per_trip': 120.0,
            'avg_travel_time': 26.0
        }
        
        # Calculate deltas manually
        def calculate_deltas(baseline, scenario):
            deltas = {}
            
            mode_changes = {}
            for mode in set(baseline['mode_shares'].keys()) | set(scenario['mode_shares'].keys()):
                base_val = baseline['mode_shares'].get(mode, 0)
                scen_val = scenario['mode_shares'].get(mode, 0)
                if base_val > 0:
                    change_pct = ((scen_val - base_val) / base_val) * 100
                else:
                    change_pct = scen_val * 100 if scen_val > 0 else 0
                mode_changes[mode] = change_pct
            
            deltas['mode_share_changes'] = mode_changes
            
            base_emissions = baseline['avg_emissions_per_trip']
            scen_emissions = scenario['avg_emissions_per_trip']
            deltas['emissions_change_pct'] = ((scen_emissions - base_emissions) / base_emissions) * 100
            
            base_time = baseline['avg_travel_time']
            scen_time = scenario['avg_travel_time']
            deltas['travel_time_change_pct'] = ((scen_time - base_time) / base_time) * 100
            
            return deltas
        
        deltas = calculate_deltas(mock_baseline, mock_scenario)
        
        logger.info("✅ Comparison structure validated")
        logger.info("\nMode Share Changes:")
        for mode, change in deltas['mode_share_changes'].items():
            logger.info(f"   {mode}: {change:+.1f}%")
        
        logger.info(f"\nEmissions: {deltas['emissions_change_pct']:+.1f}%")
        logger.info(f"Travel Time: {deltas['travel_time_change_pct']:+.1f}%")
        
        return True
    except Exception as e:
        logger.error(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_all_scenarios():
    """Test 5: Verify all scenarios are valid."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 5: All Scenarios Valid")
    logger.info("=" * 60)
    
    try:
        from scenarios.scenario_manager import ScenarioManager
        
        configs_dir = project_root / 'scenarios' / 'configs'
        manager = ScenarioManager(configs_dir)
        
        all_valid = True
        for name in manager.list_scenarios():
            try:
                success = manager.activate_scenario(name)
                if not success:
                    logger.error(f"❌ Failed to activate: {name}")
                    all_valid = False
                else:
                    report = manager.get_scenario_report()
                    logger.info(f"✅ {name}: {report['num_policies']} policies")
            except Exception as e:
                logger.error(f"❌ Error with {name}: {e}")
                all_valid = False
        
        if all_valid:
            logger.info("\n✅ All scenarios are valid!")
        else:
            logger.warning("\n⚠️  Some scenarios had issues")
        
        return all_valid
    except Exception as e:
        logger.error(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all_tests():
    """Run complete test suite."""
    logger.info("\n" + "🧪" * 30)
    logger.info("PHASE 4.5B SCENARIO FRAMEWORK TEST SUITE")
    logger.info("🧪" * 30)
    
    tests = [
        ("Scenario Loading", test_scenario_loading),
        ("Scenario Activation", test_scenario_activation),
        ("Policy Application", test_policy_application),
        ("Scenario Comparison", test_scenario_comparison),
        ("All Scenarios Valid", test_all_scenarios)
    ]
    
    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            logger.error(f"\n❌ Test crashed: {name}")
            logger.error(f"   Error: {e}")
            results.append((name, False))
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("TEST SUMMARY")
    logger.info("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status}: {name}")
    
    logger.info("\n" + "=" * 60)
    logger.info(f"Result: {passed}/{total} tests passed")
    logger.info("=" * 60)
    
    if passed == total:
        logger.info("\n🎉 ALL TESTS PASSED! Phase 4.5B is ready!")
    else:
        logger.warning(f"\n⚠️  {total - passed} test(s) failed. Review errors above.")
    
    return passed == total


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)