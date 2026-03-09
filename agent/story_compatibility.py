"""
agent/story_compatibility.py

COMPLETE WHITELIST-BASED compatibility system.

Based on actual RTD_SIM personas.yaml and job types from logs.
"""

from typing import List, Tuple
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# COMPLETE WHITELIST: User Stories That Can Do Each Job
# ============================================================================

# All 10 user personas from personas.yaml:
# - eco_warrior (passenger)
# - concerned_parent (passenger)
# - budget_student (passenger)
# - business_commuter (passenger)
# - disabled_commuter (passenger)
# - rural_resident (passenger)
# - freight_operator (freight)
# - shift_worker (passenger)
# - tourist (passenger)
# - delivery_driver (freight)

# Additional personas from extended section:
# - long_distance_commuter
# - island_resident
# - business_traveler
# - accessibility_user
# - tourist_visitor

COMPATIBLE_USERS_FOR_JOB = {
    
    # ========================================================================
    # FREIGHT & HEAVY GOODS (Professional drivers ONLY)
    # ========================================================================
    
    'freight_delivery_route': ['freight_operator', 'delivery_driver'],
    'long_haul_freight': ['freight_operator'],
    'regional_distribution': ['freight_operator', 'delivery_driver'],
    'manufacturing_supply_chain': ['freight_operator'],
    'port_to_warehouse': ['freight_operator'],
    'waste_collection': ['freight_operator', 'shift_worker'],
    
    # Construction-related freight (professional drivers)
    'construction_materials': ['freight_operator'],
    'hgv_construction_delivery_generated': ['freight_operator'],
    'truck_construction_delivery_generated': ['freight_operator'],
    'van_construction_delivery_generated': ['freight_operator', 'delivery_driver'],
    
    # Retail/warehouse freight (professional drivers)
    'hgv_retail_delivery_generated': ['freight_operator'],
    'truck_retail_delivery_generated': ['freight_operator', 'delivery_driver'],
    'van_retail_delivery_generated': ['freight_operator', 'delivery_driver'],
    
    'hgv_warehouse_transfer_generated': ['freight_operator'],
    'truck_warehouse_transfer_generated': ['freight_operator'],
    'van_warehouse_transfer_generated': ['freight_operator', 'delivery_driver'],
    
    # Specialized freight
    'refrigerated_transport': ['freight_operator'],
    'furniture_delivery': ['freight_operator', 'delivery_driver'],
    'supermarket_supply': ['freight_operator', 'delivery_driver'],
    
    # ========================================================================
    # GIG ECONOMY & URBAN DELIVERY (Flexible workers, students)
    # ========================================================================
    
    'gig_economy_delivery': [
        'delivery_driver', 'budget_student', 'shift_worker', 'eco_warrior'
    ],
    
    'urban_food_delivery': [
        'delivery_driver', 'budget_student', 'shift_worker'
    ],
    
    'urban_parcel_delivery': [
        'delivery_driver', 'budget_student', 'shift_worker'
    ],
    
    # Generated urban deliveries (time-based)
    'urban_delivery_morning_generated': [
        'delivery_driver', 'budget_student', 'shift_worker'
    ],
    
    'urban_delivery_afternoon_generated': [
        'delivery_driver', 'budget_student', 'shift_worker'
    ],
    
    'urban_delivery_night_generated': [
        'delivery_driver', 'shift_worker'  # No students at night
    ],
    
    'last_mile_scooter': [
        'delivery_driver', 'budget_student', 'shift_worker', 'eco_warrior'
    ],
    
    # ========================================================================
    # PERSONAL ERRANDS & SHOPPING (Most personas)
    # ========================================================================
    
    'shopping_trip': [
        'concerned_parent', 'disabled_commuter', 'budget_student',
        'rural_resident', 'eco_warrior', 'shift_worker', 'tourist',
        'business_commuter'  # Off-duty shopping
    ],
    
    # ========================================================================
    # COMMUTE JOBS (Workers & students)
    # ========================================================================
    
    'morning_commute': [
        'business_commuter', 'shift_worker', 'eco_warrior',
        'disabled_commuter', 'budget_student', 'long_distance_commuter',
        'accessibility_user'
    ],
    
    'commute_flexible': [
        'business_commuter', 'eco_warrior', 'disabled_commuter',
        'budget_student', 'shift_worker', 'accessibility_user'
    ],
    
    'multi_modal_commute': [
        'business_commuter', 'eco_warrior', 'budget_student',
        'long_distance_commuter', 'disabled_commuter', 'accessibility_user'
    ],
    
    'intercity_train_commute': [
        'business_commuter', 'long_distance_commuter', 'business_traveler'
    ],
    
    # ========================================================================
    # TOURISM & LEISURE (Tourists + leisure seekers)
    # ========================================================================
    
    'tourist_scenic_rail': [
        'tourist', 'eco_warrior', 'budget_student', 'tourist_visitor'
    ],
    
    'island_ferry_trip': [
        'tourist', 'rural_resident', 'eco_warrior', 'island_resident',
        'tourist_visitor'
    ],
    
    # ========================================================================
    # ACCESSIBILITY-FOCUSED (Disabled users)
    # ========================================================================
    
    'accessible_tram_journey': [
        'disabled_commuter', 'accessibility_user', 'concerned_parent',
        'eco_warrior', 'budget_student', 'business_commuter', 'tourist'
        # Tram is accessible, but primarily for disabled users
    ],
    
    # ========================================================================
    # PROFESSIONAL SERVICES (Business travelers, contractors)
    # ========================================================================
    
    'business_flight': [
        'business_commuter', 'business_traveler'  # ONLY business travelers
    ],
    
    'service_engineer_call': [
        'freight_operator',  # Service engineers may use company vans
        'business_commuter',  # Could be business service calls
        'delivery_driver'     # Gig service calls
    ],
    
    'trades_contractor': [
        # ⚠️ IMPORTANT: This appears to be a JOB (contractor work)
        # NOT a user persona!
        # Professional contractors doing trade work
        'freight_operator',   # Contractors with freight needs
        'business_commuter',  # Small business contractors
        'rural_resident'      # Rural tradespeople
    ],
}


