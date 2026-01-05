"""
simulation/setup/network_setup.py

Docstring for simulation.setup.network_setup
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