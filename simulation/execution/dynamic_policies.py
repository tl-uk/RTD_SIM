"""
simulation/execution/dynamic_policies.py

This module is is responsible for: step updates, feedback loops, and constraints.

This file should never import policy_initialization.py or instantiate anything. 
It should only take an already-built engine and step it forward.

The logic is designed to be modular and extensible, allowing for new interaction rules 
and feedback mechanisms to be added without modifying the core simulation loop.
Handles combined scenarios with interaction rules and feedback loops.

It is Called by simulation_loop.py for runtime policy adjustments.

"""

from __future__ import annotations
import logging
from typing import Dict, Optional, Any
from pathlib import Path

logger = logging.getLogger(__name__)

# Import scenario framework
try:
    from scenarios.scenario_manager import ScenarioManager
    from scenarios.dynamic_policy_engine import DynamicPolicyEngine
    SCENARIOS_AVAILABLE = True
except ImportError:
    SCENARIOS_AVAILABLE = False
    logger.warning("Dynamic policy engine not available")

# Re-export for backward compatibility
# Other modules import initialize_policy_engine from this module
# from simulation.execution.policy_initialization import initialize_policy_engine
# This file should never import policy_initialization.py or instantiate anything. 
# It should only take an already-built engine and step it forward.

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