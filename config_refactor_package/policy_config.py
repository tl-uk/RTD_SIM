"""
simulation/config/policy_config.py

Policy intervention and combined scenario configuration.
"""

from dataclasses import dataclass
from typing import Optional, Dict


@dataclass
class PolicyThresholdsConfig:
    """Policy intervention thresholds."""
    
    # Grid intervention
    grid_intervention_threshold: float = 0.70  # 70% utilization
    grid_critical_threshold: float = 0.90  # 90% = critical
    
    # EV adoption targets
    ev_adoption_target: float = 0.50  # 50% target
    ev_adoption_warning: float = 0.10  # Warn if below 10%
    
    # Congestion thresholds
    congestion_threshold: float = 0.60  # 60% road utilization
    congestion_charge_trigger: float = 0.75  # 75% = charge zone
    
    # Budget constraints
    default_budget_limit: float = 1000000.0  # £1M default
    budget_warning_threshold: float = 0.80  # Warn at 80%


@dataclass
class FeedbackLoopConfig:
    """Feedback loop parameters."""
    
    # EV adoption feedback
    ev_adoption_infrastructure_multiplier: float = 1.5
    infrastructure_adoption_multiplier: float = 1.3
    
    # Congestion feedback
    congestion_transit_investment_multiplier: float = 1.2
    transit_mode_shift_multiplier: float = 1.1
    
    # Network effects
    enable_network_effects: bool = True
    critical_mass_threshold: float = 0.15  # 15% for tipping


@dataclass
class PolicyConfig:
    """Combined policy configuration."""
    
    thresholds: PolicyThresholdsConfig = None
    feedback_loops: FeedbackLoopConfig = None
    
    # Combined scenario data (from YAML)
    combined_scenario_data: Optional[Dict] = None
    
    def __post_init__(self):
        if self.thresholds is None:
            self.thresholds = PolicyThresholdsConfig()
        if self.feedback_loops is None:
            self.feedback_loops = FeedbackLoopConfig()
