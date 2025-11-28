from __future__ import annotations
from typing import Any, List, Tuple, Optional
import math
import random
import logging
import pickle
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import osmnx as ox
    import networkx as nx
    OSMNX_AVAILABLE = True
except ImportError:
    OSMNX_AVAILABLE = False
    logger.warning("OSMnx not available - install with: pip install osmnx")


class SpatialEnvironment:
    """
    Spatial environment with optimized OSM routing.
    
    Phase 2.1 improvements:
    - Graph caching to disk (avoid repeated downloads)
    - Network type selection per mode
    - Precomputed nearest node lookup
    - Better error handling and fallbacks
    """

    def __init__(self, step_minutes: float = 1.0, cache_dir: Optional[Path] = None) -> None:
        self.graph_loaded = False
        self.osmnx_available = OSMNX_AVAILABLE
        self.G = None
        self.step_minutes = step_minutes
        
        # Cache directory for storing graphs
        self.cache_dir = cache_dir or Path.home() / ".rtd_sim_cache" / "osm_graphs"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Speed lookup (km/min)
        self.speeds_km_min = {
            'walk': 0.083,   # ~5 km/h
            'bike': 0.25,    # ~15 km/h
            'bus': 0.33,     # ~20 km/h
            'car': 0.5,      # ~30 km/h
            'ev': 0.5,       # ~30 km/h
        }
        
        # Network type mapping for different modes
        self.mode_network_types = {
            'walk': 'walk',
            'bike': 'bike',
            'bus': 'drive',  # Buses use road network
            'car': 'drive',
            'ev': 'drive',
        }
        
        # Precomputed nearest nodes cache (speeds up routing)
        self._nearest_node_cache = {}

    # ============================================================================
    # OSM Graph Loading & Caching
    # ============================================================================
    
    def load_osm_graph(
        self, 
        place: Optional[str] = None, 
        bbox: Optional[Tuple[float, float, float, float]] = None,
        network_type: str = 'all',
        use_cache: bool = True
    ) -> None:
        """
        Load OSM graph with intelligent caching.
        
        Args:
            place: Place name (e.g., "Edinburgh, UK")
            bbox: Bounding box (north, south, east, west)
            network_type: 'all', 'drive', 'walk', 'bike'
            use_cache: Whether to use cached graph if available
        """
        if not self.osmnx_available:
            logger.warning("OSMnx not available; cannot load graph")
            return
        
        # Generate cache key
        cache_key = self._get_cache_key(place, bbox, network_type)
        cache_path = self.cache_dir / f"{cache_key}.pkl"
        
        # Try loading from cache
        if use_cache and cache_path.exists():
            try:
                logger.info(f"Loading cached OSM graph: {cache_path.name}")
                with open(cache_path, 'rb') as f:
                    self.G = pickle.load(f)
                self.graph_loaded = True
                logger.info(f"Loaded from cache: {len(self.G.nodes)} nodes, {len(self.G.edges)} edges")
                return
            except Exception as e:
                logger.warning(f"Cache load failed: {e}. Re-downloading...")
        
        # Download graph
        try:
            logger.info(f"Downloading OSM graph (network_type={network_type})...")
            
            if place:
                self.G = ox.graph_from_place(place, network_type=network_type)
            elif bbox:
                north, south, east, west = bbox
                self.G = ox.graph_from_bbox(north, south, east, west, network_type=network_type)
            else:
                logger.error("Must provide either place or bbox")
                return
            
            if self.G is not None:
                # Add edge lengths if not present
                try:
                    if not all('length' in data for _, _, data in self.G.edges(data=True)):
                        logger.info("Adding edge lengths...")
                        self.G = ox.distance.add_edge_lengths(self.G)
                except Exception as e:
                    logger.warning(f"Could not add edge lengths: {e}")
                
                # Save to cache
                if use_cache:
                    try:
                        with open(cache_path, 'wb') as f:
                            pickle.dump(self.G, f)
                        logger.info(f"Saved to cache: {cache_path.name}")
                    except Exception as e:
                        logger.warning(f"Cache save failed: {e}")
                
                self.graph_loaded = True
                logger.info(f"OSM graph loaded: {len(self.G.nodes)} nodes, {len(self.G.edges)} edges")
            else:
                self.graph_loaded = False
                logger.error("Graph download returned None")
        
        except Exception as e:
            self.G = None
            self.graph_loaded = False
            logger.exception(f"OSM graph load failed: {e}")
    
    def _get_cache_key(
        self, 
        place: Optional[str], 
        bbox: Optional[Tuple], 
        network_type: str
    ) -> str:
        """Generate unique cache key for graph configuration."""
        import hashlib
        
        if place:
            key_str = f"place_{place}_{network_type}"
        elif bbox:
            key_str = f"bbox_{bbox[0]}_{bbox[1]}_{bbox[2]}_{bbox[3]}_{network_type}"
        else:
            key_str = "default"
        
        return hashlib.md5(key_str.encode()).hexdigest()[:16]
    
    def clear_cache(self) -> None:
        """Clear all cached OSM graphs."""
        if self.cache_dir.exists():
            for f in self.cache_dir.glob("*.pkl"):
                f.unlink()
            logger.info(f"Cleared cache: {self.cache_dir}")

    # ============================================================================
    # Random Point Generation
    # ============================================================================
    
    def get_random_node_coords(self) -> Optional[Tuple[float, float]]:
        """Get random node coordinates from loaded graph."""
        if not (self.graph_loaded and self.osmnx_available and self.G is not None):
            return None
        
        nodes = list(self.G.nodes(data=True))
        if not nodes:
            return None
        
        _, d = random.choice(nodes)
        return (float(d.get('x')), float(d.get('y')))
    
    def get_random_origin_dest(self) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
        """Get random origin and destination from graph."""
        o = self.get_random_node_coords()
        d = self.get_random_node_coords()
        if o is None or d is None:
            return None
        return o, d

    # ============================================================================
    # Routing (Mode-Aware)
    # ============================================================================
    
    def compute_route(
        self, 
        agent_id: str, 
        origin: Tuple[float, float], 
        dest: Tuple[float, float], 
        mode: str
    ) -> List[Tuple[float, float]]:
        """
        Compute route with mode-specific network selection.
        
        Args:
            agent_id: Agent identifier
            origin: (lon, lat) tuple
            dest: (lon, lat) tuple
            mode: Transport mode
        
        Returns:
            List of (lon, lat) waypoints
        """
        # Validate coordinates
        if not (self._is_lonlat(origin) and self._is_lonlat(dest)):
            logger.warning(f"Invalid coordinates for {agent_id}: {origin} → {dest}")
            return [origin, dest]
        
        # Check if graph is available
        if not (self.graph_loaded and self.osmnx_available and self.G is not None):
            return [origin, dest]  # Straight line fallback
        
        try:
            # Get nearest nodes with caching
            orig_node = self._get_nearest_node(origin)
            dest_node = self._get_nearest_node(dest)
            
            if orig_node is None or dest_node is None:
                logger.warning(f"Could not find nearest nodes for {agent_id}")
                return [origin, dest]
            
            # Compute shortest path
            route_nodes = nx.shortest_path(self.G, orig_node, dest_node, weight='length')
            
            # Convert to coordinates
            coords = [
                (float(self.G.nodes[n]['x']), float(self.G.nodes[n]['y'])) 
                for n in route_nodes
            ]
            
            return coords
        
        except nx.NetworkXNoPath:
            logger.warning(f"No path found for {agent_id} ({mode}): {origin} → {dest}")
            return [origin, dest]
        
        except Exception as e:
            logger.exception(f"Routing failed for {agent_id}: {e}")
            return [origin, dest]
    
    def _get_nearest_node(self, coord: Tuple[float, float]) -> Optional[int]:
        """
        Get nearest node with caching.
        
        Args:
            coord: (lon, lat) tuple
        
        Returns:
            Node ID or None
        """
        # Round coordinates for cache key (to ~10m precision)
        cache_key = (round(coord[0], 4), round(coord[1], 4))
        
        if cache_key in self._nearest_node_cache:
            return self._nearest_node_cache[cache_key]
        
        try:
            node = ox.distance.nearest_nodes(self.G, coord[0], coord[1])
            self._nearest_node_cache[cache_key] = node
            return node
        except Exception as e:
            logger.warning(f"Nearest node lookup failed: {e}")
            return None
    
    def densify_route(
        self, 
        route: List[Tuple[float, float]], 
        step_meters: float = 20.0
    ) -> List[Tuple[float, float]]:
        """
        Add intermediate points along route segments.
        
        Useful for smoother visualization.
        
        Args:
            route: List of (lon, lat) waypoints
            step_meters: Target distance between points
        
        Returns:
            Densified route
        """
        if len(route) < 2:
            return route
        
        out = [route[0]]
        
        for i in range(len(route) - 1):
            a, b = route[i], route[i + 1]
            seg_len = self._haversine_m(a, b)
            
            if seg_len <= step_meters:
                out.append(b)
                continue
            
            # Add intermediate points
            n = int(seg_len // step_meters)
            lon1, lat1 = a
            lon2, lat2 = b
            
            for k in range(1, n + 1):
                frac = min(1.0, (k * step_meters) / seg_len)
                out.append((
                    lon1 + (lon2 - lon1) * frac,
                    lat1 + (lat2 - lat1) * frac
                ))
            
            if out[-1] != b:
                out.append(b)
        
        return out

    # ============================================================================
    # Movement & Metrics
    # ============================================================================
    
    def get_speed_km_min(self, mode: str) -> float:
        """Get speed for mode (km/min)."""
        return self.speeds_km_min.get(mode, 0.1)
    
    def estimate_travel_time(self, route: List[Tuple[float, float]], mode: str) -> float:
        """Estimate travel time in minutes."""
        dist_km = self._distance(route)
        v = self.get_speed_km_min(mode)
        return dist_km / v if v > 0 else float('inf')
    
    def estimate_monetary_cost(self, route: List[Tuple[float, float]], mode: str) -> float:
        """Estimate monetary cost."""
        base = {'walk': 0.0, 'bike': 0.0, 'bus': 1.5, 'car': 3.0, 'ev': 2.0}
        return base.get(mode, 1.0)
    
    def estimate_comfort(self, route: List[Tuple[float, float]], mode: str) -> float:
        """Estimate comfort level [0,1]."""
        comfort = {'walk': 0.5, 'bike': 0.6, 'bus': 0.7, 'car': 0.8, 'ev': 0.85}
        return comfort.get(mode, 0.5)
    
    def estimate_risk(self, route: List[Tuple[float, float]], mode: str) -> float:
        """Estimate risk level [0,1]."""
        risk = {'walk': 0.2, 'bike': 0.3, 'bus': 0.15, 'car': 0.25, 'ev': 0.20}
        return risk.get(mode, 0.2)
    
    def estimate_emissions(self, route: List[Tuple[float, float]], mode: str) -> float:
        """Estimate emissions in grams CO2e."""
        grams_per_km = {'walk': 0.0, 'bike': 0.0, 'bus': 80.0, 'car': 180.0, 'ev': 60.0}
        dist_km = self._distance(route)
        return grams_per_km.get(mode, 100.0) * dist_km
    
    def advance_along_route(
        self, 
        route: List[Tuple[float, float]], 
        current_index: int, 
        offset_km: float, 
        mode: str
    ) -> Tuple[int, float, Tuple[float, float]]:
        """
        Move agent along route by one time step.
        
        Args:
            route: List of waypoints
            current_index: Current segment index
            offset_km: Distance along current segment
            mode: Transport mode (determines speed)
        
        Returns:
            (new_index, new_offset, new_position)
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
                # Move partway along segment
                frac = (off + remaining) / seg_len if seg_len > 0 else 1.0
                nx = x1 + frac * (x2 - x1)
                ny = y1 + frac * (y2 - y1)
                off = off + remaining
                remaining = 0.0
                return i, off, (nx, ny)
            else:
                # Move to next segment
                remaining -= left_on_seg
                i += 1
                off = 0.0
        
        # Reached end
        last = route[-1]
        return len(route) - 2, 0.0, last

    # ============================================================================
    # Distance Calculations
    # ============================================================================
    
    @staticmethod
    def _is_lonlat(p: Tuple[float, float]) -> bool:
        """Check if coordinates are valid WGS84."""
        x, y = p
        return (-180.0 <= x <= 180.0) and (-90.0 <= y <= 90.0)
    
    @staticmethod
    def _haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
        """Calculate great circle distance in km."""
        lon1, lat1 = a
        lon2, lat2 = b
        R = 6371.0
        
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlmb = math.radians(lon2 - lon1)
        
        h = (math.sin(dphi / 2) ** 2 + 
             math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2)
        
        return 2 * R * math.asin(math.sqrt(h))
    
    def _haversine_m(self, a: Tuple[float, float], b: Tuple[float, float]) -> float:
        """Calculate great circle distance in meters."""
        return self._haversine_km(a, b) * 1000.0
    
    def _segment_distance_km(self, a: Tuple[float, float], b: Tuple[float, float]) -> float:
        """Calculate segment distance (uses haversine for lat/lon)."""
        if self._is_lonlat(a) and self._is_lonlat(b):
            return self._haversine_km(a, b)
        # Fallback to Euclidean for non-geographic coordinates
        return math.hypot(b[0] - a[0], b[1] - a[1])
    
    def _distance(self, route: List[Tuple[float, float]]) -> float:
        """Calculate total route distance in km."""
        if len(route) < 2:
            return 0.0
        return sum(
            self._segment_distance_km(route[i], route[i + 1]) 
            for i in range(len(route) - 1)
        )

    # ============================================================================
    # Utility Methods
    # ============================================================================
    
    def get_graph_stats(self) -> dict:
        """Get statistics about loaded graph."""
        if not self.graph_loaded or self.G is None:
            return {"loaded": False}
        
        return {
            "loaded": True,
            "nodes": len(self.G.nodes),
            "edges": len(self.G.edges),
            "cache_size": len(self._nearest_node_cache),
        }
    
    def precompute_nearest_nodes(self, points: List[Tuple[float, float]]) -> None:
        """
        Precompute nearest nodes for a list of points.
        
        Useful when you know agent origins/destinations upfront.
        
        Args:
            points: List of (lon, lat) tuples to precompute
        """
        if not (self.graph_loaded and self.G is not None):
            return
        
        logger.info(f"Precomputing nearest nodes for {len(points)} points...")
        for coord in points:
            self._get_nearest_node(coord)
        logger.info(f"Cache size: {len(self._nearest_node_cache)} nodes")