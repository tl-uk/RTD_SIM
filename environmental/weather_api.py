# environmental/weather_api.py
import requests
from datetime import datetime, timedelta
from typing import Dict, Optional
import math
import logging

logger = logging.getLogger(__name__)

class WeatherManager:
    """
    Weather integration using Open-Meteo API (free, no key required)
    https://open-meteo.com/
    """
    
    def __init__(self, latitude: float = 54.5973, longitude: float = -5.9301, 
                 use_historical: bool = False, start_date: Optional[str] = None,
                 temp_adjustment: float = 0.0, precip_multiplier: float = 1.0, 
                 wind_multiplier: float = 1.0):
        """
        Initialize weather manager for Belfast, Northern Ireland by default.
        
        Args:
            latitude: Location latitude (default: Belfast)
            longitude: Location longitude (default: Belfast)
            use_historical: If True, use historical data instead of forecast
            start_date: Starting date for historical data (format: "2024-01-15")
            temp_adjustment: Temperature adjustment in °C (e.g., -10 for winter stress test)
            precip_multiplier: Precipitation multiplier (e.g., 3.0 for triple rainfall)
            wind_multiplier: Wind speed multiplier (e.g., 2.0 for double wind)
        """
        self.latitude = latitude
        self.longitude = longitude
        self.use_historical = use_historical
        self.start_date = start_date or datetime.now().strftime("%Y-%m-%d")
        
        # Store adjustment parameters
        self.temp_adjustment = temp_adjustment
        self.precip_multiplier = precip_multiplier
        self.wind_multiplier = wind_multiplier
        
        self.base_url_forecast = "https://api.open-meteo.com/v1/forecast"
        self.base_url_historical = "https://archive-api.open-meteo.com/v1/archive"
        
        self.current_conditions = {
            'temperature': 10.0,  # Celsius
            'precipitation': 0.0,  # mm/hour
            'snow_depth': 0.0,    # cm
            'ice_warning': False,
            'wind_speed': 5.0,    # km/h
            'cloud_cover': 50,    # %
            'visibility': 10000,  # meters
        }
        
        # Cache for API responses
        self._weather_cache = []
        self._cache_start_step = 0
        
        logger.info(f"🌤️ WeatherManager initialized for ({latitude}, {longitude})")
        if temp_adjustment != 0 or precip_multiplier != 1.0 or wind_multiplier != 1.0:
            logger.info(f"   Adjustments: Temp {temp_adjustment:+.1f}°C, "
                       f"Precip {precip_multiplier:.1f}x, Wind {wind_multiplier:.1f}x")
    
    def update_weather(self, step: int, time_of_day: float) -> Dict:
        """
        Update weather conditions for current simulation step.
        
        Args:
            step: Current simulation step
            time_of_day: Current hour (0-23.99)
        
        Returns:
            Dictionary of current weather conditions
        """
        # Calculate which hour we need from the cache
        hour_index = step // 60  # Assuming 1 step = 1 minute
        
        # Fetch new data if cache is empty or we've moved past cached data
        if not self._weather_cache or hour_index >= len(self._weather_cache):
            self._fetch_weather_data(step)
        
        # Get current hour's weather
        if hour_index < len(self._weather_cache):
            hourly_data = self._weather_cache[hour_index]
            self._update_conditions_from_data(hourly_data)
        
        return self.current_conditions
    
    def _fetch_weather_data(self, step: int):
        """Fetch weather data from Open-Meteo API."""
        try:
            if self.use_historical:
                url = self._build_historical_url()
            else:
                url = self._build_forecast_url()
            
            logger.info(f"🌐 Fetching weather data from Open-Meteo...")
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            self._parse_weather_response(data)
            self._cache_start_step = step
            
            logger.info(f"✅ Weather data cached for {len(self._weather_cache)} hours")
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️ Failed to fetch weather data: {e}")
            logger.warning("Using fallback synthetic weather")
            self._use_synthetic_weather(step)
    
    def _build_forecast_url(self) -> str:
        """Build URL for forecast API."""
        params = {
            'latitude': self.latitude,
            'longitude': self.longitude,
            'hourly': [
                'temperature_2m',
                'precipitation',
                'snowfall',
                'snow_depth',
                'cloud_cover',
                'wind_speed_10m',
                'visibility',
            ],
            'forecast_days': 7,
        }
        
        param_str = f"latitude={params['latitude']}&longitude={params['longitude']}"
        param_str += f"&hourly={','.join(params['hourly'])}"
        param_str += f"&forecast_days={params['forecast_days']}"
        
        return f"{self.base_url_forecast}?{param_str}"
    
    def _build_historical_url(self) -> str:
        """Build URL for historical weather API."""
        # Get 7 days of historical data starting from start_date
        start = datetime.strptime(self.start_date, "%Y-%m-%d")
        end = start + timedelta(days=7)
        
        params = {
            'latitude': self.latitude,
            'longitude': self.longitude,
            'start_date': start.strftime("%Y-%m-%d"),
            'end_date': end.strftime("%Y-%m-%d"),
            'hourly': [
                'temperature_2m',
                'precipitation',
                'snowfall',
                'snow_depth',
                'cloud_cover',
                'wind_speed_10m',
            ],
        }
        
        param_str = f"latitude={params['latitude']}&longitude={params['longitude']}"
        param_str += f"&start_date={params['start_date']}&end_date={params['end_date']}"
        param_str += f"&hourly={','.join(params['hourly'])}"
        
        return f"{self.base_url_historical}?{param_str}"
    
    def _parse_weather_response(self, data: Dict):
        """Parse Open-Meteo API response into cache."""
        hourly = data.get('hourly', {})
        
        times = hourly.get('time', [])
        temps = hourly.get('temperature_2m', [])
        precip = hourly.get('precipitation', [])
        snowfall = hourly.get('snowfall', [])
        snow_depth = hourly.get('snow_depth', [])
        cloud = hourly.get('cloud_cover', [])
        wind = hourly.get('wind_speed_10m', [])
        visibility = hourly.get('visibility', [10000] * len(times))
        
        self._weather_cache = []
        
        for i in range(len(times)):
            self._weather_cache.append({
                'time': times[i],
                'temperature': temps[i] if i < len(temps) else 10.0,
                'precipitation': precip[i] if i < len(precip) else 0.0,
                'snowfall': snowfall[i] if i < len(snowfall) else 0.0,
                'snow_depth': snow_depth[i] if i < len(snow_depth) else 0.0,
                'cloud_cover': cloud[i] if i < len(cloud) else 50,
                'wind_speed': wind[i] if i < len(wind) else 5.0,
                'visibility': visibility[i] if i < len(visibility) else 10000,
            })
    
    def _update_conditions_from_data(self, hourly_data: Dict):
        """Update current conditions from cached hourly data with adjustments applied."""
        # Get base values from data
        base_temp = hourly_data.get('temperature', 10.0)
        base_precip = hourly_data.get('precipitation', 0.0)
        base_wind = hourly_data.get('wind_speed', 5.0)
        
        # Apply adjustments
        adjusted_temp = base_temp + self.temp_adjustment
        adjusted_precip = base_precip * self.precip_multiplier
        adjusted_wind = base_wind * self.wind_multiplier
        
        self.current_conditions = {
            'temperature': adjusted_temp,
            'precipitation': adjusted_precip,
            'snow_depth': hourly_data.get('snow_depth', 0.0),
            'ice_warning': self._check_ice_conditions_adjusted(adjusted_temp, adjusted_precip),
            'wind_speed': adjusted_wind,
            'cloud_cover': hourly_data.get('cloud_cover', 50),
            'visibility': hourly_data.get('visibility', 10000),
        }
    
    def _check_ice_conditions(self, data: Dict) -> bool:
        """Determine if icy conditions exist (legacy, kept for compatibility)."""
        temp = data.get('temperature', 10.0)
        precip = data.get('precipitation', 0.0)
        return self._check_ice_conditions_adjusted(temp, precip)
    
    def _check_ice_conditions_adjusted(self, temp: float, precip: float) -> bool:
        """Determine if icy conditions exist based on adjusted values."""
        # Ice warning if temperature near freezing and recent precipitation
        return temp <= 2.0 and precip > 0.1
    
    def _use_synthetic_weather(self, step: int):
        """Fallback to synthetic weather patterns if API fails."""
        # Generate 168 hours (7 days) of synthetic data
        self._weather_cache = []
        
        for hour in range(168):
            # Simple sinusoidal temperature pattern
            temp = 10 + 5 * math.sin((hour % 24) * math.pi / 12 - math.pi / 2)
            
            # Random precipitation (20% chance per hour)
            import random
            precip = random.random() * 2 if random.random() < 0.2 else 0.0
            
            self._weather_cache.append({
                'time': f"synthetic_hour_{hour}",
                'temperature': temp,
                'precipitation': precip,
                'snowfall': precip if temp < 2 else 0.0,
                'snow_depth': 0.0,
                'cloud_cover': 60,
                'wind_speed': 10 + random.random() * 10,
                'visibility': 10000,
            })
        
        logger.info("✅ Synthetic weather pattern generated")
    
    def get_mode_speed_multiplier(self, mode: str) -> float:
        """
        Calculate speed reduction multiplier based on current weather.
        
        Returns:
            Multiplier (0.0 to 1.0) where 1.0 = no reduction
        """
        multiplier = 1.0
        
        # Temperature effects
        temp = self.current_conditions['temperature']
        if temp < 0:  # Freezing
            if mode in ['bike', 'ebike']:
                multiplier *= 0.5  # 50% speed reduction
            else:
                multiplier *= 0.7  # 30% reduction for vehicles
        
        # Precipitation effects
        precip = self.current_conditions['precipitation']
        if precip > 0:
            if mode in ['bike', 'ebike', 'walk']:
                multiplier *= 0.85  # 15% reduction
            else:
                multiplier *= 0.9  # 10% reduction
        
        # Snow effects
        snow = self.current_conditions['snow_depth']
        if snow > 0:
            if mode in ['bike', 'ebike']:
                multiplier *= 0.3  # 70% reduction
            elif mode == 'walk':
                multiplier *= 0.6  # 40% reduction
            else:
                multiplier *= 0.5  # 50% reduction for vehicles
        
        # Ice warning
        if self.current_conditions['ice_warning']:
            multiplier *= 0.6  # All modes 40% slower
        
        # Visibility effects
        visibility = self.current_conditions['visibility']
        if visibility < 1000:  # Heavy fog
            multiplier *= 0.7
        
        return max(multiplier, 0.2)  # Never reduce below 20% speed
    
    def get_ev_range_multiplier(self) -> float:
        """
        Calculate EV range reduction due to cold weather.
        
        Returns:
            Multiplier (0.0 to 1.0) where 1.0 = no reduction
        """
        temp = self.current_conditions['temperature']
        
        if temp >= 20:  # Optimal temperature
            return 1.0
        elif temp >= 10:
            return 0.95
        elif temp >= 0:
            return 0.85
        elif temp >= -5:
            return 0.75
        else:  # Extreme cold
            return 0.65
    
    def get_mode_availability(self, mode: str) -> bool:
        """
        Determine if a mode is available given current weather.
        
        Returns:
            True if mode can be used, False if weather prevents it
        """
        # Extreme weather restrictions
        snow = self.current_conditions['snow_depth']
        ice = self.current_conditions['ice_warning']
        
        if snow > 10:  # Heavy snow (>10cm)
            if mode in ['bike', 'ebike']:
                return False  # Bikes unavailable
        
        if ice and mode in ['bike', 'ebike']:
            return False  # Too dangerous
        
        return True


# Convenience function for simulation integration
def create_weather_manager(config) -> Optional[WeatherManager]:
    """Create WeatherManager from simulation config."""
    if not config.weather_enabled:
        return None
    
    return WeatherManager(
        latitude=config.latitude,
        longitude=config.longitude,
        use_historical=config.use_historical_weather,
        start_date=config.weather_start_date,
        temp_adjustment=config.weather_temp_adjustment,
        precip_multiplier=config.weather_precip_multiplier,
        wind_multiplier=config.weather_wind_multiplier
    )