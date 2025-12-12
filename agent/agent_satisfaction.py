"""
agent/agent_satisfaction.py

Mixin for tracking agent satisfaction with mode choices.
Integrates with RealisticSocialInfluence system.

Usage:
    Simply import and the tracking happens automatically in agent.step()
"""

from __future__ import annotations
from typing import Dict, Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from agent.cognitive_abm import CognitiveAgent

logger = logging.getLogger(__name__)


def calculate_mode_satisfaction(
    agent: 'CognitiveAgent',
    env,
    expected_metrics: Optional[Dict[str, float]] = None
) -> float:
    """
    Calculate agent satisfaction with current mode choice.
    
    Based on:
    - Time expectations vs reality
    - Cost expectations vs reality  
    - Comfort/risk alignment with desires
    - Emissions alignment with eco desires
    
    Args:
        agent: CognitiveAgent instance
        env: SpatialEnvironment (optional, for better estimates)
        expected_metrics: Optional pre-computed expectations
    
    Returns:
        Satisfaction score (0-1, where 1 = very satisfied)
    """
    mode = agent.state.mode
    desires = agent.desires
    
    # If no expectations provided, use reasonable defaults
    if expected_metrics is None:
        expected_metrics = _estimate_expectations(agent, env, mode)
    
    # Calculate component satisfactions
    satisfactions = []
    weights = []
    
    # 1. TIME SATISFACTION
    if 'expected_time' in expected_metrics:
        actual = agent.state.travel_time_min
        expected = expected_metrics['expected_time']
        
        if expected > 0:
            time_ratio = actual / expected
            # Satisfied if within 20% of expectation
            time_sat = max(0.0, 1.0 - abs(time_ratio - 1.0) * 2.0)
            satisfactions.append(time_sat)
            weights.append(desires.get('time', 0.5))
    
    # 2. COST SATISFACTION  
    if 'expected_cost' in expected_metrics:
        # For simplicity, assume cost matched expectations
        # (In full system, would track actual spending)
        cost_sat = 0.8  # Generally satisfied with cost
        satisfactions.append(cost_sat)
        weights.append(desires.get('cost', 0.3))
    
    # 3. ECO SATISFACTION
    if 'expected_emissions' in expected_metrics:
        actual = agent.state.emissions_g
        expected = expected_metrics['expected_emissions']
        
        if expected > 0:
            eco_ratio = actual / expected
            # Eco-conscious agents care more
            eco_sat = max(0.0, 1.0 - abs(eco_ratio - 1.0))
            satisfactions.append(eco_sat)
            weights.append(desires.get('eco', 0.6))
    
    # 4. COMFORT/SAFETY (based on mode characteristics)
    mode_comfort = _get_mode_comfort(mode)
    mode_safety = _get_mode_safety(mode)
    
    # Comfort satisfaction
    comfort_desire = desires.get('comfort', 0.3)
    comfort_sat = mode_comfort
    satisfactions.append(comfort_sat)
    weights.append(comfort_desire)
    
    # Safety satisfaction
    safety_desire = desires.get('safety', 0.5) 
    safety_sat = mode_safety
    satisfactions.append(safety_sat)
    weights.append(safety_desire)
    
    # Weight and combine
    total_weight = sum(weights)
    if total_weight > 0:
        overall = sum(s * w for s, w in zip(satisfactions, weights)) / total_weight
    else:
        overall = 0.5  # Neutral
    
    return max(0.0, min(1.0, overall))


def _estimate_expectations(agent, env, mode: str) -> Dict[str, float]:
    """Estimate what agent expected from this mode choice."""
    expectations = {}
    
    if env and agent.state.route:
        # Use environment to estimate
        try:
            expectations['expected_time'] = env.estimate_travel_time(
                agent.state.route, mode
            )
            expectations['expected_cost'] = env.estimate_monetary_cost(
                agent.state.route, mode
            )
            expectations['expected_emissions'] = env.estimate_emissions(
                agent.state.route, mode
            )
        except:
            pass
    
    # Fallback estimates if environment unavailable
    if 'expected_time' not in expectations:
        expectations['expected_time'] = agent.state.travel_time_min
    if 'expected_cost' not in expectations:
        expectations['expected_cost'] = 1.0
    if 'expected_emissions' not in expectations:
        expectations['expected_emissions'] = agent.state.emissions_g
    
    return expectations


def _get_mode_comfort(mode: str) -> float:
    """Mode comfort ratings (0-1)."""
    comfort_map = {
        'walk': 0.5,
        'bike': 0.6,
        'ebike': 0.7,
        'scooter': 0.6,
        'bus': 0.6,
        'train': 0.7,
        'tram': 0.7,
        'car': 0.8,
        'ev': 0.8,
        'taxi': 0.9,
    }
    return comfort_map.get(mode, 0.5)


