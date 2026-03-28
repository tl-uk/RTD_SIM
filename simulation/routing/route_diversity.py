"""
simulation/routing/route_diversity.py

This module implements route diversity strategies for realistic agent routing behavior.
It provides multiple approaches to prevent deterministic shortest-path routing, 
including:
- Perturbed weights: Adds random noise to edge weights for agent-specific preferences.
- K-shortest paths: Computes multiple shortest paths and randomly selects among them.
- Ultra-fast hash-based perturbation: Uses a deterministic hash function for minimal overhead.

The module is designed to be flexible, allowing different strategies to be applied based 
on performance needs and realism requirements. It modifies the routing behavior of the 
spatial environment by wrapping the existing route computation function with the selected 
diversity strategy.

Route diversity strategies for realistic agent routing behavior.
Prevents deterministic shortest-path routing.
"""

import random
import networkx as nx
import logging

logger = logging.getLogger(__name__)

# ===========================
# SHARED GEOMETRY HELPER
# ===========================
def _extract_route_geometry(
    graph,
    node_path: list,
) -> list:
    """
    Extract detailed (lon, lat) geometry from an OSMnx node path.

    For each edge in the path, uses the Shapely LineString stored on the
    edge (if present) so that curved roads render correctly on the map.
    Falls back to endpoint-node coordinates when geometry is absent
    (e.g. stale cache without geometry).  In that case straight lines are
    drawn — delete the cache file to force a re-download that includes
    full geometry.

    Args:
        graph: NetworkX MultiDiGraph from OSMnx
        node_path: Ordered list of OSM node IDs

    Returns:
        List of (lon, lat) tuples following the real road geometry.
    """
    if not node_path or len(node_path) < 2:
        return []

    coords = []
    for i in range(len(node_path) - 1):
        u = node_path[i]
        v = node_path[i + 1]

        # Add first node only on first iteration to avoid duplicates
        if i == 0:
            coords.append((float(graph.nodes[u]["x"]), float(graph.nodes[u]["y"])))

        # Prefer the Shapely geometry stored on the edge (curved road data)
        edge_data = graph.get_edge_data(u, v)
        if edge_data and isinstance(edge_data, dict) and 0 in edge_data:
            edge_data = edge_data[0]

        if edge_data and "geometry" in edge_data:
            geom = edge_data["geometry"]
            if hasattr(geom, "coords"):
                # Extend with all geometry points except the first
                # (already appended as the previous node / loop start)
                coords.extend(
                    (float(x), float(y)) for x, y in list(geom.coords)[1:]
                )
                continue  # geometry handled — skip node-only fallback

        # Fallback: straight line to next node
        coords.append((float(graph.nodes[v]["x"]), float(graph.nodes[v]["y"])))

    return coords


