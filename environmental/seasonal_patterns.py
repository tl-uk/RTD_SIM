"""
environmental/seasonal_patterns.py

Seasonal patterns for transport demand and environmental conditions.
Provides multipliers for tourism, freight, EV performance, and mode preferences.
"""

from typing import Dict
import math


def get_seasonal_multipliers(month: int, day_of_year: int) -> Dict[str, float]:
    """
    Get seasonal adjustment multipliers for transport demand and conditions.
    
    Args:
        month: Month number (1-12)
        day_of_year: Day of year (1-365)
    
    Returns:
        Dict of multipliers for various aspects
    """
    
    # Winter: December (12), January (1), February (2)
    if month in [12, 1, 2]:
        return {
            'tourism_demand': 0.6,      # Low season in Scotland
            'freight_demand': 1.3,      # Holiday shopping surge
            'ev_range': 0.75,           # Cold weather battery penalty
            'bike_adoption': 0.3,       # Weather deterrent
            'walk_adoption': 0.5,       # Cold/wet conditions
            'bus_demand': 1.2,          # More public transport use
            'car_demand': 1.1,          # Comfort preference
            'charging_time': 1.25,      # Slower charging in cold
            'grid_heating_load': 1.4,   # High heating demand
        }
    
    # Spring: March (3), April (4), May (5)
    elif month in [3, 4, 5]:
        return {
            'tourism_demand': 0.9,
            'freight_demand': 1.0,
            'ev_range': 0.90,           # Mild temperatures
            'bike_adoption': 0.8,       # Improving weather
            'walk_adoption': 0.9,
            'bus_demand': 1.0,
            'car_demand': 1.0,
            'charging_time': 1.05,
            'grid_heating_load': 1.1,
        }
    
    # Summer: June (6), July (7), August (8)
    elif month in [6, 7, 8]:
        return {
            'tourism_demand': 1.8,      # Peak tourist season
            'freight_demand': 0.9,      # Lower commercial activity
            'ev_range': 1.0,            # Optimal temperature
            'bike_adoption': 1.3,       # Best weather
            'walk_adoption': 1.2,
            'bus_demand': 0.9,          # More active travel
            'car_demand': 0.95,
            'charging_time': 1.0,
            'grid_heating_load': 0.6,   # Minimal heating
        }
    
    # Autumn: September (9), October (10), November (11)
    else:  # month in [9, 10, 11]
        return {
            'tourism_demand': 1.0,
            'freight_demand': 1.1,      # Back to school/work
            'ev_range': 0.85,           # Cooling temperatures
            'bike_adoption': 0.6,       # Deteriorating weather
            'walk_adoption': 0.7,
            'bus_demand': 1.1,
            'car_demand': 1.05,
            'charging_time': 1.15,
            'grid_heating_load': 1.2,
        }


def get_weekly_multiplier(day_of_week: int) -> Dict[str, float]:
    """
    Get day-of-week multipliers.
    
    Args:
        day_of_week: 0=Monday, 6=Sunday
    
    Returns:
        Dict of multipliers
    """
    
    # Weekend
    if day_of_week in [5, 6]:  # Saturday, Sunday
        return {
            'freight_demand': 0.5,      # Minimal commercial activity
            'commute_demand': 0.3,      # Few commuters
            'leisure_demand': 1.8,      # High leisure travel
            'tourism_demand': 1.5,
        }
    
    # Friday
    elif day_of_week == 4:
        return {
            'freight_demand': 1.1,      # End-of-week deliveries
            'commute_demand': 1.0,
            'leisure_demand': 1.3,      # Evening social
            'tourism_demand': 1.2,      # Weekend arrivals
        }
    
    # Monday-Thursday
    else:
        return {
            'freight_demand': 1.2,      # Peak commercial
            'commute_demand': 1.0,
            'leisure_demand': 0.7,
            'tourism_demand': 0.9,
        }


def get_time_of_day_multiplier(hour: int) -> Dict[str, float]:
    """
    Get hourly demand patterns.
    
    Args:
        hour: Hour of day (0-23)
    
    Returns:
        Dict of multipliers
    """
    
    # Night (00:00 - 05:59)
    if 0 <= hour < 6:
        return {
            'car_demand': 0.2,
            'bus_demand': 0.1,
            'freight_demand': 0.8,      # Night deliveries active
            'bike_demand': 0.05,
            'walk_demand': 0.1,
            'grid_load': 0.4,           # Low grid demand
        }
    
    # Morning peak (06:00 - 09:59)
    elif 6 <= hour < 10:
        return {
            'car_demand': 1.5,          # Commute peak
            'bus_demand': 1.8,
            'freight_demand': 1.3,      # Morning deliveries
            'bike_demand': 1.2,
            'walk_demand': 1.1,
            'grid_load': 1.2,
        }
    
    # Midday (10:00 - 15:59)
    elif 10 <= hour < 16:
        return {
            'car_demand': 1.0,
            'bus_demand': 0.9,
            'freight_demand': 1.5,      # Peak freight activity
            'bike_demand': 1.0,
            'walk_demand': 1.2,
            'grid_load': 1.0,
        }
    
    # Evening peak (16:00 - 19:59)
    elif 16 <= hour < 20:
        return {
            'car_demand': 1.6,          # Evening commute
            'bus_demand': 1.7,
            'freight_demand': 0.9,
            'bike_demand': 0.8,
            'walk_demand': 1.0,
            'grid_load': 1.5,           # Peak grid demand
        }
    
    # Night (20:00 - 23:59)
    else:
        return {
            'car_demand': 0.6,
            'bus_demand': 0.4,
            'freight_demand': 0.5,
            'bike_demand': 0.2,
            'walk_demand': 0.4,
            'grid_load': 0.8,
        }


