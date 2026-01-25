"""
simulation/infrastructure/grid/grid_capacity.py

Grid load tracking and capacity management. This module monitors and manages the electrical grid's capacity
to support charging infrastructure. It tracks load levels, forecasts demand spikes,
and implements strategies to prevent overloads, ensuring reliable power delivery
to charging stations.

"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)


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


class GridCapacityManager:
    """Manages grid capacity across regions."""
    
    def __init__(self, default_capacity_mw: float = 1000.0):
        """Initialize with default grid region."""
        self.regions: Dict[str, GridCapacity] = {}
        
        # Create default region
        self.regions['default'] = GridCapacity(
            region_id='default',
            capacity_mw=default_capacity_mw
        )
        
        # Track history
        self.utilization_history: List[float] = []
        
        logger.info(f"GridCapacityManager initialized ({default_capacity_mw} MW)")
    
    def add_region(self, region_id: str, capacity_mw: float) -> None:
        """Add a new grid region."""
        self.regions[region_id] = GridCapacity(
            region_id=region_id,
            capacity_mw=capacity_mw
        )
    
    def update_load(self, load_mw: float, region_id: str = 'default') -> None:
        """Update grid load for a region."""
        if region_id in self.regions:
            self.regions[region_id].current_load_mw = load_mw
            self.utilization_history.append(self.regions[region_id].utilization())
    
    def get_load(self, region_id: str = 'default') -> float:
        """Get current load."""
        return self.regions[region_id].current_load_mw if region_id in self.regions else 0.0
    
    def get_utilization(self, region_id: str = 'default') -> float:
        """Get utilization."""
        return self.regions[region_id].utilization() if region_id in self.regions else 0.0
    
    def get_stress_factor(self, region_id: str = 'default') -> float:
        """
        Get grid stress multiplier for cost calculations.
        
        Returns:
            1.0 = normal, >1.0 = stressed (increases charging cost/time)
        """
        utilization = self.get_utilization(region_id)
        
        if utilization < 0.7:
            return 1.0  # Normal
        elif utilization < 0.85:
            return 1.2  # Slightly stressed
        elif utilization < 0.95:
            return 1.5  # Stressed
        else:
            return 2.0  # Critical
    
    def get_metrics(self) -> Dict:
        """Get grid metrics."""
        default_grid = self.regions.get('default')
        
        if not default_grid:
            return {}
        
        return {
            'grid_load_mw': default_grid.current_load_mw,
            'grid_capacity_mw': default_grid.capacity_mw,
            'grid_utilization': default_grid.utilization(),
            'grid_stressed': default_grid.is_overloaded(),
        }

