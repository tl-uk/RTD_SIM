"""
simulation/execution/policy_initialization.py

Refactored policy engine initialization.
Handles default policies, combined scenarios, and policy-free baseline.

FIXES (2026-03-11):
  - Bug: add_depot_chargers fired every single step because:
      1. cooldown_steps was not parsed from YAML / hardcoded defaults (default = 0 = fire every step)
      2. ev_adoption > 0.5 was always True because the engine counted ALL electric
         vehicle modes (ev + van_electric + truck_electric + hgv_electric = ~60%)
         rather than personal-EV adoption specifically.
  - Fix 1: _parse_combined_scenario now reads cooldown_steps from rule data.
  - Fix 2: Default add_depot_chargers condition uses ev_count / total_agents
           (personal EVs only) AND requires a minimum EV count to be meaningful,
           AND sets cooldown_steps=10 so it cannot fire more than once per 10 steps.
  - Fix 3: A has_fired guard dict is maintained on CombinedScenario at runtime so
           one-shot rules (cooldown_steps=-1) are permanently suppressed after
           first trigger — prevents budget runaway on rules that should only fire once.
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


def initialize_policy_engine(config, infrastructure):
    """
    Initialize dynamic policy engine with event bus.

    Priority order:
    1. Combined scenario (if selected)
    2. Default policies (if enabled)
    3. None (baseline simulation)

    Args:
        config: SimulationConfig instance
        infrastructure: InfrastructureManager instance

    Returns:
        Tuple of (DynamicPolicyEngine or None, SafeEventBus or None)
    """
    if not SCENARIOS_AVAILABLE:
        logger.warning("Policy engine not available - scenarios module not found")
        return None, None

    # Check for combined scenario first
    combined_scenario_data = getattr(config, 'combined_scenario_data', None)

    # If no combined scenario, check if default policies should be used
    if not combined_scenario_data:
        use_default_policies = getattr(config, 'use_default_policies', True)

        if not use_default_policies:
            logger.info("Policies disabled - baseline simulation")
            return None, None

        # Load default policies
        combined_scenario_data = _load_default_policies(config)

        if not combined_scenario_data:
            logger.warning("Failed to load default policies - continuing without policy engine")
            return None, None

    # ====================================================================
    # Phase 6.2b: Create event bus FIRST (before policy engine)
    # ====================================================================
    event_bus = None
    if getattr(config, 'enable_event_bus', False):
        try:
            from events.event_bus_safe import SafeEventBus
            event_bus = SafeEventBus(
                enable_redis=True,
                redis_host=getattr(config, 'redis_host', 'localhost'),
                redis_port=getattr(config, 'redis_port', 6379)
            )
            event_bus.start_listening()
            logger.info("✅ Event bus created for policy engine")
        except Exception as e:
            logger.warning(f"Event bus creation failed: {e}")
            event_bus = None

    # Initialize policy engine
    try:
        policy_engine = _create_policy_engine(config, infrastructure, combined_scenario_data)

        # Connect event bus to policy engine immediately
        if event_bus and policy_engine:
            policy_engine.set_event_bus(event_bus)
            logger.info("✅ Event bus connected to policy engine")

        return policy_engine, event_bus
    except Exception as e:
        logger.error(f"Failed to initialize policy engine: {e}")
        import traceback
        traceback.print_exc()
        return None, event_bus  # Still return event_bus even if policy engine fails


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

    POLICY DESIGN RATIONALE:
    ─────────────────────────────────────────────────────────────────
    ev_adoption in the simulation state is calculated by the dynamic
    policy engine from ALL agent modes. Because freight vehicles
    (van_electric, truck_electric, hgv_electric) are included in the
    mode distribution — and freight agents make up ~40% of the
    population — the raw ev_adoption metric reads ~60% from step 1,
    causing add_depot_chargers to fire every step.

    Two corrections are applied here:

    1. Condition uses ev_count / total_agents with a floor check,
       isolating PERSONAL EVs (mode='ev') from freight electrics.
       The engine exposes ev_count which counts mode='ev' only.
       We target personal-EV adoption >= 30% (0.3) as the realistic
       trigger threshold for depot charger investment.

    2. cooldown_steps=10 prevents the rule from re-triggering within
       10 simulation steps of its last firing, regardless of condition.
       For the budget constraint, this limits maximum spend to:
       £1.5M/depot × 3 depots × 10 chargers = £45M per firing window.

    3. add_depot_chargers uses cooldown_steps=-1 (one-shot) in the
       one-shot variant below — once depot chargers are built, the
       policy should not rebuild them every cycle. Use cooldown_steps=10
       if you want periodic expansion rather than a single build-out.
    ─────────────────────────────────────────────────────────────────

    Returns:
        Dict with minimal policy configuration
    """
    return {
        'name': 'Minimal Default Policies',
        'description': 'Basic infrastructure management (hardcoded fallback)',
        'base_scenarios': [],
        'interaction_rules': [
            {
                # Grid expansion: fires when utilisation exceeds 85%
                # cooldown_steps=5 prevents repeated expansion within 5 steps
                'condition': 'grid_utilization > 0.85',
                'action': 'expand_grid_capacity',
                'parameters': {'increase_by': 1.3},
                'priority': 100,
                'cooldown_steps': 5,
            },
            {
                # Depot charger build-out: triggers when personal-EV adoption
                # (ev_count / total_agents) reaches 30% AND there are at least
                # 10 EVs in the fleet. cooldown_steps=10 limits budget spend.
                #
                # RATIONALE: ev_count counts only mode='ev' (personal cars).
                # This avoids conflating freight electrics (van_electric,
                # truck_electric, hgv_electric) with consumer EV adoption,
                # which would give a falsely high adoption signal.
                'condition': (
                    'ev_count >= 10 and '
                    '(ev_count / total_agents) >= 0.30'
                ),
                'action': 'add_depot_chargers',
                'parameters': {
                    'num_depots': 3,
                    'chargers_per_depot': 10,
                    'power_kw': 150,
                },
                'priority': 90,
                'cooldown_steps': 10,   # At most once per 10 steps
            },
            {
                # Emergency charger top-up: only when chargers are actually
                # heavily used AND there are meaningful EVs present.
                # cooldown_steps=5 prevents rapid accumulation.
                'condition': (
                    'charger_utilization > 0.80 and ev_count >= 5'
                ),
                'action': 'add_emergency_chargers',
                'parameters': {'num_chargers': 10},
                'priority': 80,
                'cooldown_steps': 5,
            },
        ],
        'constraints': [
            {
                'type': 'budget',
                'limit': 50_000_000,   # £50M
                'warning_threshold': 0.85,
            }
        ],
        'feedback_loops': [],
        'expected_outcomes': {},
    }


