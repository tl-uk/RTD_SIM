"""
simulation/config/__init__.py

Configuration module exports.
Maintains backward compatibility while providing modular structure.
"""

# Core configs
from .simulation_config import SimulationConfig, SimulationResults
from .infrastructure_config import InfrastructureConfig
from .agent_config import AgentConfig, AgentBehaviorConfig, SocialNetworkConfig
from .analytics_config import AnalyticsConfig
from .environmental_config import (
    EnvironmentalConfig,
    WeatherConfig,
    AirQualityConfig,
    EmissionsConfig
)
from .policy_config import (
    PolicyConfig,
    PolicyThresholdsConfig,
    FeedbackLoopConfig
)

# Presets
from .presets import ConfigurationPresets

__all__ = [
    # Main configs
    'SimulationConfig',
    'SimulationResults',
    
    # Sub-configs
    'InfrastructureConfig',
    'AgentConfig',
    'AgentBehaviorConfig',
    'SocialNetworkConfig',
    'AnalyticsConfig',
    'EnvironmentalConfig',
    'WeatherConfig',
    'AirQualityConfig',
    'EmissionsConfig',
    'PolicyConfig',
    'PolicyThresholdsConfig',
    'FeedbackLoopConfig',
    
    # Presets
    'ConfigurationPresets',
]