"""
simulation/spatial/__init__.py

Spatial subsystem for RTD_SIM.

Modular architecture with single responsibility:
- GraphManager: OSM graph loading & caching
- Router: Route computation & alternatives  
- MetricsCalculator: Performance metrics
- coordinate_utils: Pure utility functions
- CongestionManager: Dynamic congestion data handling
- rail_network: OpenRailMap integration
- rail_spine: UK intercity rail network backbone
- naptan_loader: DfT NaPTAN transfer node integration
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
    elif name == 'CongestionManager': 
        from simulation.spatial.congestion_manager import CongestionManager
        return CongestionManager
    elif name == 'coordinate_utils':
        from simulation.spatial import coordinate_utils
        return coordinate_utils
    elif name == 'rail_network':
        from simulation.spatial import rail_network
        return rail_network
    elif name == 'rail_spine':
        from simulation.spatial import rail_spine
        return rail_spine
    elif name == 'naptan_loader':
        from simulation.spatial import naptan_loader
        return naptan_loader
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

__all__ = [
    'GraphManager',
    'Router', 
    'MetricsCalculator',
    'CongestionManager', 
    'coordinate_utils',
    'rail_network',
    'rail_spine',
    'naptan_loader',
]