"""
simulation/spatial/route_diversity.py

Add route variety to overcome OSMnx deterministic shortest paths.
Multiple strategies for generating diverse but realistic routes.
"""

import random
import logging
from typing import List, Tuple, Optional
import networkx as nx

logger = logging.getLogger(__name__)


class RouteDiversifier:
    """
    Generates diverse route alternatives to OSMnx shortest paths.
    
    Strategies:
    1. K-shortest paths (Yen's algorithm)
    2. Random edge weight perturbation
    3. Via-point routing (intermediate waypoints)
    4. Time-window constraints (avoid congested times)
    """
    
    def __init__(self, diversity_mode: str = 'k_shortest', k: int = 3):
        """
        Initialize route diversifier.
        
        Args:
            diversity_mode: 'k_shortest', 'perturbed', 'via_point', or 'hybrid'
            k: Number of alternative routes to consider
        """
        self.diversity_mode = diversity_mode
        self.k = k
    
    def get_diverse_route(
        self,
        graph: nx.MultiDiGraph,
        origin_node: int,
        dest_node: int,
        weight: str = 'length',
        agent_seed: Optional[int] = None
    ) -> List[int]:
        """
        Get a diverse route between origin and destination.
        
        Args:
            graph: OSMnx graph
            origin_node: Starting node ID
            dest_node: Ending node ID
            weight: Edge weight attribute ('length', 'travel_time', etc.)
            agent_seed: Optional seed for agent-specific randomness
        
        Returns:
            List of node IDs forming the route
        """
        rng = random.Random(agent_seed) if agent_seed else random
        
        if self.diversity_mode == 'k_shortest':
            return self._k_shortest_path_route(graph, origin_node, dest_node, weight, rng)
        elif self.diversity_mode == 'perturbed':
            return self._perturbed_weight_route(graph, origin_node, dest_node, weight, rng)
        elif self.diversity_mode == 'via_point':
            return self._via_point_route(graph, origin_node, dest_node, weight, rng)
        elif self.diversity_mode == 'hybrid':
            return self._hybrid_route(graph, origin_node, dest_node, weight, rng)
        else:
            # Fallback to standard shortest path
            return nx.shortest_path(graph, origin_node, dest_node, weight=weight)
    
    def _k_shortest_path_route(
        self,
        graph: nx.MultiDiGraph,
        origin: int,
        dest: int,
        weight: str,
        rng: random.Random
    ) -> List[int]:
        """
        Use k-shortest paths algorithm to find alternatives.
        
        Returns one of the k-shortest paths randomly.
        """
        try:
            # Get k shortest paths (Yen's algorithm approximation)
            paths = list(self._k_shortest_paths(graph, origin, dest, k=self.k, weight=weight))
            
            if not paths:
                # Fallback to single shortest path
                return nx.shortest_path(graph, origin, dest, weight=weight)
            
            # Weight paths by inverse length (prefer shorter, but not exclusively)
            path_lengths = []
            for path in paths:
                length = sum(
                    graph[path[i]][path[i+1]][0].get(weight, 1)
                    for i in range(len(path) - 1)
                )
                path_lengths.append(length)
            
            # Softmax selection (prefer shorter, allow longer)
            min_length = min(path_lengths)
            weights = [1.0 / (1.0 + (length - min_length) / min_length) for length in path_lengths]
            
            chosen_path = rng.choices(paths, weights=weights, k=1)[0]
            return chosen_path
            
        except Exception as e:
            logger.warning(f"K-shortest paths failed: {e}, using shortest path")
            return nx.shortest_path(graph, origin, dest, weight=weight)
    
    def _k_shortest_paths(self, graph, source, target, k, weight='length'):
        """
        Generator for k-shortest paths (Yen's algorithm).
        
        Yields up to k paths from source to target.
        """
        # First shortest path
        try:
            path = nx.shortest_path(graph, source, target, weight=weight)
        except nx.NetworkXNoPath:
            return
        
        yield path
        
        # Find k-1 more paths
        candidates = []
        
        for _ in range(k - 1):
            # Spur node approach (simplified Yen's)
            for i in range(len(path) - 1):
                spur_node = path[i]
                root_path = path[:i+1]
                
                # Temporarily remove edges
                removed_edges = []
                for prev_path in candidates:
                    if len(prev_path) > i and prev_path[:i+1] == root_path:
                        u, v = prev_path[i], prev_path[i+1]
                        if graph.has_edge(u, v):
                            edge_data = graph[u][v]
                            removed_edges.append((u, v, edge_data))
                            graph.remove_edge(u, v)
                
                # Find spur path
                try:
                    spur_path = nx.shortest_path(graph, spur_node, target, weight=weight)
                    total_path = root_path[:-1] + spur_path
                    if total_path not in candidates and total_path != path:
                        candidates.append(total_path)
                except nx.NetworkXNoPath:
                    pass
                
                # Restore edges
                for u, v, data in removed_edges:
                    graph.add_edge(u, v, **data[0])
            
            if candidates:
                # Sort by length and yield shortest candidate
                candidates.sort(key=lambda p: sum(
                    graph[p[i]][p[i+1]][0].get(weight, 1)
                    for i in range(len(p) - 1)
                ))
                path = candidates.pop(0)
                yield path
            else:
                break
    
    def _perturbed_weight_route(
        self,
        graph: nx.MultiDiGraph,
        origin: int,
        dest: int,
        weight: str,
        rng: random.Random
    ) -> List[int]:
        """
        Perturb edge weights randomly, then find shortest path.
        
        Simulates agent-specific route preferences.
        """
        # Create temporary graph with perturbed weights
        perturbed_graph = graph.copy()
        
        for u, v, data in perturbed_graph.edges(data=True):
            original_weight = data.get(weight, 1.0)
            # Add ±20% random noise
            perturbation = rng.uniform(0.8, 1.2)
            data[f'perturbed_{weight}'] = original_weight * perturbation
        
        try:
            path = nx.shortest_path(perturbed_graph, origin, dest, weight=f'perturbed_{weight}')
            return path
        except Exception as e:
            logger.warning(f"Perturbed routing failed: {e}, using standard path")
            return nx.shortest_path(graph, origin, dest, weight=weight)
    
    def _via_point_route(
        self,
        graph: nx.MultiDiGraph,
        origin: int,
        dest: int,
        weight: str,
        rng: random.Random
    ) -> List[int]:
        """
        Route through random intermediate waypoint.
        
        Simulates agents taking scenic routes or making detours.
        """
        try:
            # Get nodes roughly between origin and dest
            origin_pos = (graph.nodes[origin]['y'], graph.nodes[origin]['x'])
            dest_pos = (graph.nodes[dest]['y'], graph.nodes[dest]['x'])
            
            mid_lat = (origin_pos[0] + dest_pos[0]) / 2
            mid_lon = (origin_pos[1] + dest_pos[1]) / 2
            
            # Find nodes near midpoint
            nearby_nodes = []
            for node, data in graph.nodes(data=True):
                node_lat, node_lon = data['y'], data['x']
                dist = ((node_lat - mid_lat)**2 + (node_lon - mid_lon)**2)**0.5
                if dist < 0.02:  # ~2km radius
                    nearby_nodes.append(node)
            
            if not nearby_nodes or len(nearby_nodes) < 5:
                # Not enough waypoints, use direct path
                return nx.shortest_path(graph, origin, dest, weight=weight)
            
            # Pick random waypoint
            via_node = rng.choice(nearby_nodes)
            
            # Route: origin → via → dest
            path1 = nx.shortest_path(graph, origin, via_node, weight=weight)
            path2 = nx.shortest_path(graph, via_node, dest, weight=weight)
            
            # Combine (remove duplicate via_node)
            combined_path = path1 + path2[1:]
            return combined_path
            
        except Exception as e:
            logger.warning(f"Via-point routing failed: {e}, using standard path")
            return nx.shortest_path(graph, origin, dest, weight=weight)
    
    def _hybrid_route(
        self,
        graph: nx.MultiDiGraph,
        origin: int,
        dest: int,
        weight: str,
        rng: random.Random
    ) -> List[int]:
        """
        Randomly choose between k-shortest, perturbed, and via-point.
        """
        strategy = rng.choice(['k_shortest', 'perturbed', 'via_point'])
        
        if strategy == 'k_shortest':
            return self._k_shortest_path_route(graph, origin, dest, weight, rng)
        elif strategy == 'perturbed':
            return self._perturbed_weight_route(graph, origin, dest, weight, rng)
        else:
            return self._via_point_route(graph, origin, dest, weight, rng)


# Integration with existing system
def integrate_route_diversity(env, agent_seed: Optional[int] = None, diversity_mode: str = 'k_shortest'):
    """
    Add route diversity to SpatialEnvironment.
    
    Usage in simulation_runner.py:
    
    ```python
    # After loading environment
    env = setup_environment(config)
    env.route_diversifier = RouteDiversifier(diversity_mode='hybrid', k=3)
    ```
    
    Usage in router.py:
    
    ```python
    # In compute_route method
    if hasattr(self, 'route_diversifier'):
        nodes = self.route_diversifier.get_diverse_route(
            graph, origin_node, dest_node, weight='length', agent_seed=agent_seed
        )
    else:
        nodes = nx.shortest_path(graph, origin_node, dest_node, weight='length')
    ```
    """
    env.route_diversifier = RouteDiversifier(diversity_mode=diversity_mode, k=3)
    return env