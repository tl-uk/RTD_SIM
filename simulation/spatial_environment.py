from __future__ import annotations
from typing import Any, List, Tuple
import math

class SpatialEnvironment:
    """Spatial environment stub with placeholder OSM hooks.
    - In Phase 2, integrate real OSM graph loading and routing.
    - For now, provides simple estimates based on Euclidean distance and mode-specific parameters.
    """
    def __init__(self) -> None:
        self.graph_loaded = False

    def load_osm_graph(self, source: str | None = None) -> None:
        self.graph_loaded = True

    def compute_route(self, agent_id: str, origin: Tuple[float, float], dest: Tuple[float, float], mode: str) -> List[Tuple[float, float]]:
        return [origin, dest]

    def _distance(self, route: List[Tuple[float, float]]) -> float:
        if not route or len(route) < 2:
            return 0.0
        (x1, y1), (x2, y2) = route[0], route[-1]
        return math.hypot(x2 - x1, y2 - y1)

    def estimate_travel_time(self, route: List[Tuple[float, float]], mode: str) -> float:
        speeds = {'walk': 0.083, 'bike': 0.25, 'bus': 0.33, 'car': 0.5, 'ev': 0.5}  # km/min
        dist_km = self._distance(route)
        v = speeds.get(mode, 0.1)
        return dist_km / v if v > 0 else float('inf')

    def estimate_monetary_cost(self, route: List[Tuple[float, float]], mode: str) -> float:
        base = {'walk': 0.0, 'bike': 0.0, 'bus': 1.5, 'car': 3.0, 'ev': 2.0}
        return base.get(mode, 1.0)

    def estimate_comfort(self, route: List[Tuple[float, float]], mode: str) -> float:
        comfort = {'walk': 0.5, 'bike': 0.6, 'bus': 0.7, 'car': 0.8, 'ev': 0.85}
        return comfort.get(mode, 0.5)

    def estimate_risk(self, route: List[Tuple[float, float]], mode: str) -> float:
        risk = {'walk': 0.2, 'bike': 0.3, 'bus': 0.15, 'car': 0.25, 'ev': 0.20}
        return risk.get(mode, 0.2)

    def estimate_emissions(self, route: List[Tuple[float, float]], mode: str) -> float:
        grams_per_km = {'walk': 0.0, 'bike': 0.0, 'bus': 80.0, 'car': 180.0, 'ev': 60.0}
        dist_km = self._distance(route)
        return grams_per_km.get(mode, 100.0) * dist_km