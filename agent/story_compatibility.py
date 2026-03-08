"""
agent/story_compatibility.py

WHITELIST-BASED compatibility system for user stories and job stories.

Instead of listing hundreds of incompatible combinations, this system defines
which user stories ARE compatible with each job type. Everything else is blocked.

This is much more maintainable and safer than a blacklist approach.
"""

from typing import List, Tuple, Set
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# WHITELIST APPROACH: Define which users CAN do each job
# ============================================================================

# For each job type, list the ONLY user stories that make sense
# If a user story is not in this list for a job, the combination is BLOCKED

COMPATIBLE_USERS_FOR_JOB = {
    
    # ========================================================================
    # FREIGHT & LOGISTICS JOBS (Professional drivers only)
    # ========================================================================
    
    'freight_delivery_route': ['freight_operator', 'delivery_driver', 'rural_resident'],
    'waste_collection': ['freight_operator', 'shift_worker'],
    'regional_distribution': ['freight_operator', 'delivery_driver', 'business_commuter'],
    'construction_supply': ['freight_operator', 'rural_resident'],
    'furniture_delivery': ['freight_operator', 'delivery_driver'],
    'trades_contractor': ['freight_operator', 'rural_resident', 'business_commuter'],
    'supermarket_supply': ['freight_operator', 'delivery_driver'],
    
    # ========================================================================
    # GIG ECONOMY & DELIVERY JOBS (Flexible workers)
    # ========================================================================
    
    'gig_economy_delivery': ['delivery_driver', 'budget_student', 'shift_worker', 'eco_warrior'],
    'urban_food_delivery': ['delivery_driver', 'budget_student', 'shift_worker'],
    'urban_parcel_delivery': ['delivery_driver', 'budget_student', 'shift_worker'],
    
    # ========================================================================
    # PERSONAL & FAMILY TRIPS (Most personas can do these)
    # ========================================================================
    
    'shopping_trip': [
        'concerned_parent', 'disabled_commuter', 'budget_student', 
        'rural_resident', 'eco_warrior', 'shift_worker', 'tourist'
    ],
    
    'school_run_then_work': ['concerned_parent'],  # ONLY parents
    
    'flexible_leisure': [
        'budget_student', 'tourist', 'eco_warrior', 
        'disabled_commuter', 'rural_resident'
    ],
    
    'medical_appointment': [
        'disabled_commuter', 'concerned_parent', 'budget_student', 
        'eco_warrior', 'shift_worker', 'rural_resident'
    ],
    
    # ========================================================================
    # TOURISM & EXPLORATION (Tourists + leisure seekers)
    # ========================================================================
    
    'tourist_exploration': ['tourist', 'eco_warrior'],
    'tourist_scenic_trail': ['tourist', 'eco_warrior', 'budget_student'],
    'island_ferry_trip': ['tourist', 'rural_resident', 'eco_warrior'],
    
    # ========================================================================
    # COMMUTE JOBS (Workers & students)
    # ========================================================================
    
    'morning_commute': [
        'business_commuter', 'shift_worker', 'eco_warrior', 
        'disabled_commuter', 'budget_student'
    ],
    
    'evening_commute': [
        'business_commuter', 'shift_worker', 'eco_warrior', 
        'disabled_commuter', 'budget_student'
    ],
    
    'night_shift': ['shift_worker', 'delivery_driver', 'freight_operator'],
    
    'commute_flexible': [
        'business_commuter', 'eco_warrior', 'disabled_commuter', 'budget_student'
    ],
    
    # ========================================================================
    # BUSINESS & PROFESSIONAL TRAVEL (Business travelers only)
    # ========================================================================
    
    'airport_transfer': ['business_commuter', 'tourist'],
    'business_flight': ['business_commuter'],  # ONLY business travelers
    'conference_attendance': ['business_commuter', 'eco_warrior'],
    
    # ========================================================================
    # SPECIAL TRIPS (Broader access)
    # ========================================================================
    
    'emergency_trip': [
        'concerned_parent', 'disabled_commuter', 'budget_student', 
        'business_commuter', 'eco_warrior', 'shift_worker', 'rural_resident'
    ],
}


# ============================================================================
# Compatibility Check Function (Whitelist-based)
# ============================================================================

def is_compatible(user_story_id: str, job_story_id: str) -> bool:
    """
    Check if user story + job story combination makes sense.
    
    WHITELIST LOGIC:
    - If job has explicit whitelist → check if user is in allowed list
    - If job NOT in whitelist → allow all (assume generic job)
    
    Args:
        user_story_id: User story identifier (e.g., 'concerned_parent')
        job_story_id: Job story identifier (e.g., 'shopping_trip')
    
    Returns:
        True if compatible (allowed), False otherwise
    
    Examples:
        >>> is_compatible('concerned_parent', 'shopping_trip')
        True  # Parent in shopping_trip whitelist
        
        >>> is_compatible('concerned_parent', 'waste_collection')
        False  # Parent NOT in waste_collection whitelist
    """
    # If job has explicit whitelist, check it
    if job_story_id in COMPATIBLE_USERS_FOR_JOB:
        allowed_users = COMPATIBLE_USERS_FOR_JOB[job_story_id]
        
        if user_story_id in allowed_users:
            return True
        else:
            logger.debug(
                f"❌ Blocked: {user_story_id} + {job_story_id} "
                f"(user not in whitelist: {allowed_users})"
            )
            return False
    
    # If job not in whitelist, allow all (generic job)
    logger.debug(f"⚠️ No whitelist for {job_story_id}, allowing {user_story_id}")
    return True


