from __future__ import annotations
from typing import Any, List, Tuple, Optional
import math
import random

class SpatialEnvironment:
    """Spatial environment with optional OSM routing and movement helpers.

    - If OSMnx + NetworkX are available and origin/dest are lon/lat, compute shortest path.
    - Else fallback to straight-line routes.
    - Provides per-mode speeds and a step duration to support simple movement per tick.
    """

    def __init__(self, step_minutes: float = 1.0) -> None:
        self.graph_loaded = False
        self.osmnx_available = False
        self.G = None  # OSM graph (optional)
        self.step_minutes = step_minutes
        # Speeds in km/min (walk ~5 km/h, bike ~15, bus ~20, car/ev ~30)
        self.speeds_km_min = {
            'walk': 0.083,
            'bike': 0.25,
            'bus': 0.33,
            'car': 0.5,
            'ev': 0.5,
        }

    # ------------------------- OSM integration -------------------------
    def load_osm_graph(
        self,
        place: Optional[str] = None,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        network_type: str = 'all'
    ) -> None:
        """Attempt to load an OSM graph via osmnx if available.

        Args:
            place: e.g., "Edinburgh, UK"
            bbox: (north, south, east, west)
            network_type: 'walk' | 'bike' | 'drive' | 'all', etc.
        """
        try:
            import osmnx as ox  # type: ignore
            import networkx as nx  # type: ignore
        except Exception:
            # Keep fallback
            self.graph_loaded = False
            self.osmnx_available = False
            return

        try:
            if place:
                self.G = ox.graph_from_place(place, network_type=network_type)
            elif bbox:
                north, south, east, west = bbox
                self.G = ox.graph_from_bbox(north, south, east, west, network_type=network_type)
            else:
                self.G = None

            if self.G is not None:
                # Edge lengths for shortest path
                self.G = ox.add_edge_lengths(self.G)
                self.graph_loaded = True
                self.osmnx_available = True
            else:
                self.graph_loaded = False
                self.osmnx_available = False
        except Exception:
            self.G = None
            self.graph_loaded = False
            self.osmnx_available = False

    def compute_route(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str
    ) -> List[Tuple[float, float]]:
        """Compute a route polyline.
        - If OSM graph loaded and origin/dest look like (lon, lat), compute shortest path by edge length.
        - Else return straight line: [origin, dest].
        """
        if self.graph_loaded and self.osmnx_available and self._is_lonlat(origin) and self._is_lonlat(dest):
            try:
                import osmnx as ox  # type: ignore
                import networkx as nx  # type: ignore
                orig_node = ox.distance.nearest_nodes(self.G, origin[0], origin[1])
                dest_node = ox.distance.nearest_nodes(self.G, dest[0], dest[1])
                route_nodes = nx.shortest_path(self.G, orig_node, dest_node, weight='length')
                coords: List[Tuple[float, float]] = []
                for n in route_nodes:
                    data = self.G.nodes[n]
                    coords.append((float(data.get('x')), float(data.get('y'))))
                return coords
            except Exception:
                pass
        # Fallback
        return [origin, dest]

    # ------------------------- Random node seeding -------------------------
    def get_random_node_coords(self) -> Optional[Tuple[float, float]]:
        """Return a random node's (lon, lat) if an OSM graph is loaded; else None."""
        if not (self.graph_loaded and self.osmnx_available and self.G is not None):
            return None
        # nodes(data=True) yields (node_id, data_dict)
        nodes = list(self.G.nodes(data=True))
        if not nodes:
            return None
        _, d = random.choice(nodes)
        x = float(d.get('x'))
        y = float(d.get('y'))
        return (x, y)

    def get_random_origin_dest(self) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
        """Return a random (origin, destination) pair (lon, lat) from the OSM graph; else None."""
        o = self.get_random_node_coords()
        d = self.get_random_node_coords()
        if o is None or d is None:
            return None
        return o, d

    # ------------------------- Metrics & speeds -------------------------
    def get_speed_km_min(self, mode: str) -> float:
        return self.speeds_km_min.get(mode, 0.1)

    @staticmethod
    def _is_lonlat(p: Tuple[float, float]) -> bool:
        x, y = p
        return (-180.0 <= x <= 180.0) and (-90.0 <= y <= 90.0)

    @staticmethod
    def _haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
        """Great-circle distance between two (lon, lat) in kilometers."""
        lon1, lat1 = a
        lon2, lat2 = b
        R = 6371.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlmb = math.radians(lon2 - lon1)
        h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
        return 2 * R * math.asin(math.sqrt(h))

    def _segment_distance_km(self, a: Tuple[float, float], b: Tuple[float, float]) -> float:
        if self._is_lonlat(a) and self._is_lonlat(b):
            return self._haversine_km(a, b)
        # Assume Cartesian kilometers if not lon/lat
        return math.hypot(b[0] - a[0], b[1] - a[1])

    def _distance(self, route: List[Tuple[float, float]]) -> float:
        if not route or len(route) < 2:
            return 0.0
        dist = 0.0
        for i in range(len(route) - 1):
            dist += self._segment_distance_km(route[i], route[i + 1])
        return dist

    def estimate_travel_time(self, route: List[Tuple[float, float]], mode: str) -> float:
        dist_km = self._distance(route)
        v = self.get_speed_km_min(mode)
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

    # ------------------------- Movement utilities -------------------------
    def advance_along_route(
        self,
        route: List[Tuple[float, float]],
        current_index: int,
        offset_km: float,
        mode: str
    ) -> Tuple[int, float, Tuple[float, float]]:
        """Advance along the route by speed*step_minutes for current tick.

        Returns:
            (new_index, new_offset_km, new_location)
        """
        if not route or len(route) < 2:
            return 0, 0.0, route[0] if route else (0.0, 0.0)

        remaining = self.get_speed_km_min(mode) * self.step_minutes
        i = max(0, min(current_index, len(route) - 2))
        off = max(0.0, offset_km)

        while remaining > 1e-9 and i < len(route) - 1:
            (x1, y1), (x2, y2) = route[i], route[i + 1]
            seg_len = self._segment_distance_km((x1, y1), (x2, y2))
            left_on_seg = max(0.0, seg_len - off)
            if remaining < left_on_seg:
                frac = (off + remaining) / seg_len if seg_len > 0 else 1.0
                nx = x1 + frac * (x2 - x1)
                ny = y1 + frac * (y2 - y1)
                off = off + remaining
                remaining = 0.0
                return i, off, (nx, ny)
            else:
                remaining -= left_on_seg
                i += 1
                off = 0.0

        last = route[-1]
        return len(route) - 2, 0.0, last