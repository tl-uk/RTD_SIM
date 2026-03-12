"""
analytics/mode_share_analyzer.py

This module provides analysis of mode share evolution and tipping point detection. It tracks 
transitions between modes, detects when rapid adoption occurs, and measures cascade effects.

Key features:
- Transition tracking: Records who switched from what to what, when, and why.
- Tipping point detection: Identifies when adoption rapidly accelerates and what triggered it.
- Cascade measurement: Analyzes how changes spread through the population via social influence.
- Temporal pattern analysis: Examines how mode share evolves over time and in response to events.

This enables a deeper understanding of population-level adoption patterns, cascades, and transitions.

"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import logging
import numpy as np
from scipy import signal
from scipy.stats import linregress

logger = logging.getLogger(__name__)

# =============================================================================
# Data Classes for Mode Share Analysis
# =============================================================================

# ModeTransition records when an agent switches modes, including the reason and any 
# social influence.
@dataclass
class ModeTransition:
    """Record of an agent switching modes."""
    agent_id: str
    step: int
    from_mode: str
    to_mode: str
    reason: str = "unknown"
    influenced_by: List[str] = None
    
    def __post_init__(self):
        if self.influenced_by is None:
            self.influenced_by = []

# TippingPoint represents a detected tipping point in the adoption curve, including the mode,
@dataclass
class TippingPoint:
    """Detected tipping point in adoption curve."""
    mode: str
    step: int
    adoption_before: float  # percentage
    adoption_after: float   # percentage
    velocity: float  # percentage points per step
    trigger: str  # What caused it
    statistical_significance: float  # p-value

# CascadeMetrics captures the characteristics of a social cascade, including its origin, 
# size, duration, and network spread.
@dataclass
class CascadeMetrics:
    """Metrics for social cascade analysis."""
    cascade_id: int
    origin_agent: str
    origin_step: int
    total_adopters: int
    cascade_duration: int  # steps
    velocity: float  # adopters per step
    max_network_distance: int  # hops from origin
    avg_network_distance: float

# ============================================================================
# Mode Share Analyzer Class
# ============================================================================
# This class provides methods to record mode share data, detect tipping points, and 
# analyze cascades. It maintains a history of mode shares and transitions, allowing for 
# detailed analysis of how mode share evolves over time and in response to events and 
# social influence. This enables analysis of population-level adoption patterns and the
# factors that drive them, which can inform policy design and system interventions.
class ModeShareAnalyzer:
    """
    Analyze mode share evolution, detect tipping points, measure cascade effects.
    
    Enables:
    - Transition tracking (who switched from what to what)
    - Tipping point detection (when did adoption accelerate)
    - Cascade measurement (how fast does change spread)
    - Temporal pattern analysis
    """
    
    def __init__(self):
        """Initialize mode share analyzer."""
        self.transitions: List[ModeTransition] = []
        self.adoption_history: Dict[str, List[float]] = defaultdict(list)
        self.mode_counts_history: Dict[str, List[int]] = defaultdict(list)
        self.step_history: List[int] = []
        
        self._agent_mode_history: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
        
        logger.info("✅ ModeShareAnalyzer initialized")
    
    # =========================================================================
    # Data Collection
    # =========================================================================
    
    def record_step(self, step: int, agents: List, total_agents: int):
        """
        Record mode distribution at current step.
        
        Args:
            step: Current simulation step
            agents: List of all agents
            total_agents: Total number of agents
        """
        self.step_history.append(step)
        
        # Count modes
        mode_counts = defaultdict(int)
        for agent in agents:
            mode = agent.state.mode
            mode_counts[mode] += 1
            
            # Track individual agent mode history
            self._agent_mode_history[agent.state.agent_id].append((step, mode))
        
        # Calculate adoption percentages
        for mode, count in mode_counts.items():
            self.mode_counts_history[mode].append(count)
            self.adoption_history[mode].append((count / total_agents) * 100)
        
        # Ensure all modes have entries (even if 0)
        for mode in self.adoption_history.keys():
            if mode not in mode_counts:
                self.mode_counts_history[mode].append(0)
                self.adoption_history[mode].append(0.0)
    
    def record_transition(
        self,
        agent_id: str,
        step: int,
        from_mode: str,
        to_mode: str,
        reason: str = "unknown",
        influenced_by: Optional[List[str]] = None
    ):
        """
        Record a mode transition for an agent.
        
        Args:
            agent_id: Agent ID
            step: When transition occurred
            from_mode: Previous mode
            to_mode: New mode
            reason: Why they switched
            influenced_by: List of agent IDs who influenced decision
        """
        transition = ModeTransition(
            agent_id=agent_id,
            step=step,
            from_mode=from_mode,
            to_mode=to_mode,
            reason=reason,
            influenced_by=influenced_by or []
        )
        
        self.transitions.append(transition)
    
    # =========================================================================
    # Tipping Point Detection
    # =========================================================================
    
    def detect_tipping_points(
        self,
        mode: Optional[str] = None,
        min_velocity: float = 0.5,  # % points per step
        min_duration: int = 5,  # Must sustain for N steps
        window_size: int = 10  # Smoothing window
    ) -> List[TippingPoint]:
        """
        Detect tipping points where adoption rapidly accelerates.
        
        Uses derivative analysis to find inflection points in adoption curves.
        
        Args:
            mode: Specific mode to analyze (None = all modes)
            min_velocity: Minimum acceleration to qualify as tipping point
            min_duration: Must sustain acceleration for this many steps
            window_size: Smoothing window for noise reduction
        
        Returns:
            List of detected tipping points
        """
        tipping_points = []
        # Analyze specified mode or all modes
        modes_to_analyze = [mode] if mode else self.adoption_history.keys()
        
        for mode_name in modes_to_analyze:
            if mode_name not in self.adoption_history:
                continue
            # Get adoption history for this mode
            history = self.adoption_history[mode_name]
            
            if len(history) < window_size * 2:
                continue  # Not enough data
            
            # Smooth the curve to reduce noise
            smoothed = self._smooth_curve(history, window_size)
            
            # Calculate first derivative (velocity)
            velocity = np.gradient(smoothed)
            
            # Calculate second derivative (acceleration)
            acceleration = np.gradient(velocity)
            
            # Find potential tipping points (where acceleration is positive and high)
            for i in range(len(acceleration) - min_duration):
                # Check if we have sustained high velocity
                window_velocity = velocity[i:i+min_duration]
                
                if np.mean(window_velocity) >= min_velocity:
                    # Found potential tipping point
                    step = self.step_history[i] if i < len(self.step_history) else i
                    
                    # Calculate statistics
                    adoption_before = smoothed[max(0, i-5)]
                    adoption_after = smoothed[min(len(smoothed)-1, i+min_duration)]
                    avg_velocity = np.mean(window_velocity)
                    
                    # Determine trigger (look at what happened around this time)
                    trigger = self._identify_trigger(mode_name, step)
                    
                    # Statistical significance (simple t-test on slopes)
                    significance = self._calculate_significance(
                        history[max(0, i-10):i],
                        history[i:min(len(history), i+min_duration)]
                    )
                    
                    tipping_point = TippingPoint(
                        mode=mode_name,
                        step=step,
                        adoption_before=adoption_before,
                        adoption_after=adoption_after,
                        velocity=avg_velocity,
                        trigger=trigger,
                        statistical_significance=significance
                    )
                    
                    tipping_points.append(tipping_point)
                    
                    # Skip ahead to avoid detecting the same tipping point multiple times
                    i += min_duration
        
        return tipping_points
    
    def _smooth_curve(self, data: List[float], window_size: int) -> np.ndarray:
        """Apply moving average smoothing."""
        if len(data) < window_size:
            return np.array(data)
        
        # Use numpy convolve for moving average
        kernel = np.ones(window_size) / window_size
        smoothed = np.convolve(data, kernel, mode='same')
        
        return smoothed
    
    def _identify_trigger(self, mode: str, step: int) -> str:
        """
        Attempt to identify what triggered a tipping point.
        
        Looks at transitions and external factors around the step.
        """
        # Check for policy changes (would need policy history)
        # For now, analyze social influence in transitions
        
        nearby_transitions = [
            t for t in self.transitions
            if t.to_mode == mode and abs(t.step - step) <= 10
        ]
        
        influenced_count = sum(1 for t in nearby_transitions if t.influenced_by)
        
        if influenced_count > len(nearby_transitions) * 0.5:
            return "social_cascade"
        elif len(nearby_transitions) > 0:
            reasons = [t.reason for t in nearby_transitions if t.reason != "unknown"]
            if reasons:
                return reasons[0]
        
        return "unknown"
    
    def _calculate_significance(self, before: List[float], after: List[float]) -> float:
        """
        Calculate statistical significance of slope change.
        
        Returns p-value (lower = more significant).
        """
        if len(before) < 2 or len(after) < 2:
            return 1.0
        
        # Calculate slopes
        x_before = np.arange(len(before))
        x_after = np.arange(len(after))
        
        slope_before, _, _, _, _ = linregress(x_before, before)
        slope_after, _, _, _, _ = linregress(x_after, after)
        
        # Simple test: is the difference large?
        diff = abs(slope_after - slope_before)
        
        # Normalize by standard deviations
        std_before = np.std(before) if len(before) > 1 else 1.0
        std_after = np.std(after) if len(after) > 1 else 1.0
        
        if std_before + std_after > 0:
            normalized_diff = diff / (std_before + std_after)
            # Convert to rough p-value estimate
            return max(0.001, 1.0 / (1.0 + normalized_diff * 10))
        
        return 1.0
    
    # =========================================================================
    # Cascade Analysis
    # =========================================================================
    
    def measure_cascade_effects(
        self,
        mode: str,
        network=None,
        min_cascade_size: int = 3
    ) -> List[CascadeMetrics]:
        """
        Identify and measure social cascades for a mode.
        
        A cascade starts with an early adopter and spreads through
        the social network via influence.
        
        Args:
            mode: Mode to analyze
            network: Social network (optional, for distance calculation)
            min_cascade_size: Minimum adopters to count as cascade
        
        Returns:
            List of detected cascades
        """
        cascades = []
        
        # Get all transitions to this mode with influence
        influenced_transitions = [
            t for t in self.transitions
            if t.to_mode == mode and t.influenced_by
        ]
        
        # Group by origin agent (first in influence chain)
        cascade_origins = self._identify_cascade_origins(influenced_transitions)
        
        cascade_id = 0
        for origin_agent, influenced in cascade_origins.items():
            if len(influenced) < min_cascade_size:
                continue
            
            # Calculate cascade metrics
            steps = [t.step for t in influenced]
            origin_step = min(steps)
            end_step = max(steps)
            duration = end_step - origin_step
            
            velocity = len(influenced) / duration if duration > 0 else 0
            
            # Network distance (if network available)
            max_distance = 0
            total_distance = 0
            if network:
                for transition in influenced:
                    dist = self._calculate_network_distance(
                        network, origin_agent, transition.agent_id
                    )
                    max_distance = max(max_distance, dist)
                    total_distance += dist
            
            avg_distance = total_distance / len(influenced) if influenced else 0
            
            cascade = CascadeMetrics(
                cascade_id=cascade_id,
                origin_agent=origin_agent,
                origin_step=origin_step,
                total_adopters=len(influenced),
                cascade_duration=duration,
                velocity=velocity,
                max_network_distance=max_distance,
                avg_network_distance=avg_distance
            )
            
            cascades.append(cascade)
            cascade_id += 1
        
        return cascades
    
    def _identify_cascade_origins(
        self,
        transitions: List[ModeTransition]
    ) -> Dict[str, List[ModeTransition]]:
        """
        Group transitions by their ultimate origin agent.
        
        Traces influence chains back to the original adopter.
        """
        origins = defaultdict(list)
        
        # Build influence graph
        influenced_by_map = {}
        for t in transitions:
            if t.influenced_by:
                influenced_by_map[t.agent_id] = t.influenced_by[0]  # First influencer
        
        # Trace each transition back to origin
        for transition in transitions:
            origin = self._find_origin(transition.agent_id, influenced_by_map)
            origins[origin].append(transition)
        
        return origins
    
    def _find_origin(self, agent_id: str, influence_map: Dict[str, str]) -> str:
        """Recursively find the origin of an influence chain."""
        if agent_id not in influence_map:
            return agent_id
        
        # Follow chain (with cycle detection)
        visited = set()
        current = agent_id
        
        while current in influence_map and current not in visited:
            visited.add(current)
            current = influence_map[current]
        
        return current
    
    def _calculate_network_distance(self, network, agent1: str, agent2: str) -> int:
        """Calculate shortest path distance in social network."""
        if not network or not hasattr(network, 'shortest_path'):
            return 0
        
        try:
            path = network.shortest_path(agent1, agent2)
            return len(path) - 1 if path else 0
        except:
            return 0
    
    # =========================================================================
    # Transition Analysis
    # =========================================================================
    
    def get_transition_matrix(self) -> Dict[Tuple[str, str], int]:
        """
        Build transition matrix showing flows between modes.
        
        Returns:
            Dict mapping (from_mode, to_mode) -> count
        """
        matrix = defaultdict(int)
        
        for transition in self.transitions:
            key = (transition.from_mode, transition.to_mode)
            matrix[key] += 1
        
        return dict(matrix)
    
    def get_transition_flows(self) -> List[Dict]:
        """
        Get transition flows suitable for Sankey diagram.
        
        Returns:
            List of {source, target, value} dicts
        """
        matrix = self.get_transition_matrix()
        
        flows = []
        for (from_mode, to_mode), count in matrix.items():
            # Skip self-loops (source == target) — Plotly Sankey renders blank/broken
            if from_mode == to_mode:
                logger.debug(f"Sankey: skipping self-loop {from_mode}→{to_mode} (count={count})")
                continue
            # Skip zero-value flows
            if count <= 0:
                continue
            flows.append({
                'source': from_mode,
                'target': to_mode,
                'value': count,
            })
        
        return flows
    
    def get_transitions_by_reason(self) -> Dict[str, List[ModeTransition]]:
        """Group transitions by reason."""
        by_reason = defaultdict(list)
        
        for transition in self.transitions:
            by_reason[transition.reason].append(transition)
        
        return dict(by_reason)
    
    # =========================================================================
    # Summary Reports
    # =========================================================================
    
    def generate_summary_report(self) -> Dict:
        """Generate comprehensive summary of mode share evolution."""
        report = {
            'overview': {
                'total_transitions': len(self.transitions),
                'modes_tracked': list(self.adoption_history.keys()),
                'simulation_duration': len(self.step_history),
            },
            'final_mode_share': {},
            'tipping_points': [],
            'transition_matrix': self.get_transition_matrix(),
            'cascades': [],
        }
        
        # Final mode shares
        for mode, history in self.adoption_history.items():
            if history:
                report['final_mode_share'][mode] = history[-1]
        
        # Detect tipping points for all modes
        for mode in self.adoption_history.keys():
            tipping_points = self.detect_tipping_points(mode=mode)
            for tp in tipping_points:
                report['tipping_points'].append({
                    'mode': tp.mode,
                    'step': tp.step,
                    'adoption_before': tp.adoption_before,
                    'adoption_after': tp.adoption_after,
                    'velocity': tp.velocity,
                    'trigger': tp.trigger,
                })
        
        return report