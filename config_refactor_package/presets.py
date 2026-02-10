"""
simulation/config/presets.py

Configuration presets for common scenarios.
Makes it easy to set up simulations that demonstrate specific behaviors.
"""

from typing import Dict, Any
from .simulation_config import SimulationConfig
from .infrastructure_config import InfrastructureConfig
from .agent_config import AgentConfig, AgentBehaviorConfig, SocialNetworkConfig
from .policy_config import PolicyConfig, PolicyThresholdsConfig


class ConfigurationPresets:
    """
    Pre-configured simulation setups.
    
    Usage:
        config = ConfigurationPresets.high_ev_demand()
        config = ConfigurationPresets.grid_stress_test()
    """
    
    @staticmethod
    def default() -> SimulationConfig:
        """Standard balanced configuration."""
        return SimulationConfig()
    
    @staticmethod
    def high_ev_demand() -> SimulationConfig:
        """
        High EV adoption scenario - GUARANTEED to trigger policy actions.
        
        Use when: You want to see grid expansion, charging infrastructure stress
        Triggers: Grid intervention, infrastructure expansion, pricing adjustments
        """
        config = SimulationConfig()
        
        # Infrastructure: Limited grid to force intervention
        config.infrastructure = InfrastructureConfig(
            enabled=True,
            num_chargers=30,  # Limited chargers
            num_depots=3,
            grid_capacity_mw=30.0,  # LOW - will trigger expansion
            charger_density_multiplier=1.5,
            allow_dynamic_expansion=True,
            expansion_trigger_threshold=0.6,  # Trigger early
            enable_dynamic_pricing=True
        )
        
        # Agents: High eco preference
        config.agents = AgentConfig(
            behavior=AgentBehaviorConfig(
                eco_desire_mean=0.8,  # HIGH eco preference
                eco_desire_std=0.15,
                cost_sensitivity_mean=0.3,  # LOW cost sensitivity
                initial_ev_adoption=0.25  # Start with 25% EVs
            ),
            social_network=SocialNetworkConfig(
                enabled=True,
                decay_rate=0.1,  # Slower decay = stronger influence
                use_realistic_influence=True
            )
        )
        
        # Policy: Aggressive thresholds
        config.policy = PolicyConfig(
            thresholds=PolicyThresholdsConfig(
                grid_intervention_threshold=0.6,  # Intervene early
                ev_adoption_target=0.5,
                budget_warning_threshold=0.7
            )
        )
        
        config.num_agents = 100  # More agents = more load
        
        return config
    
    @staticmethod
    def grid_stress_test() -> SimulationConfig:
        """
        Grid stress scenario - tests grid capacity limits.
        
        Use when: Testing infrastructure resilience, grid management
        Triggers: Grid critical alerts, load balancing, surge pricing
        """
        config = SimulationConfig()
        
        # Infrastructure: VERY limited grid
        config.infrastructure = InfrastructureConfig(
            enabled=True,
            num_chargers=20,  # Few chargers
            grid_capacity_mw=20.0,  # VERY LOW
            charger_density_multiplier=0.5,  # Sparse deployment
            allow_dynamic_expansion=True,
            expansion_trigger_threshold=0.5,
            enable_dynamic_pricing=True,
            surge_price_multiplier=3.0  # High surge pricing
        )
        
        # Agents: Moderate EV adoption
        config.agents = AgentConfig(
            behavior=AgentBehaviorConfig(
                eco_desire_mean=0.6,
                initial_ev_adoption=0.20,  # 20% EVs
                cost_sensitivity_mean=0.4
            )
        )
        
        # Policy: Hair-trigger interventions
        config.policy = PolicyConfig(
            thresholds=PolicyThresholdsConfig(
                grid_intervention_threshold=0.5,  # Very sensitive
                grid_critical_threshold=0.7
            )
        )
        
        config.num_agents = 150
        
        return config
    
    @staticmethod
    def budget_constrained() -> SimulationConfig:
        """
        Limited budget scenario - tests cost-effective decisions.
        
        Use when: Testing policy ROI, cost recovery, investment prioritization
        Triggers: Budget warnings, ROI calculations, selective expansion
        """
        config = SimulationConfig()
        
        # Infrastructure: Expensive expansion
        config.infrastructure = InfrastructureConfig(
            enabled=True,
            num_chargers=25,
            grid_capacity_mw=100.0,  # Good grid
            expansion_cost_per_charger=50000.0,  # EXPENSIVE
            allow_dynamic_expansion=True,
            expansion_trigger_threshold=0.8  # Wait longer
        )
        
        # Agents: Mixed preferences
        config.agents = AgentConfig(
            behavior=AgentBehaviorConfig(
                eco_desire_mean=0.5,
                cost_sensitivity_mean=0.7,  # HIGH cost sensitivity
                initial_ev_adoption=0.15
            )
        )
        
        # Policy: Tight budget
        config.policy = PolicyConfig(
            thresholds=PolicyThresholdsConfig(
                default_budget_limit=500000.0,  # £500k limit
                budget_warning_threshold=0.6,
                ev_adoption_target=0.4
            )
        )
        
        # Analytics: Track ROI closely
        config.analytics.calculate_policy_roi = True
        config.analytics.roi_discount_rate = 0.08  # 8% hurdle rate
        
        return config
    
    @staticmethod
    def rapid_adoption() -> SimulationConfig:
        """
        Rapid EV adoption with feedback loops.
        
        Use when: Testing tipping points, social influence, feedback loops
        Triggers: Tipping point detection, network effects, cascade events
        """
        config = SimulationConfig()
        
        # Infrastructure: Good capacity
        config.infrastructure = InfrastructureConfig(
            enabled=True,
            num_chargers=60,
            grid_capacity_mw=150.0,
            charger_density_multiplier=2.0,  # Dense network
            allow_dynamic_expansion=True
        )
        
        # Agents: Strong social influence
        config.agents = AgentConfig(
            behavior=AgentBehaviorConfig(
                eco_desire_mean=0.7,
                eco_desire_std=0.25,  # HIGH variance
                initial_ev_adoption=0.15,  # Start at critical mass threshold
                cost_sensitivity_mean=0.4
            ),
            social_network=SocialNetworkConfig(
                enabled=True,
                decay_rate=0.05,  # VERY slow decay
                habit_weight=0.3,  # Low habit = more influence
                use_realistic_influence=True,
                network_density=0.15  # Denser network
            )
        )
        
        # Policy: Feedback loops enabled
        config.policy = PolicyConfig(
            thresholds=PolicyThresholdsConfig(
                ev_adoption_target=0.6
            )
        )
        config.policy.feedback_loops.enable_network_effects = True
        config.policy.feedback_loops.critical_mass_threshold = 0.15
        
        # Analytics: Track tipping points
        config.analytics.detect_tipping_points = True
        config.analytics.tipping_point_velocity = 0.3  # Sensitive
        config.analytics.tipping_point_duration = 3  # Quick detection
        
        config.enable_social = True
        config.num_agents = 200
        
        return config
    
    @staticmethod
    def congestion_management() -> SimulationConfig:
        """
        Congestion and transit investment scenario.
        
        Use when: Testing congestion pricing, transit mode shift
        Triggers: Congestion charges, transit investment, mode shift
        """
        config = SimulationConfig()
        
        # Infrastructure: Focus on transit
        config.infrastructure = InfrastructureConfig(
            enabled=True,
            num_chargers=40
        )
        
        # Agents: Mixed mode preferences
        config.agents = AgentConfig(
            behavior=AgentBehaviorConfig(
                eco_desire_mean=0.6,
                time_sensitivity_mean=0.7,  # Time-sensitive
                initial_ev_adoption=0.10,
                initial_transit_adoption=0.20  # 20% start on transit
            )
        )
        
        # Policy: Congestion thresholds
        config.policy = PolicyConfig(
            thresholds=PolicyThresholdsConfig(
                congestion_threshold=0.6,
                congestion_charge_trigger=0.75
            )
        )
        
        config.use_congestion = True
        config.num_agents = 150
        
        return config
    
    @staticmethod
    def winter_weather_impact() -> SimulationConfig:
        """
        Winter conditions with EV range reduction.
        
        Use when: Testing weather impacts on EV performance
        Triggers: Range adjustments, charging frequency increase
        """
        config = SimulationConfig()
        
        # Infrastructure: Extra chargers for range anxiety
        config.infrastructure = InfrastructureConfig(
            enabled=True,
            num_chargers=70,
            charger_density_multiplier=1.5
        )
        
        # Environmental: Winter conditions
        config.environmental.weather.enabled = True
        config.environmental.weather.temp_adjustment = -10.0  # -10°C
        config.environmental.weather.force_season_month = 1  # January
        
        # Agents: Concerned about range
        config.agents = AgentConfig(
            behavior=AgentBehaviorConfig(
                eco_desire_mean=0.6,
                comfort_desire_mean=0.7,  # Comfort important in winter
                initial_ev_adoption=0.20
            )
        )
        
        return config
    
    @staticmethod
    def policy_comparison_baseline() -> SimulationConfig:
        """
        Business-as-usual baseline for policy comparisons.
        
        Use when: Creating baseline for scenario comparison
        """
        config = SimulationConfig()
        
        # Infrastructure: Minimal intervention
        config.infrastructure = InfrastructureConfig(
            enabled=True,
            num_chargers=40,
            allow_dynamic_expansion=False  # No expansion
        )
        
        # Agents: Current market
        config.agents = AgentConfig(
            behavior=AgentBehaviorConfig(
                eco_desire_mean=0.4,
                cost_sensitivity_mean=0.6,
                initial_ev_adoption=0.05  # Current ~5%
            )
        )
        
        # Analytics: Enable comparison
        config.analytics.enable_scenario_comparison = True
        config.analytics.comparison_baseline = "business_as_usual"
        
        return config
    
    @staticmethod
    def custom_from_params(**kwargs) -> SimulationConfig:
        """
        Create custom config from keyword arguments.
        
        Usage:
            config = ConfigurationPresets.custom_from_params(
                grid_capacity_mw=50,
                eco_desire_mean=0.8,
                num_agents=100
            )
        """
        config = SimulationConfig()
        
        # Infrastructure params
        if 'grid_capacity_mw' in kwargs:
            config.infrastructure.grid_capacity_mw = kwargs['grid_capacity_mw']
        if 'num_chargers' in kwargs:
            config.infrastructure.num_chargers = kwargs['num_chargers']
        if 'charger_density_multiplier' in kwargs:
            config.infrastructure.charger_density_multiplier = kwargs['charger_density_multiplier']
        
        # Agent behavior params
        if 'eco_desire_mean' in kwargs:
            config.agents.behavior.eco_desire_mean = kwargs['eco_desire_mean']
        if 'cost_sensitivity_mean' in kwargs:
            config.agents.behavior.cost_sensitivity_mean = kwargs['cost_sensitivity_mean']
        if 'initial_ev_adoption' in kwargs:
            config.agents.behavior.initial_ev_adoption = kwargs['initial_ev_adoption']
        
        # Policy params
        if 'grid_intervention_threshold' in kwargs:
            config.policy.thresholds.grid_intervention_threshold = kwargs['grid_intervention_threshold']
        if 'ev_adoption_target' in kwargs:
            config.policy.thresholds.ev_adoption_target = kwargs['ev_adoption_target']
        if 'budget_limit' in kwargs:
            config.policy.thresholds.default_budget_limit = kwargs['budget_limit']
        
        # Core params
        if 'num_agents' in kwargs:
            config.num_agents = kwargs['num_agents']
        if 'steps' in kwargs:
            config.steps = kwargs['steps']
        
        return config
    
    @staticmethod
    def list_presets() -> Dict[str, str]:
        """
        Get list of available presets with descriptions.
        
        Returns:
            Dict mapping preset name to description
        """
        return {
            'default': "Standard balanced configuration",
            'high_ev_demand': "High EV adoption - guaranteed policy triggers",
            'grid_stress_test': "Limited grid capacity stress test",
            'budget_constrained': "Limited budget cost-effective decisions",
            'rapid_adoption': "Rapid adoption with feedback loops",
            'congestion_management': "Congestion pricing and transit",
            'winter_weather_impact': "Winter weather EV range impact",
            'policy_comparison_baseline': "Business-as-usual baseline"
        }
    
    @staticmethod
    def get_preset(name: str) -> SimulationConfig:
        """
        Get preset by name.
        
        Args:
            name: Preset name (see list_presets())
            
        Returns:
            SimulationConfig instance
            
        Raises:
            ValueError if preset name not found
        """
        presets = {
            'default': ConfigurationPresets.default,
            'high_ev_demand': ConfigurationPresets.high_ev_demand,
            'grid_stress_test': ConfigurationPresets.grid_stress_test,
            'budget_constrained': ConfigurationPresets.budget_constrained,
            'rapid_adoption': ConfigurationPresets.rapid_adoption,
            'congestion_management': ConfigurationPresets.congestion_management,
            'winter_weather_impact': ConfigurationPresets.winter_weather_impact,
            'policy_comparison_baseline': ConfigurationPresets.policy_comparison_baseline,
        }
        
        if name not in presets:
            raise ValueError(f"Unknown preset: {name}. Available: {list(presets.keys())}")
        
        return presets[name]()
