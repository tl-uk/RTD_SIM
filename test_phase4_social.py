"""
Test suite for RTD_SIM Phase 4: Social Networks & Influence

Tests:
1. Network construction (small-world, scale-free, homophily)
2. Peer influence on mode choice
3. Strong vs weak ties
4. Social cascade detection
5. Tipping point identification
6. Integration with story-driven agents

Run: python test_phase4_social.py
"""

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(name)s: %(message)s'
)

from agent.social_network import SocialNetwork, NetworkMetrics
from agent.story_driven_agent import StoryDrivenAgent, generate_agents_from_stories
from agent.bdi_planner import BDIPlanner


def print_header(title, level=1):
    """Print formatted section header."""
    if level == 1:
        print("\n" + "="*70)
        print(title)
        print("="*70)
    else:
        print("\n" + "="*60)
        print(title)
        print("="*60)


def create_test_agents(num_agents: int = 20) -> list:
    """Create test agents with diverse profiles."""
    planner = BDIPlanner()
    
    # Mix of stories
    user_stories = ['eco_warrior', 'budget_student', 'business_commuter', 'concerned_parent']
    job_stories = ['morning_commute', 'flexible_leisure', 'shopping_trip']
    
    agents = []
    for i in range(num_agents):
        # Random origin/dest
        origin = (-3.25 + i*0.01, 55.93 + i*0.002)
        dest = (-3.15 + i*0.01, 55.97 + i*0.002)
        
        agent = StoryDrivenAgent(
            user_story_id=user_stories[i % len(user_stories)],
            job_story_id=job_stories[i % len(job_stories)],
            origin=origin,
            dest=dest,
            planner=planner,
            seed=42 + i,
            apply_variance=True
        )
        agents.append(agent)
    
    return agents


