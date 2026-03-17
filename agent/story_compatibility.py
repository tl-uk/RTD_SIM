"""
agent/story_compatibility.py

COMPLETE WHITELIST-BASED compatibility system for RTD_SIM.

Maps all 18 user personas to all 39 job types.

Persona groups:
  Core passenger (8):    eco_warrior, concerned_parent, budget_student,
                         business_commuter, disabled_commuter, rural_resident,
                         shift_worker, tourist
  Freight (2):           freight_operator, delivery_driver
  DFT segments (3):      retired_commuter, frequent_driver, elderly_non_driver
  Multi-modal (5):       long_distance_commuter, island_resident,
                         business_traveler, accessibility_user, tourist_visitor

DESIGN PRINCIPLES:
  - Whitelist approach: define who CAN do each job (safe default = block)
  - A persona appears in a job's whitelist only if the combination is
    behaviourally realistic AND adds simulation value
  - DFT and multi-modal personas are now fully integrated — they were
    previously unreachable due to a YAML nesting bug in personas.yaml
  - Target: 250-320 allowed combinations from 702 possible (18 × 39)

FUNCTION SIGNATURE (no 'strategy' parameter):
  create_realistic_agent_pool(num_agents, user_story_ids, job_story_ids)
"""

from typing import List, Tuple
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# Combination Cache
# ============================================================================
# filter_compatible_combinations() is called up to 4 times per simulation run
# (app startup, sidebar, Phase 5 agent creation, Combination Report tab) with
# the same inputs each time.  Caching the result by frozen input sets reduces
# the call from O(18 × 39) whitelist lookups + 18,000 DEBUG log lines to a
# single dict lookup on every call after the first.
#
# Call clear_compatibility_cache() if the whitelist or available stories
# change at runtime (e.g. after Phase 9 story ingestion).

_FILTER_CACHE: dict = {}


def clear_compatibility_cache() -> None:
    """Invalidate the cached combination filter result.

    Call this after the story library is updated (e.g. Phase 9 ingestion)
    so the next call to filter_compatible_combinations recomputes from scratch.
    """
    _FILTER_CACHE.clear()
    logger.debug("story_compatibility: combination cache cleared")


# ============================================================================
# COMPLETE WHITELIST: User Stories That Can Do Each Job
# ============================================================================
#
# ALL 18 personas:
# Core passenger:  eco_warrior, concerned_parent, budget_student,
#                  business_commuter, disabled_commuter, rural_resident,
#                  shift_worker, tourist
# Freight:         freight_operator, delivery_driver
# DFT:             retired_commuter, frequent_driver, elderly_non_driver
# Multi-modal:     long_distance_commuter, island_resident,
#                  business_traveler, accessibility_user, tourist_visitor

