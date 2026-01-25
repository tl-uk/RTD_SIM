"""
simulation/infrastructure/charging/charging_session_manager.py

EV range adjustments based on weather conditions.

Temperature-based range adjustment for electric vehicles. This module analyzes weather data to adjust
the estimated driving range of electric vehicles based on ambient temperature conditions. It interfaces with
the vehicle performance model and weather data provider to ensure accurate range predictions, enhancing
route planning and charging strategies.

"""

from __future__ import annotations
from typing import Dict
import logging

logger = logging.getLogger(__name__)


class EVRangeAdjuster:
    """Manages EV range adjustments for weather conditions."""
    
    def __init__(self):
        """Initialize with baseline EV ranges."""
        self._base_ranges = {
            'ev': 350.0,
            'van_electric': 200.0,
            'truck_electric': 250.0,
            'hgv_electric': 300.0,
        }
        
        self._adjusted_ranges = self._base_ranges.copy()
        
        logger.info("EVRangeAdjuster initialized")
    
    def get_base_range(self, mode: str) -> float:
        """Get rated range at optimal temperature."""
        return self._base_ranges.get(mode, 350.0)
    
    def set_adjusted_range(self, mode: str, range_km: float) -> None:
        """Set weather-adjusted range."""
        self._adjusted_ranges[mode] = range_km
    
    def get_adjusted_range(self, mode: str) -> float:
        """Get current adjusted range."""
        return self._adjusted_ranges.get(mode, self.get_base_range(mode))
    
    def apply_temperature_adjustment(self, temperature_c: float) -> None:
        """Apply temperature-based range adjustments to all EV modes."""
        for mode in self._base_ranges:
            base_range = self._base_ranges[mode]
            
            # AAA research: EVs lose ~40% range at -6°C
            if temperature_c >= 20:
                multiplier = 1.0  # Optimal
            elif temperature_c >= 10:
                multiplier = 0.95
            elif temperature_c >= 0:
                multiplier = 0.85
            elif temperature_c >= -10:
                multiplier = 0.75
            else:
                multiplier = 0.60  # Extreme cold
            
            self._adjusted_ranges[mode] = base_range * multiplier
