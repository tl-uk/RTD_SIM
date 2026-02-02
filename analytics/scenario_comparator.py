"""
analytics/scenario_comparator.py

Phase 5.3: Statistical comparison of simulation scenarios.
Enables A/B testing and baseline vs intervention analysis.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Any
import logging
import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)


@dataclass
class ScenarioComparison:
    """Comparison results between two scenarios."""
    baseline_name: str
    intervention_name: str
    
    # Mode share deltas
    mode_share_delta: Dict[str, float]  # percentage points
    
    # Emissions
    emissions_reduction_kg: float
    emissions_reduction_pct: float
    
    # Costs
    infrastructure_cost_delta: float
    operating_cost_delta: float
    net_cost_delta: float
    
    # Performance
    avg_trip_time_delta: float
    avg_trip_cost_delta: float
    
    # Statistical significance
    statistically_significant: bool
    p_values: Dict[str, float]
    
    # Key differences
    divergence_step: int  # When outcomes first split
    primary_cause: str


@dataclass
class KeyDifference:
    """A significant difference between scenarios."""
    metric_name: str
    baseline_value: float
    intervention_value: float
    delta: float
    delta_percent: float
    first_diverged_step: int
    cause: str
    significance: float  # p-value


class ScenarioComparator:
    """
    Statistical comparison of simulation scenarios.
    
    Enables:
    - Baseline vs intervention comparison
    - A/B testing
    - Statistical significance testing
    - Divergence point identification
    """
    
    def __init__(self):
        """Initialize scenario comparator."""
        self.comparisons: List[ScenarioComparison] = []
        logger.info("✅ ScenarioComparator initialized")
    
    # =========================================================================
    # Core Comparison
    # =========================================================================
    
    def compare_scenarios(
        self,
        baseline_results,
        intervention_results,
        baseline_name: str = "Baseline",
        intervention_name: str = "Intervention"
    ) -> ScenarioComparison:
        """
        Compare two simulation scenarios.
        
        Args:
            baseline_results: SimulationResults from baseline run
            intervention_results: SimulationResults from intervention run
            baseline_name: Name for baseline scenario
            intervention_name: Name for intervention scenario
        
        Returns:
            ScenarioComparison with all differences
        """
        # Mode share comparison
        mode_share_delta = self._compare_mode_share(
            baseline_results.adoption_history,
            intervention_results.adoption_history
        )
        
        # Emissions comparison
        emissions_delta = self._compare_emissions(
            baseline_results,
            intervention_results
        )
        
        # Cost comparison
        cost_delta = self._compare_costs(
            baseline_results,
            intervention_results
        )
        
        # Performance comparison
        perf_delta = self._compare_performance(
            baseline_results,
            intervention_results
        )
        
        # Statistical testing
        p_values = self._statistical_tests(
            baseline_results,
            intervention_results
        )
        
        # Identify divergence point
        divergence_step, cause = self._identify_divergence(
            baseline_results,
            intervention_results
        )
        
        # Overall significance (using mode share as primary metric)
        significant = any(p < 0.05 for p in p_values.values())
        
        comparison = ScenarioComparison(
            baseline_name=baseline_name,
            intervention_name=intervention_name,
            mode_share_delta=mode_share_delta,
            emissions_reduction_kg=emissions_delta['absolute'],
            emissions_reduction_pct=emissions_delta['percentage'],
            infrastructure_cost_delta=cost_delta['infrastructure'],
            operating_cost_delta=cost_delta['operating'],
            net_cost_delta=cost_delta['net'],
            avg_trip_time_delta=perf_delta.get('time', 0.0),
            avg_trip_cost_delta=perf_delta.get('cost', 0.0),
            statistically_significant=significant,
            p_values=p_values,
            divergence_step=divergence_step,
            primary_cause=cause
        )
        
        self.comparisons.append(comparison)
        return comparison
    
    def _compare_mode_share(
        self,
        baseline_history: Dict[str, List],
        intervention_history: Dict[str, List]
    ) -> Dict[str, float]:
        """Calculate mode share differences (percentage points)."""
        delta = {}
        
        # Get final values
        all_modes = set(list(baseline_history.keys()) + list(intervention_history.keys()))
        
        for mode in all_modes:
            baseline_final = baseline_history.get(mode, [0])[-1] if baseline_history.get(mode) else 0
            intervention_final = intervention_history.get(mode, [0])[-1] if intervention_history.get(mode) else 0
            
            # Calculate as counts (already percentages in adoption_history)
            diff = intervention_final - baseline_final
            
            if abs(diff) > 0.1:  # Only significant differences
                delta[mode] = diff
        
        return delta
    
    def _compare_emissions(
        self,
        baseline_results,
        intervention_results
    ) -> Dict[str, float]:
        """Compare total emissions."""
        baseline_total = 0.0
        intervention_total = 0.0
        
        # Sum emissions from lifecycle tracking
        if hasattr(baseline_results, 'lifecycle_emissions_total'):
            for mode_data in baseline_results.lifecycle_emissions_total.values():
                baseline_total += mode_data.get('co2e_kg', 0.0)
        
        if hasattr(intervention_results, 'lifecycle_emissions_total'):
            for mode_data in intervention_results.lifecycle_emissions_total.values():
                intervention_total += mode_data.get('co2e_kg', 0.0)
        
        absolute_reduction = baseline_total - intervention_total
        percent_reduction = (absolute_reduction / baseline_total * 100) if baseline_total > 0 else 0.0
        
        return {
            'absolute': absolute_reduction,
            'percentage': percent_reduction,
            'baseline': baseline_total,
            'intervention': intervention_total,
        }
    
    def _compare_costs(
        self,
        baseline_results,
        intervention_results
    ) -> Dict[str, float]:
        """Compare infrastructure and operating costs."""
        # Infrastructure costs (from policy engine if available)
        baseline_infra = 0.0
        intervention_infra = 0.0
        
        if hasattr(baseline_results, 'final_cost_recovery'):
            baseline_infra = baseline_results.final_cost_recovery.get('total_investment', 0.0)
        
        if hasattr(intervention_results, 'final_cost_recovery'):
            intervention_infra = intervention_results.final_cost_recovery.get('total_investment', 0.0)
        
        # Operating costs
        baseline_operating = 0.0
        intervention_operating = 0.0
        
        if hasattr(baseline_results, 'final_cost_recovery'):
            baseline_operating = baseline_results.final_cost_recovery.get('operating_costs', 0.0)
        
        if hasattr(intervention_results, 'final_cost_recovery'):
            intervention_operating = intervention_results.final_cost_recovery.get('operating_costs', 0.0)
        
        return {
            'infrastructure': intervention_infra - baseline_infra,
            'operating': intervention_operating - baseline_operating,
            'net': (intervention_infra + intervention_operating) - (baseline_infra + baseline_operating),
        }
    
    def _compare_performance(
        self,
        baseline_results,
        intervention_results
    ) -> Dict[str, float]:
        """Compare journey performance metrics."""
        # Would need journey tracker data
        # Placeholder for now
        return {
            'time': 0.0,
            'cost': 0.0,
        }
    
    def _statistical_tests(
        self,
        baseline_results,
        intervention_results
    ) -> Dict[str, float]:
        """
        Perform statistical significance tests.
        
        Returns:
            Dict of metric_name -> p_value
        """
        p_values = {}
        
        # Test mode share differences
        # Use Mann-Whitney U test for non-parametric comparison
        for mode in baseline_results.adoption_history.keys():
            if mode in intervention_results.adoption_history:
                baseline_series = baseline_results.adoption_history[mode]
                intervention_series = intervention_results.adoption_history[mode]
                
                if len(baseline_series) > 5 and len(intervention_series) > 5:
                    try:
                        statistic, p_value = stats.mannwhitneyu(
                            baseline_series,
                            intervention_series,
                            alternative='two-sided'
                        )
                        p_values[f'mode_share_{mode}'] = p_value
                    except:
                        p_values[f'mode_share_{mode}'] = 1.0
        
        # Test emissions difference
        # Would need time series data for proper test
        # Using simple comparison for now
        p_values['emissions'] = 0.05  # Placeholder
        
        return p_values
    
    def _identify_divergence(
        self,
        baseline_results,
        intervention_results
    ) -> Tuple[int, str]:
        """
        Identify when scenarios first diverged significantly.
        
        Returns:
            (step, cause) tuple
        """
        # Compare EV adoption curves
        ev_modes = ['ev', 'van_electric', 'truck_electric', 'hgv_electric']
        
        for mode in ev_modes:
            if mode in baseline_results.adoption_history and mode in intervention_results.adoption_history:
                baseline_series = baseline_results.adoption_history[mode]
                intervention_series = intervention_results.adoption_history[mode]
                
                # Find first significant difference
                min_len = min(len(baseline_series), len(intervention_series))
                
                for step in range(min_len):
                    diff = abs(intervention_series[step] - baseline_series[step])
                    
                    if diff > 1.0:  # More than 1% difference
                        # Try to identify cause
                        cause = "policy_intervention"
                        
                        # Check if there were policy actions at this step
                        if hasattr(intervention_results, 'policy_actions'):
                            actions_at_step = [
                                a for a in intervention_results.policy_actions
                                if abs(a.get('step', 0) - step) <= 5
                            ]
                            if actions_at_step:
                                cause = actions_at_step[0].get('action', 'unknown_policy')
                        
                        return step, cause
        
        return 0, "no_divergence"
    
    # =========================================================================
    # Key Differences Analysis
    # =========================================================================
    
    def identify_key_differences(
        self,
        baseline_results,
        intervention_results,
        threshold: float = 5.0  # % difference to be "key"
    ) -> List[KeyDifference]:
        """
        Identify the most important differences between scenarios.
        
        Args:
            baseline_results: Baseline simulation results
            intervention_results: Intervention simulation results
            threshold: Minimum % difference to report
        
        Returns:
            List of KeyDifference objects
        """
        differences = []
        
        # EV adoption difference
        ev_modes = ['ev', 'van_electric', 'truck_electric', 'hgv_electric']
        for mode in ev_modes:
            if mode in baseline_results.adoption_history and mode in intervention_results.adoption_history:
                baseline_final = baseline_results.adoption_history[mode][-1]
                intervention_final = intervention_results.adoption_history[mode][-1]
                
                delta = intervention_final - baseline_final
                delta_pct = (delta / baseline_final * 100) if baseline_final > 0 else 0
                
                if abs(delta_pct) >= threshold:
                    diff = KeyDifference(
                        metric_name=f'{mode}_adoption',
                        baseline_value=baseline_final,
                        intervention_value=intervention_final,
                        delta=delta,
                        delta_percent=delta_pct,
                        first_diverged_step=self._find_divergence_step(
                            baseline_results.adoption_history[mode],
                            intervention_results.adoption_history[mode]
                        ),
                        cause="policy_intervention",
                        significance=0.05  # Would calculate properly
                    )
                    differences.append(diff)
        
        # Sort by absolute delta percentage
        differences.sort(key=lambda d: abs(d.delta_percent), reverse=True)
        
        return differences
    
    def _find_divergence_step(
        self,
        baseline_series: List[float],
        intervention_series: List[float],
        threshold: float = 1.0
    ) -> int:
        """Find first step where series diverge by more than threshold."""
        min_len = min(len(baseline_series), len(intervention_series))
        
        for step in range(min_len):
            if abs(intervention_series[step] - baseline_series[step]) > threshold:
                return step
        
        return 0
    
    # =========================================================================
    # Reporting
    # =========================================================================
    
    def generate_comparison_report(
        self,
        comparison: ScenarioComparison
    ) -> Dict:
        """Generate detailed comparison report."""
        report = {
            'scenarios': {
                'baseline': comparison.baseline_name,
                'intervention': comparison.intervention_name,
            },
            'mode_share': {
                'changes': comparison.mode_share_delta,
                'significant_changes': [
                    mode for mode, delta in comparison.mode_share_delta.items()
                    if abs(delta) > 2.0
                ],
            },
            'emissions': {
                'reduction_kg': comparison.emissions_reduction_kg,
                'reduction_pct': comparison.emissions_reduction_pct,
            },
            'costs': {
                'infrastructure_delta': comparison.infrastructure_cost_delta,
                'operating_delta': comparison.operating_cost_delta,
                'net_delta': comparison.net_cost_delta,
            },
            'divergence': {
                'step': comparison.divergence_step,
                'cause': comparison.primary_cause,
            },
            'statistical': {
                'significant': comparison.statistically_significant,
                'p_values': comparison.p_values,
            },
        }
        
        return report
    
    def generate_summary_table(self) -> Dict:
        """Generate summary table of all comparisons."""
        if not self.comparisons:
            return {'comparisons': 0}
        
        summary = {
            'total_comparisons': len(self.comparisons),
            'comparisons': []
        }
        
        for comp in self.comparisons:
            summary['comparisons'].append({
                'baseline': comp.baseline_name,
                'intervention': comp.intervention_name,
                'emissions_saved_kg': comp.emissions_reduction_kg,
                'emissions_saved_pct': comp.emissions_reduction_pct,
                'cost_delta': comp.net_cost_delta,
                'significant': comp.statistically_significant,
            })
        
        return summary