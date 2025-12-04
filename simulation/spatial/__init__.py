"""
Spatial subsystem for RTD_SIM.

Modular architecture with single responsibility:
- GraphManager: OSM graph loading & caching
- Router: Route computation & alternatives  
- MetricsCalculator: Performance metrics
- coordinate_utils: Pure utility functions
"""

from simulation.spatial.graph_manager import GraphManager
from simulation.spatial.router import Router
from simulation.spatial.metrics_calculator import MetricsCalculator
from simulation.spatial import coordinate_utils

__all__ = [
    'GraphManager',
    'Router', 
    'MetricsCalculator',
    'coordinate_utils',
]