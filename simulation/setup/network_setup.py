"""
simulation/setup/network_setup.py

This module implements the setup of the social network and influence dynamics for the 
simulation.

It includes the `setup_social_network` function which initializes the social network
based on the agents and configuration settings. If social influence is enabled, it 
builds a homophily-based network and optionally enhances it with realistic influence 
dynamics that account for habit formation, experience, and peer influence.

The module is designed to be called during the simulation setup phase, after agents
have been created, to establish the social connections and influence mechanisms that 
will drive agent interactions and behavior changes throughout the simulation.

"""

import logging
from typing import List, Tuple, Optional, Any

from simulation.config.simulation_config import SimulationConfig

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
# SOCIAL NETWORK SETUP FUNCTIONS
# ============================================================
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
    if not config.enable_social or not agents:
        return None, None
    
    if progress_callback:
        progress_callback(0.45, "🌐 Building social network...")

    # Why homophily-based network? It creates clusters of similar agents, which can 
    # lead to more realistic diffusion patterns and emergent phenomena like echo 
    # chambers or opinion polarization. This allows us to study how social structure 
    # impacts the spread of behaviors and preferences in the simulation.
    network = SocialNetwork(topology='homophily', influence_enabled=True)
    
    # Use homophily-based network with k=5 neighbors and fixed seed for reproducibility.
    # Change the seed or k value to test different network structures and their impact 
    # on diffusion dynamics.
    network.build_network(agents, k=5, seed=42) 

    # Ensure influence system is returned even if not realistic to avoid downstream errors
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