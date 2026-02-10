"""
simulation/config/agent_config.py

Agent behavior and social network configuration.
"""

from dataclasses import dataclass


@dataclass
class SocialNetworkConfig:
    """Social network influence parameters."""
    
    enabled: bool = True
    decay_rate: float = 0.15
    habit_weight: float = 0.4
    use_realistic_influence: bool = True
    network_density: float = 0.1  # Connections per agent


@dataclass
class AgentBehaviorConfig:
    """Agent decision-making parameters."""
    
    # BDI desire distributions (mean values)
    eco_desire_mean: float = 0.5
    eco_desire_std: float = 0.2
    
    cost_sensitivity_mean: float = 0.5
    cost_sensitivity_std: float = 0.2
    
    time_sensitivity_mean: float = 0.5
    time_sensitivity_std: float = 0.2
    
    comfort_desire_mean: float = 0.5
    comfort_desire_std: float = 0.2
    
    # Initial mode adoption
    initial_ev_adoption: float = 0.05  # 5% start with EVs
    initial_bike_adoption: float = 0.1  # 10% start biking
    initial_transit_adoption: float = 0.15  # 15% start on transit


@dataclass
class AgentConfig:
    """Combined agent configuration."""
    
    social_network: SocialNetworkConfig = None
    behavior: AgentBehaviorConfig = None
    
    def __post_init__(self):
        if self.social_network is None:
            self.social_network = SocialNetworkConfig()
        if self.behavior is None:
            self.behavior = AgentBehaviorConfig()