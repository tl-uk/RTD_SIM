"""
simulation/config/simulation_config.py

REFACTORED: Core configuration with backward-compatible interface.
Accepts both old flat parameters and new nested structure.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict, Any
from pathlib import Path
from collections import defaultdict

# Import sub-configs
from .infrastructure_config import InfrastructureConfig
from .agent_config import AgentConfig, AgentBehaviorConfig, SocialNetworkConfig
from .analytics_config import AnalyticsConfig
from .environmental_config import EnvironmentalConfig, WeatherConfig
from .policy_config import PolicyConfig


@dataclass
class SimulationConfig:
    """
    Core simulation configuration.
    
    Supports both old flat parameters (backward compatible) and new nested structure.
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
    route_diversity_mode: str = 'ultra_fast'
    
    # ===== SCENARIO FRAMEWORK =====
    scenario_name: Optional[str] = None
    scenarios_dir: Optional[Path] = None
    combined_scenario_data: Optional[Dict] = None
    
    # ===== SUB-CONFIGURATIONS =====
    infrastructure: InfrastructureConfig = field(default_factory=InfrastructureConfig)
    agents: AgentConfig = field(default_factory=AgentConfig)
    analytics: AnalyticsConfig = field(default_factory=AnalyticsConfig)
    environmental: EnvironmentalConfig = field(default_factory=EnvironmentalConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    
    def __post_init__(self):
        """Initialize sub-configs if not provided."""
        if not isinstance(self.infrastructure, InfrastructureConfig):
            self.infrastructure = InfrastructureConfig()
        if not isinstance(self.agents, AgentConfig):
            self.agents = AgentConfig()
        if not isinstance(self.analytics, AnalyticsConfig):
            self.analytics = AnalyticsConfig()
        if not isinstance(self.environmental, EnvironmentalConfig):
            self.environmental = EnvironmentalConfig()
        if not isinstance(self.policy, PolicyConfig):
            self.policy = PolicyConfig()
    
    # ===== BACKWARD COMPATIBILITY PROPERTIES =====
    # Allow old-style access: config.grid_capacity_mw = 50
    
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
    def track_journeys(self) -> bool:
        return self.analytics.track_journeys
    
    @track_journeys.setter
    def track_journeys(self, value: bool):
        self.analytics.track_journeys = value
    
    @property
    def detect_tipping_points(self) -> bool:
        return self.analytics.detect_tipping_points
    
    @detect_tipping_points.setter
    def detect_tipping_points(self, value: bool):
        self.analytics.detect_tipping_points = value
    
    @property
    def calculate_policy_roi(self) -> bool:
        return self.analytics.calculate_policy_roi
    
    @calculate_policy_roi.setter
    def calculate_policy_roi(self, value: bool):
        self.analytics.calculate_policy_roi = value
    
    @property
    def track_network_efficiency(self) -> bool:
        return self.analytics.track_network_efficiency
    
    @track_network_efficiency.setter
    def track_network_efficiency(self, value: bool):
        self.analytics.track_network_efficiency = value
    
    @property
    def tipping_point_velocity(self) -> float:
        return self.analytics.tipping_point_velocity
    
    @tipping_point_velocity.setter
    def tipping_point_velocity(self, value: float):
        self.analytics.tipping_point_velocity = value
    
    @property
    def tipping_point_duration(self) -> int:
        return self.analytics.tipping_point_duration
    
    @tipping_point_duration.setter
    def tipping_point_duration(self, value: int):
        self.analytics.tipping_point_duration = value
    
    @property
    def weather_enabled(self) -> bool:
        return self.environmental.weather.enabled
    
    @weather_enabled.setter
    def weather_enabled(self, value: bool):
        self.environmental.weather.enabled = value
    
    @property
    def weather_source(self) -> str:
        return self.environmental.weather.source
    
    @weather_source.setter
    def weather_source(self, value: str):
        self.environmental.weather.source = value
    
    @property
    def weather_temp_adjustment(self) -> float:
        return self.environmental.weather.temp_adjustment
    
    @weather_temp_adjustment.setter
    def weather_temp_adjustment(self, value: float):
        self.environmental.weather.temp_adjustment = value
    
    @property
    def weather_precip_multiplier(self) -> float:
        return self.environmental.weather.precip_multiplier
    
    @weather_precip_multiplier.setter
    def weather_precip_multiplier(self, value: float):
        self.environmental.weather.precip_multiplier = value
    
    @property
    def weather_wind_multiplier(self) -> float:
        return self.environmental.weather.wind_multiplier
    
    @weather_wind_multiplier.setter
    def weather_wind_multiplier(self, value: float):
        self.environmental.weather.wind_multiplier = value
    
    @property
    def use_historical_weather(self) -> bool:
        return self.environmental.weather.use_historical
    
    @use_historical_weather.setter
    def use_historical_weather(self, value: bool):
        self.environmental.weather.use_historical = value
    
    @property
    def weather_start_date(self) -> Optional[str]:
        return self.environmental.weather.start_date
    
    @weather_start_date.setter
    def weather_start_date(self, value: Optional[str]):
        self.environmental.weather.start_date = value
    
    @property
    def latitude(self) -> float:
        return self.environmental.weather.latitude
    
    @latitude.setter
    def latitude(self, value: float):
        self.environmental.weather.latitude = value
    
    @property
    def longitude(self) -> float:
        return self.environmental.weather.longitude
    
    @longitude.setter
    def longitude(self, value: float):
        self.environmental.weather.longitude = value
    
    @property
    def track_air_quality(self) -> bool:
        return self.environmental.air_quality.enabled
    
    @track_air_quality.setter
    def track_air_quality(self, value: bool):
        self.environmental.air_quality.enabled = value
    
    @property
    def air_quality_grid_km(self) -> float:
        return self.environmental.air_quality.grid_resolution_km
    
    @air_quality_grid_km.setter
    def air_quality_grid_km(self, value: float):
        self.environmental.air_quality.grid_resolution_km = value
    
    @property
    def use_lifecycle_emissions(self) -> bool:
        return self.environmental.emissions.use_lifecycle
    
    @use_lifecycle_emissions.setter
    def use_lifecycle_emissions(self, value: bool):
        self.environmental.emissions.use_lifecycle = value
    
    @property
    def grid_carbon_intensity(self) -> float:
        return self.environmental.emissions.grid_carbon_intensity
    
    @grid_carbon_intensity.setter
    def grid_carbon_intensity(self, value: float):
        self.environmental.emissions.grid_carbon_intensity = value
    
    @property
    def season_month(self) -> Optional[int]:
        return self.environmental.weather.force_season_month
    
    @season_month.setter
    def season_month(self, value: Optional[int]):
        self.environmental.weather.force_season_month = value
    
    @property
    def season_day_of_year(self) -> Optional[int]:
        return self.environmental.weather.force_season_day
    
    @season_day_of_year.setter
    def season_day_of_year(self, value: Optional[int]):
        self.environmental.weather.force_season_day = value


@dataclass
class SimulationResults:
    """Container for simulation results."""
    
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
    adoption_history: Dict[str, List[float]] = field(default_factory=lambda: defaultdict(list))
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