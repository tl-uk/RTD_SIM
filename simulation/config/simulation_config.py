"""
simulation/config/simulation_config.py

REFACTORED: Core configuration with backward-compatible __init__.
Properly handles both old flat parameters and new nested structure.
"""

from __future__ import annotations
from typing import Optional, List, Tuple, Dict, Any
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# Import sub-configs
from .infrastructure_config import InfrastructureConfig
from .agent_config import AgentConfig, AgentBehaviorConfig, SocialNetworkConfig
from .analytics_config import AnalyticsConfig
from .environmental_config import EnvironmentalConfig, WeatherConfig
from .policy_config import PolicyConfig
from .system_dynamics_config import SystemDynamicsConfig


class SimulationConfig:
    """
    Core simulation configuration.
    
    Supports both old flat parameters (backward compatible) and new nested structure.
    """
    
    def __init__(
        self,
        # ===== CORE SETTINGS =====
        steps: int = 100,
        num_agents: int = 50,
        place: str = "Edinburgh, UK",
        extended_bbox: Optional[Tuple[float, float, float, float]] = None,
        use_osm: bool = True,
        region_name: Optional[str] = None,
        
        # ===== STORY SETTINGS =====
        user_stories: List[str] = None,
        job_stories: List[str] = None,
        
        # ===== FEATURE FLAGS =====
        use_congestion: bool = False,
        enable_social: bool = True,
        use_realistic_influence: bool = True,
        enable_route_diversity: bool = True,
        
        # ===== ROUTING =====
        route_diversity_mode: str = 'ultra_fast',

        # ===== PHASE 7.1: TEMPORAL SCALING =====
        enable_temporal_scaling: bool = False,
        time_scale: Optional[str] = None,
        start_datetime: Optional[Any] = None,
        
        # ===== SCENARIO FRAMEWORK =====
        scenario_name: Optional[str] = None,
        scenarios_dir: Optional[Path] = None,
        combined_scenario_data: Optional[Dict] = None,

        # ===== POLICY FRAMEWORK =====
        use_default_policies: bool = False,
        policy_thresholds: Optional[Dict] = None,
        
        # ===== BACKWARD COMPATIBILITY: OLD FLAT PARAMETERS =====
        # Infrastructure (old style)
        enable_infrastructure: bool = True,
        num_chargers: int = 50,
        num_depots: int = 5,
        grid_capacity_mw: float = 1000.0,
        
        # Social network (old style)
        decay_rate: float = 0.15,
        habit_weight: float = 0.4,
        cross_persona_prob: float = 0.25,  # Fraction of ties crossing persona boundary
        
        # Agent plan generation
        llm_backend: str = 'rule_based',  # 'rule_based' | 'olmo' | 'claude'
        
        # Analytics (old style)
        enable_analytics: bool = True,
        track_journeys: bool = True,
        detect_tipping_points: bool = True,
        calculate_policy_roi: bool = True,
        track_network_efficiency: bool = True,
        tipping_point_velocity: float = 0.5,
        tipping_point_duration: int = 5,
        
        # Weather (old style)
        weather_enabled: bool = False,
        weather_source: str = 'live',
        weather_temp_adjustment: float = 0.0,
        weather_precip_multiplier: float = 1.0,
        weather_wind_multiplier: float = 1.0,
        use_historical_weather: bool = False,
        weather_start_date: Optional[str] = None,
        latitude: float = 55.9533,
        longitude: float = -3.1883,
        
        # Air quality (old style)
        track_air_quality: bool = False,
        air_quality_grid_km: float = 1.0,
        
        # Emissions (old style)
        use_lifecycle_emissions: bool = True,
        grid_carbon_intensity: float = 0.233,
        
        # Seasonal (old style)
        season_month: Optional[int] = None,
        season_day_of_year: Optional[int] = None,
        
        # ===== NEW STRUCTURE (optional) =====
        infrastructure: Optional[InfrastructureConfig] = None,
        agents: Optional[AgentConfig] = None,
        analytics: Optional[AnalyticsConfig] = None,
        environmental: Optional[EnvironmentalConfig] = None,
        policy: Optional[PolicyConfig] = None,
        system_dynamics: Optional[SystemDynamicsConfig] = None, # System Dynamics (new structured config)
    ):
        """
        Initialize SimulationConfig.
        
        Accepts both old flat parameters (for backward compatibility)
        and new structured sub-configs.
        """
        
        # Set core attributes
        self.steps = steps
        self.num_agents = num_agents
        self.place = place
        self.extended_bbox = extended_bbox
        self.use_osm = use_osm
        self.region_name = region_name
        self.user_stories = user_stories or []
        self.job_stories = job_stories or []
        
        # Feature flags
        self.use_congestion = use_congestion
        self.enable_social = enable_social
        self.use_realistic_influence = use_realistic_influence
        self.enable_route_diversity = enable_route_diversity
        self.route_diversity_mode = route_diversity_mode
        self.cross_persona_prob = cross_persona_prob
        self.llm_backend = llm_backend
        
        # Phase 7.1: Temporal scaling
        self.enable_temporal_scaling = enable_temporal_scaling
        self.time_scale = time_scale
        self.start_datetime = start_datetime
        
        # Scenario
        self.scenario_name = scenario_name
        self.scenarios_dir = scenarios_dir
        self.combined_scenario_data = combined_scenario_data

        # Policy framework (NEW)
        self.use_default_policies = use_default_policies
        self.policy_thresholds = policy_thresholds
        
        # Initialize sub-configs
        # Use provided sub-configs OR build from flat parameters
        
        if infrastructure is not None:
            self.infrastructure = infrastructure
        else:
            self.infrastructure = InfrastructureConfig(
                enabled=enable_infrastructure,
                num_chargers=num_chargers,
                num_depots=num_depots,
                grid_capacity_mw=grid_capacity_mw
            )
        
        if agents is not None:
            self.agents = agents
        else:
            self.agents = AgentConfig(
                social_network=SocialNetworkConfig(
                    enabled=enable_social,
                    decay_rate=decay_rate,
                    habit_weight=habit_weight,
                    use_realistic_influence=use_realistic_influence
                ),
                behavior=AgentBehaviorConfig()
            )
        
        if analytics is not None:
            self.analytics = analytics
        else:
            self.analytics = AnalyticsConfig(
                enabled=enable_analytics,
                track_journeys=track_journeys,
                detect_tipping_points=detect_tipping_points,
                calculate_policy_roi=calculate_policy_roi,
                track_network_efficiency=track_network_efficiency,
                tipping_point_velocity=tipping_point_velocity,
                tipping_point_duration=tipping_point_duration
            )
        
        if environmental is not None:
            self.environmental = environmental
        else:
            self.environmental = EnvironmentalConfig(
                weather=WeatherConfig(
                    enabled=weather_enabled,
                    source=weather_source,
                    temp_adjustment=weather_temp_adjustment,
                    precip_multiplier=weather_precip_multiplier,
                    wind_multiplier=weather_wind_multiplier,
                    use_historical=use_historical_weather,
                    start_date=weather_start_date,
                    latitude=latitude,
                    longitude=longitude,
                    force_season_month=season_month,
                    force_season_day=season_day_of_year
                )
            )
            self.environmental.air_quality.enabled = track_air_quality
            self.environmental.air_quality.grid_resolution_km = air_quality_grid_km
            self.environmental.emissions.use_lifecycle = use_lifecycle_emissions
            self.environmental.emissions.grid_carbon_intensity = grid_carbon_intensity
        
        if policy is not None:
            self.policy = policy
        else:
            self.policy = PolicyConfig(
                combined_scenario_data=combined_scenario_data
            )
        
        # System Dynamics
        if system_dynamics is not None:
            self.system_dynamics = system_dynamics
        else:
            self.system_dynamics = SystemDynamicsConfig()  # Use defaults

        # Store policy framework attributes at top level
        # (policy_initialization.py reads these with getattr)
        if not hasattr(self, 'use_default_policies'):
            self.use_default_policies = use_default_policies
        if not hasattr(self, 'policy_thresholds'):
            self.policy_thresholds = policy_thresholds
    
    # ========================================
    # Phase 6.2b: Event System
    # ========================================
    enable_event_bus: bool = False
    """Enable real-time event bus (auto-falls back to in-memory if Redis unavailable)"""
    
    redis_host: str = 'localhost'
    """Redis server host for event bus"""
    
    redis_port: int = 6379
    """Redis server port for event bus"""
    
    redis_db: int = 0
    """Redis database number for event bus"""
    
    agent_perception_radius_km: float = 10.0
    """How far agents can perceive events (kilometers)"""
    
    enable_agent_event_subscription: bool = True
    """Subscribe agents to events for perception (Phase 7 - dynamic replanning)"""
    
    enable_policy_events: bool = True
    """Publish policy change events when policies trigger"""
    
    enable_infrastructure_events: bool = True
    """Publish infrastructure failure events (future use)"""


    # ===== BACKWARD COMPATIBILITY PROPERTIES =====
    # Allow old-style attribute access after initialization
    
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
    
    # Analytics properties
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
    
    # Weather properties
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
    
    # Air quality properties
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
    
    # Emissions properties
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
    
    # Seasonal properties
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


