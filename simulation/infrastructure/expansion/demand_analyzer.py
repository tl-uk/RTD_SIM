"""
simulation/infrastructure/expansion/demand_analyzer.py

Demand analysis for infrastructure expansion.

Hotspot detection for charging demand based on agent travel patterns. This module analyzes agent trip data to identify
areas with high charging demand that may require infrastructure expansion. It interfaces with the
charging session manager and station registry to assess current utilization and predict future needs,
facilitating strategic placement of new charging stations.

"""

from __future__ import annotations
from typing import List, Tuple
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


class DemandAnalyzer:
    """Analyzes charging demand patterns."""
    
    def __init__(self):
        """Initialize demand analyzer."""
        self.demand_heatmap: defaultdict = defaultdict(int)
        
    def record_demand(self, location: Tuple[float, float]) -> None:
        """Record demand at a location."""
        # Round to grid cell (0.01 degree resolution ~1km)
        grid_cell = (round(location[0], 2), round(location[1], 2))
        self.demand_heatmap[grid_cell] += 1
    
    def get_hotspots(self, top_n: int = 10) -> List[Tuple[float, float]]:
        """Get top N demand hotspots."""
        sorted_cells = sorted(
            self.demand_heatmap.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        return [cell for cell, _ in sorted_cells[:top_n]]