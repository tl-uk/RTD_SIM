"""
simulation/config/modes.py  ← Phase 10b MODES registry

Central authority for mode → network-type mapping.
This is the blocker that was causing rail/ferry/air agents
to route on the OSMnx drive graph and appear on motorways.

NETWORK TYPES
─────────────
  'drive'   → OSMnx drive graph   (routeable via OSMnx)
  'walk'    → OSMnx walk graph    (routeable via OSMnx)
  'bike'    → OSMnx bike graph    (routeable via OSMnx)
  'rail'    → abstract / GTFS     (NOT routeable via OSMnx)
  'ferry'   → abstract / maritime (NOT routeable via OSMnx)
  'air'     → abstract / airspace (NOT routeable via OSMnx)

Abstract modes produce a synthetic single-edge route of
  distance = straight_line_km × ABSTRACT_ROUTE_FACTOR
rather than a real path.  The BDIPlanner uses is_routeable()
to decide which path to take.

USAGE
─────
  from simulation.config.modes import MODES, is_routeable, abstract_distance_km

  net = MODES['intercity_train']['network']   # 'rail'
  if not is_routeable('ferry_electric'):
      dist = abstract_distance_km(origin, dest, 'ferry_electric')
"""

from __future__ import annotations
from typing import Dict, Any, Tuple
import math

# ─────────────────────────────────────────────────────────────────
# CORE REGISTRY
# ─────────────────────────────────────────────────────────────────
MODES: Dict[str, Dict[str, Any]] = {
    # ── Active micro-mobility ──────────────────────────────────────
    'walk': {
        'network':       'walk',
        'emissions_g_km': 0,
        'speed_kmh':      5,
        'routeable':      True,
    },
    'bike': {
        'network':       'bike',
        'emissions_g_km': 0,
        'speed_kmh':      15,
        'routeable':      True,
    },
    'e_scooter': {
        'network':       'bike',
        'emissions_g_km': 0,
        'speed_kmh':      20,
        'routeable':      True,
    },
    'cargo_bike': {
        'network':       'bike',
        'emissions_g_km': 0,
        'speed_kmh':      18,
        'routeable':      True,
    },

    # ── Road – personal ───────────────────────────────────────────
    'car': {
        'network':       'drive',
        'emissions_g_km': 170,
        'speed_kmh':      50,
        'routeable':      True,
    },
    'ev': {
        'network':       'drive',
        'emissions_g_km': 0,
        'speed_kmh':      50,
        'routeable':      True,
        'range_km':       350,
    },
    'bus': {
        'network':       'drive',
        'emissions_g_km': 82,
        'speed_kmh':      30,
        'routeable':      True,
    },
    'tram': {
        # Trams follow road corridors in OSMnx drive graph.
        # Not a perfect proxy but acceptable until GTFS integration.
        'network':       'drive',
        'emissions_g_km': 35,
        'speed_kmh':      25,
        'routeable':      True,
    },

    # ── Road – light commercial ───────────────────────────────────
    'van_electric': {
        'network':       'drive',
        'emissions_g_km': 0,
        'speed_kmh':      50,
        'routeable':      True,
        'range_km':       200,
    },
    'van_diesel': {
        'network':       'drive',
        'emissions_g_km': 150,
        'speed_kmh':      50,
        'routeable':      True,
    },

    # ── Road – medium freight ─────────────────────────────────────
    'truck_electric': {
        'network':       'drive',
        'emissions_g_km': 0,
        'speed_kmh':      60,
        'routeable':      True,
        'range_km':       250,
    },
    'truck_diesel': {
        'network':       'drive',
        'emissions_g_km': 200,
        'speed_kmh':      60,
        'routeable':      True,
    },

    # ── Road – heavy goods ────────────────────────────────────────
    'hgv_electric': {
        'network':       'drive',
        'emissions_g_km': 0,
        'speed_kmh':      55,
        'routeable':      True,
        'range_km':       300,
    },
    'hgv_diesel': {
        'network':       'drive',
        'emissions_g_km': 900,
        'speed_kmh':      55,
        'routeable':      True,
    },
    'hgv_hydrogen': {
        'network':       'drive',
        'emissions_g_km': 0,
        'speed_kmh':      55,
        'routeable':      True,
        'range_km':       600,
    },

    # ── Rail – ABSTRACT (no OSMnx routing) ───────────────────────
    # These appear on the map as a straight-line segment with a
    # station-marker icon at each endpoint.  Phase 10b will replace
    # this with GTFS path interpolation.
    'local_train': {
        'network':       'rail',
        'emissions_g_km': 41,
        'speed_kmh':      80,
        'routeable':      True,
    },
    'intercity_train': {
        'network':       'rail',
        'emissions_g_km': 41,
        'speed_kmh':      150,
        'routeable':      True,
    },
    # Phase 10b stub – uncomment when RailFreightAgent is ready
    'freight_rail': {
        'network':       'rail',
        'emissions_g_km': 35,   # electrified; 76 diesel
        'speed_kmh':      80,
        'routeable':      True,
    },

    # ── Ferry – ABSTRACT ─────────────────────────────────────────
    'ferry_diesel': {
        'network':       'ferry',
        'emissions_g_km': 115,
        'speed_kmh':      30,    # ~16 knots
        'routeable':      False,
    },
    'ferry_electric': {
        'network':       'ferry',
        'emissions_g_km': 0,
        'speed_kmh':      25,
        'routeable':      False,
    },

    # ── Aviation – ABSTRACT ───────────────────────────────────────
    'flight_domestic': {
        'network':       'air',
        'emissions_g_km': 255,
        'speed_kmh':      700,
        'routeable':      False,
    },
    'flight_electric': {
        'network':       'air',
        'emissions_g_km': 0,
        'speed_kmh':      400,
        'routeable':      False,
    },
}

