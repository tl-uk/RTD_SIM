"""
analytics/policy_impact_analyzer.py

Phase 5.3: Policy impact attribution and ROI analysis.
Measures effectiveness of policy interventions and calculates return on investment.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import logging
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class PolicySnapshot:
    """State snapshot before/after policy intervention."""
    step: int
    mode_share: Dict[str, float]
    ev_count: int
    total_emissions_kg: float
    grid_load: float
    grid_utilization: float
    charger_utilization: float
    avg_trip_time: float
    avg_trip_cost: float


@dataclass
class ImpactMeasurement:
    """Measured impact of a policy intervention."""
    policy_name: str
    activation_step: int
    
    # Direct effects
    agents_affected_direct: int
    mode_switches: Dict[str, int]  # mode -> net change
    cost_change: float  # Total cost change for affected agents
    emissions_reduction_kg: float
    
    # Indirect effects (cascades)
    agents_affected_indirect: int
    network_hops: float  # Average distance from directly affected
    cascade_duration: int  # Steps to reach full effect
    
    # Grid impact
    grid_load_change: float
    grid_utilization_change: float
    
    # Statistical confidence
    confidence_level: float  # 0-1


@dataclass
class ROIReport:
    """Return on investment analysis for a policy."""
    policy_name: str
    
    # Costs
    implementation_cost: float  # One-time
    operating_cost_annual: float  # Recurring
    total_cost: float
    
    # Benefits
    emissions_saved_kg: float
    cost_per_tonne_co2: float
    
    # Financial
    revenue_generated: float  # e.g., from charging fees
    cost_savings: float  # e.g., reduced congestion
    net_benefit: float
    
    # ROI metrics
    benefit_cost_ratio: float  # >1 = beneficial
    payback_period_days: float
    net_present_value: float
    
    # Non-financial
    agents_benefited: int
    quality_of_life_improvement: float


class PolicyImpactAnalyzer:
    """
    Attribute outcomes to specific policy interventions.
    Calculate ROI and effectiveness metrics.
    
    Enables:
    - Direct impact measurement
    - Cascade effect tracking
    - Cost-benefit analysis
    - Policy comparison
    """
    
    def __init__(self, policy_engine=None):
        """
        Initialize policy impact analyzer.
        
        Args:
            policy_engine: Optional DynamicPolicyEngine instance
        """
        self.policy_engine = policy_engine
        
        # Baseline state (before any policies)
        self.baseline: Optional[PolicySnapshot] = None
        
        # Policy activation tracking
        self.policy_activations: Dict[str, int] = {}  # policy -> step
        self.policy_snapshots: Dict[str, Tuple[PolicySnapshot, PolicySnapshot]] = {}  # before, after
        
        # Impact measurements
        self.impacts: List[ImpactMeasurement] = []
        self.roi_reports: Dict[str, ROIReport] = {}
        
        # Continuous tracking
        self.step_snapshots: List[PolicySnapshot] = []
        
        logger.info("✅ PolicyImpactAnalyzer initialized")
    
    # =========================================================================
    # Baseline & Snapshot Management
    # =========================================================================
    
    def capture_baseline(
        self,
        step: int,
        agents: List,
        emissions_tracker=None,
        infrastructure=None
    ):
        """
        Capture baseline state before any policy interventions.
        
        Args:
            step: Current step
            agents: List of agents
            emissions_tracker: Emissions tracking object
            infrastructure: Infrastructure manager
        """
        snapshot = self._create_snapshot(step, agents, emissions_tracker, infrastructure)
        self.baseline = snapshot
        
        logger.info(f"📸 Baseline captured at step {step}")
        logger.info(f"   EV count: {snapshot.ev_count}")
        logger.info(f"   Total emissions: {snapshot.total_emissions_kg:.1f} kg")
    
    def capture_step_snapshot(
        self,
        step: int,
        agents: List,
        emissions_tracker=None,
        infrastructure=None
    ):
        """Capture state at regular intervals for continuous tracking."""
        snapshot = self._create_snapshot(step, agents, emissions_tracker, infrastructure)
        self.step_snapshots.append(snapshot)
    
    def _create_snapshot(
        self,
        step: int,
        agents: List,
        emissions_tracker=None,
        infrastructure=None
    ) -> PolicySnapshot:
        """Create a state snapshot."""
        # Mode share
        mode_counts = defaultdict(int)
        ev_modes = ['ev', 'van_electric', 'truck_electric', 'hgv_electric']
        ev_count = 0
        
        for agent in agents:
            mode = agent.state.mode
            mode_counts[mode] += 1
            if mode in ev_modes:
                ev_count += 1
        
        total = len(agents)
        mode_share = {mode: (count / total * 100) for mode, count in mode_counts.items()}
        
        # Emissions
        total_emissions = 0.0
        if emissions_tracker and hasattr(emissions_tracker, 'lifecycle_emissions_by_mode'):
            for mode_data in emissions_tracker.lifecycle_emissions_by_mode.values():
                total_emissions += mode_data.get('co2e_kg', 0.0)
        
        # Infrastructure
        grid_load = 0.0
        grid_util = 0.0
        charger_util = 0.0
        
        if infrastructure:
            metrics = infrastructure.get_infrastructure_metrics()
            grid_load = metrics.get('grid_load_mw', 0.0)
            grid_util = metrics.get('grid_utilization', 0.0)
            charger_util = metrics.get('utilization', 0.0)
        
        # Trip metrics
        trip_times = []
        trip_costs = []
        for agent in agents:
            if hasattr(agent.state, 'last_trip_time') and agent.state.last_trip_time:
                trip_times.append(agent.state.last_trip_time)
            if hasattr(agent.state, 'last_trip_cost') and agent.state.last_trip_cost:
                trip_costs.append(agent.state.last_trip_cost)
        
        avg_time = np.mean(trip_times) if trip_times else 0.0
        avg_cost = np.mean(trip_costs) if trip_costs else 0.0
        
        return PolicySnapshot(
            step=step,
            mode_share=mode_share,
            ev_count=ev_count,
            total_emissions_kg=total_emissions,
            grid_load=grid_load,
            grid_utilization=grid_util,
            charger_utilization=charger_util,
            avg_trip_time=avg_time,
            avg_trip_cost=avg_cost
        )
    
    # =========================================================================
    # Policy Impact Measurement
    # =========================================================================
    
    def record_policy_activation(self, policy_name: str, step: int):
        """
        Record when a policy was activated.
        
        Args:
            policy_name: Name of policy action
            step: When it was activated
        """
        if policy_name not in self.policy_activations:
            self.policy_activations[policy_name] = step
            logger.info(f"📍 Policy '{policy_name}' first activated at step {step}")
    
    def measure_direct_impact(
        self,
        policy_name: str,
        before_snapshot: PolicySnapshot,
        after_snapshot: PolicySnapshot,
        agents: List,
        network=None
    ) -> ImpactMeasurement:
        """
        Measure direct impact of a policy intervention.
        
        Compares state before and after policy activation.
        
        Args:
            policy_name: Name of policy
            before_snapshot: State before policy
            after_snapshot: State after policy
            agents: List of agents
            network: Social network (optional)
        
        Returns:
            ImpactMeasurement
        """
        # Calculate mode switches
        mode_switches = {}
        for mode in set(list(before_snapshot.mode_share.keys()) + list(after_snapshot.mode_share.keys())):
            before = before_snapshot.mode_share.get(mode, 0.0)
            after = after_snapshot.mode_share.get(mode, 0.0)
            change = after - before
            if abs(change) > 0.1:  # Only significant changes
                mode_switches[mode] = change
        
        # Count affected agents (those who switched modes)
        agents_affected = int(sum(abs(change) for change in mode_switches.values()) / 100 * len(agents))
        
        # Emissions reduction
        emissions_reduction = before_snapshot.total_emissions_kg - after_snapshot.total_emissions_kg
        
        # Grid impact
        grid_load_change = after_snapshot.grid_load - before_snapshot.grid_load
        grid_util_change = after_snapshot.grid_utilization - before_snapshot.grid_utilization
        
        # Cost impact (simplified)
        cost_change = (after_snapshot.avg_trip_cost - before_snapshot.avg_trip_cost) * agents_affected
        
        # Cascade effects (if network available)
        indirect_affected = 0
        avg_hops = 0.0
        cascade_duration = after_snapshot.step - before_snapshot.step
        
        if network:
            # Estimate cascade through network
            # This would require detailed tracking of influence chains
            pass
        
        # Confidence level (based on sample size and variance)
        confidence = self._calculate_confidence(agents_affected, len(agents))
        
        impact = ImpactMeasurement(
            policy_name=policy_name,
            activation_step=before_snapshot.step,
            agents_affected_direct=agents_affected,
            mode_switches=mode_switches,
            cost_change=cost_change,
            emissions_reduction_kg=emissions_reduction,
            agents_affected_indirect=indirect_affected,
            network_hops=avg_hops,
            cascade_duration=cascade_duration,
            grid_load_change=grid_load_change,
            grid_utilization_change=grid_util_change,
            confidence_level=confidence
        )
        
        self.impacts.append(impact)
        return impact
    
    def _calculate_confidence(self, sample_size: int, population: int) -> float:
        """Calculate statistical confidence level."""
        if population == 0:
            return 0.0
        
        proportion = sample_size / population
        
        # Simple confidence calculation
        # More affected = higher confidence in real effect
        if proportion > 0.1:
            return 0.95
        elif proportion > 0.05:
            return 0.90
        elif proportion > 0.01:
            return 0.75
        else:
            return 0.50
    
    # =========================================================================
    # ROI Calculation
    # =========================================================================
    
    def calculate_roi(
        self,
        policy_name: str,
        implementation_cost: float = 0.0,
        operating_cost_annual: float = 0.0,
        simulation_duration_days: float = 7.0
    ) -> ROIReport:
        """
        Calculate return on investment for a policy.
        
        Args:
            policy_name: Name of policy
            implementation_cost: One-time cost (£)
            operating_cost_annual: Annual operating cost (£)
            simulation_duration_days: How many days simulated
        
        Returns:
            ROIReport
        """
        # Find impact measurement for this policy
        impact = next((i for i in self.impacts if i.policy_name == policy_name), None)
        
        if not impact:
            logger.warning(f"No impact data for policy '{policy_name}'")
            return self._empty_roi_report(policy_name)
        
        # Calculate total cost
        operating_cost_period = operating_cost_annual * (simulation_duration_days / 365.0)
        total_cost = implementation_cost + operating_cost_period
        
        # Calculate benefits
        emissions_saved = impact.emissions_reduction_kg
        cost_per_tonne = (total_cost / (emissions_saved / 1000)) if emissions_saved > 0 else 0.0
        
        # Revenue (e.g., from charging infrastructure)
        revenue_generated = 0.0
        if 'charger' in policy_name.lower():
            # Estimate revenue from new chargers
            revenue_generated = impact.agents_affected_direct * 50  # £50 per agent
        
        # Cost savings (e.g., reduced congestion, health benefits)
        cost_savings = 0.0
        if emissions_saved > 0:
            # Value of carbon saved (£25 per tonne CO2)
            cost_savings = (emissions_saved / 1000) * 25
        
        net_benefit = revenue_generated + cost_savings - total_cost
        
        # ROI metrics
        bcr = (revenue_generated + cost_savings) / total_cost if total_cost > 0 else 0.0
        
        # Payback period
        payback_days = 0.0
        if revenue_generated + cost_savings > 0:
            daily_benefit = (revenue_generated + cost_savings) / simulation_duration_days
            if daily_benefit > 0:
                payback_days = total_cost / daily_benefit
        else:
            payback_days = float('inf')
        
        # NPV (simplified, 5% discount rate)
        discount_rate = 0.05
        npv = -implementation_cost
        for year in range(5):
            annual_benefit = (revenue_generated + cost_savings) * (365 / simulation_duration_days)
            annual_cost = operating_cost_annual
            npv += (annual_benefit - annual_cost) / ((1 + discount_rate) ** year)
        
        # Non-financial benefits
        agents_benefited = impact.agents_affected_direct + impact.agents_affected_indirect
        qol_improvement = self._estimate_qol_improvement(impact)
        
        roi = ROIReport(
            policy_name=policy_name,
            implementation_cost=implementation_cost,
            operating_cost_annual=operating_cost_annual,
            total_cost=total_cost,
            emissions_saved_kg=emissions_saved,
            cost_per_tonne_co2=cost_per_tonne,
            revenue_generated=revenue_generated,
            cost_savings=cost_savings,
            net_benefit=net_benefit,
            benefit_cost_ratio=bcr,
            payback_period_days=payback_days,
            net_present_value=npv,
            agents_benefited=agents_benefited,
            quality_of_life_improvement=qol_improvement
        )
        
        self.roi_reports[policy_name] = roi
        return roi
    
    def _empty_roi_report(self, policy_name: str) -> ROIReport:
        """Create empty ROI report."""
        return ROIReport(
            policy_name=policy_name,
            implementation_cost=0.0,
            operating_cost_annual=0.0,
            total_cost=0.0,
            emissions_saved_kg=0.0,
            cost_per_tonne_co2=0.0,
            revenue_generated=0.0,
            cost_savings=0.0,
            net_benefit=0.0,
            benefit_cost_ratio=0.0,
            payback_period_days=float('inf'),
            net_present_value=0.0,
            agents_benefited=0,
            quality_of_life_improvement=0.0
        )
    
    def _estimate_qol_improvement(self, impact: ImpactMeasurement) -> float:
        """
        Estimate quality of life improvement (0-10 scale).
        
        Based on:
        - Reduced emissions (health benefits)
        - Improved infrastructure
        - Reduced costs
        """
        score = 0.0
        
        # Emissions reduction (0-5 points)
        if impact.emissions_reduction_kg > 1000:
            score += 5.0
        elif impact.emissions_reduction_kg > 500:
            score += 3.0
        elif impact.emissions_reduction_kg > 100:
            score += 1.0
        
        # Cost reduction (0-3 points)
        if impact.cost_change < -1000:
            score += 3.0
        elif impact.cost_change < -500:
            score += 2.0
        elif impact.cost_change < 0:
            score += 1.0
        
        # Infrastructure improvement (0-2 points)
        if impact.grid_utilization_change < 0:
            score += 2.0  # Reduced grid stress is good
        
        return min(10.0, score)
    
    # =========================================================================
    # Comparative Analysis
    # =========================================================================
    
    def compare_policies(self, policy_names: List[str]) -> Dict:
        """
        Compare multiple policies side-by-side.
        
        Args:
            policy_names: List of policy names to compare
        
        Returns:
            Comparison table
        """
        comparison = {
            'policies': policy_names,
            'metrics': defaultdict(dict)
        }
        
        for policy_name in policy_names:
            impact = next((i for i in self.impacts if i.policy_name == policy_name), None)
            roi = self.roi_reports.get(policy_name)
            
            if impact:
                comparison['metrics']['agents_affected'][policy_name] = impact.agents_affected_direct
                comparison['metrics']['emissions_saved'][policy_name] = impact.emissions_reduction_kg
                comparison['metrics']['confidence'][policy_name] = impact.confidence_level
            
            if roi:
                comparison['metrics']['cost'][policy_name] = roi.total_cost
                comparison['metrics']['bcr'][policy_name] = roi.benefit_cost_ratio
                comparison['metrics']['payback_days'][policy_name] = roi.payback_period_days
                comparison['metrics']['npv'][policy_name] = roi.net_present_value
        
        # Rank policies
        comparison['rankings'] = self._rank_policies(policy_names)
        
        return dict(comparison)
    
    def _rank_policies(self, policy_names: List[str]) -> Dict[str, List[str]]:
        """Rank policies by different criteria."""
        rankings = {}
        
        # By emissions reduction
        by_emissions = sorted(
            policy_names,
            key=lambda p: next((i.emissions_reduction_kg for i in self.impacts if i.policy_name == p), 0),
            reverse=True
        )
        rankings['by_emissions'] = by_emissions
        
        # By BCR
        by_bcr = sorted(
            policy_names,
            key=lambda p: self.roi_reports.get(p, self._empty_roi_report(p)).benefit_cost_ratio,
            reverse=True
        )
        rankings['by_bcr'] = by_bcr
        
        # By agents affected
        by_impact = sorted(
            policy_names,
            key=lambda p: next((i.agents_affected_direct for i in self.impacts if i.policy_name == p), 0),
            reverse=True
        )
        rankings['by_impact'] = by_impact
        
        return rankings
    
    # =========================================================================
    # Reporting
    # =========================================================================
    
    def generate_summary_report(self) -> Dict:
        """Generate comprehensive policy impact report."""
        report = {
            'baseline': {
                'step': self.baseline.step if self.baseline else 0,
                'ev_count': self.baseline.ev_count if self.baseline else 0,
                'emissions': self.baseline.total_emissions_kg if self.baseline else 0,
            },
            'policies_evaluated': len(self.impacts),
            'total_emissions_saved': sum(i.emissions_reduction_kg for i in self.impacts),
            'total_agents_affected': sum(i.agents_affected_direct for i in self.impacts),
            'policies': []
        }
        
        for impact in self.impacts:
            roi = self.roi_reports.get(impact.policy_name)
            
            policy_data = {
                'name': impact.policy_name,
                'activation_step': impact.activation_step,
                'agents_affected': impact.agents_affected_direct,
                'emissions_saved_kg': impact.emissions_reduction_kg,
                'mode_switches': impact.mode_switches,
                'confidence': impact.confidence_level,
            }
            
            if roi:
                policy_data['roi'] = {
                    'cost': roi.total_cost,
                    'benefit_cost_ratio': roi.benefit_cost_ratio,
                    'payback_days': roi.payback_period_days,
                    'npv': roi.net_present_value,
                }
            
            report['policies'].append(policy_data)
        
        return report