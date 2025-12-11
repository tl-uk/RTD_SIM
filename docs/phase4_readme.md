# RTD_SIM Phase 4: Social Networks & Influence

## Overview

Phase 4 adds **social network influence** to agent decision-making, enabling:
- Peer influence on mode choice
- Social cascades & tipping points
- Strong vs weak tie effects
- Homophily-based network formation
- Cascade detection mechanisms

## Quick Start

### 1. Run Tests

```bash
python test_phase4_social.py
```

Expected: **7/7 tests passing**

### 2. Basic Usage

```python
from agent.social_network import SocialNetwork
from agent.story_driven_agent import generate_agents_from_stories

# Create agents
agents = generate_agents_from_stories(...)

# Build social network
network = SocialNetwork(topology='small_world')
network.build_network(agents, k=4, p=0.1, seed=42)

# Apply peer influence
adjusted_costs = network.apply_social_influence(
    agent_id='agent_123',
    mode_costs={'bike': 1.0, 'car': 1.2, 'bus': 0.8},
    influence_strength=0.3
)
```

---

## Network Topologies

### Small-World (Watts-Strogatz)

**Best for:** Local communities with occasional long-distance ties

```python
network = SocialNetwork(topology='small_world')
network.build_network(agents, k=4, p=0.1)
```

**Properties:**
- High clustering (friends-of-friends are friends)
- Short average path length
- Resembles real-world social networks

### Scale-Free (Barabási-Albert)

**Best for:** Networks with influential hubs (e.g., social media)

```python
network = SocialNetwork(topology='scale_free')
network.build_network(agents, k=3)
```

**Properties:**
- Power-law degree distribution
- Few highly connected "influencers"
- Robust to random failures

### Homophily

**Best for:** Realistic social clustering by similarity

```python
network = SocialNetwork(topology='homophily')
network.build_network(agents, k=5)
```

**Properties:**
- Similar agents connect preferentially
- Based on desire similarity (eco warriors connect with eco warriors)
- Most realistic for transport behavior

### Random (Erdős-Rényi)

**Best for:** Baseline comparison

```python
network = SocialNetwork(topology='random')
network.build_network(agents, k=4)
```

---

## Social Influence Mechanisms

### Peer Influence on Costs

Peers reduce the perceived "cost" of modes they use:

```python
# Get what modes your friends use
peer_modes = network.get_peer_mode_share(agent_id)
# {'bike': 0.6, 'car': 0.3, 'bus': 0.1}

# Adjust costs based on peer adoption
original = {'bike': 1.0, 'car': 1.0, 'bus': 1.0}
adjusted = network.apply_social_influence(
    agent_id, 
    original,
    influence_strength=0.3  # 30% influence
)
# {'bike': 0.82, 'car': 0.91, 'bus': 0.97}
# Bike gets 18% discount because 60% of peers use it
```

### Strong vs Weak Ties

Research shows different tie types have different effects:

```python
# Strong ties (family, close friends) → influence car ownership
strong_influence = network.get_strong_tie_influence(agent_id)

# Weak ties (acquaintances) → spread info about public transit
weak_influence = network.get_weak_tie_influence(agent_id)
```

**Implementation:**
- Tie strength based on agent similarity (desires, stories)
- Strong tie threshold: default 0.6
- Geographic proximity increases tie strength

---

## Cascade Detection

### What is a Cascade?

A **social cascade** occurs when behavior spreads rapidly through a network due to peer influence.

Example: "Everyone I know is switching to e-bikes, maybe I should too!"

### Detection

```python
# Check if bike adoption is cascading
cascade_detected, clusters = network.detect_cascade(
    mode='bike',
    threshold=0.2,      # 20% minimum adoption
    min_cluster_size=5  # At least 5 connected adopters
)

if cascade_detected:
    print(f"Bike cascade! {len(clusters)} clusters found")
    print(f"Largest cluster: {max(len(c) for c in clusters)} agents")
```

### Real Example

```
Step 0: 5% bike users → No cascade
Step 5: 15% bike users → No cascade
Step 10: 35% bike users → CASCADE DETECTED!
  - Cluster 1: 12 connected agents
  - Cluster 2: 8 connected agents
```

---

