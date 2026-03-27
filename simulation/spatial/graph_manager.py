"""
simulation/spatial/graph_manager.py

OSM graph loading, caching, and management.

This module implements the GraphManager class which handles downloading OSM graphs 
for specified regions, caching them on disk for performance, and providing 
interfaces for querying the graph (e.g., nearest nodes). It supports loading separate 
graphs for different transport modes (walk, bike, drive) to allow for mode-specific 
routing and analysis.

Handles:
- Graph downloading from OpenStreetMap
- Disk caching for performance
- Mode-specific networks (walk/bike/drive)
- Nearest node queries with caching
- Elevation data integration
"""

from __future__ import annotations
import logging
import pickle
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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

# ============================================================
# Graph Manager Class
# ============================================================
class GraphManager:
    """
    Manages OSM graph loading, caching, and queries.
    """
    
    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Initialize graph manager.
        
        Args:
            cache_dir: Directory for caching graphs (default: ~/.rtd_sim_cache/osm_graphs)
        """
        self.cache_dir = cache_dir or Path.home() / ".rtd_sim_cache" / "osm_graphs"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.graphs: Dict[str, Any] = {}  # network_type -> graph
        self.primary_graph: Optional[Any] = None
        self._has_elevation = False
        
        # Nearest node cache (per network type)
        self._nearest_node_cache: Dict[str, Dict] = {}
        
        # Mode to network type mapping
        self.mode_network_types = {
            'walk': 'walk',
            'bike': 'bike',
            'bus': 'drive',
            'car': 'drive',
            'ev': 'drive',
        }
        
        logger.info(f"Graph cache: {self.cache_dir}")
    
    def load_graph(
        self,
        place: Optional[str] = None,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        network_type: str = 'all',
        use_cache: bool = True
    ) -> bool:
        """
        Load a single OSM graph.
        
        Args:
            place: Place name (e.g., "Edinburgh, Scotland")
            bbox: Bounding box (north, south, east, west)
            network_type: OSM network type ('all', 'walk', 'bike', 'drive')
            use_cache: Use cached graph if available
        
        Returns:
            True if loaded successfully
        """
        if not OSMNX_AVAILABLE:
            logger.error("OSMnx not available")
            return False
        
        cache_key = self._get_cache_key(place, bbox, network_type)
        cache_path = self.cache_dir / f"{cache_key}.pkl"
        
        # Try cache first
        if use_cache and cache_path.exists():
            try:
                logger.info(f"Loading from cache: {cache_path.name}")
                with open(cache_path, 'rb') as f:
                    graph = pickle.load(f)
                
                self.primary_graph = graph
                self.graphs[network_type] = graph
                
                logger.info(f"Loaded: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
                self._validate_cache_geometry(graph, cache_path, network_type)
                return True
            except Exception as e:
                logger.warning(f"Cache load failed: {e}")
        
        # Download from OSM
        try:
            logger.info(f"Downloading OSM graph (network_type={network_type})...")
            
            if place:
                graph = ox.graph_from_place(place, network_type=network_type)
            elif bbox:
                north, south, east, west = bbox
                graph = ox.graph_from_bbox(
                    bbox=(west, south, east, north),
                    network_type=network_type
                )
            else:
                logger.error("Must provide place or bbox")
                return False
            
            if graph is None:
                logger.error("Graph download failed")
                return False
            
            # Add edge lengths if missing
            if not all('length' in data for _, _, data in graph.edges(data=True)):
                logger.info("Adding edge lengths...")
                graph = ox.distance.add_edge_lengths(graph)
            
            # Cache it
            if use_cache:
                try:
                    with open(cache_path, 'wb') as f:
                        pickle.dump(graph, f)
                    logger.info(f"Saved to cache: {cache_path.name}")
                except Exception as e:
                    logger.warning(f"Cache save failed: {e}")
            
            self.primary_graph = graph
            self.graphs[network_type] = graph
            
            logger.info(f"Graph loaded: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
            return True
        
        except Exception as e:
            logger.exception(f"OSM load failed: {e}")
            return False
    
    def load_mode_specific_graphs(
        self,
        place: Optional[str] = None,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        modes: List[str] = None,
        use_cache: bool = True
    ) -> bool:
        """
        Load separate graphs for different transport modes.
        
        Args:
            place: Place name
            bbox: Bounding box (north, south, east, west)
            modes: List of modes to load (default: ['walk', 'bike', 'drive'])
            use_cache: Use cached graphs
        
        Returns:
            True if at least one graph loaded successfully
        """
        if not OSMNX_AVAILABLE:
            logger.error("OSMnx not available")
            return False
        
        modes = modes or ['walk', 'bike', 'drive']
        network_types = set(self.mode_network_types.get(m, 'all') for m in modes)
        
        logger.info(f"Loading graphs for modes: {modes}")
        logger.info(f"Network types: {network_types}")
        
        success_count = 0
        
        for net_type in network_types:
            cache_key = self._get_cache_key(place, bbox, net_type)
            cache_path = self.cache_dir / f"{cache_key}.pkl"
            
            graph = None
            
            # Try cache
            if use_cache and cache_path.exists():
                try:
                    logger.info(f"Loading from cache: {cache_path.name}")
                    with open(cache_path, 'rb') as f:
                        graph = pickle.load(f)
                    logger.info(f"Loaded: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
                except Exception as e:
                    logger.warning(f"Cache load failed: {e}")
            
            # Download if needed
            if graph is None:
                try:
                    logger.info(f"Downloading OSM graph (network_type={net_type})...")
                    if place:
                        graph = ox.graph_from_place(place, network_type=net_type)
                    elif bbox:
                        north, south, east, west = bbox
                        graph = ox.graph_from_bbox(
                            bbox=(west, south, east, north),
                            network_type=net_type
                        )
                    
                    if graph is not None:
                        if not all('length' in data for _, _, data in graph.edges(data=True)):
                            graph = ox.distance.add_edge_lengths(graph)
                        
                        logger.info(f"Graph loaded: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
                        
                        if use_cache:
                            try:
                                with open(cache_path, 'wb') as f:
                                    pickle.dump(graph, f)
                                logger.info(f"Saved to cache: {cache_path.name}")
                            except Exception as e:
                                logger.warning(f"Cache save failed: {e}")
                
                except Exception as e:
                    logger.exception(f"Failed to load {net_type}: {e}")
            
            # Store graph
            if graph is not None:
                self.graphs[net_type] = graph
                success_count += 1
                
                # Set primary graph to 'all' or first loaded
                if self.primary_graph is None or net_type == 'all':
                    self.primary_graph = graph
        
        if success_count > 0:
            logger.info(f"✅ Loaded {success_count} mode-specific graphs")
            return True
        else:
            logger.warning("⚠️ No graphs loaded")
            return False
    
    def add_elevation_data(
        self,
        method: str = 'opentopo',
        **kwargs
    ) -> bool:
        """
        Add elevation data to primary graph.
        
        Args:
            method: Elevation data source ('opentopo', 'opentopo_ned', etc.)
            **kwargs: Additional arguments for elevation provider
        
        Returns:
            True if elevation added successfully
        """
        if self.primary_graph is None:
            logger.warning("No graph loaded")
            return False
        
        if not ELEVATION_PROVIDER_AVAILABLE:
            logger.error("ElevationProvider not available")
            return False
        
        try:
            from simulation.elevation_provider import ElevationProvider
            
            provider = ElevationProvider(cache_dir=self.cache_dir.parent / "elevation")
            api = kwargs.get('api', method)
            
            logger.info(f"Adding elevation using {api}...")
            self.primary_graph = provider.add_elevation_to_graph(self.primary_graph, api=api)
            
            # Check if elevation was added
            sample_nodes = list(self.primary_graph.nodes(data=True))[:10]
            has_elev = any('elevation' in data for _, data in sample_nodes)
            
            if has_elev:
                self._has_elevation = True
                elevations = [data.get('elevation') for _, data in sample_nodes if 'elevation' in data]
                logger.info(f"✅ Elevation data added (sample: {elevations[:3]})")
                return True
            else:
                logger.warning("⚠️ Elevation not found in nodes")
                return False
        
        except Exception as e:
            logger.exception(f"Failed to add elevation: {e}")
            return False
    
    def _validate_cache_geometry(
        self,
        graph: Any,
        cache_path: Path,
        network_type: str,
    ) -> None:
        """
        Warn when a cached graph is missing edge geometry.

        OSMnx stores curved road geometry as a Shapely LineString on each
        simplified edge.  If it is absent, routes are rendered as straight
        lines between OSM intersection nodes, which visually cuts through
        parks, rivers, and buildings even when the underlying road is correct.

        A geometry ratio < 50 % is a strong signal that the cache file was
        created by an older code version or a different OSMnx release.
        Deleting the file forces a clean re-download with full geometry.

        Args:
            graph:        The just-loaded NetworkX graph.
            cache_path:   Path to the .pkl file, used in the warning message.
            network_type: Network type string, used for context.
        """
        total = graph.number_of_edges()
        if total == 0:
            return

        with_geom = sum(
            1 for _, _, d in graph.edges(data=True) if "geometry" in d
        )
        ratio = with_geom / total

        if ratio < 0.5:
            logger.warning(
                "⚠️  Cache geometry check FAILED for '%s' graph: "
                "only %.0f%% of edges have Shapely geometry "
                "(%d / %d edges).  Routes will appear as straight lines "
                "through parks and other obstacles.  "
                "Delete the stale cache file to force a clean re-download:\n"
                "    rm %s",
                network_type, ratio * 100, with_geom, total, cache_path,
            )
        else:
            logger.debug(
                "Cache geometry OK for '%s': %.0f%% of edges have geometry.",
                network_type, ratio * 100,
            )

    def get_graph(self, network_type: str = 'all') -> Optional[Any]:
        """
        Get graph for specific network type.

        IMPORTANT: only 'all' falls back to primary_graph.  Every other
        network type (walk, bike, drive, rail) returns None if not loaded
        so callers receive a clear signal rather than silently getting the
        wrong graph.  Previously 'rail' fell through to primary_graph (the
        drive graph), causing rail agents to route on roads.

        'rail' triggers just-in-time spine loading the first time it is
        requested and the graph has not already been loaded by load_rail_graph().

        Args:
            network_type: Network type ('all', 'walk', 'bike', 'drive', 'rail')

        Returns:
            Graph or None if not loaded / not available
        """
        if network_type in self.graphs:
            return self.graphs[network_type]

        # JIT: load the rail spine the first time rail is requested
        if network_type == 'rail':
            return self._load_rail_jit()

        # Only 'all' falls back to primary_graph — all other specific types
        # return None so the caller can handle missing graphs explicitly
        if network_type == 'all':
            return self.primary_graph

        return None

    def _load_rail_jit(self) -> Optional[Any]:
        """
        Load the rail spine graph on first demand (just-in-time).

        Called automatically by get_graph('rail') when no rail graph has
        been registered yet.  Prevents repeated load attempts once it is
        clear the spine is unavailable.

        Returns:
            Rail spine NetworkX graph or None.
        """
        if getattr(self, '_rail_load_attempted', False):
            return None
        self._rail_load_attempted = True
        try:
            from simulation.spatial.rail_spine import get_spine_graph
            G = get_spine_graph()
            if G is not None:
                self.graphs['rail'] = G
                logger.info(
                    "✅ Rail spine loaded JIT: %d stations, %d edges",
                    G.number_of_nodes(), G.number_of_edges(),
                )
            else:
                logger.warning("Rail spine JIT load returned None")
            return G
        except Exception as exc:
            logger.warning("Rail spine JIT load failed: %s", exc)
            return None
    
    def get_nearest_node(
        self,
        coord: Tuple[float, float],
        network_type: str = 'all'
    ) -> Optional[int]:
        """
        Find nearest node to coordinate with caching.
        
        Args:
            coord: (lon, lat) coordinate
            network_type: Which graph to search
        
        Returns:
            Node ID or None if not found
        """
        cache_key = (round(coord[0], 4), round(coord[1], 4))
        
        # Initialize cache for this network type
        if network_type not in self._nearest_node_cache:
            self._nearest_node_cache[network_type] = {}
        
        cache = self._nearest_node_cache[network_type]
        
        # Check cache
        if cache_key in cache:
            return cache[cache_key]
        
        # Get graph
        graph = self.get_graph(network_type)
        if graph is None:
            return None
        
        # Find nearest node
        try:
            node = ox.distance.nearest_nodes(graph, coord[0], coord[1])
            cache[cache_key] = node
            return node
        except Exception as e:
            logger.warning(f"Nearest node failed: {e}")
            return None
    
    def precompute_nearest_nodes(
        self,
        points: List[Tuple[float, float]]
    ) -> None:
        """
        Precompute nearest nodes for list of points.
        
        Args:
            points: List of (lon, lat) coordinates
        """
        logger.info(f"Precomputing nearest nodes for {len(points)} points...")
        for coord in points:
            for net_type in self.graphs.keys():
                self.get_nearest_node(coord, net_type)
        
        cache_size = sum(len(c) for c in self._nearest_node_cache.values())
        logger.info(f"Cache size: {cache_size} nodes")
    
    def has_elevation(self) -> bool:
        """Check if elevation data is available."""
        return self._has_elevation

    def project_to_utm(self, network_type: str = 'drive') -> bool:
        """
        Project graph to local UTM (EPSG:27700 British National Grid for UK).

        OSMnx stores node coordinates in WGS84 decimal degrees (x=lon, y=lat).
        All spatial calculations on the graph (length, grade, area) use the
        pre-computed `length` attribute in metres added by OSMnx at download
        time — so edge distances are already correct.

        However `ox.add_edge_grades()` requires that `elevation` node attributes
        exist AND that we are working in a projected CRS so that the grade
        calculation:

            grade = Δelevation / length

        uses matching units (both in metres).  Calling this method:
          1. Re-projects the graph to BNG (EPSG:27700) so coordinates are
             in metres (Easting, Northing) and `length` values are verified.
          2. Adds the `grade` attribute to every edge via ox.add_edge_grades().

        The projected graph is stored back under the same network_type key
        so subsequent routing calls use gradient-aware edge weights
        automatically.

        Args:
            network_type: Which graph to project (default 'drive').

        Returns:
            True if projection succeeded, False otherwise.
        """
        if not OSMNX_AVAILABLE:
            logger.warning("project_to_utm: OSMnx not available")
            return False

        graph = self.get_graph(network_type)
        if graph is None:
            logger.warning("project_to_utm: no graph for network_type=%s", network_type)
            return False

        if not self._has_elevation:
            logger.warning(
                "project_to_utm: elevation data not loaded — "
                "call add_elevation_data() first for accurate grades"
            )
            # Still project so length values are in metres for future use
            # but grades will be zero without elevation

        try:
            import osmnx as ox
            # Project to British National Grid (EPSG:27700) — ~1m accuracy across UK
            G_proj = ox.project_graph(graph, to_crs='EPSG:27700')

            # Add true grade (Δelevation_m / length_m) to every directed edge.
            # Requires elevation node attribute — silently adds 0 if absent.
            if self._has_elevation:
                G_proj = ox.add_edge_grades(G_proj, add_absolute=True)
                logger.info(
                    "✅ Graph projected (EPSG:27700) + edge grades added: "
                    "%d edges with grade attribute",
                    sum(1 for _, _, d in G_proj.edges(data=True) if 'grade' in d),
                )
            else:
                logger.info("✅ Graph projected to EPSG:27700 (no elevation → grades=0)")

            # Store projected graph — downstream routing uses it transparently
            self.graphs[network_type] = G_proj
            if network_type == 'drive':
                self.primary_graph = G_proj

            # Clear nearest-node cache — projected coordinates differ from WGS84
            self._nearest_node_cache.pop(network_type, None)
            return True

        except Exception as exc:
            logger.error("project_to_utm failed: %s", exc)
            return False
    
    def is_loaded(self) -> bool:
        """Check if any graph is loaded."""
        return self.primary_graph is not None
    
    def get_stats(self) -> dict:
        """Get graph statistics including spatial bounds."""
        if not self.is_loaded():
            return {"loaded": False}

        stats = {
            "loaded": True,
            "nodes": len(self.primary_graph.nodes),
            "edges": len(self.primary_graph.edges),
            "has_elevation": self._has_elevation,
            "num_graphs": len(self.graphs),
            "cache_size": sum(len(c) for c in self._nearest_node_cache.values()),
        }

        # Spatial bounds — extracted from node coordinates so environment_setup.py
        # can derive bbox for charger placement without hardcoding any city.
        try:
            lons = [d['x'] for _, d in self.primary_graph.nodes(data=True)]
            lats = [d['y'] for _, d in self.primary_graph.nodes(data=True)]
            stats['west']  = min(lons)
            stats['east']  = max(lons)
            stats['south'] = min(lats)
            stats['north'] = max(lats)
        except Exception:
            pass  # bounds absent — callers that need them will fall back gracefully

        return stats
    
    def clear_cache(self) -> None:
        """Clear disk cache."""
        if self.cache_dir.exists():
            for f in self.cache_dir.glob("*.pkl"):
                f.unlink()
            logger.info(f"Cleared cache: {self.cache_dir}")
    
    def _get_cache_key(
        self,
        place: Optional[str],
        bbox: Optional[Tuple],
        network_type: str
    ) -> str:
        """Generate cache key for graph."""
        if place:
            key_str = f"place_{place}_{network_type}"
        elif bbox:
            key_str = f"bbox_{bbox[0]}_{bbox[1]}_{bbox[2]}_{bbox[3]}_{network_type}"
        else:
            key_str = "default"
        
        return hashlib.md5(key_str.encode()).hexdigest()[:16]