class SimulationResults:
    """Container for simulation results."""
    
    def __init__(self):
        # Core results
        self.time_series = None
        self.env = None
        self.agents = []
        
        # Network results
        self.network = None
        self.influence_system = None
        
        # Infrastructure results
        self.infrastructure = None
        
        # Metrics
        self.adoption_history = defaultdict(list)
        self.cascade_events = []
        self.desire_std = {}
        
        # Execution status
        self.success = False
        self.error_message = ""
        
        # Scenario results
        self.scenario_report = None
        
        # Combined scenario results
        self.policy_actions = []
        self.constraint_violations = []
        self.cost_recovery_history = []
        self.final_cost_recovery = None
        self.policy_status = None

        # Environmental results
        self.weather_manager = None
        self.weather_history = []
        self.air_quality_metrics = None
        self.air_quality_tracker = None
        self.lifecycle_emissions_total = {}

        # Analytics results
        self.journey_tracker = None
        self.mode_share_analyzer = None
        self.policy_impact_analyzer = None
        self.network_efficiency_tracker = None
        self.scenario_comparator = None
        self.analytics_summary = {}
        
        # Phase 5.3: System Dynamics results
        self.system_dynamics_history = []

        # ── Data quality counters ──────────────────────────────────────────
        # routing_fallback_count: incremented in cognitive_abm._maybe_plan
        # whenever the planner returns no valid route and the agent falls
        # back to a straight-line walk.  A non-zero value flags potential
        # OD-pair connectivity issues that could bias mode-share results.
        self.routing_fallback_count: int = 0