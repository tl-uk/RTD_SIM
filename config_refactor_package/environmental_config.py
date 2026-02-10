"""
simulation/config/environmental_config.py

Environmental, weather, and emissions configuration.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class WeatherConfig:
    """Weather simulation parameters."""
    
    enabled: bool = False
    source: str = 'live'  # 'live', 'historical', 'synthetic'
    
    # Manual adjustments
    temp_adjustment: float = 0.0  # Celsius offset
    precip_multiplier: float = 1.0
    wind_multiplier: float = 1.0
    
    # Historical weather
    use_historical: bool = False
    start_date: Optional[str] = None  # "2024-01-15"
    
    # Location (default Edinburgh)
    latitude: float = 55.9533
    longitude: float = -3.1883
    
    # Seasonal forcing
    force_season_month: Optional[int] = None  # Force specific month
    force_season_day: Optional[int] = None


@dataclass
class AirQualityConfig:
    """Air quality tracking configuration."""
    
    enabled: bool = False
    grid_resolution_km: float = 1.0  # Air quality grid cell size
    update_frequency: int = 10  # Update every N steps
    
    # Pollution thresholds (μg/m³)
    pm25_threshold: float = 25.0  # WHO guideline
    no2_threshold: float = 40.0


@dataclass
class EmissionsConfig:
    """Emissions calculation configuration."""
    
    use_lifecycle: bool = True  # Full lifecycle vs tailpipe only
    grid_carbon_intensity: float = 0.233  # UK 2024 (kgCO2/kWh)
    
    # Emission factors (gCO2/km)
    diesel_car_factor: float = 171.0
    petrol_car_factor: float = 192.0
    ev_tailpipe_factor: float = 0.0
    
    # Manufacturing emissions (kgCO2 per vehicle)
    ev_manufacturing: float = 10000.0
    diesel_manufacturing: float = 7000.0


@dataclass
class EnvironmentalConfig:
    """Combined environmental configuration."""
    
    weather: WeatherConfig = None
    air_quality: AirQualityConfig = None
    emissions: EmissionsConfig = None
    
    def __post_init__(self):
        if self.weather is None:
            self.weather = WeatherConfig()
        if self.air_quality is None:
            self.air_quality = AirQualityConfig()
        if self.emissions is None:
            self.emissions = EmissionsConfig()
