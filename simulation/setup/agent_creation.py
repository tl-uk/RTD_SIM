"""
simulation/setup/agent_creation.py

Agent creation and initialization.
Handles agent instantiation and configuration.
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
except ImportError:
    logger.warning("Story-driven agents not available")

# ============================================================
# AGENT CREATION FUNCTIONS
# ============================================================
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
    if config.user_stories and config.job_stories:
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