# ─────────────────────────────────────────────────────────────────
# ROUTE FACTOR – multiply straight-line distance for abstract modes
# ─────────────────────────────────────────────────────────────────
ABSTRACT_ROUTE_FACTOR: Dict[str, float] = {
    'rail':  1.15,   # rail lines are ~15% longer than crow-flies
    'ferry': 1.05,   # sea routes are near-straight
    'air':   1.02,   # flight paths nearly direct
}

# ─────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────

def is_routeable(mode: str) -> bool:
    """Return True if this mode can be routed via OSMnx."""
    return MODES.get(mode, {}).get('routeable', False)


def get_network(mode: str) -> str:
    """Return the OSMnx network type for a routeable mode.

    For non-routeable modes returns the abstract network name
    (e.g. 'rail', 'ferry', 'air') – caller must check is_routeable().
    """
    return MODES.get(mode, {}).get('network', 'drive')


def abstract_distance_km(
    origin: Tuple[float, float],
    dest: Tuple[float, float],
    mode: str,
) -> float:
    """Compute synthetic route distance for a non-routable mode.

    Args:
        origin: (lat, lon) tuple
        dest:   (lat, lon) tuple
        mode:   mode string (must be non-routeable)

    Returns:
        Estimated route distance in km.
    """
    # NOTE: coordinate order is (lon, lat)
    lon1, lat1 = origin
    lon2, lat2 = dest
    # Haversine
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    straight_km = 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    network = get_network(mode)
    factor = ABSTRACT_ROUTE_FACTOR.get(network, 1.1)
    return straight_km * factor


def make_synthetic_route(
    origin: Tuple[float, float],
    dest: Tuple[float, float],
    mode: str,
) -> list:
    """Return a minimal 2-node 'route' for an abstract mode.

    The route contains the origin and destination as (lat, lon) tuples
    so that visualisation code can draw a straight line between them.
    The mode label carries the semantic information.

    Compatible with the existing route list convention used in
    BDIPlanner.actions_for() and visualiser/visualization.py.
    """
    # NOTE: always return a list of standard 2-tuples so is_valid_lonlat() and 
    # route_distance_km() can parse them without unpacking errors.
    return [tuple(origin), tuple(dest)]


def emissions_g_km(mode: str) -> float:
    """Return CO₂e grams per km for a mode (0 for zero-emission)."""
    return MODES.get(mode, {}).get('emissions_g_km', 0.0)


def speed_kmh(mode: str) -> float:
    """Return representative speed in km/h for a mode."""
    return MODES.get(mode, {}).get('speed_kmh', 50.0)


# ─────────────────────────────────────────────────────────────────
# CONVENIENCE SETS (used by FusedIdentity and BDIPlanner)
# ─────────────────────────────────────────────────────────────────
ROUTEABLE_MODES = frozenset(m for m, v in MODES.items() if v.get('routeable'))
ABSTRACT_MODES  = frozenset(m for m, v in MODES.items() if not v.get('routeable'))
ZERO_EMISSION   = frozenset(m for m, v in MODES.items() if v.get('emissions_g_km', 1) == 0)
FREIGHT_MODES   = frozenset({'van_electric', 'van_diesel', 'truck_electric', 'truck_diesel',
                              'hgv_electric', 'hgv_diesel', 'hgv_hydrogen', 'cargo_bike'})
PASSENGER_MODES = frozenset({'walk', 'bike', 'e_scooter', 'car', 'ev', 'bus', 'tram',
                              'local_train', 'intercity_train', 'ferry_diesel', 'ferry_electric',
                              'flight_domestic', 'flight_electric'})
