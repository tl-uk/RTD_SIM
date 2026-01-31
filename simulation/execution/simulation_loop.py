"""
simulation/execution/simulation_loop.py

Main simulation loop execution with metrics tracking.
FIXED: Infrastructure policy application with correct variable references.
"""

from __future__ import annotations
import random
import logging
from typing import Any, Dict, Optional, List
from pathlib import Path
from collections import defaultdict

from simulation.config.simulation_config import SimulationConfig
from simulation.spatial_environment import SpatialEnvironment
from simulation.execution.timeseries import TimeSeries

from simulation.execution.dynamic_policies import (
    initialize_policy_engine,
    apply_dynamic_policies,
    record_charging_revenue,
    get_final_policy_report
)

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
    SOCIAL_AVAILABLE = True
except ImportError:
    SOCIAL_AVAILABLE = False
    logger.warning("Story-driven agents not available")

# Scenario framework
try:
    from scenarios.scenario_manager import ScenarioManager
    SCENARIOS_AVAILABLE = True
except ImportError:
    SCENARIOS_AVAILABLE = False
    logger.warning("Scenario framework not available")

# Environmental modules (Phase 5.2)
try:
    from environmental.weather_api import create_weather_manager
    from environmental.seasonal_patterns import (
        get_combined_multipliers,
        apply_seasonal_ev_range_penalty
    )
    WEATHER_AVAILABLE = True
except ImportError:
    # Weather system not yet implemented - provide fallbacks
    WEATHER_AVAILABLE = False
    logger.warning("⚠️ Weather system modules not found - weather features disabled")
    
    def create_weather_manager(config):
        """Fallback: return None if weather not available."""
        return None
    
    def get_combined_multipliers(month, day_of_year, day_of_week, hour):
        """Fallback: return neutral multipliers."""
        modes = ['walk', 'bike', 'car', 'ev', 'bus', 'tram', 
                 'van_diesel', 'van_electric', 'truck_diesel', 'truck_electric']
        return {mode: 1.0 for mode in modes}
    
    def apply_seasonal_ev_range_penalty(base_range, temperature):
        """Fallback: return unchanged range."""
        return base_range
from environmental.emissions_calculator import LifecycleEmissions
from environmental.air_quality import create_air_quality_tracker

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
        scenarios_dir = config.scenarios_dir or (Path(__file__).parent.parent.parent / 'scenarios' / 'configs')
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

        # ====================================================================
        # NEW: Apply infrastructure policies
        # ====================================================================
        infrastructure_changes = {}
        
        # Get scenario data (FIX: use manager.active_scenario instead of undefined 'scenario')
        if manager.active_scenario and config.infrastructure:
            scenario_data = manager.active_scenario
            
            for policy in scenario_data.get('policies', []):
                target = policy.get('target', '')
                
                if target == 'infrastructure':
                    param = policy['parameter']
                    
                    # Add chargers
                    if param == 'add_chargers':
                        num = policy['value']
                        strategy = policy.get('placement_strategy', 'demand_heatmap')
                        charger_type = policy.get('charger_type', 'level2')
                        power_kw = policy.get('power_kw', 7.0)
                        
                        # Add chargers using infrastructure manager
                        new_stations = config.infrastructure.add_chargers_by_demand(
                            num_chargers=num,
                            charger_type=charger_type,
                            strategy=strategy
                        )
                        
                        infrastructure_changes['added_chargers'] = {
                            'count': len(new_stations),
                            'station_ids': new_stations,
                            'strategy': strategy,
                            'charger_type': charger_type,
                            'power_kw': power_kw
                        }
                        
                        logger.info(f"✅ Added {len(new_stations)} {charger_type} chargers using {strategy} strategy")
                    
                    # Relocate underutilized chargers
                    elif param == 'relocate_chargers':
                        num = policy['value']
                        threshold = policy.get('utilization_threshold', 0.2)
                        
                        relocated = config.infrastructure.relocate_underutilized_chargers(
                            num_to_relocate=num,
                            utilization_threshold=threshold
                        )
                        
                        infrastructure_changes['relocated_chargers'] = {
                            'count': len(relocated),
                            'station_ids': relocated,
                            'threshold': threshold
                        }
                        
                        logger.info(f"✅ Relocated {len(relocated)} underutilized chargers")
                    
                    # Increase grid capacity
                    elif param == 'increase_capacity':
                        multiplier = policy['value']
                        region = policy.get('region', 'default')
                        
                        if region in config.infrastructure.grid_regions:
                            grid = config.infrastructure.grid_regions[region]
                            old_capacity = grid.capacity_mw
                            grid.capacity_mw *= multiplier
                            
                            infrastructure_changes['grid_capacity_increase'] = {
                                'region': region,
                                'old_capacity_mw': old_capacity,
                                'new_capacity_mw': grid.capacity_mw,
                                'multiplier': multiplier
                            }
                            
                            logger.info(f"✅ Increased grid capacity: {old_capacity:.0f} MW → {grid.capacity_mw:.0f} MW ({multiplier}x)")
                        else:
                            logger.warning(f"Grid region '{region}' not found")
                    
                    # Reduce charging costs (multiplier)
                    elif param == 'charging_cost_multiplier':
                        multiplier = policy['value']
                        
                        # Apply to all charging stations
                        updated_count = 0
                        for station in config.infrastructure.charging_stations.values():
                            station.cost_per_kwh *= multiplier
                            updated_count += 1
                        
                        infrastructure_changes['charging_cost_adjustment'] = {
                            'multiplier': multiplier,
                            'stations_updated': updated_count
                        }
                        
                        logger.info(f"✅ Adjusted charging costs by {multiplier}x for {updated_count} stations")
        
        # Add infrastructure changes to report
        if infrastructure_changes:
            report['infrastructure_changes'] = infrastructure_changes
            logger.info(f"📊 Infrastructure changes: {len(infrastructure_changes)} types applied")
        else:
            report['infrastructure_changes'] = None
        
        return report
        
    except Exception as e:
        logger.error(f"Failed to apply scenario: {e}")
        import traceback
        traceback.print_exc()
        return None


