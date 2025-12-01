"""
Enhanced SpatialEnvironment with:
- Mode-specific routing (different networks per mode)
- Elevation data integration
- Energy consumption with elevation adjustments

New in this version:
- load_mode_specific_graphs() - Load separate graphs for walk/bike/drive
- compute_route() - Now uses mode-appropriate graph
- add_elevation_data() - Add elevation to graph nodes
- estimate_emissions_with_elevation() - Adjust for hills
"""

from __future__ import annotations
from typing import Any, List, Tuple, Optional, Dict
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
    logger.warning("OSMnx not available")

try:
    from simulation.elevation_provider import ElevationProvider
    ELEVATION_PROVIDER_AVAILABLE = True
except ImportError:
    ELEVATION_PROVIDER_AVAILABLE = False

class SpatialEnvironment:
    """Enhanced spatial environment with mode-specific routing and elevation."""

    def __init__(self, step_minutes: float = 1.0, cache_dir: Optional[Path] = None) -> None:
        self.graph_loaded = False
        self.osmnx_available = OSMNX_AVAILABLE
        self.G = None  # Primary graph (all networks)
        self.mode_graphs: Dict[str, Any] = {}  # Mode-specific graphs
        self.step_minutes = step_minutes
        self.has_elevation = False
        
        self.cache_dir = cache_dir or Path.home() / ".rtd_sim_cache" / "osm_graphs"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.speeds_km_min = {
            'walk': 0.083,
            'bike': 0.25,
            'bus': 0.33,
            'car': 0.5,
            'ev': 0.5,
        }
        
        # Map modes to OSM network types
        self.mode_network_types = {
            'walk': 'walk',
            'bike': 'bike',
            'bus': 'drive',
            'car': 'drive',
            'ev': 'drive',
        }
        
        self._nearest_node_cache: Dict[str, Dict] = {}  # Per-graph cache

    # ============================================================================
    # Multi-Graph Loading (Mode-Specific)
    # ============================================================================
    
    def load_mode_specific_graphs(
        self,
        place: Optional[str] = None,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        modes: List[str] = None,
        use_cache: bool = True
    ) -> None:
        """
        Load separate OSM graphs for different transport modes.
        
        This enables mode-specific routing:
        - Walkers can use pedestrian paths
        - Cyclists use bike lanes
        - Cars use roads
        
        Args:
            place: Place name
            bbox: Bounding box
            modes: List of modes to load graphs for (default: walk, bike, drive)
            use_cache: Use cached graphs
        """
        if not self.osmnx_available:
            logger.warning("OSMnx not available")
            return
        
        modes = modes or ['walk', 'bike', 'drive']
        network_types = set(self.mode_network_types.get(m, 'all') for m in modes)
        
        logger.info(f"Loading graphs for modes: {modes}")
        logger.info(f"Network types: {network_types}")
        
        for net_type in network_types:
            cache_key = self._get_cache_key(place, bbox, net_type)
            cache_path = self.cache_dir / f"{cache_key}.pkl"
            
            graph = None
            
            # Try cache
            if use_cache and cache_path.exists():
                try:
                    logger.info(f"Loading {net_type} from cache...")
                    with open(cache_path, 'rb') as f:
                        graph = pickle.load(f)
                except Exception as e:
                    logger.warning(f"Cache load failed: {e}")
            
            # Download if needed
            if graph is None:
                try:
                    logger.info(f"Downloading {net_type} network...")
                    if place:
                        graph = ox.graph_from_place(place, network_type=net_type)
                    elif bbox:
                        north, south, east, west = bbox
                        graph = ox.graph_from_bbox(north, south, east, west, network_type=net_type)
                    
                    if graph is not None:
                        # Add edge lengths
                        if not all('length' in data for _, _, data in graph.edges(data=True)):
                            graph = ox.distance.add_edge_lengths(graph)
                        
                        # Cache it
                        if use_cache:
                            with open(cache_path, 'wb') as f:
                                pickle.dump(graph, f)
                            logger.info(f"Cached {net_type} graph")
                
                except Exception as e:
                    logger.exception(f"Failed to load {net_type}: {e}")
            
            # Store graph
            if graph is not None:
                self.mode_graphs[net_type] = graph
                logger.info(f"Loaded {net_type}: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
                
                # Set primary graph to 'all' or first loaded
                if self.G is None or net_type == 'all':
                    self.G = graph
                    self.graph_loaded = True
        
        if self.mode_graphs:
            logger.info(f"Loaded {len(self.mode_graphs)} mode-specific graphs")
        else:
            logger.warning("No graphs loaded")
    
    def load_osm_graph(
        self, 
        place: Optional[str] = None, 
        bbox: Optional[Tuple[float, float, float, float]] = None,
        network_type: str = 'all',
        use_cache: bool = True
    ) -> None:
        """Load single OSM graph (backward compatible)."""
        if not self.osmnx_available:
            logger.warning("OSMnx not available")
            return
        
        cache_key = self._get_cache_key(place, bbox, network_type)
        cache_path = self.cache_dir / f"{cache_key}.pkl"
        
        if use_cache and cache_path.exists():
            try:
                logger.info(f"Loading from cache: {cache_path.name}")
                with open(cache_path, 'rb') as f:
                    self.G = pickle.load(f)
                self.graph_loaded = True
                logger.info(f"Loaded: {len(self.G.nodes)} nodes, {len(self.G.edges)} edges")
                return
            except Exception as e:
                logger.warning(f"Cache load failed: {e}")
        
        try:
            logger.info(f"Downloading OSM graph (network_type={network_type})...")
            
            if place:
                self.G = ox.graph_from_place(place, network_type=network_type)
            elif bbox:
                north, south, east, west = bbox
                self.G = ox.graph_from_bbox(north, south, east, west, network_type=network_type)
            else:
                logger.error("Must provide place or bbox")
                return
            
            if self.G is not None:
                if not all('length' in data for _, _, data in self.G.edges(data=True)):
                    logger.info("Adding edge lengths...")
                    self.G = ox.distance.add_edge_lengths(self.G)
                
                if use_cache:
                    try:
                        with open(cache_path, 'wb') as f:
                            pickle.dump(self.G, f)
                        logger.info(f"Saved to cache: {cache_path.name}")
                    except Exception as e:
                        logger.warning(f"Cache save failed: {e}")
                
                self.graph_loaded = True
                logger.info(f"Graph loaded: {len(self.G.nodes)} nodes, {len(self.G.edges)} edges")
        
        except Exception as e:
            self.G = None
            self.graph_loaded = False
            logger.exception(f"OSM load failed: {e}")
    
    def _get_cache_key(self, place: Optional[str], bbox: Optional[Tuple], network_type: str) -> str:
        import hashlib
        if place:
            key_str = f"place_{place}_{network_type}"
        elif bbox:
            key_str = f"bbox_{bbox[0]}_{bbox[1]}_{bbox[2]}_{bbox[3]}_{network_type}"
        else:
            key_str = "default"
        return hashlib.md5(key_str.encode()).hexdigest()[:16]

    # ============================================================================
    # Elevation Integration
    # ============================================================================
    
    def add_elevation_data(self, method: str = 'opentopo', **kwargs) -> bool:
        """
        Add elevation data to graph nodes using free open-source methods.
        
        Args:
            method: 'opentopo' (default, free), 'opentopo_ned' (US only), 'raster', or 'google'
            **kwargs: Additional arguments for specific methods
                - raster_path: Path to DEM file (for method='raster')
                - api_key: Google API key (for method='google')
                - api: Which OpenTopoData API (for method='opentopo')
        
        Returns:
            True if elevation added successfully
        """
        if not self.graph_loaded or self.G is None:
            logger.warning("No graph loaded")
            return False
        
        try:
            if method in ['opentopo', 'opentopo_ned', 'opentopo_mapzen']:
                # Use our ElevationProvider
                from .elevation_provider import ElevationProvider
                
                provider = ElevationProvider(cache_dir=self.cache_dir.parent / "elevation")
                api = kwargs.get('api', method)
                
                logger.info(f"Adding elevation using {api}...")
                self.G = provider.add_elevation_to_graph(self.G, api=api)
            
            elif method == 'raster':
                raster_path = kwargs.get('raster_path')
                if raster_path is None:
                    logger.error("Must provide raster_path for method='raster'")
                    return False
                logger.info(f"Adding elevation from raster: {raster_path}")
                self.G = ox.elevation.add_node_elevations_raster(self.G, raster_path)
            
            elif method == 'google':
                api_key = kwargs.get('api_key')
                if api_key is None:
                    logger.error("Must provide api_key for method='google'")
                    return False
                logger.info("Adding elevation from Google API")
                self.G = ox.elevation.add_node_elevations_google(self.G, api_key=api_key)
            
            else:
                logger.error(f"Unknown method: {method}")
                return False
            
            # Check if elevation was added
            sample_nodes = list(self.G.nodes(data=True))[:10]
            has_elev = any('elevation' in data for _, data in sample_nodes)
            
            if has_elev:
                self.has_elevation = True
                elevations = [data.get('elevation') for _, data in sample_nodes if 'elevation' in data]
                logger.info(f"✅ Elevation data added (sample: {elevations[:3]})")
                return True
            else:
                logger.warning("⚠️ Elevation not found in nodes")
                return False
        
        except Exception as e:
            logger.exception(f"Failed to add elevation: {e}")
            return False

    # ============================================================================
    # Mode-Specific Routing
    # ============================================================================
    
    def compute_route(
        self, 
        agent_id: str, 
        origin: Tuple[float, float], 
        dest: Tuple[float, float], 
        mode: str
    ) -> List[Tuple[float, float]]:
        """
        Compute route using mode-appropriate network.
        
        If mode-specific graphs loaded, use appropriate one.
        Otherwise fall back to primary graph.
        """
        if not (self._is_lonlat(origin) and self._is_lonlat(dest)):
            logger.warning(f"Invalid coords: {origin} → {dest}")
            return [origin, dest]
        
        # Select graph for this mode
        network_type = self.mode_network_types.get(mode, 'all')
        graph = self.mode_graphs.get(network_type, self.G)
        
        if graph is None:
            return [origin, dest]
        
        try:
            orig_node = self._get_nearest_node(origin, network_type)
            dest_node = self._get_nearest_node(dest, network_type)
            
            if orig_node is None or dest_node is None:
                logger.warning(f"Could not find nodes for {agent_id}")
                return [origin, dest]
            
            route_nodes = nx.shortest_path(graph, orig_node, dest_node, weight='length')
            coords = [(float(graph.nodes[n]['x']), float(graph.nodes[n]['y'])) for n in route_nodes]
            
            return coords
        
        except nx.NetworkXNoPath:
            logger.warning(f"No path for {agent_id} ({mode})")
            return [origin, dest]
        except Exception as e:
            logger.exception(f"Routing failed: {e}")
            return [origin, dest]
    
    def _get_nearest_node(self, coord: Tuple[float, float], network_type: str = 'all') -> Optional[int]:
        """Get nearest node with per-graph caching."""
        cache_key = (round(coord[0], 4), round(coord[1], 4))
        
        if network_type not in self._nearest_node_cache:
            self._nearest_node_cache[network_type] = {}
        
        cache = self._nearest_node_cache[network_type]
        
        if cache_key in cache:
            return cache[cache_key]
        
        graph = self.mode_graphs.get(network_type, self.G)
        if graph is None:
            return None
        
        try:
            node = ox.distance.nearest_nodes(graph, coord[0], coord[1])
            cache[cache_key] = node
            return node
        except Exception as e:
            logger.warning(f"Nearest node failed: {e}")
            return None

    # ============================================================================
    # Elevation-Aware Energy Consumption
    # ============================================================================
    
    def estimate_emissions_with_elevation(
        self, 
        route: List[Tuple[float, float]], 
        mode: str
    ) -> float:
        """
        Estimate emissions accounting for elevation changes.
        
        Returns emissions in grams CO2e.
        """
        if not self.has_elevation or not self.graph_loaded:
            # Fall back to flat calculation
            return self.estimate_emissions(route, mode)
        
        if len(route) < 2:
            return 0.0
        
        # Base emissions (grams per km)
        base_grams_per_km = {
            'walk': 0.0, 'bike': 0.0, 
            'bus': 80.0, 'car': 180.0, 'ev': 60.0
        }
        base_rate = base_grams_per_km.get(mode, 100.0)
        
        # Get network for this mode
        network_type = self.mode_network_types.get(mode, 'all')
        graph = self.mode_graphs.get(network_type, self.G)
        
        if graph is None:
            return self.estimate_emissions(route, mode)
        
        total_emissions = 0.0
        
        try:
            for i in range(len(route) - 1):
                p1, p2 = route[i], route[i+1]
                
                # Get nearest nodes
                n1 = self._get_nearest_node(p1, network_type)
                n2 = self._get_nearest_node(p2, network_type)
                
                if n1 is None or n2 is None:
                    # Fallback
                    seg_dist = self._segment_distance_km(p1, p2)
                    total_emissions += base_rate * seg_dist
                    continue
                
                # Get elevations
                elev1 = graph.nodes[n1].get('elevation', 0)
                elev2 = graph.nodes[n2].get('elevation', 0)
                
                # Calculate segment distance and elevation change
                seg_dist = self._segment_distance_km(p1, p2)
                elev_change = elev2 - elev1  # meters
                
                # Calculate grade (rise/run)
                grade = elev_change / (seg_dist * 1000) if seg_dist > 0 else 0
                
                # Adjustment factor based on grade
                # Uphill: +50% per 10% grade
                # Downhill: -20% per 10% grade (regenerative braking)
                if grade > 0:  # Uphill
                    factor = 1.0 + (5.0 * grade)  # +50% per 10% grade
                else:  # Downhill
                    factor = 1.0 + (2.0 * grade)  # -20% per 10% grade
                    factor = max(0.5, factor)  # Min 50% of base
                
                factor = max(0.5, min(2.0, factor))  # Clamp to [0.5, 2.0]
                
                seg_emissions = base_rate * seg_dist * factor
                total_emissions += seg_emissions
        
        except Exception as e:
            logger.warning(f"Elevation-aware calculation failed: {e}")
            return self.estimate_emissions(route, mode)
        
        return total_emissions

    # ============================================================================
    # Standard Methods (unchanged)
    # ============================================================================
    
    def get_random_node_coords(self) -> Optional[Tuple[float, float]]:
        if not (self.graph_loaded and self.G is not None):
            return None
        nodes = list(self.G.nodes(data=True))
        if not nodes:
            return None
        _, d = random.choice(nodes)
        return (float(d.get('x')), float(d.get('y')))
    
    def get_random_origin_dest(self) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
        o = self.get_random_node_coords()
        d = self.get_random_node_coords()
        if o is None or d is None:
            return None
        return o, d
    
    def densify_route(self, route: List[Tuple[float, float]], step_meters: float = 20.0) -> List[Tuple[float, float]]:
        if len(route) < 2:
            return route
        out = [route[0]]
        for i in range(len(route) - 1):
            a, b = route[i], route[i + 1]
            seg_len = self._haversine_m(a, b)
            if seg_len <= step_meters:
                out.append(b)
                continue
            n = int(seg_len // step_meters)
            lon1, lat1 = a
            lon2, lat2 = b
            for k in range(1, n + 1):
                frac = min(1.0, (k * step_meters) / seg_len)
                out.append((lon1 + (lon2 - lon1) * frac, lat1 + (lat2 - lat1) * frac))
            if out[-1] != b:
                out.append(b)
        return out
    
    def get_speed_km_min(self, mode: str) -> float:
        return self.speeds_km_min.get(mode, 0.1)
    
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
    
    def advance_along_route(self, route: List[Tuple[float, float]], current_index: int, 
                           offset_km: float, mode: str) -> Tuple[int, float, Tuple[float, float]]:
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
    
    @staticmethod
    def _is_lonlat(p: Tuple[float, float]) -> bool:
        x, y = p
        return (-180.0 <= x <= 180.0) and (-90.0 <= y <= 90.0)
    
    @staticmethod
    def _haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
        lon1, lat1 = a
        lon2, lat2 = b
        R = 6371.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlmb = math.radians(lon2 - lon1)
        h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
        return 2 * R * math.asin(math.sqrt(h))
    
    def _haversine_m(self, a: Tuple[float, float], b: Tuple[float, float]) -> float:
        return self._haversine_km(a, b) * 1000.0
    
    def _segment_distance_km(self, a: Tuple[float, float], b: Tuple[float, float]) -> float:
        if self._is_lonlat(a) and self._is_lonlat(b):
            return self._haversine_km(a, b)
        return math.hypot(b[0] - a[0], b[1] - a[1])
    
    def _distance(self, route: List[Tuple[float, float]]) -> float:
        if len(route) < 2:
            return 0.0
        return sum(self._segment_distance_km(route[i], route[i + 1]) for i in range(len(route) - 1))
    
    def get_graph_stats(self) -> dict:
        if not self.graph_loaded or self.G is None:
            return {"loaded": False}
        return {
            "loaded": True,
            "nodes": len(self.G.nodes),
            "edges": len(self.G.edges),
            "has_elevation": self.has_elevation,
            "mode_graphs": len(self.mode_graphs),
            "cache_size": sum(len(c) for c in self._nearest_node_cache.values()),
        }
    
    def precompute_nearest_nodes(self, points: List[Tuple[float, float]]) -> None:
        if not (self.graph_loaded and self.G is not None):
            return
        logger.info(f"Precomputing nearest nodes for {len(points)} points...")
        for coord in points:
            for net_type in self.mode_graphs.keys():
                self._get_nearest_node(coord, net_type)
        logger.info(f"Cache size: {sum(len(c) for c in self._nearest_node_cache.values())} nodes")
    
    def clear_cache(self) -> None:
        if self.cache_dir.exists():
            for f in self.cache_dir.glob("*.pkl"):
                f.unlink()
            logger.info(f"Cleared cache: {self.cache_dir}")