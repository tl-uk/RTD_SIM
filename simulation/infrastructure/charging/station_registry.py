"""
simulation/infrastructure/charging/station_registry.py

Charging station registry and spatial queries.
Manages all charging station locations and properties.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
import logging
import math
import random

logger = logging.getLogger(__name__)


@dataclass
class ChargingStation:
    """Individual charging station with state tracking."""
    station_id: str
    location: Tuple[float, float]  # (lon, lat)
    charger_type: str  # 'level2', 'dcfast', 'home', 'depot'
    num_ports: int
    power_kw: float
    cost_per_kwh: float
    
    # Real-time state
    currently_occupied: int = 0
    queue: List[str] = field(default_factory=list)  # agent_ids waiting
    
    # Operational
    operational: bool = True
    owner_type: str = 'public'  # 'public', 'private', 'commercial'
    
    # History tracking
    utilization_history: List[float] = field(default_factory=list)
    revenue_history: List[float] = field(default_factory=list)
    
    def is_available(self) -> bool:
        """Check if station has free ports."""
        return self.operational and self.currently_occupied < self.num_ports
    
    def get_queue_wait_time_min(self, avg_charge_time_min: float = 30.0) -> float:
        """Estimate wait time based on queue length."""
        if self.is_available():
            return 0.0
        
        # Queue position × average charge time / number of ports
        return (len(self.queue) * avg_charge_time_min) / max(1, self.num_ports)
    
    def occupancy_rate(self) -> float:
        """Get current occupancy (0-1)."""
        return self.currently_occupied / max(1, self.num_ports)
    
    def record_utilization(self) -> None:
        """Record current utilization for history."""
        self.utilization_history.append(self.occupancy_rate())
    
    def get_avg_utilization(self) -> float:
        """Get average utilization over history."""
        if not self.utilization_history:
            return 0.0
        return sum(self.utilization_history) / len(self.utilization_history)


class ChargingStationRegistry:
    """
    Registry of all charging stations with spatial queries.
    
    Responsibilities:
    - Store station metadata
    - Spatial queries (nearest, within radius)
    - Availability tracking
    - Metrics aggregation
    """
    
    def __init__(self):
        """Initialize empty registry."""
        self.stations: Dict[str, ChargingStation] = {}
        logger.info("ChargingStationRegistry initialized")
    
    def add_station(
        self,
        station_id: str,
        location: Tuple[float, float],
        charger_type: str = 'level2',
        num_ports: int = 2,
        power_kw: float = 7.0,
        cost_per_kwh: float = 0.15,
        owner_type: str = 'public'
    ) -> None:
        """Add a charging station to the registry."""
        station = ChargingStation(
            station_id=station_id,
            location=location,
            charger_type=charger_type,
            num_ports=num_ports,
            power_kw=power_kw,
            cost_per_kwh=cost_per_kwh,
            owner_type=owner_type
        )
        
        self.stations[station_id] = station
        logger.debug(f"Added charging station: {station_id} at {location}")
    
    def find_nearest(
        self,
        location: Tuple[float, float],
        charger_type: str = 'any',
        max_distance_km: float = 5.0,
        require_available: bool = False
    ) -> Optional[Tuple[str, float]]:
        """
        Find nearest charging station to location.
        
        Args:
            location: Search origin (lon, lat)
            charger_type: Required type ('any', 'level2', 'dcfast', 'home')
            max_distance_km: Maximum search radius
            require_available: Only return if ports available
        
        Returns:
            Tuple of (station_id, distance_km) or None
        """
        nearest = None
        min_distance = float('inf')
        
        for station_id, station in self.stations.items():
            # Filter by type
            if charger_type != 'any' and station.charger_type != charger_type:
                continue
            
            # Filter by availability
            if require_available and not station.is_available():
                continue
            
            # Calculate distance
            distance = self._haversine_km(location, station.location)
            
            if distance < min_distance and distance <= max_distance_km:
                min_distance = distance
                nearest = (station_id, distance)
        
        return nearest
    
    def find_within_radius(
        self,
        location: Tuple[float, float],
        radius_km: float = 2.0,
        charger_type: str = 'any'
    ) -> List[Tuple[str, float]]:
        """Find all stations within radius."""
        stations_within = []
        
        for station_id, station in self.stations.items():
            if charger_type != 'any' and station.charger_type != charger_type:
                continue
            
            distance = self._haversine_km(location, station.location)
            
            if distance <= radius_km:
                stations_within.append((station_id, distance))
        
        # Sort by distance
        stations_within.sort(key=lambda x: x[1])
        
        return stations_within
    
    def get_availability(self, station_id: str) -> Dict:
        """Get detailed availability info for a station."""
        if station_id not in self.stations:
            return {'exists': False}
        
        station = self.stations[station_id]
        
        return {
            'exists': True,
            'available': station.is_available(),
            'free_ports': max(0, station.num_ports - station.currently_occupied),
            'total_ports': station.num_ports,
            'queue_length': len(station.queue),
            'estimated_wait_min': station.get_queue_wait_time_min(),
            'occupancy_rate': station.occupancy_rate(),
            'cost_per_kwh': station.cost_per_kwh,
            'charger_type': station.charger_type,
        }
    
    def get_hotspots(self, threshold: float = 0.8) -> List[str]:
        """
        Identify overutilized charging stations.
        
        Args:
            threshold: Occupancy threshold (0-1)
        
        Returns:
            List of station IDs with high utilization
        """
        hotspots = []
        
        for station_id, station in self.stations.items():
            if station.occupancy_rate() >= threshold:
                hotspots.append(station_id)
        
        return hotspots
    
    def get_underutilized(self, threshold: float = 0.2) -> List[str]:
        """Find stations with low average utilization."""
        underutilized = []
        
        for station_id, station in self.stations.items():
            avg_util = station.get_avg_utilization()
            if avg_util < threshold and len(station.utilization_history) > 10:
                underutilized.append(station_id)
        
        return underutilized
    
    def record_all_utilization(self) -> None:
        """Record current utilization for all stations."""
        for station in self.stations.values():
            station.record_utilization()
    
    def get_metrics(self) -> Dict:
        """Get aggregate metrics for all stations."""
        if not self.stations:
            return {
                'charging_stations': 0,
                'total_ports': 0,
                'occupied_ports': 0,
                'utilization': 0.0,
            }
        
        total_ports = sum(s.num_ports for s in self.stations.values())
        occupied = sum(s.currently_occupied for s in self.stations.values())
        queued = sum(len(s.queue) for s in self.stations.values())
        
        return {
            'charging_stations': len(self.stations),
            'total_ports': total_ports,
            'occupied_ports': occupied,
            'utilization': occupied / max(1, total_ports),
            'queued_agents': queued,
        }
    
    def populate_edinburgh(self, num_public: int = 50) -> None:
        """Quick setup for Edinburgh testing."""
        # Edinburgh bounding box
        lon_min, lon_max = -3.35, -3.05
        lat_min, lat_max = 55.85, 56.00
        
        # Public chargers (Level 2)
        for i in range(num_public):
            lon = random.uniform(lon_min, lon_max)
            lat = random.uniform(lat_min, lat_max)
            
            self.add_station(
                station_id=f"public_{i:03d}",
                location=(lon, lat),
                charger_type='level2',
                num_ports=random.choice([2, 4, 6]),
                power_kw=7.0,
                cost_per_kwh=0.15,
                owner_type='public'
            )
        
        # Add 20% DC Fast chargers
        for i in range(num_public // 5):
            lon = random.uniform(lon_min, lon_max)
            lat = random.uniform(lat_min, lat_max)
            
            self.add_station(
                station_id=f"dcfast_{i:02d}",
                location=(lon, lat),
                charger_type='dcfast',
                num_ports=random.choice([2, 4]),
                power_kw=50.0,
                cost_per_kwh=0.25,
                owner_type='commercial'
            )
        
        logger.info(f"Populated Edinburgh with {len(self.stations)} charging stations")
    
    @staticmethod
    def _haversine_km(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
        """Calculate haversine distance in kilometers."""
        from math import radians, sin, cos, sqrt, atan2
        
        lon1, lat1 = coord1
        lon2, lat2 = coord2
        
        R = 6371.0  # Earth radius in km
        
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        
        a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))
        
        return R * c