def get_combined_multipliers(
    month: int,
    day_of_year: int,
    day_of_week: int,
    hour: int
) -> Dict[str, float]:
    """
    Get combined seasonal, weekly, and hourly multipliers.
    
    Args:
        month: Month (1-12)
        day_of_year: Day of year (1-365)
        day_of_week: Day of week (0=Mon, 6=Sun)
        hour: Hour of day (0-23)
    
    Returns:
        Dict of combined multipliers
    """
    seasonal = get_seasonal_multipliers(month, day_of_year)
    weekly = get_weekly_multiplier(day_of_week)
    hourly = get_time_of_day_multiplier(hour)
    
    # Combine multipliers
    combined = {}
    
    # Direct seasonal values
    for key in ['ev_range', 'bike_adoption', 'walk_adoption', 
                'charging_time', 'grid_heating_load']:
        combined[key] = seasonal.get(key, 1.0)
    
    # Multiply freight demand across all timeframes
    combined['freight_demand'] = (
        seasonal.get('freight_demand', 1.0) *
        weekly.get('freight_demand', 1.0) *
        hourly.get('freight_demand', 1.0)
    )
    
    # Tourism combines seasonal and weekly
    combined['tourism_demand'] = (
        seasonal.get('tourism_demand', 1.0) *
        weekly.get('tourism_demand', 1.0)
    )
    
    # Mode-specific demand (hourly x seasonal adoption)
    combined['car_demand'] = (
        hourly.get('car_demand', 1.0) *
        seasonal.get('car_demand', 1.0)
    )
    
    combined['bus_demand'] = (
        hourly.get('bus_demand', 1.0) *
        seasonal.get('bus_demand', 1.0)
    )
    
    combined['bike_demand'] = (
        hourly.get('bike_demand', 1.0) *
        seasonal.get('bike_adoption', 1.0)
    )
    
    # Grid load combines hourly baseline with seasonal heating
    combined['grid_load'] = (
        hourly.get('grid_load', 1.0) *
        seasonal.get('grid_heating_load', 1.0)
    )
    
    return combined


def apply_seasonal_ev_range_penalty(
    base_range_km: float,
    temperature_c: float
) -> float:
    """
    Calculate EV range with temperature penalty.
    
    Based on AAA research: EVs lose ~40% range at -6°C
    
    Args:
        base_range_km: Rated range at 20°C
        temperature_c: Current temperature
    
    Returns:
        Adjusted range in km
    """
    if temperature_c >= 20:
        # Optimal temperature
        return base_range_km
    elif temperature_c >= 10:
        # Mild reduction
        penalty = 1.0 - (20 - temperature_c) * 0.01  # 1% per degree
        return base_range_km * penalty
    elif temperature_c >= 0:
        # Moderate reduction
        penalty = 0.9 - (10 - temperature_c) * 0.015  # 1.5% per degree
        return base_range_km * penalty
    elif temperature_c >= -10:
        # Severe reduction
        penalty = 0.75 - (0 - temperature_c) * 0.025  # 2.5% per degree
        return base_range_km * penalty
    else:
        # Extreme cold
        return base_range_km * 0.50  # 50% of rated range


def get_seasonal_mode_preferences(
    month: int,
    weather_conditions: Dict
) -> Dict[str, float]:
    """
    Get mode preference multipliers based on season and weather.
    
    Returns cost multipliers (lower = more preferred).
    
    Args:
        month: Month (1-12)
        weather_conditions: Dict with temperature, precipitation, etc.
    
    Returns:
        Dict of mode cost multipliers
    """
    temp = weather_conditions.get('temperature', 10.0)
    precip = weather_conditions.get('precipitation', 0.0)
    snow = weather_conditions.get('snow_depth', 0.0)
    
    multipliers = {
        'walk': 1.0,
        'bike': 1.0,
        'bus': 1.0,
        'car': 1.0,
        'ev': 1.0,
    }
    
    # Winter penalties for active travel
    if month in [12, 1, 2]:
        multipliers['bike'] *= 1.5  # Harder to choose bike
        multipliers['walk'] *= 1.2
        multipliers['bus'] *= 0.8   # More attractive
    
    # Summer bonuses for active travel
    elif month in [6, 7, 8]:
        multipliers['bike'] *= 0.7  # More attractive
        multipliers['walk'] *= 0.8
        multipliers['car'] *= 1.1   # Less attractive
    
    # Weather-specific adjustments
    if precip > 0:
        multipliers['bike'] *= 1.3
        multipliers['walk'] *= 1.2
    
    if snow > 0:
        multipliers['bike'] *= 2.0  # Very unattractive
        multipliers['walk'] *= 1.5
        multipliers['car'] *= 1.2
    
    if temp < 0:
        multipliers['bike'] *= 1.4
        multipliers['ev'] *= 1.1    # Range anxiety in cold
    
    return multipliers