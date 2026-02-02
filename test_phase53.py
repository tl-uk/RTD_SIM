from simulation.simulation_runner import run_simulation
from simulation.config.simulation_config import SimulationConfig

config = SimulationConfig(
    steps=50,
    num_agents=30,
    place='Edinburgh, UK',
    enable_analytics=True,
    track_journeys=True,
)

results = run_simulation(config)

# Check results
print(f"Journeys recorded: {len(results.journey_tracker.journeys)}")
print(f"Summary: {results.journey_tracker.get_summary_statistics()}")