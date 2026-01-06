"""
simulation/analysis/scenario_comparison.py

Scenario analysis and comparison utilities.
"""

from __future__ import annotations
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

try:
    from scenarios.scenario_manager import ScenarioManager
    SCENARIOS_AVAILABLE = True
except ImportError:
    SCENARIOS_AVAILABLE = False
    logger.warning("Scenario framework not available")


def list_available_scenarios(scenarios_dir: Optional[Path] = None) -> List[str]:
    """
    List all available scenario configurations.
    
    Args:
        scenarios_dir: Directory containing scenario configs
    
    Returns:
        List of scenario names
    """
    if not SCENARIOS_AVAILABLE:
        logger.warning("Scenario framework not available")
        return []
    
    try:
        scenarios_dir = scenarios_dir or (Path(__file__).parent.parent / 'scenarios' / 'configs')
        manager = ScenarioManager(scenarios_dir)
        return manager.list_scenarios()
    except Exception as e:
        logger.error(f"Failed to list scenarios: {e}")
        return []


def get_scenario_info(scenario_name: str, scenarios_dir: Optional[Path] = None) -> Optional[Dict]:
    """
    Get detailed information about a specific scenario.
    
    Args:
        scenario_name: Name of scenario
        scenarios_dir: Directory containing scenario configs
    
    Returns:
        Dict with scenario details or None
    """
    if not SCENARIOS_AVAILABLE:
        return None
    
    try:
        scenarios_dir = scenarios_dir or (Path(__file__).parent.parent / 'scenarios' / 'configs')
        manager = ScenarioManager(scenarios_dir)
        
        success = manager.activate_scenario(scenario_name)
        if not success:
            return None
        
        return manager.get_scenario_report()
    except Exception as e:
        logger.error(f"Failed to get scenario info: {e}")
        return None


def compare_scenarios(
    baseline_results: Dict[str, Any],
    scenario_results: Dict[str, Any],
    scenario_name: str
) -> Dict[str, Any]:
    """
    Compare simulation results between baseline and scenario.
    
    Args:
        baseline_results: Results from baseline simulation
        scenario_results: Results from scenario simulation
        scenario_name: Name of applied scenario
    
    Returns:
        Dict with comparison metrics
    """
    comparison = {
        'scenario_name': scenario_name,
        'mode_shifts': {},
        'adoption_changes': {},
        'infrastructure_impact': {},
        'environmental_impact': {}
    }
    
    try:
        # Compare final mode adoption
        baseline_adoption = baseline_results.get('adoption_history', {})
        scenario_adoption = scenario_results.get('adoption_history', {})
        
        for mode in ['walk', 'bike', 'bus', 'car', 'ev', 'van_electric', 'van_diesel']:
            baseline_final = baseline_adoption.get(mode, [0])[-1] if baseline_adoption.get(mode) else 0
            scenario_final = scenario_adoption.get(mode, [0])[-1] if scenario_adoption.get(mode) else 0
            
            change = scenario_final - baseline_final
            pct_change = (change / max(baseline_final, 1)) * 100
            
            comparison['mode_shifts'][mode] = {
                'baseline': baseline_final,
                'scenario': scenario_final,
                'absolute_change': change,
                'percent_change': pct_change
            }
        
        # Calculate adoption rate changes
        for mode in ['ev', 'van_electric']:
            baseline_history = baseline_adoption.get(mode, [])
            scenario_history = scenario_adoption.get(mode, [])
            
            if len(baseline_history) > 10 and len(scenario_history) > 10:
                # Calculate growth rate in final 20% of simulation
                cutoff = int(len(baseline_history) * 0.8)
                
                baseline_growth = baseline_history[-1] - baseline_history[cutoff]
                scenario_growth = scenario_history[-1] - scenario_history[cutoff]
                
                comparison['adoption_changes'][mode] = {
                    'baseline_growth': baseline_growth,
                    'scenario_growth': scenario_growth,
                    'growth_acceleration': scenario_growth - baseline_growth
                }
        
        # Infrastructure utilization (if available)
        baseline_infra = baseline_results.get('infrastructure')
        scenario_infra = scenario_results.get('infrastructure')
        
        if baseline_infra and scenario_infra:
            baseline_metrics = baseline_infra.get_infrastructure_metrics()
            scenario_metrics = scenario_infra.get_infrastructure_metrics()
            
            comparison['infrastructure_impact'] = {
                'utilization_change': (
                    scenario_metrics.get('avg_utilization', 0) - 
                    baseline_metrics.get('avg_utilization', 0)
                ),
                'charging_events_change': (
                    scenario_metrics.get('total_charging_events', 0) - 
                    baseline_metrics.get('total_charging_events', 0)
                )
            }
        
        # Environmental impact (simplified)
        baseline_agents = baseline_results.get('agents', [])
        scenario_agents = scenario_results.get('agents', [])
        
        baseline_emissions = sum(
            getattr(a.state, 'emissions_g', 0) for a in baseline_agents
        )
        scenario_emissions = sum(
            getattr(a.state, 'emissions_g', 0) for a in scenario_agents
        )
        
        comparison['environmental_impact'] = {
            'baseline_emissions_g': baseline_emissions,
            'scenario_emissions_g': scenario_emissions,
            'emissions_reduction_g': baseline_emissions - scenario_emissions,
            'emissions_reduction_pct': (
                ((baseline_emissions - scenario_emissions) / max(baseline_emissions, 1)) * 100
            )
        }
        
    except Exception as e:
        logger.error(f"Failed to compare scenarios: {e}")
        comparison['error'] = str(e)
    
    return comparison


def format_comparison_report(comparison: Dict[str, Any]) -> str:
    """
    Format comparison results as human-readable report.
    
    Args:
        comparison: Comparison dict from compare_scenarios()
    
    Returns:
        Formatted string report
    """
    report = []
    report.append(f"\n{'='*60}")
    report.append(f"SCENARIO COMPARISON: {comparison['scenario_name']}")
    report.append(f"{'='*60}\n")
    
    # Mode shifts
    report.append("MODE ADOPTION CHANGES:")
    report.append("-" * 60)
    
    mode_shifts = comparison.get('mode_shifts', {})
    for mode, data in mode_shifts.items():
        if abs(data['percent_change']) > 1:  # Only show significant changes
            arrow = "↑" if data['percent_change'] > 0 else "↓"
            report.append(
                f"  {mode:15s}: {data['baseline']:3.0f} → {data['scenario']:3.0f} "
                f"({arrow} {abs(data['percent_change']):5.1f}%)"
            )
    
    # EV adoption acceleration
    adoption_changes = comparison.get('adoption_changes', {})
    if adoption_changes:
        report.append(f"\nEV ADOPTION ACCELERATION:")
        report.append("-" * 60)
        for mode, data in adoption_changes.items():
            report.append(
                f"  {mode:15s}: Growth accelerated by "
                f"{data['growth_acceleration']:+.1f} agents"
            )
    
    # Environmental impact
    env_impact = comparison.get('environmental_impact', {})
    if env_impact:
        report.append(f"\nENVIRONMENTAL IMPACT:")
        report.append("-" * 60)
        reduction_pct = env_impact.get('emissions_reduction_pct', 0)
        arrow = "↓" if reduction_pct > 0 else "↑"
        report.append(
            f"  Emissions: {arrow} {abs(reduction_pct):.1f}% "
            f"({env_impact.get('emissions_reduction_g', 0):,.0f}g CO₂ saved)"
        )
    
    report.append(f"\n{'='*60}\n")
    
    return "\n".join(report)