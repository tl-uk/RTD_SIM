"""
Headless Simulation Runner - Phase 5.3
Run multiple simulations without UI and generate reports

Usage:
    python headless_simulation_runner.py --scenarios baseline,aggressive,conservative --steps 200
    python headless_simulation_runner.py --scenarios all --steps 150
    python headless_simulation_runner.py --scenarios baseline --steps 100
"""

import sys
from pathlib import Path
import argparse
import json
import csv
from datetime import datetime
from typing import Dict, List, Any

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulation.simulation_runner import run_simulation
from simulation.config.simulation_config import SimulationConfig
from simulation.config.system_dynamics_config import SystemDynamicsConfig


# ============================================================================
# SCENARIO DEFINITIONS
# ============================================================================

def get_scenario_configs() -> Dict[str, SimulationConfig]:
    """
    Define test scenarios with different SD parameters.
    
    Returns:
        Dictionary of scenario_name -> SimulationConfig
    """
    
    scenarios = {}
    
    # Baseline: Default parameters
    scenarios['baseline'] = SimulationConfig(
        steps=100,
        num_agents=100,
        place="Edinburgh, UK",
        use_osm=True,
        enable_infrastructure=True,
        num_chargers=50,
        grid_capacity_mw=50.0,
        system_dynamics=SystemDynamicsConfig(
            ev_growth_rate_r=0.05,
            ev_carrying_capacity_K=0.80,
            infrastructure_feedback_strength=0.02,
            social_influence_strength=0.03,
        )
    )
    
    # Aggressive: Fast growth, high capacity
    scenarios['aggressive'] = SimulationConfig(
        steps=100,
        num_agents=100,
        place="Edinburgh, UK",
        use_osm=True,
        enable_infrastructure=True,
        num_chargers=100,
        grid_capacity_mw=100.0,
        system_dynamics=SystemDynamicsConfig(
            ev_growth_rate_r=0.10,
            ev_carrying_capacity_K=0.90,
            infrastructure_feedback_strength=0.05,
            social_influence_strength=0.06,
        )
    )
    
    # Conservative: Slow growth, low capacity
    scenarios['conservative'] = SimulationConfig(
        steps=100,
        num_agents=100,
        place="Edinburgh, UK",
        use_osm=True,
        enable_infrastructure=True,
        num_chargers=30,
        grid_capacity_mw=30.0,
        system_dynamics=SystemDynamicsConfig(
            ev_growth_rate_r=0.02,
            ev_carrying_capacity_K=0.60,
            infrastructure_feedback_strength=0.01,
            social_influence_strength=0.02,
        )
    )
    
    # Social-driven: High social influence, normal infrastructure
    scenarios['social_driven'] = SimulationConfig(
        steps=100,
        num_agents=100,
        place="Edinburgh, UK",
        use_osm=True,
        enable_infrastructure=True,
        num_chargers=50,
        grid_capacity_mw=50.0,
        system_dynamics=SystemDynamicsConfig(
            ev_growth_rate_r=0.05,
            ev_carrying_capacity_K=0.80,
            infrastructure_feedback_strength=0.01,
            social_influence_strength=0.08,  # Very high!
        )
    )
    
    # Infrastructure-driven: High infrastructure, low social
    scenarios['infrastructure_driven'] = SimulationConfig(
        steps=100,
        num_agents=100,
        place="Edinburgh, UK",
        use_osm=True,
        enable_infrastructure=True,
        num_chargers=150,
        grid_capacity_mw=80.0,
        system_dynamics=SystemDynamicsConfig(
            ev_growth_rate_r=0.05,
            ev_carrying_capacity_K=0.80,
            infrastructure_feedback_strength=0.08,  # Very high!
            social_influence_strength=0.01,
        )
    )
    
    return scenarios


# ============================================================================
# REPORT GENERATION
# ============================================================================

