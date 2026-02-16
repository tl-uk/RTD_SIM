"""
simulation/simulation_runner.py

Main simulation orchestrator - delegates to specialized modules.

MODIFIED Phase 5.1: Added dynamic policy engine support for combined scenarios
"""

from __future__ import annotations

# Enable logging to console
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s',
    force=True
)

from typing import Optional, Callable

from simulation.config.simulation_config import SimulationConfig, SimulationResults
from simulation.setup.environment_setup import setup_environment, setup_infrastructure
from simulation.setup.agent_creation import create_agents, create_planner
from simulation.setup.network_setup import setup_social_network
from simulation.execution.simulation_loop import run_simulation_loop, apply_scenario_policies
from simulation.routing.route_diversity import apply_route_diversity
from simulation.analysis.scenario_comparison import (
    list_available_scenarios,
    get_scenario_info,
    compare_scenarios,
    format_comparison_report
)

# NEW Phase 5.1: Import dynamic policy engine
from simulation.execution.dynamic_policies import initialize_policy_engine

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = [
    'SimulationConfig',
    'SimulationResults',
    'run_simulation',
    'list_available_scenarios',
    'get_scenario_info',
    'compare_scenarios',
    'format_comparison_report'
]


def run_simulation(
    config: SimulationConfig,
    progress_callback: Optional[Callable[[float, str], None]] = None
) -> SimulationResults:
    """
    Execute complete simulation run (orchestrator only).
    
    This function delegates to specialized modules for each phase:
    1. Environment setup (OSM graphs, congestion)
    2. Route diversity strategies
    3. Infrastructure (charging stations, depots)
    4. Scenario policies (if specified) - NEW: includes combined scenarios
    5. Agent creation (story-driven or basic)
    6. Social network (influence system)
    7. Main simulation loop - NEW: with policy engine
    8. Results collection - NEW: includes policy results
    
    Args:
        config: SimulationConfig with all parameters
        progress_callback: Optional callback(progress: float, message: str)
    
    Returns:
        SimulationResults with complete simulation data
    """
    results = SimulationResults()
    
    try:
        # Phase 1: Setup environment
        logger.info("🗺️ Phase 1: Environment setup")
        env = setup_environment(config, progress_callback)
        results.env = env
        
        # Phase 2: Apply route diversity
        if config.use_osm and config.enable_route_diversity:
            logger.info(f"🛣️ Phase 2: Route diversity ({config.route_diversity_mode})")
            env = apply_route_diversity(env, mode=config.route_diversity_mode)
            logger.info(f"✅ Route diversity: {config.route_diversity_mode}")
        
        # Phase 3: Setup infrastructure
        logger.info("🔌 Phase 3: Infrastructure setup")
        infrastructure = setup_infrastructure(config, progress_callback)
        results.infrastructure = infrastructure
        
        # Phase 4: Create planner
        logger.info("🧠 Phase 4: BDI planner creation")
        planner = create_planner(infrastructure)
        
        # ====================================================================
        # Phase 4.5: Apply policies (simple, combined, or default)
        # ====================================================================
        policy_engine = None

        # Check if combined scenario OR default policies are active
        if config.combined_scenario_data or getattr(config, 'use_default_policies', False):
            if config.combined_scenario_data:
                logger.info("🔗 Phase 4.5: Initializing dynamic policy engine (combined scenario)")
            else:
                logger.info("🔗 Phase 4.5: Initializing dynamic policy engine (default policies)")
            
            policy_engine = initialize_policy_engine(config, infrastructure)
            
            if policy_engine:
                logger.info(f"✅ Policy engine initialized")
            else:
                logger.warning("⚠️ Failed to initialize policy engine, continuing without it")

        # Fallback to simple scenario if no combined scenario and no default policies
        elif config.scenario_name:
            logger.info(f"📋 Phase 4.5: Applying simple scenario '{config.scenario_name}'")
            scenario_report = apply_scenario_policies(config, env, progress_callback)
            results.scenario_report = scenario_report
            
            if scenario_report:
                logger.info(f"✅ Scenario applied: {scenario_report['name']}")

        else:
            logger.info("➖ Phase 4.5: No scenarios active (baseline run)")
        
        # ====================================================================
        # Phase 7: Run main simulation loop (with policy engine if active)
        # ====================================================================
        logger.info("⚙️ Phase 7: Running simulation loop")
        loop_results = run_simulation_loop(
            config=config,
            agents=agents,
            env=env,
            infrastructure=infrastructure,
            network=network,
            influence_system=influence_system,
            policy_engine=policy_engine,  # NEW: Pass policy engine!
            progress_callback=progress_callback
        )
        
        # ====================================================================
        # Phase 8: Collect results (including policy results)
        # ====================================================================
        logger.info("📊 Phase 8: Collecting results")
        results.time_series = loop_results['time_series']
        results.adoption_history = loop_results['adoption_history']
        results.cascade_events = loop_results['cascade_events']
        
        # NEW: Collect policy results if available
        if 'policy_actions' in loop_results:
            results.policy_actions = loop_results['policy_actions']
            results.constraint_violations = loop_results.get('constraint_violations', [])
            results.cost_recovery_history = loop_results.get('cost_recovery_history', [])
            results.final_cost_recovery = loop_results.get('final_cost_recovery')
            results.policy_status = loop_results.get('policy_status')
            
            logger.info(f"✅ Policy tracking: {len(results.policy_actions)} actions, "
                       f"{len(results.constraint_violations)} violations")
        
        # Collect weather/environmental results if present
        if 'weather_manager' in loop_results:
            results.weather_manager = loop_results['weather_manager']
            results.weather_history = loop_results.get('weather_history', [])
            
            if results.weather_history:
                logger.info(f"✅ Weather tracking: {len(results.weather_history)} timesteps")
        
        if 'air_quality_tracker' in loop_results:
            results.air_quality_tracker = loop_results['air_quality_tracker']

        if 'lifecycle_emissions' in loop_results:
            results.lifecycle_emissions_total = loop_results['lifecycle_emissions']

        # Phase 5.3: Collect analytics results
        if 'journey_tracker' in loop_results:
            results.journey_tracker = loop_results['journey_tracker']
            logger.info(f"📊 Analytics: {len(loop_results['journey_tracker'].journeys)} journeys tracked")

        if 'mode_share_analyzer' in loop_results:
            results.mode_share_analyzer = loop_results['mode_share_analyzer']

        if 'policy_impact_analyzer' in loop_results:
            results.policy_impact_analyzer = loop_results['policy_impact_analyzer']

        if 'network_efficiency_tracker' in loop_results:
            results.network_efficiency_tracker = loop_results['network_efficiency_tracker']

        if 'analytics_summary' in loop_results:
            results.analytics_summary = loop_results['analytics_summary']
            logger.info(f"✅ Analytics summary generated")
        results.success = True
        
        # Log summary
        num_cascades = len(results.cascade_events)
        logger.info(f"✅ Simulation complete: {num_cascades} cascades detected")
        
        if progress_callback:
            progress_callback(1.0, "✅ Complete!")
        
    except Exception as e:
        logger.exception(f"❌ Simulation failed: {e}")
        results.success = False
        results.error_message = str(e)
        
        if progress_callback:
            progress_callback(1.0, f"❌ Failed: {str(e)[:50]}")
    
    return results


