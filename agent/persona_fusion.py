"""
agent/persona_fusion.py

Generative synthesis step that fuses a UserStory (WHO) with a JobStory (WHAT)
into a FusedIdentity (COMBINED BEHAVIOURAL PROFILE).

This is the missing link between the two YAML sources and the BDI planner.

─────────────────────────────────────────────────────────────────────────────
WHAT IT SOLVES
─────────────────────────────────────────────────────────────────────────────
Before this module:
  UserStory → persona (desires, beliefs from personas.yaml)
  JobStory  → task context (modes, time window from job_contexts/)
  StoryDrivenAgent loads both independently.
  BDIPlanner sees only vehicle_type + vehicle_required flags.
  ⇒ rail/ferry/air agents route on the OSMnx drive graph
  ⇒ no automatic BDI beliefs/desires/intentions
  ⇒ no ASI tier, no EV viability threshold

After this module:
  PersonaFusion.fuse(user_story, job_story) → FusedIdentity
  FusedIdentity contains:
    • desires       – merged + weighted from both stories
    • beliefs       – calibrated to the combination
    • intentions    – job-derived action commitments
    • allowed_modes – hard-constrained by (persona, job, network_type)
    • network_type  – primary physical network of this agent
    • asi_tier      – 'avoid' | 'shift' | 'improve'
    • ev_viability_threshold – Complex Contagion gate
    • llm_narrative – optional OLMo 2 synthesis (async)
  BDIPlanner uses FusedIdentity instead of raw flags.

─────────────────────────────────────────────────────────────────────────────
PIPELINE POSITION
─────────────────────────────────────────────────────────────────────────────
  story_compatibility.filter_compatible_combinations()
      ↓
  PersonaFusion.fuse(user_story, job_story)   ← THIS MODULE
      ↓
  StoryDrivenAgent.__init__(fused_identity)
      ↓
  BDIPlanner.__init__(fused_identity=fused_identity)
      ↓
  BDIPlanner.actions_for() → uses fused_identity.allowed_modes
  BDIPlanner._get_route()  → uses modes.is_routeable()

─────────────────────────────────────────────────────────────────────────────
WIRING POINTS (changes in other files)
─────────────────────────────────────────────────────────────────────────────
  agent/story_driven_agent.py — call fuse() in __init__, pass to planner
  agent/bdi_planner.py        — accept fused_identity; guard abstract modes
  simulation/setup/agent_creation.py — no change needed (transparent)
"""

from __future__ import annotations

import logging
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# Optional imports (graceful degradation)
# ─────────────────────────────────────────────────────────────────
try:
    from agent.user_stories import UserStory
    _USER_STORY_AVAILABLE = True
except ImportError:
    _USER_STORY_AVAILABLE = False
    UserStory = None  # type: ignore

try:
    from agent.job_stories import JobStory, TaskContext
    _JOB_STORY_AVAILABLE = True
except ImportError:
    _JOB_STORY_AVAILABLE = False
    JobStory = None  # type: ignore
    TaskContext = None  # type: ignore

try:
    from simulation.config.modes import (
        MODES, ROUTEABLE_MODES, ABSTRACT_MODES,
        ZERO_EMISSION, FREIGHT_MODES, PASSENGER_MODES,
        is_routeable, get_network,
    )
    _MODES_AVAILABLE = True
except ImportError:
    # Fallback when modes.py not yet deployed
    _MODES_AVAILABLE = False
    ROUTEABLE_MODES = frozenset({
        'walk', 'bike', 'e_scooter', 'cargo_bike',
        'car', 'ev', 'bus', 'tram',
        'van_electric', 'van_diesel',
        'truck_electric', 'truck_diesel',
        'hgv_electric', 'hgv_diesel', 'hgv_hydrogen',
    })
    ABSTRACT_MODES = frozenset({
        'local_train', 'intercity_train',
        'ferry_diesel', 'ferry_electric',
        'flight_domestic', 'flight_electric',
    })
    def is_routeable(m): return m in ROUTEABLE_MODES
    def get_network(m):
        if m in ('local_train', 'intercity_train'):   return 'rail'
        if m in ('ferry_diesel', 'ferry_electric'):   return 'ferry'
        if m in ('flight_domestic', 'flight_electric'): return 'air'
        return 'drive'

try:
    from services.llm_client import LLMClient
    _LLM_AVAILABLE = True
except ImportError:
    _LLM_AVAILABLE = False
    LLMClient = None  # type: ignore


# ─────────────────────────────────────────────────────────────────
# FUSED IDENTITY DATACLASS
# ─────────────────────────────────────────────────────────────────

