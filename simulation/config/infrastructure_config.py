"""
simulation/config/infrastructure_config.py

Infrastructure-specific configuration.
Separates grid, charging, and depot settings from core config.
"""

from dataclasses import dataclass


@dataclass
class InfrastructureConfig:
    """Infrastructure configuration for charging, grid, and depots."""
    
    # Master switch
    enabled: bool = True
    
    # Charging infrastructure
    num_chargers: int = 50
    charger_power_kw: float = 50.0  # Standard charger power
    charger_density_multiplier: float = 1.0  # For scaling chargers
    
    # Depot infrastructure
    num_depots: int = 5
    depot_charger_power_kw: float = 150.0  # Fast depot charging
    
    # Grid capacity
    grid_capacity_mw: float = 1000.0
    grid_reserve_margin: float = 0.1  # 10% reserve
    
    # Expansion parameters
    allow_dynamic_expansion: bool = True
    expansion_cost_per_charger: float = 25000.0  # £25k per charger
    expansion_trigger_threshold: float = 0.7  # 70% utilization
    
    # Pricing
    enable_dynamic_pricing: bool = False
    base_price_per_kwh: float = 0.30  # £0.30/kWh
    surge_price_multiplier: float = 2.0
    off_peak_discount: float = 0.5