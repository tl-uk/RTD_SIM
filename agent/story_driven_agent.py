"""
agent/story_driven_agent.py

Story-driven BDI agent that generates behavior from user + job stories.
Extends CognitiveAgent with story-based instantiation.
"""

from __future__ import annotations
from typing import Dict, Any, Tuple, Optional, List
from pathlib import Path
import random
import logging

from agent.cognitive_abm import CognitiveAgent
from agent.user_stories import UserStoryParser, UserStory
from agent.job_stories import JobStoryParser, JobStory

logger = logging.getLogger(__name__)


class StoryDrivenAgent(CognitiveAgent):
    """
    Agent created from user + job stories.
    
    Combines:
    - User story (WHO): personality, beliefs, desires
    - Job story (WHAT): task, constraints, context
    
    Result: Fully parameterized BDI agent with realistic behavior.
    """
    
    def __init__(
        self,
        user_story_id: str,
        job_story_id: str,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        agent_id: Optional[str] = None,
        planner = None,
        seed: Optional[int] = None,
        user_stories_path: Optional[Path] = None,
        job_stories_path: Optional[Path] = None,
        csv_data: Optional[Dict[str, Any]] = None,
        conflict_resolution: str = 'dynamic',  # 'dynamic', 'user_priority', 'job_priority'
        apply_variance: bool = True
    ):
        """
        Initialize story-driven agent.
        
        Args:
            user_story_id: User story identifier (e.g., 'eco_warrior')
            job_story_id: Job story identifier (e.g., 'morning_commute')
            origin: Origin coordinates (lon, lat)
            dest: Destination coordinates (lon, lat)
            agent_id: Optional agent ID (auto-generated if None)
            planner: BDI planner instance
            seed: Random seed for variance
            user_stories_path: Path to personas.yaml
            job_stories_path: Path to job_contexts.yaml
            csv_data: Optional CSV row data
            conflict_resolution: How to resolve desire conflicts
            apply_variance: Whether to apply stochastic variance
        """
        # Store story IDs for reference
        self.user_story_id = user_story_id
        self.job_story_id = job_story_id
        self.conflict_resolution = conflict_resolution
        
        # Parse stories
        user_parser = UserStoryParser(user_stories_path)
        job_parser = JobStoryParser(job_stories_path)
        
        self.user_story = user_parser.load_from_yaml(user_story_id)
        self.job_story = job_parser.load_from_yaml(job_story_id)

        # Extract context from job story
        agent_context = self._extract_agent_context()
        
        # Generate task context
        self.task_context = self.job_story.to_task_context(origin, dest, csv_data)
        
        # Resolve desires (combine user + job)
        desires = self._resolve_desires()
        
        # Apply stochastic variance
        if apply_variance:
            desires = self._apply_variance(desires, seed)
        
        # Generate agent ID if not provided
        if agent_id is None:
            agent_id = f"{user_story_id}_{job_story_id}_{random.randint(1000, 9999)}"
        
        # Initialize parent CognitiveAgent
        super().__init__(
            seed=seed,
            agent_id=agent_id,
            agent_context=agent_context,
            desires=desires,
            planner=planner,
            origin=origin,
            dest=dest
        )
        
        logger.info(f"Created StoryDrivenAgent: {agent_id} "
                   f"({user_story_id} + {job_story_id})")
    
    def _extract_agent_context(self) -> Dict:
        """Extract infrastructure-relevant context from stories."""
        context = {}
        
        # Vehicle requirements from job story
        if self.job_story.vehicle_constraints:
            context['vehicle_type'] = self.job_story.vehicle_constraints.get('type', 'personal')
            context['cargo_capacity'] = self.job_story.vehicle_constraints.get('cargo', False)
        
        # Priority from desire overrides
        if self.job_story.desire_overrides:
            # Emergency services have overridden desires
            context['priority'] = 'emergency'
        elif self.job_story.delivery_params:
            context['priority'] = 'commercial'
        else:
            context['priority'] = 'normal'
        
        # Recurring trips affect charging strategy
        context['recurring'] = self.job_story.parameters.get('recurring', False)
        
        return context

    def _resolve_desires(self) -> Dict[str, float]:
        """
        Resolve desires from user story + job story.
        
        Handles conflicts based on conflict_resolution strategy.
        """
        # Get base desires from user story
        user_desires = self.user_story.to_bdi_desires()
        
        # Check if job story has desire overrides (e.g., emergency)
        if self.job_story.desire_overrides:
            desires = user_desires.copy()
            for key, value in self.job_story.desire_overrides.items():
                desires[key] = value
            logger.debug(f"Applied job story overrides: {self.job_story.desire_overrides}")
            return desires
        
        # Apply conflict resolution strategy
        if self.conflict_resolution == 'user_priority':
            # User story dominates
            return user_desires
        
        elif self.conflict_resolution == 'job_priority':
            # Job story context modifies desires
            return self._apply_job_context_weights(user_desires)
        
        elif self.conflict_resolution == 'dynamic':
            # Dynamic weighting based on urgency
            return self._dynamic_weighting(user_desires)
        
        else:
            logger.warning(f"Unknown conflict resolution: {self.conflict_resolution}")
            return user_desires
    
    def _apply_job_context_weights(self, desires: Dict[str, float]) -> Dict[str, float]:
        """
        Modify desires based on job context.
        
        Example: Time-critical job increases time desire.
        """
        modified = desires.copy()
        
        # Urgency affects time desire
        urgency = self.job_story.parameters.get('urgency', 'medium')
        if urgency == 'critical':
            modified['time'] = min(1.0, modified.get('time', 0.5) + 0.3)
        elif urgency == 'high':
            modified['time'] = min(1.0, modified.get('time', 0.5) + 0.2)
        
        # Recurring trips increase reliability desire
        if self.job_story.parameters.get('recurring'):
            modified['reliability'] = min(1.0, modified.get('reliability', 0.5) + 0.2)
        
        # Time window flexibility
        if self.job_story.time_window:
            if self.job_story.time_window.flexibility in ['none', 'very_low']:
                modified['time'] = min(1.0, modified.get('time', 0.5) + 0.2)
        
        return modified
    
    def _dynamic_weighting(self, desires: Dict[str, float]) -> Dict[str, float]:
        """
        Dynamic weighting: blend user + job based on importance.
        
        Default: 70% user personality, 30% job context.
        """
        modified = self._apply_job_context_weights(desires)
        
        # Blend with original
        blended = {}
        for key in desires:
            user_val = desires.get(key, 0.5)
            job_val = modified.get(key, 0.5)
            # 70% user, 30% job
            blended[key] = 0.7 * user_val + 0.3 * job_val
        
        return blended
    
    def _apply_variance(
        self, 
        desires: Dict[str, float], 
        seed: Optional[int]
    ) -> Dict[str, float]:
        """
        Apply stochastic variance to desires.
        
        Variance amount from user story (default ±10%).
        """
        variance = self.user_story.desire_variance
        rng = random.Random(seed)
        
        varied = {}
        for key, value in desires.items():
            # Apply ±variance% noise
            noise = rng.uniform(-variance, variance)
            varied[key] = max(0.0, min(1.0, value + noise))
        
        return varied
    
    def get_story_context(self) -> Dict[str, Any]:
        """
        Get full story context for this agent.
        
        Useful for debugging and explanation.
        """
        return {
            'user_story_id': self.user_story_id,
            'job_story_id': self.job_story_id,
            'persona_type': self.user_story.persona_type,
            'job_type': self.job_story.job_type,
            'desires': self.desires,
            'beliefs': [b.text for b in self.user_story.beliefs],
            'constraints': self.user_story.constraints + self.task_context.constraints,
            'conflict_resolution': self.conflict_resolution,
        }
    
    def explain_decision(self, action: str) -> str:
        """
        Explain why agent chose this action (for explainability).
        
        BDI agents can articulate their reasoning!
        """
        context = self.get_story_context()
        
        explanation = (
            f"As a {self.user_story_id} performing {self.job_story_id}, "
            f"I chose {action} because:\n"
        )
        
        # Top 3 desires
        top_desires = sorted(self.desires.items(), key=lambda x: x[1], reverse=True)[:3]
        explanation += f"- My priorities are: {', '.join(f'{k}={v:.2f}' for k, v in top_desires)}\n"
        
        # Relevant beliefs
        if self.user_story.beliefs:
            explanation += f"- I believe: {self.user_story.beliefs[0].text}\n"
        
        # Constraints
        if context['constraints']:
            explanation += f"- I must respect: {', '.join(context['constraints'][:2])}\n"
        
        return explanation
    
    def __repr__(self) -> str:
        return (f"StoryDrivenAgent(id={self.state.agent_id}, "
                f"user={self.user_story_id}, job={self.job_story_id})")


