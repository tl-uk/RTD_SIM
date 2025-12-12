"""
agent/social_influence_dynamics.py

Realistic social influence with:
- Temporal decay (influences fade over time)
- Habit formation & inertia
- Competing trends
- Influence saturation
- Recency bias
- Personal experience override

This addresses the over-deterministic cascade problem.
"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import deque
import random
import logging

logger = logging.getLogger(__name__)


@dataclass
class InfluenceMemory:
    """
    Tracks influence events with temporal decay.
    
    Key insight: Recent influences matter more than old ones.
    """
    mode: str
    timestamp: int
    strength: float
    source_agent: str
    decay_rate: float = 0.1  # How fast influence fades (per time step)
    
    def get_current_strength(self, current_time: int) -> float:
        """Calculate decayed influence strength."""
        time_elapsed = current_time - self.timestamp
        decayed = self.strength * (1.0 - self.decay_rate) ** time_elapsed
        return max(0.0, decayed)


@dataclass
class HabitState:
    """
    Tracks agent's habit formation for a mode.
    
    Key insight: Repeated use builds inertia, making switching harder.
    """
    mode: str
    consecutive_uses: int = 0
    total_uses: int = 0
    satisfaction_history: List[float] = field(default_factory=list)
    
    def get_habit_strength(self) -> float:
        """
        Calculate habit strength (0-1).
        
        More consecutive uses = stronger habit.
        """
        # Logistic function: habit builds up but saturates
        if self.consecutive_uses == 0:
            return 0.0
        
        # Saturation at ~10 consecutive uses
        return 1.0 - 1.0 / (1.0 + self.consecutive_uses / 5.0)
    
    def get_average_satisfaction(self) -> float:
        """Average satisfaction from past experiences."""
        if not self.satisfaction_history:
            return 0.5  # Neutral
        return sum(self.satisfaction_history[-10:]) / len(self.satisfaction_history[-10:])


class RealisticSocialInfluence:
    """
    Enhanced social influence with realistic dynamics.
    
    Prevents over-deterministic cascades through:
    1. Temporal decay
    2. Habit inertia
    3. Personal experience weighting
    4. Influence saturation
    5. Competing trends
    """
    
    def __init__(
        self,
        decay_rate: float = 0.1,
        habit_weight: float = 0.4,
        experience_weight: float = 0.4,
        peer_weight: float = 0.2,
        saturation_threshold: int = 5,
        recency_window: int = 10
    ):
        """
        Initialize realistic influence system.
        
        Args:
            decay_rate: How fast influence memories fade (0-1)
            habit_weight: Weight of habit inertia (0-1)
            experience_weight: Weight of personal experience (0-1)
            peer_weight: Weight of peer influence (0-1)
            saturation_threshold: Max peer events to consider
            recency_window: How many recent steps matter most
        """
        self.decay_rate = decay_rate
        self.habit_weight = habit_weight
        self.experience_weight = experience_weight
        self.peer_weight = peer_weight
        self.saturation_threshold = saturation_threshold
        self.recency_window = recency_window
        
        # Agent state tracking
        self._influence_memories: Dict[str, List[InfluenceMemory]] = {}
        self._habit_states: Dict[str, Dict[str, HabitState]] = {}
        self._current_time: int = 0
        
        logger.info(f"RealisticSocialInfluence: decay={decay_rate}, "
                   f"habit={habit_weight}, exp={experience_weight}, peer={peer_weight}")
    
    def advance_time(self, steps: int = 1) -> None:
        """Advance simulation time (for decay calculations)."""
        self._current_time += steps
    
    def record_influence_event(
        self,
        agent_id: str,
        mode: str,
        strength: float,
        source_agent: str
    ) -> None:
        """
        Record a peer influence event.
        
        Args:
            agent_id: Agent being influenced
            mode: Mode being promoted
            strength: Influence strength (tie strength)
            source_agent: Agent doing the influencing
        """
        if agent_id not in self._influence_memories:
            self._influence_memories[agent_id] = []
        
        memory = InfluenceMemory(
            mode=mode,
            timestamp=self._current_time,
            strength=strength,
            source_agent=source_agent,
            decay_rate=self.decay_rate
        )
        
        self._influence_memories[agent_id].append(memory)
        
        # Prune old memories (efficiency)
        self._prune_old_memories(agent_id)
    
    def record_mode_usage(
        self,
        agent_id: str,
        mode: str,
        satisfaction: float
    ) -> None:
        """
        Record agent using a mode (builds habit).
        
        Args:
            agent_id: Agent identifier
            mode: Mode used
            satisfaction: How satisfied (0-1)
        """
        if agent_id not in self._habit_states:
            self._habit_states[agent_id] = {}
        
        # Update habit for this mode
        if mode not in self._habit_states[agent_id]:
            self._habit_states[agent_id][mode] = HabitState(mode)
        
        habit = self._habit_states[agent_id][mode]
        habit.consecutive_uses += 1
        habit.total_uses += 1
        habit.satisfaction_history.append(satisfaction)
        
        # Reset other modes' consecutive uses
        for other_mode, other_habit in self._habit_states[agent_id].items():
            if other_mode != mode:
                other_habit.consecutive_uses = 0
    
    def calculate_mode_attractiveness(
        self,
        agent_id: str,
        mode: str,
        base_cost: float,
        peer_mode_share: Dict[str, float]
    ) -> float:
        """
        Calculate mode attractiveness with realistic dynamics.
        
        Combines:
        1. Base cost (from planner)
        2. Habit inertia (resistance to change)
        3. Personal experience (past satisfaction)
        4. Peer influence (with decay)
        
        Args:
            agent_id: Agent identifier
            mode: Mode to evaluate
            base_cost: Base cost from BDI planner
            peer_mode_share: Current peer mode distribution
        
        Returns:
            Adjusted cost (lower = more attractive)
        """
        # Start with base cost
        adjusted_cost = base_cost
        
        # 1. HABIT INERTIA
        habit_bonus = self._calculate_habit_bonus(agent_id, mode)
        
        # 2. PERSONAL EXPERIENCE
        experience_bonus = self._calculate_experience_bonus(agent_id, mode)
        
        # 3. PEER INFLUENCE (with decay)
        peer_bonus = self._calculate_peer_bonus(agent_id, mode, peer_mode_share)
        
        # Combine with weights
        total_bonus = (
            self.habit_weight * habit_bonus +
            self.experience_weight * experience_bonus +
            self.peer_weight * peer_bonus
        )
        
        # Apply bonus (cap at 50% reduction)
        adjusted_cost *= (1.0 - min(0.5, total_bonus))
        
        return adjusted_cost
    
    def _calculate_habit_bonus(self, agent_id: str, mode: str) -> float:
        """
        Calculate habit bonus for mode.
        
        Strong habits reduce cost (make switching harder).
        """
        if agent_id not in self._habit_states:
            return 0.0
        
        if mode not in self._habit_states[agent_id]:
            return 0.0
        
        habit = self._habit_states[agent_id][mode]
        return habit.get_habit_strength()
    
    def _calculate_experience_bonus(self, agent_id: str, mode: str) -> float:
        """
        Calculate bonus from personal experience.
        
        Good past experiences make mode more attractive.
        """
        if agent_id not in self._habit_states:
            return 0.0
        
        if mode not in self._habit_states[agent_id]:
            return 0.0
        
        habit = self._habit_states[agent_id][mode]
        satisfaction = habit.get_average_satisfaction()
        
        # Convert satisfaction (0-1) to bonus
        # High satisfaction (>0.7) gives bonus
        # Low satisfaction (<0.3) gives penalty
        return (satisfaction - 0.5) * 2.0
    
    def _calculate_peer_bonus(
        self,
        agent_id: str,
        mode: str,
        peer_mode_share: Dict[str, float]
    ) -> float:
        """
        Calculate peer influence bonus with decay.
        
        Recent peer adoptions matter more than old ones.
        """
        if agent_id not in self._influence_memories:
            return 0.0
        
        # Get recent memories for this mode
        recent_influences = [
            mem for mem in self._influence_memories[agent_id]
            if mem.mode == mode
            and (self._current_time - mem.timestamp) <= self.recency_window
        ]
        
        if not recent_influences:
            # No recent peer influence, use current peer share
            return peer_mode_share.get(mode, 0.0) * 0.5
        
        # Calculate weighted average of decayed influences
        total_strength = 0.0
        for mem in recent_influences[-self.saturation_threshold:]:
            decayed_strength = mem.get_current_strength(self._current_time)
            total_strength += decayed_strength
        
        # Normalize by saturation threshold
        return min(1.0, total_strength / self.saturation_threshold)
    
    def _prune_old_memories(self, agent_id: str) -> None:
        """Remove influence memories that have fully decayed."""
        if agent_id not in self._influence_memories:
            return
        
        cutoff_time = self._current_time - (10 / self.decay_rate)  # ~10 half-lives
        
        self._influence_memories[agent_id] = [
            mem for mem in self._influence_memories[agent_id]
            if mem.timestamp > cutoff_time
        ]
    
    def get_agent_state_summary(self, agent_id: str) -> Dict:
        """Get agent's influence state for debugging."""
        summary = {
            'influence_memories': len(self._influence_memories.get(agent_id, [])),
            'habits': {},
            'current_time': self._current_time
        }
        
        if agent_id in self._habit_states:
            for mode, habit in self._habit_states[agent_id].items():
                summary['habits'][mode] = {
                    'strength': habit.get_habit_strength(),
                    'consecutive_uses': habit.consecutive_uses,
                    'satisfaction': habit.get_average_satisfaction()
                }
        
        return summary
    
    def detect_trend_reversal(
        self,
        mode: str,
        adoption_history: List[float],
        window: int = 5
    ) -> bool:
        """
        Detect if a trend is reversing (people abandoning a mode).
        
        Args:
            mode: Mode to check
            adoption_history: List of adoption rates over time
            window: How many recent steps to check
        
        Returns:
            True if trend is reversing
        """
        if len(adoption_history) < window + 1:
            return False
        
        recent = adoption_history[-window:]
        previous = adoption_history[-window-1]
        
        # Check if adoption is consistently decreasing
        decreasing_count = sum(
            1 for i in range(len(recent)-1)
            if recent[i+1] < recent[i]
        )
        
        # Reversal = most recent steps show decline
        return decreasing_count >= (window - 1) and recent[-1] < previous
    
    def apply_fashion_cycle(
        self,
        mode: str,
        current_adoption: float,
        time_at_peak: int,
        cycle_length: int = 50
    ) -> float:
        """
        Apply fashion cycle effect.
        
        Modes become less attractive after being popular for too long.
        
        Args:
            mode: Mode name
            current_adoption: Current adoption rate
            time_at_peak: How long it's been popular
            cycle_length: How long until "backlash"
        
        Returns:
            Penalty factor (1.0 = no penalty, 1.5 = 50% cost increase)
        """
        if current_adoption < 0.3:
            return 1.0  # Not popular enough for backlash
        
        if time_at_peak < cycle_length / 2:
            return 1.0  # Still rising
        
        # Calculate backlash effect
        excess_time = time_at_peak - (cycle_length / 2)
        backlash = min(0.5, excess_time / cycle_length)
        
        return 1.0 + backlash