def _get_mode_safety(mode: str) -> float:
    """Mode safety ratings (0-1)."""
    safety_map = {
        'walk': 0.7,
        'bike': 0.5,
        'ebike': 0.5,
        'scooter': 0.4,
        'bus': 0.8,
        'train': 0.9,
        'tram': 0.9,
        'car': 0.7,
        'ev': 0.7,
        'taxi': 0.8,
    }
    return safety_map.get(mode, 0.6)


# ============================================================================
# Integration Hook for CognitiveAgent
# ============================================================================

def add_satisfaction_tracking(agent_class):
    """
    Decorator to add satisfaction tracking to CognitiveAgent.
    
    Usage:
        @add_satisfaction_tracking
        class CognitiveAgent:
            ...
    """
    original_step = agent_class.step
    
    def step_with_satisfaction(self, env=None):
        """Enhanced step that tracks satisfaction."""
        # Store pre-step expectations
        expected_time = None
        if env and hasattr(self.state, 'route') and self.state.route:
            try:
                expected_time = env.estimate_travel_time(
                    self.state.route, self.state.mode
                )
            except:
                pass
        
        # Call original step
        result = original_step(self, env)
        
        # Calculate satisfaction if not arrived
        if not self.state.arrived and env:
            expectations = {}
            if expected_time:
                expectations['expected_time'] = expected_time
            
            self._current_satisfaction = calculate_mode_satisfaction(
                self, env, expectations
            )
        
        return result
    
    agent_class.step = step_with_satisfaction
    return agent_class


# ============================================================================
# Direct Integration Example
# ============================================================================

def integrate_realistic_influence_with_simulation(
    agents,
    network,
    env,
    influence_system
):
    """
    Complete integration pattern for simulation loop.
    
    Args:
        agents: List of CognitiveAgent or StoryDrivenAgent
        network: SocialNetwork instance
        env: SpatialEnvironment instance
        influence_system: RealisticSocialInfluence instance
    
    Usage in simulation loop:
        
        for step in range(num_steps):
            influence_system.advance_time()
            
            for agent in agents:
                # Apply realistic influence
                mode_costs = {...}
                adjusted = network.apply_social_influence(
                    agent.state.agent_id, mode_costs
                )
                
                # Agent acts
                agent.step(env)
                
                # Track satisfaction for realistic system
                if not agent.state.arrived:
                    satisfaction = calculate_mode_satisfaction(agent, env)
                    influence_system.record_mode_usage(
                        agent.state.agent_id,
                        agent.state.mode,
                        satisfaction
                    )
    """
    pass  # This is just documentation


# ============================================================================
# Personality-Based Influence Configuration
# ============================================================================

def get_influence_config_for_agent(agent) -> Dict[str, float]:
    """
    Get realistic influence configuration based on agent personality.
    
    Different user stories have different susceptibility to influence.
    
    Args:
        agent: StoryDrivenAgent with user_story_id attribute
    
    Returns:
        Configuration dict for RealisticSocialInfluence
    """
    # Default configuration
    config = {
        'decay_rate': 0.15,
        'habit_weight': 0.4,
        'experience_weight': 0.4,
        'peer_weight': 0.2
    }
    
    # Personality-specific adjustments
    if hasattr(agent, 'user_story_id'):
        story_id = agent.user_story_id
        
        if story_id == 'eco_warrior':
            # Experience-driven (strong convictions)
            config['habit_weight'] = 0.3
            config['experience_weight'] = 0.5
            config['peer_weight'] = 0.2
        
        elif story_id == 'budget_student':
            # Peer-influenced (follows trends)
            config['habit_weight'] = 0.2
            config['experience_weight'] = 0.3
            config['peer_weight'] = 0.5
            config['decay_rate'] = 0.1  # Slower decay
        
        elif story_id == 'business_commuter':
            # Habit-driven (routine matters)
            config['habit_weight'] = 0.6
            config['experience_weight'] = 0.3
            config['peer_weight'] = 0.1
            config['decay_rate'] = 0.2  # Faster decay
        
        elif story_id == 'concerned_parent':
            # Safety-focused (experience + habit)
            config['habit_weight'] = 0.5
            config['experience_weight'] = 0.4
            config['peer_weight'] = 0.1
        
        elif story_id == 'rural_resident':
            # Practical (habit dominates)
            config['habit_weight'] = 0.6
            config['experience_weight'] = 0.3
            config['peer_weight'] = 0.1
        
        elif story_id == 'tourist':
            # Experience-seeking (peers matter)
            config['habit_weight'] = 0.1
            config['experience_weight'] = 0.5
            config['peer_weight'] = 0.4
    
    return config