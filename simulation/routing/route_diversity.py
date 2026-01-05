"""
simulation/routing/route_diversity.py

Route diversity strategies for realistic agent routing behavior.
Prevents deterministic shortest-path routing.
"""

import random
import networkx as nx
import logging

logger = logging.getLogger(__name__)


def add_route_diversity_perturbed(env):
    """
    Add route diversity through weight perturbation.
    
    Fast and provides agent-specific route preferences.
    Uses on-the-fly weight function (no graph copying).
    
    Performance: ~0.05 seconds per route
    """
    original_compute_route = env.compute_route
    
    def diversified_compute_route(agent_id, origin, dest, mode='drive'):
        """Compute route with agent-specific perturbation."""
        agent_seed = hash(agent_id) % (2**32)
        rng = random.Random(agent_seed)
        
        network_type = {
            'walk': 'walk', 'bike': 'bike', 'bus': 'drive',
            'car': 'drive', 'ev': 'drive',
            'van_electric': 'drive', 'van_diesel': 'drive'
        }.get(mode, 'drive')
        
        graph = env.graph_manager.get_graph(network_type)
        if graph is None:
            return []
        
        origin_node = env.graph_manager.get_nearest_node(origin, network_type)
        dest_node = env.graph_manager.get_nearest_node(dest, network_type)
        
        if origin_node is None or dest_node is None:
            return []
        
        try:
            edge_perturbations = {}
            
            def perturbed_weight(u, v, d):
                """Weight function with agent-specific perturbation."""
                edge_key = (u, v)
                if edge_key not in edge_perturbations:
                    edge_perturbations[edge_key] = rng.uniform(0.85, 1.15)
                return d.get('length', 1.0) * edge_perturbations[edge_key]
            
            node_path = nx.shortest_path(graph, origin_node, dest_node, weight=perturbed_weight)
            route = [(graph.nodes[n]['x'], graph.nodes[n]['y']) for n in node_path]
            return route
            
        except nx.NetworkXNoPath:
            return original_compute_route(agent_id, origin, dest, mode)
        except Exception as e:
            logger.warning(f"Perturbed routing failed: {e}, using fallback")
            return original_compute_route(agent_id, origin, dest, mode)
    
    env.compute_route = diversified_compute_route
    return env


def add_route_diversity_k_shortest(env, k=3):
    """
    Add route diversity using k-shortest paths.
    
    More realistic but slower than perturbation.
    Agents randomly select from top-k shortest paths.
    
    Performance: ~0.1-0.2 seconds per route
    """
    original_compute_route = env.compute_route
    
    def k_shortest_compute_route(agent_id, origin, dest, mode='drive'):
        """Find k shortest paths efficiently."""
        agent_seed = hash(agent_id) % (2**32)
        rng = random.Random(agent_seed)
        
        network_type = {'walk': 'walk', 'bike': 'bike'}.get(mode, 'drive')
        
        graph = env.graph_manager.get_graph(network_type)
        if graph is None:
            return []
        
        origin_node = env.graph_manager.get_nearest_node(origin, network_type)
        dest_node = env.graph_manager.get_nearest_node(dest, network_type)
        
        if origin_node is None or dest_node is None:
            return []
        
        try:
            shortest_path = nx.shortest_path(graph, origin_node, dest_node, weight='length')
            shortest_length = sum(
                graph[shortest_path[i]][shortest_path[i+1]][0]['length']
                for i in range(len(shortest_path) - 1)
            )
            
            all_paths = [(shortest_path, shortest_length)]
            paths_found = 1
            max_iterations = 20
            
            for iteration, path in enumerate(nx.all_simple_paths(
                graph, origin_node, dest_node, cutoff=len(shortest_path) + 3
            )):
                if iteration >= max_iterations:
                    break
                if path == shortest_path:
                    continue
                
                path_length = sum(
                    graph[path[i]][path[i+1]][0]['length']
                    for i in range(len(path) - 1)
                )
                
                if path_length <= shortest_length * 1.3:
                    all_paths.append((path, path_length))
                    paths_found += 1
                    if paths_found >= k:
                        break
            
            min_length = min(length for _, length in all_paths)
            weights = [1.0 / (1.0 + (length - min_length) / min_length) for _, length in all_paths]
            
            chosen_path, _ = rng.choices(all_paths, weights=weights, k=1)[0]
            route = [(graph.nodes[n]['x'], graph.nodes[n]['y']) for n in chosen_path]
            return route
            
        except Exception as e:
            logger.warning(f"K-shortest failed: {e}, using standard path")
            return original_compute_route(agent_id, origin, dest, mode)
    
    env.compute_route = k_shortest_compute_route
    return env


def add_route_diversity_ultra_fast(env):
    """
    Ultra-fast route diversity using hash-based perturbation.
    
    Fastest option with minimal overhead.
    Uses deterministic hash function for agent-specific routes.
    
    Performance: ~0.02 seconds per route
    """
    original_compute_route = env.compute_route
    
    def ultra_fast_diverse_route(agent_id, origin, dest, mode='drive'):
        """Route with hash-based agent-specific bias."""
        agent_seed = hash(agent_id) % (2**32)
        
        network_type = {'walk': 'walk', 'bike': 'bike'}.get(mode, 'drive')
        
        graph = env.graph_manager.get_graph(network_type)
        if graph is None:
            return []
        
        origin_node = env.graph_manager.get_nearest_node(origin, network_type)
        dest_node = env.graph_manager.get_nearest_node(dest, network_type)
        
        if origin_node is None or dest_node is None:
            return []
        
        try:
            def agent_biased_weight(u, v, d):
                """Apply agent-specific bias to edge weights."""
                length = d.get('length', 1.0)
                edge_hash = hash((u, v, agent_seed)) % 1000
                perturbation = 0.85 + (edge_hash / 1000) * 0.3
                return length * perturbation
            
            node_path = nx.shortest_path(graph, origin_node, dest_node, weight=agent_biased_weight)
            route = [(graph.nodes[n]['x'], graph.nodes[n]['y']) for n in node_path]
            return route
            
        except Exception as e:
            return original_compute_route(agent_id, origin, dest, mode)
    
    env.compute_route = ultra_fast_diverse_route
    return env


def apply_route_diversity(env, mode='ultra_fast', k=3):
    """
    Apply selected route diversity strategy.
    
    Args:
        env: SpatialEnvironment instance
        mode: Strategy - 'perturbed', 'k_shortest', or 'ultra_fast'
        k: Number of paths for k-shortest algorithm
    
    Returns:
        Modified environment with route diversity
    """
    if mode == 'perturbed':
        return add_route_diversity_perturbed(env)
    elif mode == 'k_shortest':
        return add_route_diversity_k_shortest(env, k)
    elif mode == 'ultra_fast':
        return add_route_diversity_ultra_fast(env)
    else:
        logger.warning(f"Unknown route diversity mode: {mode}, no diversity applied")
        return env