# ============================================================================
# Integration with SocialNetwork
# ============================================================================

def enhance_social_network_with_realism(network, influence_system: RealisticSocialInfluence):
    """
    Enhance existing SocialNetwork with realistic influence dynamics.
    
    Usage:
        network = SocialNetwork(...)
        influence = RealisticSocialInfluence()
        enhance_social_network_with_realism(network, influence)
    """
    # Store influence system as attribute
    network.influence_system = influence_system
    
    # Override apply_social_influence method
    original_apply = network.apply_social_influence
    
    def realistic_apply_social_influence(
        agent_id: str,
        mode_costs: Dict[str, float],
        **kwargs
    ) -> Dict[str, float]:
        """Enhanced influence with realistic dynamics."""
        
        # Get peer mode share
        peer_modes = network.get_peer_mode_share(agent_id)
        
        # Record influence events
        for mode, share in peer_modes.items():
            if share > 0.1:  # Only significant influences
                # Find neighbors using this mode
                neighbors = network.get_neighbors(agent_id)
                for neighbor_id in neighbors:
                    neighbor = network._agent_registry.get(neighbor_id)
                    if neighbor and neighbor.state.mode == mode:
                        tie_strength = network.G[agent_id][neighbor_id].get('strength', 0.5)
                        influence_system.record_influence_event(
                            agent_id, mode, tie_strength, neighbor_id
                        )
        
        # Calculate adjusted costs with realistic dynamics
        adjusted_costs = {}
        for mode, base_cost in mode_costs.items():
            adjusted_costs[mode] = influence_system.calculate_mode_attractiveness(
                agent_id, mode, base_cost, peer_modes
            )
        
        return adjusted_costs
    
    # Replace method
    network.apply_social_influence = realistic_apply_social_influence
    
    logger.info("SocialNetwork enhanced with realistic influence dynamics")