def extract_sd_metrics(results) -> Dict[str, Any]:
    """
    Extract key System Dynamics metrics from simulation results.
    
    Args:
        results: SimulationResults object
    
    Returns:
        Dictionary of metrics
    """
    
    sd_history = results.system_dynamics_history
    
    if not sd_history or len(sd_history) == 0:
        return {
            'sd_enabled': False,
            'error': 'No SD data available'
        }
    
    # Extract key metrics
    initial = sd_history[0]
    final = sd_history[-1]
    
    # Find when tipping point was crossed
    tipping_point_step = None
    for i, h in enumerate(sd_history):
        if h.get('thresholds_crossed', {}).get('adoption_tipping_point', False):
            tipping_point_step = i
            break
    
    # Calculate flow statistics
    flows = [h['ev_adoption_flow'] for h in sd_history]
    avg_flow = sum(flows) / len(flows)
    max_flow = max(flows)
    min_flow = min(flows)
    
    # Calculate adoption growth
    adoptions = [h['ev_adoption'] for h in sd_history]
    initial_adoption = adoptions[0]
    final_adoption = adoptions[-1]
    peak_adoption = max(adoptions)
    
    # Find step where adoption peaked
    peak_step = adoptions.index(peak_adoption)
    
    # Calculate flow components at final step
    final_adoption_frac = final['ev_adoption']
    r = final.get('ev_growth_rate_r', 0.05)
    K = final.get('ev_carrying_capacity_K', 0.80)
    
    logistic_term = r * final_adoption_frac * (1 - final_adoption_frac / K)
    infrastructure_term = 0.02 * final_adoption_frac  # Approximate
    social_term = 0.03 * final_adoption_frac  # Approximate
    
    return {
        'sd_enabled': True,
        'timesteps': len(sd_history),
        
        # Adoption metrics
        'initial_adoption_pct': initial_adoption * 100,
        'final_adoption_pct': final_adoption * 100,
        'peak_adoption_pct': peak_adoption * 100,
        'adoption_growth_pct': (final_adoption - initial_adoption) * 100,
        'peak_step': peak_step,
        
        # Flow metrics
        'initial_flow': flows[0],
        'final_flow': flows[-1],
        'avg_flow': avg_flow,
        'max_flow': max_flow,
        'min_flow': min_flow,
        
        # Flow decomposition (final step)
        'logistic_component': logistic_term,
        'infrastructure_component': infrastructure_term,
        'social_component': social_term,
        
        # Threshold events
        'tipping_point_crossed': tipping_point_step is not None,
        'tipping_point_step': tipping_point_step if tipping_point_step else -1,
        
        # Parameters
        'growth_rate_r': r,
        'carrying_capacity_K': K,
        
        # Grid metrics
        'final_grid_load_mw': final.get('grid_load', 0),
        'final_grid_utilization_pct': final.get('grid_utilization', 0) * 100,
    }


def extract_general_metrics(results) -> Dict[str, Any]:
    """
    Extract general simulation metrics.
    
    Args:
        results: SimulationResults object
    
    Returns:
        Dictionary of metrics
    """
    
    # Mode distribution from final step
    if results.time_series and len(results.time_series) > 0:
        final_step = results.time_series[-1] if isinstance(results.time_series, list) else results.time_series.get_timestep(len(results.time_series) - 1)
        agent_states = final_step.get('agent_states', [])
        
        # Count modes
        mode_counts = {}
        for agent in agent_states:
            mode = agent.get('mode', 'unknown')
            mode_counts[mode] = mode_counts.get(mode, 0) + 1
        
        total_agents = len(agent_states)
        
        # EV modes
        ev_modes = ['ev', 'van_electric', 'truck_electric', 'hgv_electric']
        ev_count = sum(mode_counts.get(mode, 0) for mode in ev_modes)
        ev_adoption_pct = (ev_count / total_agents * 100) if total_agents > 0 else 0
        
    else:
        mode_counts = {}
        total_agents = 0
        ev_adoption_pct = 0
    
    # Get grid metrics safely
    grid_capacity_mw = 0
    if results.infrastructure and hasattr(results.infrastructure, 'grid'):
        grid_metrics = results.infrastructure.grid.get_metrics()
        grid_capacity_mw = grid_metrics.get('grid_capacity_mw', 0)
    
    return {
        'success': results.success,
        'total_agents': total_agents,
        'total_steps': results.total_steps if hasattr(results, 'total_steps') else 0,
        'journeys_recorded': len(results.adoption_history.get('walk', [])) if results.adoption_history else 0,
        'cascades_detected': len(results.cascade_events) if results.cascade_events else 0,
        
        # Final mode distribution
        'mode_counts': mode_counts,
        'ev_adoption_from_agents_pct': ev_adoption_pct,
        
        # Infrastructure
        'grid_capacity_mw': grid_capacity_mw,
        'num_chargers': len(results.infrastructure.chargers) if results.infrastructure else 0,
    }


