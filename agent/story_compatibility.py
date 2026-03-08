"""
agent/story_compatibility.py

This module implements a compatibility system for user stories and job stories in the 
agent-based transport simulation. It defines rules to filter out unrealistic combinations 
of user personas and job scenarios, ensuring that generated agents have plausible motivations 
and behaviors. The system includes functions to check compatibility, generate preferred 
combinations, and explain incompatibilities, which can be integrated into the agent generation 
process to create a more realistic and coherent population of agents for simulation.

NOTE: This is experimental and filters may not be perfect - we can adjust rules as we see what 
combinations are generated and how they behave in the simulation.

"""

from typing import List, Tuple, Set
import logging

logger = logging.getLogger(__name__)


# Define incompatible combinations
INCOMPATIBLE_COMBINATIONS = {
    # ========================================================================
    # FREIGHT & PROFESSIONAL DELIVERY JOBS
    # ========================================================================
    
    'freight_delivery_route': {
        'incompatible_users': [
            'budget_student',      # Students don't drive commercial trucks
            'concerned_parent',    # Parents doing school runs, not freight
            'disabled_commuter',   # May have medical restrictions
            'tourist',             # Tourists don't work
            'eco_warrior',         # Unless they're a professional driver
            'business_commuter',   # Office workers, not truck drivers
            'shift_worker',        # Generic shift work, not freight-specific
        ]
    },
    
    'gig_economy_delivery': {
        'incompatible_users': [
            'concerned_parent',    # Unlikely with young children
            'disabled_commuter',   # May have mobility/medical restrictions
            'tourist',             # Tourists don't work
            'freight_operator',    # Professional drivers don't do gig work
            'business_commuter',   # Office job, not delivery
        ]
    },
    
    'urban_food_delivery': {
        'incompatible_users': [
            'concerned_parent',    # Unlikely with young children needing care
            'tourist',             # Tourists don't work
            'freight_operator',    # Wrong profession (freight != food delivery)
        ]
    },
    
    'urban_parcel_delivery': {
        'incompatible_users': [
            'tourist',             # Tourists don't work
            'freight_operator',    # Wrong scale (freight = large vehicles, parcels = vans/bikes)
        ]
    },
    
    # ========================================================================
    # PERSONAL & LEISURE TRIPS
    # ========================================================================
    
    'shopping_trip': {
        'incompatible_users': [
            'freight_operator',    # Professional driver on duty, not personal shopping
            'delivery_driver',     # On delivery duty, not personal errands
        ]
    },
    
    'flexible_leisure': {
        'incompatible_users': [
            'freight_operator',    # On the job, not leisure time
            'delivery_driver',     # On delivery duty
            'business_commuter',   # Structured work schedule, not flexible leisure
        ]
    },
    
    # ========================================================================
    # FAMILY & SCHOOL TRIPS
    # ========================================================================
    
    'school_run_then_work': {
        'incompatible_users': [
            'budget_student',      # Students don't have school-age children
            'tourist',             # Tourists don't have kids in local schools
            'freight_operator',    # Professional drivers have different schedules
            'delivery_driver',     # Delivery schedule incompatible with school hours
        ]
    },
    
    # ========================================================================
    # TOURISM & EXPLORATION
    # ========================================================================
    
    'tourist_exploration': {
        'incompatible_users': [
            'freight_operator',    # Working, not touring
            'delivery_driver',     # Working, not touring
            'business_commuter',   # Working, not touring
            'concerned_parent',    # Parenting duties, not tourism
        ]
    },
    
    # ========================================================================
    # COMMUTE TRIPS
    # ========================================================================
    
    'morning_commute': {
        'incompatible_users': [
            'tourist',             # Tourists don't commute to work
        ]
    },
    
    'evening_commute': {
        'incompatible_users': [
            'tourist',             # Tourists don't commute
        ]
    },
    
    'night_shift': {
        'incompatible_users': [
            'tourist',             # Tourists don't work night shifts
            'concerned_parent',    # Unlikely with young children (may be overly restrictive)
        ]
    },
    
    # ========================================================================
    # SPECIAL TRIPS
    # ========================================================================
    
    'airport_transfer': {
        'incompatible_users': [
            'freight_operator',    # On delivery duty, not flying
            'delivery_driver',     # On delivery duty, not traveling
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