COMPATIBLE_USERS_FOR_JOB = {

    # ========================================================================
    # HEAVY FREIGHT (professional freight drivers only)
    # ========================================================================

    'freight_delivery_route': [
        'freight_operator', 'delivery_driver'
    ],

    'long_haul_freight': [
        'freight_operator'
    ],

    'regional_distribution': [
        'freight_operator', 'delivery_driver'
    ],

    'manufacturing_supply_chain': [
        'freight_operator'
    ],

    'port_to_warehouse': [
        'freight_operator'
    ],

    'electric_hgv_port_delivery': [
        'freight_operator'
    ],

    'ferry_freight_roro': [
        'freight_operator'
    ],

    'refrigerated_transport': [
        'freight_operator'
    ],

    'supermarket_supply': [
        'freight_operator', 'delivery_driver'
    ],

    'furniture_delivery': [
        'freight_operator', 'delivery_driver'
    ],

    'waste_collection': [
        'freight_operator', 'shift_worker'
    ],

    'construction_materials': [
        'freight_operator'
    ],

    # ========================================================================
    # HGV GENERATED JOBS (professional heavy freight only)
    # ========================================================================

    'hgv_construction_delivery_generated': [
        'freight_operator'
    ],

    'hgv_retail_delivery_generated': [
        'freight_operator'
    ],

    'hgv_warehouse_transfer_generated': [
        'freight_operator'
    ],

    'truck_construction_delivery_generated': [
        'freight_operator'
    ],

    'truck_retail_delivery_generated': [
        'freight_operator', 'delivery_driver'
    ],

    'truck_warehouse_transfer_generated': [
        'freight_operator'
    ],

    'van_construction_delivery_generated': [
        'freight_operator', 'delivery_driver'
    ],

    'van_retail_delivery_generated': [
        'freight_operator', 'delivery_driver'
    ],

    'van_warehouse_transfer_generated': [
        'freight_operator', 'delivery_driver'
    ],

    # ========================================================================
    # GIG ECONOMY & URBAN DELIVERY (flexible workers)
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

    'last_mile_scooter': [
        'delivery_driver', 'budget_student', 'shift_worker', 'eco_warrior'
    ],

    'urban_delivery_morning_generated': [
        'delivery_driver', 'budget_student', 'shift_worker'
    ],

    'urban_delivery_afternoon_generated': [
        'delivery_driver', 'budget_student', 'shift_worker'
    ],

    'urban_delivery_night_generated': [
        'delivery_driver', 'shift_worker'  # No students at night
    ],

    # ========================================================================
    # COMMUTE JOBS
    # ========================================================================

    'morning_commute': [
        'business_commuter', 'shift_worker', 'eco_warrior',
        'disabled_commuter', 'budget_student', 'long_distance_commuter',
        'accessibility_user', 'frequent_driver',
        'concerned_parent',         # school run IS a morning commute
    ],

    'commute_flexible': [
        'business_commuter', 'eco_warrior', 'disabled_commuter',
        'budget_student', 'shift_worker', 'accessibility_user',
        'long_distance_commuter', 'frequent_driver',
        'concerned_parent',         # flexible school pickup/drop-off trips
    ],

    'multi_modal_commute': [
        'business_commuter', 'eco_warrior', 'budget_student',
        'long_distance_commuter', 'disabled_commuter', 'accessibility_user',
        'shift_worker', 'business_traveler',  # multi-leg business travel
    ],

    'intercity_train_commute': [
        'business_commuter', 'long_distance_commuter', 'business_traveler',
        'eco_warrior', 'budget_student',
        'retired_commuter',         # leisure intercity rail trips
    ],

    # ========================================================================
    # SHOPPING & ERRANDS (broad access — most non-freight personas)
    # ========================================================================

    'shopping_trip': [
        'concerned_parent', 'disabled_commuter', 'budget_student',
        'rural_resident', 'eco_warrior', 'shift_worker', 'tourist',
        'business_commuter', 'retired_commuter', 'frequent_driver',
        'elderly_non_driver', 'long_distance_commuter', 'island_resident',
        'accessibility_user', 'tourist_visitor',
        'business_traveler',        # business travelers shop too
    ],

    # ========================================================================
    # TOURISM & LEISURE
    # ========================================================================

    'tourist_scenic_rail': [
        'tourist', 'eco_warrior', 'budget_student',
        'tourist_visitor', 'retired_commuter', 'long_distance_commuter',
        'concerned_parent',         # family day trips on scenic rail
        'island_resident',          # mainland day trips via rail
    ],

    'island_ferry_trip': [
        'tourist', 'rural_resident', 'eco_warrior', 'island_resident',
        'tourist_visitor', 'retired_commuter', 'elderly_non_driver',
        'concerned_parent', 'long_distance_commuter',
        'business_traveler',        # some island business destinations
    ],

    # ========================================================================
    # ACCESSIBILITY-FOCUSED
    # ========================================================================

    'accessible_tram_journey': [
        'disabled_commuter', 'accessibility_user', 'concerned_parent',
        'eco_warrior', 'budget_student', 'business_commuter', 'tourist',
        'retired_commuter', 'elderly_non_driver', 'tourist_visitor',
        'business_traveler',        # in-city tram use at meeting destinations
        'long_distance_commuter',   # city-end of intercity journey
    ],

    # ========================================================================
    # PROFESSIONAL SERVICES & BUSINESS TRAVEL
    # ========================================================================

    'business_flight': [
        'business_commuter', 'business_traveler'
    ],

    'service_engineer_call': [
        'freight_operator', 'business_commuter', 'delivery_driver',
        'rural_resident', 'frequent_driver'
    ],

    'trades_contractor': [
        'freight_operator', 'business_commuter', 'rural_resident',
        'frequent_driver', 'delivery_driver',
        'island_resident',          # island tradespeople doing contract work
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

    # Safe default: block unknown jobs
    logger.warning(
        f"⚠️ Job '{job_story_id}' has NO WHITELIST — blocking all users. "
        f"(user: {user_story_id})"
    )
    return False


def filter_compatible_combinations(
    user_story_ids: List[str],
    job_story_ids: List[str]
) -> List[Tuple[str, str]]:
    """
    Filter to only compatible user + job combinations.

    Results are cached by input set so that repeated calls (UI tab renders,
    agent creation phases) with the same persona/job lists pay the O(N×M)
    whitelist cost only once per simulation run.

    Args:
        user_story_ids: List of user personas
        job_story_ids:  List of job types

    Returns:
        List of (user, job) tuples that are compatible
    """
    cache_key = (frozenset(user_story_ids), frozenset(job_story_ids))

    if cache_key in _FILTER_CACHE:
        cached = _FILTER_CACHE[cache_key]
        total_combos = len(user_story_ids) * len(job_story_ids)
        logger.info(
            "✅ Whitelist filtering: %d/%d allowed (cached — 0 new evaluations)",
            len(cached), total_combos,
        )
        return list(cached)   # return a copy so callers can mutate freely

    compatible = []
    for user_story in user_story_ids:
        for job_story in job_story_ids:
            if is_compatible(user_story, job_story):
                compatible.append((user_story, job_story))

    total_combos = len(user_story_ids) * len(job_story_ids)
    filtered_count = total_combos - len(compatible)

    logger.info(
        "✅ Whitelist filtering: %d/%d allowed (%d blocked)",
        len(compatible), total_combos, filtered_count,
    )

    _FILTER_CACHE[cache_key] = compatible
    return list(compatible)


def get_missing_whitelists(job_story_ids: List[str]) -> List[str]:
    """Identify job types that don't have whitelists."""
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

    NOTE: No 'strategy' parameter — this was removed in Phase 7.2.

    Args:
        num_agents: Number of agents needed
        user_story_ids: Available user personas
        job_story_ids: Available job types

    Returns:
        List of (user, job) tuples, length == num_agents
    """
    combinations = filter_compatible_combinations(user_story_ids, job_story_ids)

    if not combinations:
        logger.error("❌ No compatible combinations — check whitelists!")
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

    return pool[:num_agents]