def generate_text_report(scenario_name: str, config: SimulationConfig, 
                        general_metrics: Dict, sd_metrics: Dict) -> str:
    """
    Generate human-readable text report.
    
    Returns:
        Report as string
    """
    
    report = []
    report.append("=" * 80)
    report.append(f"SIMULATION REPORT: {scenario_name.upper()}")
    report.append("=" * 80)
    report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("")
    
    # Configuration
    report.append("CONFIGURATION")
    report.append("-" * 80)
    report.append(f"Steps:             {config.steps}")
    report.append(f"Agents:            {config.num_agents}")
    report.append(f"Location:          {config.place}")
    report.append(f"Grid Capacity:     {config.grid_capacity_mw:.1f} MW")
    report.append(f"Chargers:          {config.num_chargers}")
    report.append("")
    
    # System Dynamics Parameters
    if sd_metrics['sd_enabled']:
        report.append("SYSTEM DYNAMICS PARAMETERS")
        report.append("-" * 80)
        report.append(f"Growth Rate (r):         {sd_metrics['growth_rate_r']:.3f}")
        report.append(f"Carrying Capacity (K):   {sd_metrics['carrying_capacity_K']:.1%}")
        report.append(f"Infrastructure Feedback: {sd_metrics['infrastructure_component']:.5f}")
        report.append(f"Social Influence:        {sd_metrics['social_component']:.5f}")
        report.append("")
    
    # General Results
    report.append("GENERAL RESULTS")
    report.append("-" * 80)
    report.append(f"Success:           {'✅ Yes' if general_metrics['success'] else '❌ No'}")
    report.append(f"Total Agents:      {general_metrics['total_agents']}")
    report.append(f"Cascades Detected: {general_metrics['cascades_detected']}")
    report.append(f"EV Adoption (Agents): {general_metrics['ev_adoption_from_agents_pct']:.1f}%")
    report.append("")
    
    # System Dynamics Results
    if sd_metrics['sd_enabled']:
        report.append("SYSTEM DYNAMICS RESULTS")
        report.append("-" * 80)
        report.append(f"Initial Adoption:  {sd_metrics['initial_adoption_pct']:.1f}%")
        report.append(f"Final Adoption:    {sd_metrics['final_adoption_pct']:.1f}%")
        report.append(f"Peak Adoption:     {sd_metrics['peak_adoption_pct']:.1f}% (step {sd_metrics['peak_step']})")
        report.append(f"Growth:            {sd_metrics['adoption_growth_pct']:+.1f}%")
        report.append("")
        
        report.append(f"Average Flow:      {sd_metrics['avg_flow']:.5f}")
        report.append(f"Max Flow:          {sd_metrics['max_flow']:.5f}")
        report.append(f"Final Flow:        {sd_metrics['final_flow']:.5f}")
        report.append("")
        
        report.append("FLOW DECOMPOSITION (Final Step)")
        report.append(f"  Logistic:        {sd_metrics['logistic_component']:.5f}")
        report.append(f"  Infrastructure:  {sd_metrics['infrastructure_component']:.5f}")
        report.append(f"  Social:          {sd_metrics['social_component']:.5f}")
        report.append("")
        
        if sd_metrics['tipping_point_crossed']:
            report.append(f"🎯 Tipping Point:  CROSSED at step {sd_metrics['tipping_point_step']}")
        else:
            report.append("🎯 Tipping Point:  NOT REACHED")
        report.append("")
        
        report.append(f"Grid Load:         {sd_metrics['final_grid_load_mw']:.1f} MW")
        report.append(f"Grid Utilization:  {sd_metrics['final_grid_utilization_pct']:.1f}%")
        report.append("")
    
    # Mode Distribution
    report.append("MODE DISTRIBUTION (Final Step)")
    report.append("-" * 80)
    for mode, count in sorted(general_metrics['mode_counts'].items(), key=lambda x: -x[1]):
        pct = count / general_metrics['total_agents'] * 100 if general_metrics['total_agents'] > 0 else 0
        report.append(f"  {mode:20s} {count:4d} ({pct:5.1f}%)")
    report.append("")
    
    report.append("=" * 80)
    
    return "\n".join(report)


