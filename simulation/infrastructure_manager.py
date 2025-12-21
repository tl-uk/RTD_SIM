"""
simulation/infrastructure_manager.py

Central infrastructure registry for Phase 4.5.
Manages charging stations, depots, grid capacity, and availability.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Set
from collections import defaultdict
import logging
import math

logger = logging.getLogger(__name__)


@dataclass
class ChargingStation:
    """Individual charging station."""
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


@dataclass
class GridCapacity:
    """Regional grid capacity tracking."""
    region_id: str
    capacity_mw: float
    current_load_mw: float = 0.0
    
    def utilization(self) -> float:
        """Get grid utilization (0-1)."""
        return self.current_load_mw / max(0.001, self.capacity_mw)
    
    def is_overloaded(self, threshold: float = 0.95) -> bool:
        """Check if grid is near capacity."""
        return self.utilization() >= threshold


class InfrastructureManager:
    """
    Central manager for transport infrastructure.
    
    Responsibilities:
    - Track charging station locations and availability
    - Manage depot infrastructure
    - Monitor grid capacity and load
    - Provide infrastructure queries for BDI planner
    """
    
    def __init__(self, grid_capacity_mw: float = 1000.0):
        """
        Initialize infrastructure manager.
        
        Args:
            grid_capacity_mw: Total grid capacity in megawatts
        """
        # Infrastructure registries
        self.charging_stations: Dict[str, ChargingStation] = {}
        self.depots: Dict[str, Depot] = {}
        self.grid_regions: Dict[str, GridCapacity] = {}
        
        # Initialize default grid region
        self.grid_regions['default'] = GridCapacity(
            region_id='default',
            capacity_mw=grid_capacity_mw
        )
        
        # Usage tracking
        self.agent_charging_state: Dict[str, Dict] = {}  # agent_id -> state
        self.historical_utilization: List[float] = []
        
        logger.info(f"InfrastructureManager initialized (grid: {grid_capacity_mw} MW)")
    
    # ========================================================================
    # Charging Station Management
    # ========================================================================
    
    def add_charging_station(
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
        
        self.charging_stations[station_id] = station
        logger.debug(f"Added charging station: {station_id} at {location}")
    
    def find_nearest_charger(
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
        
        for station_id, station in self.charging_stations.items():
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
    
    def get_charger_availability(self, station_id: str) -> Dict:
        """Get detailed availability info for a station."""
        if station_id not in self.charging_stations:
            return {'exists': False}
        
        station = self.charging_stations[station_id]
        
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
    
    def reserve_charger(
        self,
        agent_id: str,
        station_id: str,
        duration_min: float
    ) -> bool:
        """
        Reserve a charger for an agent.
        
        Args:
            agent_id: Agent identifier
            station_id: Charging station ID
            duration_min: Expected charging duration
        
        Returns:
            True if reserved successfully
        """
        if station_id not in self.charging_stations:
            logger.warning(f"Station {station_id} not found")
            return False
        
        station = self.charging_stations[station_id]
        
        if station.is_available():
            # Occupy a port
            station.currently_occupied += 1
            
            # Track agent state
            self.agent_charging_state[agent_id] = {
                'station_id': station_id,
                'start_time': None,  # Set when charging starts
                'duration_min': duration_min,
                'status': 'reserved'
            }
            
            logger.debug(f"Agent {agent_id} reserved {station_id}")
            return True
        else:
            # Add to queue
            if agent_id not in station.queue:
                station.queue.append(agent_id)
                logger.debug(f"Agent {agent_id} queued at {station_id} (pos {len(station.queue)})")
            return False
    
    def release_charger(self, agent_id: str) -> None:
        """Release a charger when agent finishes charging."""
        if agent_id not in self.agent_charging_state:
            return
        
        state = self.agent_charging_state[agent_id]
        station_id = state['station_id']
        
        if station_id in self.charging_stations:
            station = self.charging_stations[station_id]
            station.currently_occupied = max(0, station.currently_occupied - 1)
            
            # Process queue
            if station.queue and station.is_available():
                next_agent = station.queue.pop(0)
                logger.debug(f"Agent {next_agent} moved from queue to charging at {station_id}")
        
        del self.agent_charging_state[agent_id]
        logger.debug(f"Agent {agent_id} released charger at {station_id}")
    
    # ========================================================================
    # Grid Management
    # ========================================================================
    
    def update_grid_load(self, step: int) -> None:
        """
        Update grid load based on active charging.
        
        Call this each simulation step.
        """
        grid = self.grid_regions['default']
        
        # Calculate total load from all active charging
        total_load_kw = 0.0
        
        for agent_id, state in self.agent_charging_state.items():
            if state['status'] == 'charging':
                station_id = state['station_id']
                if station_id in self.charging_stations:
                    station = self.charging_stations[station_id]
                    total_load_kw += station.power_kw
        
        grid.current_load_mw = total_load_kw / 1000.0
        
        # Track history
        self.historical_utilization.append(grid.utilization())
        
        if grid.is_overloaded():
            logger.warning(f"Step {step}: Grid overloaded! ({grid.utilization():.1%})")
    
    def get_grid_stress_factor(self) -> float:
        """
        Get grid stress multiplier for BDI cost calculation.
        
        Returns:
            1.0 = normal, >1.0 = stressed (increases charging cost/time)
        """
        grid = self.grid_regions['default']
        utilization = grid.utilization()
        
        if utilization < 0.7:
            return 1.0  # Normal
        elif utilization < 0.85:
            return 1.2  # Slightly stressed
        elif utilization < 0.95:
            return 1.5  # Stressed
        else:
            return 2.0  # Critical
    
    # ========================================================================
    # Depot Management
    # ========================================================================
    
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
    
    def find_nearest_depot(
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
    
    # ========================================================================
    # Metrics & Analytics
    # ========================================================================
    
    def get_infrastructure_metrics(self) -> Dict:
        """Get comprehensive infrastructure metrics."""
        total_chargers = sum(s.num_ports for s in self.charging_stations.values())
        occupied_chargers = sum(s.currently_occupied for s in self.charging_stations.values())
        total_queued = sum(len(s.queue) for s in self.charging_stations.values())
        
        grid = self.grid_regions['default']
        
        return {
            'charging_stations': len(self.charging_stations),
            'total_ports': total_chargers,
            'occupied_ports': occupied_chargers,
            'utilization': occupied_chargers / max(1, total_chargers),
            'queued_agents': total_queued,
            'depots': len(self.depots),
            'grid_load_mw': grid.current_load_mw,
            'grid_capacity_mw': grid.capacity_mw,
            'grid_utilization': grid.utilization(),
            'grid_stressed': grid.is_overloaded(),
            'active_charging': len([s for s in self.agent_charging_state.values() 
                                   if s['status'] == 'charging']),
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
        
        for station_id, station in self.charging_stations.items():
            if station.occupancy_rate() >= threshold:
                hotspots.append(station_id)
        
        return hotspots
    
    # ========================================================================
    # Utilities
    # ========================================================================
    
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
    
    def populate_edinburgh_chargers(self, num_public: int = 50, num_depot: int = 5) -> None:
        """
        Quick setup for Edinburgh testing.
        
        Args:
            num_public: Number of public chargers to create
            num_depot: Number of depot chargers
        """
        import random
        
        # Edinburgh bounding box
        lon_min, lon_max = -3.35, -3.05
        lat_min, lat_max = 55.85, 56.00
        
        # Public chargers (Level 2)
        for i in range(num_public):
            lon = random.uniform(lon_min, lon_max)
            lat = random.uniform(lat_min, lat_max)
            
            self.add_charging_station(
                station_id=f"public_{i:03d}",
                location=(lon, lat),
                charger_type='level2',
                num_ports=random.choice([2, 4, 6]),
                power_kw=7.0,
                cost_per_kwh=0.15,
                owner_type='public'
            )
        
        # DC Fast chargers (fewer, higher power)
        for i in range(num_public // 5):
            lon = random.uniform(lon_min, lon_max)
            lat = random.uniform(lat_min, lat_max)
            
            self.add_charging_station(
                station_id=f"dcfast_{i:02d}",
                location=(lon, lat),
                charger_type='dcfast',
                num_ports=random.choice([2, 4]),
                power_kw=50.0,
                cost_per_kwh=0.25,
                owner_type='commercial'
            )
        
        # Depots
        for i in range(num_depot):
            lon = random.uniform(lon_min, lon_max)
            lat = random.uniform(lat_min, lat_max)
            
            self.add_depot(
                depot_id=f"depot_{i:02d}",
                location=(lon, lat),
                depot_type=random.choice(['delivery', 'bus', 'taxi']),
                num_chargers=random.choice([10, 20, 30]),
                charger_power_kw=50.0
            )
        
        logger.info(f"Populated Edinburgh with {num_public} public chargers, {num_depot} depots")