"""
agent/social_network.py

This module implements a Social Network Influence System. The SocialNetwork class models 
the social connections between agents, allowing for peer influence on transport mode 
choice. It supports multiple network topologies (small-world, scale-free, homophily-based), 
distinguishes between strong and weak ties, and includes mechanisms for detecting social 
cascades and tipping points in mode adoption.

Implements:
- Social network topologies (small-world, scale-free, homophily-based)
- Peer influence on mode choice
- Social cascades & tipping points
- Strong ties vs weak ties
- Information diffusion
- Conformity pressure

Research basis: Social influence significantly affects transport mode choice through
peer observation, information exchange, and conformity mechanisms.
"""

from __future__ import annotations
from typing import Dict, List, Tuple, Set, Optional, Any
from dataclasses import dataclass, field
from collections import Counter, defaultdict
import random
import logging

try:
    import networkx as nx
    NETWORKX_AVAILABLE = True
except ImportError:
    NETWORKX_AVAILABLE = False
    logging.warning("NetworkX not available - install with: pip install networkx")

logger = logging.getLogger(__name__)

# ========================================================================
# Data Classes for Social Ties and Network Metrics
# ========================================================================

# Data class representing a social tie between two agents, with attributes for strength, 
# type, geographic distance, and interaction frequency. Includes methods to determine if 
# it's a strong tie and to calculate influence weight.
@dataclass
class SocialTie:
    """Represents a social connection between two agents."""
    source_id: str
    target_id: str
    strength: float = 0.5  # 0-1, where 1 = strong tie, 0 = weak tie
    tie_type: str = 'friend'  # 'family', 'friend', 'colleague', 'neighbor'
    geographic_distance_km: float = 0.0
    interaction_frequency: float = 0.5  # 0-1, how often they interact
    
    def is_strong_tie(self, threshold: float = 0.6) -> bool:
        """Strong ties defined as strength > threshold."""
        return self.strength >= threshold
    
    def get_influence_weight(self) -> float:
        """
        Calculate influence weight based on tie characteristics.
        
        Strong ties + high frequency + close proximity = high influence.
        """
        # Combine factors
        geo_factor = 1.0 / (1.0 + self.geographic_distance_km / 10.0)  # Decay with distance
        weight = (
            0.5 * self.strength +
            0.3 * self.interaction_frequency +
            0.2 * geo_factor
        )
        return min(1.0, weight)

# Data class for aggregate network metrics, including total agents, ties, average degree,
# clustering coefficient, average path length, network density, strong tie ratio, mode
# distribution, and cascade/tipping point indicators.
@dataclass
class NetworkMetrics:
    """Aggregate network statistics."""
    total_agents: int = 0
    total_ties: int = 0
    avg_degree: float = 0.0
    clustering_coefficient: float = 0.0
    avg_path_length: float = 0.0
    network_density: float = 0.0
    strong_tie_ratio: float = 0.0
    
    # Mode adoption metrics
    mode_distribution: Dict[str, float] = field(default_factory=dict)
    mode_clusters: List[Set[str]] = field(default_factory=list)
    tipping_point_reached: bool = False
    cascade_active: bool = False

# ========================================================================
# Social Network Class
# ========================================================================

