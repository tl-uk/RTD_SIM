# agent/__init__.py
"""
RTD_SIM Agent Module

Phase 1: BDI cognitive agents
Phase 2: Route planning integration
Phase 3: Story-driven agent generation
"""

from agent.cognitive_abm import CognitiveAgent, AgentState
from agent.bdi_planner import BDIPlanner, Action, ActionScore

# Phase 3: Story framework
try:
    from agent.user_stories import (
        UserStoryParser, 
        UserStory, 
        Belief,
        load_user_story,
        list_user_stories
    )
    from agent.job_stories import (
        JobStoryParser, 
        JobStory, 
        TaskContext,
        TimeWindow,
        load_job_story,
        list_job_stories
    )
    from agent.story_driven_agent import (
        StoryDrivenAgent,
        generate_agents_from_stories,
        generate_balanced_population
    )
    STORY_FRAMEWORK_AVAILABLE = True
except ImportError:
    STORY_FRAMEWORK_AVAILABLE = False

# Phase 4: Social networks
try:
    from agent.social_network import (
        SocialNetwork,
        SocialTie,
        NetworkMetrics
    )
    SOCIAL_NETWORK_AVAILABLE = True
except ImportError:
    SOCIAL_NETWORK_AVAILABLE = False

# Phase 4b: Realistic social influence
try:
    from agent.social_influence_dynamics import (
        RealisticSocialInfluence,
        InfluenceMemory,
        HabitState,
        enhance_social_network_with_realism,
        calculate_satisfaction
    )
    REALISTIC_INFLUENCE_AVAILABLE = True
except ImportError:
    REALISTIC_INFLUENCE_AVAILABLE = False


__all__ = [
    # Phase 1: Core BDI
    'CognitiveAgent',
    'AgentState',
    'BDIPlanner',
    'Action',
    'ActionScore',
]

# Add Phase 3 exports if available
if STORY_FRAMEWORK_AVAILABLE:
    __all__.extend([
        'UserStoryParser',
        'UserStory',
        'Belief',
        'load_user_story',
        'list_user_stories',
        'JobStoryParser',
        'JobStory',
        'TaskContext',
        'TimeWindow',
        'load_job_story',
        'list_job_stories',
        'StoryDrivenAgent',
        'generate_agents_from_stories',
        'generate_balanced_population',
    ])

# Add Phase 4 exports if available
if SOCIAL_NETWORK_AVAILABLE:
    __all__.extend(['SocialNetwork', 'SocialTie', 'NetworkMetrics'])

# Add Phase 4b exports if available
if REALISTIC_INFLUENCE_AVAILABLE:
    __all__.extend([
        'RealisticSocialInfluence',
        'InfluenceMemory', 
        'HabitState',
        'enhance_social_network_with_realism',
        'calculate_satisfaction'
    ])

__version__ = '4.1.0'