#!/usr/bin/env python3
"""
setup_scenarios.py

One-time setup script to initialize Phase 4.5B scenario framework.
Run this to create directory structure and example scenarios.
"""

from pathlib import Path
import sys
import logging

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from scenarios.scenario_manager import create_example_scenarios

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def setup_phase_4_5b():
    """Complete setup for Phase 4.5B."""
    
    logger.info("=" * 60)
    logger.info("RTD_SIM Phase 4.5B Setup - Scenario Framework")
    logger.info("=" * 60)
    
    # 1. Create directory structure
    logger.info("\n1. Creating directory structure...")
    scenarios_dir = project_root / 'scenarios'
    scenarios_dir.mkdir(exist_ok=True)
    
    configs_dir = scenarios_dir / 'configs'
    configs_dir.mkdir(exist_ok=True)
    
    logger.info(f"   ✅ Created: {scenarios_dir}")
    logger.info(f"   ✅ Created: {configs_dir}")
    
    # 2. Create __init__.py for scenarios package
    logger.info("\n2. Creating package files...")
    init_file = scenarios_dir / '__init__.py'
    if not init_file.exists():
        init_file.write_text('"""RTD_SIM Policy Scenario Framework"""')
        logger.info(f"   ✅ Created: {init_file}")
    
    # 3. Generate example scenarios
    logger.info("\n3. Generating example scenarios...")
    create_example_scenarios(configs_dir)
    
    # 4. List created scenarios
    logger.info("\n4. Available scenarios:")
    yaml_files = list(configs_dir.glob('*.yaml'))
    for i, yaml_file in enumerate(yaml_files, 1):
        logger.info(f"   {i}. {yaml_file.name}")
    
    # 5. Quick test of scenario loading
    logger.info("\n5. Testing scenario loading...")
    try:
        from scenarios.scenario_manager import ScenarioManager
        manager = ScenarioManager(configs_dir)
        scenarios = manager.list_scenarios()
        logger.info(f"   ✅ Successfully loaded {len(scenarios)} scenarios")
        
        for scenario_name in scenarios:
            info = manager.get_scenario_info(scenario_name)
            logger.info(f"      - {scenario_name}: {info['description']}")
    except Exception as e:
        logger.error(f"   ❌ Failed to load scenarios: {e}")
        return False
    
    # 6. Final summary
    logger.info("\n" + "=" * 60)
    logger.info("✅ Phase 4.5B Setup Complete!")
    logger.info("=" * 60)
    logger.info("\nNext steps:")
    logger.info("1. Apply the two critical fixes:")
    logger.info("   - agent/bdi_planner.py line 151: Change <= to <")
    logger.info("   - simulation/spatial/metrics_calculator.py:")
    logger.info("     * van_electric: 0.35 per km")
    logger.info("     * van_diesel: 0.55 per km")
    logger.info("\n2. Update simulation_runner.py:")
    logger.info("   - Add scenario manager initialization")
    logger.info("   - Add set_scenario() method")
    logger.info("   - Apply policies in run() method")
    logger.info("\n3. Update streamlit_app.py:")
    logger.info("   - Add scenario selector dropdown")
    logger.info("   - Add scenario comparison feature")
    logger.info("\n4. Test with a simple scenario:")
    logger.info("   python streamlit_app.py")
    logger.info("   Select 'EV Subsidy 30%' and run simulation")
    logger.info("\n" + "=" * 60)
    
    return True


if __name__ == '__main__':
    success = setup_phase_4_5b()
    sys.exit(0 if success else 1)