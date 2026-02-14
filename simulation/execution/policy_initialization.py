"""
simulation/execution/policy_initialization.py

Refactored policy engine initialization.
Handles default policies, combined scenarios, and policy-free baseline.
"""

from __future__ import annotations
import logging
from typing import Dict, Optional
from pathlib import Path
import yaml

logger = logging.getLogger(__name__)

# Import scenario framework
try:
    from scenarios.scenario_manager import ScenarioManager
    from scenarios.dynamic_policy_engine import DynamicPolicyEngine
    SCENARIOS_AVAILABLE = True
except ImportError:
    SCENARIOS_AVAILABLE = False
    logger.warning("Dynamic policy engine not available")


def initialize_policy_engine(config, infrastructure) -> Optional[DynamicPolicyEngine]:
    """
    Initialize dynamic policy engine with flexible configuration.
    
    Priority order:
    1. Combined scenario (if selected)
    2. Default policies (if enabled)
    3. None (baseline simulation)
    
    Args:
        config: SimulationConfig instance
        infrastructure: InfrastructureManager instance
    
    Returns:
        DynamicPolicyEngine instance or None
    """
    if not SCENARIOS_AVAILABLE:
        logger.warning("Policy engine not available - scenarios module not found")
        return None
    
    # Check for combined scenario first
    combined_scenario_data = getattr(config, 'combined_scenario_data', None)
    
    # If no combined scenario, check if default policies should be used
    if not combined_scenario_data:
        use_default_policies = getattr(config, 'use_default_policies', True)
        
        if not use_default_policies:
            logger.info("Policies disabled - baseline simulation")
            return None
        
        # Load default policies
        combined_scenario_data = _load_default_policies(config)
        
        if not combined_scenario_data:
            logger.warning("Failed to load default policies - continuing without policy engine")
            return None
    
    # Initialize policy engine
    try:
        policy_engine = _create_policy_engine(config, infrastructure, combined_scenario_data)
        return policy_engine
    except Exception as e:
        logger.error(f"Failed to initialize policy engine: {e}")
        import traceback
        traceback.print_exc()
        return None


def _load_default_policies(config) -> Optional[Dict]:
    """
    Load default policy configuration.
    
    Priority:
    1. default_policies.yaml in scenarios/combined_configs
    2. Hardcoded minimal defaults
    
    Returns:
        Dict with policy configuration or None
    """
    # Try loading from YAML file
    scenarios_dir = getattr(config, 'scenarios_dir', None)
    if not scenarios_dir:
        scenarios_dir = Path(__file__).parent.parent.parent / 'scenarios' / 'combined_configs'
    
    default_policy_file = Path(scenarios_dir) / 'default_policies.yaml'
    
    if default_policy_file.exists():
        try:
            with open(default_policy_file, 'r') as f:
                data = yaml.safe_load(f)
            logger.info(f"✅ Loaded default policies from {default_policy_file.name}")
            return data
        except Exception as e:
            logger.warning(f"Failed to load {default_policy_file}: {e}")
    else:
        logger.info(f"default_policies.yaml not found at {default_policy_file}")
    
    # Fallback to hardcoded minimal defaults
    logger.info("Using hardcoded minimal default policies")
    return _create_minimal_default_policies()


def _create_minimal_default_policies() -> Dict:
    """
    Create minimal default policies in-memory.
    
    Used as fallback if default_policies.yaml doesn't exist.
    
    Returns:
        Dict with minimal policy configuration
    """
    return {
        'name': 'Minimal Default Policies',
        'description': 'Basic infrastructure management (hardcoded fallback)',
        'base_scenarios': [],
        'interaction_rules': [
            {
                'condition': 'grid_utilization > 0.85',
                'action': 'expand_grid_capacity',
                'parameters': {'increase_by': 1.3},
                'priority': 100
            },
            {
                'condition': 'ev_adoption > 0.5',
                'action': 'add_depot_chargers',
                'parameters': {
                    'num_depots': 3,
                    'chargers_per_depot': 10,
                    'power_kw': 150
                },
                'priority': 90
            },
            {
                'condition': 'charger_utilization > 0.80',
                'action': 'add_emergency_chargers',
                'parameters': {'num_chargers': 10},
                'priority': 80
            }
        ],
        'constraints': [
            {
                'type': 'budget',
                'limit': 50000000,  # £50M
                'warning_threshold': 0.85
            }
        ],
        'feedback_loops': [],
        'expected_outcomes': {}
    }


def _create_policy_engine(
    config,
    infrastructure,
    scenario_data: Dict
) -> DynamicPolicyEngine:
    """
    Create and configure policy engine instance.
    
    Args:
        config: SimulationConfig
        infrastructure: InfrastructureManager
        scenario_data: Combined scenario data (dict)
    
    Returns:
        Configured DynamicPolicyEngine instance
    
    Raises:
        Exception if initialization fails
    """
    from scenarios.dynamic_policy_engine import CombinedScenario, InteractionRule, PolicyConstraint, FeedbackLoop
    
    # Initialize scenario manager
    scenarios_dir = getattr(config, 'scenarios_dir', None)
    if not scenarios_dir:
        scenarios_dir = Path(__file__).parent.parent.parent / 'scenarios' / 'configs'
    
    scenario_manager = ScenarioManager(scenarios_dir)
    
    # Create policy engine
    policy_engine = DynamicPolicyEngine(
        infrastructure_manager=infrastructure,
        scenario_manager=scenario_manager
    )
    
    # Parse scenario data into CombinedScenario object
    combined = _parse_combined_scenario(scenario_data)
    
    # Activate scenario
    policy_engine.activate_combined_scenario(combined)
    
    # Log initialization
    scenario_type = "combined scenario" if hasattr(config, 'combined_scenario_data') and config.combined_scenario_data else "default policies"
    logger.info(f"✅ Policy engine initialized: {combined.name} ({scenario_type})")
    logger.info(f"   Rules: {len(combined.interaction_rules)}")
    logger.info(f"   Constraints: {len(combined.constraints)}")
    
    return policy_engine


def _parse_combined_scenario(data: Dict):
    """
    Parse combined scenario data from dict/YAML into CombinedScenario object.
    
    Args:
        data: Combined scenario data (from YAML or hardcoded)
    
    Returns:
        CombinedScenario instance
    """
    from scenarios.dynamic_policy_engine import CombinedScenario, InteractionRule, PolicyConstraint, FeedbackLoop
    
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
    
    # Create combined scenario object
    combined = CombinedScenario(
        name=data['name'],
        description=data['description'],
        base_scenarios=data.get('base_scenarios', []),
        interaction_rules=rules,
        constraints=constraints,
        feedback_loops=feedback_loops
    )
    
    return combined


# Convenience function for backward compatibility
def get_policy_engine_or_none(config, infrastructure) -> Optional[DynamicPolicyEngine]:
    """
    Backward compatible wrapper for initialize_policy_engine.
    
    Returns None if policy engine cannot be initialized.
    """
    try:
        return initialize_policy_engine(config, infrastructure)
    except Exception as e:
        logger.error(f"Policy engine initialization failed: {e}")
        return None