import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from simulation.config.simulation_config import SimulationConfig
from simulation.config.system_dynamics_config import SystemDynamicsConfig
from simulation.simulation_runner import run_simulation

print("Testing SD in baseline mode...")

config = SimulationConfig(
    steps=10,  # Short test
    num_agents=50,
    place="Edinburgh, UK",
    use_osm=True,
    system_dynamics=SystemDynamicsConfig()  # Explicit SD
)

print("Running simulation...")
results = run_simulation(config)

print("\n" + "="*60)
print("DIAGNOSTIC RESULTS:")
print("="*60)

has_attr = hasattr(results, 'system_dynamics_history')
print(f"Has system_dynamics_history attribute: {has_attr}")

if has_attr:
    hist = results.system_dynamics_history
    print(f"Type: {type(hist)}")
    print(f"Length: {len(hist) if hist else 0}")
    
    if hist and len(hist) > 0:
        print("✅ SD IS WORKING!")
        print(f"Initial adoption: {hist[0]['ev_adoption']:.1%}")
        print(f"Final adoption: {hist[-1]['ev_adoption']:.1%}")
        print(f"Keys in history: {list(hist[0].keys())}")
    else:
        print("❌ SD history is empty!")
        print("→ Check if SD engine.update() is being called")
else:
    print("❌ No system_dynamics_history attribute!")
    print("→ Check if results.system_dynamics_history is set")

print("="*60)