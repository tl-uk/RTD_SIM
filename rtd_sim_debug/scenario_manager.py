# scenarios/scenario_manager.py
"""
Phase 4.5B: Policy Scenario Framework

Enables YAML-based policy configurations with runtime injection.
Supports what-if analysis and automated policy testing.

UPDATED: Handles multi-document YAML files (multiple scenarios per file)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
import yaml
import logging

logger = logging.getLogger(__name__)


@dataclass
class PolicyModifier:
    """Single policy modification to apply."""
    parameter: str  # e.g., 'car_cost_multiplier', 'ev_subsidy_percent'
    value: Any
    target: str  # 'mode', 'infrastructure', 'grid', 'agent_desire'
    mode: Optional[str] = None  # specific mode if target='mode'


@dataclass
class Scenario:
    """Complete policy scenario configuration."""
    name: str
    description: str
    policies: List[PolicyModifier]
    duration: int  # simulation steps
    expected_outcomes: Dict[str, float]
    metadata: Dict[str, Any]


class ScenarioManager:
    """Manages policy scenarios and runtime injection."""
    
    def __init__(self, scenarios_dir: Optional[Path] = None):
        """Initialize scenario manager."""
        if scenarios_dir is None:
            scenarios_dir = Path(__file__).parent / 'configs'
        self.scenarios_dir = Path(scenarios_dir)
        self.scenarios: Dict[str, Scenario] = {}
        self.active_scenario: Optional[Scenario] = None
        
        if self.scenarios_dir.exists():
            self.load_all_scenarios()
    
    def load_all_scenarios(self) -> None:
        """
        Load all YAML scenario files.
        
        UPDATED: Handles multi-document YAML files with '---' separators.
        """
        if not self.scenarios_dir.exists():
            logger.warning(f"Scenarios directory not found: {self.scenarios_dir}")
            return
        
        yaml_files = list(self.scenarios_dir.glob('*.yaml'))
        total_loaded = 0
        
        for yaml_file in yaml_files:
            try:
                # FIXED: Load all documents from file (handles '---' separators)
                scenarios_from_file = self.load_scenarios_from_file(yaml_file)
                
                for scenario in scenarios_from_file:
                    self.scenarios[scenario.name] = scenario
                    logger.info(f"Loaded scenario: {scenario.name}")
                    total_loaded += 1
                    
            except Exception as e:
                logger.error(f"Failed to load {yaml_file}: {e}")
        
        logger.info(f"Loaded {total_loaded} scenarios from {len(yaml_files)} files")
    
    def load_scenarios_from_file(self, path: Path) -> List[Scenario]:
        """
        Load all scenarios from a single YAML file.
        
        Args:
            path: Path to YAML file
        
        Returns:
            List of Scenario objects (one per document in file)
        """
        scenarios = []
        
        with open(path, 'r') as f:
            # CRITICAL FIX: Use safe_load_all to handle multi-document YAML
            documents = yaml.safe_load_all(f)
            
            for doc in documents:
                if doc is None:
                    continue
                
                if 'name' not in doc:
                    logger.warning(f"Scenario in {path.name} missing 'name' field, skipping")
                    continue
                
                # Parse policies
                policies = []
                for p in doc.get('policies', []):
                    policies.append(PolicyModifier(
                        parameter=p['parameter'],
                        value=p['value'],
                        target=p['target'],
                        mode=p.get('mode')
                    ))
                
                # Create scenario object
                scenario = Scenario(
                    name=doc['name'],
                    description=doc.get('description', ''),
                    policies=policies,
                    duration=doc.get('duration', 100),
                    expected_outcomes=doc.get('expected_outcomes', {}),
                    metadata=doc.get('metadata', {})
                )
                
                scenarios.append(scenario)
        
        return scenarios
    
    def load_scenario(self, path: Path) -> Scenario:
        """
        Load single scenario from YAML (legacy method - kept for compatibility).
        
        NOTE: This now loads the FIRST scenario from the file.
        Use load_scenarios_from_file() to get all scenarios.
        """
        scenarios = self.load_scenarios_from_file(path)
        if not scenarios:
            raise ValueError(f"No valid scenarios found in {path}")
        return scenarios[0]
    
    def activate_scenario(self, scenario_name: str) -> bool:
        """Activate a scenario for the next simulation."""
        if scenario_name not in self.scenarios:
            logger.error(f"Scenario not found: {scenario_name}")
            logger.info(f"Available scenarios: {list(self.scenarios.keys())}")
            return False
        
        self.active_scenario = self.scenarios[scenario_name]
        logger.info(f"Activated scenario: {scenario_name}")
        return True
    
    def apply_to_environment(self, env) -> None:
        """Apply active scenario policies to environment."""
        if not self.active_scenario:
            return
        
        logger.info(f"Applying scenario: {self.active_scenario.name}")
        
        for policy in self.active_scenario.policies:
            try:
                self._apply_policy(policy, env)
            except Exception as e:
                logger.error(f"Failed to apply policy {policy.parameter}: {e}")
    
    def _apply_policy(self, policy: PolicyModifier, env) -> None:
        """Apply single policy modification."""
        if policy.target == 'mode':
            self._apply_mode_policy(policy, env)
        elif policy.target == 'infrastructure':
            # Infrastructure policies are handled in simulation_loop.py
            logger.debug(f"Infrastructure policy {policy.parameter} will be applied in simulation_loop")
        elif policy.target == 'grid':
            self._apply_grid_policy(policy, env)
        elif policy.target == 'agent_desire':
            self._apply_desire_policy(policy, env)
        else:
            logger.warning(f"Unknown policy target: {policy.target}")
    
    def _apply_mode_policy(self, policy: PolicyModifier, env) -> None:
        """Modify mode-specific parameters."""
        metrics = env.metrics_calculator
        
        if policy.parameter == 'cost_multiplier':
            # Modify cost for specific mode
            if policy.mode and policy.mode in metrics.cost:
                old_cost = metrics.cost[policy.mode]
                metrics.cost[policy.mode] = {
                    'base': old_cost['base'] * policy.value,
                    'per_km': old_cost['per_km'] * policy.value
                }
                logger.info(f"Applied {policy.value}x cost multiplier to {policy.mode}")
        
        elif policy.parameter == 'cost_reduction':
            # Reduce cost by percentage (e.g., EV subsidy)
            if policy.mode and policy.mode in metrics.cost:
                old_cost = metrics.cost[policy.mode]
                multiplier = 1.0 - (policy.value / 100.0)
                metrics.cost[policy.mode] = {
                    'base': old_cost['base'] * multiplier,
                    'per_km': old_cost['per_km'] * multiplier
                }
                logger.info(f"Reduced {policy.mode} cost by {policy.value}%")
        
        elif policy.parameter == 'speed_multiplier':
            # Modify speed (e.g., bus lanes)
            if policy.mode and policy.mode in metrics.speed:
                old_speed = metrics.speed[policy.mode]
                metrics.speed[policy.mode] = {
                    'city': old_speed['city'] * policy.value,
                    'highway': old_speed['highway'] * policy.value
                }
                logger.info(f"Applied {policy.value}x speed multiplier to {policy.mode}")
        
        elif policy.parameter == 'ban':
            # Mode ban in specific zone (not implemented yet - needs zone support)
            logger.warning(f"Mode ban not yet implemented: {policy.mode}")
    
    def _apply_infrastructure_policy(self, policy: PolicyModifier, env) -> None:
        """
        Modify charging infrastructure.
        
        NOTE: Most infrastructure policies are now handled in simulation_loop.py
        """
        if not hasattr(env, 'infrastructure'):
            logger.warning("Environment has no infrastructure manager")
            return
        
        infra = env.infrastructure
        
        if policy.parameter == 'add_chargers':
            # This is now handled in simulation_loop.py
            logger.debug(f"add_chargers policy will be applied in simulation_loop")
        
        elif policy.parameter == 'charging_cost_multiplier':
            # Modify charging costs
            for station_id, station in infra.charging_stations.items():
                station.cost_per_kwh *= policy.value
            logger.info(f"Applied {policy.value}x charging cost multiplier")
        
        elif policy.parameter == 'increase_capacity':
            # This is now handled in simulation_loop.py
            logger.debug(f"increase_capacity policy will be applied in simulation_loop")
    
    def _apply_grid_policy(self, policy: PolicyModifier, env) -> None:
        """Modify grid parameters."""
        if not hasattr(env, 'infrastructure'):
            return
        
        infra = env.infrastructure
        
        if policy.parameter == 'peak_pricing_multiplier':
            # This would need time-of-day implementation
            logger.info(f"Peak pricing multiplier: {policy.value}x (needs time-of-day)")
    
    def _apply_desire_policy(self, policy: PolicyModifier, env) -> None:
        """Modify agent desire distributions (population-level)."""
        # This would affect new agents created after policy
        if policy.parameter == 'eco_awareness_boost':
            # Increase eco desire across population
            logger.info(f"Eco awareness boost: +{policy.value} (affects new agents)")
    
    def get_scenario_report(self) -> Dict[str, Any]:
        """Generate report on active scenario."""
        if not self.active_scenario:
            return {'status': 'no_active_scenario'}
        
        return {
            'name': self.active_scenario.name,
            'description': self.active_scenario.description,
            'num_policies': len(self.active_scenario.policies),
            'policies': [
                {
                    'parameter': p.parameter,
                    'value': p.value,
                    'target': p.target,
                    'mode': p.mode
                }
                for p in self.active_scenario.policies
            ],
            'expected_outcomes': self.active_scenario.expected_outcomes,
            'duration': self.active_scenario.duration
        }
    
    def list_scenarios(self) -> List[str]:
        """Get list of available scenario names."""
        return sorted(list(self.scenarios.keys()))
    
    def get_scenario_info(self, name: str) -> Optional[Dict]:
        """Get info about a specific scenario."""
        if name not in self.scenarios:
            return None
        
        scenario = self.scenarios[name]
        return {
            'name': scenario.name,
            'description': scenario.description,
            'num_policies': len(scenario.policies),
            'expected_outcomes': scenario.expected_outcomes,
            'metadata': scenario.metadata
        }
    
    def get_scenarios_by_type(self, policy_type: str) -> List[str]:
        """
        Get scenarios of a specific type.
        
        Args:
            policy_type: Type from metadata (e.g., 'comprehensive_electrification')
        
        Returns:
            List of scenario names matching the type
        """
        matching = []
        for name, scenario in self.scenarios.items():
            if scenario.metadata.get('policy_type') == policy_type:
                matching.append(name)
        return matching
    
    def get_infrastructure_scenarios(self) -> List[str]:
        """Get scenarios that modify infrastructure."""
        infrastructure_scenarios = []
        for name, scenario in self.scenarios.items():
            for policy in scenario.policies:
                if policy.target == 'infrastructure':
                    infrastructure_scenarios.append(name)
                    break
        return infrastructure_scenarios


def create_example_scenarios(output_dir: Path) -> None:
    """Create example scenario YAML files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    scenarios = [
        {
            'name': 'EV Subsidy 30%',
            'description': 'Government subsidizes EVs by 30% to boost adoption',
            'policies': [
                {
                    'parameter': 'cost_reduction',
                    'value': 30.0,
                    'target': 'mode',
                    'mode': 'ev'
                },
                {
                    'parameter': 'cost_reduction',
                    'value': 30.0,
                    'target': 'mode',
                    'mode': 'van_electric'
                }
            ],
            'duration': 100,
            'expected_outcomes': {
                'ev_adoption_increase': 0.4,
                'car_reduction': 0.2,
                'emissions_reduction': 0.15
            },
            'metadata': {
                'policy_type': 'financial_incentive',
                'target_group': 'all_users'
            }
        },
        {
            'name': 'Congestion Charge',
            'description': 'London-style £15 congestion charge in city center',
            'policies': [
                {
                    'parameter': 'cost_multiplier',
                    'value': 4.0,
                    'target': 'mode',
                    'mode': 'car'
                },
                {
                    'parameter': 'cost_multiplier',
                    'value': 3.0,
                    'target': 'mode',
                    'mode': 'van_diesel'
                }
            ],
            'duration': 100,
            'expected_outcomes': {
                'car_reduction': 0.3,
                'bus_increase': 0.2,
                'ev_increase': 0.1
            },
            'metadata': {
                'policy_type': 'congestion_pricing',
                'zone': 'city_center'
            }
        },
        {
            'name': 'Bus Rapid Transit',
            'description': 'Dedicated bus lanes increase bus speeds by 40%',
            'policies': [
                {
                    'parameter': 'speed_multiplier',
                    'value': 1.4,
                    'target': 'mode',
                    'mode': 'bus'
                },
                {
                    'parameter': 'cost_reduction',
                    'value': 20.0,
                    'target': 'mode',
                    'mode': 'bus'
                }
            ],
            'duration': 100,
            'expected_outcomes': {
                'bus_increase': 0.35,
                'car_reduction': 0.2,
                'travel_time_reduction': 0.15
            },
            'metadata': {
                'policy_type': 'infrastructure_improvement',
                'infrastructure': 'dedicated_lanes'
            }
        },
        {
            'name': 'Freight Electrification',
            'description': 'Subsidize electric vans and add freight charging stations',
            'policies': [
                {
                    'parameter': 'cost_reduction',
                    'value': 40.0,
                    'target': 'mode',
                    'mode': 'van_electric'
                },
                {
                    'parameter': 'add_chargers',
                    'value': 20,
                    'target': 'infrastructure'
                }
            ],
            'duration': 100,
            'expected_outcomes': {
                'van_electric_increase': 0.6,
                'van_diesel_reduction': 0.5,
                'freight_emissions_reduction': 0.4
            },
            'metadata': {
                'policy_type': 'sector_specific',
                'target_sector': 'freight'
            }
        },
        {
            'name': 'Car Free Zone',
            'description': 'Ban private cars in city center, promote active transport',
            'policies': [
                {
                    'parameter': 'cost_multiplier',
                    'value': 10.0,
                    'target': 'mode',
                    'mode': 'car'
                },
                {
                    'parameter': 'cost_reduction',
                    'value': 50.0,
                    'target': 'mode',
                    'mode': 'bike'
                }
            ],
            'duration': 100,
            'expected_outcomes': {
                'car_reduction': 0.7,
                'bike_increase': 0.4,
                'walk_increase': 0.2,
                'bus_increase': 0.15
            },
            'metadata': {
                'policy_type': 'modal_restriction',
                'zone': 'city_center'
            }
        }
    ]
    
    for scenario in scenarios:
        filename = scenario['name'].lower().replace(' ', '_').replace('%', '') + '.yaml'
        filepath = output_dir / filename
        with open(filepath, 'w') as f:
            yaml.dump(scenario, f, default_flow_style=False, sort_keys=False)
        logger.info(f"Created scenario: {filepath}")