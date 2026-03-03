"""
scenarios/dynamic_policy_engine.py

Orchestrates dynamic policy application during simulation.

Phase 1 refactor: data models moved to policy_models.py.
This file now contains only the engine logic:
  - YAML loading / scenario activation
  - Per-step state updates and rule evaluation (with cooldown support)
  - Action dispatch and all action implementations
  - Feedback loops, constraint monitoring, and reporting
"""

from __future__ import annotations
from typing import Dict, List, Optional, Any
from pathlib import Path
import yaml
import logging

from scenarios.policy_models import (
    PolicyTrigger,       # re-exported for any callers that import it from here
    InteractionRule,
    PolicyConstraint,
    FeedbackLoop,
    CombinedScenario,
)

logger = logging.getLogger(__name__)


class DynamicPolicyEngine:
    """
    Manages policy combinations, interactions, and dynamic adjustments.

    Key features:
    1. Combine multiple scenarios
    2. Apply interaction rules based on simulation state (with cooldown)
    3. Enforce constraints (budget, grid, deployment)
    4. Model feedback loops
    5. Track infrastructure cost recovery
    """

    def __init__(self, infrastructure_manager, scenario_manager):
        """
        Args:
            infrastructure_manager: InfrastructureManager instance
            scenario_manager      : ScenarioManager instance
        """
        self.infrastructure = infrastructure_manager
        self.scenario_manager = scenario_manager

        # Active combined scenario
        self.active_combined: Optional[CombinedScenario] = None

        # State tracking
        self.simulation_state: Dict[str, Any] = {}
        self.policy_history: List[Dict] = []

        # Cost recovery tracking
        self.infrastructure_capex = 0.0
        self.charging_revenue = 0.0
        self.operating_costs = 0.0

        # Dynamic pricing state
        self.base_charging_cost = 0.15       # GBP/kWh baseline
        self.current_price_multiplier = 1.0

        logger.info("Dynamic Policy Engine initialized")

        # Phase 6.2b: Event bus for publishing policy changes
        self.event_bus = None  # Will be set by simulation loop

    # =======================================================================
    # Event Bus Integration
    # =======================================================================
    def set_event_bus(self, event_bus):
        """
        Connect event bus for policy event publishing.
        
        Called by simulation loop to inject event bus.
        
        Args:
            event_bus: SafeEventBus instance
        """
        self.event_bus = event_bus
        if event_bus and event_bus.is_available():
            logger.info("✅ Event bus connected to policy engine")

    # ======================================================================
    # Policy Event Publishing
    # 
    def _publish_policy_event(
        self,
        parameter: str,
        old_value: float,
        new_value: float,
        lat: float = 56.0,
        lon: float = -3.5,
        radius_km: float = 200.0
    ):
        """
        Publish policy change event.
        
        Args:
            parameter: Policy parameter name (e.g., 'carbon_tax')
            old_value: Previous value
            new_value: New value
            lat: Event center latitude (default: Scotland center)
            lon: Event center longitude
            radius_km: Event radius (default: 200km = nationwide)
        """
        if not self.event_bus or not self.event_bus.is_available():
            return
        
        try:
            from events.event_types import PolicyChangeEvent
            
            event = PolicyChangeEvent(
                parameter=parameter,
                old_value=old_value,
                new_value=new_value,
                lat=lat,
                lon=lon,
                radius_km=radius_km,
                source='policy_engine'
            )
            
            success = self.event_bus.publish(event)
            if success:
                logger.debug(f"📢 Published policy event: {parameter} {old_value}→{new_value}")
            
        except Exception as e:
            logger.debug(f"Policy event publish failed (non-critical): {e}")



    # =========================================================================
    # Scenario Loading & Activation
    # =========================================================================

    def load_combined_scenario(self, yaml_path: Path) -> CombinedScenario:
        """Load a combined scenario from a YAML file."""
        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f)

        # Parse interaction rules
        rules = []
        for rule_data in data.get('interaction_rules', []):
            rule = InteractionRule(
                condition=rule_data['condition'],
                action=rule_data['action'],
                parameters=rule_data.get('parameters', {}),
                priority=rule_data.get('priority', 0),
                cooldown_steps=rule_data.get('cooldown_steps', 0),
            )
            rules.append(rule)

        # Parse constraints
        constraints = {}
        for const_data in data.get('constraints', []):
            constraint = PolicyConstraint(
                constraint_type=const_data['type'],
                limit=const_data['limit'],
                warning_threshold=const_data.get('warning_threshold', 0.8),
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
                strength=loop_data.get('strength', 1.0),
            )
            feedback_loops.append(loop)

        combined = CombinedScenario(
            name=data['name'],
            description=data['description'],
            base_scenarios=data['base_scenarios'],
            interaction_rules=rules,
            constraints=constraints,
            feedback_loops=feedback_loops,
        )

        logger.info(f"Loaded combined scenario: {combined.name}")
        logger.info(f"  Base scenarios: {combined.base_scenarios}")
        logger.info(f"  Interaction rules: {len(combined.interaction_rules)}")
        logger.info(f"  Constraints: {len(combined.constraints)}")

        return combined

    def activate_combined_scenario(self, combined: CombinedScenario) -> None:
        """Activate a combined scenario and apply its base policies."""
        self.active_combined = combined

        for scenario_name in combined.base_scenarios:
            success = self.scenario_manager.activate_scenario(scenario_name)
            if success:
                logger.info(f"  Applied base scenario: {scenario_name}")
            else:
                logger.error(f"  Failed to apply: {scenario_name}")

        if 'budget' in combined.constraints:
            budget = combined.constraints['budget']
            logger.info(f"  Budget constraint: £{budget.limit:,.0f}")

        if 'grid_capacity' in combined.constraints:
            grid = combined.constraints['grid_capacity']
            logger.info(f"  Grid capacity constraint: {grid.limit:.0f} MW")

    # =========================================================================
    # Per-Step State & Rule Evaluation
    # =========================================================================

    def update_simulation_state(self, step: int, agents: List, env, infrastructure) -> None:
        """Refresh the simulation state snapshot used for condition evaluation."""
        ev_modes = ['ev', 'van_electric', 'truck_electric', 'hgv_electric']
        ev_count = sum(1 for a in agents if a.state.mode in ev_modes)
        total_agents = len(agents)

        grid_metrics = infrastructure.get_infrastructure_metrics()
        charger_util = grid_metrics.get('utilization', 0)

        self.simulation_state = {
            'step':                step,
            'time_of_day':         infrastructure.current_hour if hasattr(infrastructure, 'current_hour') else 8,
            'ev_adoption':         ev_count / max(1, total_agents),
            'ev_count':            ev_count,
            'total_agents':        total_agents,
            'grid_load':           grid_metrics.get('grid_load_mw', 0),
            'grid_capacity':       grid_metrics.get('grid_capacity_mw', 1000),
            'grid_utilization':    grid_metrics.get('grid_utilization', 0),
            'charger_utilization': charger_util,
            'occupied_chargers':   grid_metrics.get('occupied_ports', 0),
            'total_chargers':      grid_metrics.get('total_ports', 1),
            'avg_charging_cost':   self.base_charging_cost * self.current_price_multiplier,
        }

        # Attach weather data when a weather manager is present
        if hasattr(self, 'weather_manager') and self.weather_manager:
            conditions = self.weather_manager.current_conditions
            self.simulation_state['temperature']   = conditions.get('temperature', 10.0)
            self.simulation_state['precipitation']  = conditions.get('precipitation', 0.0)
            self.simulation_state['snow_depth']     = conditions.get('snow_depth', 0.0)
            self.simulation_state['ice_warning']    = conditions.get('ice_warning', False)
            self.simulation_state['wind_speed']     = conditions.get('wind_speed', 10.0)

        # Keep grid_capacity constraint current
        if self.active_combined:
            if 'grid_capacity' in self.active_combined.constraints:
                self.active_combined.constraints['grid_capacity'].current = (
                    self.simulation_state['grid_load']
                )

    def apply_interaction_rules(self, step: int) -> List[Dict]:
        """Evaluate all rules for the current step and execute qualifying actions."""
        if not self.active_combined or not self.active_combined.interaction_rules:
            return []

        actions_taken = []

        sorted_rules = sorted(
            self.active_combined.interaction_rules,
            key=lambda r: r.priority,
            reverse=True,
        )

        logger.info(f"========== POLICY DEBUG Step {step} ==========")
        logger.info(f"Grid utilization: {self.simulation_state.get('grid_utilization', 'N/A')}")
        logger.info(f"Grid load: {self.simulation_state.get('grid_load', 'N/A')} MW")
        logger.info(f"Grid capacity: {self.simulation_state.get('grid_capacity', 'N/A')} MW")
        logger.info(f"Charger utilization: {self.simulation_state.get('charger_utilization', 'N/A')}")
        logger.info(f"EV adoption: {self.simulation_state.get('ev_adoption', 'N/A')}")
        logger.info(f"Number of rules to check: {len(sorted_rules)}")

        for i, rule in enumerate(sorted_rules):
            logger.info(f"--- Rule {i+1}: {rule.action} ---")
            logger.info(f"  Condition: {rule.condition}")
            logger.info(f"  Priority: {rule.priority}")

            condition_result = rule.evaluate_condition(self.simulation_state)
            logger.info(f"  Condition result: {condition_result}")

            # Cooldown check — suppress if triggered too recently
            if condition_result and rule.cooldown_steps > 0:
                steps_since_trigger = step - rule.last_triggered_step
                if steps_since_trigger < rule.cooldown_steps:
                    logger.info(f"  ⏸️  COOLDOWN: {steps_since_trigger}/{rule.cooldown_steps} steps elapsed")
                    condition_result = False

            if condition_result:
                logger.info(f"  ✅ EXECUTING ACTION: {rule.action}")
                action_result = self._execute_action(rule, step)

                if action_result:
                    actions_taken.append({
                        'step':      step,
                        'condition': rule.condition,
                        'action':    rule.action,
                        'result':    action_result,
                    })

                    rule_key = f"{rule.action}_{rule.condition}"
                    self.active_combined.triggered_at_step[rule_key] = step
                    rule.last_triggered_step = step  # Update cooldown tracker

                    logger.info(f"  ✅ Action completed: {action_result}")
            else:
                logger.info(f"  ❌ Condition not met, skipping")

        logger.info(f"Total actions taken: {len(actions_taken)}")
        logger.info(f"==========================================")

        return actions_taken

    # =========================================================================
    # Action Dispatcher
    # =========================================================================

    def _execute_action(self, rule: InteractionRule, step: int) -> Optional[Dict]:
        """Dispatch a rule's action to the appropriate handler method."""
        action = rule.action
        params = rule.parameters

        # Pricing
        if action == 'apply_surge_pricing':
            return self._apply_surge_pricing(params)
        elif action == 'increase_charging_cost':
            return self._increase_charging_cost(params)
        elif action == 'reduce_charging_costs':
            return self._reduce_charging_costs(params)

        # Infrastructure
        elif action in ('add_emergency_chargers', 'add_chargers'):
            return self._add_emergency_chargers(params)
        elif action == 'relocate_chargers':
            return self._relocate_underutilized_chargers(params)
        elif action == 'upgrade_charger_speed':
            return self._upgrade_charger_speed(params)
        elif action == 'add_depot_chargers':
            return self._add_depot_chargers(params)

        # Grid
        elif action == 'enable_smart_charging':
            return self._enable_smart_charging(params)
        elif action == 'increase_grid_capacity':
            return self._increase_grid_capacity(params)
        elif action == 'expand_grid_capacity':
            return self._expand_grid_capacity(params)
        elif action == 'load_balancing':
            return self._apply_load_balancing(params)

        # Subsidies & policy
        elif action == 'reduce_ev_subsidy':
            return self._reduce_ev_subsidy(params)
        elif action == 'increase_ev_subsidy':
            return self._increase_ev_subsidy(params)
        elif action == 'apply_congestion_charge':
            return self._apply_congestion_charge(params)
        elif action == 'ban_diesel_vehicles':
            return self._ban_diesel_vehicles(params)

        # Weather
        elif action == 'activate_winter_gritting':
            self.simulation_state['ice_warning'] = False
            logger.info(f"Step {step}: Activated winter gritting")
        elif action == 'close_routes':
            logger.info(f"Step {step}: Closed routes in {params.get('region', 'all')} due to weather")
        elif action == 'emergency_transit':
            logger.info(f"Step {step}: Emergency transit boost ({params.get('frequency_multiplier', 1.5)}x)")
        elif action == 'reduce_charging_time':
            logger.info(f"Step {step}: Charging time reduced to {params.get('reduction_factor', 0.8)*100}%")
        elif action == 'enable_winter_protocols':
            return self._enable_winter_protocols(params, step)

        else:
            logger.warning(f"Unknown action: {action}")
            return None

    # =========================================================================
    # Action Implementations — Pricing
    # =========================================================================

    def _apply_surge_pricing(self, params: Dict) -> Dict:
        """Apply surge pricing during high grid load."""
        multiplier = params.get('multiplier', 2.0)
        old_multiplier = self.current_price_multiplier
        self.current_price_multiplier = multiplier
        for station in self.infrastructure.charging_stations.values():
            station.cost_per_kwh = self.base_charging_cost * multiplier

        logger.info(f"  Surge pricing: {old_multiplier:.2f}x → {multiplier:.2f}x")
        
        # Phase 6.2b: Publish policy event
        self._publish_policy_event(
            parameter='charging_price_multiplier',
            old_value=old_multiplier,
            new_value=multiplier,
            radius_km=200.0
        )
        
        return {
            'old_multiplier':    old_multiplier,
            'new_multiplier':    multiplier,
            'affected_stations': len(self.infrastructure.charging_stations),
        }

    def _increase_charging_cost(self, params: Dict) -> Dict:
        """Increase charging cost for infrastructure cost recovery."""
        reason = params.get('reason', 'cost_recovery')
        if reason == 'infrastructure_cost_recovery':
            utilization = self.simulation_state.get('charger_utilization', 0.5)
            cost_multiplier = 1.5 if utilization < 0.3 else 1.2 if utilization < 0.5 else 1.0
            self.current_price_multiplier = cost_multiplier
            for station in self.infrastructure.charging_stations.values():
                station.cost_per_kwh = self.base_charging_cost * cost_multiplier
            logger.info(f"  Cost recovery pricing: {cost_multiplier:.2f}x (utilization: {utilization:.1%})")
            return {'utilization': utilization, 'cost_multiplier': cost_multiplier, 'reason': reason}
        return {}

    def _reduce_charging_costs(self, params: Dict) -> Dict:
        """Reduce charging costs to incentivise EV adoption."""
        multiplier = params.get('multiplier', 0.8)
        old_multiplier = self.current_price_multiplier
        self.current_price_multiplier = multiplier
        updated = 0
        for station in self.infrastructure.charging_stations.values():
            station.cost_per_kwh = self.base_charging_cost * multiplier
            updated += 1
        logger.info(f"  Charging cost reduction: {old_multiplier:.2f}x → {multiplier:.2f}x ({updated} stations)")
        return {
            'old_multiplier':      old_multiplier,
            'new_multiplier':      multiplier,
            'discount_percentage': (1 - multiplier) * 100,
            'stations_updated':    updated,
        }

    # =========================================================================
    # Action Implementations — Infrastructure
    # =========================================================================

    def _add_emergency_chargers(self, params: Dict) -> Dict:
        """Add public chargers in response to high demand."""
        num_chargers = params.get('num_chargers', 10)
        strategy = params.get('strategy', 'demand_heatmap')

        if self.active_combined and 'budget' in self.active_combined.constraints:
            budget = self.active_combined.constraints['budget']
            cost_per_charger = 5000
            total_cost = num_chargers * cost_per_charger
            if budget.remaining() < total_cost:
                logger.warning(
                    f"  Insufficient budget for {num_chargers} chargers "
                    f"(need £{total_cost:,}, have £{budget.remaining():,})"
                )
                num_chargers = int(budget.remaining() / cost_per_charger)
                if num_chargers == 0:
                    return {'added': 0, 'reason': 'budget_exceeded'}

        new_stations = self.infrastructure.add_chargers_by_demand(
            num_chargers=num_chargers, strategy=strategy
        )

        if self.active_combined and 'budget' in self.active_combined.constraints:
            budget = self.active_combined.constraints['budget']
            budget.current += len(new_stations) * 5000
            self.infrastructure_capex += len(new_stations) * 5000

        logger.info(f"  Added {len(new_stations)} emergency chargers")

        # Phase 6.2b: Publish policy event
        self._publish_policy_event(
            parameter='emergency_chargers',
            old_value=0,
            new_value=params.get('count', 10),
            radius_km=50.0  # Emergency chargers are regional
        )
        
        return {'added': len(new_stations), 'station_ids': new_stations, 'strategy': strategy}

    def _relocate_underutilized_chargers(self, params: Dict) -> Dict:
        """Relocate underutilised chargers to high-demand areas."""
        num_to_relocate = params.get('num_chargers', 5)
        utilization_threshold = params.get('utilization_threshold', 0.2)

        underutilized = [
            sid for sid, station in self.infrastructure.charging_stations.items()
            if hasattr(station, 'utilization_history') and
            sum(station.utilization_history) / max(1, len(station.utilization_history)) < utilization_threshold
        ]

        relocated_count = min(num_to_relocate, len(underutilized))
        for station_id in underutilized[:relocated_count]:
            self.infrastructure.charging_stations.pop(station_id, None)

        new_stations = self.infrastructure.add_chargers_by_demand(
            num_chargers=relocated_count, strategy='demand_heatmap'
        )
        logger.info(f"  Relocated {relocated_count} underutilised chargers to high-demand areas")
        return {'relocated_count': relocated_count, 'new_station_ids': new_stations,
                'threshold': utilization_threshold}

    def _upgrade_charger_speed(self, params: Dict) -> Dict:
        """Upgrade chargers to faster charging speeds."""
        num_to_upgrade = params.get('num_chargers', 10)
        target_speed = params.get('power_kw', 150)
        upgraded = 0
        for station in list(self.infrastructure.charging_stations.values())[:num_to_upgrade]:
            station.power_kw = target_speed
            station.charger_type = 'dc_fast' if target_speed >= 50 else 'level2'
            upgraded += 1
        logger.info(f"  Upgraded {upgraded} chargers to {target_speed}kW")
        return {'upgraded_count': upgraded, 'new_power_kw': target_speed}

    def _add_depot_chargers(self, params: Dict) -> Dict:
        """Add depot charging infrastructure for commercial/freight vehicles."""
        num_depots = params.get('num_depots', 5)
        chargers_per_depot = params.get('chargers_per_depot', 10)
        power_kw = params.get('power_kw', 150)

        if not hasattr(self.infrastructure, 'depots'):
            logger.warning("  Infrastructure does not have depot manager")
            return {'error': 'no_depot_manager'}

        import random
        added_depots = 0
        total_chargers = 0

        for i in range(num_depots):
            depot_id = f"policy_depot_{len(self.infrastructure.depots.depots) + i + 1:03d}"
            lon = random.uniform(-3.35, -3.05)
            lat = random.uniform(55.85, 56.00)
            self.infrastructure.depots.add_depot(
                depot_id=depot_id,
                location=(lon, lat),
                depot_type='freight',
                num_chargers=chargers_per_depot,
                charger_power_kw=power_kw,
            )
            added_depots += 1
            total_chargers += chargers_per_depot

        cost_per_charger = 50000
        total_cost = total_chargers * cost_per_charger

        if self.active_combined and 'budget' in self.active_combined.constraints:
            self.active_combined.constraints['budget'].current += total_cost
            self.infrastructure_capex += total_cost

        logger.info(
            f"  Added {added_depots} depot(s) with {total_chargers} chargers "
            f"({chargers_per_depot} chargers/depot @ {power_kw} kW)"
        )
        
        # Phase 6.2b: Publish policy event
        self._publish_policy_event(
            parameter='depot_chargers',
            old_value=0,  # Could track previous count if needed
            new_value=total_chargers,
            radius_km=200.0
        )
        
        return {
            'depots_added':       added_depots,
            'total_chargers':     total_chargers,
            'chargers_per_depot': chargers_per_depot,
            'power_kw':           power_kw,
            'cost':               total_cost,
        }

    # =========================================================================
    # Action Implementations — Grid
    # =========================================================================

    def _increase_grid_capacity(self, params: Dict) -> Dict:
        """Increase grid capacity by a fixed MW amount."""
        additional_mw = params.get('additional_mw', 5)
        region = params.get('region', 'default')

        if region not in self.infrastructure.grid_regions:
            return {'error': 'region_not_found'}

        grid = self.infrastructure.grid_regions[region]
        old_capacity = grid.capacity_mw
        grid.capacity_mw += additional_mw
        total_cost = additional_mw * 1_000_000

        if self.active_combined and 'budget' in self.active_combined.constraints:
            self.active_combined.constraints['budget'].current += total_cost
            self.infrastructure_capex += total_cost

        logger.info(f"  Grid capacity increased: {old_capacity:.0f} MW → {grid.capacity_mw:.0f} MW")
        
        # Phase 6.2b: Publish policy event
        self._publish_policy_event(
            parameter='grid_capacity_mw',
            old_value=old_capacity,
            new_value=grid.capacity_mw,
            radius_km=100.0  # Grid region specific
        )
        
        return {'old_capacity_mw': old_capacity, 'new_capacity_mw': grid.capacity_mw,
                'additional_mw': additional_mw, 'cost': total_cost}

    def _expand_grid_capacity(self, params: Dict) -> Dict:
        """Expand grid capacity by a multiplier (e.g. 1.3 = 30 % increase)."""
        increase_by = params.get('increase_by', 1.5)
        region = params.get('region', 'default')

        if region not in self.infrastructure.grid_regions:
            logger.warning(f"  Grid region '{region}' not found")
            return {'error': 'region_not_found'}

        grid = self.infrastructure.grid_regions[region]
        old_capacity = grid.capacity_mw
        additional_mw = old_capacity * (increase_by - 1.0)
        grid.capacity_mw = old_capacity * increase_by
        total_cost = additional_mw * 1_000_000

        if self.active_combined and 'budget' in self.active_combined.constraints:
            self.active_combined.constraints['budget'].current += total_cost
            self.infrastructure_capex += total_cost

        logger.info(f"  Grid capacity expanded: {old_capacity:.0f} MW → {grid.capacity_mw:.0f} MW ({increase_by}x)")
        return {
            'old_capacity_mw':     old_capacity,
            'new_capacity_mw':     grid.capacity_mw,
            'increase_multiplier': increase_by,
            'additional_mw':       additional_mw,
            'cost':                total_cost,
        }

    def _enable_smart_charging(self, params: Dict) -> Dict:
        """Enable smart charging optimisation."""
        if not self.infrastructure.enable_tod_pricing:
            logger.warning("  Time-of-day pricing not enabled, cannot activate smart charging")
            return {'enabled': False, 'reason': 'tod_pricing_disabled'}
        logger.info("  Smart charging enabled")
        return {'enabled': True}

    def _apply_load_balancing(self, params: Dict) -> Dict:
        """Apply smart load balancing to distribute charging demand."""
        strategy = params.get('strategy', 'time_shift')
        logger.info(f"  Load balancing activated: {strategy}")
        return {'strategy': strategy, 'enabled': True}

    # =========================================================================
    # Action Implementations — Subsidies & Policy
    # =========================================================================

    def _reduce_ev_subsidy(self, params: Dict) -> Dict:
        """Reduce EV subsidy (phase-out logic)."""
        reduction_pct = params.get('reduction_percentage', 10)
        logger.info(f"  Reducing EV subsidy by {reduction_pct}%")
        return {'reduction_percentage': reduction_pct}

    def _increase_ev_subsidy(self, params: Dict) -> Dict:
        """Increase EV subsidy amount."""
        amount = params.get('amount', 5000)
        logger.info(f"  Increased EV subsidy by £{amount}")
        return {'subsidy_increase': amount, 'action': 'increased_subsidy'}

    def _apply_congestion_charge(self, params: Dict) -> Dict:
        """Apply congestion charge to diesel vehicles."""
        charge_amount = params.get('amount', 15)
        zone = params.get('zone', 'city_center')
        logger.info(f"  Congestion charge applied: £{charge_amount} in {zone}")
        return {'charge_amount': charge_amount, 'zone': zone,
                'affected_modes': ['car', 'van_diesel', 'truck_diesel']}

    def _ban_diesel_vehicles(self, params: Dict) -> Dict:
        """Ban diesel vehicles in a specified zone."""
        zone = params.get('zone', 'city_center')
        affected_modes = params.get('modes', ['van_diesel', 'truck_diesel'])
        logger.info(f"  Diesel ban in {zone}: {affected_modes}")
        return {'zone': zone, 'banned_modes': affected_modes,
                'enforcement_date': self.simulation_state.get('step', 0)}

    # =========================================================================
    # Action Implementations — Weather
    # =========================================================================

    def _enable_winter_protocols(self, params: Dict, step: int) -> bool:
        """Activate winter emergency protocols during severe conditions."""
        try:
            temp        = self.simulation_state.get('temperature', 10.0)
            ice_warning = self.simulation_state.get('ice_warning', False)
            snow_depth  = self.simulation_state.get('snow_depth', 0.0)

            if not ((temp < 0) or ice_warning or (snow_depth > 5)):
                logger.info("  Winter protocols not needed (conditions mild)")
                return False

            subsidy_boost     = params.get('subsidy_boost', 10000)
            charging_discount = params.get('charging_discount', 0.5)

            self.simulation_state['winter_protocols_active']  = True
            self.simulation_state['winter_subsidy_boost']     = subsidy_boost
            self.simulation_state['winter_charging_discount'] = charging_discount

            logger.info(f"  ❄️ Winter protocols ENABLED: {temp:.1f}°C, ice={ice_warning}, snow={snow_depth}cm")
            logger.info(f"     Extra subsidy: £{subsidy_boost} | Discount: {charging_discount*100}%")
            return True

        except Exception as e:
            logger.error(f"Failed to enable winter protocols: {e}")
            return False

    # =========================================================================
    # Feedback Loops
    # =========================================================================

    def apply_feedback_loops(self, step: int) -> List[Dict]:
        """Apply all active feedback loops for the current step."""
        if not self.active_combined:
            return []
        adjustments = []
        for loop in self.active_combined.feedback_loops:
            adjustment = loop.apply(self.simulation_state)
            if adjustment:
                adjustments.append({'step': step, 'loop': loop.name, 'adjustments': adjustment})
        return adjustments

    # =========================================================================
    # Cost Recovery
    # =========================================================================

    def calculate_cost_recovery(self) -> Dict:
        """Calculate infrastructure cost recovery metrics."""
        roi = (self.charging_revenue / self.infrastructure_capex * 100) if self.infrastructure_capex > 0 else 0
        profit = self.charging_revenue - self.operating_costs
        payback_years = (self.infrastructure_capex / self.charging_revenue) if self.charging_revenue > 0 else float('inf')
        return {
            'total_investment': self.infrastructure_capex,
            'total_revenue':    self.charging_revenue,
            'operating_costs':  self.operating_costs,
            'profit':           profit,
            'roi_percentage':   roi,
            'payback_years':    payback_years,
            'break_even':       profit >= 0,
        }

    def record_charging_session(self, cost: float) -> None:
        """Record revenue from a completed charging session."""
        self.charging_revenue += cost
        self.operating_costs  += cost * 0.10  # 10 % operating overhead

    # =========================================================================
    # Constraint Monitoring
    # =========================================================================

    def check_constraints(self) -> List[Dict]:
        """Check all constraints and return a list of violations and warnings."""
        if not self.active_combined:
            return []

        issues = []
        for const_type, constraint in self.active_combined.constraints.items():
            if constraint.is_exceeded():
                issues.append({
                    'type': 'violation', 'constraint': const_type,
                    'limit': constraint.limit, 'current': constraint.current,
                    'utilization': constraint.utilization(),
                })
                logger.error(f"❌ Constraint violated: {const_type} ({constraint.current}/{constraint.limit})")
            elif constraint.is_warning():
                issues.append({
                    'type': 'warning', 'constraint': const_type,
                    'limit': constraint.limit, 'current': constraint.current,
                    'utilization': constraint.utilization(),
                })
                logger.warning(f"⚠️ Constraint warning: {const_type} ({constraint.utilization():.0%})")

        return issues

    # =========================================================================
    # Reporting
    # =========================================================================

    def get_status_report(self) -> Dict:
        """Return a comprehensive status snapshot of the active policy engine."""
        if not self.active_combined:
            return {'active': False}

        constraint_status = {
            const_type: {
                'limit':       c.limit,
                'current':     c.current,
                'remaining':   c.remaining(),
                'utilization': c.utilization(),
                'status':      'exceeded' if c.is_exceeded() else 'warning' if c.is_warning() else 'ok',
            }
            for const_type, c in self.active_combined.constraints.items()
        }

        return {
            'active':                    True,
            'scenario_name':             self.active_combined.name,
            'base_scenarios':            self.active_combined.base_scenarios,
            'simulation_state':          self.simulation_state,
            'constraints':               constraint_status,
            'cost_recovery':             self.calculate_cost_recovery(),
            'current_pricing_multiplier':self.current_price_multiplier,
            'total_interaction_rules':   len(self.active_combined.interaction_rules),
            'rules_triggered':           len(self.active_combined.triggered_at_step),
            'active_feedback_loops':     len(self.active_combined.feedback_loops),
        }


# =============================================================================
# Predefined Feedback Loop Functions
# (pass as update_function when constructing FeedbackLoop objects)
# =============================================================================

def ev_adoption_infrastructure_loop(state: Dict, strength: float) -> Dict:
    """Positive feedback: More EVs → more infrastructure → more EVs."""
    ev_adoption  = state.get('ev_adoption', 0)
    charger_util = state.get('charger_utilization', 0)
    if ev_adoption > 0.5 and charger_util < 0.3:
        return {'charging_cost_increase': 0.1 * strength}
    if ev_adoption > 0.4 and charger_util > 0.8:
        return {'infrastructure_demand': 1.2 * strength}
    return {}


def grid_stress_pricing_loop(state: Dict, strength: float) -> Dict:
    """Negative feedback: Grid stress → higher prices → delayed charging → less stress."""
    grid_util = state.get('grid_utilization', 0)
    if grid_util > 0.8:
        return {'price_multiplier': 1.0 + (grid_util - 0.8) * 2.0 * strength}
    if grid_util < 0.5:
        return {'price_multiplier': 1.0 - (0.5 - grid_util) * 0.5 * strength}
    return {}