# ============================================================================
# Compatibility Check Function
# ============================================================================

def is_compatible(user_story_id: str, job_story_id: str) -> bool:
    """
    Check if user + job combination makes sense (whitelist-based).
    
    Args:
        user_story_id: User persona (e.g., 'concerned_parent')
        job_story_id: Job/task type (e.g., 'shopping_trip')
    
    Returns:
        True if compatible, False otherwise
    """
    # If job has explicit whitelist, check it
    if job_story_id in COMPATIBLE_USERS_FOR_JOB:
        allowed_users = COMPATIBLE_USERS_FOR_JOB[job_story_id]
        
        if user_story_id in allowed_users:
            return True
        else:
            logger.debug(
                f"❌ Blocked: {user_story_id} + {job_story_id} "
                f"(not in whitelist: {allowed_users})"
            )
            return False
    
    # ⚠️ CRITICAL: If job NOT in whitelist, BLOCK IT (safe default)
    # This prevents nonsensical combinations for unknown job types
    logger.warning(
        f"⚠️ Job '{job_story_id}' has NO WHITELIST - BLOCKING all users! "
        f"(user: {user_story_id})"
    )
    return False


def filter_compatible_combinations(
    user_story_ids: List[str],
    job_story_ids: List[str]
) -> List[Tuple[str, str]]:
    """
    Filter to only compatible user + job combinations.
    
    Args:
        user_story_ids: List of user personas
        job_story_ids: List of job types
    
    Returns:
        List of (user, job) tuples that are compatible
    """
    compatible = []
    
    for user_story in user_story_ids:
        for job_story in job_story_ids:
            if is_compatible(user_story, job_story):
                compatible.append((user_story, job_story))
    
    total_combos = len(user_story_ids) * len(job_story_ids)
    filtered_count = total_combos - len(compatible)
    
    logger.info(
        f"✅ Whitelist filtering: {len(compatible)}/{total_combos} allowed "
        f"({filtered_count} blocked)"
    )
    
    return compatible


def get_missing_whitelists(job_story_ids: List[str]) -> List[str]:
    """
    Identify job types that don't have whitelists.
    
    Args:
        job_story_ids: All job types in the system
    
    Returns:
        List of job IDs missing whitelists
    """
    missing = []
    for job in job_story_ids:
        if job not in COMPATIBLE_USERS_FOR_JOB:
            missing.append(job)
    
    if missing:
        logger.warning(
            f"⚠️ {len(missing)} jobs missing whitelists: {missing}"
        )
    
    return missing


def get_compatible_jobs_for_user(
    user_story_id: str, 
    all_job_ids: List[str]
) -> List[str]:
    """Get all jobs this user can do."""
    return [job for job in all_job_ids if is_compatible(user_story_id, job)]


def get_compatible_users_for_job(job_story_id: str) -> List[str]:
    """Get all users who can do this job."""
    return COMPATIBLE_USERS_FOR_JOB.get(job_story_id, [])


def create_realistic_agent_pool(
    num_agents: int,
    user_story_ids: List[str],
    job_story_ids: List[str]
) -> List[Tuple[str, str]]:
    """
    Create pool of (user, job) pairs for agent generation.
    
    Args:
        num_agents: Number of agents needed
        user_story_ids: Available user personas
        job_story_ids: Available job types
    
    Returns:
        List of (user, job) tuples
    """
    combinations = filter_compatible_combinations(user_story_ids, job_story_ids)
    
    if not combinations:
        logger.error("❌ No compatible combinations - check whitelists!")
        return []
    
    # Distribute evenly across combinations
    agents_per_combo = max(1, num_agents // len(combinations))
    remainder = num_agents % len(combinations)
    
    pool = []
    for i, (user, job) in enumerate(combinations):
        count = agents_per_combo + (1 if i < remainder else 0)
        pool.extend([(user, job)] * count)
    
    logger.info(
        f"✅ Created agent pool: {len(pool)} agents from "
        f"{len(combinations)} compatible combinations"
    )
    
    return pool[:num_agents]  # Trim to exact count