@dataclass
class FusedIdentity:
    """
    Computed combined identity for a StoryDrivenAgent.

    This is the single object BDIPlanner needs instead of the raw
    vehicle_type/vehicle_required flags it currently receives.

    Produced by PersonaFusion.fuse(user_story, job_story).
    """

    # ── Source identifiers ────────────────────────────────────────
    persona_id: str = ''
    job_id: str     = ''
    agent_label: str = ''   # '{persona_id}_{job_id}' for logging

    # ── BDI Beliefs ──────────────────────────────────────────────
    # Calibrated belief strengths for key transport beliefs.
    # These seed the BayesianBeliefUpdater at agent creation.
    beliefs: Dict[str, float] = field(default_factory=lambda: {
        'ev_is_viable':              0.50,
        'public_transport_reliable': 0.60,
        'congestion_likely':         0.40,
        'cost_pressure_high':        0.40,
        'climate_urgency':           0.50,
        'range_anxiety':             0.30,
        'charger_availability':      0.50,
    })

    # ── BDI Desires ──────────────────────────────────────────────
    # Merged and weighted from UserStory + JobStory.
    # Same key-space as existing desires dict in StoryDrivenAgent.
    desires: Dict[str, float] = field(default_factory=lambda: {
        'minimize_time':       0.50,
        'minimize_cost':       0.50,
        'minimize_emissions':  0.30,
        'maximize_comfort':    0.40,
        'maximize_reliability':0.50,
        'maximize_safety':     0.50,
    })

    # ── BDI Intentions ───────────────────────────────────────────
    # Concrete commitments derived from the job context.
    # Used by ContextualPlanGenerator and BDIPlanner.
    intentions: List[str] = field(default_factory=list)

    # ── Mode constraints ─────────────────────────────────────────
    # Hard-constrained mode set for this agent.
    # BDIPlanner.actions_for() MUST use this instead of default_modes.
    allowed_modes:  List[str] = field(default_factory=list)

    # Modes that need abstract (non-OSMnx) routing.
    abstract_modes: List[str] = field(default_factory=list)

    # Modes that can use the OSMnx graph directly.
    routeable_modes: List[str] = field(default_factory=list)

    # ── Network type ─────────────────────────────────────────────
    # Primary physical network for this agent's job.
    # 'drive' | 'walk' | 'bike' | 'rail' | 'ferry' | 'air'
    primary_network: str = 'drive'

    # Land-access modes when primary is rail/ferry/air
    # (e.g. car/bus to reach station/port/airport)
    access_modes: List[str] = field(default_factory=list)

    # ── ASI intent tier ───────────────────────────────────────────
    # 'avoid' → reduce trip frequency
    # 'shift' → switch to lower-carbon mode
    # 'improve' → upgrade current mode technology
    asi_tier: str = 'improve'

    # ── Complex Contagion gate ────────────────────────────────────
    # Minimum social proof (fraction of peers) needed before
    # this agent updates its EV viability belief.
    ev_viability_threshold: float = 0.50

    # ── Reliability flag ─────────────────────────────────────────
    reliability_critical: bool = False

    # ── LLM narrative (optional) ─────────────────────────────────
    llm_narrative: Optional[str] = None

    # ── Fusion metadata ──────────────────────────────────────────
    fusion_method: str = 'rule_based'   # 'rule_based' | 'llm' | 'hybrid'
    confidence: float  = 1.0


