"""
siumulation/infrastructure/pricing/dynamic_pricing_engine.py

Dynamic pricing with time-of-day and surge pricing support.

Surge pricing, cost adjustments, recovery, and dynamic pricing strategies for EV charging stations. This module
analyzes real-time data on station utilization, grid load, and external factors to implement
dynamic pricing models. It interfaces with the charging session manager and grid capacity
modules to optimize pricing for both users and infrastructure efficiency.

"""

from __future__ import annotations
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class DynamicPricingEngine:
    """Manages dynamic pricing for charging."""
    
    def __init__(self, enable_time_of_day: bool = False):
        """Initialize pricing engine."""
        self.enable_tod = enable_time_of_day
        self.base_price = 0.15  # £/kWh
        self.surge_multiplier = 1.0
        self.current_hour = 8
        
        # Time-of-day pricing tiers
        self.tod_multipliers = {
            'off_peak': 0.8,    # 00:00-07:00
            'standard': 1.0,    # 07:00-16:00
            'peak': 1.4,        # 16:00-20:00
            'evening': 1.1,     # 20:00-00:00
        }
        
        logger.info(f"DynamicPricingEngine initialized (ToD: {enable_time_of_day})")
    
    def update_hour(self, hour: int) -> None:
        """Update current simulation hour."""
        self.current_hour = hour % 24
    
    def get_tod_tier(self, hour: Optional[int] = None) -> str:
        """Get time-of-day pricing tier."""
        h = hour if hour is not None else self.current_hour
        
        if 0 <= h < 7:
            return 'off_peak'
        elif 7 <= h < 16:
            return 'standard'
        elif 16 <= h < 20:
            return 'peak'
        else:
            return 'evening'
    
    def get_price(self, station_id: str, stations: Dict) -> float:
        """Get current price for a station."""
        if station_id not in stations:
            return self.base_price
        
        station = stations[station_id]
        base = station.cost_per_kwh
        
        # Apply time-of-day multiplier
        if self.enable_tod:
            tier = self.get_tod_tier()
            tod_mult = self.tod_multipliers[tier]
            base *= tod_mult
        
        # Apply surge multiplier
        base *= self.surge_multiplier
        
        return base
    
    def set_surge_multiplier(self, multiplier: float) -> None:
        """Set surge pricing multiplier."""
        self.surge_multiplier = multiplier
        logger.info(f"Surge pricing set to {multiplier}x")
    
    def reset_surge(self) -> None:
        """Reset surge pricing to normal."""
        self.surge_multiplier = 1.0