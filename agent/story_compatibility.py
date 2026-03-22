"""
agent/story_compatibility.py

COMPLETE WHITELIST-BASED compatibility system for RTD_SIM.

Maps all 24 user personas to all 55 job types.

Persona groups:
  Core passenger (9):    eco_warrior, concerned_parent, budget_student,
                         business_commuter, disabled_commuter, rural_resident,
                         shift_worker, tourist, delivery_driver
  Freight (1):           freight_operator
  DFT segments (3):      retired_commuter, frequent_driver, elderly_non_driver
  Multi-modal (5):       long_distance_commuter, island_resident,
                         business_traveler, accessibility_user, tourist_visitor
  Operator (6):          fleet_manager_logistics, fleet_manager_healthcare,
                         fleet_manager_retail, port_terminal_operator,
                         rail_freight_operator, air_freight_operator

Job sources (55 total):
  transit_passenger.yaml  (8)   heavy_freight.yaml   (6)   medium_freight.yaml (5)
  passenger_special.yaml  (5)   light_commercial.yaml (3)   micro_delivery.yaml (3)
  multimodal.yaml         (2)   fleet_operators.yaml  (7)   rail_operations.yaml (5)
  port_operations.yaml    (9)   aviation.yaml         (4)

DESIGN PRINCIPLES:
  - Whitelist approach: define who CAN do each job (safe default = block)
  - A persona appears in a job's whitelist only if the combination is
    behaviourally realistic AND adds simulation value
  - Operator personas (fleet_manager_*, port_terminal_operator,
    rail_freight_operator, air_freight_operator) are loaded from
    agent/personas/operator_personas.yaml by UserStoryParser.

PHASE 10b STUBS:
  The 12 *_generated job IDs below exist in the whitelist but have NO
  YAML definitions yet. They are generated programmatically by job_stories.py
  at runtime. If they appear in config.job_stories before their YAML stubs
  are created, JobStoryParser will raise KeyError.
  DO NOT add them to config.job_stories until their YAML stubs exist.

FUNCTION SIGNATURE (no 'strategy' parameter — removed Phase 7.2):
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
# the same inputs each time. Caching the result by frozen input sets reduces
# the call from O(24 × 55) whitelist lookups + many DEBUG log lines to a
# single dict lookup on every call after the first.
#
# Call clear_compatibility_cache() if the whitelist or available stories
# change at runtime (e.g. after Phase 9 story ingestion or hot-reload).

_FILTER_CACHE: dict = {}


def clear_compatibility_cache() -> None:
    """Invalidate the cached combination filter result.

    Call this after the story library is updated (e.g. Phase 9 ingestion
    or StoryLibraryLoader.apply_to_simulation()) so the next call to
    filter_compatible_combinations recomputes from scratch.
    """
    _FILTER_CACHE.clear()
    logger.debug("story_compatibility: combination cache cleared")


# ============================================================================
# COMPLETE WHITELIST: User Stories That Can Do Each Job
# ============================================================================
#
# ALL 24 personas:
# Core passenger:  eco_warrior, concerned_parent, budget_student,
#                  business_commuter, disabled_commuter, rural_resident,
#                  shift_worker, tourist, delivery_driver
# Freight:         freight_operator
# DFT:             retired_commuter, frequent_driver, elderly_non_driver
# Multi-modal:     long_distance_commuter, island_resident,
#                  business_traveler, accessibility_user, tourist_visitor
# Operator:        fleet_manager_logistics, fleet_manager_healthcare,
#                  fleet_manager_retail, port_terminal_operator,
#                  rail_freight_operator, air_freight_operator

COMPATIBLE_USERS_FOR_JOB = {

    # ========================================================================
    # HEAVY FREIGHT — heavy_freight.yaml
    # Professional freight operators only.
    # ========================================================================

    'long_haul_freight': [
        'freight_operator',
        'rail_freight_operator',          # operator-level planning perspective
    ],

    'port_to_warehouse': [
        'freight_operator',
        'port_terminal_operator',
    ],

    'supermarket_supply': [
        'freight_operator',
        'delivery_driver',
        'fleet_manager_retail',
    ],

    'manufacturing_supply_chain': [
        'freight_operator',
        'rail_freight_operator',
    ],

    'electric_hgv_port_delivery': [
        'freight_operator',
        'port_terminal_operator',
    ],

    'ferry_freight_roro': [
        'freight_operator',
        'port_terminal_operator',
    ],

    # ========================================================================
    # MEDIUM FREIGHT — medium_freight.yaml
    # ========================================================================

    'regional_distribution': [
        'freight_operator',
        'delivery_driver',
        'fleet_manager_logistics',
    ],

    'furniture_delivery': [
        'freight_operator',
        'delivery_driver',
    ],

    'construction_materials': [
        'freight_operator',
    ],

    'refrigerated_transport': [
        'freight_operator',
        'fleet_manager_retail',
    ],

    'waste_collection': [
        'freight_operator',
        'shift_worker',
    ],

    # ========================================================================
    # LIGHT COMMERCIAL — light_commercial.yaml
    # ========================================================================

    'service_engineer_call': [
        'freight_operator',
        'business_commuter',
        'delivery_driver',
        'rural_resident',
        'frequent_driver',
    ],

    'trades_contractor': [
        'freight_operator',
        'business_commuter',
        'rural_resident',
        'frequent_driver',
        'delivery_driver',
        'island_resident',          # island tradespeople doing contract work
    ],

    'freight_delivery_route': [
        'freight_operator',
        'delivery_driver',
        'fleet_manager_logistics',
    ],

    # ========================================================================
    # MICRO DELIVERY — micro_delivery.yaml
    # Gig and urban delivery workers; some students for food delivery gigs.
    # ========================================================================

    'urban_food_delivery': [
        'delivery_driver',
        'budget_student',
        'shift_worker',
    ],

    'urban_parcel_delivery': [
        'delivery_driver',
        'budget_student',
        'shift_worker',
        'fleet_manager_logistics',
    ],

    'gig_economy_delivery': [
        'delivery_driver',
        'budget_student',
        'shift_worker',
        'eco_warrior',              # e-cargo-bike gig work appeals to eco types
    ],

    # ========================================================================
    # PHASE 10b STUBS — *_generated jobs (NO YAML YET)
    # These are programmatically generated by job_stories.py at runtime.
    # DO NOT add to config.job_stories until YAML stubs exist.
    # ========================================================================

    'hgv_construction_delivery_generated': [
        'freight_operator',
    ],

    'hgv_retail_delivery_generated': [
        'freight_operator',
    ],

    'hgv_warehouse_transfer_generated': [
        'freight_operator',
    ],

    'truck_construction_delivery_generated': [
        'freight_operator',
    ],

    'truck_retail_delivery_generated': [
        'freight_operator',
        'delivery_driver',
    ],

    'truck_warehouse_transfer_generated': [
        'freight_operator',
    ],

    'van_construction_delivery_generated': [
        'freight_operator',
        'delivery_driver',
    ],

    'van_retail_delivery_generated': [
        'freight_operator',
        'delivery_driver',
    ],

    'van_warehouse_transfer_generated': [
        'freight_operator',
        'delivery_driver',
    ],

    'urban_delivery_morning_generated': [
        'delivery_driver',
        'budget_student',
        'shift_worker',
    ],

    'urban_delivery_afternoon_generated': [
        'delivery_driver',
        'budget_student',
        'shift_worker',
    ],

    'urban_delivery_night_generated': [
        'delivery_driver',
        'shift_worker',             # No students at night
    ],

    # ========================================================================
    # COMMUTE JOBS — transit_passenger.yaml
    # ========================================================================

    'morning_commute': [
        'business_commuter',
        'shift_worker',
        'eco_warrior',
        'disabled_commuter',
        'budget_student',
        'long_distance_commuter',
        'accessibility_user',
        'frequent_driver',
        'concerned_parent',         # school run IS a morning commute
    ],

    'commute_flexible': [
        'business_commuter',
        'eco_warrior',
        'disabled_commuter',
        'budget_student',
        'shift_worker',
        'accessibility_user',
        'long_distance_commuter',
        'frequent_driver',
        'concerned_parent',         # flexible school pickup/drop-off trips
    ],

    'multi_modal_commute': [
        'business_commuter',
        'eco_warrior',
        'budget_student',
        'long_distance_commuter',
        'disabled_commuter',
        'accessibility_user',
        'shift_worker',
        'business_traveler',        # multi-leg business travel
    ],

    'intercity_train_commute': [
        'business_commuter',
        'long_distance_commuter',
        'business_traveler',
        'eco_warrior',
        'budget_student',
        'retired_commuter',         # leisure intercity rail trips
        'rail_freight_operator',    # operators understand intercity rail context
    ],

    # ========================================================================
    # SHOPPING & ERRANDS — transit_passenger.yaml
    # Broad access — most non-freight personas.
    # ========================================================================

    'shopping_trip': [
        'concerned_parent',
        'disabled_commuter',
        'budget_student',
        'rural_resident',
        'eco_warrior',
        'shift_worker',
        'tourist',
        'business_commuter',
        'retired_commuter',
        'frequent_driver',
        'elderly_non_driver',
        'long_distance_commuter',
        'island_resident',
        'accessibility_user',
        'tourist_visitor',
        'business_traveler',        # business travelers shop too
    ],

    # ========================================================================
    # TRANSIT-SPECIFIC PASSENGER JOURNEYS — transit_passenger.yaml
    # ========================================================================

    'accessible_tram_journey': [
        'disabled_commuter',
        'accessibility_user',
        'concerned_parent',
        'eco_warrior',
        'budget_student',
        'business_commuter',
        'tourist',
        'retired_commuter',
        'elderly_non_driver',
        'tourist_visitor',
        'business_traveler',        # in-city tram use at meeting destinations
        'long_distance_commuter',   # city-end of intercity journey
    ],

    'tourist_scenic_rail': [
        'tourist',
        'eco_warrior',
        'budget_student',
        'tourist_visitor',
        'retired_commuter',
        'long_distance_commuter',
        'concerned_parent',         # family day trips on scenic rail
        'island_resident',          # mainland day trips via rail
    ],

    'island_ferry_trip': [
        'tourist',
        'rural_resident',
        'eco_warrior',
        'island_resident',
        'tourist_visitor',
        'retired_commuter',
        'elderly_non_driver',
        'concerned_parent',
        'long_distance_commuter',
        'business_traveler',        # some island business destinations
    ],

    # ========================================================================
    # MULTIMODAL — multimodal.yaml
    # ========================================================================

    'business_flight': [
        'business_commuter',
        'business_traveler',
        'air_freight_operator',     # air freight operators understand air travel
    ],

    'last_mile_scooter': [
        'delivery_driver',
        'budget_student',
        'shift_worker',
        'eco_warrior',
        'business_commuter',        # station-to-office last mile
    ],

    # ========================================================================
    # PASSENGER SPECIAL — passenger_special.yaml
    # NOTE: story_combinations.yaml v4.0.0 incorrectly stated these jobs
    # do not exist. They are defined in passenger_special.yaml and are
    # active below. story_combinations.yaml changelog must be corrected.
    # ========================================================================

    'school_run_then_work': [
        'concerned_parent',
        'frequent_driver',
        'eco_warrior',              # parents who want sustainable school runs
        'shift_worker',             # parents on unusual schedules
    ],

    'flexible_leisure': [
        'eco_warrior',
        'budget_student',
        'tourist',
        'tourist_visitor',
        'retired_commuter',
        'elderly_non_driver',
        'long_distance_commuter',
        'island_resident',
        'concerned_parent',
        'disabled_commuter',
        'accessibility_user',
        'shift_worker',             # leisure on days off
        'frequent_driver',
    ],

    'airport_transfer': [
        'business_commuter',
        'business_traveler',
        'frequent_driver',
        'long_distance_commuter',
        'tourist',
        'tourist_visitor',
        'rural_resident',           # rural travellers must drive to airport
        'air_freight_operator',     # ground leg of air cargo operations
    ],

    'tourist_exploration': [
        'tourist',
        'tourist_visitor',
        'eco_warrior',
        'budget_student',
        'retired_commuter',
        'long_distance_commuter',
        'island_resident',          # day trips on mainland
    ],

    'night_shift': [
        'shift_worker',
        'delivery_driver',          # gig workers on late shifts
        'freight_operator',         # overnight freight drivers
        'fleet_manager_logistics',  # logistics managers monitoring night runs
        'fleet_manager_healthcare', # NHS transport managers on call
    ],

    # ========================================================================
    # FLEET OPERATOR JOBS — fleet_operators.yaml
    # These jobs model institutional fleet decisions, not individual trips.
    # Primarily for operator personas; freight_operator included as proxy
    # until FreightOperatorAgent is implemented (Phase 10b).
    # ========================================================================

    'logistics_hub_to_hub': [
        'freight_operator',
        'fleet_manager_logistics',
        'rail_freight_operator',    # rail alternative for trunk haul
    ],

    'logistics_last_mile_urban': [
        'delivery_driver',
        'fleet_manager_logistics',
        'budget_student',           # gig last-mile workers
        'shift_worker',
    ],

    'retail_dc_to_store': [
        'freight_operator',
        'fleet_manager_retail',
    ],

    'retail_store_collection': [
        'freight_operator',
        'fleet_manager_retail',
    ],

    'nhs_patient_transport': [
        'fleet_manager_healthcare',
        'shift_worker',             # PTS drivers are shift workers
        'paramedic',                # paramedics do planned transport between blue-light calls
        'nhs_supply_chain',         # contracted PTS uses logistics company fleet
        'freight_operator',         # contracted patient transport
    ],

    'nhs_staff_commute': [
        'shift_worker',             # NHS staff commuting on shift patterns
        'fleet_manager_healthcare',
        'disabled_commuter',        # NHS staff with accessibility needs
        'frequent_driver',          # staff who drive to hospital sites
        'nhs_ward_manager',         # ward managers on shift commute
        'community_health_worker',  # community nurses commuting to health centre base
    ],

    'nhs_clinical_supplies': [
        'freight_operator',
        'fleet_manager_healthcare',
        'fleet_manager_logistics',  # NHS Supply Chain uses same DC infrastructure as commercial logistics
        'delivery_driver',          # contracted clinical supply delivery
        'nhs_supply_chain',         # dedicated NHS supply chain operator persona
    ],

    # ── BRIDGING: night_shift cross-cluster fix ────────────────────────────
    # shift_worker already in night_shift; add logistics persona that does
    # overnight hub-to-hub runs — creates logistics ↔ healthcare bridge via
    # shared infrastructure at hospital-adjacent distribution centres.
    # (night_shift entry is in the NIGHT_OPS section above — adding here only
    #  ensures the NHS operator types are also in scope)

    # ========================================================================
    # NHS OPERATIONS — nhs_operations.yaml
    # New jobs creating cross-cluster bridges
    # ========================================================================

    'ambulance_emergency_response': [
        'paramedic',
        'shift_worker',             # paramedic-grade shift workers
        'fleet_manager_healthcare', # ambulance trust fleet management
    ],

    'community_nursing_rounds': [
        'community_health_worker',
        'shift_worker',             # district nurses on early/late shift
        'nhs_ward_manager',         # ward managers covering community outreach
    ],

    'nhs_supply_chain_delivery': [
        'nhs_supply_chain',
        'freight_operator',         # contracted NHS Supply Chain logistics
        'fleet_manager_healthcare',
        'fleet_manager_logistics',  # NHS Supply Chain shares DC with commercial logistics
        'delivery_driver',          # contracted delivery on NHS routes
    ],

    'clinical_waste_collection': [
        'clinical_waste_driver',
        'shift_worker',             # clinical waste runs overlap with waste_collection job
        'freight_operator',         # Veolia, SRCL, Stericycle are commercial operators
    ],

    'gp_surgery_supply_run': [
        'nhs_supply_chain',
        'delivery_driver',          # GP supply uses same last-mile infrastructure
        'fleet_manager_healthcare',
        'fleet_manager_logistics',  # NHS Supply Chain logistics
    ],

    # ========================================================================
    # RAIL OPERATIONS — rail_operations.yaml
    # ========================================================================

    'rail_freight_intermodal': [
        'freight_operator',
        'rail_freight_operator',
    ],

    'rail_freight_bulk': [
        'freight_operator',
        'rail_freight_operator',
    ],

    'rail_freight_terminal_drayage': [
        'freight_operator',
        'delivery_driver',
        'rail_freight_operator',
    ],

    'commuter_rail_journey': [
        'business_commuter',
        'long_distance_commuter',
        'eco_warrior',
        'budget_student',
        'shift_worker',
        'retired_commuter',
        'accessibility_user',
        'disabled_commuter',
        'frequent_driver',          # occasional rail users
    ],

    'rail_multimodal_transfer': [
        'business_commuter',
        'long_distance_commuter',
        'tourist',
        'tourist_visitor',
        'eco_warrior',
        'budget_student',
        'accessibility_user',
        'disabled_commuter',
    ],

    # ========================================================================
    # PORT OPERATIONS — port_operations.yaml
    # ========================================================================

    'container_terminal_drayage': [
        'freight_operator',
        'port_terminal_operator',
    ],

    'dover_roro_outbound': [
        'freight_operator',
        'port_terminal_operator',
    ],

    'rosyth_roro_freight': [
        'freight_operator',
        'port_terminal_operator',
    ],

    'bulk_port_outbound': [
        'freight_operator',
        'port_terminal_operator',
    ],

    'offshore_energy_port': [
        'freight_operator',
        'port_terminal_operator',
        'shift_worker',             # offshore crew transfer workers
    ],

    'cruise_passenger_turnaround': [
        'tourist',
        'tourist_visitor',
        'retired_commuter',
        'elderly_non_driver',
        'business_traveler',
        'long_distance_commuter',
        'port_terminal_operator',   # operator managing turnaround logistics
    ],

    'port_of_london_barge_transfer': [
        'freight_operator',
        'port_terminal_operator',
        'eco_warrior',              # barge modal shift aligns with eco values
    ],

    # ========================================================================
    # AVIATION — aviation.yaml
    # ========================================================================

    'domestic_air_travel': [
        'business_traveler',
        'business_commuter',
        'frequent_driver',          # car-centric travellers who fly short-haul
        'air_freight_operator',     # operators understand air travel context
    ],

    'island_lifeline_air': [
        'island_resident',
        'tourist_visitor',
        'rural_resident',
        'tourist',
        'retired_commuter',
        'air_freight_operator',     # lifeline service planning context
    ],

    'airport_ground_transfer': [
        'business_traveler',
        'business_commuter',
        'tourist',
        'tourist_visitor',
        'frequent_driver',
        'long_distance_commuter',
        'eco_warrior',              # sustainable airport ground transfer choices
        'budget_student',           # cost-conscious airport access
        'air_freight_operator',
    ],

    'air_cargo_express': [
        'freight_operator',
        'air_freight_operator',
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
                f"(not in whitelist)"
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