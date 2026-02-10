"""
simulation/config/analytics_config.py

Analytics and tracking configuration.
"""

from dataclasses import dataclass


@dataclass
class AnalyticsConfig:
    """Analytics and tracking configuration."""
    
    # Master switch
    enabled: bool = True
    
    # Tracking flags
    track_journeys: bool = True
    track_mode_share: bool = True
    track_network_efficiency: bool = True
    track_policy_impact: bool = True
    
    # Tipping point detection
    detect_tipping_points: bool = True
    tipping_point_velocity: float = 0.5  # % points per step
    tipping_point_duration: int = 5  # Sustain for N steps
    
    # Policy ROI
    calculate_policy_roi: bool = True
    roi_discount_rate: float = 0.05  # 5% discount rate
    
    # Scenario comparison
    enable_scenario_comparison: bool = False
    comparison_baseline: str = "business_as_usual"
