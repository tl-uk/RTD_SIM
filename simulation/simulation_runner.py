"""
simulation/simulation_runner.py

Simulation execution logic separated from UI.
Handles infrastructure setup, agent creation, and main simulation loop.
"""

from __future__ import annotations
import secrets
import random
import logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any
from collections import Counter, defaultdict

from simulation.spatial_environment import SpatialEnvironment
from simulation.infrastructure_manager import InfrastructureManager
from agent.bdi_planner import BDIPlanner
from visualiser.data_adapters import TimeSeriesStorage

logger = logging.getLogger(__name__)

# Phase 3+4 imports (optional)
try:
    from agent.story_driven_agent import StoryDrivenAgent
    from agent.social_network import SocialNetwork
    from agent.social_influence_dynamics import (
        RealisticSocialInfluence,
        enhance_social_network_with_realism,
        calculate_satisfaction
    )
    PHASE_4_AVAILABLE = True
except ImportError:
    PHASE_4_AVAILABLE = False
    logger.warning("Phase 4 story-driven agents not available")

try:
    from scenarios.scenario_manager import ScenarioManager
    SCENARIOS_AVAILABLE = True
except ImportError:
    SCENARIOS_AVAILABLE = False
    logger.warning("Scenario framework not available")

class SimulationConfig:
    """Configuration for a simulation run."""
    
    def __init__(
        self,
        steps: int = 100,
        num_agents: int = 50,
        place: str = "Edinburgh, UK",
        extended_bbox: Optional[Tuple[float, float, float, float]] = None,
        use_osm: bool = True,
        user_stories: List[str] = None,
        job_stories: List[str] = None,
        use_congestion: bool = False,
        enable_social: bool = True,
        use_realistic_influence: bool = True,
        decay_rate: float = 0.15,
        habit_weight: float = 0.4,
        enable_infrastructure: bool = True,
        num_chargers: int = 50,
        num_depots: int = 5,
        grid_capacity_mw: float = 1000.0,
        scenario_name: Optional[str] = None,  # Name of policy scenario to apply
        scenarios_dir: Optional[Path] = None,  # Path to scenarios directory

    ):
        self.steps = steps
        self.num_agents = num_agents
        self.place = place
        self.extended_bbox = extended_bbox
        self.use_osm = use_osm
        self.user_stories = user_stories or []
        self.job_stories = job_stories or []
        self.use_congestion = use_congestion
        self.enable_social = enable_social
        self.use_realistic_influence = use_realistic_influence
        self.decay_rate = decay_rate
        self.habit_weight = habit_weight
        self.enable_infrastructure = enable_infrastructure
        self.num_chargers = num_chargers
        self.num_depots = num_depots
        self.grid_capacity_mw = grid_capacity_mw

        # ADD THESE NEW ATTRIBUTES:
        self.scenario_name = scenario_name
        self.scenarios_dir = scenarios_dir

class SimulationResults:
    """Container for simulation results."""
    
    def __init__(self):
        self.time_series: Optional[TimeSeriesStorage] = None
        self.env: Optional[SpatialEnvironment] = None
        self.agents: List[Any] = []
        self.network: Optional[SocialNetwork] = None
        self.influence_system: Optional[RealisticSocialInfluence] = None
        self.infrastructure: Optional[InfrastructureManager] = None
        self.adoption_history: Dict[str, List[float]] = defaultdict(list)
        self.cascade_events: List[Dict] = []
        self.desire_std: Dict[str, float] = {}
        self.success: bool = False
        self.error_message: str = ""

        self.scenario_report: Optional[Dict] = None  # Scenario info if applied


def setup_environment(config: SimulationConfig, progress_callback=None) -> SpatialEnvironment:
    """
    Initialize spatial environment.
    
    Args:
        config: SimulationConfig instance
        progress_callback: Optional callback(progress: float, message: str)
    
    Returns:
        Configured SpatialEnvironment
    """
    if progress_callback:
        progress_callback(0.1, "🗺️ Loading environment...")
    
    cache_dir = Path.home() / ".rtd_sim_cache" / "osm_graphs"
    env = SpatialEnvironment(
        step_minutes=1.0,
        cache_dir=cache_dir,
        use_congestion=config.use_congestion
    )
    
    if config.use_osm:
        # Support extended bbox for freight scenarios
        if config.extended_bbox:
            # Regional scale (e.g., Edinburgh-Glasgow corridor)
            west, south, east, north = config.extended_bbox
            logger.info(f"Loading extended region: bbox {config.extended_bbox}")
            env.load_osm_graph(bbox=(north, south, east, west), use_cache=True)
            region_name = "Central Scotland"
        elif config.place:
            # City scale
            logger.info(f"Loading city: {config.place}")
            env.load_osm_graph(place=config.place, use_cache=True)
            region_name = config.place
        else:
            logger.warning("No place or bbox specified")
            return env
        
        stats = env.get_graph_stats()
        logger.info(f"✅ Loaded {region_name}: {stats['nodes']:,} nodes")
        
        if progress_callback:
            progress_callback(0.15, f"✅ Loaded {region_name}")
        
        # Verify congestion if enabled
        if config.use_congestion:
            try:
                if hasattr(env, 'congestion_manager') and env.congestion_manager:
                    logger.info("✅ Congestion tracking enabled")
                elif hasattr(env, 'get_congestion_heatmap'):
                    test_heatmap = env.get_congestion_heatmap()
                    logger.info(f"✅ Congestion tracking enabled ({len(test_heatmap)} edges)")
                else:
                    logger.warning("⚠️ Congestion requested but not available")
            except Exception as e:
                logger.warning(f"⚠️ Congestion initialization failed: {e}")
    
    if progress_callback:
        progress_callback(0.2, "✅ Environment loaded")
    
    return env


