"""
simulation/spatial/graph_manager.py

OSM graph loading, caching, and management.

GraphManager handles downloading OSM graphs for specified regions, caching
them on disk for performance, and providing interfaces for querying the
graph (nearest nodes, elevation, etc.).  It supports separate graphs for
different transport modes (walk, bike, drive) and a dedicated rail graph
that can be loaded either on-demand from OpenRailMap or from the
hardcoded rail spine fallback.

Rail graph loading order
------------------------
The rail graph can arrive via two paths:

  1. Just-In-Time (JIT) — the first call to get_graph('rail') triggers
     _load_rail_jit(), which loads the lightweight 41-station spine so
     that rail routing never hard-crashes on first access.

  2. Explicit — spatial_environment.load_rail_graph() calls
     get_or_fallback_rail_graph() and then registers the result via
     register_rail_graph().  This OVERRIDES the JIT-loaded spine and
     resets _rail_load_attempted so a future re-load is possible.

Always call env.load_rail_graph() (or register_rail_graph() directly)
after environment setup.  Never rely on the JIT spine as the final graph
— it has no Shapely edge geometry, so all rail routes will be straight
lines between station centroids.

Elevation
---------
add_elevation_data() annotates graph nodes with elevation in metres from
an external provider.  project_to_utm() then re-projects to EPSG:27700
(British National Grid), adds true grade attributes via
ox.add_edge_grades(), and projects back to WGS84 so that all downstream
code (Router, GTFS, Visualizer) continues to receive lon/lat coordinates.
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


class GraphManager:
    """
    Manages OSM graph loading, caching, and nearest-node queries.

    Graphs are keyed by network type string: 'drive', 'walk', 'bike',
    'rail', 'transit'.  Only 'all' falls back to primary_graph; all other
    specific types return None when not loaded so callers can handle
    missing graphs explicitly rather than receiving the wrong graph.
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Args:
            cache_dir: Directory for caching downloaded graphs.
                       Defaults to ~/.rtd_sim_cache/osm_graphs.
        """
        self.cache_dir = cache_dir or Path.home() / ".rtd_sim_cache" / "osm_graphs"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.graphs: Dict[str, Any] = {}       # network_type → NetworkX graph
        self.primary_graph: Optional[Any] = None
        self._has_elevation: bool = False

        # Nearest-node cache keyed by (rounded_lon, rounded_lat) per network type.
        self._nearest_node_cache: Dict[str, Dict] = {}

        # Flag that prevents the JIT spine loader from retrying after failure.
        # Reset by register_rail_graph() when a real graph is loaded.
        self._rail_load_attempted: bool = False

        # Mode → network type mapping (for callers that need the type string).
        self.mode_network_types: Dict[str, str] = {
            'walk': 'walk',
            'bike': 'bike',
            'bus':  'drive',
            'car':  'drive',
            'ev':   'drive',
        }

        logger.info("Graph cache: %s", self.cache_dir)

    # =========================================================================
    # GRAPH LOADING
    # =========================================================================

    def load_graph(
        self,
        place: Optional[str] = None,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        network_type: str = 'all',
        use_cache: bool = True,
    ) -> bool:
        """
        Load a single OSM graph by place name or bounding box.

        Args:
            place:        Place name (e.g. "Edinburgh, Scotland").
            bbox:         Bounding box as (north, south, east, west).
                          Internally reordered to (west, south, east, north)
                          for the OSMnx 2.x API.
            network_type: OSM network type ('all', 'walk', 'bike', 'drive').
            use_cache:    Load from disk cache when available.

        Returns:
            True if the graph loaded successfully, False otherwise.
        """
        if not OSMNX_AVAILABLE:
            logger.error("OSMnx not available")
            return False

        cache_key  = self._get_cache_key(place, bbox, network_type)
        cache_path = self.cache_dir / f"{cache_key}.pkl"

        if use_cache and cache_path.exists():
            try:
                logger.info("Loading from cache: %s", cache_path.name)
                with open(cache_path, 'rb') as f:
                    graph = pickle.load(f)
                self.primary_graph          = graph
                self.graphs[network_type]   = graph
                logger.info("Loaded: %d nodes, %d edges", len(graph.nodes), len(graph.edges))
                self._validate_cache_geometry(graph, cache_path, network_type)
                return True
            except Exception as e:
                logger.warning("Cache load failed: %s", e)

        try:
            logger.info("Downloading OSM graph (network_type=%s)…", network_type)
            if place:
                graph = ox.graph_from_place(place, network_type=network_type)
            elif bbox:
                north, south, east, west = bbox
                graph = ox.graph_from_bbox(
                    bbox=(west, south, east, north),
                    network_type=network_type,
                )
            else:
                logger.error("Must provide place or bbox")
                return False

            if graph is None:
                logger.error("Graph download returned None")
                return False

            if not all('length' in data for _, _, data in graph.edges(data=True)):
                logger.info("Adding missing edge lengths…")
                if OSMNX_AVAILABLE:
                    graph = ox.distance.add_edge_lengths(graph)

            if use_cache:
                try:
                    with open(cache_path, 'wb') as f:
                        pickle.dump(graph, f)
                    logger.info("Saved to cache: %s", cache_path.name)
                except Exception as e:
                    logger.warning("Cache save failed: %s", e)

            self.primary_graph        = graph
            self.graphs[network_type] = graph
            logger.info("Graph loaded: %d nodes, %d edges", len(graph.nodes), len(graph.edges))
            return True

        except Exception as e:
            logger.exception("OSM load failed: %s", e)
            return False

    def load_mode_specific_graphs(
        self,
        place: Optional[str] = None,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        modes: List[str] = None,
        use_cache: bool = True,
    ) -> bool:
        """
        Load separate graphs for different transport modes.

        Args:
            place:     Place name.
            bbox:      Bounding box as (north, south, east, west).
            modes:     List of mode strings (default: ['walk', 'bike', 'drive']).
            use_cache: Use disk cache when available.

        Returns:
            True if at least one graph loaded successfully.
        """
        if not OSMNX_AVAILABLE:
            logger.error("OSMnx not available")
            return False

        modes         = modes or ['walk', 'bike', 'drive']
        network_types = set(self.mode_network_types.get(m, 'all') for m in modes)
        logger.info("Loading graphs for network types: %s", network_types)

        success_count = 0

        for net_type in network_types:
            cache_key  = self._get_cache_key(place, bbox, net_type)
            cache_path = self.cache_dir / f"{cache_key}.pkl"
            graph      = None

            if use_cache and cache_path.exists():
                try:
                    logger.info("Loading from cache: %s", cache_path.name)
                    with open(cache_path, 'rb') as f:
                        graph = pickle.load(f)
                    logger.info("Loaded: %d nodes, %d edges", len(graph.nodes), len(graph.edges))
                except Exception as e:
                    logger.warning("Cache load failed: %s", e)

            if graph is None:
                try:
                    logger.info("Downloading OSM graph (network_type=%s)…", net_type)
                    if place:
                        graph = ox.graph_from_place(place, network_type=net_type)
                    elif bbox:
                        north, south, east, west = bbox
                        graph = ox.graph_from_bbox(
                            bbox=(west, south, east, north),
                            network_type=net_type,
                        )

                    if graph is not None:
                        if not all('length' in data for _, _, data in graph.edges(data=True)):
                            if OSMNX_AVAILABLE:
                                graph = ox.distance.add_edge_lengths(graph)
                        logger.info("Graph loaded: %d nodes, %d edges",
                                    len(graph.nodes), len(graph.edges))
                        if use_cache:
                            try:
                                with open(cache_path, 'wb') as f:
                                    pickle.dump(graph, f)
                                logger.info("Saved to cache: %s", cache_path.name)
                            except Exception as e:
                                logger.warning("Cache save failed: %s", e)

                except Exception as e:
                    logger.exception("Failed to load network_type=%s: %s", net_type, e)

            if graph is not None:
                self.graphs[net_type] = graph
                success_count += 1
                if self.primary_graph is None or net_type == 'all':
                    self.primary_graph = graph

        if success_count > 0:
            logger.info("✅ Loaded %d mode-specific graphs", success_count)
            return True

        logger.warning("⚠️ No graphs loaded")
        return False

    # =========================================================================
    # ELEVATION
    # =========================================================================

    def add_elevation_data(self, method: str = 'opentopo', **kwargs) -> bool:
        """
        Add elevation data to the primary graph.

        Args:
            method: Elevation data source ('opentopo', etc.)
            **kwargs: Additional arguments forwarded to ElevationProvider.

        Returns:
            True if elevation attributes were successfully added.
        """
        if self.primary_graph is None:
            logger.warning("No graph loaded")
            return False

        if not ELEVATION_PROVIDER_AVAILABLE:
            logger.error("ElevationProvider not available")
            return False

        try:
            provider = ElevationProvider(
                cache_dir=self.cache_dir.parent / "elevation"
            )
            api = kwargs.get('api', method)
            logger.info("Adding elevation using %s…", api)
            self.primary_graph = provider.add_elevation_to_graph(
                self.primary_graph, api=api
            )

            sample = list(self.primary_graph.nodes(data=True))[:10]
            if any('elevation' in d for _, d in sample):
                self._has_elevation = True
                elevations = [d['elevation'] for _, d in sample if 'elevation' in d]
                logger.info("✅ Elevation added (sample: %s)", elevations[:3])
                return True

            logger.warning("⚠️ Elevation attribute not found after provider call")
            return False

        except Exception as e:
            logger.exception("Failed to add elevation: %s", e)
            return False

    def project_to_utm(self, network_type: str = 'drive') -> bool:
        """
        Project a graph to EPSG:27700 (British National Grid), add edge grades,
        then project back to WGS84 for downstream compatibility.

        OSMnx stores node coordinates in WGS84.  Edge lengths are already in
        metres (added at download time by OSMnx), so routing distances are
        correct without projection.  However ox.add_edge_grades() requires
        elevation in metres AND coordinates in a projected CRS so that
        grade = Δelevation_m / length_m is dimensionally consistent.

        The graph is stored back in WGS84 after grade computation so that
        the Router, GTFS layer, and Visualizer all continue to receive
        standard lon/lat coordinates.

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
                "project_to_utm: elevation not loaded — grades will be zero"
            )

        try:
            G_proj = ox.project_graph(graph, to_crs='EPSG:27700')

            if self._has_elevation:
                G_proj = ox.add_edge_grades(G_proj, add_absolute=True)
                grade_count = sum(
                    1 for _, _, d in G_proj.edges(data=True) if 'grade' in d
                )
                logger.info(
                    "✅ Projected to EPSG:27700 + %d edge grades added", grade_count
                )
            else:
                logger.info("✅ Projected to EPSG:27700 (no elevation → grades=0)")

            # Re-project to WGS84 so downstream code receives lon/lat.
            G_wgs84 = ox.project_graph(G_proj, to_crs='EPSG:4326')

            self.graphs[network_type] = G_wgs84
            if network_type == 'drive':
                self.primary_graph = G_wgs84

            # Projected coordinates differ from WGS84 — clear stale cache.
            self._nearest_node_cache.pop(network_type, None)
            return True

        except Exception as exc:
            logger.error("project_to_utm failed: %s", exc)
            return False

    # =========================================================================
    # RAIL GRAPH
    # =========================================================================

    def get_graph(self, network_type: str = 'all') -> Optional[Any]:
        """
        Return the graph for a specific network type.

        'rail' triggers just-in-time spine loading on first access so that
        rail routing never hard-crashes.  Call register_rail_graph() after
        env.load_rail_graph() to replace the spine with the real OpenRailMap
        graph — this is critical for correct geometry.

        Only 'all' falls back to primary_graph; every other specific type
        returns None when not loaded so callers get a clear failure signal
        rather than silently receiving the wrong graph.

        Args:
            network_type: 'all', 'walk', 'bike', 'drive', 'rail', 'transit'.

        Returns:
            NetworkX graph or None.
        """
        if network_type in self.graphs:
            return self.graphs[network_type]

        if network_type == 'rail':
            return self._load_rail_jit()

        if network_type == 'all':
            return self.primary_graph

        return None

    def register_rail_graph(self, G_rail: Any) -> None:
        """
        Register an externally loaded rail graph, overriding any JIT spine.

        Call this from spatial_environment.load_rail_graph() after calling
        get_or_fallback_rail_graph().  Resetting _rail_load_attempted allows
        a future re-load (e.g. after a configuration change) without
        restarting the process.

        Args:
            G_rail: NetworkX MultiDiGraph from fetch_rail_graph() or
                    the rail spine — must not be None.
        """
        if G_rail is None:
            logger.warning("register_rail_graph: received None — ignoring")
            return
        self.graphs['rail']         = G_rail
        self._rail_load_attempted   = False   # allow future re-loads
        logger.info(
            "✅ Rail graph registered: %d nodes, %d edges",
            G_rail.number_of_nodes(), G_rail.number_of_edges(),
        )

    def _load_rail_jit(self) -> Optional[Any]:
        """
        Load the rail spine on first demand (just-in-time).

        This is a safety net only — it ensures rail routing never crashes
        on first access.  The spine has no Shapely edge geometry, so every
        rail route will be a straight line unless register_rail_graph() is
        subsequently called with the full OpenRailMap graph.

        Sets _rail_load_attempted = True to prevent repeated load attempts
        on failure (reset by register_rail_graph() on success).
        """
        if self._rail_load_attempted:
            return None
        self._rail_load_attempted = True
        try:
            from simulation.spatial.rail_spine import get_spine_graph
            G = get_spine_graph()
            if G is not None:
                self.graphs['rail'] = G
                logger.info(
                    "✅ Rail spine loaded JIT: %d stations, %d edges "
                    "(call register_rail_graph() with OpenRailMap data to override)",
                    G.number_of_nodes(), G.number_of_edges(),
                )
            else:
                logger.warning("Rail spine JIT load returned None")
            return G
        except Exception as exc:
            logger.warning("Rail spine JIT load failed: %s", exc)
            return None

    # =========================================================================
    # NEAREST-NODE QUERIES
    # =========================================================================

    def get_nearest_node(
        self,
        coord: Tuple[float, float],
        network_type: str = 'all',
    ) -> Optional[int]:
        """
        Find the nearest graph node to a (lon, lat) coordinate.

        Results are cached at 4 decimal-place precision (~11 m resolution)
        to avoid redundant OSMnx distance queries across simulation steps.

        Args:
            coord:        (longitude, latitude).
            network_type: Which graph to search.

        Returns:
            Node ID (int) or None if the graph is not loaded.
        """
        cache_key = (round(coord[0], 4), round(coord[1], 4))

        if network_type not in self._nearest_node_cache:
            self._nearest_node_cache[network_type] = {}

        cache = self._nearest_node_cache[network_type]
        if cache_key in cache:
            return cache[cache_key]

        graph = self.get_graph(network_type)
        if graph is None:
            return None

        try:
            node = ox.distance.nearest_nodes(graph, coord[0], coord[1])
            cache[cache_key] = node
            return node
        except Exception as e:
            logger.warning("Nearest node query failed: %s", e)
            return None

    def precompute_nearest_nodes(
        self,
        points: List[Tuple[float, float]],
    ) -> None:
        """
        Pre-warm the nearest-node cache for a list of coordinates.

        Useful before a simulation run to avoid per-step latency for agents
        whose origin/destination coordinates are known in advance.

        Args:
            points: List of (lon, lat) coordinates.
        """
        logger.info("Pre-computing nearest nodes for %d points…", len(points))
        for coord in points:
            for net_type in self.graphs:
                self.get_nearest_node(coord, net_type)
        cache_size = sum(len(c) for c in self._nearest_node_cache.values())
        logger.info("Nearest-node cache size: %d entries", cache_size)

    # =========================================================================
    # GEOMETRY VALIDATION
    # =========================================================================

    def _validate_cache_geometry(
        self,
        graph: Any,
        cache_path: Path,
        network_type: str,
    ) -> None:
        """
        Warn when a cached graph has fewer than 50 % of edges with Shapely
        geometry.

        OSMnx stores curved road geometry as a Shapely LineString on each
        simplified edge.  If it is absent, routes render as straight lines
        between OSM intersection nodes even when the underlying road curves
        around buildings, parks, and rivers.

        A ratio below 50 % usually means the cache was created by an older
        code version.  Deleting the .pkl file forces a clean re-download.

        Args:
            graph:        The just-loaded NetworkX graph.
            cache_path:   Path to the .pkl file.
            network_type: Network type string, used for context in the message.
        """
        total = graph.number_of_edges()
        if total == 0:
            return

        with_geom = sum(
            1 for _, _, d in graph.edges(data=True) if 'geometry' in d
        )
        ratio = with_geom / total

        if ratio < 0.5:
            logger.warning(
                "⚠️  Cache geometry check FAILED for '%s' graph: "
                "only %.0f%% of edges have Shapely geometry (%d / %d). "
                "Routes will appear as straight lines.  "
                "Delete the stale cache to force a re-download:\n    rm %s",
                network_type, ratio * 100, with_geom, total, cache_path,
            )
        else:
            logger.debug(
                "Cache geometry OK for '%s': %.0f%% of edges have geometry.",
                network_type, ratio * 100,
            )

    # =========================================================================
    # UTILITY
    # =========================================================================

    def has_elevation(self) -> bool:
        """Return True if elevation data has been added to the primary graph."""
        return self._has_elevation

    def is_loaded(self) -> bool:
        """Return True if at least one graph has been loaded."""
        return self.primary_graph is not None

    def get_stats(self) -> dict:
        """
        Return a summary dict with node/edge counts and spatial bounds.

        Spatial bounds (west, east, south, north) are derived from primary
        graph node coordinates and can be used by infrastructure placement
        logic without hardcoding city extents.
        """
        if not self.is_loaded():
            return {"loaded": False}

        stats = {
            "loaded":      True,
            "nodes":       len(self.primary_graph.nodes),
            "edges":       len(self.primary_graph.edges),
            "has_elevation": self._has_elevation,
            "num_graphs":  len(self.graphs),
            "cache_size":  sum(len(c) for c in self._nearest_node_cache.values()),
        }

        try:
            lons = [d['x'] for _, d in self.primary_graph.nodes(data=True)]
            lats = [d['y'] for _, d in self.primary_graph.nodes(data=True)]
            stats['west']  = min(lons)
            stats['east']  = max(lons)
            stats['south'] = min(lats)
            stats['north'] = max(lats)
        except Exception:
            pass

        return stats

    def clear_cache(self) -> None:
        """Delete all .pkl files from the disk cache directory."""
        if self.cache_dir.exists():
            for f in self.cache_dir.glob("*.pkl"):
                f.unlink()
            logger.info("Cleared cache: %s", self.cache_dir)

    def _get_cache_key(
        self,
        place: Optional[str],
        bbox: Optional[Tuple],
        network_type: str,
    ) -> str:
        """Generate a stable 16-character cache filename from the query parameters."""
        if place:
            key_str = f"place_{place}_{network_type}"
        elif bbox:
            key_str = f"bbox_{bbox[0]}_{bbox[1]}_{bbox[2]}_{bbox[3]}_{network_type}"
        else:
            key_str = "default"
        return hashlib.md5(key_str.encode()).hexdigest()[:16]