# ─────────────────────────────────────────────────────────────────
# PERSONA PROFILE TABLE
# Maps persona_id → baseline behavioural traits.
# Extended automatically if new personas are added.
# ─────────────────────────────────────────────────────────────────
_PERSONA_PROFILES: Dict[str, Dict[str, Any]] = {
    # ── Core passenger ───────────────────────────────────────────
    'eco_warrior': {
        'asi_tier': 'avoid',
        'ev_threshold': 0.30,
        'desire_weights': {'minimize_emissions': 0.90, 'minimize_cost': 0.40},
        'beliefs':        {'ev_is_viable': 0.80, 'climate_urgency': 0.90},
        'base_modes':     ['walk', 'bike', 'cargo_bike', 'bus', 'ev', 'e_scooter',
                           'local_train', 'intercity_train'],
    },
    'concerned_parent': {
        'asi_tier': 'shift',
        'ev_threshold': 0.45,
        'desire_weights': {'maximize_safety': 0.85, 'maximize_reliability': 0.80,
                           'minimize_cost': 0.60},
        'beliefs':        {'ev_is_viable': 0.55, 'public_transport_reliable': 0.65},
        'base_modes':     ['car', 'ev', 'bus', 'tram', 'local_train'],
    },
    'budget_student': {
        'asi_tier': 'shift',
        'ev_threshold': 0.55,
        'desire_weights': {'minimize_cost': 0.90, 'minimize_time': 0.50},
        'beliefs':        {'cost_pressure_high': 0.85, 'ev_is_viable': 0.45},
        'base_modes':     ['walk', 'bike', 'bus', 'tram', 'e_scooter', 'local_train'],
    },
    'business_commuter': {
        'asi_tier': 'improve',
        'ev_threshold': 0.50,
        'desire_weights': {'minimize_time': 0.85, 'maximize_comfort': 0.75,
                           'maximize_reliability': 0.80},
        'beliefs':        {'ev_is_viable': 0.60, 'congestion_likely': 0.65},
        'base_modes':     ['car', 'ev', 'bus', 'local_train', 'intercity_train', 'tram'],
    },
    'disabled_commuter': {
        'asi_tier': 'improve',
        'ev_threshold': 0.55,
        'desire_weights': {'maximize_accessibility': 0.95, 'maximize_reliability': 0.85,
                           'maximize_safety': 0.80},
        'beliefs':        {'public_transport_reliable': 0.50, 'ev_is_viable': 0.50},
        'base_modes':     ['bus', 'tram', 'ev', 'car', 'local_train'],
    },
    'rural_resident': {
        'asi_tier': 'improve',
        'ev_threshold': 0.65,
        'desire_weights': {'minimize_cost': 0.70, 'maximize_reliability': 0.75},
        'beliefs':        {'charger_availability': 0.30, 'range_anxiety': 0.65,
                           'public_transport_reliable': 0.30},
        'base_modes':     ['car', 'ev', 'bus', 'local_train'],
    },
    'shift_worker': {
        'asi_tier': 'improve',
        'ev_threshold': 0.55,
        'desire_weights': {'minimize_cost': 0.75, 'maximize_reliability': 0.80},
        'beliefs':        {'public_transport_reliable': 0.45, 'cost_pressure_high': 0.70},
        'base_modes':     ['car', 'ev', 'bus', 'van_electric', 'van_diesel'],
    },
    'tourist': {
        'asi_tier': 'improve',
        'ev_threshold': 0.50,
        'desire_weights': {'maximize_comfort': 0.75, 'minimize_time': 0.55},
        'beliefs':        {'ev_is_viable': 0.55},
        'base_modes':     ['car', 'ev', 'bus', 'local_train', 'intercity_train',
                           'ferry_diesel', 'ferry_electric'],
    },
    'delivery_driver': {
        'asi_tier': 'shift',
        'ev_threshold': 0.55,
        'desire_weights': {'minimize_time': 0.80, 'minimize_cost': 0.75},
        'beliefs':        {'ev_is_viable': 0.55, 'cost_pressure_high': 0.70},
        'base_modes':     ['van_electric', 'van_diesel', 'cargo_bike'],
    },
    'freight_operator': {
        'asi_tier': 'shift',
        'ev_threshold': 0.65,
        'desire_weights': {'minimize_cost': 0.85, 'maximize_reliability': 0.85,
                           'minimize_time': 0.70},
        'beliefs':        {'ev_is_viable': 0.45, 'range_anxiety': 0.60,
                           'cost_pressure_high': 0.80},
        'base_modes':     ['van_electric', 'van_diesel', 'truck_electric', 'truck_diesel',
                           'hgv_electric', 'hgv_diesel'],
    },
    # ── DfT segments ─────────────────────────────────────────────
    'retired_commuter': {
        'asi_tier': 'improve',
        'ev_threshold': 0.60,
        'desire_weights': {'minimize_cost': 0.70, 'maximize_comfort': 0.70},
        'beliefs':        {'ev_is_viable': 0.45, 'public_transport_reliable': 0.60},
        'base_modes':     ['car', 'ev', 'bus', 'local_train', 'tram'],
    },
    'frequent_driver': {
        'asi_tier': 'improve',
        'ev_threshold': 0.55,
        'desire_weights': {'minimize_time': 0.75, 'maximize_comfort': 0.65},
        'beliefs':        {'ev_is_viable': 0.55, 'congestion_likely': 0.55},
        'base_modes':     ['car', 'ev', 'van_electric', 'van_diesel'],
    },
    'elderly_non_driver': {
        'asi_tier': 'shift',
        'ev_threshold': 0.65,
        'desire_weights': {'maximize_accessibility': 0.90, 'maximize_safety': 0.85,
                           'maximize_comfort': 0.70},
        'beliefs':        {'public_transport_reliable': 0.55, 'ev_is_viable': 0.35},
        'base_modes':     ['bus', 'tram', 'local_train', 'ferry_diesel', 'ferry_electric'],
    },
    # ── Multi-modal ───────────────────────────────────────────────
    'long_distance_commuter': {
        'asi_tier': 'shift',
        'ev_threshold': 0.55,
        'desire_weights': {'minimize_time': 0.85, 'minimize_cost': 0.65,
                           'maximize_comfort': 0.65},
        'beliefs':        {'ev_is_viable': 0.60, 'public_transport_reliable': 0.65},
        'base_modes':     ['car', 'ev', 'intercity_train', 'local_train'],
    },
    'island_resident': {
        'asi_tier': 'improve',
        'ev_threshold': 0.70,
        'desire_weights': {'maximize_reliability': 0.90, 'minimize_cost': 0.70},
        'beliefs':        {'charger_availability': 0.25, 'range_anxiety': 0.75,
                           'public_transport_reliable': 0.55},
        # Island residents MUST have ferry access; land access only on island
        'base_modes':     ['car', 'ev', 'ferry_diesel', 'ferry_electric'],
        'access_modes':   ['car', 'ev', 'bus'],
    },
    'business_traveler': {
        'asi_tier': 'shift',
        'ev_threshold': 0.45,
        'desire_weights': {'minimize_time': 0.90, 'maximize_comfort': 0.80,
                           'maximize_reliability': 0.80},
        'beliefs':        {'ev_is_viable': 0.65, 'public_transport_reliable': 0.75},
        'base_modes':     ['car', 'ev', 'intercity_train', 'local_train',
                           'bus', 'flight_domestic', 'flight_electric'],
    },
    'accessibility_user': {
        'asi_tier': 'improve',
        'ev_threshold': 0.60,
        'desire_weights': {'maximize_accessibility': 0.95, 'maximize_reliability': 0.85},
        'beliefs':        {'public_transport_reliable': 0.50},
        'base_modes':     ['bus', 'tram', 'ev', 'car', 'local_train'],
    },
    'tourist_visitor': {
        'asi_tier': 'improve',
        'ev_threshold': 0.45,
        'desire_weights': {'maximize_comfort': 0.80, 'minimize_cost': 0.55},
        'beliefs':        {'ev_is_viable': 0.60},
        'base_modes':     ['car', 'ev', 'bus', 'local_train', 'intercity_train',
                           'ferry_diesel', 'ferry_electric'],
    },
    # ── Operator personas ─────────────────────────────────────────
    'fleet_manager_logistics': {
        'asi_tier': 'shift',
        'ev_threshold': 0.70,
        'desire_weights': {'minimize_cost': 0.85, 'maximize_reliability': 0.90,
                           'minimize_emissions': 0.50},
        'beliefs':        {'ev_is_viable': 0.50, 'cost_pressure_high': 0.85,
                           'range_anxiety': 0.55},
        'base_modes':     ['van_electric', 'van_diesel', 'truck_electric', 'truck_diesel',
                           'hgv_electric', 'hgv_diesel'],
    },
    'fleet_manager_healthcare': {
        'asi_tier': 'improve',
        'ev_threshold': 0.75,
        'desire_weights': {'maximize_reliability': 0.95, 'maximize_safety': 0.90,
                           'minimize_cost': 0.60},
        'beliefs':        {'ev_is_viable': 0.55, 'charger_availability': 0.55},
        'base_modes':     ['van_electric', 'van_diesel', 'ev', 'car'],
    },
    'fleet_manager_retail': {
        'asi_tier': 'shift',
        'ev_threshold': 0.65,
        'desire_weights': {'minimize_cost': 0.85, 'minimize_time': 0.75},
        'beliefs':        {'ev_is_viable': 0.55, 'cost_pressure_high': 0.75},
        'base_modes':     ['van_electric', 'van_diesel', 'cargo_bike', 'truck_electric',
                           'truck_diesel'],
    },
    'port_terminal_operator': {
        'asi_tier': 'shift',
        'ev_threshold': 0.70,
        'desire_weights': {'maximize_reliability': 0.90, 'minimize_emissions': 0.55,
                           'minimize_cost': 0.75},
        'beliefs':        {'ev_is_viable': 0.50, 'cost_pressure_high': 0.80},
        'base_modes':     ['hgv_diesel', 'hgv_electric', 'hgv_hydrogen',
                           'truck_diesel', 'truck_electric'],
    },
    'rail_freight_operator': {
        'asi_tier': 'shift',
        'ev_threshold': 0.70,
        'desire_weights': {'minimize_cost': 0.80, 'minimize_emissions': 0.60,
                           'maximize_reliability': 0.85},
        'beliefs':        {'ev_is_viable': 0.50, 'public_transport_reliable': 0.80},
        # Rail freight: drayage legs use truck; main haul is abstract (rail)
        # Phase 10b: add 'freight_rail' here when RailFreightAgent is ready
        'base_modes':     ['truck_electric', 'truck_diesel', 'hgv_diesel', 'hgv_electric'],
        'access_modes':   ['truck_electric', 'truck_diesel'],
        'primary_network': 'drive',    # drayage on drive; abstract rail not yet in OSMnx
    },
    'air_freight_operator': {
        'asi_tier': 'improve',
        'ev_threshold': 0.75,
        'desire_weights': {'minimize_time': 0.90, 'maximize_reliability': 0.90,
                           'minimize_cost': 0.65},
        'beliefs':        {'ev_is_viable': 0.40},
        'base_modes':     ['van_electric', 'van_diesel', 'truck_electric', 'truck_diesel',
                           'flight_domestic'],
        'access_modes':   ['van_electric', 'van_diesel'],
        'primary_network': 'drive',    # ground legs on drive
    },
    # ── NHS extended ──────────────────────────────────────────────
    'paramedic': {
        'asi_tier': 'improve',
        'ev_threshold': 0.85,
        'reliability_critical': True,
        'desire_weights': {'maximize_reliability': 0.99, 'maximize_safety': 0.95,
                           'minimize_time': 0.90},
        'beliefs':        {'ev_is_viable': 0.45, 'charger_availability': 0.40},
        'base_modes':     ['van_diesel', 'van_electric'],   # EV blocked if charger_occ>0.1
    },
    'community_health_worker': {
        'asi_tier': 'shift',
        'ev_threshold': 0.60,
        'desire_weights': {'minimize_cost': 0.75, 'maximize_reliability': 0.80,
                           'minimize_emissions': 0.55},
        'beliefs':        {'ev_is_viable': 0.60, 'charger_availability': 0.55},
        'base_modes':     ['van_electric', 'van_diesel', 'ev', 'car'],
    },
    'nhs_ward_manager': {
        'asi_tier': 'improve',
        'ev_threshold': 0.60,
        'desire_weights': {'minimize_cost': 0.70, 'maximize_reliability': 0.80},
        'beliefs':        {'ev_is_viable': 0.55},
        'base_modes':     ['car', 'ev', 'bus', 'van_electric', 'van_diesel'],
    },
    'clinical_waste_driver': {
        'asi_tier': 'improve',
        'ev_threshold': 0.65,
        'desire_weights': {'maximize_reliability': 0.85, 'maximize_safety': 0.85,
                           'minimize_cost': 0.65},
        'beliefs':        {'ev_is_viable': 0.50},
        'base_modes':     ['van_diesel', 'van_electric', 'truck_diesel', 'truck_electric'],
    },
    'nhs_supply_chain': {
        'asi_tier': 'shift',
        'ev_threshold': 0.65,
        'desire_weights': {'minimize_cost': 0.80, 'maximize_reliability': 0.80,
                           'minimize_emissions': 0.50},
        'beliefs':        {'ev_is_viable': 0.55, 'cost_pressure_high': 0.70},
        'base_modes':     ['van_electric', 'van_diesel', 'truck_electric', 'truck_diesel'],
    },
}