def setup_infrastructure(config: SimulationConfig, progress_callback=None) -> Optional[InfrastructureManager]:
    """
    Initialize infrastructure manager.
    
    Args:
        config: SimulationConfig instance
        progress_callback: Optional callback(progress: float, message: str)
    
    Returns:
        InfrastructureManager or None if disabled
    """
    if not config.enable_infrastructure:
        return None
    
    if progress_callback:
        progress_callback(0.25, "🔌 Setting up infrastructure...")
    
    infrastructure = InfrastructureManager(grid_capacity_mw=config.grid_capacity_mw)
    
    # Determine spatial bounds for charger placement
    if config.extended_bbox:
        # Regional scale - place chargers across extended region
        west, south, east, north = config.extended_bbox
        logger.info(f"Populating infrastructure across extended region")
        
        # For extended region, use custom placement
        import random
        for i in range(config.num_chargers):
            lon = random.uniform(west, east)
            lat = random.uniform(south, north)
            
            infrastructure.add_charging_station(
                station_id=f"regional_{i:03d}",
                location=(lon, lat),
                charger_type=random.choice(['level2', 'dcfast']),
                num_ports=random.choice([2, 4, 6]),
                power_kw=7.0 if i % 5 != 0 else 50.0,  # 20% DC fast
                cost_per_kwh=0.15 if i % 5 != 0 else 0.25,
                owner_type='public'
            )
        
        # Add depots in major cities (Glasgow and Edinburgh)
        depot_locations = [
            (-4.25, 55.86, "glasgow"),   # Glasgow
            (-3.19, 55.95, "edinburgh"),  # Edinburgh
        ]
        
        for i, (lon, lat, city) in enumerate(depot_locations):
            infrastructure.add_depot(
                depot_id=f"depot_{city}_{i:02d}",
                location=(lon, lat),
                depot_type=random.choice(['delivery', 'freight']),
                num_chargers=random.choice([10, 20]),
                charger_power_kw=50.0
            )
    else:
        # City scale - use default Edinburgh placement
        infrastructure.populate_edinburgh_chargers(
            num_public=config.num_chargers,
            num_depot=config.num_depots
        )
    
    metrics = infrastructure.get_infrastructure_metrics()
    logger.info(f"✅ Infrastructure: {metrics['charging_stations']} stations, "
                f"{metrics['total_ports']} ports, {metrics['depots']} depots")
    
    if progress_callback:
        progress_callback(0.3, "✅ Infrastructure ready")
    
    return infrastructure


def create_planner(infrastructure: Optional[InfrastructureManager]) -> BDIPlanner:
    """
    Create BDI planner (with or without infrastructure).
    
    Args:
        infrastructure: Optional InfrastructureManager
    
    Returns:
        BDI planner instance (auto-detects Phase 4 vs 4.5)
    """
    planner = BDIPlanner(infrastructure_manager=infrastructure)
    
    if infrastructure is not None:
        logger.info("✅ Created infrastructure-aware BDI planner (Phase 4.5)")
    else:
        logger.info("✅ Created basic BDI planner (Phase 4)")
    
    return planner


