"""
scenarios/dynamic_policy_engine.py

Phase 5.1: Dynamic Policy Interaction Engine

Enables:
- Combining multiple scenarios with interaction rules
- Real-time policy adjustments based on simulation state
- Feedback loops (grid stress → pricing → behavior)
- Infrastructure cost recovery modeling
- Constraint enforcement (budget, grid capacity, deployment rates)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from pathlib import Path
import yaml
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class PolicyTrigger(Enum):
    """When policies activate."""
    IMMEDIATE = "immediate"           # At scenario start
    CONDITIONAL = "conditional"       # When condition met
    SCHEDULED = "scheduled"           # At specific step/time
    FEEDBACK = "feedback"             # Continuous adjustment


@dataclass
class InteractionRule:
    """Defines how policies interact with each other."""
    condition: str                    # Python expression to evaluate
    action: str                       # What to do when condition met
    parameters: Dict[str, Any]        # Action parameters
    priority: int = 0                 # Higher = evaluated first
    
    def evaluate_condition(self, state: Dict[str, Any]) -> bool:
        """Safely evaluate condition against simulation state."""
        try:
            # Create safe evaluation context
            # FIX: Include ALL state variables, not just a subset!
            safe_context = {
                'grid_load': state.get('grid_load', 0),
                'grid_capacity': state.get('grid_capacity', 1000),
                'grid_utilization': state.get('grid_utilization', 0),
                'charger_utilization': state.get('charger_utilization', 0),
                'occupied_chargers': state.get('occupied_chargers', 0),
                'total_chargers': state.get('total_chargers', 1),
                'ev_adoption': state.get('ev_adoption', 0),
                'ev_count': state.get('ev_count', 0),  # FIX: Added ev_count!
                'total_agents': state.get('total_agents', 1),  # FIX: Added total_agents!
                'avg_charging_cost': state.get('avg_charging_cost', 0),
                'step': state.get('step', 0),
                'time_of_day': state.get('time_of_day', 8),
            }
            
            return eval(self.condition, {"__builtins__": {}}, safe_context)
        except Exception as e:
            logger.error(f"Failed to evaluate condition '{self.condition}': {e}")
            return False

@dataclass
class PolicyConstraint:
    """Limits on policy application."""
    constraint_type: str              # 'budget', 'grid_capacity', 'deployment_rate'
    limit: float                      # Maximum value
    current: float = 0.0              # Current usage
    warning_threshold: float = 0.8   # Warn at 80% of limit
    
    def is_exceeded(self) -> bool:
        """Check if constraint is violated."""
        return self.current >= self.limit
    
    def is_warning(self) -> bool:
        """Check if approaching limit."""
        return self.current >= (self.limit * self.warning_threshold)
    
    def remaining(self) -> float:
        """Get remaining capacity."""
        return max(0, self.limit - self.current)
    
    def utilization(self) -> float:
        """Get utilization as percentage."""
        return (self.current / self.limit) if self.limit > 0 else 0


@dataclass
class FeedbackLoop:
    """Models dynamic feedback between system components."""
    name: str
    description: str
    variables: List[str]              # Variables involved in loop
    loop_type: str                    # 'positive' (reinforcing) or 'negative' (balancing)
    strength: float = 1.0             # Loop strength multiplier
    update_function: Optional[Callable] = None  # Custom update logic
    
    def apply(self, state: Dict[str, Any]) -> Dict[str, float]:
        """Apply feedback loop adjustments."""
        if self.update_function:
            return self.update_function(state, self.strength)
        return {}


@dataclass
class CombinedScenario:
    """Multiple scenarios combined with interaction rules."""
    name: str
    description: str
    base_scenarios: List[str]         # Scenario names to combine
    interaction_rules: List[InteractionRule] = field(default_factory=list)
    constraints: Dict[str, PolicyConstraint] = field(default_factory=dict)
    feedback_loops: List[FeedbackLoop] = field(default_factory=list)
    
    # State tracking
    active_rules: List[InteractionRule] = field(default_factory=list)
    triggered_at_step: Dict[str, int] = field(default_factory=dict)


class DynamicPolicyEngine:
    """
    Manages policy combinations, interactions, and dynamic adjustments.
    
    Key features:
    1. Combine multiple scenarios
    2. Apply interaction rules based on simulation state
    3. Enforce constraints (budget, grid, deployment)
    4. Model feedback loops
    5. Track infrastructure cost recovery
    """
    
    def __init__(self, infrastructure_manager, scenario_manager):
        """
        Initialize dynamic policy engine.
        
        Args:
            infrastructure_manager: InfrastructureManager instance
            scenario_manager: ScenarioManager instance
        """
        self.infrastructure = infrastructure_manager
        self.scenario_manager = scenario_manager
        
        # Active combined scenario
        self.active_combined: Optional[CombinedScenario] = None
        
        # State tracking
        self.simulation_state: Dict[str, Any] = {}
        self.policy_history: List[Dict] = []
        
        # Cost recovery tracking
        self.infrastructure_capex = 0.0      # Total infrastructure investment
        self.charging_revenue = 0.0           # Total revenue from charging
        self.operating_costs = 0.0            # Ongoing operations
        
        # Dynamic pricing state
        self.base_charging_cost = 0.15       # GBP/kWh baseline
        self.current_price_multiplier = 1.0  # Dynamic adjustment
        
        logger.info("Dynamic Policy Engine initialized")
    
    # =====================================================================
    # Scenario Combination
    # =====================================================================
    
    def load_combined_scenario(self, yaml_path: Path) -> CombinedScenario:
        """Load combined scenario from YAML."""
        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f)
        
        # Parse interaction rules
        rules = []
        for rule_data in data.get('interaction_rules', []):
            rule = InteractionRule(
                condition=rule_data['condition'],
                action=rule_data['action'],
                parameters=rule_data.get('parameters', {}),
                priority=rule_data.get('priority', 0)
            )
            rules.append(rule)
        
        # Parse constraints
        constraints = {}
        for const_data in data.get('constraints', []):
            constraint = PolicyConstraint(
                constraint_type=const_data['type'],
                limit=const_data['limit'],
                warning_threshold=const_data.get('warning_threshold', 0.8)
            )
            constraints[const_data['type']] = constraint
        
        # Parse feedback loops
        feedback_loops = []
        for loop_data in data.get('feedback_loops', []):
            loop = FeedbackLoop(
                name=loop_data['name'],
                description=loop_data['description'],
                variables=loop_data['variables'],
                loop_type=loop_data['loop_type'],
                strength=loop_data.get('strength', 1.0)
            )
            feedback_loops.append(loop)
        
        combined = CombinedScenario(
            name=data['name'],
            description=data['description'],
            base_scenarios=data['base_scenarios'],
            interaction_rules=rules,
            constraints=constraints,
            feedback_loops=feedback_loops
        )
        
        logger.info(f"Loaded combined scenario: {combined.name}")
        logger.info(f"  Base scenarios: {combined.base_scenarios}")
        logger.info(f"  Interaction rules: {len(combined.interaction_rules)}")
        logger.info(f"  Constraints: {len(combined.constraints)}")
        
        return combined
    
    def activate_combined_scenario(self, combined: CombinedScenario) -> None:
        """Activate combined scenario and apply base policies."""
        self.active_combined = combined
        
        # Apply all base scenarios
        for scenario_name in combined.base_scenarios:
            success = self.scenario_manager.activate_scenario(scenario_name)
            if success:
                logger.info(f"  Applied base scenario: {scenario_name}")
            else:
                logger.error(f"  Failed to apply: {scenario_name}")
        
        # Initialize constraints
        if 'budget' in combined.constraints:
            budget = combined.constraints['budget']
            logger.info(f"  Budget constraint: £{budget.limit:,.0f}")
        
        if 'grid_capacity' in combined.constraints:
            grid = combined.constraints['grid_capacity']
            logger.info(f"  Grid capacity constraint: {grid.limit:.0f} MW")
    
    # =====================================================================
    # Dynamic State Updates
    # =====================================================================
    
    def update_simulation_state(self, step: int, agents: List, env, infrastructure) -> None:
        """
        Update simulation state for condition evaluation.
        
        Call this every simulation step.
        """
        # Count EV adoption
        ev_modes = ['ev', 'van_electric', 'truck_electric', 'hgv_electric']
        ev_count = sum(1 for a in agents if a.state.mode in ev_modes)
        total_agents = len(agents)
        
        # Grid metrics
        grid_metrics = infrastructure.get_infrastructure_metrics()
        
        # Charging utilization
        charger_util = grid_metrics.get('utilization', 0)
        
        # Update state dict (including weather if available)
        self.simulation_state = {
            'step': step,
            'time_of_day': infrastructure.current_hour if hasattr(infrastructure, 'current_hour') else 8,
            'ev_adoption': ev_count / max(1, total_agents),
            'ev_count': ev_count,
            'total_agents': total_agents,
            'grid_load': grid_metrics.get('grid_load_mw', 0),
            'grid_capacity': grid_metrics.get('grid_capacity_mw', 1000),
            'grid_utilization': grid_metrics.get('grid_utilization', 0),
            'charger_utilization': charger_util,
            'occupied_chargers': grid_metrics.get('occupied_ports', 0),
            'total_chargers': grid_metrics.get('total_ports', 1),
            'avg_charging_cost': self.base_charging_cost * self.current_price_multiplier,
        }
        
        # Add weather data to state if weather manager is available
        if hasattr(self, 'weather_manager') and self.weather_manager:
            conditions = self.weather_manager.current_conditions
            self.simulation_state['temperature'] = conditions.get('temperature', 10.0)
            self.simulation_state['precipitation'] = conditions.get('precipitation', 0.0)
            self.simulation_state['snow_depth'] = conditions.get('snow_depth', 0.0)
            self.simulation_state['ice_warning'] = conditions.get('ice_warning', False)
            self.simulation_state['wind_speed'] = conditions.get('wind_speed', 10.0)
        
        # Update constraints
        if self.active_combined:
            if 'grid_capacity' in self.active_combined.constraints:
                constraint = self.active_combined.constraints['grid_capacity']
                constraint.current = self.simulation_state['grid_load']
    
    def apply_interaction_rules(self, step: int) -> List[Dict]:
        """
        Evaluate and apply interaction rules based on current state.
        
        Returns:
            List of actions taken
        """
        if not self.active_combined:
            return []
        
        actions_taken = []
        
        # Sort rules by priority (highest first)
        sorted_rules = sorted(
            self.active_combined.interaction_rules,
            key=lambda r: r.priority,
            reverse=True
        )
        
        for rule in sorted_rules:
            # Check if condition met
            if rule.evaluate_condition(self.simulation_state):
                # Execute action
                action_result = self._execute_action(rule, step)
                
                if action_result:
                    actions_taken.append({
                        'step': step,
                        'condition': rule.condition,
                        'action': rule.action,
                        'result': action_result
                    })
                    
                    # Track when rule was triggered
                    rule_key = f"{rule.action}_{rule.condition}"
                    self.active_combined.triggered_at_step[rule_key] = step
                    
                    logger.info(f"Step {step}: Triggered rule - {rule.action}")
        
        return actions_taken
    
    def _execute_action(self, rule: InteractionRule, step: int) -> Optional[Dict]:
        """Execute rule action."""
        action = rule.action
        params = rule.parameters
        
        # Pricing actions
        if action == 'apply_surge_pricing':
            return self._apply_surge_pricing(params)
        elif action == 'increase_charging_cost':
            return self._increase_charging_cost(params)
        elif action == 'reduce_charging_costs':  # NEW: Alias for discounts
            return self._reduce_charging_costs(params)
        
        # Infrastructure actions
        elif action == 'add_emergency_chargers':
            return self._add_emergency_chargers(params)
        elif action == 'add_chargers':  # NEW: Alias
            return self._add_emergency_chargers(params)
        elif action == 'relocate_chargers':  # NEW
            return self._relocate_underutilized_chargers(params)
        elif action == 'upgrade_charger_speed':  # NEW
            return self._upgrade_charger_speed(params)
        
        # Subsidy actions
        elif action == 'reduce_ev_subsidy':
            return self._reduce_ev_subsidy(params)
        elif action == 'increase_ev_subsidy':  # NEW
            return self._increase_ev_subsidy(params)
        
        # Grid actions
        elif action == 'enable_smart_charging':
            return self._enable_smart_charging(params)
        elif action == 'increase_grid_capacity':  # NEW
            return self._increase_grid_capacity(params)
        elif action == 'load_balancing':  # NEW
            return self._apply_load_balancing(params)
        
        # Mode-specific actions
        elif action == 'apply_congestion_charge':  # NEW
            return self._apply_congestion_charge(params)
        elif action == 'ban_diesel_vehicles':  # NEW
            return self._ban_diesel_vehicles(params)
        
        # NEW: Weather-responsive actions
        elif action == 'activate_winter_gritting':
            # Reduce speed penalties on icy roads
            self.state['ice_warning'] = False
            logger.info(f"Step {step}: Activated winter gritting")
        
        elif action == 'close_routes':
            # Mark certain routes as unavailable
            region = rule.action.get('region', 'all')
            logger.info(f"Step {step}: Closed routes in {region} due to weather")
        
        elif action == 'emergency_transit':
            # Boost public transport frequency
            multiplier = rule.action.get('frequency_multiplier', 1.5)
            logger.info(f"Step {step}: Emergency transit boost ({multiplier}x)")
        
        elif action == 'reduce_charging_time':
            # Temperature-controlled charging
            reduction = rule.action.get('reduction_factor', 0.8)
            logger.info(f"Step {step}: Charging time reduced to {reduction*100}%")

        elif action == 'enable_winter_protocols':
            # Winter emergency protocols
            success = self._enable_winter_protocols(params, step)

        else:
            logger.warning(f"Unknown action: {action}")
            return None

    # ====================================================================
    # Action Implementations
    # ===================================================================
    def _reduce_charging_costs(self, params: Dict) -> Dict:
        """Reduce charging costs (incentivize EV adoption)."""
        multiplier = params.get('multiplier', 0.8)  # Default 20% discount
        
        old_multiplier = self.current_price_multiplier
        self.current_price_multiplier = multiplier
        
        # Update all charging station costs
        updated = 0
        for station in self.infrastructure.charging_stations.values():
            station.cost_per_kwh = self.base_charging_cost * multiplier
            updated += 1
        
        logger.info(f"  Charging cost reduction: {old_multiplier:.2f}x → {multiplier:.2f}x ({updated} stations)")
        
        return {
            'old_multiplier': old_multiplier,
            'new_multiplier': multiplier,
            'discount_percentage': (1 - multiplier) * 100,
            'stations_updated': updated
        }
    
    def _relocate_underutilized_chargers(self, params: Dict) -> Dict:
        """Relocate underutilized chargers to high-demand areas."""
        num_to_relocate = params.get('num_chargers', 5)
        utilization_threshold = params.get('utilization_threshold', 0.2)
        
        # Find underutilized stations
        underutilized = []
        for station_id, station in self.infrastructure.charging_stations.items():
            if hasattr(station, 'utilization_history'):
                avg_util = sum(station.utilization_history) / max(1, len(station.utilization_history))
                if avg_util < utilization_threshold:
                    underutilized.append(station_id)
        
        # Relocate (simplified - just remove and add new ones)
        relocated_count = min(num_to_relocate, len(underutilized))
        
        for station_id in underutilized[:relocated_count]:
            if station_id in self.infrastructure.charging_stations:
                del self.infrastructure.charging_stations[station_id]
        
        # Add new chargers in high-demand areas
        new_stations = self.infrastructure.add_chargers_by_demand(
            num_chargers=relocated_count,
            strategy='demand_heatmap'
        )
        
        logger.info(f"  Relocated {relocated_count} underutilized chargers to high-demand areas")
        
        return {
            'relocated_count': relocated_count,
            'new_station_ids': new_stations,
            'threshold': utilization_threshold
        }
    
    def _upgrade_charger_speed(self, params: Dict) -> Dict:
        """Upgrade chargers to faster charging speeds."""
        num_to_upgrade = params.get('num_chargers', 10)
        target_speed = params.get('power_kw', 150)  # DC fast charger
        
        upgraded = 0
        for station in list(self.infrastructure.charging_stations.values())[:num_to_upgrade]:
            old_power = station.power_kw
            station.power_kw = target_speed
            station.charger_type = 'dc_fast' if target_speed >= 50 else 'level2'
            upgraded += 1
        
        logger.info(f"  Upgraded {upgraded} chargers to {target_speed}kW")
        
        return {
            'upgraded_count': upgraded,
            'new_power_kw': target_speed
        }
    
    def _increase_ev_subsidy(self, params: Dict) -> Dict:
        """Increase EV subsidy amount."""
        amount = params.get('amount', 5000)  # £5000 additional subsidy
        
        # This would modify the scenario manager's active policies
        # For now, just log and track
        logger.info(f"  Increased EV subsidy by £{amount}")
        
        return {
            'subsidy_increase': amount,
            'action': 'increased_subsidy'
        }
    
    def _increase_grid_capacity(self, params: Dict) -> Dict:
        """Increase grid capacity (infrastructure investment)."""
        additional_mw = params.get('additional_mw', 5)
        region = params.get('region', 'default')
        
        if region in self.infrastructure.grid_regions:
            grid = self.infrastructure.grid_regions[region]
            old_capacity = grid.capacity_mw
            grid.capacity_mw += additional_mw
            
            # Track cost
            cost_per_mw = 1000000  # £1M per MW
            total_cost = additional_mw * cost_per_mw
            
            if self.active_combined and 'budget' in self.active_combined.constraints:
                budget = self.active_combined.constraints['budget']
                budget.current += total_cost
                self.infrastructure_capex += total_cost
            
            logger.info(f"  Grid capacity increased: {old_capacity:.0f} MW → {grid.capacity_mw:.0f} MW")
            
            return {
                'old_capacity_mw': old_capacity,
                'new_capacity_mw': grid.capacity_mw,
                'additional_mw': additional_mw,
                'cost': total_cost
            }
        
        return {'error': 'region_not_found'}
    
    def _apply_load_balancing(self, params: Dict) -> Dict:
        """Apply smart load balancing to distribute charging demand."""
        strategy = params.get('strategy', 'time_shift')
        
        # This would integrate with smart charging logic
        logger.info(f"  Load balancing activated: {strategy}")
        
        return {
            'strategy': strategy,
            'enabled': True
        }
    
    def _apply_congestion_charge(self, params: Dict) -> Dict:
        """Apply congestion charge to diesel vehicles (requires env access)."""
        charge_amount = params.get('amount', 15)  # £15 typical
        zone = params.get('zone', 'city_center')
        
        # This would modify mode costs in the environment
        # For now, track the policy
        logger.info(f"  Congestion charge applied: £{charge_amount} in {zone}")
        
        return {
            'charge_amount': charge_amount,
            'zone': zone,
            'affected_modes': ['car', 'van_diesel', 'truck_diesel']
        }
    
    def _ban_diesel_vehicles(self, params: Dict) -> Dict:
        """Ban diesel vehicles in specified zone."""
        zone = params.get('zone', 'city_center')
        affected_modes = params.get('modes', ['van_diesel', 'truck_diesel'])
        
        # This would modify mode availability in the environment
        logger.info(f"  Diesel ban in {zone}: {affected_modes}")
        
        return {
            'zone': zone,
            'banned_modes': affected_modes,
            'enforcement_date': self.simulation_state.get('step', 0)
        }
    
    # =====================================================================
    # Action Implementations
    # =====================================================================
    
    def _apply_surge_pricing(self, params: Dict) -> Dict:
        """Apply surge pricing during high grid load."""
        multiplier = params.get('multiplier', 2.0)
        duration_steps = params.get('duration_steps', 20)
        
        # Update pricing multiplier
        old_multiplier = self.current_price_multiplier
        self.current_price_multiplier = multiplier
        
        # Update all charging station costs
        for station in self.infrastructure.charging_stations.values():
            station.cost_per_kwh = self.base_charging_cost * multiplier
        
        logger.info(f"  Surge pricing: {old_multiplier:.2f}x → {multiplier:.2f}x")
        
        return {
            'old_multiplier': old_multiplier,
            'new_multiplier': multiplier,
            'affected_stations': len(self.infrastructure.charging_stations)
        }
    
    def _increase_charging_cost(self, params: Dict) -> Dict:
        """Increase charging cost for infrastructure cost recovery."""
        reason = params.get('reason', 'cost_recovery')
        
        if reason == 'infrastructure_cost_recovery':
            # Calculate cost based on utilization
            utilization = self.simulation_state.get('charger_utilization', 0.5)
            
            # Low utilization = high cost per charge (spread fixed costs)
            if utilization < 0.3:
                cost_multiplier = 1.5
            elif utilization < 0.5:
                cost_multiplier = 1.2
            else:
                cost_multiplier = 1.0
            
            self.current_price_multiplier = cost_multiplier
            
            # Update stations
            for station in self.infrastructure.charging_stations.values():
                station.cost_per_kwh = self.base_charging_cost * cost_multiplier
            
            logger.info(f"  Cost recovery pricing: {cost_multiplier:.2f}x (utilization: {utilization:.1%})")
            
            return {
                'utilization': utilization,
                'cost_multiplier': cost_multiplier,
                'reason': reason
            }
        
        return {}
    
    def _add_emergency_chargers(self, params: Dict) -> Dict:
        """Add chargers in response to high demand."""
        num_chargers = params.get('num_chargers', 10)
        strategy = params.get('strategy', 'demand_heatmap')
        
        # Check budget constraint
        if self.active_combined and 'budget' in self.active_combined.constraints:
            budget = self.active_combined.constraints['budget']
            cost_per_charger = 5000  # £5k per charger
            total_cost = num_chargers * cost_per_charger
            
            if budget.remaining() < total_cost:
                logger.warning(f"  Insufficient budget for {num_chargers} chargers (need £{total_cost:,}, have £{budget.remaining():,})")
                # Add what we can afford
                num_chargers = int(budget.remaining() / cost_per_charger)
                if num_chargers == 0:
                    return {'added': 0, 'reason': 'budget_exceeded'}
        
        # Add chargers
        new_stations = self.infrastructure.add_chargers_by_demand(
            num_chargers=num_chargers,
            strategy=strategy
        )
        
        # Update budget constraint
        if self.active_combined and 'budget' in self.active_combined.constraints:
            budget = self.active_combined.constraints['budget']
            budget.current += len(new_stations) * 5000
            self.infrastructure_capex += len(new_stations) * 5000
        
        logger.info(f"  Added {len(new_stations)} emergency chargers")
        
        return {
            'added': len(new_stations),
            'station_ids': new_stations,
            'strategy': strategy
        }
    
    def _reduce_ev_subsidy(self, params: Dict) -> Dict:
        """Reduce EV subsidy (phase-out logic)."""
        reduction_pct = params.get('reduction_percentage', 10)
        
        # Reduce subsidy in scenario manager
        # (This would require modifying active scenario's cost_reduction policies)
        
        logger.info(f"  Reducing EV subsidy by {reduction_pct}%")
        
        return {
            'reduction_percentage': reduction_pct
        }
    
    def _enable_smart_charging(self, params: Dict) -> Dict:
        """Enable smart charging optimization."""
        if not self.infrastructure.enable_tod_pricing:
            logger.warning("  Time-of-day pricing not enabled, cannot activate smart charging")
            return {'enabled': False, 'reason': 'tod_pricing_disabled'}
        
        logger.info("  Smart charging enabled")
        
        return {'enabled': True}
    
    def _enable_winter_protocols(self, params: Dict, step: int) -> bool:
        """
        Enable winter emergency protocols.
        
        Triggers during severe winter conditions to:
        - Increase charging subsidies
        - Deploy emergency infrastructure
        - Alert operators
        """
        try:
            # Get weather conditions from simulation_state (not self.state)
            temp = self.simulation_state.get('temperature', 10.0)
            ice_warning = self.simulation_state.get('ice_warning', False)
            snow_depth = self.simulation_state.get('snow_depth', 0.0)
            
            # Check if protocols needed
            severe_winter = (temp < 0) or ice_warning or (snow_depth > 5)
            
            if not severe_winter:
                logger.info("  Winter protocols not needed (conditions mild)")
                return False
            
            # Activate protocols
            subsidy_boost = params.get('subsidy_boost', 10000)  # £10k extra
            charging_discount = params.get('charging_discount', 0.5)  # 50% off
            
            # Update state (store in simulation_state)
            self.simulation_state['winter_protocols_active'] = True
            self.simulation_state['winter_subsidy_boost'] = subsidy_boost
            self.simulation_state['winter_charging_discount'] = charging_discount
            
            logger.info(f"  ❄️ Winter protocols ENABLED:")
            logger.info(f"     Temperature: {temp:.1f}°C")
            logger.info(f"     Ice warning: {ice_warning}")
            logger.info(f"     Snow depth: {snow_depth}cm")
            logger.info(f"     Extra subsidy: £{subsidy_boost}")
            logger.info(f"     Charging discount: {charging_discount*100}%")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to enable winter protocols: {e}")
            return False
    
    # =====================================================================
    # Feedback Loops
    # =====================================================================
    
    def apply_feedback_loops(self, step: int) -> List[Dict]:
        """Apply all active feedback loops."""
        if not self.active_combined:
            return []
        
        adjustments = []
        
        for loop in self.active_combined.feedback_loops:
            adjustment = loop.apply(self.simulation_state)
            if adjustment:
                adjustments.append({
                    'step': step,
                    'loop': loop.name,
                    'adjustments': adjustment
                })
        
        return adjustments
    
    # =====================================================================
    # Infrastructure Cost Recovery
    # =====================================================================
    
    def calculate_cost_recovery(self) -> Dict:
        """Calculate infrastructure cost recovery metrics."""
        # Revenue from charging
        roi = (self.charging_revenue / self.infrastructure_capex * 100) if self.infrastructure_capex > 0 else 0
        
        # Operating profit
        profit = self.charging_revenue - self.operating_costs
        
        # Payback period (years)
        annual_revenue = self.charging_revenue  # Assume current rate continues
        payback_years = (self.infrastructure_capex / annual_revenue) if annual_revenue > 0 else float('inf')
        
        return {
            'total_investment': self.infrastructure_capex,
            'total_revenue': self.charging_revenue,
            'operating_costs': self.operating_costs,
            'profit': profit,
            'roi_percentage': roi,
            'payback_years': payback_years,
            'break_even': profit >= 0
        }
    
    def record_charging_session(self, cost: float) -> None:
        """Record revenue from charging session."""
        self.charging_revenue += cost
        
        # Operating costs (10% of revenue)
        self.operating_costs += cost * 0.10
    
    # =====================================================================
    # Constraint Monitoring
    # =====================================================================
    
    def check_constraints(self) -> List[Dict]:
        """Check all constraints and return violations/warnings."""
        if not self.active_combined:
            return []
        
        issues = []
        
        for const_type, constraint in self.active_combined.constraints.items():
            if constraint.is_exceeded():
                issues.append({
                    'type': 'violation',
                    'constraint': const_type,
                    'limit': constraint.limit,
                    'current': constraint.current,
                    'utilization': constraint.utilization()
                })
                logger.error(f"❌ Constraint violated: {const_type} ({constraint.current}/{constraint.limit})")
            
            elif constraint.is_warning():
                issues.append({
                    'type': 'warning',
                    'constraint': const_type,
                    'limit': constraint.limit,
                    'current': constraint.current,
                    'utilization': constraint.utilization()
                })
                logger.warning(f"⚠️ Constraint warning: {const_type} ({constraint.utilization():.0%})")
        
        return issues
    
    # =====================================================================
    # Reporting
    # =====================================================================
    
    def get_status_report(self) -> Dict:
        """Get comprehensive status of dynamic policies."""
        if not self.active_combined:
            return {'active': False}
        
        # Constraint status
        constraint_status = {}
        for const_type, constraint in self.active_combined.constraints.items():
            constraint_status[const_type] = {
                'limit': constraint.limit,
                'current': constraint.current,
                'remaining': constraint.remaining(),
                'utilization': constraint.utilization(),
                'status': 'exceeded' if constraint.is_exceeded() else ('warning' if constraint.is_warning() else 'ok')
            }
        
        # Cost recovery
        cost_recovery = self.calculate_cost_recovery()
        
        return {
            'active': True,
            'scenario_name': self.active_combined.name,
            'base_scenarios': self.active_combined.base_scenarios,
            'simulation_state': self.simulation_state,
            'constraints': constraint_status,
            'cost_recovery': cost_recovery,
            'current_pricing_multiplier': self.current_price_multiplier,
            'total_interaction_rules': len(self.active_combined.interaction_rules),  # FIX: Added total rules
            'rules_triggered': len(self.active_combined.triggered_at_step),
            'active_feedback_loops': len(self.active_combined.feedback_loops)
        }


# ==========================================================================
# Predefined Feedback Loops
# ==========================================================================

def ev_adoption_infrastructure_loop(state: Dict, strength: float) -> Dict:
    """
    Positive feedback loop: More EVs → More infrastructure → More EVs
    
    But with tipping point: If utilization too high, slows adoption
    """
    ev_adoption = state.get('ev_adoption', 0)
    charger_util = state.get('charger_utilization', 0)
    
    adjustments = {}
    
    # If high adoption but low utilization → infrastructure overbuilt → waste
    if ev_adoption > 0.5 and charger_util < 0.3:
        adjustments['charging_cost_increase'] = 0.1 * strength
    
    # If high adoption and high utilization → infrastructure stressed → need more
    elif ev_adoption > 0.4 and charger_util > 0.8:
        adjustments['infrastructure_demand'] = 1.2 * strength
    
    return adjustments


def grid_stress_pricing_loop(state: Dict, strength: float) -> Dict:
    """
    Negative feedback loop: Grid stress → Higher prices → Delayed charging → Less stress
    """
    grid_util = state.get('grid_utilization', 0)
    
    adjustments = {}
    
    if grid_util > 0.8:
        # Increase prices to reduce demand
        price_increase = (grid_util - 0.8) * 2.0 * strength
        adjustments['price_multiplier'] = 1.0 + price_increase
    
    elif grid_util < 0.5:
        # Decrease prices to encourage charging
        price_decrease = (0.5 - grid_util) * 0.5 * strength
        adjustments['price_multiplier'] = 1.0 - price_decrease
    
    return adjustments