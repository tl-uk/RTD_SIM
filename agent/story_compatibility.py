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

from agent.user_stories import UserStoryParser
from agent.job_stories import JobStoryParser

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
# DYNAMIC HEURISTIC RESOLVER
# ============================================================================

def _auto_resolve_compatibility(user_id: str, job_id: str) -> bool:
    """
    Ontology-driven dynamic resolver. 
    Refined to handle rail operations, implicit healthcare, and cross-domain commuting.
    """
    try:
        from agent.user_stories import UserStoryParser
        from agent.job_stories import JobStoryParser
        
        user = UserStoryParser().load_from_yaml(user_id)
        job = JobStoryParser().load_from_yaml(job_id)
        
        p_type = getattr(user, 'persona_type', 'passenger').lower()
        j_type = getattr(job, 'job_type', 'general').lower()
        params = getattr(job, 'parameters', {})
        operator_type = params.get('operator_type', '').lower()
        
        # ====================================================================
        # 1. Healthcare & Medical Transport Ontology
        # ====================================================================
        hc_keywords = ['nhs', 'clinical', 'patient', 'ambulance', 'nursing', 'gp_', 'surgery', 'health', 'ward']
        if operator_type == 'healthcare' or any(kw in job_id for kw in hc_keywords):
            healthcare_core = [
                'fleet_manager_healthcare', 'paramedic', 'community_health_worker', 
                'nhs_ward_manager', 'clinical_waste_driver', 'nhs_supply_chain'
            ]
            if user_id in healthcare_core: return True
            
            # Allow shift workers and delivery drivers for gig/contracted health logistics
            if user_id in ['shift_worker', 'delivery_driver'] and j_type in ['passenger_commute', 'service', 'delivery']: return True
            if p_type == 'freight' and any(kw in job_id for kw in ['supply', 'waste']): return True
            
            # Allow specific passenger types to commute to NHS jobs
            if user_id in ['disabled_commuter', 'frequent_driver'] and 'commute' in job_id: return True
            return False

        # ====================================================================
        # 2. Heavy Freight, Port, Rail, & Aviation Ontology
        # ====================================================================
        if j_type in ['freight', 'multimodal_freight', 'rail_freight'] or operator_type in ['logistics', 'retail']:
            heavy_freight_personas = [
                'freight_operator', 'rail_freight_operator', 'port_terminal_operator', 
                'air_freight_operator', 'fleet_manager_logistics', 'fleet_manager_retail'
            ]
            if user_id in heavy_freight_personas: return True
            if user_id == 'delivery_driver' and 'heavy' not in params.get('vehicle_type', ''): return True
            
            # Specific exception: Eco-warriors support barge/river transfers
            if user_id == 'eco_warrior' and 'barge' in job_id: return True
            # Specific exception: Shift workers staff offshore energy ports
            if user_id == 'shift_worker' and 'offshore' in job_id: return True
            return False

        # ====================================================================
        # 3. Urban Delivery & Gig Economy Ontology
        # ====================================================================
        if j_type in ['delivery', 'gig_delivery'] or 'last_mile' in job_id:
            if 'passenger' in j_type or 'scooter' in job_id:
                return p_type == 'passenger' and user_id != 'elderly_non_driver'

            delivery_personas = [
                'delivery_driver', 'fleet_manager_logistics', 'budget_student', 
                'shift_worker', 'eco_warrior', 'freight_operator'
            ]
            return user_id in delivery_personas

        # ====================================================================
        # 4. Mobility of Care & Transit Ontology (Cruises/Ferries)
        # ====================================================================
        if job_id in ['school_run_then_work', 'shopping_trip'] or 'cruise' in job_id or 'island_ferry' in job_id:
            # Freight operators don't do personal errands/cruises in work vehicles
            if p_type == 'freight' and 'operator' not in user_id: return False
            if user_id == 'port_terminal_operator' and 'cruise' in job_id: return True
            return p_type == 'passenger'

        # ====================================================================
        # 5. General Passenger Transit & Commuting Ontology
        # ====================================================================
        if j_type in ['passenger_commute', 'passenger_errand', 'passenger_transit',
                      'passenger_leisure', 'business_travel', 'passenger_special']:
            
            # Allow freight operators to commute (e.g., night_shift), but block
            # them from leisure/tourism/scenic jobs
            if p_type == 'freight':
                return j_type in ('passenger_commute',)
                
            if j_type == 'business_travel':
                return user_id in ['business_commuter', 'business_traveler',
                                   'air_freight_operator']

            # Tourist-specific jobs: only tourist personas and multi-modal
            # travellers; block pure commuter personas from scenic-rail etc.
            if j_type == 'passenger_special' or any(
                kw in job_id for kw in ('scenic', 'tourist_', 'exploration', 'cruise')
            ):
                tourist_personas = [
                    'tourist', 'tourist_visitor', 'long_distance_commuter',
                    'business_traveler', 'eco_warrior', 'retired_commuter',
                    'elderly_non_driver', 'accessibility_user',
                ]
                return user_id in tourist_personas

            # Rail-operations passenger jobs (commuter_rail_journey,
            # intercity_train_commute, multi_modal_commute, rail_multimodal_transfer)
            # — accessible to any non-freight commuter/traveller persona
            if any(kw in job_id for kw in ('rail', 'train', 'commuter_rail',
                                            'intercity_train', 'multi_modal')):
                blocked = ['elderly_non_driver', 'shift_worker']
                return p_type == 'passenger' and user_id not in blocked

            return True

        # ====================================================================
        # 6. Service & Trades Ontology
        # ====================================================================
        # if j_type == 'service':
        #     trades_personas = [
        #         'freight_operator', 'frequent_driver', 'rural_resident', 
        #         'business_commuter', 'delivery_driver', 'island_resident',
        #         'shift_worker'
        #     ]
        #     return user_id in trades_personas

        # return False

        # ====================================================================
        # 6. Service & Trades Ontology (UPDATED)
        # ====================================================================
        if j_type == 'service':
            # NEW: Cleaned up trade personas
            trades_personas = [
                'island_tradesperson', 'rural_technician', 
                'specialist_engineer', 'emergency_trade_worker',
                'freight_operator', 'delivery_driver'
            ]
            return user_id in trades_personas

        # ====================================================================
        # 7. Taxi & Private Hire Ontology (NEW)
        # ====================================================================
        if j_type == 'taxi_service' or operator_type == 'taxi':
            taxi_personas = [
                'taxi_driver', 'ride_hail_driver', 'fleet_manager_taxi'
            ]
            return user_id in taxi_personas
        
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(f"Ontology resolver failed for {user_id}_{job_id}: {e}")
        return False

