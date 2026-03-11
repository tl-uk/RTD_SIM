"""
scenarios/policy_models.py

Data models for the dynamic policy engine.

Extracted from dynamic_policy_engine.py (Phase 1 refactor) to keep
the engine file focused on orchestration logic only.

Contains:
    - PolicyTrigger  : enum of when policies activate
    - InteractionRule: a single condition → action rule with cooldown support
    - PolicyConstraint: budget / capacity limit with tracking
    - FeedbackLoop   : reinforcing or balancing feedback between variables
    - CombinedScenario: a named set of rules, constraints and feedback loops
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class PolicyTrigger(Enum):
    """When policies activate."""
    IMMEDIATE = "immediate"       # At scenario start
    CONDITIONAL = "conditional"   # When condition met
    SCHEDULED = "scheduled"       # At specific step/time
    FEEDBACK = "feedback"         # Continuous adjustment


@dataclass
class InteractionRule:
    """
    Defines a single condition → action policy rule.

    Attributes:
        condition        : Python expression evaluated against simulation state.
        action           : Name of the action to execute when condition is True.
        parameters       : Key/value arguments forwarded to the action handler.
        priority         : Evaluation order — higher values run first.
        cooldown_steps   : Minimum steps between successive triggers (0 = no limit).
        last_triggered_step: Step number of the most recent trigger (internal).
    """
    condition: str
    action: str
    parameters: Dict[str, Any]
    priority: int = 0
    cooldown_steps: int = 0
    last_triggered_step: int = -999   # Default far in past so first trigger always works

    def evaluate_condition(self, state: Dict[str, Any]) -> bool:
        """Safely evaluate condition expression against simulation state."""
        try:
            safe_context = {
                'grid_load':          state.get('grid_load', 0),
                'grid_capacity':      state.get('grid_capacity', 1000),
                'grid_utilization':   state.get('grid_utilization', 0),
                'charger_utilization':state.get('charger_utilization', 0),
                'occupied_chargers':  state.get('occupied_chargers', 0),
                'total_chargers':     state.get('total_chargers', 1),
                'ev_adoption':        state.get('ev_adoption', 0),
                'ev_count':           state.get('ev_count', 0),
                'freight_ev_count':   state.get('freight_ev_count', 0),  # van/truck/hgv electric
                'total_agents':       state.get('total_agents', 1),
                'avg_charging_cost':  state.get('avg_charging_cost', 0),
                'step':               state.get('step', 0),
                'time_of_day':        state.get('time_of_day', 8),
            }
            return eval(self.condition, {"__builtins__": {}}, safe_context)
        except Exception as e:
            logger.error(f"Failed to evaluate condition '{self.condition}': {e}")
            return False


@dataclass
class PolicyConstraint:
    """
    A hard or soft limit on policy spending / capacity.

    Attributes:
        constraint_type   : Label — 'budget', 'grid_capacity', 'deployment_rate', etc.
        limit             : Maximum allowed value.
        current           : Accumulated usage so far.
        warning_threshold : Fraction of limit at which a warning is raised (default 80 %).
    """
    constraint_type: str
    limit: float
    current: float = 0.0
    warning_threshold: float = 0.8

    def is_exceeded(self) -> bool:
        """Return True if current usage is at or above the limit."""
        return self.current >= self.limit

    def is_warning(self) -> bool:
        """Return True if current usage is above the warning threshold."""
        return self.current >= (self.limit * self.warning_threshold)

    def remaining(self) -> float:
        """Return headroom left before the limit is reached."""
        return max(0.0, self.limit - self.current)

    def utilization(self) -> float:
        """Return current usage as a fraction of the limit (0–1)."""
        return (self.current / self.limit) if self.limit > 0 else 0.0


@dataclass
class FeedbackLoop:
    """
    Models a reinforcing (positive) or balancing (negative) feedback relationship
    between simulation variables.

    Attributes:
        name            : Short identifier.
        description     : Human-readable explanation of the loop.
        variables       : Variable names involved in the loop.
        loop_type       : 'positive' (amplifying) or 'negative' (dampening).
        strength        : Scalar multiplier applied to the loop effect.
        update_function : Optional callable(state, strength) → Dict[str, float].
    """
    name: str
    description: str
    variables: List[str]
    loop_type: str
    strength: float = 1.0
    update_function: Optional[Callable] = None

    def apply(self, state: Dict[str, Any]) -> Dict[str, float]:
        """Apply the feedback loop and return variable adjustments."""
        if self.update_function:
            return self.update_function(state, self.strength)
        return {}


@dataclass
class CombinedScenario:
    """
    A named collection of base scenarios, interaction rules, constraints
    and feedback loops that are applied together as a single policy package.

    Attributes:
        name              : Display name.
        description       : Explanation of what this scenario does.
        base_scenarios    : List of simple scenario names to activate first.
        interaction_rules : Ordered list of condition → action rules.
        constraints       : Map of constraint type → PolicyConstraint.
        feedback_loops    : List of active feedback loops.
        active_rules      : Rules currently eligible to fire (populated at runtime).
        triggered_at_step : Map of rule_key → last step number it fired.
    """
    name: str
    description: str
    base_scenarios: List[str]
    interaction_rules: List[InteractionRule] = field(default_factory=list)
    constraints: Dict[str, PolicyConstraint] = field(default_factory=dict)
    feedback_loops: List[FeedbackLoop] = field(default_factory=list)

    # Runtime state — populated by the engine, not from YAML
    active_rules: List[InteractionRule] = field(default_factory=list)
    triggered_at_step: Dict[str, int] = field(default_factory=dict)