def run_simulation_loop(
        config, 
        agents, 
        env, 
        infrastructure, 
        network, 
        influence_system, 
        policy_engine=None,  # NEW
        progress_callback=None
    ):
    """
    Execute main simulation loop and return results.
    
    Args:
        config: SimulationConfig instance
        agents: List of agents
        env: SpatialEnvironment
        infrastructure: Optional InfrastructureManager
        network: Optional SocialNetwork
        influence_system: Optional RealisticSocialInfluence
        progress_callback: Optional callback(progress, message)
    
    Returns:
        Dict with time_series, adoption_history, cascade_events
    """
    # Initialize tracking structures
    time_series = TimeSeries()
    adoption_history = defaultdict(list)
    cascade_events = []

    # Policy tracking
    policy_actions_taken = []
    constraint_violations = []
    cost_recovery_history = []
    
    # Track mode adoption over time
    def record_adoption():
        """Record current mode distribution."""
        mode_counts = defaultdict(int)
        for agent in agents:
            mode = agent.state.mode
            mode_counts[mode] += 1
        
        # Include all freight modes
        all_modes = [
            'walk', 'bike', 'bus', 'car', 'ev',
            'cargo_bike',
            'van_electric', 'van_diesel',
            'truck_electric', 'truck_diesel',
            'hgv_electric', 'hgv_diesel', 'hgv_hydrogen'
        ]
        
        for mode in all_modes:
            adoption_history[mode].append(mode_counts.get(mode, 0))
    
    # Initialize environmental systems
    weather_manager = create_weather_manager(config) if config.weather_enabled else None
    weather_history = []  # Track weather data for visualization
    
    if weather_manager:
        logger.info("✅ Weather system initialized")
        logger.info(f"   Source: {config.weather_source}")
        logger.info(f"   Location: ({config.latitude:.2f}, {config.longitude:.2f})")
    
    air_quality = create_air_quality_tracker(config) if config.track_air_quality else None
    emissions_calc = LifecycleEmissions(config.grid_carbon_intensity) if config.use_lifecycle_emissions else None
    
    # Track lifecycle emissions
    lifecycle_emissions_by_mode = defaultdict(lambda: {'co2e_kg': 0, 'pm25_g': 0, 'nox_g': 0})
 
    # Main simulation loop
    for step in range(config.steps):
        # Calculate current time
        time_of_day = (step % 1440) / 60.0  # hours (assuming 1 step = 1 min)
        hour = int(time_of_day)
        
        # Calculate date (if seasonal patterns enabled)
        month = config.season_month or 6  # Default to summer
        day_of_year = config.season_day_of_year or 180
        day_of_week = (step // 1440) % 7  # Assuming day 0 is Monday
        
        # UPDATE WEATHER
        if weather_manager:
            weather_conditions = weather_manager.update_weather(step, time_of_day)
            
            # Track weather history for visualization
            weather_history.append({
                'step': step,
                'temperature': weather_conditions.get('temperature', 10.0),
                'precipitation': weather_conditions.get('precipitation', 0.0),
                'wind_speed': weather_conditions.get('wind_speed', 10.0),
                'ice_warning': weather_conditions.get('ice_warning', False),
                'snow_depth': weather_conditions.get('snow_depth', 0.0),
                'cloud_cover': weather_conditions.get('cloud_cover', 50),
                'visibility': weather_conditions.get('visibility', 10000),
                'time_of_day': time_of_day,
                'hour': hour,
            })
            
            # Log weather periodically
            if step % 20 == 0:
                ice_indicator = " ❄️" if weather_conditions.get('ice_warning') else ""
                logger.info(f"Weather (step {step}): "
                           f"{weather_conditions['temperature']:.1f}°C, "
                           f"{weather_conditions['precipitation']:.1f}mm/h, "
                           f"{weather_conditions['wind_speed']:.1f}km/h{ice_indicator}")
            
            # Apply weather to environment speeds
            # Define available transport modes (since env doesn't have get_available_modes)
            transport_modes = [
                'walk', 'bike', 'car', 'ev', 'bus', 'tram', 
                'van_diesel', 'van_electric', 
                'truck_diesel', 'truck_electric',
                'hgv_diesel', 'hgv_electric',
                'cargo_bike'
            ]
            
            for mode in transport_modes:
                speed_mult = weather_manager.get_mode_speed_multiplier(mode)
                # Only set if environment has this method
                if hasattr(env, 'set_weather_speed_multiplier'):
                    env.set_weather_speed_multiplier(mode, speed_mult)
            
            # Adjust EV ranges based on temperature
            if infrastructure:
                temp = weather_conditions['temperature']
                for mode in ['ev', 'van_electric', 'truck_electric', 'hgv_electric']:
                    base_range = infrastructure.get_base_ev_range(mode)
                    adjusted_range = apply_seasonal_ev_range_penalty(base_range, temp)
                    infrastructure.set_adjusted_ev_range(mode, adjusted_range)
        
        # GET SEASONAL MULTIPLIERS
        seasonal_mults = get_combined_multipliers(month, day_of_year, day_of_week, hour)
        
        # Apply to infrastructure grid load
        if infrastructure:
            base_load = infrastructure.get_base_grid_load()
            adjusted_load = base_load * seasonal_mults.get('grid_load', 1.0)
            infrastructure.set_grid_load(adjusted_load)

        if progress_callback and step % 10 == 0:
            progress = 0.5 + (step / config.steps) * 0.45
            progress_callback(progress, f"⚙️ Step {step}/{config.steps}")
        
        # Update systems
        if influence_system:
            influence_system.advance_time()
        
        if infrastructure:
            infrastructure.update_grid_load(step)
            infrastructure.update_time(step)  # Update time for time-of-day pricing
        
        # Apply dynamic policies
        if policy_engine:
            policy_result = apply_dynamic_policies(
                policy_engine=policy_engine,
                step=step,
                agents=agents,
                env=env,
                infrastructure=infrastructure
            )
            
            # Track policy actions
            if policy_result.get('actions_taken'):
                policy_actions_taken.extend(policy_result['actions_taken'])
                logger.info(f"Step {step}: Applied {len(policy_result['actions_taken'])} policy adjustments")
            
            # Track violations
            if policy_result.get('violations'):
                constraint_violations.extend(policy_result['violations'])
            
            # Record cost recovery snapshot every 10 steps
            if step % 10 == 0:
                cost_recovery = policy_engine.calculate_cost_recovery()
                cost_recovery['step'] = step
                cost_recovery_history.append(cost_recovery)

        # Agent steps with lifecycle emissions
        agent_states = []
        for agent in agents:
            # Track previous distance BEFORE agent step
            prev_distance = agent.state.distance_km
            prev_location = agent.state.location
            
            # Execute agent step
            try:
                agent.step(env)
            except:
                agent.step()
            
            # Social influence (if enabled)
            if network and SOCIAL_AVAILABLE:
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
                
                # Record satisfaction for influence system
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
            
            # Calculate lifecycle emissions if agent moved
            if emissions_calc and agent.state.location != prev_location:
                mode = agent.state.mode
                distance_traveled = agent.state.distance_km - prev_distance
                
                # Only calculate if positive distance (agent actually moved)
                if distance_traveled > 0:
                    emissions = emissions_calc.calculate_trip_emissions(
                        mode=mode,
                        distance_km=distance_traveled
                    )
                    
                    # Accumulate
                    lifecycle_emissions_by_mode[mode]['co2e_kg'] += emissions['co2e_kg']
                    lifecycle_emissions_by_mode[mode]['pm25_g'] += emissions['pm25_g']
                    lifecycle_emissions_by_mode[mode]['nox_g'] += emissions['nox_g']
                    
                    # Add to air quality tracker
                    if air_quality and agent.state.location:
                        air_quality.add_emissions(
                            location=agent.state.location,
                            emissions=emissions
                        )
            
            # Infrastructure interaction
            if infrastructure and agent.state.mode in ['ev', 'van_electric', 'truck_electric', 'hgv_electric']:
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

                                    # Record charging revenue
                                    if policy_engine:
                                        station = infrastructure.charging_stations.get(station_id)
                                        if station:
                                            # Estimate energy needed (rough calculation)
                                            kwh_needed = (trip_distance / 5) * 20  # ~20 kWh per 5km
                                            charging_cost = kwh_needed * station.cost_per_kwh
                                            record_charging_revenue(policy_engine, charging_cost)
                
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
        
        # Air quality step (atmospheric dispersion) - MUST BE OUTSIDE AGENT LOOP
        # TO AVOID DOUBLE COUNTING EMISSIONS
        if air_quality:
            wind_speed = weather_conditions.get('wind_speed', 10.0) if weather_manager else 10.0
            air_quality.step(wind_speed_kmh=wind_speed)
            
            # Check for exceedances every hour
            if step % 60 == 0:
                exceedances = air_quality.check_exceedances('hourly')
                if exceedances:
                    logger.warning(f"Step {step}: {len(exceedances)} air quality exceedances")
                    
        # Record this timestep (use 'agent_states' to match UI expectations)
        time_series.append({
            'step': step,
            'agent_states': agent_states,
            'metrics': {}  # Empty metrics for compatibility
        })
        
        # Record adoption
        record_adoption()
        
        # Detect cascades (simplified - checks for rapid mode shifts)
        if step > 0 and step % 10 == 0:
            for mode in adoption_history.keys():
                current = adoption_history[mode][-1]
                previous = adoption_history[mode][-10] if len(adoption_history[mode]) >= 10 else adoption_history[mode][0]
                
                if current > previous * 1.5:  # 50% increase
                    cascade_events.append({
                        'step': step,
                        'mode': mode,
                        'growth': (current - previous) / max(previous, 1)
                    })
    
    if progress_callback:
        progress_callback(0.95, "✅ Simulation complete")
    
    # Final logging
    logger.info("✅ Simulation complete")
    logger.info(f"   Cascades detected: {len(cascade_events)}")
    if weather_manager:
        logger.info(f"   Weather timesteps tracked: {len(weather_history)}")
    
    results = {
        'time_series': time_series,
        'adoption_history': dict(adoption_history),
        'cascade_events': cascade_events,
        'lifecycle_emissions': dict(lifecycle_emissions_by_mode),
        'weather_manager': weather_manager,
        'weather_history': weather_history,  # Add weather history
        'air_quality_tracker': air_quality,
    }
    
    # Add dynamic policy results if available
    if policy_engine:
        # Get final policy report
        final_report = get_final_policy_report(policy_engine)
        
        if final_report:
            results['policy_actions'] = policy_actions_taken
            results['constraint_violations'] = constraint_violations
            results['cost_recovery_history'] = cost_recovery_history
            results['final_cost_recovery'] = final_report['cost_recovery']
            results['policy_status'] = final_report['policy_status']
        
        logger.info(f"✅ Policy tracking: {len(policy_actions_taken)} actions, "
                   f"{len(constraint_violations)} violations")
    
    return results