def generate_csv_report(results_list: List[Dict]) -> str:
    """
    Generate CSV report from multiple simulation results.
    
    Args:
        results_list: List of dicts with keys: scenario_name, general_metrics, sd_metrics
    
    Returns:
        CSV content as string
    """
    
    if not results_list:
        return ""
    
    # Define CSV columns
    columns = [
        'scenario_name',
        'success',
        'total_agents',
        'total_steps',
        'cascades',
        
        # SD metrics
        'initial_adoption_pct',
        'final_adoption_pct',
        'adoption_growth_pct',
        'peak_adoption_pct',
        'peak_step',
        
        'avg_flow',
        'max_flow',
        'final_flow',
        
        'logistic_component',
        'infrastructure_component',
        'social_component',
        
        'tipping_point_crossed',
        'tipping_point_step',
        
        'growth_rate_r',
        'carrying_capacity_K',
        
        'final_grid_load_mw',
        'final_grid_utilization_pct',
        
        # Agent-based metrics
        'ev_adoption_from_agents_pct',
    ]
    
    # Build CSV rows
    rows = []
    for result in results_list:
        scenario = result['scenario_name']
        general = result['general_metrics']
        sd = result['sd_metrics']
        
        if not sd['sd_enabled']:
            continue  # Skip scenarios without SD data
        
        row = {
            'scenario_name': scenario,
            'success': general['success'],
            'total_agents': general['total_agents'],
            'total_steps': general.get('total_steps', 0),
            'cascades': general['cascades_detected'],
            
            'initial_adoption_pct': sd['initial_adoption_pct'],
            'final_adoption_pct': sd['final_adoption_pct'],
            'adoption_growth_pct': sd['adoption_growth_pct'],
            'peak_adoption_pct': sd['peak_adoption_pct'],
            'peak_step': sd['peak_step'],
            
            'avg_flow': sd['avg_flow'],
            'max_flow': sd['max_flow'],
            'final_flow': sd['final_flow'],
            
            'logistic_component': sd['logistic_component'],
            'infrastructure_component': sd['infrastructure_component'],
            'social_component': sd['social_component'],
            
            'tipping_point_crossed': sd['tipping_point_crossed'],
            'tipping_point_step': sd['tipping_point_step'],
            
            'growth_rate_r': sd['growth_rate_r'],
            'carrying_capacity_K': sd['carrying_capacity_K'],
            
            'final_grid_load_mw': sd['final_grid_load_mw'],
            'final_grid_utilization_pct': sd['final_grid_utilization_pct'],
            
            'ev_adoption_from_agents_pct': general['ev_adoption_from_agents_pct'],
        }
        
        rows.append(row)
    
    # Write CSV
    output = []
    output.append(','.join(columns))
    
    for row in rows:
        values = [str(row.get(col, '')) for col in columns]
        output.append(','.join(values))
    
    return '\n'.join(output)


# ============================================================================
# MAIN RUNNER
# ============================================================================

