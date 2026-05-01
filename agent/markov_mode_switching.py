"""
agent/markov_mode_switching.py

Phase 3: Markov Mode Switching with personality-dependent transition matrices
and habit formation over time.

Design:
  - Each StoryDrivenAgent gets a PersonalityMarkovChain initialised from
    their persona type (eco_warrior, business_commuter, etc.)
  - The chain records mode history and updates transition probabilities
    based on satisfaction and consecutive-use streak (habit formation)
  - The BDI planner reads the Markov prior as a cost discount, so it
    biases toward habitual modes without overriding the planner's logic
  - Transition matrices are row-stochastic and renormalised after each update

Markov Decision Model:
  State  = current transport mode (e.g. 'ev')
  Action = next mode choice (selected by BDI planner)
  Reward = satisfaction score [0,1]
  P(s'|s) = learned transition probability, updated online

  The Markov chain is NOT a replacement for the BDI planner. It provides
  a prior P(next_mode | current_mode, persona) that gets encoded as a
  cost discount in actions_for(). The BDI planner still evaluates all
  feasible modes; the chain just makes habitual modes marginally cheaper.
"""

from __future__ import annotations
import math
from utils.secure_rng import AgentRandom
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Full mode list used across the simulation
ALL_MODES = [
    'walk', 'bike', 'e_scooter', 'cargo_bike',
    'bus', 'tram', 'local_train', 'intercity_train',
    'car', 'ev',
    'van_electric', 'van_diesel',
    'truck_electric', 'truck_diesel',
    'hgv_electric', 'hgv_diesel', 'hgv_hydrogen',
    'ferry_diesel', 'ferry_electric',
    'flight_domestic', 'flight_electric',
]

# Persona → base diagonal (self-transition / habit strength)
# Eco warriors switch more; business commuters lock in; freight operators
# follow cost signals rather than habit.
_PERSONA_BASE_DIAGONAL: Dict[str, float] = {
    'eco_warrior':          0.45,  # high switching propensity
    'concerned_parent':     0.55,
    'budget_commuter':      0.60,
    'shift_worker':         0.65,
    'business_commuter':    0.70,  # habit-driven
    'remote_worker':        0.55,
    'student':              0.50,
    'mobility_impaired':    0.70,  # constrained choices
    'freight_operator':     0.60,
    'taxi_driver':          0.75,  # High habit/vehicle lock-in
    'ride_hail_driver':     0.55,  # Fluid, goes where the money is
    'island_tradesperson':  0.80,  # Highly constrained options
    'rural_technician':     0.75,  # Route habituation
    'specialist_engineer':  0.65,
    'emergency_trade_worker': 0.70,
    'last_mile_delivery':   0.55,
    'gig_worker':           0.50,
    # ── Operator personas (operator_personas.yaml) ────────────────────────
    # Previously fell through to 'default': 0.60, understating diesel lock-in.
    'fleet_manager_logistics':  0.65,  # schedule-driven; moderate habit
    'fleet_manager_healthcare': 0.70,  # compliance + reliability lock-in
    'fleet_manager_retail':     0.65,  # delivery-window driven
    'port_terminal_operator':   0.65,  # schedule + throughput driven
    'rail_freight_operator':    0.62,  # path-dependent; moderate lock-in
    'air_freight_operator':     0.62,
    # ── NHS extended personas (nhs_extended_personas.yaml) ───────────────
    'paramedic':                0.80,  # blue-light: always same route, same vehicle
    'community_health_worker':  0.55,  # multi-stop flexibility, moderate switching
    'nhs_ward_manager':         0.65,  # schedule-driven, moderate habit
    'clinical_waste_driver':    0.68,  # regulated routes, moderate lock-in
    'nhs_supply_chain':         0.65,  # scheduled logistics
    'default':                  0.60,
}

# Persona → green bias: extra P(current → green_mode) added on init
_GREEN_MODES = {'ev', 'van_electric', 'truck_electric', 'hgv_electric',
                'bike', 'walk', 'e_scooter', 'cargo_bike', 'tram',
                'local_train', 'bus', 'ferry_electric', 'flight_electric'}

_PERSONA_GREEN_BIAS: Dict[str, float] = {
    'eco_warrior':       0.12,
    'concerned_parent':  0.06,
    'budget_commuter':   0.02,
    'business_commuter': 0.01,
    'freight_operator':  0.02,
    # ── Operator personas ─────────────────────────────────────────────────
    'fleet_manager_logistics':  0.04,  # ZEV mandate compliance pressure
    'fleet_manager_healthcare': 0.06,  # NHS net-zero 2040 mandate
    'fleet_manager_retail':     0.04,
    'port_terminal_operator':   0.03,
    'rail_freight_operator':    0.05,  # rail is already low-carbon
    'air_freight_operator':     0.02,
    # ── NHS extended personas ─────────────────────────────────────────────
    'nhs_ward_manager':         0.08,  # leadership signal: high green bias
    'community_health_worker':  0.05,
    'nhs_supply_chain':         0.05,  # NHS net-zero supply chain mandate
    'clinical_waste_driver':    0.03,
    'paramedic':                0.02,  # safety-first: low green switching bias
    'default':                  0.03,
}