# ─────────────────────────────────────────────────────────────────
# JOB → ALLOWED MODES OVERRIDE TABLE
# When a job has a specific physical network requirement, list the
# modes that are appropriate.  Agents not in this table get their
# modes from the persona profile + vehicle_type context.
# ─────────────────────────────────────────────────────────────────
_JOB_MODE_OVERRIDES: Dict[str, Dict[str, Any]] = {
    # ── Ferry jobs ────────────────────────────────────────────────
    'island_ferry_trip': {
        'abstract_modes': ['ferry_diesel', 'ferry_electric'],
        'access_modes':   ['car', 'ev', 'bus'],
        'primary_network': 'ferry',
        'intentions':     ['board_ferry', 'travel_to_island'],
    },
    'rosyth_roro_freight': {
        'abstract_modes': ['ferry_diesel', 'ferry_electric'],
        'access_modes':   ['hgv_diesel', 'hgv_electric', 'truck_diesel', 'truck_electric'],
        'primary_network': 'ferry',
        'intentions':     ['drive_to_port', 'board_roro_ferry', 'unload_at_destination'],
    },
    'dover_roro_outbound': {
        'abstract_modes': ['ferry_diesel', 'ferry_electric'],
        'access_modes':   ['hgv_diesel', 'hgv_electric'],
        'primary_network': 'ferry',
        'intentions':     ['drive_to_port', 'board_roro_ferry'],
    },
    'ferry_freight_roro': {
        'abstract_modes': ['ferry_diesel', 'ferry_electric'],
        'access_modes':   ['truck_diesel', 'truck_electric', 'hgv_diesel', 'hgv_electric'],
        'primary_network': 'ferry',
        'intentions':     ['load_freight', 'board_ferry', 'offload_freight'],
    },

    # ── Aviation jobs ─────────────────────────────────────────────
    'island_lifeline_air': {
        'abstract_modes': ['flight_domestic', 'flight_electric'],
        'access_modes':   ['car', 'ev', 'bus'],
        'primary_network': 'air',
        'intentions':     ['travel_to_airport', 'board_flight', 'lifeline_service'],
    },
    'domestic_air_travel': {
        'abstract_modes': ['flight_domestic', 'flight_electric'],
        'access_modes':   ['car', 'ev', 'bus', 'local_train'],
        'primary_network': 'air',
        'intentions':     ['travel_to_airport', 'board_flight'],
    },
    'business_flight': {
        'abstract_modes': ['flight_domestic', 'flight_electric'],
        'access_modes':   ['car', 'ev', 'local_train'],
        'primary_network': 'air',
        'intentions':     ['check_in', 'board_flight', 'business_meeting'],
    },
    'air_cargo_express': {
        'abstract_modes': ['flight_domestic'],
        'access_modes':   ['van_electric', 'van_diesel'],
        'primary_network': 'air',
        'intentions':     ['collect_cargo', 'airside_transfer', 'deliver_cargo'],
    },

    # ── Rail jobs ─────────────────────────────────────────────────
    'rail_freight_intermodal': {
        # Drayage legs are on road; the rail haul is abstract.
        # Phase 10b: add 'freight_rail' to abstract_modes when ready.
        'abstract_modes': [],     # no abstract routing yet — pure drayage
        'access_modes':   ['truck_electric', 'truck_diesel', 'hgv_diesel', 'hgv_electric'],
        'primary_network': 'drive',
        'intentions':     ['drayage_to_rail_terminal', 'rail_haul', 'drayage_to_destination'],
    },
    'rail_freight_bulk': {
        'abstract_modes': [],
        'access_modes':   ['hgv_diesel', 'hgv_electric', 'hgv_hydrogen'],
        'primary_network': 'drive',
        'intentions':     ['bulk_load', 'rail_haul', 'bulk_unload'],
    },
    'rail_freight_terminal_drayage': {
        'abstract_modes': [],
        'access_modes':   ['truck_electric', 'truck_diesel'],
        'primary_network': 'drive',
        'intentions':     ['drayage_collection', 'terminal_delivery'],
    },
    'commuter_rail_journey': {
        'abstract_modes': ['local_train'],
        'access_modes':   ['walk', 'bike', 'bus', 'car', 'ev'],
        'primary_network': 'rail',
        'intentions':     ['travel_to_station', 'board_train', 'commute'],
    },
    'intercity_train_commute': {
        'abstract_modes': ['intercity_train'],
        'access_modes':   ['car', 'ev', 'bus', 'local_train'],
        'primary_network': 'rail',
        'intentions':     ['travel_to_station', 'board_intercity', 'commute'],
    },
    'tourist_scenic_rail': {
        'abstract_modes': ['local_train', 'intercity_train'],
        'access_modes':   ['car', 'ev', 'bus'],
        'primary_network': 'rail',
        'intentions':     ['scenic_journey', 'tourism'],
    },

    # ── Port jobs ─────────────────────────────────────────────────
    'container_terminal_drayage': {
        'abstract_modes': [],
        'access_modes':   ['hgv_diesel', 'hgv_electric', 'truck_diesel', 'truck_electric'],
        'primary_network': 'drive',
        'intentions':     ['container_pickup', 'port_delivery'],
    },
    'port_of_london_barge_transfer': {
        'abstract_modes': ['ferry_diesel', 'ferry_electric'],
        'access_modes':   ['truck_diesel', 'truck_electric'],
        'primary_network': 'ferry',
        'intentions':     ['barge_transfer', 'river_logistics'],
    },
}