## Tipping Points

### What is a Tipping Point?

The **tipping point** is when adoption suddenly accelerates - the moment a behavior goes from gradual to viral.

### Detection

```python
# Record mode distribution over time
for step in range(100):
    # ... simulation step ...
    network.record_mode_snapshot()

# Detect acceleration in adoption
tipping = network.detect_tipping_point(
    mode='bike',
    history_window=10,
    acceleration_threshold=0.05  # 5% acceleration
)

if tipping:
    print("Tipping point reached! Bike adoption accelerating")
```

### Classic Example

```
Weeks 1-10: Linear growth (5% → 15%)
Week 11-12: TIPPING POINT
Weeks 13-20: Exponential growth (15% → 60%)
```

---

## Network Analysis

### Basic Metrics

```python
metrics = network.get_network_metrics()

print(f"Agents: {metrics.total_agents}")
print(f"Connections: {metrics.total_ties}")
print(f"Avg connections/agent: {metrics.avg_degree:.1f}")
print(f"Clustering: {metrics.clustering_coefficient:.3f}")
```

### Mode Distribution

```python
metrics = network.get_network_metrics()

for mode, share in metrics.mode_distribution.items():
    print(f"{mode}: {share:.1%}")
```

Output:
```
bike: 45.2%
car: 32.1%
bus: 15.3%
walk: 7.4%
```

### Agent Centrality

Find influential agents:

```python
# Who has most connections?
centrality = network.get_agent_centrality(agent_id, metric='degree')

# Who is most "between" others?
betweenness = network.get_agent_centrality(agent_id, metric='betweenness')
```

---

## Integration with Story-Driven Agents

### Automatic Similarity Clustering

When using `homophily` topology with story-driven agents:

```python
# Agents with similar desires automatically cluster
agents = generate_agents_from_stories(
    user_story_ids=['eco_warrior', 'budget_student', 'business_commuter'],
    ...
)

network = SocialNetwork(topology='homophily')
network.build_network(agents)

# Result: eco_warriors connect with eco_warriors
#         students connect with students
#         business travelers connect with business travelers
```

### Influence Matches Personality

```python
# Eco warrior with many eco warrior friends
eco_agent = agents[0]  # eco_warrior

peer_modes = network.get_peer_mode_share(eco_agent.state.agent_id)
# Result: {'bike': 0.8, 'bus': 0.15, 'walk': 0.05}
# Friends mostly use sustainable modes!

# Business commuter with business friends
business_agent = agents[10]  # business_commuter

peer_modes = network.get_peer_mode_share(business_agent.state.agent_id)
# Result: {'car': 0.7, 'taxi': 0.2, 'train': 0.1}
# Friends mostly use fast, comfortable modes!
```

---

## Simulation Integration

### Simple Integration

```python
from simulation.controller import SimulationController

# Create agents + network
agents = generate_agents_from_stories(...)
network = SocialNetwork(topology='small_world')
network.build_network(agents)

# In simulation loop:
for step in range(100):
    for agent in agents:
        # Get planner costs
        mode_costs = planner.calculate_costs(agent, env)
        
        # Apply social influence
        adjusted_costs = network.apply_social_influence(
            agent.state.agent_id,
            mode_costs,
            influence_strength=0.2
        )
        
        # Agent chooses mode with adjusted costs
        chosen_mode = min(adjusted_costs, key=adjusted_costs.get)
        agent.state.mode = chosen_mode
    
    # Record for cascade detection
    network.record_mode_snapshot()
    
    # Check for cascades
    metrics = network.get_network_metrics()
    if metrics.cascade_active:
        print(f"Step {step}: CASCADE DETECTED!")
```

### Advanced: Dynamic Networks

Networks can evolve over time:

```python
# Agents form new ties based on mode similarity
if step % 10 == 0:  # Every 10 steps
    for agent in agents:
        # Find others using same mode
        same_mode_agents = [
            a for a in agents 
            if a.state.mode == agent.state.mode 
            and a != agent
        ]
        
        # Form new connection with probability
        if same_mode_agents and random.random() < 0.1:
            new_friend = random.choice(same_mode_agents)
            network.G.add_edge(
                agent.state.agent_id,
                new_friend.state.agent_id
            )
```

