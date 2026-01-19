"""
simulation/execution/dynamic_policies.py

NEW Phase 5.1: Dynamic policy application logic.
Handles combined scenarios with interaction rules and feedback loops.

Called by simulation_loop.py for runtime policy adjustments.
"""

from __future__ import annotations
import logging
from typing import Dict, Optional, Any
from pathlib import Path

logger = logging.getLogger(__name__)

# Import scenario framework
try:
    from scenarios.scenario_manager import ScenarioManager
    from scenarios.dynamic_policy_engine import (
        DynamicPolicyEngine,
        CombinedScenario,
        InteractionRule,
        PolicyConstraint,
        FeedbackLoop
    )
    SCENARIOS_AVAILABLE = True
except ImportError:
    SCENARIOS_AVAILABLE = False
    logger.warning("Dynamic policy engine not available")


def initialize_policy_engine(config, infrastructure) -> Optional[DynamicPolicyEngine]:
    """
    Initialize dynamic policy engine if combined scenario is active.
    
    Args:
        config: SimulationConfig instance
        infrastructure: InfrastructureManager instance
    
    Returns:
        DynamicPolicyEngine instance or None
    """
    if not SCENARIOS_AVAILABLE:
        logger.warning("Dynamic policy engine not available - scenarios module not found")
        return None
    
    # Check if combined scenario selected
    combined_scenario_data = getattr(config, 'combined_scenario_data', None)
    
    if not combined_scenario_data:
        logger.info("No combined scenario - using simple scenario or baseline")
        return None
    
    try:
        # Initialize scenario manager
        scenarios_dir = config.scenarios_dir or (Path(__file__).parent.parent.parent / 'scenarios' / 'configs')
        scenario_manager = ScenarioManager(scenarios_dir)
        
        # Initialize dynamic policy engine
        policy_engine = DynamicPolicyEngine(
            infrastructure_manager=infrastructure,
            scenario_manager=scenario_manager
        )
        
        # Parse and load combined scenario
        combined = _parse_combined_scenario(combined_scenario_data)
        
        # Activate combined scenario
        policy_engine.activate_combined_scenario(combined)
        
        logger.info(f"✅ Dynamic policy engine initialized: {combined.name}")
        logger.info(f"   Base scenarios: {combined.base_scenarios}")
        logger.info(f"   Interaction rules: {len(combined.interaction_rules)}")
        logger.info(f"   Constraints: {len(combined.constraints)}")
        
        return policy_engine
        
    except Exception as e:
        logger.error(f"Failed to initialize dynamic policy engine: {e}")
        import traceback
        traceback.print_exc()
        return None


def _parse_combined_scenario(data: Dict) -> CombinedScenario:
    """
    Parse combined scenario data from dict/YAML into CombinedScenario object.
    
    Args:
        data: Combined scenario data (from YAML or session state)
    
    Returns:
        CombinedScenario instance
    """
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
        base_scenarios=data['base_scenarios'],
        interaction_rules=rules,
        constraints=constraints,
        feedback_loops=feedback_loops
    )
    
    return combined


def apply_dynamic_policies(
    policy_engine: DynamicPolicyEngine,
    step: int,
    agents: list,
    env,
    infrastructure
) -> Dict[str, Any]:
    """
    Apply dynamic policy adjustments for current simulation step.
    
    Called every step by simulation_loop.py.
    
    Args:
        policy_engine: DynamicPolicyEngine instance
        step: Current simulation step
        agents: List of agents
        env: SpatialEnvironment
        infrastructure: InfrastructureManager
    
    Returns:
        Dict with actions_taken, violations, adjustments
    """
    if policy_engine is None:
        return {}
    
    try:
        # Update simulation state for condition evaluation
        policy_engine.update_simulation_state(
            step=step,
            agents=agents,
            env=env,
            infrastructure=infrastructure
        )
        
        # Apply interaction rules (dynamic policy adjustments)
        actions_taken = policy_engine.apply_interaction_rules(step)
        
        # Apply feedback loops
        feedback_adjustments = policy_engine.apply_feedback_loops(step)
        
        # Check constraints
        violations = policy_engine.check_constraints()
        
        # Return results for tracking
        return {
            'actions_taken': actions_taken,
            'feedback_adjustments': feedback_adjustments,
            'violations': violations,
            'step': step
        }
        
    except Exception as e:
        logger.error(f"Step {step}: Failed to apply dynamic policies: {e}")
        return {}


def record_charging_revenue(
    policy_engine: DynamicPolicyEngine,
    charging_cost: float
) -> None:
    """
    Record revenue from charging session for cost recovery tracking.
    
    Args:
        policy_engine: DynamicPolicyEngine instance
        charging_cost: Cost of charging session (£)
    """
    if policy_engine is None:
        return
    
    try:
        policy_engine.record_charging_session(charging_cost)
    except Exception as e:
        logger.error(f"Failed to record charging revenue: {e}")


def get_final_policy_report(policy_engine: DynamicPolicyEngine) -> Optional[Dict]:
    """
    Get final policy status report after simulation completes.
    
    Args:
        policy_engine: DynamicPolicyEngine instance
    
    Returns:
        Dict with policy status, cost recovery, constraints
    """
    if policy_engine is None:
        return None
    
    try:
        status = policy_engine.get_status_report()
        cost_recovery = policy_engine.calculate_cost_recovery()
        
        return {
            'policy_status': status,
            'cost_recovery': cost_recovery,
            'active': True
        }
        
    except Exception as e:
        logger.error(f"Failed to generate policy report: {e}")
        return None