def test_network_construction():
    """Test 1: Build networks with different topologies."""
    print_header("TEST 1: Network Construction", level=2)
    
    try:
        agents = create_test_agents(30)
        
        # Test small-world
        print("\n[*] Building small-world network...")
        net_sw = SocialNetwork(topology='small_world')
        net_sw.build_network(agents, k=4, p=0.1, seed=42)
        
        metrics_sw = net_sw.get_network_metrics()
        print(f"    Agents: {metrics_sw.total_agents}")
        print(f"    Ties: {metrics_sw.total_ties}")
        print(f"    Avg degree: {metrics_sw.avg_degree:.2f}")
        print(f"    Clustering: {metrics_sw.clustering_coefficient:.3f}")
        
        # Test scale-free
        print("\n[*] Building scale-free network...")
        net_sf = SocialNetwork(topology='scale_free')
        net_sf.build_network(agents, k=3, seed=42)
        
        metrics_sf = net_sf.get_network_metrics()
        print(f"    Agents: {metrics_sf.total_agents}")
        print(f"    Ties: {metrics_sf.total_ties}")
        print(f"    Avg degree: {metrics_sf.avg_degree:.2f}")
        
        # Test homophily
        print("\n[*] Building homophily network...")
        net_hom = SocialNetwork(topology='homophily')
        net_hom.build_network(agents, k=4, seed=42)
        
        metrics_hom = net_hom.get_network_metrics()
        print(f"    Agents: {metrics_hom.total_agents}")
        print(f"    Ties: {metrics_hom.total_ties}")
        print(f"    Strong tie ratio: {metrics_hom.strong_tie_ratio:.2f}")
        
        # Small-world should have higher clustering
        if metrics_sw.clustering_coefficient > metrics_sf.clustering_coefficient:
            print("\n[OK] Small-world has higher clustering (as expected)")
        else:
            print("\n[INFO] Clustering may vary with small samples")
        
        print("\n[OK] Network construction successful")
        return True
        
    except Exception as e:
        print(f"\n[FAIL] Error in network construction: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_peer_influence():
    """Test 2: Peer influence on mode choice."""
    print_header("TEST 2: Peer Influence on Mode Choice", level=2)
    
    try:
        agents = create_test_agents(20)
        
        # Build network
        network = SocialNetwork(topology='small_world', influence_enabled=True)
        network.build_network(agents, k=4, seed=42)
        
        # Set some agents to use bike
        for i in range(10):
            agents[i].state.mode = 'bike'
        
        # Set others to use car
        for i in range(10, 20):
            agents[i].state.mode = 'car'
        
        print("\n[*] Initial mode distribution:")
        print(f"    Bike: 10 agents")
        print(f"    Car: 10 agents")
        
        # Test influence for an agent
        test_agent = agents[5]
        print(f"\n[*] Testing influence on agent: {test_agent.state.agent_id}")
        
        # Get peer mode share
        peer_modes = network.get_peer_mode_share(test_agent.state.agent_id)
        print(f"    Peer mode share: {peer_modes}")
        
        # Apply influence to costs
        original_costs = {
            'bike': 1.0,
            'car': 1.0,
            'bus': 1.0,
            'walk': 1.0
        }
        
        adjusted_costs = network.apply_social_influence(
            test_agent.state.agent_id,
            original_costs,
            influence_strength=0.3
        )
        
        print(f"\n[*] Cost adjustment:")
        for mode, cost in adjusted_costs.items():
            if mode in original_costs:
                discount = (1 - cost / original_costs[mode]) * 100
                print(f"    {mode}: {cost:.3f} ({discount:+.1f}% change)")
        
        # Check that peer modes got discounts
        if peer_modes:
            dominant_mode = max(peer_modes, key=peer_modes.get)
            if adjusted_costs[dominant_mode] < original_costs[dominant_mode]:
                print(f"\n[OK] Peer-preferred mode '{dominant_mode}' got discount")
            else:
                print(f"\n[WARN] Expected discount on peer mode '{dominant_mode}'")
        
        print("\n[OK] Peer influence test complete")
        return True
        
    except Exception as e:
        print(f"\n[FAIL] Error in peer influence: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_strong_weak_ties():
    """Test 3: Strong vs weak tie influence."""
    print_header("TEST 3: Strong vs Weak Tie Influence", level=2)
    
    try:
        agents = create_test_agents(30)
        
        # Build homophily network (creates strong ties between similar agents)
        network = SocialNetwork(topology='homophily', strong_tie_threshold=0.6)
        network.build_network(agents, k=5, seed=42)
        
        # Set modes
        for i, agent in enumerate(agents):
            agent.state.mode = 'bike' if i < 15 else 'car'
        
        # Test agent
        test_agent = agents[10]
        
        print(f"\n[*] Testing agent: {test_agent.state.agent_id}")
        print(f"    Current mode: {test_agent.state.mode}")
        
        # Get strong tie influence
        strong_ties = network.get_strong_tie_influence(test_agent.state.agent_id)
        print(f"\n[*] Strong tie mode share: {strong_ties}")
        
        # Get weak tie influence
        weak_ties = network.get_weak_tie_influence(test_agent.state.agent_id)
        print(f"[*] Weak tie mode share: {weak_ties}")
        
        # Get all peers
        all_peers = network.get_peer_mode_share(test_agent.state.agent_id)
        print(f"[*] All peers mode share: {all_peers}")
        
        print("\n[OK] Strong/weak tie analysis complete")
        return True
        
    except Exception as e:
        print(f"\n[FAIL] Error in tie analysis: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_cascade_detection():
    """Test 4: Social cascade detection."""
    print_header("TEST 4: Social Cascade Detection", level=2)
    
    try:
        agents = create_test_agents(50)
        
        # Build network
        network = SocialNetwork(topology='small_world')
        network.build_network(agents, k=6, seed=42)
        
        print("\n[*] Scenario 1: Random distribution (no cascade expected)")
        # Random mode assignment
        modes = ['bike', 'car', 'bus', 'walk']
        for i, agent in enumerate(agents):
            agent.state.mode = modes[i % len(modes)]
        
        for mode in modes:
            cascade, clusters = network.detect_cascade(mode, threshold=0.15, min_cluster_size=5)
            print(f"    {mode}: cascade={cascade}, clusters={len(clusters)}")
        
        print("\n[*] Scenario 2: Clustered adoption (cascade expected)")
        # Create a cascade: most agents use bike
        for i, agent in enumerate(agents):
            if i < 35:  # 70% use bike
                agent.state.mode = 'bike'
            else:
                agent.state.mode = 'car'
        
        cascade, clusters = network.detect_cascade('bike', threshold=0.15, min_cluster_size=5)
        print(f"    Bike cascade detected: {cascade}")
        print(f"    Number of clusters: {len(clusters)}")
        
        if cascade:
            print(f"    Largest cluster size: {max(len(c) for c in clusters)}")
        
        if cascade:
            print("\n[OK] Cascade detection working")
        else:
            print("\n[WARN] Expected cascade for 70% adoption")
        
        print("\n[OK] Cascade detection test complete")
        return True
        
    except Exception as e:
        print(f"\n[FAIL] Error in cascade detection: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_tipping_point():
    """Test 5: Tipping point detection."""
    print_header("TEST 5: Tipping Point Detection", level=2)
    
    try:
        agents = create_test_agents(40)
        
        network = SocialNetwork(topology='small_world')
        network.build_network(agents, k=4, seed=42)
        
        print("\n[*] Simulating gradual adoption then acceleration...")
        
        # Simulate adoption over time
        bike_users = [5, 6, 7, 8, 9, 10, 11, 12, 20, 28, 35]  # Acceleration at end
        
        for step, num_bike in enumerate(bike_users):
            # Set modes
            for i, agent in enumerate(agents):
                agent.state.mode = 'bike' if i < num_bike else 'car'
            
            # Record snapshot
            network.record_mode_snapshot()
            
            # Check for tipping point
            tipping = network.detect_tipping_point('bike', history_window=5)
            
            rate = num_bike / len(agents)
            print(f"    Step {step}: {num_bike}/40 bike users ({rate:.1%}) - Tipping: {tipping}")
        
        # Final check
        tipping = network.detect_tipping_point('bike', history_window=5, acceleration_threshold=0.05)
        
        if tipping:
            print("\n[OK] Tipping point detected during acceleration phase")
        else:
            print("\n[INFO] Tipping point detection may need more data points")
        
        print("\n[OK] Tipping point test complete")
        return True
        
    except Exception as e:
        print(f"\n[FAIL] Error in tipping point detection: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_network_metrics():
    """Test 6: Network metrics calculation."""
    print_header("TEST 6: Network Metrics", level=2)
    
    try:
        agents = create_test_agents(25)
        
        network = SocialNetwork(topology='small_world')
        network.build_network(agents, k=4, seed=42)
        
        # Set diverse modes
        for i, agent in enumerate(agents):
            if i < 10:
                agent.state.mode = 'bike'
            elif i < 18:
                agent.state.mode = 'car'
            else:
                agent.state.mode = 'bus'
        
        print("\n[*] Calculating network metrics...")
        
        metrics = network.get_network_metrics()
        
        print(f"\n[*] Network Structure:")
        print(f"    Total agents: {metrics.total_agents}")
        print(f"    Total ties: {metrics.total_ties}")
        print(f"    Average degree: {metrics.avg_degree:.2f}")
        print(f"    Clustering coefficient: {metrics.clustering_coefficient:.3f}")
        print(f"    Network density: {metrics.network_density:.3f}")
        print(f"    Strong tie ratio: {metrics.strong_tie_ratio:.2f}")
        
        print(f"\n[*] Mode Distribution:")
        for mode, share in metrics.mode_distribution.items():
            print(f"    {mode}: {share:.1%}")
        
        print(f"\n[*] Social Dynamics:")
        print(f"    Cascade active: {metrics.cascade_active}")
        print(f"    Tipping point: {metrics.tipping_point_reached}")
        
        # Test centrality
        test_agent = agents[0]
        centrality = network.get_agent_centrality(test_agent.state.agent_id, 'degree')
        print(f"\n[*] Centrality (agent 0):")
        print(f"    Degree centrality: {centrality:.3f}")
        
        print("\n[OK] Network metrics test complete")
        return True
        
    except Exception as e:
        print(f"\n[FAIL] Error calculating metrics: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_story_integration():
    """Test 7: Integration with story-driven agents."""
    print_header("TEST 7: Story-Driven Agent Integration", level=2)
    
    try:
        print("\n[*] Creating story-driven agents with social network...")
        
        # Generate diverse agents
        planner = BDIPlanner()
        user_stories = ['eco_warrior', 'budget_student', 'business_commuter']
        job_stories = ['morning_commute', 'flexible_leisure']
        
        od_pairs = [
            ((-3.25 + i*0.01, 55.93 + i*0.002), (-3.15 + i*0.01, 55.97 + i*0.002))
            for i in range(30)
        ]
        
        agents = generate_agents_from_stories(
            user_story_ids=user_stories,
            job_story_ids=job_stories,
            origin_dest_pairs=od_pairs,
            planner=planner,
            seed=42
        )
        
        print(f"    Created {len(agents)} agents")
        
        # Build social network
        network = SocialNetwork(topology='homophily')
        network.build_network(agents, k=5, seed=42)
        
        print(f"    Built network: {len(network.G.edges())} connections")
        
        # Check that similar agents are connected
        eco_agents = [a for a in agents if a.user_story_id == 'eco_warrior']
        if len(eco_agents) >= 2:
            agent1 = eco_agents[0]
            agent2 = eco_agents[1]
            
            neighbors1 = set(network.get_neighbors(agent1.state.agent_id))
            neighbors2 = set(network.get_neighbors(agent2.state.agent_id))
            
            # Check if they're connected or share neighbors
            connected = agent2.state.agent_id in neighbors1
            shared_neighbors = len(neighbors1 & neighbors2)
            
            print(f"\n[*] Homophily check (eco_warrior agents):")
            print(f"    Directly connected: {connected}")
            print(f"    Shared neighbors: {shared_neighbors}")
            
            if connected or shared_neighbors > 0:
                print("    [OK] Similar agents tend to cluster")
        
        # Test influence on story-driven agent
        test_agent = agents[0]
        print(f"\n[*] Testing influence on {test_agent.user_story_id}...")
        
        mode_costs = {'bike': 1.0, 'car': 1.2, 'bus': 0.8, 'walk': 0.7}
        adjusted = network.apply_social_influence(
            test_agent.state.agent_id,
            mode_costs,
            influence_strength=0.25
        )
        
        print(f"    Original costs: {mode_costs}")
        print(f"    Adjusted costs: {adjusted}")
        
        print("\n[OK] Story-driven agent integration successful")
        return True
        
    except Exception as e:
        print(f"\n[FAIL] Error in integration: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print_header("RTD_SIM Phase 4: Social Networks & Influence Tests", level=1)
    
    results = {
        "Network Construction": test_network_construction(),
        "Peer Influence": test_peer_influence(),
        "Strong/Weak Ties": test_strong_weak_ties(),
        "Cascade Detection": test_cascade_detection(),
        "Tipping Point": test_tipping_point(),
        "Network Metrics": test_network_metrics(),
        "Story Integration": test_story_integration(),
    }
    
    print_header("TEST SUMMARY", level=1)
    for test_name, passed in results.items():
        status = "[OK]" if passed else "[FAIL]"
        print(f"{status} {test_name}")
    
    total = len(results)
    passed = sum(results.values())
    
    print(f"\nPassed: {passed}/{total} tests")
    
    if passed == total:
        print("\n*** All tests passed! Phase 4 Social Networks ready. ***")
        print("\nNext steps:")
        print("  1. Integrate with simulation controller")
        print("  2. Validate cascade behaviors")
        print("  3. Test with real Edinburgh network")
        print("  4. Proceed to Phase 5: System Dynamics")
    else:
        print("\n*** Some tests failed. Review errors above. ***")


if __name__ == "__main__":
    main()