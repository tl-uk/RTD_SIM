"""
simulation/infrastructure/depots/__init__.py

Depot subsystem exports. 

Re-export depot management classes for easy access.
"""

from .depot_manager import Depot, DepotManager

__all__ = ['Depot', 'DepotManager']