def create_agents(
    config: SimulationConfig,
    env: SpatialEnvironment,
    planner: Any,
    progress_callback=None
) -> Tuple[List[Any], Dict[str, float]]:
    """
    Create agent population.
    
    FIX: Now filters incompatible story combinations and logs context.
    """
    if progress_callback:
        progress_callback(0.35, "🤖 Creating agents...")
    
    # Crypto RNG for better spatial distribution
    crypto_rng = random.Random(secrets.randbits(128))
    
    def random_od() -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """Generate random origin-destination pairs."""
        if config.use_osm and env.graph_loaded:
            pair = env.get_random_origin_dest()
            return pair if pair else ((-3.19, 55.95), (-3.15, 55.97))
        else:
            # Use bbox bounds if extended, otherwise Edinburgh default
            if config.extended_bbox:
                west, south, east, north = config.extended_bbox
                return (
                    (crypto_rng.uniform(west, east), crypto_rng.uniform(south, north)),
                    (crypto_rng.uniform(west, east), crypto_rng.uniform(south, north))
                )
            else:
                # Edinburgh bbox
                return (
                    (crypto_rng.uniform(-3.35, -3.05), crypto_rng.uniform(55.85, 56.00)),
                    (crypto_rng.uniform(-3.35, -3.05), crypto_rng.uniform(55.85, 56.00))
                )
    
    agents = []
    
    # Story-driven agents
    if PHASE_4_AVAILABLE and config.user_stories and config.job_stories:
        # FIX: Import and use story compatibility filter
        try:
            from agent.story_compatibility import create_realistic_agent_pool
            
            # Create filtered agent pool
            agent_pool = create_realistic_agent_pool(
                num_agents=config.num_agents,
                user_story_ids=config.user_stories,
                job_story_ids=config.job_stories,
                strategy='compatible'  # Filter nonsensical combinations
            )
            
            logger.info(f"Creating {len(agent_pool)} agents from filtered combinations")
            
        except ImportError:
            # Fallback to old method if story_compatibility.py doesn't exist
            logger.warning("story_compatibility.py not found - using unfiltered combinations")
            num_combinations = len(config.user_stories) * len(config.job_stories)
            base_agents_per_combo = config.num_agents // num_combinations
            remainder = config.num_agents % num_combinations
            
            agent_pool = []
            combo_index = 0
            for user_story in config.user_stories:
                for job_story in config.job_stories:
                    count = base_agents_per_combo + (1 if combo_index < remainder else 0)
                    for _ in range(count):
                        agent_pool.append((user_story, job_story))
                    combo_index += 1
        
        # Create agents from pool
        for user_story, job_story in agent_pool:
            origin, dest = random_od()
            agent_seed = secrets.randbits(32)
            
            agent = StoryDrivenAgent(
                user_story_id=user_story,
                job_story_id=job_story,
                origin=origin,
                dest=dest,
                planner=planner,
                seed=agent_seed,
                apply_variance=True
            )
            agents.append(agent)
        
        # Shuffle for spatial diversity
        crypto_rng.shuffle(agents)
        
        # Calculate desire diversity
        import statistics
        eco_values = [a.desires.get('eco', 0) for a in agents]
        time_values = [a.desires.get('time', 0) for a in agents]
        cost_values = [a.desires.get('cost', 0) for a in agents]
        
        eco_std = statistics.stdev(eco_values) if len(eco_values) > 1 else 0
        time_std = statistics.stdev(time_values) if len(time_values) > 1 else 0
        cost_std = statistics.stdev(cost_values) if len(cost_values) > 1 else 0
        
        desire_std = {'eco': eco_std, 'time': time_std, 'cost': cost_std}
        
        # FIX: Log vehicle_required statistics
        vehicle_required_count = sum(
            1 for a in agents 
            if hasattr(a, 'agent_context') 
            and a.agent_context.get('vehicle_required', False)
        )
        
        freight_job_count = sum(
            1 for a in agents
            if hasattr(a, 'job_story_id')
            and 'freight' in a.job_story_id.lower() or 'delivery' in a.job_story_id.lower()
        )
        
        logger.info(f"✅ Created {len(agents)} story-driven agents")
        logger.info(f"📊 Desire diversity - Eco: σ={eco_std:.3f}, Time: σ={time_std:.3f}, Cost: σ={cost_std:.3f}")
        logger.info(f"🚚 Freight context: {vehicle_required_count} agents with vehicle_required=True")
        logger.info(f"📦 Job distribution: {freight_job_count} freight/delivery jobs")
        
        # DEBUG: Show first 3 agents' contexts
        for i, agent in enumerate(agents[:3]):
            context = getattr(agent, 'agent_context', {})
            logger.info(f"   Sample {i+1}: {agent.state.agent_id} -> "
                       f"vehicle_required={context.get('vehicle_required')}, "
                       f"vehicle_type={context.get('vehicle_type')}")
        
        return agents, desire_std
    
    # Basic agents (fallback)
    else:
        from agent.cognitive_abm import CognitiveAgent
        
        for i in range(config.num_agents):
            origin, dest = random_od()
            agent_seed = secrets.randbits(32)
            agent_rng = random.Random(agent_seed)
            
            agents.append(CognitiveAgent(
                seed=agent_seed,
                agent_id=f"agent_{i+1}",
                desires={
                    'eco': agent_rng.uniform(0.2, 0.9),
                    'time': agent_rng.uniform(0.2, 0.9),
                    'cost': agent_rng.uniform(0.2, 0.9)
                },
                planner=planner,
                origin=origin,
                dest=dest
            ))
        
        logger.info(f"✅ Created {len(agents)} basic agents")
        return agents, {}


