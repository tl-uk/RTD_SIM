# social_network.py (new file)
import networkx as nx

class SocialNetwork:
    def __init__(self, agents: List[CognitiveAgent]):
        self.G = nx.Graph()
        self._build_network(agents)
    
    def _build_network(self, agents: List[CognitiveAgent]):
        """Create social connections (e.g., small-world network)."""
        self.G = nx.watts_strogatz_graph(len(agents), k=4, p=0.1)
        # Map node IDs to agent IDs
        for i, agent in enumerate(agents):
            self.G.nodes[i]['agent_id'] = agent.state.agent_id
    
    def get_peer_mode_share(self, agent_id: str, all_agents: List[CognitiveAgent]) -> dict:
        """Get mode share among agent's social connections."""
        # Find agent's neighbors
        node = [n for n, d in self.G.nodes(data=True) 
                if d['agent_id'] == agent_id][0]
        neighbors = list(self.G.neighbors(node))
        
        # Count modes among neighbors
        neighbor_ids = [self.G.nodes[n]['agent_id'] for n in neighbors]
        neighbor_agents = [a for a in all_agents if a.state.agent_id in neighbor_ids]
        modes = [a.state.mode for a in neighbor_agents]
        
        from collections import Counter
        return Counter(modes)
    
    def apply_social_influence(self, costs: dict, peer_modes: dict, 
                              influence_strength: float = 0.2) -> dict:
        """Reduce cost of modes used by peers."""
        adjusted = costs.copy()
        total_peers = sum(peer_modes.values())
        
        for mode, count in peer_modes.items():
            if mode in adjusted:
                peer_share = count / total_peers
                adjusted[mode] *= (1.0 - influence_strength * peer_share)
        
        return adjusted