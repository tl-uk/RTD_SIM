"""
simulation/execution/simulation_loop.py

Main simulation loop execution with metrics tracking.
Infrastructure policy application with correct variable references.
"""

from __future__ import annotations
import random
import logging
from typing import Any, Dict, Optional, List
from pathlib import Path
from collections import defaultdict

from simulation.config.simulation_config import SimulationConfig

# Belief updating and Markov mode switching
try:
    from agent.bayesian_belief_updater import BayesianBeliefUpdater
    BELIEF_UPDATER_AVAILABLE = True
except ImportError:
    BELIEF_UPDATER_AVAILABLE = False
from simulation.spatial_environment import SpatialEnvironment
from simulation.execution.timeseries import TimeSeries
from simulation.time.temporal_engine import create_temporal_engine_from_config
from simulation.events.synthetic_generator import (
    create_event_generator_from_config,
    EventType
)

from analytics import (
    JourneyTracker,
    ModeShareAnalyzer,
    PolicyImpactAnalyzer,
    NetworkEfficiencyTracker
)

from simulation.execution.dynamic_policies import (
    initialize_policy_engine,
    apply_dynamic_policies as _infra_apply_dynamic_policies,  # renamed — SD import may override
    record_charging_revenue,
    get_final_policy_report
)

logger = logging.getLogger(__name__)

# Event System
try:
    from events.event_bus_safe import SafeEventBus
    EVENT_BUS_AVAILABLE = True
except ImportError:
    EVENT_BUS_AVAILABLE = False
    logger.warning("⚠️ Event bus not available")
    SafeEventBus = None

# System Dynamics
from agent.system_dynamics import StreamingSystemDynamics
try:
    from simulation.execution.system_dynamics_integration import (
        initialize_system_dynamics,      # ← was missing — caused always-None SD engine
        apply_dynamic_policies,          # augmented version that includes SD feedback
        update_system_dynamics,
        get_system_dynamics_history
    )
    SYSTEM_DYNAMICS_AVAILABLE = True
except ImportError:
    SYSTEM_DYNAMICS_AVAILABLE = False
    logger.warning("⚠️ System Dynamics integration module not available — using direct init")

    # Restore infrastructure apply_dynamic_policies so policy engine still works
    apply_dynamic_policies = _infra_apply_dynamic_policies

    def initialize_system_dynamics(config: SimulationConfig) -> Optional[StreamingSystemDynamics]:
        """
        Direct fallback: instantiate StreamingSystemDynamics when
        system_dynamics_integration is unavailable.
        config.system_dynamics must be a SystemDynamicsConfig instance
        (sidebar_config.py always creates one: config.system_dynamics = SystemDynamicsConfig()).
        """
        sd_config = getattr(config, 'system_dynamics', None)
        if sd_config is None:
            logger.warning(
                "⚠️ System Dynamics not enabled: config.system_dynamics is None. "
                "sidebar_config.py should always set this — check render_sidebar_config()."
            )
            return None
        try:
            engine = StreamingSystemDynamics(sd_config)
            logger.info("✅ System Dynamics engine initialized (direct fallback)")
            return engine
        except Exception as exc:
            logger.error("❌ System Dynamics direct init failed: %s", exc)
            return None

    def update_system_dynamics(system_dynamics, step, agents, infrastructure, dt=1.0):
        if system_dynamics is None:
            return []
        try:
            if hasattr(system_dynamics, 'step'):
                result = system_dynamics.step(
                    agents=agents, infrastructure=infrastructure, dt=dt
                )
                return result if isinstance(result, list) else []
        except Exception as exc:
            logger.debug("SD update error at step %d: %s", step, exc)
        return []

    def get_system_dynamics_history(system_dynamics):
        if system_dynamics is None:
            return []
        try:
            if hasattr(system_dynamics, 'get_history'):
                return system_dynamics.get_history()
            if hasattr(system_dynamics, 'history'):
                return system_dynamics.history
        except Exception:
            pass
        return []

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
    ScenarioManager = None

