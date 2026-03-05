"""
simulation/setup/agent_creation.py

Agent creation and initialization.

This module is responsible for creating the agent population for the simulation, 
including both story-driven agents (if user/job stories are provided) and basic 
cognitive agents (as a fallback). 

It uses a crypto-secure random generator to create spatially diverse origin-destination 
pairs for agents, with a minimum distance filter to ensure realistic trips.

The module also computes initial routes for all agents immediately upon creation, which 
is a critical fix to ensure that agents have valid routes from the start of the 
simulation.

"""

import secrets
import random
import logging
from typing import List, Dict, Tuple, Any, Optional

from agent.bdi_planner import BDIPlanner
from simulation.config.simulation_config import SimulationConfig
from simulation.infrastructure.infrastructure_manager import InfrastructureManager
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
    STORY_AVAILABLE = True
except ImportError:
    STORY_AVAILABLE = False
    logger.warning("Story-driven agents not available")


def create_planner(infrastructure: Optional[InfrastructureManager]) -> BDIPlanner:
    """
    Create BDI planner (with or without infrastructure).
    
    Args:
        infrastructure: Optional InfrastructureManager
    
    Returns:
        BDI planner instance
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
    Create agent population with initial routes.
    """
    if progress_callback:
        progress_callback(0.35, "🤖 Creating agents...")
    
    # Crypto RNG for better spatial distribution
    crypto_rng = random.Random(secrets.randbits(128))
    
    # Helper function to generate random origin-destination pairs
    def random_od() -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """Generate random origin-destination pairs with minimum distance."""
        if config.use_osm and env.graph_loaded:
            # Try OSM-based random OD pairs with distance filter
            max_attempts = 10
            for _ in range(max_attempts):
                pair = env.get_random_origin_dest()
                if pair:
                    origin, dest = pair
                    # Calculate straight-line distance
                    from math import radians, cos, sin, asin, sqrt
                    lon1, lat1 = origin
                    lon2, lat2 = dest
                    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
                    dlon = lon2 - lon1
                    dlat = lat2 - lat1
                    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
                    c = 2 * asin(sqrt(a))
                    distance_km = 6371 * c
                    
                    # Reject trips shorter than 2km
                    if distance_km >= 2.0:
                        return pair
            
            # If all attempts failed, fall through to random bbox
            logger.warning("get_random_origin_dest() couldn't find trip >= 2km after 10 attempts, using random bbox coords")
        
        # Generate random coordinates within bbox (with distance filter)
        if config.extended_bbox:
            west, south, east, north = config.extended_bbox
        else:
            west, south, east, north = -3.35, 55.85, -3.05, 56.00
        
        max_attempts = 20
        for _ in range(max_attempts):
            origin = (crypto_rng.uniform(west, east), crypto_rng.uniform(south, north))
            dest = (crypto_rng.uniform(west, east), crypto_rng.uniform(south, north))
            
            # Check distance
            from math import radians, cos, sin, asin, sqrt
            lon1, lat1 = origin
            lon2, lat2 = dest
            lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
            dlon = lon2 - lon1
            dlat = lat2 - lat1
            a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
            c = 2 * asin(sqrt(a))
            distance_km = 6371 * c
            
            if distance_km >= 2.0:
                return (origin, dest)
        
        # Fallback: just return last attempt even if short
        return (origin, dest)
    
    agents = []
    
    # Story-driven agents
    if config.user_stories and config.job_stories and STORY_AVAILABLE:
        # Try to use story compatibility filter
        try:
            from agent.story_compatibility import create_realistic_agent_pool
            
            agent_pool = create_realistic_agent_pool(
                num_agents=config.num_agents,
                user_story_ids=config.user_stories,
                job_story_ids=config.job_stories,
                strategy='compatible'
            )
            
            logger.info(f"Creating {len(agent_pool)} agents from filtered combinations")
            
        except ImportError:
            # Fallback to unfiltered
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
        routes_computed = 0
        routes_failed = 0
        
        for i, (user_story, job_story) in enumerate(agent_pool):
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
            
            # Compute initial route immediately
            try:
                # Force initial planning by directly calling the planner
                # (don't rely on _maybe_plan's replan period logic)
                scores = agent.planner.evaluate_actions(
                    env,
                    agent.state,
                    agent.desires,
                    agent.state.location,
                    agent.state.destination,
                    agent_context=agent.agent_context
                )
                
                if scores:
                    best = agent.planner.choose_action(scores)
                    agent.state.mode = best.mode
                    agent.state.route = [(float(x), float(y)) for (x, y) in (best.route or [])]
                    agent.state.route_index = 0
                    agent.state.route_offset_km = 0.0
                    agent.state.departed_at_step = 0
                    
                    # Store action params
                    if hasattr(agent.state, 'action_params'):
                        agent.state.action_params = best.params
                
                # Verify route was assigned
                if agent.state.route and len(agent.state.route) > 1:
                    routes_computed += 1
                    
                    # Calculate initial metrics
                    from simulation.spatial.coordinate_utils import route_distance_km
                    agent.state.distance_km = route_distance_km(agent.state.route)
                    agent.state.emissions_g = env.estimate_emissions(agent.state.route, agent.state.mode)
                else:
                    routes_failed += 1
                    logger.warning(f"❌ Agent {agent.state.agent_id}: No route computed "
                                f"(mode={agent.state.mode}, context={agent.agent_context})")

            except Exception as e:
                routes_failed += 1
                logger.error(f"❌ Agent {agent.state.agent_id}: Route computation failed: {e}")
            
            agents.append(agent)
            
            # Progress update every 10 agents
            if progress_callback and (i + 1) % 10 == 0:
                progress = 0.35 + (i + 1) / len(agent_pool) * 0.10
                progress_callback(progress, f"🤖 Created {i+1}/{len(agent_pool)} agents")
        
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
        
        # Statistics
        vehicle_required_count = sum(
            1 for a in agents 
            if hasattr(a, 'agent_context') 
            and a.agent_context.get('vehicle_required', False)
        )
        
        freight_job_count = sum(
            1 for a in agents
            if hasattr(a, 'job_story_id')
            and ('freight' in a.job_story_id.lower() or 'delivery' in a.job_story_id.lower())
        )
        
        # Mode distribution
        mode_counts = {}
        for agent in agents:
            mode = agent.state.mode
            mode_counts[mode] = mode_counts.get(mode, 0) + 1
        
        logger.info(f"✅ Created {len(agents)} story-driven agents")
        logger.info(f"   Routes: {routes_computed} computed, {routes_failed} failed")
        logger.info(f"📊 Desire diversity - Eco: σ={eco_std:.3f}, Time: σ={time_std:.3f}, Cost: σ={cost_std:.3f}")
        logger.info(f"🚚 Freight context: {vehicle_required_count} agents with vehicle_required=True")
        logger.info(f"📦 Job distribution: {freight_job_count} freight/delivery jobs")
        
        # Mode distribution
        logger.info(f"🚗 Mode distribution:")
        for mode, count in sorted(mode_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
            pct = count / len(agents) * 100
            logger.info(f"   {mode}: {count} ({pct:.1f}%)")
        
        # DEBUG: Show first 3 agents
        logger.info(f"🔍 Sample agents:")
        for i, agent in enumerate(agents[:3]):
            context = getattr(agent, 'agent_context', {})
            logger.info(f"   {i+1}. {agent.state.agent_id}")
            logger.info(f"      Mode: {agent.state.mode}, Distance: {agent.state.distance_km:.1f} km")
            logger.info(f"      Context: vehicle_type={context.get('vehicle_type')}, "
                       f"vehicle_required={context.get('vehicle_required')}")
        
        if routes_failed > len(agents) * 0.5:
            logger.error(f"⚠️ WARNING: {routes_failed}/{len(agents)} agents failed to get routes!")
            logger.error("   This will cause all agents to walk. Check:")
            logger.error("   1. Graph is loaded correctly")
            logger.error("   2. BDI planner mode filtering")
            logger.error("   3. Router network mappings")
        
        return agents, desire_std
    
    # Basic agents (fallback)
    else:
        from agent.cognitive_abm import CognitiveAgent
        
        for i in range(config.num_agents):
            origin, dest = random_od()
            agent_seed = secrets.randbits(32)
            agent_rng = random.Random(agent_seed)
            
            agent = CognitiveAgent(
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
            )
            
            # Compute initial route for basic agents too
            try:
                agent._maybe_plan(env)
            except Exception as e:
                logger.error(f"Failed to plan route for {agent.state.agent_id}: {e}")
            
            agents.append(agent)
        
        logger.info(f"✅ Created {len(agents)} basic agents")
        return agents, {}