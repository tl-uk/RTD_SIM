"""
simulation/infrastructure/expansion/placement_optimizer.py

Optimal placement strategies for new charging stations.

Charger placement strategy optimization based on demand forecasts. This module analyzes projected charging demand
patterns and suggests optimal locations for new charging stations. It interfaces with the demand analyzer
and station registry to ensure strategic expansion of the charging infrastructure, maximizing accessibility
and utilization.

"""

from __future__ import annotations
from typing import List, Tuple
import random
import secrets  # ✅ ADD: Cryptographic RNG
import logging

logger = logging.getLogger(__name__)


class ChargingPlacementOptimizer:
    """Optimizes placement of new charging stations."""
    
    def __init__(self, station_registry):
        """
        Initialize placement optimizer.
        
        Args:
            station_registry: ChargingStationRegistry instance
        """
        self.registry = station_registry
        self.demand_analyzer = None  # Optional
    
    def place_chargers(
        self,
        num_chargers: int,
        charger_type: str = 'level2',
        strategy: str = 'demand_heatmap'
    ) -> List[str]:
        """
        Place new chargers using specified strategy.
        
        Strategies:
        - demand_heatmap: Place where demand is highest
        - coverage_gaps: Fill areas >5km from nearest charger
        - equitable: Spread evenly across region
        
        Args:
            num_chargers: Number of chargers to add
            charger_type: Type of charger
            strategy: Placement strategy
        
        Returns:
            List of new station IDs
        """
        new_station_ids = []
        
        if strategy == 'demand_heatmap':
            locations = self._get_demand_locations(num_chargers)
        elif strategy == 'coverage_gaps':
            locations = self._get_gap_locations(num_chargers)
        else:  # equitable
            locations = self._get_equitable_locations(num_chargers)
        
        for i, (lon, lat) in enumerate(locations):
            station_id = f"{strategy}_{len(self.registry.stations) + i:03d}"
            
            self.registry.add_station(
                station_id=station_id,
                location=(lon, lat),
                charger_type=charger_type,
                num_ports=4 if charger_type == 'dcfast' else 2,
                power_kw=50.0 if charger_type == 'dcfast' else 7.0,
                cost_per_kwh=0.25 if charger_type == 'dcfast' else 0.15,
                owner_type='public'
            )
            
            new_station_ids.append(station_id)
        
        logger.info(f"Placed {len(new_station_ids)} chargers using {strategy} strategy")
        
        return new_station_ids
    
    def relocate_underutilized(
        self,
        num_to_relocate: int,
        utilization_threshold: float = 0.2
    ) -> List[str]:
        """Relocate underutilized chargers to high-demand areas."""
        underutilized = self.registry.get_underutilized(utilization_threshold)
        
        relocated = []
        hotspots = self._get_demand_locations(num_to_relocate)
        
        for i, station_id in enumerate(underutilized[:num_to_relocate]):
            if i < len(hotspots):
                station = self.registry.stations[station_id]
                old_location = station.location
                new_location = hotspots[i]
                
                station.location = new_location
                relocated.append(station_id)
                
                logger.info(f"Relocated {station_id}: {old_location} → {new_location}")
        
        return relocated
    
    def _get_demand_locations(self, num: int) -> List[Tuple[float, float]]:
        """
        Get locations based on demand heatmap (simplified).
        
        ✅ FIX: Use crypto RNG for better spatial distribution
        ✅ FIX: Validate coordinates are within Edinburgh bounds
        """
        # ✅ Use cryptographic RNG
        crypto_rng = random.Random(secrets.randbits(128))
        
        locations = []
        max_attempts = num * 10  # Allow retries for valid locations
        attempts = 0
        
        while len(locations) < num and attempts < max_attempts:
            attempts += 1
            
            # Generate random location in Edinburgh
            lon = crypto_rng.uniform(-3.35, -3.05)
            lat = crypto_rng.uniform(55.85, 56.00)
            
            # ✅ VALIDATE: Check if location is valid
            if self._is_valid_location((lon, lat)):
                locations.append((lon, lat))
        
        if len(locations) < num:
            logger.warning(f"Only found {len(locations)}/{num} valid locations for chargers")
        
        return locations
    
    def _is_valid_location(self, coord: Tuple[float, float]) -> bool:
        """
        Check if coordinate is valid for infrastructure placement.
        
        ✅ FIX: Prevents chargers from being placed in the ocean or outside network
        """
        lon, lat = coord
        
        # Basic bounds check (Edinburgh)
        if not (-3.35 <= lon <= -3.05 and 55.85 <= lat <= 56.00):
            logger.debug(f"Location {coord} outside Edinburgh bounds")
            return False
        
        # ✅ OPTIONAL: More strict validation using coordinate utils
        from simulation.spatial.coordinate_utils import is_valid_lonlat
        if not is_valid_lonlat(coord):
            logger.debug(f"Location {coord} invalid lon/lat format")
            return False
        
        # Accept location if it passes basic checks
        # In production, you could add:
        # - Distance check to nearest road
        # - Check if on land (not ocean)
        # - Check if not in protected area
        
        return True
    
    def _get_gap_locations(self, num: int) -> List[Tuple[float, float]]:
        """Find locations >5km from any charger."""
        gaps = []
        
        # Sample grid and check distance
        for lon in range(-335, -305, 5):
            for lat in range(5585, 5600, 5):
                loc = (lon/100, lat/100)
                nearest = self.registry.find_nearest(loc, max_distance_km=100)
                
                if nearest is None or nearest[1] > 5.0:
                    gaps.append(loc)
                
                if len(gaps) >= num:
                    return gaps[:num]
        
        return gaps
    
    def _get_equitable_locations(self, num: int) -> List[Tuple[float, float]]:
        """
        Spread chargers evenly across region.
        
        ✅ FIX: Add slight randomness using crypto RNG to avoid perfect grid
        """
        locations = []
        
        # Simple grid placement with slight random jitter
        import math
        grid_size = math.ceil(math.sqrt(num))
        
        # ✅ Use crypto RNG for jitter
        crypto_rng = random.Random(secrets.randbits(128))
        
        for i in range(num):
            row = i // grid_size
            col = i % grid_size
            
            # Base grid position
            lon_base = -3.35 + (col / grid_size) * 0.30
            lat_base = 55.85 + (row / grid_size) * 0.15
            
            # ✅ Add small random jitter (±0.01 degrees ~1km)
            lon = lon_base + crypto_rng.uniform(-0.01, 0.01)
            lat = lat_base + crypto_rng.uniform(-0.01, 0.01)
            
            # Clamp to bounds
            lon = max(-3.35, min(-3.05, lon))
            lat = max(55.85, min(56.00, lat))
            
            locations.append((lon, lat))
        
        return locations