# Environmental modules (weathers, emissions, air quality)
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
    
    class _FallbackWeatherManager:
        """Fallback weather manager when real weather system unavailable."""
        def get_mode_speed_multiplier(self, mode: str) -> float:
            """Return neutral multiplier (no weather impact)."""
            return 1.0
    
    def create_weather_manager(config) -> Optional[object]:
        """Fallback: return minimal weather manager if weather not available."""
        return _FallbackWeatherManager()
    
    def get_combined_multipliers(month, day_of_year, day_of_week, hour):
        """Fallback: return neutral multipliers."""
        modes = ['walk', 'bike', 'car', 'ev', 'bus', 'tram', 
                 'van_diesel', 'van_electric', 'truck_diesel', 'truck_electric']
        return {mode: 1.0 for mode in modes}
    
    def apply_seasonal_ev_range_penalty(base_range_km, temperature_c):
        """Fallback: return unchanged range."""
        return base_range_km
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
        if ScenarioManager is None:
            logger.error("ScenarioManager not available (import failed)")
            return None
        
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
        # Apply infrastructure policies
        # ====================================================================
        infrastructure_changes = {}
        
        # Get scenario data (use manager.active_scenario instead of undefined 'scenario')
        if manager.active_scenario and config.infrastructure:
            scenario_data = manager.active_scenario
            
            for policy in getattr(scenario_data, 'policies', []):
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

        # Collect mode-level cost policies so the BDI planner can apply them.
        # The scenario YAML declares cost_reduction/cost_increase with target:mode
        # but apply_to_environment() only touches the road network — not the BDI
        # cost function. We surface the raw policies so simulation_runner.py can
        # call planner.apply_scenario_cost_factors(report['mode_cost_policies']).
        mode_cost_policies = []
        if manager.active_scenario:
            for policy in manager.active_scenario.get('policies', []):
                if policy.get('target') == 'mode' and policy.get('parameter') in (
                    'cost_reduction', 'cost_increase', 'cost_factor'
                ):
                    mode_cost_policies.append(policy)
        report['mode_cost_policies'] = mode_cost_policies
        if mode_cost_policies:
            logger.info(
                "📋 Mode cost policies surfaced for BDI planner: %s",
                [(p.get('mode'), p.get('parameter'), p.get('value')) for p in mode_cost_policies],
            )
            # Store on config so run_simulation_loop can wire them to agent planners
            # without needing simulation_runner.py to be modified.
            config._scenario_mode_policies = mode_cost_policies

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
        policy_engine=None,  # Pass policy engine for event bus access
        event_bus=None,  # Phase 6.2b: Event bus from policy initialization
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

    # ====================================================================
    # Phase 7.1: Initialize Temporal Engine
    # ====================================================================
    temporal_engine = create_temporal_engine_from_config(config)
    
    if temporal_engine:
        logger.info("⏰ Temporal scaling enabled")
        summary = temporal_engine.get_summary()
        logger.info(f"   Time scale: {summary['time_scale']}")
        logger.info(f"   Duration: {summary['duration']}")
        logger.info(f"   From {summary['start_date']} to {summary['end_date']}")
    else:
        logger.info("⏰ Temporal scaling disabled (using default time)")

    # ====================================================================
    # Phase 7.2: Initialize Synthetic Event Generator
    # ====================================================================
    event_generator = create_event_generator_from_config(config)
    
    if event_generator:
        logger.info("🎲 Synthetic event generator initialized")
        summary = event_generator.get_summary()
        logger.info(f"   Traffic: {'enabled' if summary['traffic_enabled'] else 'disabled'}")
        logger.info(f"   Weather: {'enabled' if summary['weather_enabled'] else 'disabled'}")
        logger.info(f"   Infrastructure: {'enabled' if summary['infrastructure_enabled'] else 'disabled'}")
    else:
        event_generator = None
        logger.info("🎲 Synthetic events disabled")

    # ====================================================================
    # Event Bus Setup
    # ====================================================================
    # NOTE: Event bus is now created in policy_initialization.py and passed as parameter
    # This ensures policy engine and agents use the SAME event bus instance
    
    if event_bus and config.enable_event_bus:
        try:
            logger.info(f"✅ Using event bus from policy engine (mode: {event_bus.get_mode()})")
            
            # Register agents for spatial filtering
            if event_bus.is_available():
                for agent in agents:
                    try:
                        lat, lon = agent.state.location[1], agent.state.location[0]
                        event_bus.register_agent(
                            agent.state.agent_id,
                            lat=lat,
                            lon=lon,
                            perception_radius_km=config.agent_perception_radius_km
                        )
                    except Exception as e:
                        logger.debug(f"Agent registration failed: {e}")
                
                logger.info(f"📍 Registered {len(agents)} agents with event bus")
            
            # Subscribe agents to events (if enabled)
            logger.info(f"🔍 DEBUG: config.enable_agent_event_subscription = {config.enable_agent_event_subscription}")
            logger.info(f"🔍 DEBUG: Number of agents = {len(agents)}")
            
            if config.enable_agent_event_subscription:
                logger.info("✅ Agent subscription is ENABLED, proceeding...")
                subscribed = 0
                failed = 0
                no_method = 0
                
                for agent in agents:
                    if hasattr(agent, 'subscribe_to_events'):
                        try:
                            agent.subscribe_to_events(event_bus)
                            subscribed += 1
                        except Exception as e:
                            failed += 1
                            logger.error(f"❌ Agent subscription failed: {e}")
                    else:
                        no_method += 1
                
                logger.info(f"📊 Subscription results:")
                logger.info(f"   ✅ Subscribed: {subscribed}")
                logger.info(f"   ❌ Failed: {failed}")
                logger.info(f"   ⚠️  No method: {no_method}")
                
                if subscribed > 0:
                    logger.info(f"🎧 Subscribed {subscribed} agents to events")
                else:
                    logger.warning(f"⚠️ NO agents subscribed!")
                    logger.warning(f"   - Agents without method: {no_method}")
                    logger.warning(f"   - Failed subscriptions: {failed}")
            else:
                logger.warning("⚠️ Agent subscription is DISABLED in config!")
                logger.warning(f"   enable_event_bus={config.enable_event_bus}")
                logger.warning(f"   enable_agent_event_subscription={config.enable_agent_event_subscription}")
                
        except Exception as e:
            logger.warning(f"⚠️ Event bus setup failed: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            event_bus = None
    elif config.enable_event_bus and not event_bus:
        logger.warning("⚠️ Event bus requested but not provided by policy initialization")
    else:
        logger.info("➖ Event bus disabled in config")
    
    # Check if event bus was requested but not available
    if config.enable_event_bus and not EVENT_BUS_AVAILABLE:
        logger.warning("⚠️ Event bus requested but not available (import failed)")

    # Policy tracking
    policy_actions_taken = []
    constraint_violations = []
    cost_recovery_history = []
    
    # Track mode adoption over time
    def record_adoption():
        """Record current mode distribution across ALL modes."""
        mode_counts = defaultdict(int)
        for agent in agents:
            mode = agent.state.mode
            mode_counts[mode] += 1

        # Complete mode list — matches MODES registry in modes.py.
        # Previously this list omitted transit and rail modes, making
        # local_train, bus, tram, etc. invisible in tipping-point detection.
        all_modes = [
            # Active
            'walk', 'bike', 'e_scooter', 'cargo_bike',
            # Road – personal
            'car', 'ev', 'taxi_ev', 'taxi_diesel',
            # Road – commercial
            'bus', 'tram',
            # Road – freight
            'van_electric', 'van_diesel',
            'truck_electric', 'truck_diesel',
            'hgv_electric', 'hgv_diesel', 'hgv_hydrogen',
            # Rail
            'local_train', 'intercity_train', 'freight_rail',
            # Maritime
            'ferry_diesel', 'ferry_electric',
            # Aviation
            'flight_domestic', 'flight_electric',
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
        
        # Connect weather to policy engine
        if policy_engine:
            policy_engine.weather_manager = weather_manager
            logger.info("✅ Policy engine connected to weather system")
    
    air_quality = create_air_quality_tracker(config) if config.track_air_quality else None
    emissions_calc = LifecycleEmissions(config.grid_carbon_intensity) if config.use_lifecycle_emissions else None
    
    # Track lifecycle emissions
    lifecycle_emissions_by_mode = defaultdict(lambda: {'co2e_kg': 0, 'pm25_g': 0, 'nox_g': 0})
 
    # Initialize analytics
    journey_tracker = JourneyTracker() if config.track_journeys else None
    mode_share_analyzer = ModeShareAnalyzer() if config.enable_analytics else None
    policy_impact_analyzer = PolicyImpactAnalyzer(policy_engine) if config.calculate_policy_roi else None
    network_efficiency = NetworkEfficiencyTracker() if config.track_network_efficiency else None
    
    # ------------ FIX WARNING AND ENABLE POLICIES ---------
    if policy_engine is None:
        try:
            policy_engine = initialize_policy_engine(config, infrastructure)
            if policy_engine:
                logger.info("✅ Dynamic Policy Engine initialized successfully.")
        except Exception as e:
            logger.warning(f"⚠️ Could not initialize Dynamic Policy Engine: {e}")
    # -------------------------------------------------------

    # Capture baseline before any policies
    if policy_impact_analyzer and policy_engine:
        policy_impact_analyzer.capture_baseline(
            step=0,
            agents=agents,
            emissions_tracker=emissions_calc,
            infrastructure=infrastructure
        )
    
    # Initialize System Dynamics
    system_dynamics = None
    
    if SYSTEM_DYNAMICS_AVAILABLE:
        system_dynamics = initialize_system_dynamics(config)
        if system_dynamics:
            logger.info("✅ System Dynamics initialized")

    # Main simulation loop
    # Phase 2: Bayesian belief updater — shared across all agents, stateless
    belief_updater = BayesianBeliefUpdater() if BELIEF_UPDATER_AVAILABLE else None
    # Per-agent, per-mode satisfaction tracking for the belief updater
    satisfaction_by_mode: dict = {}   # mode → [float]

    # Fix 2: build agent index so peer signal lookup works
    if belief_updater and agents:
        belief_updater.rebuild_agent_index(agents)

    # Wire scenario mode-cost factors to every agent's BDI planner.
    # apply_scenario_policies() surfaces mode-level cost_reduction policies
    # via config's scenario_report. Without this, EV Subsidy 30% (and any
    # other YAML cost policy targeting a mode) was loaded but never applied —
    # the BDI cost function saw no multiplier and chose modes purely on the
    # unmodified cost weights.
    _scenario_mode_policies = getattr(config, '_scenario_mode_policies', [])
    if _scenario_mode_policies:
        _planners_updated = 0
        for _agent in agents:
            _planner = getattr(_agent, 'planner', None)
            if _planner and hasattr(_planner, 'apply_scenario_cost_factors'):
                _planner.apply_scenario_cost_factors(_scenario_mode_policies)
                _planners_updated += 1
        if _planners_updated:
            logger.info(
                "💰 Scenario cost factors applied to %d agent planners: %s",
                _planners_updated,
                [(p.get('mode'), p.get('parameter'), p.get('value'))
                 for p in _scenario_mode_policies],
            )

    # ── Propagate generalised cost parameters into every agent's context ──────
    # The BDI cost function reads boarding_penalty_min, carbon_tax_gbp_tco2,
    # etc. from agent_context so that scenario policy changes (e.g. a carbon
    # tax hike) immediately shift the effective rail/road cost differential
    # without needing a full replanning cycle.
    #
    # Defaults match _DEFAULT_POLICY in router.py so results are consistent
    # whether cost() or Router.compute_route() is called first.
    _gen_cost_defaults = {
        'boarding_penalty_min': 20.0,    # walk-to-station + wait
        'carbon_tax_gbp_tco2': 0.0,      # £0 default (no carbon tax)
        'energy_price_gbp_km': 0.12,     # ~12p/km road energy
        'value_of_time_gbp_h': 10.0,     # UK DfT avg VoT
    }
    # Extract scenario-level overrides from active scenario policies
    if _scenario_mode_policies:
        for _pol in _scenario_mode_policies:
            _param = _pol.get('parameter', '')
            _val   = _pol.get('value', None)
            if _param == 'carbon_tax' and _val is not None:
                _gen_cost_defaults['carbon_tax_gbp_tco2'] = float(_val)
            elif _param == 'boarding_penalty_min' and _val is not None:
                _gen_cost_defaults['boarding_penalty_min'] = float(_val)
            elif _param == 'energy_price_gbp_km' and _val is not None:
                _gen_cost_defaults['energy_price_gbp_km'] = float(_val)

    for _agent in agents:
        ctx = getattr(_agent, 'agent_context', None)
        if ctx is not None:
            for k, v in _gen_cost_defaults.items():
                ctx.setdefault(k, v)   # don't overwrite if FusedIdentity already set it

    logger.debug(
        "Generalised cost params seeded into %d agent contexts: %s",
        len(agents), _gen_cost_defaults,
    )

    for step in range(config.steps):
        # Initialize agent states for this step
        agent_states = []
        
        # Initialize time variables with defaults
        time_of_day = (step % 1440) / 60.0  # hours (assuming 1 step = 1 min)
        hour = int(time_of_day)
        month = config.season_month or 6  # Default to summer
        day_of_year = config.season_day_of_year or 180
        day_of_week = (step // 1440) % 7  # Assuming day 0 is Monday
        current_datetime = None
        
        # === PHASE 7.1: Get time info from temporal engine ===
        if temporal_engine:
            time_info = temporal_engine.get_time_info(step)
            time_of_day = time_info['hour'] + (time_info['datetime'].minute / 60.0)
            hour = time_info['hour']
            month = time_info['month']
            day_of_year = time_info['day_of_year']
            day_of_week = time_info['day_of_week']
            current_datetime = time_info['datetime']
            
            # Log progress with human-readable time (every 20 steps)
            if step % 20 == 0:
                logger.info(
                    f"Step {step}/{config.steps}: {time_info['date']} {time_info['time']} "
                    f"({temporal_engine.get_progress_string(step)})"
                )
        else:
            time_info = None
            current_datetime = None
        
        # === PHASE 7.2: GENERATE SYNTHETIC EVENTS ===
        if event_generator and time_info:
            new_events = event_generator.generate_events_for_step(step, time_info)
            
            if new_events:
                event_icons = {
                    'traffic_congestion': '🚗',
                    'weather_disruption': '🌧️',
                    'infrastructure_failure': '🔌',
                    'grid_stress': '⚡',
                }
                
                for event in new_events:
                    icon = event_icons.get(event.event_type.value, '🎲')
                    logger.info(f"{icon} Event: {event.description} ({event.duration_steps} steps)")
                    
                    if event.event_type == EventType.WEATHER_DISRUPTION:
                        weather_type = event.impact_data.get('weather_type', 'unknown')
                        logger.info(f"   Weather type: {weather_type}, "
                                   f"Impact: {event.impact_data}")
                    
                    # Publish to event bus if available
                    # event is a BaseEvent object — use publish() directly
                    if event_bus and event_bus.is_available():
                        event_bus.publish(event)
        
        # UPDATE WEATHER
        else:
            # Fallback to old method if temporal engine not enabled
            time_of_day = (step % 1440) / 60.0  # hours (assuming 1 step = 1 min)
            hour = int(time_of_day)
            month = config.season_month or 6  # Default to summer
            day_of_year = config.season_day_of_year or 180
            day_of_week = (step // 1440) % 7  # Assuming day 0 is Monday
            current_datetime = None
        
        # UPDATE WEATHER
        if weather_manager:
            try:
                # Update weather (fetches new data if needed and applies adjustments)
                weather_conditions = weather_manager.update_weather(step, time_of_day)
                
                # Store in history
                if hasattr(weather_history, 'append'):
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
            except Exception as e:
                logger.error(f"Weather update failed: {e}")
                # Fallback to current conditions if update fails
                weather_conditions = getattr(weather_manager, 'current_conditions', {
                    'temperature': 10.0,
                    'precipitation': 0.0,
                    'wind_speed': 10.0,
                    'ice_warning': False,
                    'snow_depth': 0.0,
                    'cloud_cover': 50,
                    'visibility': 10000,
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
            # Snapshot per-station utilization so get_hotspots() and
            # get_avg_utilization() have real data to work with.
            infrastructure.stations.record_all_utilization()
        
        # Apply dynamic policies
        policy_result = None
        if policy_engine:
            policy_result = apply_dynamic_policies(
                policy_engine=policy_engine,
                step=step,
                agents=agents,
                env=env,
                infrastructure=infrastructure
            )
            
            # Track policy actions
            if policy_result and policy_result.get('actions_taken'):
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
        
        # UPDATE SYSTEM DYNAMICS
        if system_dynamics:
            # Derive real infrastructure capacity from the current charger count and
            # write it directly onto the SD state BEFORE calling update_system_dynamics.
            #
            # Why direct assignment rather than a kwarg:
            #   update_system_dynamics() (defined in system_dynamics_integration.py)
            #   has the signature (sd, step, agents, infra, dt=1.0) — it does not accept
            #   infrastructure_capacity as a parameter.  Bypassing the wrapper and setting
            #   the stock directly on the StreamingSDState dataclass is the correct
            #   approach: it matches what sd.update() does internally at line 259, keeps
            #   the value time-varying so SHAP sees a non-constant infrastructure_effect,
            #   and doesn't require changes to the integration module.
            try:
                if infrastructure is not None:
                    _infra_capacity = float(len(infrastructure.charging_stations))
                else:
                    _infra_capacity = 100.0   # baseline — no infrastructure manager
                system_dynamics.state.infrastructure_capacity_stock = _infra_capacity
            except Exception as _infra_err:
                logger.debug("Could not update infrastructure_capacity_stock: %s", _infra_err)

            sd_events = update_system_dynamics(
                system_dynamics=system_dynamics,
                step=step,
                agents=agents,
                infrastructure=infrastructure,
                dt=1.0,
            )
            
            # Log significant SD events
            for event in sd_events:
                if event.severity in ['high', 'critical']:
                    logger.info(f"🎯 SD Event @ step {step}: {event.event_type}")

        # RECORD MODE SHARE (for tipping point detection)
        if mode_share_analyzer:
            mode_share_analyzer.record_step(step, agents, len(agents))
        
        # RECORD INFRASTRUCTURE STATE
        if network_efficiency:
            network_efficiency.record_infrastructure_state(step, infrastructure)
        
        # Agent steps
        for agent in agents:
            prev_location = agent.state.location
            prev_mode = agent.state.mode
            prev_distance = agent.state.distance_km
            
            # Execute agent step
            try:
                agent.step(env)
            except:
                agent.step()
            
            # Route-status trace (DEBUG only — does not appear in production logs)
            if step <= 2:
                route_info = "None"
                if hasattr(agent.state, 'route'):
                    route_info = f"{len(agent.state.route)} points" if agent.state.route else "empty/None"
                logger.debug(f"      After step: agent={agent.state.agent_id}, route={route_info}, distance={agent.state.distance_km:.1f}km, arrived={agent.state.arrived}")


            # Phase 6.2b: Update agent locations in event bus (if agents moved)
            if event_bus and event_bus.is_available():
                for other_agent in agents:  # MUST Use different variable name
                    # Only update if agent has moved (check if attribute exists)
                    if hasattr(other_agent, 'has_moved') and other_agent.has_moved:
                        try:
                            event_bus.update_agent_location(
                                agent_id=other_agent.agent_id,
                                lat=other_agent.state.latitude,
                                lon=other_agent.state.longitude
                            )
                        except Exception as e:
                            logger.debug(f"Location update failed: {e}")

            # RECORD JOURNEY
            if journey_tracker and agent.state.location != prev_location:
                # Gather context
                decision_factors = getattr(agent, 'last_decision_factors', {})
                social_influence = {
                    'influenced_by': getattr(agent, 'influenced_by_agents', []),
                    'strength': getattr(agent, 'influence_strength', 0.0)
                }
                
                # Get emissions for this trip
                trip_distance = agent.state.distance_km - prev_distance
                trip_emissions = None
                if emissions_calc and trip_distance > 0:
                    trip_emissions = emissions_calc.calculate_trip_emissions(
                        mode=agent.state.mode,
                        distance_km=trip_distance
                    )
                
                if journey_tracker:
                    # === PHASE 7.2: Get weather from active synthetic events ===
                    weather_impact = {
                        'temperature': 10.0,
                        'precipitation': 0.0,
                        'ice_warning': False,
                    }
                    
                    if event_generator:
                        active_events = event_generator.get_active_events()
                        for event in active_events:
                            if event.event_type == EventType.WEATHER_DISRUPTION:
                                weather_type = event.impact_data.get('weather_type', 'unknown')
                                
                                # Map weather type to journey tracker format
                                if weather_type in ['snow', 'ice']:
                                    weather_impact['temperature'] = -5.0
                                    weather_impact['ice_warning'] = True
                                elif weather_type in ['rain', 'heavy_rain']:
                                    weather_impact['precipitation'] = 5.0
                                elif weather_type == 'wind':
                                    weather_impact['temperature'] = 5.0
                    
                    journey_tracker.record_journey(
                        agent=agent,
                        step=step,
                        weather_conditions=weather_impact,
                        emissions=trip_emissions,             # calculated above; None when no movement
                    )
            
            # RECORD MODE TRANSITION
            if mode_share_analyzer and prev_mode != agent.state.mode:
                mode_share_analyzer.record_transition(
                    agent_id=agent.state.agent_id,  # NOTE: Use agent.state.agent_id
                    step=step,
                    from_mode=prev_mode,
                    to_mode=agent.state.mode,
                    reason=getattr(agent, 'switch_reason', 'unknown'),
                    influenced_by=getattr(agent, 'influenced_by_agents', [])
                )
            
            # RECORD VKT
            if network_efficiency:
                trip_distance = agent.state.distance_km - prev_distance
                if trip_distance > 0:
                    vehicle_type = agent.agent_context.get('vehicle_type', 'personal')
                    network_efficiency.record_vehicle_travel(
                        agent_id=agent.state.agent_id,  # NOTE: Use agent.state.agent_id
                        mode=agent.state.mode,
                        distance_km=trip_distance,
                        vehicle_type=vehicle_type,
                        step=step
                    )
            
            # ── Infrastructure interaction — EV charging ───────────────────
            # This block MUST be inside `for agent in agents` so every EV agent
            # gets a charging opportunity each step, not just the last one.
            if infrastructure and agent.state.mode in ['ev', 'van_electric', 'truck_electric', 'hgv_electric']:
                _agent_id = agent.state.agent_id
                try:
                    if _agent_id not in infrastructure.agent_charging_state:
                        # Guard: location must be valid before calling find_nearest_charger
                        _loc = agent.state.location
                        if _loc is None or len(_loc) < 2:
                            pass  # agent not yet placed — skip this step
                        else:
                            # Trigger charging when: arrived, or has travelled > 3km,
                            # or 10% random chance on shorter trips (urban top-up).
                            _should_charge = (
                                agent.state.arrived or
                                agent.state.distance_km > 3.0 or
                                (agent.state.distance_km > 1.0 and random.random() < 0.1)
                            )

                            if _should_charge:
                                _nearest = infrastructure.find_nearest_charger(
                                    location=_loc,
                                    charger_type='any',
                                    max_distance_km=5.0,
                                )

                                if _nearest:
                                    _station_id, _dist_km = _nearest
                                    _trip_dist = agent.state.distance_km or 5.0

                                    if _trip_dist < 5.0:
                                        _charge_dur = random.uniform(15, 30)
                                    elif _trip_dist < 15.0:
                                        _charge_dur = random.uniform(30, 60)
                                    else:
                                        _charge_dur = random.uniform(60, 120)

                                    _success = infrastructure.reserve_charger(
                                        _agent_id, _station_id, duration_min=_charge_dur
                                    )

                                    if _success:
                                        infrastructure.agent_charging_state[_agent_id]['status'] = 'charging'
                                        infrastructure.agent_charging_state[_agent_id]['start_time'] = step
                                        logger.debug(
                                            f"Step {step}: {_agent_id} charging at {_station_id} "
                                            f"({_dist_km:.1f}km away, {_charge_dur:.0f}min)"
                                        )
                                        if policy_engine:
                                            _station = infrastructure.charging_stations.get(_station_id)
                                            if _station:
                                                _kwh = (_trip_dist / 5.0) * 20.0
                                                record_charging_revenue(policy_engine, _kwh * _station.cost_per_kwh)

                    else:
                        # Already charging — check if session is complete
                        _cs = infrastructure.agent_charging_state[_agent_id]
                        if _cs.get('status') == 'charging':
                            _elapsed = (step - _cs.get('start_time', step)) * 1.0
                            if _elapsed >= _cs.get('duration_min', 999):
                                infrastructure.release_charger(_agent_id)
                                logger.debug(f"Step {step}: {_agent_id} finished charging ({_elapsed:.0f}min)")

                except Exception as _e:
                    # Never let a charging error crash the simulation step.
                    # Log at debug level to avoid flooding INFO logs.
                    logger.debug(f"Step {step}: charging error for {_agent_id}: {_e}")


            # ── Phase 3: Markov record_step ──────────────────────────────────
            # Called every step the agent has a mode, regardless of policy
            # engine, social network, or influence system availability.
            # Uses a lightweight satisfaction proxy when the full calculation
            # isn't available — sufficient for habit formation purposes.
            _mc = getattr(agent, 'mode_chain', None)
            if _mc is not None:
                try:
                    _mc_mode = getattr(agent.state, 'mode', None)
                    if _mc_mode:
                        # Use the real satisfaction score if it was computed
                        # this step (set by the influence block above).
                        # Otherwise use a proxy: distance > 0 and not stuck = 0.6
                        _mc_sat = satisfaction_by_mode.get(_mc_mode, [0.6])[-1] \
                            if satisfaction_by_mode.get(_mc_mode) else 0.6
                        _mc.record_step(_mc_mode, _mc_sat)
                except Exception as _mce:
                    logger.debug("Markov record_step failed: %s", _mce)
            # ── End Phase 3 ──────────────────────────────────────────────────

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
            
            # Collect agent state at END of agent loop iteration
            # This MUST be at 12 spaces (inside `for agent in agents`)
            # and MUST be AFTER all agent processing for this step
            agent_states.append({
                'agent_id':         agent.state.agent_id,
                'location':         agent.state.location,
                'mode':             agent.state.mode,
                'arrived':          agent.state.arrived,
                'route':            agent.state.route,
                'distance_km':      agent.state.distance_km,
                'emissions_g':      agent.state.emissions_g,
                # ── Multimodal segment colouring ──────────────────────────────
                # route_segments: list of {'path':…,'mode':…,'label':…} dicts
                # from _intermodal_with_segments / _gtfs_with_segments.
                # visualization.py reads this to draw each leg in its own colour.
                # Without this copy, walk legs are invisible — visualization only
                # sees state.get('route_segments') from THIS dict, not agent.state.
                'route_segments':   getattr(agent.state, 'route_segments', []),
                # trip_chain serialised dict for journey_tracker and analytics
                'trip_chain':       (
                    agent.state.trip_chain.to_dict()
                    if getattr(agent.state, 'trip_chain', None) is not None
                       and hasattr(agent.state.trip_chain, 'to_dict')
                    else None
                ),
                # ── Tooltip labels ────────────────────────────────────────────
                'origin_name':      getattr(agent.state, 'origin_name',      ''),
                'destination_name': getattr(agent.state, 'destination_name', ''),
                'service_id':       getattr(agent.state, 'service_id',       ''),
                'destination_stop': getattr(agent.state, 'destination_stop', ''),
            })
        
        # POLICY IMPACT TRACKING
        # Guard: `agent` is the loop variable from `for agent in agents` above.
        # If agents list is empty the variable is never bound → UnboundLocalError.
        if agents and policy_impact_analyzer and policy_engine:
            # Capture snapshots periodically
            if step % 20 == 0:
                policy_impact_analyzer.capture_step_snapshot(
                    step=step,
                    agents=agents,
                    emissions_tracker=emissions_calc,
                    infrastructure=infrastructure
                )
            
            # Record policy activations from this step's results
            if policy_result.get('actions_taken'):
                for action in policy_result['actions_taken']:
                    action_name = action.get('action', 'unknown_policy')
                    policy_impact_analyzer.record_policy_activation(action_name, step)
            
            # Social influence (if enabled)
            if network and SOCIAL_AVAILABLE:
                mode_costs = getattr(agent.state, 'mode_costs', {})
                if mode_costs:
                    adjusted = network.apply_social_influence(
                        agent.state.agent_id,
                        mode_costs,
                        influence_strength=getattr(config, 'influence_strength', 0.2),
                        conformity_pressure=getattr(config, 'conformity_pressure', 0.3),
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

                    # Phase 2: accumulate satisfaction by mode for belief updater
                    _mode = agent.state.mode
                    if _mode not in satisfaction_by_mode:
                        satisfaction_by_mode[_mode] = []
                    satisfaction_by_mode[_mode].append(satisfaction)

                    # Phase 3: update Markov chain with this step's outcome
                    # _chain = getattr(agent, 'mode_chain', None)
                    # if _chain is not None:
                    #     _chain.record_step(_mode, satisfaction)
            
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
            
            # (Infrastructure charging moved into the agent loop — see below)
        
        # Phase 2: Bayesian belief update every 5 steps (all agents)
        if belief_updater and step % 5 == 0:
            for _agent in agents:
                if hasattr(_agent, 'user_story'):
                    try:
                        _agent.state._agent_ref = _agent
                        belief_updater.update_agent(
                            agent=_agent,
                            step=step,
                            infrastructure=infrastructure,
                            network=network,
                            satisfaction_by_mode=satisfaction_by_mode,
                        )
                    except Exception as _be:
                        logger.debug("Belief update failed for %s: %s",
                                     _agent.state.agent_id, _be)
                        
        # Phase 3: Log Markov chain summaries every 50 steps
        # Writes to simulation log file via log_capture.py
        if step % 50 == 0 and step > 0:
            _markov_agents = [
                a for a in agents
                if getattr(a, 'mode_chain', None) is not None
            ]
            if _markov_agents:
                logger.info(
                    "─── Markov habit snapshot (step %d, %d agents) ───",
                    step, len(_markov_agents),
                )
                for _ma in _markov_agents[:10]:  # cap at 10 to keep log readable
                    _summary = _ma.mode_chain.summary()
                    _habits = _summary.get('habits', {})
                    _history = _summary.get('mode_history', [])
                    if _habits:
                        _habit_str = ", ".join(
                            f"{m}={p:.2f}" for m, p in
                            sorted(_habits.items(), key=lambda x: x[1], reverse=True)
                        )
                        logger.info(
                            "  %s [%s]: habits={%s} recent=%s",
                            _ma.state.agent_id,
                            _summary.get('persona', '?'),
                            _habit_str,
                            _history[-3:] if _history else [],
                        )

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

    # Phase 3: End-of-run Markov habit summary
    # Logged to simulation file so you can review habit formation after each run
    _markov_agents_final = [
        a for a in agents
        if getattr(a, 'mode_chain', None) is not None
    ]
    if _markov_agents_final:
        logger.info("=" * 60)
        logger.info("MARKOV HABIT FORMATION SUMMARY (end of run)")
        logger.info("=" * 60)
        logger.info(
            "  %-40s %-20s %-8s %-30s",
            "Agent ID", "Persona", "Steps", "Strongest Habits",
        )
        logger.info("  " + "-" * 100)
 
        for _ma in _markov_agents_final:
            _s = _ma.mode_chain.summary()
            _habits = _s.get('habits', {})
            _steps = _s.get('total_steps', 0)
            _persona = _s.get('persona', '?')
 
            if _habits:
                _top = sorted(_habits.items(), key=lambda x: x[1], reverse=True)[:3]
                _habit_str = "  ".join(f"{m}({p:.2f})" for m, p in _top)
            else:
                _habit_str = "none yet"
 
            logger.info(
                "  %-40s %-20s %-8d %s",
                _ma.state.agent_id[:40],
                _persona[:20],
                _steps,
                _habit_str,
            )
 
        # Aggregate: which modes have the strongest habits across the population
        _mode_habit_totals: dict = {}
        for _ma in _markov_agents_final:
            for _mode, _strength in _ma.mode_chain.summary().get('habits', {}).items():
                if _mode not in _mode_habit_totals:
                    _mode_habit_totals[_mode] = []
                _mode_habit_totals[_mode].append(_strength)
 
        if _mode_habit_totals:
            logger.info("")
            logger.info("  Population habit averages:")
            for _mode in sorted(
                _mode_habit_totals,
                key=lambda m: sum(_mode_habit_totals[m]) / len(_mode_habit_totals[m]),
                reverse=True,
            ):
                _vals = _mode_habit_totals[_mode]
                _avg = sum(_vals) / len(_vals)
                _n = len(_vals)
                logger.info(
                    "    %-20s avg=%.3f  n=%d agents with streak",
                    _mode, _avg, _n,
                )
 
        logger.info("=" * 60)

    # GENERATE ANALYTICS REPORTS
    analytics_summary = {}
    
    if journey_tracker:
        analytics_summary['journeys'] = journey_tracker.generate_summary_report()
        logger.info(f"📊 Recorded {len(journey_tracker.journeys)} journeys")
    
    if mode_share_analyzer:
        analytics_summary['mode_share'] = mode_share_analyzer.generate_summary_report()
        
        # Detect tipping points
        if config.detect_tipping_points:
            tipping_points = mode_share_analyzer.detect_tipping_points(
                min_velocity=config.tipping_point_velocity,
                min_duration=config.tipping_point_duration
            )
            logger.info(f"🎯 Detected {len(tipping_points)} tipping points")
            analytics_summary['tipping_points'] = tipping_points
    
    if policy_impact_analyzer:
        # Compute impact measurements and ROI for every policy that fired.
        # We need at least one step-snapshot captured during the run (every 20 steps).
        if (policy_impact_analyzer.policy_activations
                and len(policy_impact_analyzer.step_snapshots) >= 1):

            final_snapshot = policy_impact_analyzer.step_snapshots[-1]

            # Cost estimates per policy action (£) — expand as new actions are added
            _POLICY_COSTS = {
                'expand_grid_capacity':  500_000.0,
                'add_depot_chargers':    150_000.0,   # 3 depots × 10 chargers × £5k
                'add_emergency_chargers': 50_000.0,   # 10 chargers × £5k
                'add_chargers':           25_000.0,   # single station estimate
                'relocate_chargers':       5_000.0,   # labour only
            }
            _DEFAULT_COST = 10_000.0

            for policy_name, activation_step in policy_impact_analyzer.policy_activations.items():
                # Find the snapshot closest to (but not after) the activation step
                before_snapshot = policy_impact_analyzer.baseline
                for snap in policy_impact_analyzer.step_snapshots:
                    if snap.step <= activation_step:
                        before_snapshot = snap
                    else:
                        break

                if before_snapshot is None:
                    before_snapshot = final_snapshot  # degenerate fallback

                policy_impact_analyzer.measure_direct_impact(
                    policy_name=policy_name,
                    before_snapshot=before_snapshot,
                    after_snapshot=final_snapshot,
                    agents=agents,
                )

                # Estimate simulation duration in days (1 step ≈ 1 minute)
                sim_days = config.steps / 1440.0

                policy_impact_analyzer.calculate_roi(
                    policy_name=policy_name,
                    implementation_cost=_POLICY_COSTS.get(policy_name, _DEFAULT_COST),
                    operating_cost_annual=_POLICY_COSTS.get(policy_name, _DEFAULT_COST) * 0.1,
                    simulation_duration_days=max(sim_days, 1.0),
                )

        analytics_summary['policy_impact'] = policy_impact_analyzer.generate_summary_report()
        logger.info(f"💰 Evaluated {len(policy_impact_analyzer.impacts)} policy impacts")
    
    if network_efficiency:
        analytics_summary['network_efficiency'] = network_efficiency.generate_summary_report()
        
        # Identify bottlenecks
        bottlenecks = network_efficiency.identify_bottlenecks(infrastructure)
        logger.info(f"🚧 Identified {len(bottlenecks)} bottlenecks")
        analytics_summary['bottlenecks'] = bottlenecks
    
    results = {
        'time_series': time_series,
        'adoption_history': dict(adoption_history),
        'cascade_events': cascade_events,
        # Analytics
        'journey_tracker': journey_tracker,
        'mode_share_analyzer': mode_share_analyzer,
        'policy_impact_analyzer': policy_impact_analyzer,
        'network_efficiency_tracker': network_efficiency,
        'analytics_summary': analytics_summary,

        'lifecycle_emissions': dict(lifecycle_emissions_by_mode),
        'weather_manager': weather_manager,
        'weather_history': weather_history,  # Add weather history
        'air_quality_tracker': air_quality,
        
        # System Dynamics
        'system_dynamics_history': get_system_dynamics_history(system_dynamics),

        # Phase 7.1
        'temporal_engine': temporal_engine,  
        'event_generator': event_generator,  # Phase 7.2
    }

    # ── GTFS post-simulation analytics ────────────────────────────────────────
    if getattr(config, 'run_gtfs_analytics', False):
        try:
            from simulation.gtfs.gtfs_analytics import run_full_gtfs_analysis
            gtfs_report = run_full_gtfs_analysis(
                agents         = agents,
                results        = results,
                env            = env,
                policy_context = _gen_cost_defaults,
            )
            results['gtfs_analytics'] = gtfs_report
            logger.info("✅ GTFS analytics complete")
        except Exception as _gtfs_err:
            logger.warning("GTFS analytics failed (non-fatal): %s", _gtfs_err)
            results['gtfs_analytics'] = None
    
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
        
    # Cleanup event bus
    if event_bus:
        try:
            stats = event_bus.get_statistics()
            logger.info("📊 Event bus statistics:")
            logger.info(f"   - Mode: {stats.get('mode', 'unknown')}")
            logger.info(f"   - Events published: {stats.get('events_published', 0)}")
            logger.info(f"   - Events received: {stats.get('events_received', 0)}")
            
            event_bus.close()
            logger.info("Event bus closed cleanly")
        except Exception as e:
            logger.debug(f"Event bus cleanup failed: {e}")
    
    # Add event_bus to results (for UI display)
    results['event_bus_stats'] = event_bus.get_statistics() if event_bus else None
    
    return results