"""
Dynamic traffic congestion management.

Tracks vehicle density on network edges and adjusts travel times.

Features:
- Edge-level traffic counting
- Congestion-based speed reduction
- Time-of-day patterns (peak hours)
- Decay over time (vehicles leave edges)
- Configurable congestion models
"""

from __future__ import annotations
import logging
from typing import Dict, Tuple, Optional, Set, TYPE_CHECKING
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum

if TYPE_CHECKING:
    from simulation.spatial.graph_manager import GraphManager

logger = logging.getLogger(__name__)


class CongestionModel(Enum):
    """Congestion calculation models."""
    LINEAR = "linear"           # Simple linear increase
    BPR = "bpr"                # Bureau of Public Roads function
    EXPONENTIAL = "exponential" # Exponential growth


@dataclass
class CongestionConfig:
    """Configuration for congestion behavior."""
    
    # Model selection
    model: CongestionModel = CongestionModel.LINEAR
    
    # Linear model parameters
    linear_factor: float = 0.15  # +15% delay per vehicle
    
    # BPR model parameters (standard: t = t0 * (1 + 0.15 * (v/c)^4))
    bpr_alpha: float = 0.15
    bpr_beta: float = 4.0
    
    # Exponential model parameters
    exp_base: float = 1.1  # 1.1^vehicles
    
    # Capacity (vehicles that can use edge simultaneously)
    default_capacity: int = 10
    capacity_by_highway: Dict[str, int] = None
    
    # Congestion limits
    max_congestion_factor: float = 3.0  # Max 3x slower
    min_congestion_factor: float = 1.0  # Min 1x (no speedup)
    
    # Time-of-day patterns (hour -> multiplier)
    peak_hours: Set[int] = None  # e.g., {7, 8, 9, 17, 18, 19}
    peak_multiplier: float = 1.5  # Congestion 50% worse during peaks
    
    # Decay (vehicles gradually leave edges)
    decay_rate: float = 0.1  # 10% of vehicles leave per time step
    
    def __post_init__(self):
        if self.capacity_by_highway is None:
            self.capacity_by_highway = {
                'motorway': 20,
                'trunk': 15,
                'primary': 12,
                'secondary': 10,
                'tertiary': 8,
                'residential': 5,
                'living_street': 3,
            }
        
        if self.peak_hours is None:
            self.peak_hours = {7, 8, 9, 17, 18, 19}