# ============================================================================
# UPDATED COMPATIBILITY CHECK
# ============================================================================

def is_compatible(user_story_id: str, job_story_id: str) -> bool:
    """
    Check if user + job combination makes sense.
    Checks the hardcoded dictionary first, then falls back to the Auto-Resolver.
    """
    # 1. Check Explicit Hardcoded Whitelist (Overrides)
    if job_story_id in COMPATIBLE_USERS_FOR_JOB:
        if user_story_id in COMPATIBLE_USERS_FOR_JOB[job_story_id]:
            return True
            
    # 2. Check Dynamic Auto-Resolver (The Magic Bullet)
    # This automatically approves generated templates (like urban_delivery_night_generated)
    is_valid = _auto_resolve_compatibility(user_story_id, job_story_id)
    
    if is_valid:
        return True

    logger.debug(f"❌ Blocked by Heuristics: {user_story_id} cannot perform {job_story_id}")
    return False

def filter_compatible_combinations(
    user_story_ids: List[str],
    job_story_ids: List[str]
) -> List[Tuple[str, str]]:
    """
    Filter to only compatible user + job combinations.
    """
    cache_key = (frozenset(user_story_ids), frozenset(job_story_ids))

    if cache_key in _FILTER_CACHE:
        return list(_FILTER_CACHE[cache_key])

    compatible = []
    
    # Pre-load parsers to cache all YAMLs in memory before the big loop
    # This makes the auto-resolver lightning fast.
    UserStoryParser().list_available_stories()
    JobStoryParser().list_available_stories()
    
    for user_story in user_story_ids:
        for job_story in job_story_ids:
            if is_compatible(user_story, job_story):
                compatible.append((user_story, job_story))

    total_combos = len(user_story_ids) * len(job_story_ids)
    
    logger.info(
        f"✅ Auto-Heuristic Filtering: {len(compatible)}/{total_combos} allowed "
        f"({total_combos - len(compatible)} safely blocked)"
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

    Phase 10a fix: the previous implementation assigned agents in strict
    iteration order (alphabetical by user then job). With 293 combinations
    and 150 agents, floor(150/293)=0 so only the first 150 combinations
    received one agent each — producing eco_warrior-dominated runs because
    eco_warrior sorts before freight_operator alphabetically.

    Fixed approach:
      1. Shuffle combinations so alphabetical bias is eliminated.
      2. Distribute using round-robin over the shuffled list so every
         combination gets at least one agent if num_agents >= len(combinations).
      3. If num_agents < len(combinations), sample without replacement so
         all persona/job types have an equal chance of appearing.

    Args:
        num_agents: Number of agents needed
        user_story_ids: Available user personas
        job_story_ids: Available job types

    Returns:
        List of (user, job) tuples, length == num_agents
    """
    import random as _random

    combinations = filter_compatible_combinations(user_story_ids, job_story_ids)

    if not combinations:
        logger.error("❌ No compatible combinations — check whitelists!")
        return []

    # Shuffle once with a stable seed derived from num_agents so repeated
    # calls with the same inputs are reproducible but not alphabetical.
    rng = _random.Random(num_agents ^ len(combinations))
    shuffled = list(combinations)
    rng.shuffle(shuffled)

    if num_agents <= len(shuffled):
        # Fewer agents than combinations: sample without replacement so every
        # agent gets a unique combination (no persona dominance from repetition).
        pool = shuffled[:num_agents]
    else:
        # More agents than combinations: round-robin fill so every combination
        # is represented at least floor(num_agents/len) times before any gets
        # an extra agent.  This is bias-free and predictable.
        repeats, remainder = divmod(num_agents, len(shuffled))
        pool = shuffled * repeats + shuffled[:remainder]

    logger.info(
        "✅ Created agent pool: %d agents from %d compatible combinations "
        "(%.1f agents/combo avg)",
        len(pool), len(combinations), len(pool) / max(len(combinations), 1),
    )

    return pool