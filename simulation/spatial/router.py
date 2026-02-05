"""
simulation/spatial/router.py

Route computation and alternatives generation.

Handles:
- Basic routing (shortest path)
- Route alternatives (fastest, safest, greenest, scenic)
- Weight functions for different routing objectives

✅ FIXED: Complete mode_network_types mapping for all 21 transport modes
"""

from __future__ import annotations
import logging
from typing import List, Tuple, Optional, Any, TYPE_CHECKING

from simulation.spatial.coordinate_utils import is_valid_lonlat

if TYPE_CHECKING:
    from simulation.spatial.graph_manager import GraphManager

logger = logging.getLogger(__name__)

try:
    import networkx as nx
    NETWORKX_AVAILABLE = True
except ImportError:
    NETWORKX_AVAILABLE = False
    logger.warning("NetworkX not available")

try:
    from simulation.route_alternative import RouteAlternative
    ROUTE_ALTERNATIVE_AVAILABLE = True
except ImportError:
    ROUTE_ALTERNATIVE_AVAILABLE = False


class Router:
    """
    Computes routes and route alternatives using OSM graphs.
    """
    
    def __init__(self, graph_manager: 'GraphManager', congestion_manager=None):
        """
        Initialize router.
        
        Args:
            graph_manager: GraphManager instance with loaded graphs
            congestion_manager: Optional CongestionManager for dynamic routing
        """
        self.graph_manager = graph_manager
        self.congestion_manager = congestion_manager
        
        # ✅ FIXED: Complete mode to network type mapping for ALL modes
        self.mode_network_types = {
            # Active mobility
            'walk': 'walk',
            'bike': 'bike',
            'cargo_bike': 'bike',
            'e_scooter': 'bike',
            
            # Passenger vehicles
            'bus': 'drive',
            'car': 'drive',
            'ev': 'drive',
            
            # Light commercial (Phase 4.5F)
            'van_electric': 'drive',
            'van_diesel': 'drive',
            
            # Medium freight (Phase 4.5F)
            'truck_electric': 'drive',
            'truck_diesel': 'drive',
            
            # Heavy freight (Phase 4.5F)
            'hgv_electric': 'drive',
            'hgv_diesel': 'drive',
            'hgv_hydrogen': 'drive',
            
            # Public transport (Phase 4.5G)
            'tram': 'drive',
            'local_train': 'drive',
            'intercity_train': 'drive',
            
            # Maritime (Phase 4.5G)
            'ferry_diesel': 'drive',
            'ferry_electric': 'drive',
            
            # Aviation (Phase 4.5G)
            'flight_domestic': 'drive',
            'flight_electric': 'drive',
        }
        
        # ✅ FIXED: Complete speed mapping for ALL modes (in km per minute)
        self.speeds_km_min = {
            # Active mobility
            'walk': 0.083,       # 5 km/h
            'bike': 0.25,        # 15 km/h
            'cargo_bike': 0.20,  # 12 km/h (heavier)
            'e_scooter': 0.33,   # 20 km/h
            
            # Passenger vehicles
            'bus': 0.33,    # 20 km/h city average
            'car': 0.5,     # 30 km/h city average
            'ev': 0.5,
            
            # Light commercial (Phase 4.5F)
            'van_electric': 0.45,  # 27 km/h
            'van_diesel': 0.45,
            
            # Medium freight (Phase 4.5F)
            'truck_electric': 0.40,  # 24 km/h
            'truck_diesel': 0.40,
            
            # Heavy freight (Phase 4.5F)
            'hgv_electric': 0.35,  # 21 km/h
            'hgv_diesel': 0.42,    # 25 km/h
            'hgv_hydrogen': 0.42,
            
            # Public transport (Phase 4.5G)
            'tram': 0.42,           # 25 km/h
            'local_train': 1.0,     # 60 km/h
            'intercity_train': 2.0, # 120 km/h
            
            # Maritime (Phase 4.5G)
            'ferry_diesel': 0.58,   # 35 km/h
            'ferry_electric': 0.50, # 30 km/h
            
            # Aviation (Phase 4.5G)
            'flight_domestic': 7.5,    # 450 km/h
            'flight_electric': 5.83,   # 350 km/h
        }
    
    def compute_route(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str
    ) -> List[Tuple[float, float]]:
        """
        Compute shortest path route with detailed geometry.
        """
        if not (is_valid_lonlat(origin) and is_valid_lonlat(dest)):
            logger.error(f"❌ {agent_id}: Invalid coords {origin} → {dest}")
            return []
        
        network_type = self.mode_network_types.get(mode, 'drive')
        graph = self.graph_manager.get_graph(network_type)
        
        if graph is None:
            logger.error(f"❌ {agent_id}: No graph for {mode}")
            return []
        
        try:
            orig_node = self.graph_manager.get_nearest_node(origin, network_type)
            dest_node = self.graph_manager.get_nearest_node(dest, network_type)
            
            if orig_node is None or dest_node is None:
                logger.error(f"❌ {agent_id}: Could not find nodes")
                return []
            
            # Get node route
            route_nodes = nx.shortest_path(graph, orig_node, dest_node, weight='length')
            
            # ✅ NEW: Extract detailed geometry
            detailed_coords = []
            
            for i in range(len(route_nodes) - 1):
                u = route_nodes[i]
                v = route_nodes[i + 1]
                
                # Get edge data
                edge_data = graph.get_edge_data(u, v)
                
                if edge_data and isinstance(edge_data, dict) and 0 in edge_data:
                    edge_data = edge_data[0]
                
                # Add node coordinate if first iteration
                if i == 0:
                    detailed_coords.append((float(graph.nodes[u]['x']), float(graph.nodes[u]['y'])))
                
                # Extract edge geometry
                if edge_data and 'geometry' in edge_data:
                    geom = edge_data['geometry']
                    if hasattr(geom, 'coords'):
                        edge_coords = [(float(x), float(y)) for (x, y) in geom.coords]
                        # Add geometry points (skip first as it's the same as last point added)
                        detailed_coords.extend(edge_coords[1:])
                    else:
                        # No geometry: add destination node
                        detailed_coords.append((float(graph.nodes[v]['x']), float(graph.nodes[v]['y'])))
                else:
                    # No geometry: add destination node
                    detailed_coords.append((float(graph.nodes[v]['x']), float(graph.nodes[v]['y'])))
            
            logger.info(f"✅ {agent_id}: {mode} route with {len(detailed_coords)} geometry points (from {len(route_nodes)} nodes)")
            return detailed_coords
        
        except nx.NetworkXNoPath:
            logger.error(f"❌ {agent_id}: No path exists")
            return []
        except Exception as e:
            logger.error(f"❌ {agent_id}: Routing failed: {e}")
            return []
    
    def compute_alternatives(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str,
        variants: List[str] = None
    ) -> List['RouteAlternative']:
        """
        Compute multiple route alternatives.
        
        Args:
            agent_id: Agent identifier
            origin: Starting coordinate (lon, lat)
            dest: Destination coordinate (lon, lat)
            mode: Transport mode
            variants: Route types to compute
                     Options: 'shortest', 'fastest', 'safest', 'greenest', 'scenic'
                     Default: ['shortest', 'fastest']
        
        Returns:
            List of RouteAlternative objects
        """
        if not ROUTE_ALTERNATIVE_AVAILABLE:
            logger.warning("RouteAlternative not available, using basic routing")
            route = self.compute_route(agent_id, origin, dest, mode)
            return [{'route': route, 'mode': mode, 'variant': 'shortest'}]
        
        variants = variants or ['shortest', 'fastest']
        alternatives = []
        
        for variant in variants:
            route = self._compute_route_variant(origin, dest, mode, variant)
            if route and len(route) >= 2:
                alt = RouteAlternative(route, mode, variant)
                alternatives.append(alt)
                logger.debug(f"Computed {variant} route: {len(route)} waypoints")
        
        if not alternatives:
            logger.warning(f"No alternatives generated for {agent_id}, using basic route")
            basic_route = self.compute_route(agent_id, origin, dest, mode)
            if basic_route and len(basic_route) >= 2:
                alt = RouteAlternative(basic_route, mode, 'shortest')
                alternatives.append(alt)
        
        return alternatives
    
    def _compute_route_variant(
        self,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str,
        variant: str
    ) -> Optional[List[Tuple[float, float]]]:
        """Compute specific route variant."""
        if not (is_valid_lonlat(origin) and is_valid_lonlat(dest)):
            return []  # ← Changed from None
        
        network_type = self.mode_network_types.get(mode, 'drive')
        graph = self.graph_manager.get_graph(network_type)
        
        if graph is None:
            return []  # ← Changed from None
        
        try:
            orig_node = self.graph_manager.get_nearest_node(origin, network_type)
            dest_node = self.graph_manager.get_nearest_node(dest, network_type)
            
            if orig_node is None or dest_node is None:
                return []  # ← Changed from None
            
            weight_attr = self._get_weight_attribute(graph, mode, variant)
            
            if weight_attr is None:
                return []  # ← Changed from None
            
            route_nodes = nx.shortest_path(graph, orig_node, dest_node, weight=weight_attr)
            coords = [
                (float(graph.nodes[n]['x']), float(graph.nodes[n]['y'])) 
                for n in route_nodes
            ]
            
            return coords
        
        except nx.NetworkXNoPath:
            logger.debug(f"No path found for {variant} variant")
            return []  # ← Changed from None
        except Exception as e:
            logger.warning(f"Route variant {variant} failed: {e}")
            return []  # ← Changed from None
    
    def _get_weight_attribute(
        self,
        graph: Any,
        mode: str,
        variant: str
    ) -> Optional[str]:
        """Get or create edge weight attribute for routing variant."""
        
        if variant == 'shortest':
            return 'length'
        elif variant == 'fastest':
            return self._add_time_weights(graph, mode)
        elif variant == 'safest':
            return self._add_safety_weights(graph, mode)
        elif variant == 'greenest':
            return self._add_emission_weights(graph, mode)
        elif variant == 'scenic':
            return self._add_scenic_weights(graph, mode)
        else:
            logger.warning(f"Unknown variant: {variant}, using 'length'")
            return 'length'
    
    def _add_time_weights(self, graph: Any, mode: str) -> str:
        """Add travel time as edge weights with optional congestion."""
        speed_km_min = self.speeds_km_min.get(mode, 0.1)
        speed_m_per_min = speed_km_min * 1000
        
        for u, v, key, data in graph.edges(keys=True, data=True):
            length = data.get('length', 0)
            base_time = length / speed_m_per_min if speed_m_per_min > 0 else 1e9
            
            if self.congestion_manager is not None:
                congestion_factor = self.congestion_manager.get_congestion_factor(u, v, key)
                data['time_weight'] = base_time * congestion_factor
            else:
                data['time_weight'] = base_time
        
        return 'time_weight'
    
    def _add_safety_weights(self, graph: Any, mode: str) -> str:
        """Add safety-based weights (prefer low-speed roads for bikes/walk)."""
        
        for u, v, key, data in graph.edges(keys=True, data=True):
            length = data.get('length', 0)
            highway_type = data.get('highway', 'residential')
            
            if isinstance(highway_type, list):
                highway_type = highway_type[0] if highway_type else 'residential'
            
            if mode in ['walk', 'bike', 'cargo_bike', 'e_scooter']:
                if highway_type in ['motorway', 'motorway_link', 'trunk', 'trunk_link']:
                    risk_factor = 100.0
                elif highway_type in ['primary', 'primary_link']:
                    risk_factor = 5.0
                elif highway_type in ['secondary', 'secondary_link']:
                    risk_factor = 2.0
                elif highway_type in ['residential', 'living_street', 'cycleway', 'path', 'footway']:
                    risk_factor = 0.8
                else:
                    risk_factor = 1.0
            else:
                risk_factor = 1.0
            
            data['safety_weight'] = length * risk_factor
        
        return 'safety_weight'
    
    def _add_emission_weights(self, graph: Any, mode: str) -> str:
        """Add emission-based weights (prefer flat routes)."""
        
        has_elevation = self.graph_manager.has_elevation()
        
        for u, v, key, data in graph.edges(keys=True, data=True):
            length = data.get('length', 0)
            
            if has_elevation:
                u_elev = graph.nodes[u].get('elevation', 0)
                v_elev = graph.nodes[v].get('elevation', 0)
                elev_change = abs(v_elev - u_elev)
                elev_penalty = 1.0 + (elev_change / 100.0)
            else:
                elev_penalty = 1.0
            
            data['emission_weight'] = length * elev_penalty
        
        return 'emission_weight'
    
    def _add_scenic_weights(self, graph: Any, mode: str) -> str:
        """Add scenic/quality weights (prefer green spaces, paths)."""
        
        for u, v, key, data in graph.edges(keys=True, data=True):
            length = data.get('length', 0)
            highway_type = data.get('highway', 'residential')
            
            if isinstance(highway_type, list):
                highway_type = highway_type[0] if highway_type else 'residential'
            
            if highway_type in ['path', 'footway', 'cycleway', 'track', 'bridleway']:
                scenic_factor = 0.5
            elif highway_type in ['residential', 'living_street', 'pedestrian']:
                scenic_factor = 0.7
            elif highway_type in ['tertiary', 'tertiary_link', 'unclassified']:
                scenic_factor = 0.9
            elif highway_type in ['secondary', 'secondary_link']:
                scenic_factor = 1.2
            else:
                scenic_factor = 1.5
            
            data['scenic_weight'] = length * scenic_factor
        
        return 'scenic_weight'