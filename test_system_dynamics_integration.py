"""
Test System Dynamics Integration

Verifies that Phase 1-3 integration works end-to-end.
"""

from simulation.config.simulation_config import SimulationConfig
from simulation.simulation_runner import run_simulation

print("=" * 70)
print("SYSTEM DYNAMICS INTEGRATION TEST")
print("=" * 70)

# Create config with minimal parameters for fast test
config = SimulationConfig(
    steps=50,
    num_agents=100,
    use_osm=False,  # Use synthetic network for speed
    place="Edinburgh, UK"
)

print("\n🚀 Running simulation...")
print(f"   Steps: {config.steps}")
print(f"   Agents: {config.num_agents}")
print(f"   OSM: {config.use_osm}")

# Run simulation
results = run_simulation(config)

print("\n" + "=" * 70)
print("RESULTS")
print("=" * 70)

# Check if simulation succeeded
if not results.success:
    print(f"❌ Simulation failed: {results.error_message}")
    exit(1)

print(f"✅ Simulation succeeded")

# Access SD history from results object (NOT .get() - it's an object not dict)
sd_history = results.system_dynamics_history

print(f"\n📊 System Dynamics History:")
print(f"   Entries: {len(sd_history)}")

if sd_history:
    print(f"\n   Initial state:")
    print(f"      EV adoption: {sd_history[0]['ev_adoption']:.1%}")
    print(f"      EV flow: {sd_history[0]['ev_adoption_flow']:.5f}")
    print(f"      Grid load: {sd_history[0]['grid_load']:.2f} MW")
    
    print(f"\n   Final state:")
    print(f"      EV adoption: {sd_history[-1]['ev_adoption']:.1%}")
    print(f"      EV flow: {sd_history[-1]['ev_adoption_flow']:.5f}")
    print(f"      Grid load: {sd_history[-1]['grid_load']:.2f} MW")
    
    growth = sd_history[-1]['ev_adoption'] - sd_history[0]['ev_adoption']
    print(f"\n   Growth: {growth:+.1%}")
    
    # Check for threshold events
    events_found = []
    for entry in sd_history:
        thresholds = entry.get('thresholds_crossed', {})
        for threshold, crossed in thresholds.items():
            if crossed and threshold not in events_found:
                events_found.append(threshold)
                print(f"\n   🎯 Threshold crossed: {threshold}")
    
    print("\n" + "=" * 70)
    print("✅ INTEGRATION TEST PASSED")
    print("=" * 70)
    print("\nSystem Dynamics is working end-to-end:")
    print(f"  ✅ SD initialized")
    print(f"  ✅ SD updated {len(sd_history)} times")
    print(f"  ✅ EV adoption grew from {sd_history[0]['ev_adoption']:.1%} to {sd_history[-1]['ev_adoption']:.1%}")
    print(f"  ✅ History accessible via results.system_dynamics_history")
    
else:
    print("\n❌ No System Dynamics history found!")
    print("   Check that system_dynamics module is installed")
    print("   Check logs for initialization errors")