# Convenience functions for common operations
def run_baseline_simulation(config: SimulationConfig) -> SimulationResults:
    """Run simulation without any scenario (baseline)."""
    config.scenario_name = None
    config.combined_scenario_data = None
    return run_simulation(config)


def run_scenario_simulation(
    config: SimulationConfig,
    scenario_name: str
) -> SimulationResults:
    """Run simulation with specified scenario applied."""
    config.scenario_name = scenario_name
    config.combined_scenario_data = None
    return run_simulation(config)


def compare_baseline_vs_scenario(
    config: SimulationConfig,
    scenario_name: str,
    progress_callback: Optional[Callable[[float, str], None]] = None
) -> dict:
    """
    Run baseline and scenario simulations, return comparison.
    
    Args:
        config: Base configuration
        scenario_name: Scenario to compare against baseline
        progress_callback: Optional progress callback
    
    Returns:
        Dict with baseline_results, scenario_results, and comparison
    """
    logger.info("Running baseline simulation...")
    baseline_results = run_baseline_simulation(config)
    
    logger.info(f"Running scenario simulation: {scenario_name}")
    scenario_results = run_scenario_simulation(config, scenario_name)
    
    logger.info("Comparing results...")
    comparison = compare_scenarios(
        baseline_results.__dict__,
        scenario_results.__dict__,
        scenario_name
    )
    
    return {
        'baseline_results': baseline_results,
        'scenario_results': scenario_results,
        'comparison': comparison,
        'report': format_comparison_report(comparison)
    }