class PersonalityMarkovChain:
    """
    Per-agent Markov mode switching model.

    Attributes:
        modes:               ordered list of modes this agent can use
        T:                   transition matrix [n×n], row-stochastic
        habit_counts:        consecutive-use counts per mode
        mode_history:        recent mode choices (capped at max_history)
        total_updates:       total update calls (for convergence monitoring)
    """

    def __init__(
        self,
        persona_id: str,
        available_modes: Optional[List[str]] = None,
        max_history: int = 20,
    ):
        self.persona_id   = persona_id
        self.modes        = available_modes or ALL_MODES[:]
        self.max_history  = max_history
        self.mode_history: List[str] = []
        self.habit_counts: Dict[str, int] = {m: 0 for m in self.modes}
        self.total_updates = 0

        self.rng = AgentRandom(seed)

        n = len(self.modes)
        self.T = self._init_matrix(persona_id, n)

    # ── Initialisation ────────────────────────────────────────────────────

    def _init_matrix(self, persona_id: str, n: int) -> List[List[float]]:
        """
        Build initial n×n row-stochastic transition matrix.

        Layout:
          - Diagonal = base self-transition (habit strength from persona)
          - Green modes get a small extra probability mass from every row
          - Remaining mass distributed uniformly across other modes
        """
        diag   = _PERSONA_BASE_DIAGONAL.get(persona_id, _PERSONA_BASE_DIAGONAL['default'])
        green  = _PERSONA_GREEN_BIAS.get(persona_id,   _PERSONA_GREEN_BIAS['default'])

        green_idx = {i for i, m in enumerate(self.modes) if m in _GREEN_MODES}

        T = []
        for i in range(n):
            row = [0.0] * n

            # Self-transition
            row[i] = diag

            # Green bias (excluding self if already green)
            remaining_green = [j for j in green_idx if j != i]
            if remaining_green:
                per_green = green / len(remaining_green)
                for j in remaining_green:
                    row[j] = per_green

            # Distribute remainder uniformly
            used = sum(row)
            leftover = max(0.0, 1.0 - used)
            other = [j for j in range(n) if j != i and j not in green_idx]
            if other:
                per_other = leftover / len(other)
                for j in other:
                    row[j] = per_other
            else:
                # All modes are green — put leftover on self
                row[i] += leftover

            # Renormalise to handle floating-point drift
            row = _normalise(row)
            T.append(row)

        return T

    # ── Online update ─────────────────────────────────────────────────────

    def record_step(self, mode: str, satisfaction: float) -> None:
        """
        Record one mode use and update the transition matrix.

        Args:
            mode:         mode used this step
            satisfaction: satisfaction score [0,1]
        """
        if mode not in self.modes:
            return

        # Update history
        self.mode_history.append(mode)
        if len(self.mode_history) > self.max_history:
            self.mode_history.pop(0)

        # Update habit counter (reset on mode switch)
        prev = self.mode_history[-2] if len(self.mode_history) >= 2 else mode
        if prev == mode:
            self.habit_counts[mode] = self.habit_counts.get(mode, 0) + 1
        else:
            self.habit_counts[mode] = 1

        self._update_transitions(mode, satisfaction, self.habit_counts[mode])
        self.total_updates += 1

    def _update_transitions(
        self, mode: str, satisfaction: float, streak: int
    ) -> None:
        """
        Adjust row T[mode_idx] based on satisfaction and habit streak.

        Rules:
          - High satisfaction (>0.7): self-transition +Δ_good
          - Low satisfaction  (<0.3): self-transition -Δ_bad
          - Habit streak      (>3):   additional +habit_bonus (capped at 0.30)
        After adjustment the row is renormalised.
        """
        i = self.modes.index(mode)
        row = self.T[i][:]  # copy

        Δ_good  = 0.04
        Δ_bad   = 0.03
        max_self = 0.85  # never lock in completely

        if satisfaction > 0.7:
            row[i] = min(max_self, row[i] + Δ_good)
        elif satisfaction < 0.3:
            row[i] = max(0.05, row[i] - Δ_bad)

        # Habit bonus: every 3 consecutive uses adds a small lock-in
        if streak > 3:
            habit_bonus = min(0.02 * (streak // 3), 0.15)
            row[i] = min(max_self, row[i] + habit_bonus)

        self.T[i] = _normalise(row)

    # ── Prediction ────────────────────────────────────────────────────────

    def get_prior(self, current_mode: str) -> Dict[str, float]:
        """
        Return transition probabilities from current_mode as a dict.

        This dict is consumed by the BDI planner to apply cost discounts:
            if mode in prior and prior[mode] > threshold:
                cost *= (1 - discount_factor * prior[mode])
        """
        if current_mode not in self.modes:
            return {}

        i = self.modes.index(current_mode)
        return {m: self.T[i][j] for j, m in enumerate(self.modes)}

    def sample_next_mode(self, current_mode: str) -> str:
        """
        Sample next mode from P(next | current). Used for diagnostics.
        Not called during live simulation — the BDI planner decides.
        """
        if current_mode not in self.modes:
            return current_mode

        i = self.modes.index(current_mode)
        probs = self.T[i]
        r = random.random()
        cumulative = 0.0
        for j, p in enumerate(probs):
            cumulative += p
            if r <= cumulative:
                return self.modes[j]
        return self.modes[-1]

    def get_habit_strength(self, mode: str) -> float:
        """Return P(stay in mode | in mode), a proxy for habit strength."""
        if mode not in self.modes:
            return 0.0
        i = self.modes.index(mode)
        return self.T[i][i]

    def summary(self) -> Dict:
        """Return a compact summary for logging / UI display."""
        return {
            'persona':      self.persona_id,
            'total_steps':  self.total_updates,
            'mode_history': self.mode_history[-5:],
            'habits':       {
                m: round(self.get_habit_strength(m), 3)
                for m in self.modes
                if self.habit_counts.get(m, 0) > 2
            },
        }


# ── Utility ───────────────────────────────────────────────────────────────

def _normalise(row: List[float]) -> List[float]:
    """Normalise a list of floats to sum to 1.0."""
    total = sum(row)
    if total < 1e-9:
        n = len(row)
        return [1.0 / n] * n
    return [x / total for x in row]