# ============================================================================
# Batch Generation Functions
# ============================================================================

def generate_agents_from_stories(
    user_story_ids: List[str],
    job_story_ids: List[str],
    origin_dest_pairs: List[Tuple[Tuple[float, float], Tuple[float, float]]],
    planner = None,
    seed: Optional[int] = None,
    user_stories_path: Optional[Path] = None,
    job_stories_path: Optional[Path] = None
) -> List[StoryDrivenAgent]:
    """
    Generate multiple agents from story combinations.
    
    Args:
        user_story_ids: List of user story IDs
        job_story_ids: List of job story IDs
        origin_dest_pairs: List of (origin, dest) coordinate pairs
        planner: BDI planner instance
        seed: Random seed for reproducibility
        user_stories_path: Path to personas.yaml
        job_stories_path: Path to job_contexts.yaml
    
    Returns:
        List of StoryDrivenAgent instances
    
    Example:
        >>> user_stories = ['eco_warrior', 'busy_parent', 'student']
        >>> job_stories = ['morning_commute', 'school_run']
        >>> od_pairs = [((lon1, lat1), (lon2, lat2)), ...]
        >>> agents = generate_agents_from_stories(user_stories, job_stories, od_pairs)
    """
    agents = []
    rng = random.Random(seed)
    
    for i, (origin, dest) in enumerate(origin_dest_pairs):
        # Pick random user + job story
        user_story = rng.choice(user_story_ids)
        job_story = rng.choice(job_story_ids)
        
        agent = StoryDrivenAgent(
            user_story_id=user_story,
            job_story_id=job_story,
            origin=origin,
            dest=dest,
            planner=planner,
            seed=seed + i if seed else None,
            user_stories_path=user_stories_path,
            job_stories_path=job_stories_path
        )
        agents.append(agent)
    
    logger.info(f"Generated {len(agents)} agents from stories")
    return agents