---

## Research Applications

### Experiment 1: Influence Strength

Test different influence levels:

```python
for strength in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]:
    network = SocialNetwork(...)
    # Run simulation with this influence strength
    # Measure: time to 50% bike adoption
```

**Research Question:** How much do peers affect mode choice?

### Experiment 2: Network Topology

Compare cascade behavior across topologies:

```python
topologies = ['small_world', 'scale_free', 'random', 'homophily']

for topo in topologies:
    network = SocialNetwork(topology=topo)
    # Run simulation
    # Measure: cascade frequency, tipping point timing
```

**Research Question:** Does network structure affect sustainable transport adoption?

### Experiment 3: Policy Interventions

Test policies with social influence:

```python
# Baseline: No intervention
baseline_adoption = run_simulation(network, policy=None)

# Policy: Subsidize e-bikes for 10% of agents
network.apply_subsidy(num_agents=100, mode='ebike')
policy_adoption = run_simulation(network, policy='ebike_subsidy')

# Compare cascade behavior
print(f"Baseline: {baseline_adoption[-1]:.1%} adoption")
print(f"With policy: {policy_adoption[-1]:.1%} adoption")
```

**Research Question:** Can targeting influential agents amplify policy impact?

---

## Validation

### Modal Split Comparison

```python
# Get Edinburgh survey data
edinburgh_modal_split = {
    'car': 0.45,
    'bus': 0.12,
    'walk': 0.25,
    'bike': 0.03,
    'train': 0.15
}

# Get simulation results
metrics = network.get_network_metrics()
simulated_split = metrics.mode_distribution

# Compare
for mode in edinburgh_modal_split:
    real = edinburgh_modal_split[mode]
    sim = simulated_split.get(mode, 0)
    diff = abs(real - sim)
    print(f"{mode}: Real={real:.1%}, Sim={sim:.1%}, Diff={diff:.1%}")
```

### Cascade Validation

Look for evidence of real-world transport cascades:
- E-bike adoption in Netherlands (2010-2020)
- Boris Bikes in London (2010-2012)
- E-scooter adoption in Paris (2018-2020)

---

## Performance

### Network Size Limits

- **< 100 agents**: All metrics fast
- **100-1000 agents**: Most metrics OK, disable path length calculation
- **1000-10000 agents**: Use sparse networks, limited analysis
- **> 10000 agents**: Requires optimization (not Phase 4 scope)

### Optimization Tips

```python
# For large networks (>500 agents)
network = SocialNetwork(topology='small_world')
network.build_network(agents, k=4)  # Lower k = fewer edges

# Skip expensive calculations
metrics = network.get_network_metrics()
# avg_path_length automatically skipped for large networks
```

---

## Troubleshooting

### NetworkX Not Found

```
ImportError: NetworkX required
```

**Solution:** `pip install networkx`

### Empty Network

```
No agents provided to build network
```

**Solution:** Create agents first:
```python
agents = generate_agents_from_stories(...)
network.build_network(agents)
```

### No Influence Effect

**Check:**
1. `influence_enabled=True` in network constructor
2. `influence_strength > 0` in apply_social_influence()
3. Agents actually have different modes

---

## Next: Phase 5

With social networks complete, Phase 5 will add:
- **System Dynamics**: Carbon budget, feedback loops
- **Streaming SD**: Real-time stock/flow updates
- **MQTT Integration**: Live data feeds
- **Policy Injection**: Test interventions dynamically

**Timeline:** Phase 5 = Months 7-10

---

## References

Key research papers that informed this implementation:
- Kowald et al. (2015) - Social networks in travel behavior
- Han et al. (2011) - Agent-based social influence
- Chen et al. (2014) - Attitude diffusion in sustainable transport
- Salazar-Serna et al. (2023) - Social network impact on mode choice

---

## Success Criteria ✓

- [x] Multiple network topologies implemented
- [x] Peer influence mechanism working
- [x] Strong/weak tie distinction
- [x] Cascade detection algorithm
- [x] Tipping point identification
- [x] Integration with story-driven agents
- [x] Network analysis metrics
- [x] All tests passing (7/7)

**Phase 4 Complete! Ready for Phase 5.**
