from simulation.config.simulation_config import SimulationConfig
from simulation.simulation_runner import run_simulation

config = SimulationConfig(
    steps=50,
    num_agents=100,
    use_osm=False  # Use synthetic network for speed
)

results = run_simulation(config)

# Check SD history
sd_history = results.get('system_dynamics_history', [])
print(f"SD history entries: {len(sd_history)}")

if sd_history:
    print(f"Initial EV: {sd_history[0]['ev_adoption']:.1%}")
    print(f"Final EV: {sd_history[-1]['ev_adoption']:.1%}")
    print(f"Growth observed: {sd_history[-1]['ev_adoption'] > sd_history[0]['ev_adoption']}")