class CongestionManager:
    """
    Manages dynamic traffic congestion across the network.
    
    Tracks vehicle positions and calculates congestion-based delays.
    """
    
    def __init__(
        self,
        graph_manager: 'GraphManager',
        config: Optional[CongestionConfig] = None
    ):
        """
        Initialize congestion manager.
        
        Args:
            graph_manager: GraphManager with loaded network
            config: Congestion configuration (uses defaults if None)
        """
        self.graph_manager = graph_manager
        self.config = config or CongestionConfig()
        
        # Track vehicles on edges: (u, v, key) -> set of agent_ids
        self.edge_vehicles: Dict[Tuple[int, int, int], Set[str]] = defaultdict(set)
        
        # Track agent current edges: agent_id -> (u, v, key)
        self.agent_edges: Dict[str, Tuple[int, int, int]] = {}
        
        # Edge capacities (computed from graph)
        self.edge_capacities: Dict[Tuple[int, int, int], int] = {}
        
        # Current simulation time (for time-of-day patterns)
        self.current_hour: int = 8  # Start at 8 AM
        
        # Statistics
        self.stats = {
            'total_updates': 0,
            'max_congestion_seen': 1.0,
            'congested_edges': 0,
        }
        
        logger.info("CongestionManager initialized")
        self._compute_edge_capacities()
    
    def _compute_edge_capacities(self) -> None:
        """Compute capacity for all edges based on road type."""
        if not self.graph_manager.is_loaded():
            logger.warning("Graph not loaded, using default capacities")
            return
        
        graph = self.graph_manager.primary_graph
        if graph is None:
            return
        
        for u, v, key, data in graph.edges(keys=True, data=True):
            highway_type = data.get('highway', 'residential')
            
            # Handle list of highway types
            if isinstance(highway_type, list):
                highway_type = highway_type[0] if highway_type else 'residential'
            
            capacity = self.config.capacity_by_highway.get(
                highway_type,
                self.config.default_capacity
            )
            
            self.edge_capacities[(u, v, key)] = capacity
        
        logger.info(f"Computed capacities for {len(self.edge_capacities)} edges")
    
    def update_agent_position(
        self,
        agent_id: str,
        current_edge: Optional[Tuple[int, int, int]],
        previous_edge: Optional[Tuple[int, int, int]] = None
    ) -> None:
        """
        Update agent's position in the network.
        
        Args:
            agent_id: Agent identifier
            current_edge: Edge agent is currently on (u, v, key), or None if not on network
            previous_edge: Edge agent was on (for removal), or None to auto-detect
        """
        # Remove from previous edge
        if previous_edge is None and agent_id in self.agent_edges:
            previous_edge = self.agent_edges[agent_id]
        
        if previous_edge is not None:
            self.edge_vehicles[previous_edge].discard(agent_id)
            if not self.edge_vehicles[previous_edge]:
                del self.edge_vehicles[previous_edge]
        
        # Add to current edge
        if current_edge is not None:
            self.edge_vehicles[current_edge].add(agent_id)
            self.agent_edges[agent_id] = current_edge
        elif agent_id in self.agent_edges:
            del self.agent_edges[agent_id]
        
        self.stats['total_updates'] += 1
    
    def get_congestion_factor(
        self,
        u: int,
        v: int,
        key: int = 0
    ) -> float:
        """
        Get congestion multiplier for edge.
        
        Args:
            u, v, key: Edge identifier
        
        Returns:
            Congestion factor (1.0 = no congestion, >1.0 = slower)
        """
        edge = (u, v, key)
        vehicle_count = len(self.edge_vehicles.get(edge, set()))
        
        if vehicle_count == 0:
            return 1.0
        
        # Get capacity
        capacity = self.edge_capacities.get(edge, self.config.default_capacity)
        
        # Calculate base congestion factor
        if self.config.model == CongestionModel.LINEAR:
            factor = 1.0 + (vehicle_count * self.config.linear_factor)
        
        elif self.config.model == CongestionModel.BPR:
            # BPR function: t = t0 * (1 + alpha * (volume/capacity)^beta)
            ratio = vehicle_count / capacity
            factor = 1.0 + self.config.bpr_alpha * (ratio ** self.config.bpr_beta)
        
        elif self.config.model == CongestionModel.EXPONENTIAL:
            factor = self.config.exp_base ** vehicle_count
        
        else:
            factor = 1.0
        
        # Apply time-of-day multiplier
        if self.current_hour in self.config.peak_hours:
            factor *= self.config.peak_multiplier
        
        # Clamp to limits
        factor = max(
            self.config.min_congestion_factor,
            min(self.config.max_congestion_factor, factor)
        )
        
        # Update statistics
        if factor > self.stats['max_congestion_seen']:
            self.stats['max_congestion_seen'] = factor
        
        return factor
    
    def get_edge_vehicle_count(self, u: int, v: int, key: int = 0) -> int:
        """Get number of vehicles on edge."""
        return len(self.edge_vehicles.get((u, v, key), set()))
    
    def apply_decay(self) -> None:
        """
        Apply decay to vehicle counts (simulate vehicles leaving edges).
        
        This helps prevent congestion from accumulating unrealistically
        if agents get stuck or simulation has issues.
        """
        if self.config.decay_rate <= 0:
            return
        
        edges_to_remove = []
        
        for edge, vehicles in list(self.edge_vehicles.items()):
            # Remove random fraction of vehicles
            vehicles_to_remove = set(
                list(vehicles)[:int(len(vehicles) * self.config.decay_rate)]
            )
            
            for agent_id in vehicles_to_remove:
                vehicles.discard(agent_id)
                if agent_id in self.agent_edges:
                    del self.agent_edges[agent_id]
            
            if not vehicles:
                edges_to_remove.append(edge)
        
        for edge in edges_to_remove:
            del self.edge_vehicles[edge]
    
    def advance_time(self, hours: float = 0.0167) -> None:
        """
        Advance simulation time (default: 1 minute).
        
        Args:
            hours: Time to advance in hours
        """
        self.current_hour = int((self.current_hour + hours) % 24)
    
    def get_congested_edges(self, threshold: float = 1.5) -> list:
        """
        Get list of edges with congestion above threshold.
        
        Args:
            threshold: Congestion factor threshold
        
        Returns:
            List of (edge, factor, vehicle_count) tuples
        """
        congested = []
        
        for edge, vehicles in self.edge_vehicles.items():
            if not vehicles:
                continue
            
            factor = self.get_congestion_factor(*edge)
            if factor >= threshold:
                congested.append((edge, factor, len(vehicles)))
        
        return sorted(congested, key=lambda x: x[1], reverse=True)
    
    def get_stats(self) -> dict:
        """Get congestion statistics."""
        total_vehicles = sum(len(v) for v in self.edge_vehicles.values())
        congested_count = len([
            e for e in self.edge_vehicles.keys()
            if self.get_congestion_factor(*e) > 1.2
        ])
        
        return {
            'total_edges_with_vehicles': len(self.edge_vehicles),
            'total_vehicles_on_network': total_vehicles,
            'congested_edges': congested_count,
            'max_congestion_factor': self.stats['max_congestion_seen'],
            'current_hour': self.current_hour,
            'total_updates': self.stats['total_updates'],
        }
    
    def reset(self) -> None:
        """Reset all congestion data."""
        self.edge_vehicles.clear()
        self.agent_edges.clear()
        self.stats = {
            'total_updates': 0,
            'max_congestion_seen': 1.0,
            'congested_edges': 0,
        }
        self.current_hour = 8
        logger.info("Congestion data reset")
    
    def get_congestion_heatmap(self) -> Dict[Tuple[int, int, int], float]:
        """
        Get congestion factor for all edges with vehicles.
        
        Returns:
            Dictionary mapping edge -> congestion_factor
        """
        heatmap = {}
        for edge in self.edge_vehicles.keys():
            heatmap[edge] = self.get_congestion_factor(*edge)
        return heatmap