# ===========================
# ROUTE DIVERSITY STRATEGIES
# ===========================
def add_route_diversity_perturbed(env):
    """
    Add route diversity through weight perturbation.
    
    Fast and provides agent-specific route preferences.
    Uses on-the-fly weight function (no graph copying).
    
    Performance: ~0.05 seconds per route
    """
    original_compute_route = env.compute_route
    
    def diversified_compute_route(agent_id, origin, dest, mode='drive', policy_context=None, **kwargs):
        """Compute route with agent-specific perturbation.

        policy_context is accepted and forwarded to the real router so that
        scenario parameters (carbon_tax, VoT, energy_price) reach edge weights.
        Non-road modes (rail, transit, ferry, air) are delegated directly to
        the real router rather than the drive-graph perturbation path.
        """
        agent_seed = hash(agent_id) % (2**32)
        rng = random.Random(agent_seed)

        # Only perturb road modes — rail/transit/ferry/air have dedicated routing paths
        _ROAD_MODES = {
            'walk', 'bike', 'cargo_bike', 'e_scooter',
            'car', 'ev', 'taxi_ev', 'taxi_diesel',
            'van_electric', 'van_diesel',
            'truck_electric', 'truck_diesel',
            'hgv_electric', 'hgv_diesel', 'hgv_hydrogen',
            'bus',   # bus uses drive graph when no GTFS loaded
        }
        if mode not in _ROAD_MODES:
            return original_compute_route(agent_id, origin, dest, mode, policy_context=policy_context)

        network_type = {
            'walk': 'walk', 'bike': 'bike', 'cargo_bike': 'bike', 'e_scooter': 'bike',
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
            return _extract_route_geometry(graph, node_path)
            
        except nx.NetworkXNoPath:
            return original_compute_route(agent_id, origin, dest, mode, policy_context=policy_context)
        except Exception as e:
            logger.warning(f"Perturbed routing failed: {e}, using fallback")
            return original_compute_route(agent_id, origin, dest, mode, policy_context=policy_context)
    
    env.compute_route = diversified_compute_route
    return env

# Other strategies (k-shortest, ultra-fast) can be implemented similarly by wrapping the 
# compute_route function with different logic for path selection.
def add_route_diversity_k_shortest(env, k=3):
    """
    Add route diversity using k-shortest paths.
    
    More realistic but slower than perturbation.
    Agents randomly select from top-k shortest paths.
    
    Performance: ~0.1-0.2 seconds per route
    """
    original_compute_route = env.compute_route
    
    def k_shortest_compute_route(agent_id, origin, dest, mode='drive', policy_context=None, **kwargs):
        """Find k shortest paths efficiently.

        policy_context forwarded to real router for non-road modes and fallbacks.
        """
        agent_seed = hash(agent_id) % (2**32)
        rng = random.Random(agent_seed)

        _ROAD_MODES_K = {
            'walk', 'bike', 'cargo_bike', 'e_scooter',
            'car', 'ev', 'taxi_ev', 'taxi_diesel',
            'van_electric', 'van_diesel',
            'truck_electric', 'truck_diesel',
            'hgv_electric', 'hgv_diesel', 'hgv_hydrogen',
            'bus',
        }
        if mode not in _ROAD_MODES_K:
            return original_compute_route(agent_id, origin, dest, mode, policy_context=policy_context)

        network_type = {
            'walk': 'walk', 'bike': 'bike', 'cargo_bike': 'bike', 'e_scooter': 'bike',
        }.get(mode, 'drive')
        
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
            return _extract_route_geometry(graph, chosen_path)
            
        except Exception as e:
            logger.warning(f"K-shortest failed: {e}, using standard path")
            return original_compute_route(agent_id, origin, dest, mode, policy_context=policy_context)
    
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
    
    # This method applies a deterministic hash-based perturbation to edge weights, creating
    # agent-specific route preferences with minimal computational overhead. It does not
    # guarantee optimality but provides a simple way to introduce diversity without complex
    # path enumeration or random sampling. The logic is embedded directly in the weight function, 
    # ensuring that the same agent will consistently receive the same route for the same 
    # origin-destination pair, while different agents will have different routes due to 
    # their unique hashes. This approach is ideal for large-scale simulations where performance 
    # is a concern and some level of route diversity is desired without the need for complex 
    # algorithms.
    def ultra_fast_diverse_route(agent_id, origin, dest, mode='drive', policy_context=None, **kwargs):
        """Route with hash-based agent-specific bias.

        policy_context accepted and forwarded so that scenario-adjusted edge
        weights (carbon_tax, VoT, energy_price) reach the real router for any
        mode that bypasses the drive-graph perturbation path.
        """
        agent_seed = hash(agent_id) % (2**32)

        _ROAD_MODES_UF = {
            'walk', 'bike', 'cargo_bike', 'e_scooter',
            'car', 'ev', 'taxi_ev', 'taxi_diesel',
            'van_electric', 'van_diesel',
            'truck_electric', 'truck_diesel',
            'hgv_electric', 'hgv_diesel', 'hgv_hydrogen',
            'bus',
        }
        if mode not in _ROAD_MODES_UF:
            return original_compute_route(agent_id, origin, dest, mode, policy_context=policy_context)

        network_type = {
            'walk': 'walk', 'bike': 'bike', 'cargo_bike': 'bike', 'e_scooter': 'bike',
        }.get(mode, 'drive')
        
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
            return _extract_route_geometry(graph, node_path)
            
        except Exception as e:
            return original_compute_route(agent_id, origin, dest, mode, policy_context=policy_context)
    
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