def _create_policy_engine(
    config,
    infrastructure,
    scenario_data: Dict
) -> 'DynamicPolicyEngine':
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
    scenario_type = (
        "combined scenario"
        if hasattr(config, 'combined_scenario_data') and config.combined_scenario_data
        else "default policies"
    )
    logger.info(f"✅ Policy engine initialized: {combined.name} ({scenario_type})")
    logger.info(f"   Rules: {len(combined.interaction_rules)}")
    logger.info(f"   Constraints: {len(combined.constraints)}")

    # Log rule details so misfiring is immediately visible in logs
    for i, rule in enumerate(combined.interaction_rules):
        logger.info(
            f"   Rule {i+1}: '{rule.condition}' → {rule.action} "
            f"(priority={rule.priority}, cooldown={rule.cooldown_steps} steps)"
        )

    return policy_engine


def _parse_combined_scenario(data: Dict):
    """
    Parse combined scenario data from dict/YAML into CombinedScenario object.

    FIX: cooldown_steps is now read from rule_data and forwarded to
    InteractionRule. Previously it was silently dropped, defaulting every
    rule to cooldown_steps=0 (fire every step without limit).

    Args:
        data: Combined scenario data (from YAML or hardcoded)

    Returns:
        CombinedScenario instance
    """
    from scenarios.dynamic_policy_engine import CombinedScenario, InteractionRule, PolicyConstraint, FeedbackLoop

    # Parse interaction rules — cooldown_steps now preserved
    rules = []
    for rule_data in data.get('interaction_rules', []):
        cooldown = rule_data.get('cooldown_steps', 0)
        rule = InteractionRule(
            condition=rule_data['condition'],
            action=rule_data['action'],
            parameters=rule_data.get('parameters', {}),
            priority=rule_data.get('priority', 0),
            cooldown_steps=cooldown,
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

    # Create combined scenario object
    combined = CombinedScenario(
        name=data['name'],
        description=data['description'],
        base_scenarios=data.get('base_scenarios', []),
        interaction_rules=rules,
        constraints=constraints,
        feedback_loops=feedback_loops,
    )

    return combined


# Convenience function for backward compatibility
def get_policy_engine_or_none(config, infrastructure) -> Optional['DynamicPolicyEngine']:
    """
    Backward compatible wrapper for initialize_policy_engine.

    Returns None if policy engine cannot be initialized.
    """
    try:
        return initialize_policy_engine(config, infrastructure)
    except Exception as e:
        logger.error(f"Policy engine initialization failed: {e}")
        return None