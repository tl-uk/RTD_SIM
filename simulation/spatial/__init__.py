"""
Spatial subsystem for RTD_SIM.

Modular architecture with single responsibility:
- GraphManager: OSM graph loading & caching
- Router: Route computation & alternatives  
- MetricsCalculator: Performance metrics
- coordinate_utils: Pure utility functions
"""

# Import classes lazily to avoid circular imports
def __getattr__(name):
    if name == 'GraphManager':
        from simulation.spatial.graph_manager import GraphManager
        return GraphManager
    elif name == 'Router':
        from simulation.spatial.router import Router
        return Router
    elif name == 'MetricsCalculator':
        from simulation.spatial.metrics_calculator import MetricsCalculator
        return MetricsCalculator
    elif name == 'coordinate_utils':
        from simulation.spatial import coordinate_utils
        return coordinate_utils
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

__all__ = [
    'GraphManager',
    'Router', 
    'MetricsCalculator',
    'coordinate_utils',
]