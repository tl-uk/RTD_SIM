"""
agent/story_compatibility.py

Filters out nonsensical user story + job story combinations.
Ensures realistic agent generation.

CREATE THIS FILE: agent/story_compatibility.py
"""

from typing import List, Tuple, Set
import logging

logger = logging.getLogger(__name__)


# Define incompatible combinations
INCOMPATIBLE_COMBINATIONS = {
    # Freight jobs are professional - not for casual personas
    'freight_delivery_route': {
        'incompatible_users': [
            'budget_student',
            'concerned_parent', 
            'disabled_commuter',
            'tourist',
            'eco_warrior',  # Unless they're a professional driver
        ]
    },
    
    'gig_economy_delivery': {
        'incompatible_users': [
            'concerned_parent',  # Unlikely to do gig work with kids
            'disabled_commuter',
            'tourist',
        ]
    },
    
    # School run is parent-specific
    'school_run_then_work': {
        'incompatible_users': [
            'budget_student',
            'tourist',
            'freight_operator',
            'delivery_driver',
        ]
    },
    
    # Tourism is for tourists
    'tourist_exploration': {
        'incompatible_users': [
            'freight_operator',
            'delivery_driver',
            'business_commuter',  # They're working, not touring
        ]
    },
    
    # Night shift is for shift workers
    'night_shift': {
        'incompatible_users': [
            'tourist',
            'concerned_parent',  # Unlikely with young children
        ]
    },
}


# Define preferred combinations (for smart defaults)
PREFERRED_COMBINATIONS = {
    'freight_delivery_route': ['freight_operator', 'delivery_driver', 'rural_resident'],
    'gig_economy_delivery': ['delivery_driver', 'budget_student', 'shift_worker'],
    'school_run_then_work': ['concerned_parent'],
    'tourist_exploration': ['tourist'],
    'morning_commute': ['business_commuter', 'eco_warrior', 'disabled_commuter', 'shift_worker'],
    'flexible_leisure': ['budget_student', 'tourist', 'eco_warrior'],
    'night_shift': ['shift_worker'],
    'shopping_trip': ['concerned_parent', 'rural_resident'],
    'airport_transfer': ['business_commuter', 'tourist'],
}


def is_compatible(user_story_id: str, job_story_id: str) -> bool:
    """
    Check if user story + job story combination is realistic.
    
    Args:
        user_story_id: User story identifier
        job_story_id: Job story identifier
    
    Returns:
        True if compatible, False otherwise
    """
    # Check if job has incompatibility rules
    if job_story_id in INCOMPATIBLE_COMBINATIONS:
        rules = INCOMPATIBLE_COMBINATIONS[job_story_id]
        incompatible_users = rules.get('incompatible_users', [])
        
        if user_story_id in incompatible_users:
            logger.debug(f"Incompatible: {user_story_id} + {job_story_id}")
            return False
    
    return True


def filter_compatible_combinations(
    user_story_ids: List[str],
    job_story_ids: List[str]
) -> List[Tuple[str, str]]:
    """
    Get all compatible user + job story combinations.
    
    Args:
        user_story_ids: List of user story IDs
        job_story_ids: List of job story IDs
    
    Returns:
        List of (user_story_id, job_story_id) tuples
    """
    compatible = []
    
    for user_story in user_story_ids:
        for job_story in job_story_ids:
            if is_compatible(user_story, job_story):
                compatible.append((user_story, job_story))
    
    total_combos = len(user_story_ids) * len(job_story_ids)
    filtered_count = total_combos - len(compatible)
    
    if filtered_count > 0:
        logger.info(f"Filtered {filtered_count} incompatible combinations "
                   f"({len(compatible)}/{total_combos} valid)")
    
    return compatible


def get_preferred_combinations(
    user_story_ids: List[str],
    job_story_ids: List[str],
    min_coverage: float = 0.8
) -> List[Tuple[str, str]]:
    """
    Get preferred combinations that make most sense.
    
    Use this for testing or when you want realistic default populations.
    
    Args:
        user_story_ids: Available user stories
        job_story_ids: Available job stories
        min_coverage: Minimum fraction of jobs to cover (0-1)
    
    Returns:
        List of (user_story_id, job_story_id) tuples
    """
    preferred = []
    covered_jobs = set()
    
    # First pass: Add all preferred combinations
    for job_story in job_story_ids:
        if job_story in PREFERRED_COMBINATIONS:
            preferred_users = PREFERRED_COMBINATIONS[job_story]
            
            for user_story in preferred_users:
                if user_story in user_story_ids:
                    preferred.append((user_story, job_story))
                    covered_jobs.add(job_story)
    
    # Second pass: Ensure all jobs are covered
    for job_story in job_story_ids:
        if job_story not in covered_jobs:
            # Find any compatible user
            for user_story in user_story_ids:
                if is_compatible(user_story, job_story):
                    preferred.append((user_story, job_story))
                    covered_jobs.add(job_story)
                    break
    
    logger.info(f"Generated {len(preferred)} preferred combinations "
               f"covering {len(covered_jobs)}/{len(job_story_ids)} jobs")
    
    return preferred


def explain_incompatibility(user_story_id: str, job_story_id: str) -> str:
    """
    Explain why a combination is incompatible.
    
    Args:
        user_story_id: User story identifier
        job_story_id: Job story identifier
    
    Returns:
        Explanation string
    """
    if not is_compatible(user_story_id, job_story_id):
        if job_story_id in INCOMPATIBLE_COMBINATIONS:
            return (f"{user_story_id} + {job_story_id} is incompatible: "
                   f"This persona wouldn't typically perform this job.")
    
    return f"{user_story_id} + {job_story_id} is compatible"


# ============================================================================
# Integration with Simulation Runner
# ============================================================================

def create_realistic_agent_pool(
    num_agents: int,
    user_story_ids: List[str],
    job_story_ids: List[str],
    strategy: str = 'compatible'  # 'compatible', 'preferred', 'all'
) -> List[Tuple[str, str]]:
    """
    Create a pool of (user_story, job_story) pairs for agent generation.
    
    Args:
        num_agents: Number of agents to create
        user_story_ids: Available user stories
        job_story_ids: Available job stories
        strategy: Selection strategy:
            - 'compatible': All compatible combinations (balanced)
            - 'preferred': Only preferred combinations (realistic)
            - 'all': All combinations (including nonsensical)
    
    Returns:
        List of (user_story_id, job_story_id) tuples
    """
    if strategy == 'all':
        # No filtering
        combinations = [
            (u, j) for u in user_story_ids for j in job_story_ids
        ]
    elif strategy == 'preferred':
        # Only preferred combinations
        combinations = get_preferred_combinations(user_story_ids, job_story_ids)
    else:  # 'compatible' (default)
        # All compatible combinations
        combinations = filter_compatible_combinations(user_story_ids, job_story_ids)
    
    if not combinations:
        logger.warning("No valid combinations found - using all")
        combinations = [(u, j) for u in user_story_ids for j in job_story_ids]
    
    # Calculate how many agents per combination
    agents_per_combo = max(1, num_agents // len(combinations))
    remainder = num_agents % len(combinations)
    
    pool = []
    for i, (user_story, job_story) in enumerate(combinations):
        # Add base number of agents for this combo
        count = agents_per_combo
        # Add one more for first N combinations (to handle remainder)
        if i < remainder:
            count += 1
        
        for _ in range(count):
            pool.append((user_story, job_story))
    
    logger.info(f"Created agent pool: {len(pool)} agents, "
               f"{len(combinations)} unique combinations, "
               f"strategy='{strategy}'")
    
    return pool