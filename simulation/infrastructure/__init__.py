"""
simulation/infrastructure/__init__.py

Re-export main infrastructure classes for backward compatibility.

Usage:
    from simulation.infrastructure import InfrastructureManager
    
    # All subsystems accessible through facade
    infra = InfrastructureManager()
"""

from .infrastructure_manager import InfrastructureManager
from .charging.station_registry import ChargingStation, ChargingStationRegistry
from .grid.grid_capacity import GridCapacity, GridCapacityManager
from .depots.depot_manager import Depot, DepotManager

__all__ = [
    'InfrastructureManager',
    'ChargingStation',
    'ChargingStationRegistry',
    'GridCapacity',
    'GridCapacityManager',
    'Depot',
    'DepotManager',
]

__version__ = '5.2.0'