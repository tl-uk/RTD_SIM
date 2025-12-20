import logging
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple  

@dataclass
class ChargingStation:
    station_id: str
    location: Tuple[float, float]
    charger_type: str  # 'level2', 'dcfast', 'home'
    num_ports: int
    power_kw: float
    cost_per_kwh: float
    currently_occupied: int = 0
    queue: List[str] = field(default_factory=list)

@dataclass
class Depot:
    depot_id: str
    location: Tuple[float, float]
    
class InfrastructureRegistry:
    def __init__(self):
        self.charging_stations: Dict[str, ChargingStation] = {}
        self.depots: Dict[str, Depot] = {}
        self.grid_capacity_mw: float = 1000.0
        
    def find_nearest_charger(self, location, charger_type='any'):
        # Returns nearest available charger
        pass
        
    def check_availability(self, station_id):
        # Returns True if charger free
        pass
        
    def reserve_charger(self, agent_id, station_id, duration_min):
        # Queue agent for charging
        pass