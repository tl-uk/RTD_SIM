"""
environmental/air_quality.py

Spatial air quality modeling for transport emissions.
Creates heatmaps of PM2.5, NOx, and CO concentrations.
"""

from typing import Dict, List, Tuple, Optional
import math
from collections import defaultdict


class AirQualityTracker:
    """Track and visualize air quality impacts of transport emissions."""
    
    # WHO Air Quality Guidelines (µg/m³)
    WHO_LIMITS = {
        'pm25': {
            'annual': 5.0,      # µg/m³ annual mean
            'daily': 15.0,      # µg/m³ 24-hour mean
        },
        'nox': {
            'annual': 40.0,     # µg/m³ annual mean (as NO2)
            'hourly': 200.0,    # µg/m³ 1-hour mean
        },
        'co': {
            'daily': 4000.0,    # µg/m³ 24-hour mean
        }
    }
    
    # UK legal limits (more lenient than WHO)
    UK_LIMITS = {
        'pm25': {'annual': 10.0},
        'nox': {'annual': 40.0},
    }
    
    def __init__(self, grid_resolution_km: float = 1.0):
        """
        Initialize air quality tracker.
        
        Args:
            grid_resolution_km: Size of spatial grid cells in km
        """
        self.grid_resolution = grid_resolution_km
        
        # Spatial grids: {(grid_x, grid_y): {pollutant: concentration}}
        self.current_concentrations = defaultdict(lambda: {'pm25': 0.0, 'nox': 0.0, 'co': 0.0})
        self.cumulative_concentrations = defaultdict(lambda: {'pm25': 0.0, 'nox': 0.0, 'co': 0.0})
        
        # Track exceedances
        self.exceedance_events = []
        
        # Measurement count (for averaging)
        self.measurement_counts = defaultdict(int)
    
    def _location_to_grid(self, location: Tuple[float, float]) -> Tuple[int, int]:
        """Convert (lon, lat) to grid coordinates."""
        lon, lat = location
        grid_x = int(lon / self.grid_resolution)
        grid_y = int(lat / self.grid_resolution)
        return (grid_x, grid_y)
    
    def add_emissions(
        self,
        location: Tuple[float, float],
        emissions: Dict[str, float],
        dispersion_radius_km: float = 2.0
    ):
        """
        Add emissions to spatial grid with Gaussian dispersion.
        
        Args:
            location: (lon, lat) of emission source
            emissions: Dict with pm25_g, nox_g, co_g
            dispersion_radius_km: How far emissions spread
        """
        center_grid = self._location_to_grid(location)
        
        # Number of grid cells to consider
        radius_cells = int(dispersion_radius_km / self.grid_resolution) + 1
        
        # Gaussian dispersion to neighboring cells
        for dx in range(-radius_cells, radius_cells + 1):
            for dy in range(-radius_cells, radius_cells + 1):
                grid_cell = (center_grid[0] + dx, center_grid[1] + dy)
                
                # Calculate distance from center
                distance_km = math.sqrt(dx**2 + dy**2) * self.grid_resolution
                
                if distance_km > dispersion_radius_km:
                    continue
                
                # Gaussian dispersion factor
                sigma = dispersion_radius_km / 2.0  # Standard deviation
                dispersion_factor = math.exp(-(distance_km**2) / (2 * sigma**2))
                
                # Add dispersed concentrations (convert g to µg/m³)
                # Simplified conversion: assume 1g over 1km² = 1 µg/m³
                self.current_concentrations[grid_cell]['pm25'] += emissions.get('pm25_g', 0) * dispersion_factor
                self.current_concentrations[grid_cell]['nox'] += emissions.get('nox_g', 0) * dispersion_factor
                self.current_concentrations[grid_cell]['co'] += emissions.get('co_g', 0) * dispersion_factor
                
                self.measurement_counts[grid_cell] += 1
    
    def step(self, wind_speed_kmh: float = 10.0):
        """
        Advance one timestep with atmospheric dispersion.
        
        Args:
            wind_speed_kmh: Wind speed for dispersion
        """
        # Decay factor based on wind speed (higher wind = faster dispersion)
        decay_rate = 0.1 + (wind_speed_kmh / 100.0)
        
        # Apply decay to current concentrations
        for grid_cell in self.current_concentrations:
            for pollutant in ['pm25', 'nox', 'co']:
                self.current_concentrations[grid_cell][pollutant] *= (1.0 - decay_rate)
        
        # Accumulate for averaging
        for grid_cell, concentrations in self.current_concentrations.items():
            for pollutant, value in concentrations.items():
                self.cumulative_concentrations[grid_cell][pollutant] += value
    
    def check_exceedances(self, time_period: str = 'hourly') -> List[Dict]:
        """
        Check for WHO guideline exceedances.
        
        Args:
            time_period: 'hourly', 'daily', or 'annual'
        
        Returns:
            List of exceedance events
        """
        exceedances = []
        
        limits = self.WHO_LIMITS
        
        for grid_cell, concentrations in self.current_concentrations.items():
            # PM2.5 check
            if time_period == 'hourly' and concentrations['pm25'] > limits['pm25']['daily']:
                exceedances.append({
                    'grid_cell': grid_cell,
                    'pollutant': 'PM2.5',
                    'concentration': concentrations['pm25'],
                    'limit': limits['pm25']['daily'],
                    'severity': concentrations['pm25'] / limits['pm25']['daily']
                })
            
            # NOx check
            if time_period == 'hourly' and concentrations['nox'] > limits['nox']['hourly']:
                exceedances.append({
                    'grid_cell': grid_cell,
                    'pollutant': 'NOx',
                    'concentration': concentrations['nox'],
                    'limit': limits['nox']['hourly'],
                    'severity': concentrations['nox'] / limits['nox']['hourly']
                })
            
            # CO check
            if time_period == 'daily' and concentrations['co'] > limits['co']['daily']:
                exceedances.append({
                    'grid_cell': grid_cell,
                    'pollutant': 'CO',
                    'concentration': concentrations['co'],
                    'limit': limits['co']['daily'],
                    'severity': concentrations['co'] / limits['co']['daily']
                })
        
        self.exceedance_events.extend(exceedances)
        return exceedances
    
    def get_heatmap(
        self,
        pollutant: str = 'pm25',
        use_cumulative: bool = False
    ) -> Dict[Tuple[int, int], float]:
        """
        Get spatial heatmap of concentrations.
        
        Args:
            pollutant: 'pm25', 'nox', or 'co'
            use_cumulative: If True, return time-averaged concentrations
        
        Returns:
            Dict mapping grid coordinates to concentration values
        """
        source = self.cumulative_concentrations if use_cumulative else self.current_concentrations
        
        heatmap = {}
        
        for grid_cell, concentrations in source.items():
            value = concentrations.get(pollutant, 0.0)
            
            # Average if cumulative
            if use_cumulative and self.measurement_counts[grid_cell] > 0:
                value /= self.measurement_counts[grid_cell]
            
            heatmap[grid_cell] = value
        
        return heatmap
    
    def get_hotspots(
        self,
        pollutant: str = 'pm25',
        threshold_multiplier: float = 2.0
    ) -> List[Dict]:
        """
        Identify pollution hotspots (areas exceeding WHO guidelines).
        
        Args:
            pollutant: Pollutant to check
            threshold_multiplier: Multiple of WHO limit to flag
        
        Returns:
            List of hotspot dicts
        """
        if pollutant == 'pm25':
            limit = self.WHO_LIMITS['pm25']['daily']
        elif pollutant == 'nox':
            limit = self.WHO_LIMITS['nox']['hourly']
        elif pollutant == 'co':
            limit = self.WHO_LIMITS['co']['daily']
        else:
            return []
        
        threshold = limit * threshold_multiplier
        
        hotspots = []
        
        for grid_cell, concentrations in self.current_concentrations.items():
            value = concentrations.get(pollutant, 0.0)
            
            if value > threshold:
                hotspots.append({
                    'grid_cell': grid_cell,
                    'pollutant': pollutant,
                    'concentration': value,
                    'threshold': threshold,
                    'exceedance_factor': value / limit
                })
        
        # Sort by severity
        hotspots.sort(key=lambda x: x['exceedance_factor'], reverse=True)
        
        return hotspots
    
    def get_population_exposure(
        self,
        population_density_map: Dict[Tuple[int, int], float],
        pollutant: str = 'pm25'
    ) -> Dict[str, float]:
        """
        Calculate population exposure metrics.
        
        Args:
            population_density_map: Dict mapping grid cells to population
            pollutant: Pollutant to analyze
        
        Returns:
            Dict with exposure metrics
        """
        total_population = sum(population_density_map.values())
        exposed_population = 0.0
        weighted_exposure = 0.0
        
        limit = self.WHO_LIMITS[pollutant]['daily' if pollutant == 'pm25' else 'hourly']
        
        for grid_cell, population in population_density_map.items():
            concentration = self.current_concentrations[grid_cell].get(pollutant, 0.0)
            
            if concentration > limit:
                exposed_population += population
                weighted_exposure += population * (concentration / limit)
        
        return {
            'total_population': total_population,
            'exposed_population': exposed_population,
            'exposure_rate': exposed_population / total_population if total_population > 0 else 0,
            'weighted_exposure': weighted_exposure,
            'avg_exceedance': weighted_exposure / exposed_population if exposed_population > 0 else 0,
        }
    
    def get_summary_statistics(self) -> Dict[str, Dict[str, float]]:
        """Get summary statistics for all pollutants."""
        stats = {}
        
        for pollutant in ['pm25', 'nox', 'co']:
            values = [c[pollutant] for c in self.current_concentrations.values() if c[pollutant] > 0]
            
            if not values:
                stats[pollutant] = {
                    'min': 0.0,
                    'max': 0.0,
                    'mean': 0.0,
                    'median': 0.0,
                }
                continue
            
            values.sort()
            
            stats[pollutant] = {
                'min': values[0],
                'max': values[-1],
                'mean': sum(values) / len(values),
                'median': values[len(values) // 2],
                'p95': values[int(len(values) * 0.95)] if len(values) > 20 else values[-1],
                'who_limit': self.WHO_LIMITS[pollutant]['daily' if pollutant == 'pm25' else 'hourly'],
            }
        
        return stats
    
    def reset(self):
        """Reset all concentrations and tracking."""
        self.current_concentrations.clear()
        self.cumulative_concentrations.clear()
        self.exceedance_events.clear()
        self.measurement_counts.clear()


def create_air_quality_tracker(config) -> Optional[AirQualityTracker]:
    """
    Create AirQualityTracker from simulation config.
    
    Args:
        config: SimulationConfig instance
    
    Returns:
        AirQualityTracker or None if disabled
    """
    if not getattr(config, 'track_air_quality', False):
        return None
    
    grid_resolution = getattr(config, 'air_quality_grid_km', 1.0)
    
    return AirQualityTracker(grid_resolution_km=grid_resolution)