# ─────────────────────────────────────────────────────────────────
# ASI TIER LOOKUP
# job_category → ASI tier (persona overrides this if stronger)
# ─────────────────────────────────────────────────────────────────
_JOB_ASI_TIERS: Dict[str, str] = {
    'passenger_commute':     'improve',
    'passenger_errand':      'improve',
    'passenger_special':     'shift',
    'freight':               'shift',
    'multimodal_freight':    'shift',
    'logistics':             'shift',
    'passenger_leisure':     'avoid',
    'service':               'improve',
    'heavy_freight':         'shift',
    'rail_operations':       'shift',
    'port_operations':       'shift',
    'aviation':              'improve',
    'nhs_operations':        'improve',
}

_ASI_PRIORITY = {'avoid': 0, 'shift': 1, 'improve': 2}


def _pick_asi_tier(persona_tier: str, job_category: str) -> str:
    """Pick the lower ASI tier (more conservative / earlier in hierarchy)."""
    job_tier = _JOB_ASI_TIERS.get(job_category, 'improve')
    if _ASI_PRIORITY.get(persona_tier, 2) <= _ASI_PRIORITY.get(job_tier, 2):
        return persona_tier
    return job_tier


# ─────────────────────────────────────────────────────────────────
# PERSONA FUSION CLASS
# ─────────────────────────────────────────────────────────────────