def run_headless_tests(scenario_names: List[str], steps: int = 100, 
                       output_dir: Path = Path('./reports')) -> None:
    """
    Run multiple simulations headlessly and generate reports.
    
    Args:
        scenario_names: List of scenario names to run
        steps: Number of simulation steps
        output_dir: Directory to save reports
    """
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Get scenario configurations
    all_scenarios = get_scenario_configs()
    
    # Override steps if specified
    for config in all_scenarios.values():
        config.steps = steps
    
    # Filter requested scenarios
    scenarios_to_run = {
        name: config for name, config in all_scenarios.items() 
        if name in scenario_names
    }
    
    if not scenarios_to_run:
        print(f"❌ No valid scenarios found. Available: {list(all_scenarios.keys())}")
        return
    
    print(f"🚀 Running {len(scenarios_to_run)} scenario(s) with {steps} steps each")
    print("=" * 80)
    
    results_list = []
    
    for scenario_name, config in scenarios_to_run.items():
        print(f"\n📊 Running scenario: {scenario_name}")
        print("-" * 80)
        
        try:
            # Run simulation
            results = run_simulation(config)
            
            if not results.success:
                print(f"❌ Simulation failed: {results.error_message}")
                continue
            
            print(f"✅ Simulation complete")
            
            # Extract metrics
            general_metrics = extract_general_metrics(results)
            sd_metrics = extract_sd_metrics(results)
            
            # Store for CSV
            results_list.append({
                'scenario_name': scenario_name,
                'config': config,
                'general_metrics': general_metrics,
                'sd_metrics': sd_metrics,
            })
            
            # Generate text report
            text_report = generate_text_report(scenario_name, config, general_metrics, sd_metrics)
            
            # Save text report
            report_file = output_dir / f"{scenario_name}_report.txt"
            with open(report_file, 'w') as f:
                f.write(text_report)
            
            print(f"📄 Report saved: {report_file}")
            
            # Print summary
            if sd_metrics['sd_enabled']:
                print(f"   Initial adoption: {sd_metrics['initial_adoption_pct']:.1f}%")
                print(f"   Final adoption:   {sd_metrics['final_adoption_pct']:.1f}%")
                print(f"   Growth:           {sd_metrics['adoption_growth_pct']:+.1f}%")
                if sd_metrics['tipping_point_crossed']:
                    print(f"   🎯 Tipping point: Crossed at step {sd_metrics['tipping_point_step']}")
            
        except Exception as e:
            print(f"❌ Error running scenario: {e}")
            import traceback
            traceback.print_exc()
    
    # Generate combined CSV report
    if results_list:
        print("\n" + "=" * 80)
        print("📊 Generating combined CSV report")
        
        csv_content = generate_csv_report(results_list)
        csv_file = output_dir / f"simulation_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        with open(csv_file, 'w') as f:
            f.write(csv_content)
        
        print(f"📄 CSV report saved: {csv_file}")
        
        # Print comparison table
        print("\n" + "=" * 80)
        print("SCENARIO COMPARISON")
        print("=" * 80)
        print(f"{'Scenario':<25} {'Initial':<10} {'Final':<10} {'Growth':<10} {'Tipping':<10}")
        print("-" * 80)
        
        for result in results_list:
            sd = result['sd_metrics']
            if sd['sd_enabled']:
                tipping = f"Step {sd['tipping_point_step']}" if sd['tipping_point_crossed'] else "No"
                print(f"{result['scenario_name']:<25} {sd['initial_adoption_pct']:>7.1f}%  {sd['final_adoption_pct']:>7.1f}%  {sd['adoption_growth_pct']:>7.1f}%  {tipping:<10}")
        
        print("=" * 80)
    
    print(f"\n✅ All reports saved to: {output_dir.absolute()}")


def main():
    """Command-line interface."""
    
    parser = argparse.ArgumentParser(
        description="Run headless simulations and generate reports",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all scenarios with 200 steps
  python headless_simulation_runner.py --scenarios baseline,aggressive,conservative --steps 200
  
  # Run single scenario
  python headless_simulation_runner.py --scenarios baseline --steps 100
  
  # Run all predefined scenarios
  python headless_simulation_runner.py --scenarios all --steps 150
  
Available scenarios:
  baseline, aggressive, conservative, social_driven, infrastructure_driven
        """
    )
    
    parser.add_argument(
        '--scenarios',
        type=str,
        default='baseline,aggressive,conservative',
        help='Comma-separated list of scenarios to run (or "all" for all scenarios)'
    )
    
    parser.add_argument(
        '--steps',
        type=int,
        default=100,
        help='Number of simulation steps (default: 100)'
    )
    
    parser.add_argument(
        '--output-dir',
        type=str,
        default='./reports',
        help='Output directory for reports (default: ./reports)'
    )
    
    args = parser.parse_args()
    
    # Parse scenarios
    if args.scenarios.lower() == 'all':
        scenario_names = list(get_scenario_configs().keys())
    else:
        scenario_names = [s.strip() for s in args.scenarios.split(',')]
    
    # Run tests
    run_headless_tests(
        scenario_names=scenario_names,
        steps=args.steps,
        output_dir=Path(args.output_dir)
    )


if __name__ == '__main__':
    main()