def generate_balanced_population(
    num_agents: int,
    user_story_ids: List[str],
    job_story_ids: List[str],
    origin_dest_generator,  # Callable that returns (origin, dest)
    planner = None,
    seed: Optional[int] = None,
    user_stories_path: Optional[Path] = None,
    job_stories_path: Optional[Path] = None
) -> List[StoryDrivenAgent]:
    """
    Generate balanced population with even story distribution.
    
    Ensures each user story + job story combination is represented.
    
    Args:
        num_agents: Target number of agents
        user_story_ids: List of user story IDs
        job_story_ids: List of job story IDs
        origin_dest_generator: Function that returns (origin, dest) tuple
        planner: BDI planner instance
        seed: Random seed
        user_stories_path: Path to personas.yaml
        job_stories_path: Path to job_contexts.yaml
    
    Returns:
        List of StoryDrivenAgent instances
    """
    agents = []
    rng = random.Random(seed)
    
    # Calculate agents per combination
    total_combinations = len(user_story_ids) * len(job_story_ids)
    agents_per_combo = max(1, num_agents // total_combinations)
    
    logger.info(f"Generating {agents_per_combo} agents per combination")
    
    for user_story in user_story_ids:
        for job_story in job_story_ids:
            for i in range(agents_per_combo):
                origin, dest = origin_dest_generator()
                
                agent = StoryDrivenAgent(
                    user_story_id=user_story,
                    job_story_id=job_story,
                    origin=origin,
                    dest=dest,
                    planner=planner,
                    seed=seed + len(agents) if seed else None,
                    user_stories_path=user_stories_path,
                    job_stories_path=job_stories_path
                )
                agents.append(agent)
                
                if len(agents) >= num_agents:
                    break
            if len(agents) >= num_agents:
                break
        if len(agents) >= num_agents:
            break
    
    logger.info(f"Generated {len(agents)} balanced agents")
    return agents