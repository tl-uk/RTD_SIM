"""
simulation/execution/simulation_loop.py

Docstring for simulation.execution.simulation_loop
"""

from __future__ import annotations
import random
import logging
from typing import Any, Dict, Optional
from pathlib import Path
from simulation.config.simulation_config import SimulationConfig
from simulation.spatial_environment import SpatialEnvironment

logger = logging.getLogger(__name__)

# Story-driven agents and social influence dynamics
try:
    from agent.story_driven_agent import StoryDrivenAgent
    from agent.social_network import SocialNetwork
    from agent.social_influence_dynamics import (
        RealisticSocialInfluence,
        enhance_social_network_with_realism,
        calculate_satisfaction
    )
except ImportError:
    logger.warning("Story-driven agents not available")

# Scenario framework
try:
    from scenarios.scenario_manager import ScenarioManager
    SCENARIOS_AVAILABLE = True
except ImportError:
    SCENARIOS_AVAILABLE = False
    logger.warning("Scenario framework not available")

# ============================================================
# SIMULATION LOOP FUNCTIONS
# ============================================================
def apply_scenario_policies(
    config: SimulationConfig,
    env: SpatialEnvironment,
    progress_callback=None
) -> Optional[Dict]:
    """
    Apply policy scenario to environment if specified.
    
    Args:
        config: SimulationConfig instance
        env: SpatialEnvironment to modify
        progress_callback: Optional callback
    
    Returns:
        Scenario report dict or None
    """
    if not SCENARIOS_AVAILABLE or not config.scenario_name:
        return None
    
    if progress_callback:
        progress_callback(0.48, f"📋 Applying scenario: {config.scenario_name}")
    
    try:
        # Initialize scenario manager
        scenarios_dir = config.scenarios_dir or (Path(__file__).parent.parent / 'scenarios' / 'configs')
        manager = ScenarioManager(scenarios_dir)
        
        # Activate scenario
        success = manager.activate_scenario(config.scenario_name)
        if not success:
            logger.error(f"Failed to activate scenario: {config.scenario_name}")
            return None
        
        # Apply policies to environment
        manager.apply_to_environment(env)
        
        # Generate report
        report = manager.get_scenario_report()
        
        # Log applied policies
        logger.info(f"📋 Scenario Active: {report['name']}")
        logger.info(f"   {report['description']}")
        for policy in report['policies']:
            mode_info = f" ({policy['mode']})" if policy.get('mode') else ""
            logger.info(f"   - {policy['parameter']}: {policy['value']}{mode_info}")
        
        return report
        
    except Exception as e:
        logger.error(f"Failed to apply scenario: {e}")
        import traceback
        traceback.print_exc()
        return None
    
def run_simulation_loop(
    config, agents, env, infrastructure, network, influence_system, progress_callback=None
) -> dict:
    """Execute main simulation loop and return results."""
    for step in range(config.steps):
            # Update systems
            if influence_system:
                influence_system.advance_time()
            
            if infrastructure:
                infrastructure.update_grid_load(step)
            
            # Agent steps
            agent_states = []
            for agent in agents:
                try:
                    agent.step(env)
                except:
                    agent.step()
                
                # Social influence
                if network:
                    mode_costs = getattr(agent.state, 'mode_costs', {})
                    if mode_costs:
                        adjusted = network.apply_social_influence(
                            agent.state.agent_id,
                            mode_costs,
                            influence_strength=0.10,
                            conformity_pressure=0.10
                        )
                        # Apply influence 50% of time to preserve diversity
                        if random.random() < 0.5:
                            best_mode = min(adjusted, key=adjusted.get)
                            agent.state.mode = best_mode
                    
                    if influence_system and not agent.state.arrived:
                        satisfaction = calculate_satisfaction(
                            agent, env,
                            actual_time=agent.state.travel_time_min,
                            expected_time=10.0,
                            actual_cost=1.0,
                            expected_cost=1.0
                        )
                        influence_system.record_mode_usage(
                            agent.state.agent_id,
                            agent.state.mode,
                            satisfaction
                        )
                
                # Infrastructure interaction (Phase 4.5)
                if infrastructure and agent.state.mode == 'ev':
                    agent_id = agent.state.agent_id
                    
                    # Check if agent is already charging
                    if agent_id not in infrastructure.agent_charging_state:
                        # Agent not yet charging - check if should start
                        if hasattr(agent.state, 'action_params') and agent.state.action_params:
                            params = agent.state.action_params
                            
                            if 'nearest_charger' in params:
                                # More realistic charging triggers
                                should_charge = (
                                    agent.state.arrived or 
                                    agent.state.distance_km > 3.0 or
                                    (agent.state.distance_km > 1.0 and random.random() < 0.1)
                                )
                                
                                if should_charge:
                                    station_id = params['nearest_charger']
                                    
                                    # Realistic charging duration based on trip
                                    trip_distance = params.get('trip_distance_km', 5.0)
                                    if trip_distance < 5.0:
                                        charge_duration = random.uniform(15, 30)
                                    elif trip_distance < 15.0:
                                        charge_duration = random.uniform(30, 60)
                                    else:
                                        charge_duration = random.uniform(60, 120)
                                    
                                    success = infrastructure.reserve_charger(
                                        agent_id,
                                        station_id,
                                        duration_min=charge_duration
                                    )
                                    
                                    if success:
                                        infrastructure.agent_charging_state[agent_id]['status'] = 'charging'
                                        infrastructure.agent_charging_state[agent_id]['start_time'] = step
                                        logger.debug(f"Step {step}: Agent {agent_id} started charging at {station_id} ({charge_duration:.0f} min)")
                    
                    else:
                        # Agent is already charging - check if done
                        charge_state = infrastructure.agent_charging_state[agent_id]
                        if charge_state['status'] == 'charging':
                            start_time = charge_state.get('start_time', step)
                            duration = charge_state['duration_min']
                            elapsed_min = (step - start_time) * 1.0
                            
                            if elapsed_min >= duration:
                                infrastructure.release_charger(agent_id)
                                logger.debug(f"Step {step}: Agent {agent_id} finished charging ({elapsed_min:.0f} min)")
                
                # Collect state
                agent_states.append({
                    'agent_id': agent.state.agent_id,
                    'location': agent.state.location,
                    'mode': agent.state.mode,
                    'arrived': agent.state.arrived,
                    'route': agent.state.route,
                    'distance_km': agent.state.distance_km,
                    'emissions_g': agent.state.emissions_g,
                })
    
    return {
        'time_series': time_series,
        'adoption_history': adoption_history,
        'cascade_events': cascade_events
    }