def setup_social_network(
    config: SimulationConfig,
    agents: List[Any],
    progress_callback=None
) -> Tuple[Optional[SocialNetwork], Optional[RealisticSocialInfluence]]:
    """
    Setup social network and influence system.
    
    Args:
        config: SimulationConfig instance
        agents: List of agents
        progress_callback: Optional callback(progress: float, message: str)
    
    Returns:
        Tuple of (SocialNetwork, RealisticSocialInfluence) or (None, None)
    """
    if not config.enable_social or not PHASE_4_AVAILABLE:
        return None, None
    
    if progress_callback:
        progress_callback(0.45, "🌐 Building social network...")
    
    network = SocialNetwork(topology='homophily', influence_enabled=True)
    network.build_network(agents, k=5, seed=42)
    
    influence_system = None
    if config.use_realistic_influence:
        influence_system = RealisticSocialInfluence(
            decay_rate=config.decay_rate,
            habit_weight=config.habit_weight,
            experience_weight=0.4,
            peer_weight=0.2
        )
        enhance_social_network_with_realism(network, influence_system)
        logger.info("✅ Realistic influence enabled")
    else:
        logger.info("✅ Deterministic influence enabled")
    
    if progress_callback:
        progress_callback(0.5, "✅ Social network ready")
    
    return network, influence_system

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
    
def run_simulation(config: SimulationConfig, progress_callback=None) -> SimulationResults:
    """
    Execute complete simulation.
    
    Args:
        config: SimulationConfig instance
        progress_callback: Optional callback(progress: float, message: str)
    
    Returns:
        SimulationResults instance
    """
    results = SimulationResults()
    
    try:
        # Setup environment
        env = setup_environment(config, progress_callback)
        results.env = env
        
        # Setup infrastructure
        infrastructure = setup_infrastructure(config, progress_callback)
        results.infrastructure = infrastructure
        
        # Create planner
        planner = create_planner(infrastructure)

        # Apply scenario policies BEFORE creating agents
        # This ensures agents use modified costs when planning
        scenario_report = apply_scenario_policies(config, env, progress_callback)
        results.scenario_report = scenario_report
        
        # Create agents
        agents, desire_std = create_agents(config, env, planner, progress_callback)
        results.desire_std = desire_std
        results.agents = agents
        
        # Setup social network
        network, influence_system = setup_social_network(config, agents, progress_callback)
        results.network = network
        results.influence_system = influence_system
        
        # Initialize time series storage
        time_series = TimeSeriesStorage()
        
        # Main simulation loop
        if progress_callback:
            progress_callback(0.5, "🏃 Running simulation...")
        
        adoption_history = defaultdict(list)
        cascade_events = []
        
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
            
            # Track metrics
            if network:
                network.record_mode_snapshot()
            
            mode_counts = Counter(a.state.mode for a in agents)
            for mode in ['walk', 'bike', 'bus', 'car', 'ev', 'van_electric', 'van_diesel']:
                adoption_history[mode].append(mode_counts.get(mode, 0) / len(agents))
            
            # Cascade detection
            if network:
                for mode in mode_counts.keys():
                    cascade, clusters = network.detect_cascade(mode, threshold=0.15)
                    if cascade:
                        cascade_events.append({
                            'step': step,
                            'mode': mode,
                            'size': max(len(c) for c in clusters) if clusters else 0
                        })
            
            # Aggregate metrics
            metrics = {
                'arrivals': sum(1 for a in agents if a.state.arrived),
                'emissions': sum(a.state.emissions_g for a in agents),
                'distance': sum(a.state.distance_km for a in agents),
            }
            
            # Store timestep
            time_series.store_timestep(step, agent_states, None, metrics)
            
            # Progress update
            if step % max(1, config.steps // 10) == 0 and progress_callback:
                progress = 0.5 + (0.45 * step / config.steps)
                progress_callback(progress, f"Step {step}/{config.steps}")
        
        # Finalize results
        results.time_series = time_series
        results.adoption_history = adoption_history
        results.cascade_events = cascade_events
        results.success = True
        
        if progress_callback:
            progress_callback(1.0, "✅ Simulation complete!")
        
        logger.info(f"✅ Simulation complete: {len(cascade_events)} cascades detected")
        
    except Exception as e:
        logger.exception(f"Simulation failed: {e}")
        results.success = False
        results.error_message = str(e)
    
    return results