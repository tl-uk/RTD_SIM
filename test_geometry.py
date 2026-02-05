# test_geometry.py
from simulation.simulation_runner import run_simulation
from simulation.config.simulation_config import SimulationConfig

config = SimulationConfig(
    steps=5,  # Short test
    num_agents=3,
    place='Edinburgh, UK',
)

results = run_simulation(config)

print("="*70)
print("GEOMETRY DETAIL CHECK")
print("="*70)

for agent in results.agents[:3]:
    route = agent.state.route
    print(f"\n{agent.state.agent_id} ({agent.state.mode}):")
    print(f"  Route points: {len(route) if route else 0}")
    
    if route and len(route) > 5:
        # Check spacing between points
        from simulation.spatial.coordinate_utils import haversine_km
        distances = []
        for i in range(min(10, len(route)-1)):
            dist = haversine_km(route[i], route[i+1])
            distances.append(dist * 1000)  # Convert to meters
        
        avg_spacing = sum(distances) / len(distances)
        print(f"  Avg point spacing: {avg_spacing:.1f}m")
        print(f"  First 3 points: {route[:3]}")
        
        if avg_spacing < 50:  # Less than 50m between points = good!
            print(f"  ✅ HIGH DETAIL (points every {avg_spacing:.0f}m)")
        else:
            print(f"  ⚠️  LOW DETAIL (points every {avg_spacing:.0f}m - may show straight lines)")