# ============================================================================
# Helper Functions
# ============================================================================

def calculate_satisfaction(
    agent,
    env,
    actual_time: float,
    expected_time: float,
    actual_cost: float,
    expected_cost: float
) -> float:
    """
    Calculate agent satisfaction with mode choice.
    
    Used to build experience-based preferences.
    
    Args:
        agent: Agent object
        env: Environment
        actual_time: Actual travel time
        expected_time: Expected travel time
        actual_cost: Actual cost
        expected_cost: Expected cost
    
    Returns:
        Satisfaction (0-1)
    """
    # Time satisfaction
    time_ratio = actual_time / expected_time if expected_time > 0 else 1.0
    time_sat = max(0.0, 1.0 - abs(time_ratio - 1.0))
    
    # Cost satisfaction
    cost_ratio = actual_cost / expected_cost if expected_cost > 0 else 1.0
    cost_sat = max(0.0, 1.0 - abs(cost_ratio - 1.0))
    
    # Overall satisfaction (weighted by agent desires)
    w_time = agent.desires.get('time', 0.5)
    w_cost = agent.desires.get('cost', 0.5)
    
    total_weight = w_time + w_cost
    if total_weight > 0:
        satisfaction = (w_time * time_sat + w_cost * cost_sat) / total_weight
    else:
        satisfaction = 0.5
    
    return satisfaction