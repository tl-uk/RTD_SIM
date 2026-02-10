"""
simulation/config/simulation_config.py

REFACTORED: Core configuration only.
Other configs moved to separate modules for maintainability.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict, Any
from pathlib import Path

# Import sub-configs
from .infrastructure_config import InfrastructureConfig
from .agent_config import AgentConfig
from .analytics_config import AnalyticsConfig
from .environmental_config import EnvironmentalConfig
from .policy_config import PolicyConfig


@dataclass
class SimulationConfig:
    """
    Core simulation configuration.
    
    This class now delegates to specialized configs for better maintainability.
    Use presets.py for common configurations.
    """
    
    # ===== CORE SETTINGS =====
    steps: int = 100
    num_agents: int = 50
    place: str = "Edinburgh, UK"
    extended_bbox: Optional[Tuple[float, float, float, float]] = None
    use_osm: bool = True
    region_name: Optional[str] = None
    
    # ===== STORY SETTINGS =====
    user_stories: List[str] = field(default_factory=list)
    job_stories: List[str] = field(default_factory=list)
    
    # ===== FEATURE FLAGS =====
    use_congestion: bool = False
    enable_social: bool = True
    use_realistic_influence: bool = True
    enable_route_diversity: bool = True
    
    # ===== ROUTING =====
    route_diversity_mode: str = 'ultra_fast'  # 'perturbed', 'k_shortest', 'ultra_fast'
    
    # ===== SCENARIO FRAMEWORK =====
    scenario_name: Optional[str] = None
    scenarios_dir: Optional[Path] = None
    combined_scenario_data: Optional[Dict] = None
    
    # ===== SUB-CONFIGURATIONS =====
    # These delegate to specialized config classes
    infrastructure: InfrastructureConfig = field(default_factory=InfrastructureConfig)
    agents: AgentConfig = field(default_factory=AgentConfig)
    analytics: AnalyticsConfig = field(default_factory=AnalyticsConfig)
    environmental: EnvironmentalConfig = field(default_factory=EnvironmentalConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    
    # ===== BACKWARD COMPATIBILITY =====
    # These properties map to sub-configs for existing code
    
    @property
    def enable_infrastructure(self) -> bool:
        return self.infrastructure.enabled
    
    @enable_infrastructure.setter
    def enable_infrastructure(self, value: bool):
        self.infrastructure.enabled = value
    
    @property
    def num_chargers(self) -> int:
        return self.infrastructure.num_chargers
    
    @num_chargers.setter
    def num_chargers(self, value: int):
        self.infrastructure.num_chargers = value
    
    @property
    def num_depots(self) -> int:
        return self.infrastructure.num_depots
    
    @num_depots.setter
    def num_depots(self, value: int):
        self.infrastructure.num_depots = value
    
    @property
    def grid_capacity_mw(self) -> float:
        return self.infrastructure.grid_capacity_mw
    
    @grid_capacity_mw.setter
    def grid_capacity_mw(self, value: float):
        self.infrastructure.grid_capacity_mw = value
    
    @property
    def decay_rate(self) -> float:
        return self.agents.social_network.decay_rate
    
    @decay_rate.setter
    def decay_rate(self, value: float):
        self.agents.social_network.decay_rate = value
    
    @property
    def habit_weight(self) -> float:
        return self.agents.social_network.habit_weight
    
    @habit_weight.setter
    def habit_weight(self, value: float):
        self.agents.social_network.habit_weight = value
    
    @property
    def enable_analytics(self) -> bool:
        return self.analytics.enabled
    
    @enable_analytics.setter
    def enable_analytics(self, value: bool):
        self.analytics.enabled = value
    
    @property
    def weather_enabled(self) -> bool:
        return self.environmental.weather.enabled
    
    @weather_enabled.setter
    def weather_enabled(self, value: bool):
        self.environmental.weather.enabled = value
    
    @property
    def track_air_quality(self) -> bool:
        return self.environmental.air_quality.enabled
    
    @track_air_quality.setter
    def track_air_quality(self, value: bool):
        self.environmental.air_quality.enabled = value


@dataclass
class SimulationResults:
    """Container for simulation results - unchanged."""
    
    # Core results
    time_series: Optional[Any] = None
    env: Optional[Any] = None
    agents: List[Any] = field(default_factory=list)
    
    # Network results
    network: Optional[Any] = None
    influence_system: Optional[Any] = None
    
    # Infrastructure results
    infrastructure: Optional[Any] = None
    
    # Metrics
    adoption_history: Dict[str, List[float]] = field(default_factory=dict)
    cascade_events: List[Dict] = field(default_factory=list)
    desire_std: Dict[str, float] = field(default_factory=dict)
    
    # Execution status
    success: bool = False
    error_message: str = ""
    
    # Scenario results
    scenario_report: Optional[Dict] = None
    
    # Combined scenario results
    policy_actions: List[Dict] = field(default_factory=list)
    constraint_violations: List[Dict] = field(default_factory=list)
    cost_recovery_history: List[Dict] = field(default_factory=list)
    final_cost_recovery: Optional[Dict] = None
    policy_status: Optional[Dict] = None

    # Environmental results
    weather_manager: Optional[Any] = None
    weather_history: List = field(default_factory=list)
    air_quality_metrics: Optional[Dict] = None
    air_quality_tracker: Optional[Any] = None
    lifecycle_emissions_total: Dict[str, float] = field(default_factory=dict)

    # Analytics results
    journey_tracker: Optional[Any] = None
    mode_share_analyzer: Optional[Any] = None
    policy_impact_analyzer: Optional[Any] = None
    network_efficiency_tracker: Optional[Any] = None
    scenario_comparator: Optional[Any] = None
    analytics_summary: Dict = field(default_factory=dict)