def filter_compatible_combinations(
    user_story_ids: List[str],
    job_story_ids: List[str]
) -> List[Tuple[str, str]]:
    """
    Get all compatible user + job story combinations.
    
    Uses whitelist-based filtering.
    
    Args:
        user_story_ids: List of user story IDs
        job_story_ids: List of job story IDs
    
    Returns:
        List of (user_story_id, job_story_id) tuples that are compatible
    """
    compatible = []
    
    for user_story in user_story_ids:
        for job_story in job_story_ids:
            if is_compatible(user_story, job_story):
                compatible.append((user_story, job_story))
    
    total_combos = len(user_story_ids) * len(job_story_ids)
    filtered_count = total_combos - len(compatible)
    
    logger.info(
        f"✅ Filtered {filtered_count} incompatible combinations "
        f"({len(compatible)}/{total_combos} valid)"
    )
    
    return compatible


def get_preferred_combinations(
    user_story_ids: List[str],
    job_story_ids: List[str],
    min_coverage: float = 0.8
) -> List[Tuple[str, str]]:
    """
    Get preferred combinations that make most sense.
    
    Simply returns all compatible combinations (whitelist already ensures quality).
    
    Args:
        user_story_ids: Available user stories
        job_story_ids: Available job stories
        min_coverage: Ignored (kept for API compatibility)
    
    Returns:
        List of (user_story_id, job_story_id) tuples
    """
    return filter_compatible_combinations(user_story_ids, job_story_ids)


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
        if job_story_id in COMPATIBLE_USERS_FOR_JOB:
            allowed = COMPATIBLE_USERS_FOR_JOB[job_story_id]
            return (
                f"❌ {user_story_id} + {job_story_id} is incompatible: "
                f"{user_story_id} is not in the allowed list for this job.\n"
                f"Allowed personas: {', '.join(allowed)}"
            )
        else:
            return f"❌ {user_story_id} + {job_story_id}: No whitelist defined for this job"
    
    return f"✅ {user_story_id} + {job_story_id} is compatible"


# ============================================================================
# Integration with Simulation Runner
# ============================================================================

def create_realistic_agent_pool(
    num_agents: int,
    user_story_ids: List[str],
    job_story_ids: List[str],
    strategy: str = 'compatible'
) -> List[Tuple[str, str]]:
    """
    Create a pool of (user_story, job_story) pairs for agent generation.
    
    Args:
        num_agents: Number of agents to create
        user_story_ids: Available user stories
        job_story_ids: Available job stories
        strategy: Selection strategy (only 'compatible' and 'preferred' supported now)
    
    Returns:
        List of (user_story_id, job_story_id) tuples
    """
    # Get compatible combinations
    combinations = filter_compatible_combinations(user_story_ids, job_story_ids)
    
    if not combinations:
        logger.warning("⚠️ No compatible combinations found - check whitelists!")
        return []
    
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
    
    logger.info(
        f"✅ Created agent pool: {len(pool)} agents, "
        f"{len(combinations)} unique combinations (whitelist-filtered)"
    )
    
    return pool


# ============================================================================
# Diagnostic Functions
# ============================================================================

def get_all_compatible_jobs_for_user(user_story_id: str, all_job_ids: List[str]) -> List[str]:
    """Get all jobs this user can do."""
    return [job for job in all_job_ids if is_compatible(user_story_id, job)]


def get_all_compatible_users_for_job(job_story_id: str) -> List[str]:
    """Get all users who can do this job."""
    if job_story_id in COMPATIBLE_USERS_FOR_JOB:
        return COMPATIBLE_USERS_FOR_JOB[job_story_id]
    else:
        return []  # No whitelist = no users allowed (conservative)


def print_compatibility_matrix(user_story_ids: List[str], job_story_ids: List[str]):
    """Print a compatibility matrix for debugging."""
    print("\n" + "="*80)
    print("COMPATIBILITY MATRIX (Whitelist-based)")
    print("="*80)
    
    for job in job_story_ids:
        compatible_users = [u for u in user_story_ids if is_compatible(u, job)]
        print(f"\n{job}:")
        print(f"  ✅ Compatible: {', '.join(compatible_users) if compatible_users else 'NONE'}")
        print(f"  ❌ Blocked: {len(user_story_ids) - len(compatible_users)} user stories")
    
    print("\n" + "="*80)