# The SocialNetwork class models the social connections between agents, allowing for peer
# influence on transport mode choice. It supports multiple network topologies (small-world,
# scale-free, homophily-based), distinguishes between strong and weak ties, and includes
# mechanisms for detecting social cascades and tipping points in mode adoption. The class
# includes methods for building the network, applying social influence to mode costs,
# detecting cascades, and calculating network metrics.
class SocialNetwork:
    """
    Social network for agent-based transport simulation.
    
    Features:
    - Multiple network topologies
    - Strong/weak tie distinction
    - Peer influence on mode choice
    - Cascade detection
    - Homophily (similarity-based connections)
    """
    
    def __init__(
        self,
        topology: str = 'small_world',
        strong_tie_threshold: float = 0.6,
        influence_enabled: bool = True
    ):
        """
        Initialize social network.
        
        Args:
            topology: Network structure ('small_world', 'scale_free', 'random', 'homophily')
            strong_tie_threshold: Threshold for classifying strong ties
            influence_enabled: Whether to apply social influence
        """
        if not NETWORKX_AVAILABLE:
            raise ImportError("NetworkX required: pip install networkx")
        
        self.G = nx.Graph()
        self.topology = topology
        self.strong_tie_threshold = strong_tie_threshold
        self.influence_enabled = influence_enabled
        
        # Agent registry
        self._agent_registry: Dict[str, Any] = {}  # agent_id -> agent object
        
        # Influence tracking
        self._influence_history: List[Dict[str, Any]] = []
        self._mode_adoption_history: List[Dict[str, int]] = []
        
        logger.info(f"SocialNetwork initialized: {topology} topology")
    
    # ========================================================================
    # Network Construction
    # ========================================================================
    
    def build_network(
        self,
        agents: List[Any],
        k: int = 4,  # Average degree
        p: float = 0.1,  # Rewiring probability (for small-world)
        seed: Optional[int] = None,
        cross_persona_prob: float = 0.25,  # Fraction of cross-persona ties (homophily)
    ) -> None:
        """
        Build social network from agent population.
        
        Args:
            agents:             List of agent objects.
            k:                  Average degree (connections per agent).
            p:                  Rewiring probability (Watts-Strogatz only).
            seed:               Random seed.
            cross_persona_prob: Fraction of each agent's ties that cross persona
                                boundary (homophily topology only).  Default 0.25
                                matches empirical bridging-tie ratios and ensures
                                cross-group EV adoption diffusion.
        """
        n = len(agents)
        
        if n == 0:
            logger.warning("No agents provided to build network")
            return
        
        # Register agents
        for agent in agents:
            agent_id = agent.state.agent_id
            self._agent_registry[agent_id] = agent
            self.G.add_node(agent_id, agent=agent)
        
        # Build topology
        if self.topology == 'small_world':
            self._build_small_world(n, k, p, seed)
        elif self.topology == 'scale_free':
            self._build_scale_free(n, k, seed)
        elif self.topology == 'random':
            self._build_random(n, k, seed)
        elif self.topology == 'homophily':
            self._build_homophily(agents, k, seed, cross_persona_prob=cross_persona_prob)
        else:
            logger.warning(f"Unknown topology: {self.topology}, using small_world")
            self._build_small_world(n, k, p, seed)
        
        # Assign tie attributes
        self._assign_tie_attributes(agents)
        
        logger.info(f"Network built: {n} agents, {self.G.number_of_edges()} ties")
    
    # ========================================================================
    # Helper methods for building different topologies
    # ========================================================================
    # Note: These methods create a temporary graph structure and then map it to the 
    # agent IDs in self.G. This allows us to leverage NetworkX's built-in graph generators 
    # while maintaining control over the agent IDs and tie attributes in our main graph.
    # The homophily-based network is built by calculating similarity between agents and connecting
    # them based on that similarity, with some randomness to avoid deterministic connections.
    # The tie attributes are assigned after the network is built, based on the similarity 
    # and interaction patterns of the connected agents.
    # The influence weight of each tie is calculated based on its strength, interaction 
    # frequency, and geographic distance, which can be used later when applying social 
    # influence to mode costs. This allows for a more nuanced influence mechanism where 
    # not all connections have the same impact on an agent's mode choice.
    def _build_small_world(self, n: int, k: int, p: float, seed: Optional[int]) -> None:
        """Watts-Strogatz small-world network."""
        # Create lattice
        temp_g = nx.watts_strogatz_graph(n, k, p, seed=seed)
        
        # Map to agent IDs
        agent_ids = list(self.G.nodes())
        for u, v in temp_g.edges():
            self.G.add_edge(agent_ids[u], agent_ids[v])
    
    def _build_scale_free(self, n: int, m: int, seed: Optional[int]) -> None:
        """Barabási-Albert scale-free network (preferential attachment)."""
        temp_g = nx.barabasi_albert_graph(n, m, seed=seed)
        
        agent_ids = list(self.G.nodes())
        for u, v in temp_g.edges():
            self.G.add_edge(agent_ids[u], agent_ids[v])
    
    def _build_random(self, n: int, avg_degree: int, seed: Optional[int]) -> None:
        """Erdős-Rényi random network."""
        p_edge = avg_degree / (n - 1) if n > 1 else 0
        temp_g = nx.erdos_renyi_graph(n, p_edge, seed=seed)
        
        agent_ids = list(self.G.nodes())
        for u, v in temp_g.edges():
            self.G.add_edge(agent_ids[u], agent_ids[v])
    
    def _build_homophily(
        self,
        agents: List[Any],
        k: int,
        seed: Optional[int],
        cross_persona_prob: float = 0.25,
    ) -> None:
        """
        Homophily network: agents connect with similar others, with a
        guaranteed fraction of cross-persona ties.

        Without cross-persona wiring the desire-similarity scores are so
        dominated by persona type that the candidate pool (top k*2) is
        always same-persona, producing a collection of isolated per-persona
        stars with zero inter-group edges.  Real social networks have both
        strong homophily *and* bridging ties (Granovetter 1973).

        Algorithm per agent:
          - same_slots  = round(k * (1 - cross_persona_prob))  ← within-persona
          - cross_slots = k - same_slots                        ← cross-persona
          - Same-persona pool: top same_slots*3 most similar WITHIN persona,
            weighted-random draw.
          - Cross-persona pool: top cross_slots*3 most similar ACROSS personas,
            weighted-random draw (ensures diverse bridging ties, not purely
            random noise).

        Args:
            agents:             Full agent list.
            k:                  Target degree per agent.
            seed:               RNG seed for reproducibility.
            cross_persona_prob: Fraction of ties that cross persona boundary
                                (default 0.25 — matches Watts-Strogatz p).
        """
        rng = random.Random(seed)
        agent_list = list(agents)

        # Pre-group agents by persona for fast pool construction.
        # Fall back to user_story_id then a fixed constant if neither exists.
        def _persona(a) -> str:
            return (
                getattr(a, 'user_story_id', None)
                or getattr(a, 'persona_id', None)
                or 'unknown'
            )

        persona_of = {a.state.agent_id: _persona(a) for a in agent_list}

        for agent in agent_list:
            agent_id  = agent.state.agent_id
            my_persona = persona_of[agent_id]

            # How many slots go to same-persona vs cross-persona
            cross_slots = max(1, round(k * cross_persona_prob))
            same_slots  = k - cross_slots

            # Separate existing candidates into two pools
            same_pool  = []   # (other_id, similarity)
            cross_pool = []

            for other in agent_list:
                other_id = other.state.agent_id
                if other_id == agent_id or self.G.has_edge(agent_id, other_id):
                    continue
                sim = self._calculate_similarity(agent, other)
                if persona_of[other_id] == my_persona:
                    same_pool.append((other_id, sim))
                else:
                    cross_pool.append((other_id, sim))

            # Sort both pools by similarity descending so weights are positive
            same_pool.sort(key=lambda x: x[1], reverse=True)
            cross_pool.sort(key=lambda x: x[1], reverse=True)

            def _draw(pool, n_slots):
                """Weighted draw from the top 3*n_slots of pool."""
                candidates = pool[:n_slots * 3]
                if not candidates:
                    return []
                ids     = [c[0] for c in candidates]
                weights = [max(c[1], 1e-6) for c in candidates]   # no zero weights
                draw_n  = min(n_slots, len(ids))
                # rng.choices allows duplicates; deduplicate while preserving order
                seen, result = set(), []
                for oid in rng.choices(ids, weights=weights, k=draw_n * 2):
                    if oid not in seen and not self.G.has_edge(agent_id, oid):
                        seen.add(oid)
                        result.append(oid)
                    if len(result) == draw_n:
                        break
                return result

            selected = _draw(same_pool, same_slots) + _draw(cross_pool, cross_slots)

            for other_id in selected:
                if not self.G.has_edge(agent_id, other_id):
                    self.G.add_edge(agent_id, other_id)
    
    def _calculate_similarity(self, agent1: Any, agent2: Any) -> float:
        """
        Calculate similarity between two agents.
        
        Based on desire vector distance (Euclidean).
        """
        desires1 = agent1.desires
        desires2 = agent2.desires
        
        # Get common desire keys
        keys = set(desires1.keys()) & set(desires2.keys())
        
        if not keys:
            return 0.0
        
        # Euclidean distance
        dist_sq = sum((desires1[k] - desires2[k])**2 for k in keys)
        distance = dist_sq ** 0.5
        
        # Convert to similarity (0-1, higher = more similar)
        max_dist = len(keys) ** 0.5  # Max possible distance
        similarity = 1.0 - (distance / max_dist) if max_dist > 0 else 0.0
        
        return similarity
    
    def _assign_tie_attributes(self, agents: List[Any]) -> None:
        """Assign attributes to edges (tie strength, type, etc.)."""
        for u, v in self.G.edges():
            agent_u = self._agent_registry[u]
            agent_v = self._agent_registry[v]
            
            # Calculate tie strength based on similarity
            strength = self._calculate_similarity(agent_u, agent_v)
            
            # Classify tie type based on strength
            if strength > 0.8:
                tie_type = 'family'
            elif strength > 0.6:
                tie_type = 'friend'
            elif strength > 0.4:
                tie_type = 'colleague'
            else:
                tie_type = 'acquaintance'
            
            # Geographic distance (if locations available)
            geo_dist = 0.0
            if hasattr(agent_u.state, 'location') and hasattr(agent_v.state, 'location'):
                loc_u = agent_u.state.location
                loc_v = agent_v.state.location
                if loc_u and loc_v:
                    # Haversine distance approximation
                    geo_dist = ((loc_u[0] - loc_v[0])**2 + (loc_u[1] - loc_v[1])**2)**0.5
            
            # Interaction frequency (random for now, could be learned)
            interaction_freq = random.uniform(0.3, 0.9)
            
            # Store as edge attributes
            self.G[u][v]['strength'] = strength
            self.G[u][v]['tie_type'] = tie_type
            self.G[u][v]['geo_distance'] = geo_dist
            self.G[u][v]['interaction_freq'] = interaction_freq
    
    # ========================================================================
    # Social Influence
    # ========================================================================
    
    def get_peer_mode_share(
        self, 
        agent_id: str,
        strong_ties_only: bool = False
    ) -> Dict[str, float]:
        """
        Get mode share among agent's social connections.
        
        Args:
            agent_id: Agent identifier
            strong_ties_only: If True, only consider strong ties
        
        Returns:
            Dictionary of {mode: proportion}
        """
        if agent_id not in self.G:
            return {}
        
        neighbors = list(self.G.neighbors(agent_id))
        
        if not neighbors:
            return {}
        
        # Filter by tie strength if requested
        if strong_ties_only:
            neighbors = [
                n for n in neighbors
                if self.G[agent_id][n].get('strength', 0) >= self.strong_tie_threshold
            ]
        
        # Count modes
        mode_counts = Counter()
        total_weight = 0.0
        
        for neighbor_id in neighbors:
            neighbor = self._agent_registry.get(neighbor_id)
            if neighbor:
                mode = neighbor.state.mode
                
                # Weight by tie strength
                weight = self.G[agent_id][neighbor_id].get('strength', 0.5)
                mode_counts[mode] += weight
                total_weight += weight
        
        # Convert to proportions
        if total_weight > 0:
            mode_share = {
                mode: count / total_weight
                for mode, count in mode_counts.items()
            }
        else:
            mode_share = {}
        
        return mode_share
    
    def apply_social_influence(
        self,
        agent_id: str,
        mode_costs: Dict[str, float],
        influence_strength: float = 0.2,
        conformity_pressure: float = 0.3
    ) -> Dict[str, float]:
        """
        Apply social influence to mode costs.
        
        Mechanism: Reduce perceived cost of modes used by peers.
        
        Args:
            agent_id: Agent identifier
            mode_costs: Dictionary of {mode: cost}
            influence_strength: How much peers affect costs (0-1)
            conformity_pressure: Additional pressure from network density (0-1)
        
        Returns:
            Adjusted costs with social influence
        """
        if not self.influence_enabled or agent_id not in self.G:
            return mode_costs
        
        # Get peer mode preferences
        peer_modes = self.get_peer_mode_share(agent_id)
        
        if not peer_modes:
            return mode_costs
        
        # Adjust costs
        adjusted_costs = mode_costs.copy()
        
        for mode, peer_share in peer_modes.items():
            if mode in adjusted_costs:
                # Reduce cost proportional to peer adoption
                discount = influence_strength * peer_share
                
                # Add conformity pressure if mode is dominant
                if peer_share > 0.5:  # Majority using this mode
                    discount += conformity_pressure * (peer_share - 0.5)
                
                adjusted_costs[mode] *= (1.0 - min(discount, 0.5))  # Max 50% discount
        
        # Track influence event
        self._influence_history.append({
            'agent_id': agent_id,
            'peer_modes': peer_modes,
            'original_costs': mode_costs,
            'adjusted_costs': adjusted_costs
        })
        
        return adjusted_costs
    
    def get_strong_tie_influence(self, agent_id: str) -> Dict[str, float]:
        """Get mode share from strong ties only."""
        return self.get_peer_mode_share(agent_id, strong_ties_only=True)
    
    def get_weak_tie_influence(self, agent_id: str) -> Dict[str, float]:
        """Get mode share from weak ties only."""
        if agent_id not in self.G:
            return {}
        
        neighbors = list(self.G.neighbors(agent_id))
        weak_neighbors = [
            n for n in neighbors
            if self.G[agent_id][n].get('strength', 0) < self.strong_tie_threshold
        ]
        
        if not weak_neighbors:
            return {}
        
        mode_counts = Counter()
        for neighbor_id in weak_neighbors:
            neighbor = self._agent_registry.get(neighbor_id)
            if neighbor:
                mode_counts[neighbor.state.mode] += 1
        
        total = sum(mode_counts.values())
        return {mode: count / total for mode, count in mode_counts.items()} if total > 0 else {}
    
    # ========================================================================
    # Cascade Detection
    # ========================================================================
    
    def detect_cascade(
        self,
        mode: str,
        threshold: float = 0.2,
        min_cluster_size: int = 5
    ) -> Tuple[bool, List[Set[str]]]:
        """
        Detect if a cascade (rapid adoption spread) is occurring.
        
        Cascade = spatially/socially clustered adoption above threshold.
        
        Args:
            mode: Mode to check for cascade
            threshold: Minimum adoption rate to consider cascade
            min_cluster_size: Minimum cluster size
        
        Returns:
            (cascade_detected, list_of_clusters)
        """
        # Find all agents using this mode
        mode_users = set()
        for agent_id, agent in self._agent_registry.items():
            if agent.state.mode == mode:
                mode_users.add(agent_id)
        
        if len(mode_users) < min_cluster_size:
            return False, []
        
        # Overall adoption rate
        adoption_rate = len(mode_users) / len(self._agent_registry)
        
        if adoption_rate < threshold:
            return False, []
        
        # Find connected components of mode users
        mode_subgraph = self.G.subgraph(mode_users)
        clusters = list(nx.connected_components(mode_subgraph))
        
        # Filter by size
        significant_clusters = [c for c in clusters if len(c) >= min_cluster_size]
        
        cascade_detected = len(significant_clusters) > 0
        
        return cascade_detected, significant_clusters
    
    def detect_tipping_point(
        self,
        mode: str,
        history_window: int = 10,
        acceleration_threshold: float = 0.05
    ) -> bool:
        """
        Detect if mode adoption has reached a tipping point.
        
        Tipping point = sudden acceleration in adoption rate.
        
        Args:
            mode: Mode to check
            history_window: Number of historical periods to compare
            acceleration_threshold: Minimum acceleration to detect tipping
        
        Returns:
            True if tipping point detected
        """
        if len(self._mode_adoption_history) < history_window + 1:
            return False
        
        # Get recent adoption rates
        recent_rates = []
        for hist in self._mode_adoption_history[-history_window:]:
            total = sum(hist.values())
            rate = hist.get(mode, 0) / total if total > 0 else 0
            recent_rates.append(rate)
        
        # Calculate acceleration (second derivative)
        if len(recent_rates) < 3:
            return False
        
        # Simple acceleration: compare recent vs older rates
        old_avg = sum(recent_rates[:len(recent_rates)//2]) / (len(recent_rates)//2)
        new_avg = sum(recent_rates[len(recent_rates)//2:]) / (len(recent_rates) - len(recent_rates)//2)
        
        acceleration = new_avg - old_avg
        
        return acceleration >= acceleration_threshold
    
    # ========================================================================
    # Network Analysis
    # ========================================================================
    
    def get_network_metrics(self) -> NetworkMetrics:
        """Calculate network statistics."""
        metrics = NetworkMetrics()
        
        if len(self.G) == 0:
            return metrics
        
        metrics.total_agents = len(self.G.nodes())
        metrics.total_ties = len(self.G.edges())
        
        # Average degree
        degrees = [d for _, d in self.G.degree()]
        metrics.avg_degree = sum(degrees) / len(degrees) if degrees else 0
        
        # Clustering
        try:
            metrics.clustering_coefficient = nx.average_clustering(self.G)
        except:
            metrics.clustering_coefficient = 0.0
        
        # Average path length (expensive for large graphs)
        if len(self.G) < 500:
            try:
                if nx.is_connected(self.G):
                    metrics.avg_path_length = nx.average_shortest_path_length(self.G)
            except:
                pass
        
        # Density
        metrics.network_density = nx.density(self.G)
        
        # Strong tie ratio
        strong_ties = sum(
            1 for u, v, data in self.G.edges(data=True)
            if data.get('strength', 0) >= self.strong_tie_threshold
        )
        metrics.strong_tie_ratio = strong_ties / metrics.total_ties if metrics.total_ties > 0 else 0
        
        # Mode distribution
        mode_counts = Counter(
            agent.state.mode for agent in self._agent_registry.values()
        )
        total = sum(mode_counts.values())
        metrics.mode_distribution = {
            mode: count / total for mode, count in mode_counts.items()
        } if total > 0 else {}
        
        # Cascade detection for each mode
        for mode in metrics.mode_distribution.keys():
            cascade, clusters = self.detect_cascade(mode)
            if cascade:
                metrics.cascade_active = True
                metrics.mode_clusters.extend(clusters)
            
            tipping = self.detect_tipping_point(mode)
            if tipping:
                metrics.tipping_point_reached = True
        
        return metrics
    
    def record_mode_snapshot(self) -> None:
        """Record current mode distribution for cascade detection."""
        mode_counts = Counter(
            agent.state.mode for agent in self._agent_registry.values()
        )
        self._mode_adoption_history.append(dict(mode_counts))
    
    def get_agent_centrality(self, agent_id: str, metric: str = 'degree') -> float:
        """
        Get agent's network centrality.
        
        Args:
            agent_id: Agent identifier
            metric: 'degree', 'betweenness', 'closeness', 'eigenvector'
        
        Returns:
            Centrality score
        """
        if agent_id not in self.G:
            return 0.0
        
        if metric == 'degree':
            return self.G.degree(agent_id) / (len(self.G) - 1)
        elif metric == 'betweenness':
            cent = nx.betweenness_centrality(self.G)
            return cent.get(agent_id, 0.0)
        elif metric == 'closeness':
            if nx.is_connected(self.G):
                cent = nx.closeness_centrality(self.G)
                return cent.get(agent_id, 0.0)
        elif metric == 'eigenvector':
            try:
                cent = nx.eigenvector_centrality(self.G, max_iter=100)
                return cent.get(agent_id, 0.0)
            except:
                return 0.0
        
        return 0.0
    
    # ========================================================================
    # Utilities
    # ========================================================================
    
    def get_neighbors(self, agent_id: str) -> List[str]:
        """Get list of agent's neighbors."""
        if agent_id in self.G:
            return list(self.G.neighbors(agent_id))
        return []
    
    def get_network_stats_summary(self) -> Dict[str, Any]:
        """Get summary statistics as dictionary."""
        metrics = self.get_network_metrics()
        return {
            'total_agents': metrics.total_agents,
            'total_ties': metrics.total_ties,
            'avg_degree': round(metrics.avg_degree, 2),
            'clustering': round(metrics.clustering_coefficient, 3),
            'density': round(metrics.network_density, 3),
            'strong_tie_ratio': round(metrics.strong_tie_ratio, 2),
            'mode_distribution': metrics.mode_distribution,
            'cascade_active': metrics.cascade_active,
            'tipping_point': metrics.tipping_point_reached,
        }
    
    def __repr__(self) -> str:
        return (f"SocialNetwork(agents={len(self.G)}, "
                f"ties={len(self.G.edges())}, "
                f"topology={self.topology})")