class PersonaFusion:
    """
    Fuse a UserStory and a JobStory into a FusedIdentity.

    Usage:
        fusion = PersonaFusion()
        identity = fusion.fuse(user_story, job_story)
        agent = StoryDrivenAgent(fused_identity=identity, ...)

    LLM synthesis:
        identity = await fusion.fuse_with_llm(user_story, job_story)
    """

    def __init__(self, llm_client=None):
        self._llm = llm_client  # LLMClient instance (optional)

    # ─────────────────────────────────────────────────────────────
    # PUBLIC: rule-based fuse (synchronous, always available)
    # ─────────────────────────────────────────────────────────────
    def fuse(self, user_story: Any, job_story: Any) -> FusedIdentity:
        """
        Fuse user_story + job_story into a FusedIdentity.

        Works with both UserStory dataclass instances and plain dicts
        (for compatibility with agents created before this module).

        Args:
            user_story: UserStory instance or dict with 'story_id', 'desires',
                        'beliefs', 'mode_preferences', 'constraints'
            job_story:  JobStory instance or dict with 'job_id', 'parameters',
                        'typical_vehicle', 'vehicle_required', 'job_category'

        Returns:
            FusedIdentity with all fields populated.
        """
        persona_id = self._get_attr(user_story, 'story_id', '')
        # Fallback to story_id if job_id is empty
        job_id = self._get_attr(job_story, 'job_id') or self._get_attr(job_story, 'story_id', '')
        label      = f"{persona_id}_{job_id}"

        logger.debug("PersonaFusion: fusing %s", label)

        # 1. Look up persona profile (use defaults if unknown)
        profile = _PERSONA_PROFILES.get(persona_id, {})

        # 2. Compute desires (merge persona + job)
        desires = self._compute_desires(user_story, job_story, profile)

        # 3. Compute beliefs (persona-calibrated + job-adjusted)
        beliefs = self._compute_beliefs(user_story, job_story, profile)

        # 4. Compute intentions (job-derived)
        intentions = self._compute_intentions(job_story, job_id)

        # 5. Compute allowed modes (hard constraint)
        allowed, abstract, routeable, primary_net, access = \
            self._compute_modes(user_story, job_story, persona_id, job_id, profile)

        # 6. ASI tier
        persona_asi = profile.get('asi_tier', 'improve')
        job_category = self._get_attr(job_story, 'job_category', '') or \
                       self._infer_job_category(job_id)
        asi_tier = _pick_asi_tier(persona_asi, job_category)

        # 7. EV viability threshold
        ev_threshold = profile.get('ev_threshold', 0.50)
        ev_threshold = self._adjust_ev_threshold(ev_threshold, job_id, job_category)

        # 8. Reliability critical flag
        reliability_critical = (
            profile.get('reliability_critical', False) or
            bool(self._get_attr(user_story, 'reliability_critical', False)) or
            'ambulance' in job_id or 'emergency' in job_id
        )

        identity = FusedIdentity(
            persona_id=persona_id,
            job_id=job_id,
            agent_label=label,
            beliefs=beliefs,
            desires=desires,
            intentions=intentions,
            allowed_modes=allowed,
            abstract_modes=abstract,
            routeable_modes=routeable,
            primary_network=primary_net,
            access_modes=access,
            asi_tier=asi_tier,
            ev_viability_threshold=ev_threshold,
            reliability_critical=reliability_critical,
            fusion_method='rule_based',
            confidence=1.0,
        )

        logger.debug(
            "PersonaFusion: %s → asi=%s ev_thr=%.2f modes=%s abstract=%s",
            label, asi_tier, ev_threshold, allowed, abstract,
        )
        return identity

    # ─────────────────────────────────────────────────────────────
    # PUBLIC: LLM-enhanced fuse (adds narrative synthesis)
    # ─────────────────────────────────────────────────────────────
    def fuse_with_llm(self, user_story: Any, job_story: Any) -> FusedIdentity:
        """
        Fuse with optional OLMo 2 narrative synthesis.

        Falls back gracefully to rule-based if LLM unavailable.
        The LLM output enriches the FusedIdentity with a behavioural
        narrative used in report generation and XAI explanations.
        It does NOT override hard constraints (allowed_modes, asi_tier).
        """
        identity = self.fuse(user_story, job_story)

        if not self._llm or not _LLM_AVAILABLE:
            return identity

        try:
            narrative = self._synthesise_narrative(user_story, job_story, identity)
            if narrative:
                identity.llm_narrative = narrative
                identity.fusion_method = 'hybrid'
                identity.confidence    = 0.85
        except Exception as exc:
            logger.warning("PersonaFusion: LLM synthesis failed (%s) — using rule-based", exc)

        return identity

    # ─────────────────────────────────────────────────────────────
    # PRIVATE: compute desires
    # ─────────────────────────────────────────────────────────────
    def _compute_desires(self, user_story, job_story, profile) -> Dict[str, float]:
        base = {
            'minimize_time':        0.50,
            'minimize_cost':        0.50,
            'minimize_emissions':   0.30,
            'maximize_comfort':     0.40,
            'maximize_reliability': 0.50,
            'maximize_safety':      0.50,
            'maximize_accessibility': 0.30,
        }

        # 1. Apply persona profile weights
        for k, v in profile.get('desire_weights', {}).items():
            base[k] = v

        # 2. Merge user_story desires (if present)
        us_desires = self._get_attr(user_story, 'desires', {}) or {}
        for k, v in us_desires.items():
            if k in base:
                # Weighted average: 60% persona profile, 40% story YAML
                base[k] = 0.6 * base[k] + 0.4 * float(v)
            else:
                base[k] = float(v)

        # 3. Apply desire_variance jitter (seeded by agent ID for reproducibility)
        variance = self._get_attr(user_story, 'desire_variance', 0.10)
        import random
        rng = random.Random(hash(str(self._get_attr(user_story, 'story_id', ''))))
        for k in base:
            jitter = rng.uniform(-variance, variance)
            base[k] = max(0.0, min(1.0, base[k] + jitter))

        return base

    # ─────────────────────────────────────────────────────────────
    # PRIVATE: compute beliefs
    # ─────────────────────────────────────────────────────────────
    def _compute_beliefs(self, user_story, job_story, profile) -> Dict[str, float]:
        base = {
            'ev_is_viable':              0.50,
            'public_transport_reliable': 0.60,
            'congestion_likely':         0.40,
            'cost_pressure_high':        0.40,
            'climate_urgency':           0.50,
            'range_anxiety':             0.30,
            'charger_availability':      0.50,
        }

        # Apply persona profile
        for k, v in profile.get('beliefs', {}).items():
            base[k] = float(v)

        # Merge user_story beliefs list → dict
        us_beliefs = self._get_attr(user_story, 'beliefs', []) or []
        for b in us_beliefs:
            text = self._get_attr(b, 'text', '') or str(b)
            strength = float(self._get_attr(b, 'strength', 0.5))
            # Map narrative text to belief key
            mapped = self._map_belief_text(text)
            if mapped:
                base[mapped] = (base.get(mapped, 0.5) + strength) / 2.0

        return base

    # ─────────────────────────────────────────────────────────────
    # PRIVATE: compute intentions
    # ─────────────────────────────────────────────────────────────
    def _compute_intentions(self, job_story, job_id: str) -> List[str]:
        """Derive BDI intentions from job context."""
        intentions: List[str] = []

        # From job override table
        override = _JOB_MODE_OVERRIDES.get(job_id, {})
        intentions.extend(override.get('intentions', []))

        # From job_story plan_context
        plan_context = self._get_attr(job_story, 'plan_context', []) or []
        for item in plan_context:
            step = str(item) if not isinstance(item, str) else item
            if step and step not in intentions:
                intentions.append(step)

        # Fallback: infer from job_id keywords
        if not intentions:
            if 'commute' in job_id:
                intentions = ['travel_to_work', 'return_home']
            elif 'delivery' in job_id or 'freight' in job_id:
                intentions = ['collect_load', 'deliver_load']
            elif 'ferry' in job_id or 'island' in job_id:
                intentions = ['travel_to_port', 'board_ferry']
            elif 'air' in job_id or 'flight' in job_id:
                intentions = ['travel_to_airport', 'board_flight']
            elif 'rail' in job_id or 'train' in job_id:
                intentions = ['travel_to_station', 'board_train']
            else:
                intentions = ['point_to_point_trip']

        return intentions

    # ─────────────────────────────────────────────────────────────
    # PRIVATE: compute allowed modes
    # ─────────────────────────────────────────────────────────────
    def _compute_modes(
        self, user_story, job_story, persona_id: str, job_id: str, profile
    ) -> Tuple[List[str], List[str], List[str], str, List[str]]:
        """
        Returns:
            (allowed_modes, abstract_modes, routeable_modes, primary_network, access_modes)
        """
        override = _JOB_MODE_OVERRIDES.get(job_id)

        if override:
            abstract = list(override.get('abstract_modes', []))
            access   = list(override.get('access_modes',   []))
            primary  = override.get('primary_network', 'drive')

            # If the job has abstract (rail/ferry/air) modes,
            # the routeable set is the access modes only.
            routeable = [m for m in access if is_routeable(m)]
            allowed   = abstract + routeable

        else:
            # Use persona profile base_modes
            persona_modes = list(profile.get('base_modes', [
                'car', 'ev', 'bus', 'walk',
            ]))
            # Filter by vehicle_type from job story
            persona_modes = self._filter_by_vehicle_type(
                persona_modes, job_story, persona_id
            )
            abstract  = [m for m in persona_modes if not is_routeable(m)]
            routeable = [m for m in persona_modes if is_routeable(m)]
            primary   = profile.get('primary_network', 'drive')
            access    = list(profile.get('access_modes', []))
            allowed   = persona_modes

        # Never return an empty allowed_modes
        if not allowed:
            logger.warning(
                "PersonaFusion: empty allowed_modes for %s+%s — falling back to [car, ev, bus]",
                persona_id, job_id,
            )
            allowed   = ['car', 'ev', 'bus']
            routeable = ['car', 'ev', 'bus']
            abstract  = []

        return allowed, abstract, routeable, primary, access

    # ─────────────────────────────────────────────────────────────
    # PRIVATE: filter modes by job vehicle_type
    # ─────────────────────────────────────────────────────────────
    def _filter_by_vehicle_type(
        self, modes: List[str], job_story: Any, persona_id: str
    ) -> List[str]:
        vehicle_type = self._get_attr(job_story, 'vehicle_type', '') or \
                       self._get_attr(job_story, 'typical_vehicle', '') or ''
        vehicle_type = str(vehicle_type).lower()
        vehicle_required = bool(self._get_attr(job_story, 'vehicle_required', False))

        _FREIGHT_M = {'van_electric', 'van_diesel', 'truck_electric', 'truck_diesel',
                      'hgv_electric', 'hgv_diesel', 'hgv_hydrogen', 'cargo_bike'}
        _PASSENGER_M = {'walk', 'bike', 'e_scooter', 'cargo_bike', 'car', 'ev',
                        'bus', 'tram', 'local_train', 'intercity_train',
                        'ferry_diesel', 'ferry_electric', 'flight_domestic', 'flight_electric'}

        if 'heavy_freight' in vehicle_type:
            keep = {'hgv_diesel', 'hgv_electric', 'hgv_hydrogen', 'truck_diesel', 'truck_electric'}
        elif 'medium_freight' in vehicle_type or 'commercial' in vehicle_type:
            keep = {'van_electric', 'van_diesel', 'truck_electric', 'truck_diesel', 'cargo_bike'}
        elif vehicle_required and vehicle_type in ('personal', 'transit'):
            keep = _PASSENGER_M
        elif vehicle_required and not vehicle_type:
            # Don't over-restrict; return as-is
            return modes
        else:
            return modes

        return [m for m in modes if m in keep] or modes

    # ─────────────────────────────────────────────────────────────
    # PRIVATE: LLM narrative synthesis
    # ─────────────────────────────────────────────────────────────
    def _synthesise_narrative(
        self, user_story: Any, job_story: Any, identity: FusedIdentity
    ) -> Optional[str]:
        """Call OLMo 2 to generate a context-rich behavioural tendency paragraph."""
        if not self._llm:
            return None

        persona_id = identity.persona_id
        job_id     = identity.job_id
        desires    = ', '.join(f"{k}={v:.2f}" for k, v in
                               sorted(identity.desires.items(), key=lambda x: -x[1])[:4])
        modes      = ', '.join(identity.allowed_modes[:5])

        prompt = (
            f"You are synthesising a behavioural profile for a transport simulation agent.\n"
            f"Persona: {persona_id}\n"
            f"Job context: {job_id}\n"
            f"Top desires: {desires}\n"
            f"Available modes: {modes}\n"
            f"ASI tier: {identity.asi_tier}\n\n"
            f"In 2-3 sentences, describe how this agent approaches transport decisions, "
            f"what trade-offs they prioritise, and what would change their mode choice. "
            f"Be specific about the {job_id} job context. Do not use bullet points."
        )

        try:
            response = self._llm.complete(prompt, max_tokens=150)
            return response.strip() if response else None
        except Exception as exc:
            logger.debug("PersonaFusion LLM call failed: %s", exc)
            return None

    # ─────────────────────────────────────────────────────────────
    # PRIVATE: helpers
    # ─────────────────────────────────────────────────────────────
    @staticmethod
    def _get_attr(obj: Any, attr: str, default: Any = None) -> Any:
        """Get attribute from dataclass or dict."""
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)

    @staticmethod
    def _map_belief_text(text: str) -> Optional[str]:
        """Map free-text belief to canonical belief key."""
        t = text.lower()
        if any(w in t for w in ('ev', 'electric', 'battery')):
            return 'ev_is_viable'
        if any(w in t for w in ('transit', 'public transport', 'bus', 'train')):
            return 'public_transport_reliable'
        if any(w in t for w in ('congestion', 'traffic', 'jam')):
            return 'congestion_likely'
        if any(w in t for w in ('cost', 'afford', 'price', 'expensive')):
            return 'cost_pressure_high'
        if any(w in t for w in ('climate', 'carbon', 'emission', 'environment')):
            return 'climate_urgency'
        if any(w in t for w in ('range', 'anxiety', 'mileage')):
            return 'range_anxiety'
        if any(w in t for w in ('charger', 'charging', 'infrastructure')):
            return 'charger_availability'
        return None

    @staticmethod
    def _infer_job_category(job_id: str) -> str:
        """Infer job category from job_id string."""
        if any(w in job_id for w in ('commute', 'commuter')):
            return 'passenger_commute'
        if any(w in job_id for w in ('freight', 'logistics', 'delivery', 'hgv', 'truck', 'van')):
            return 'freight'
        if any(w in job_id for w in ('ferry', 'island', 'roro')):
            return 'port_operations'
        if any(w in job_id for w in ('air', 'flight', 'aviation')):
            return 'aviation'
        if any(w in job_id for w in ('rail', 'train')):
            return 'rail_operations'
        if any(w in job_id for w in ('nhs', 'patient', 'clinical', 'ambulance')):
            return 'nhs_operations'
        if any(w in job_id for w in ('port', 'terminal', 'drayage', 'barge')):
            return 'port_operations'
        return 'passenger_errand'

    @staticmethod
    def _adjust_ev_threshold(base: float, job_id: str, job_category: str) -> float:
        """Adjust EV viability threshold based on job context."""
        # High-risk freight jobs: raise threshold (more social proof needed)
        if job_category in ('freight', 'heavy_freight', 'multimodal_freight'):
            base = min(0.90, base + 0.10)
        # Emergency / critical reliability: raise threshold
        if any(w in job_id for w in ('ambulance', 'emergency', 'clinical_waste')):
            base = min(0.95, base + 0.15)
        # Eco-conscious leisure: lower threshold
        if any(w in job_id for w in ('leisure', 'scenic', 'tourist')):
            base = max(0.20, base - 0.10)
        return round(base, 2)

    @staticmethod
    def _determine_network_type(job_id: str) -> str:
        """Map job context to physical network type."""
        # Add rail/tram detection
        if any(w in job_id for w in ('rail', 'train', 'tram')):
            return 'rail'
        if 'walk' in job_id:
            return 'walk'
        if 'bike' in job_id or 'cycling' in job_id:
            return 'bike'
        return 'drive'

# ─────────────────────────────────────────────────────────────────
# MODULE-LEVEL SINGLETON (convenience)
# ─────────────────────────────────────────────────────────────────
_DEFAULT_FUSION = PersonaFusion()


def fuse(user_story: Any, job_story: Any) -> FusedIdentity:
    """Module-level convenience wrapper around PersonaFusion.fuse()."""
    return _DEFAULT_FUSION.fuse(user_story, job_story)
