"""
simulation/config/system_dynamics_config.py

Phase 5.3: Configuration for System Dynamics parameters

User-tunable parameters for continuous dynamics:
- EV adoption (logistic growth)
- Grid stress thresholds
- Emissions targets
- Feedback loop strengths
"""

from dataclasses import dataclass


@dataclass
class SystemDynamicsConfig:
    """
    System Dynamics parameters (user-configurable via UI).
    
    These control the continuous differential equations and
    discrete event thresholds in the hybrid system.
    """
    
    # ========================================================================
    # EV ADOPTION DYNAMICS (Logistic Growth Model)
    # ========================================================================
    ev_growth_rate_r: float = 0.05
    """
    Base growth rate for EV adoption.
    
    Range: 0.01 - 0.20
    Typical: 0.03 - 0.08
    
    Higher values → faster adoption
    """
    
    ev_carrying_capacity_K: float = 0.80
    """
    Maximum EV adoption ceiling (carrying capacity).
    
    Range: 0.50 - 1.00
    Typical: 0.70 - 0.90
    
    Represents structural constraints (cost, infrastructure, preferences)
    that prevent 100% adoption.
    """
    
    infrastructure_feedback_strength: float = 0.02
    """
    How much charging infrastructure boosts adoption.
    
    Range: 0.0 - 0.10
    Typical: 0.01 - 0.05
    
    Effect: (chargers / 100) * strength added to growth rate
    Example: 200 chargers * 0.02 = +0.04 to growth rate
    """
    
    social_influence_strength: float = 0.03
    """
    How much peer adoption influences individuals.
    
    Range: 0.0 - 0.10
    Typical: 0.02 - 0.05
    
    Effect: current_adoption * strength added to growth rate
    Creates S-curve acceleration after tipping point
    """
    
    # ========================================================================
    # GRID DYNAMICS
    # ========================================================================
    grid_stress_threshold: float = 0.85
    """
    Grid utilization % that triggers stress events.
    
    Range: 0.70 - 0.95
    Typical: 0.80 - 0.90
    
    When exceeded, policy engine may expand capacity
    """
    
    policy_response_gain: float = 0.5
    """
    How aggressively policy engine reacts to grid stress.
    
    Range: 0.1 - 1.0
    Typical: 0.3 - 0.7
    
    Higher = faster infrastructure expansion
    """
    
    # ========================================================================
    # EMISSIONS DYNAMICS
    # ========================================================================
    emissions_target_kg_day: float = 40000.0
    """
    Daily emissions target (kg CO2).
    
    Range: 10,000 - 100,000
    
    Exceeding this triggers carbon pricing increases
    """
    
    carbon_pricing_sensitivity: float = 0.5
    """
    How much carbon prices increase per kg over target.
    
    Range: 0.0 - 2.0
    Typical: 0.3 - 0.8
    
    Effect: (emissions - target) * sensitivity = price increase (£/kg)
    """
    
    # ========================================================================
    # TIPPING POINTS & THRESHOLDS
    # ========================================================================
    adoption_tipping_point: float = 0.30
    """
    EV adoption % that triggers tipping point event.
    
    Range: 0.20 - 0.40
    Typical: 0.25 - 0.35
    
    After this point, social influence accelerates adoption
    """
    
    grid_emergency_threshold: float = 0.90
    """
    Critical grid utilization % (emergency mode).
    
    Range: 0.85 - 0.98
    Typical: 0.90 - 0.95
    
    Triggers immediate intervention policies
    """
    
    # ========================================================================
    # SENSITIVITY & TUNING
    # ========================================================================
    enable_infrastructure_feedback: bool = True
    """Enable infrastructure → adoption feedback loop."""
    
    enable_social_feedback: bool = True
    """Enable social influence → adoption feedback loop."""
    
    enable_carbon_pricing_feedback: bool = True
    """Enable emissions → carbon price feedback loop."""
    
    @classmethod
    def default(cls):
        """Return default configuration."""
        return cls()
    
    @classmethod
    def aggressive_policy(cls):
        """Aggressive decarbonization scenario."""
        return cls(
            ev_growth_rate_r=0.08,
            infrastructure_feedback_strength=0.05,
            social_influence_strength=0.05,
            grid_stress_threshold=0.80,
            adoption_tipping_point=0.25,
            carbon_pricing_sensitivity=0.8
        )
    
    @classmethod
    def conservative_policy(cls):
        """Conservative/business-as-usual scenario."""
        return cls(
            ev_growth_rate_r=0.03,
            infrastructure_feedback_strength=0.01,
            social_influence_strength=0.02,
            grid_stress_threshold=0.90,
            adoption_tipping_point=0.35,
            carbon_pricing_sensitivity=0.3
        )
    
    def to_dict(self):
        """Convert to dictionary (for serialization)."""
        return {
            'ev_growth_rate_r': self.ev_growth_rate_r,
            'ev_carrying_capacity_K': self.ev_carrying_capacity_K,
            'infrastructure_feedback_strength': self.infrastructure_feedback_strength,
            'social_influence_strength': self.social_influence_strength,
            'grid_stress_threshold': self.grid_stress_threshold,
            'policy_response_gain': self.policy_response_gain,
            'emissions_target_kg_day': self.emissions_target_kg_day,
            'carbon_pricing_sensitivity': self.carbon_pricing_sensitivity,
            'adoption_tipping_point': self.adoption_tipping_point,
            'grid_emergency_threshold': self.grid_emergency_threshold,
        }