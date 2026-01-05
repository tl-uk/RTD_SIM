"""
simulation/config/simulation_config.py

Configuration classes for simulation runs.
Separated from execution logic for better maintainability.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict, Any
from pathlib import Path
from collections import defaultdict


@dataclass
class SimulationConfig:
    """Configuration for a simulation run."""
    
    # Basic settings
    steps: int = 100
    num_agents: int = 50
    place: str = "Edinburgh, UK"
    extended_bbox: Optional[Tuple[float, float, float, float]] = None
    use_osm: bool = True
    
    # Story settings
    user_stories: List[str] = field(default_factory=list)
    job_stories: List[str] = field(default_factory=list)
    
    # Feature flags
    use_congestion: bool = False
    enable_social: bool = True
    use_realistic_influence: bool = True
    enable_infrastructure: bool = True
    enable_route_diversity: bool = True
    
    # Social network parameters
    decay_rate: float = 0.15
    habit_weight: float = 0.4
    
    # Infrastructure parameters
    num_chargers: int = 50
    num_depots: int = 5
    grid_capacity_mw: float = 1000.0
    
    # Routing parameters
    route_diversity_mode: str = 'ultra_fast'  # 'perturbed', 'k_shortest', 'ultra_fast'
    
    # Scenario framework (Phase 4.5B)
    scenario_name: Optional[str] = None
    scenarios_dir: Optional[Path] = None


@dataclass
class SimulationResults:
    """Container for simulation results."""
    
    # Core results
    time_series: Optional[Any] = None
    env: Optional[Any] = None
    agents: List[Any] = field(default_factory=list)
    
    # Network results
    network: Optional[Any] = None
    influence_system: Optional[Any] = None
    
    # Infrastructure results
    infrastructure: Optional[Any] = None
    
    # Metrics
    adoption_history: Dict[str, List[float]] = field(default_factory=lambda: defaultdict(list))
    cascade_events: List[Dict] = field(default_factory=list)
    desire_std: Dict[str, float] = field(default_factory=dict)
    
    # Execution status
    success: bool = False
    error_message: str = ""
    
    # Scenario results (Phase 4.5B)
    scenario_report: Optional[Dict] = None