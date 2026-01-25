"""
simiulation/infrastructure/depots/depot_manager.py

Depot tracking and management for electric vehicle fleets. This module oversees the status, location, and
operations of depots used for vehicle storage, maintenance, and charging. It interfaces with the fleet
management system and charging session manager to ensure efficient depot utilization and support for
fleet operations.

"""

"""
Freight and commercial depot management.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
import logging
import random

logger = logging.getLogger(__name__)


@dataclass
class Depot:
    """Freight/commercial depot with charging facilities."""
    depot_id: str
    location: Tuple[float, float]
    depot_type: str  # 'delivery', 'freight', 'bus', 'taxi'
    
    # Charging infrastructure
    num_chargers: int = 0
    charger_power_kw: float = 50.0
    
    # Operational hours
    operates_24_7: bool = False
    operating_hours: Optional[Tuple[int, int]] = None  # (start_hour, end_hour)


class DepotManager:
    """Manages freight and commercial depots."""
    
    def __init__(self):
        """Initialize empty depot registry."""
        self.depots: Dict[str, Depot] = {}
        logger.info("DepotManager initialized")
    
    def add_depot(
        self,
        depot_id: str,
        location: Tuple[float, float],
        depot_type: str,
        num_chargers: int = 10,
        charger_power_kw: float = 50.0
    ) -> None:
        """Add a commercial/freight depot."""
        depot = Depot(
            depot_id=depot_id,
            location=location,
            depot_type=depot_type,
            num_chargers=num_chargers,
            charger_power_kw=charger_power_kw
        )
        
        self.depots[depot_id] = depot
        logger.info(f"Added depot: {depot_id} ({depot_type})")
    
    def find_nearest(
        self,
        location: Tuple[float, float],
        depot_type: str = 'any'
    ) -> Optional[Tuple[str, float]]:
        """Find nearest depot to location."""
        nearest = None
        min_distance = float('inf')
        
        for depot_id, depot in self.depots.items():
            if depot_type != 'any' and depot.depot_type != depot_type:
                continue
            
            distance = self._haversine_km(location, depot.location)
            
            if distance < min_distance:
                min_distance = distance
                nearest = (depot_id, distance)
        
        return nearest
    
    def populate_edinburgh(self, num_depots: int = 5) -> None:
        """Quick setup for Edinburgh."""
        lon_min, lon_max = -3.35, -3.05
        lat_min, lat_max = 55.85, 56.00
        
        for i in range(num_depots):
            lon = random.uniform(lon_min, lon_max)
            lat = random.uniform(lat_min, lat_max)
            
            self.add_depot(
                depot_id=f"depot_{i:02d}",
                location=(lon, lat),
                depot_type=random.choice(['delivery', 'bus', 'taxi']),
                num_chargers=random.choice([10, 20, 30]),
                charger_power_kw=50.0
            )
        
        logger.info(f"Populated Edinburgh with {num_depots} depots")
    
    @staticmethod
    def _haversine_km(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
        """Calculate haversine distance."""
        from math import radians, sin, cos, sqrt, atan2
        
        lon1, lat1 = coord1
        lon2, lat2 = coord2
        
        R = 6371.0
        
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        
        a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))
        
        return R * c