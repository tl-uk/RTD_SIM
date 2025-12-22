"""
simulation_runner.py

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
from agent.bdi_planner import BDIPlanner  # Now handles both Phase 4 and 4.5
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


class SimulationConfig:
    """Configuration for a simulation run."""
    
    def __init__(
        self,
        steps: int = 100,
        num_agents: int = 50,
        place: str = "Edinburgh, UK",
        use_osm: bool = True,
        user_stories: List[str] = None,
        job_stories: List[str] = None,
        use_congestion: bool = False,
        enable_social: bool = True,
        use_realistic_influence: bool = True,
        decay_rate: float = 0.15,
        habit_weight: float = 0.4,
        enable_infrastructure: bool = True,  # NEW
        num_chargers: int = 50,              # NEW
        num_depots: int = 5,                 # NEW
        grid_capacity_mw: float = 1000.0,   # NEW
    ):
        self.steps = steps
        self.num_agents = num_agents
        self.place = place
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


class SimulationResults:
    """Container for simulation results."""
    
    def __init__(self):
        self.time_series: Optional[TimeSeriesStorage] = None
        self.env: Optional[SpatialEnvironment] = None
        self.agents: List[Any] = []
        self.network: Optional[SocialNetwork] = None
        self.influence_system: Optional[RealisticSocialInfluence] = None
        self.infrastructure: Optional[InfrastructureManager] = None  # NEW
        self.adoption_history: Dict[str, List[float]] = defaultdict(list)
        self.cascade_events: List[Dict] = []
        self.desire_std: Dict[str, float] = {}
        self.success: bool = False
        self.error_message: str = ""


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
    
    if config.use_osm and config.place:
        env.load_osm_graph(place=config.place, use_cache=True)
        stats = env.get_graph_stats()
        logger.info(f"✅ Loaded {stats['nodes']:,} nodes")
        
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
) -> List[Any]:
    """
    Create agent population.
    
    Args:
        config: SimulationConfig instance
        env: SpatialEnvironment instance
        planner: BDI planner instance
        progress_callback: Optional callback(progress: float, message: str)
    
    Returns:
        List of agents
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
            # Edinburgh bbox
            return (
                (crypto_rng.uniform(-3.35, -3.05), crypto_rng.uniform(55.85, 56.00)),
                (crypto_rng.uniform(-3.35, -3.05), crypto_rng.uniform(55.85, 56.00))
            )
    
    agents = []
    
    # Story-driven agents
    if PHASE_4_AVAILABLE and config.user_stories and config.job_stories:
        num_combinations = len(config.user_stories) * len(config.job_stories)
        base_agents_per_combo = config.num_agents // num_combinations
        remainder = config.num_agents % num_combinations
        
        combo_index = 0
        for user_story in config.user_stories:
            for job_story in config.job_stories:
                count = base_agents_per_combo + (1 if combo_index < remainder else 0)
                
                for i in range(count):
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
                
                combo_index += 1
        
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
        
        logger.info(f"✅ Created {len(agents)} story-driven agents "
                   f"({len(config.user_stories)} personas × {len(config.job_stories)} jobs)")
        logger.info(f"📊 Desire diversity - Eco: σ={eco_std:.3f}, Time: σ={time_std:.3f}, Cost: σ={cost_std:.3f}")
        
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
        
        # Create agents
        agents_result = create_agents(config, env, planner, progress_callback)
        if isinstance(agents_result, tuple):
            agents, desire_std = agents_result
            results.desire_std = desire_std
        else:
            agents = agents_result
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
                                # Check if agent has traveled enough to need charging
                                # Or if agent has arrived at destination
                                if agent.state.arrived or agent.state.distance_km > 5.0:
                                    station_id = params['nearest_charger']
                                    success = infrastructure.reserve_charger(
                                        agent_id,
                                        station_id,
                                        duration_min=30.0
                                    )
                                    
                                    if success:
                                        # Immediately transition to charging status
                                        infrastructure.agent_charging_state[agent_id]['status'] = 'charging'
                                        infrastructure.agent_charging_state[agent_id]['start_time'] = step
                                        logger.debug(f"Step {step}: Agent {agent_id} started charging at {station_id}")
                    
                    else:
                        # Agent is already charging - check if done
                        charge_state = infrastructure.agent_charging_state[agent_id]
                        if charge_state['status'] == 'charging':
                            start_time = charge_state.get('start_time', step)
                            duration = charge_state['duration_min']
                            
                            # Convert steps to minutes (step_minutes from env)
                            elapsed_min = (step - start_time) * 1.0  # Assuming 1 step = 1 minute
                            
                            if elapsed_min >= duration:
                                # Charging complete - release
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
            for mode in ['walk', 'bike', 'bus', 'car', 'ev']:
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
            
            # Infrastructure metrics
            infra_metrics = None
            if infrastructure:
                infra_metrics = infrastructure.get_infrastructure_metrics()
            
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