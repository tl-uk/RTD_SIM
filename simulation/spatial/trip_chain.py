"""
simulation/spatial/trip_chain.py

Multimodal trip data model for RTD_SIM.

A single agent journey is modelled as a TripChain — an ordered list of
TripLegs.  Each leg records:
  - transport mode used
  - geometry (list of (lon, lat) waypoints)
  - start / end place names or coordinates
  - transfer points (stations, stops, ports, interchanges)
  - distance, estimated travel time, emissions

The TripChainPlanner builds realistic chains from origin to destination
using the BDI agent's mode preferences, infrastructure availability, and
the trip context extracted by ContextualPlanGenerator.

Design principles
-----------------
1. Every leg has a definite mode — never "unknown" or "mixed".
2. Walk legs between PT stages are first-class legs, not artefacts.
3. A chain is stored on AgentState and updated at every replan so the
   visualiser always has the current itinerary.
4. Chains are serialisable to dicts (JSON-safe) for logging and export.

Supported chain patterns (non-exhaustive)
------------------------------------------
  walk
  car
  bike → ferry → bike
  walk → tram → walk → bus → walk
  walk → local_train → walk
  car → ferry → car
  walk → bus → walk → intercity_train → walk → taxi_ev
  bike → local_train (bike on train) → bike
  walk → bus → walk → bus → walk
  ev → ferry → ev
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

# Modes that support carrying a bike (bike-on-board)
BIKE_PERMISSIVE_MODES = frozenset({
    'local_train', 'intercity_train', 'ferry_diesel', 'ferry_electric',
})

# Modes that end at a facility where onward modes are available
INTERCHANGE_MODES = frozenset({
    'local_train', 'intercity_train',
    'ferry_diesel', 'ferry_electric',
    'flight_domestic', 'flight_electric',
})

# Typical onward modes available from each interchange type
INTERCHANGE_ONWARD = {
    'rail_station':   ['walk', 'bus', 'tram', 'taxi_ev', 'taxi_diesel', 'car', 'ev', 'bike'],
    'ferry_terminal': ['walk', 'bus', 'taxi_ev', 'taxi_diesel', 'car', 'ev', 'bike'],
    'airport':        ['walk', 'bus', 'tram', 'taxi_ev', 'taxi_diesel', 'car', 'ev'],
    'tram_stop':      ['walk', 'bus', 'taxi_ev', 'taxi_diesel'],
    'bus_stop':       ['walk', 'tram', 'bus', 'taxi_ev'],
}

# Transfer walk threshold: legs shorter than this are "platform walk" and
# don't need to be shown as separate legs in the tooltip.
MIN_TRANSFER_WALK_KM = 0.15


# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TripLeg:
    """
    One leg of a multimodal journey.

    A leg is a continuous movement in a single transport mode between two
    distinct points (origin stop / interchange / final destination).
    """

    # Core identity
    mode:        str                           # e.g. 'walk', 'local_train', 'bus'
    path:        List[Tuple[float, float]]     # [(lon, lat), ...] ≥ 2 points
    label:       str                           # human-readable e.g. "ScotRail local train"

    # Place metadata (populated when available)
    origin_name:   str = ''    # start place name  e.g. "Edinburgh Waverley"
    dest_name:     str = ''    # end place name    e.g. "Haymarket"
    service_id:    str = ''    # GTFS route_id, train service code, etc.
    route_short_name: str = '' # GTFS route_short_name e.g. "23", "N3", "X47"
    stop_id:       str = ''    # GTFS stop_id or NaPTAN ATCO code at boarding

    # Transfer context
    is_transfer_walk: bool = False   # True if this walk leg is a platform/interchange transfer

    # Metrics (computed after routing)
    distance_km:   float = 0.0
    travel_time_min: float = 0.0
    emissions_g:   float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'mode':             self.mode,
            'path':             [[pt[0], pt[1]] for pt in self.path],
            'label':            self.label,
            'origin_name':      self.origin_name,
            'dest_name':        self.dest_name,
            'service_id':       self.service_id,
            'route_short_name': self.route_short_name,
            'stop_id':          self.stop_id,
            'is_transfer_walk': self.is_transfer_walk,
            'distance_km':      round(self.distance_km, 3),
            'travel_time_min':  round(self.travel_time_min, 1),
            'emissions_g':      round(self.emissions_g, 1),
        }

    @classmethod
    def from_segment(
        cls,
        seg: Dict[str, Any],
        origin_name: str = '',
        dest_name: str = '',
    ) -> 'TripLeg':
        """
        Build a TripLeg from a route_segment dict produced by the router.

        route_segment format: {'path': [(lon,lat),...], 'mode': str, 'label': str}
        """
        path = [(float(p[0]), float(p[1])) for p in seg.get('path', [])]
        mode = seg.get('mode', 'walk')
        dist = _path_km(path)
        # Extract bus/tram service number from label (e.g. "Bus 23") or from
        # dedicated route_short_name key set by the router service-name patch.
        _rsn = seg.get('route_short_name', '')
        if not _rsn:
            _label = seg.get('label', '')
            # Label format: "Bus 23" or "Tram N3" — extract trailing token
            _parts = _label.strip().split()
            if len(_parts) >= 2 and _parts[0].lower() in ('bus', 'tram'):
                _rsn = _parts[-1]
        return cls(
            mode=mode,
            path=path,
            label=seg.get('label', mode.replace('_', ' ').title()),
            origin_name=origin_name,
            dest_name=dest_name,
            route_short_name=_rsn,
            distance_km=dist,
            is_transfer_walk=(mode == 'walk' and dist < MIN_TRANSFER_WALK_KM),
        )


@dataclass
class TripChain:
    """
    Complete multimodal journey for one agent trip.

    Stores the ordered sequence of TripLegs from origin to final destination.
    Updated on every BDI replan so the visualiser always has current data.
    """

    # Top-level journey metadata
    origin:       Tuple[float, float]   # (lon, lat)
    destination:  Tuple[float, float]   # (lon, lat)
    origin_name:  str = ''
    dest_name:    str = ''

    # Ordered legs
    legs: List[TripLeg] = field(default_factory=list)

    # Journey-level metrics (computed from legs)
    total_distance_km:   float = 0.0
    total_time_min:      float = 0.0
    total_emissions_g:   float = 0.0

    # BDI context
    planned_at_step: int  = 0
    replan_count:    int  = 0

    def add_leg(self, leg: TripLeg) -> None:
        self.legs.append(leg)
        self._recompute_totals()

    def _recompute_totals(self) -> None:
        self.total_distance_km  = sum(l.distance_km   for l in self.legs)
        self.total_time_min     = sum(l.travel_time_min for l in self.legs)
        self.total_emissions_g  = sum(l.emissions_g   for l in self.legs)

    @property
    def modes(self) -> List[str]:
        """Return ordered list of transport modes used."""
        return [l.mode for l in self.legs]

    @property
    def primary_mode(self) -> str:
        """
        Return the dominant mode by distance (excluding walk legs).
        Falls back to first leg mode if all legs are walking.
        """
        non_walk = [(l.distance_km, l.mode) for l in self.legs if l.mode != 'walk']
        if non_walk:
            return max(non_walk, key=lambda x: x[0])[1]
        return self.legs[0].mode if self.legs else 'walk'

    @property
    def route_segments(self) -> List[Dict[str, Any]]:
        """
        Return route_segments list compatible with visualization.py.

        Each entry includes the full TripLeg.to_dict() payload so that
        visualization.py seg.get('distance_km'), seg.get('emissions_g'),
        seg.get('origin_name'), and seg.get('dest_name') all resolve.

        Previous version returned only {'path', 'mode', 'label'}, causing
        segment-level distance/emissions stats to always show as blank in
        the multimodal route tooltip.
        """
        return [
            leg.to_dict()
            for leg in self.legs
            if leg.path and len(leg.path) >= 2
        ]

    @property
    def flat_route(self) -> List[Tuple[float, float]]:
        """Return full route as a flat list of coordinates (all legs stitched)."""
        result: List[Tuple[float, float]] = []
        for leg in self.legs:
            if not leg.path:
                continue
            if result:
                result.extend(leg.path[1:])   # skip duplicate join point
            else:
                result.extend(leg.path)
        return result

    @property
    def transfer_points(self) -> List[Tuple[float, float]]:
        """Return the coordinates of all mode-change transfer points."""
        pts = []
        for i in range(1, len(self.legs)):
            prev, curr = self.legs[i - 1], self.legs[i]
            if prev.mode != curr.mode and prev.path:
                pts.append(prev.path[-1])
        return pts

    def summary(self) -> str:
        """Human-readable one-line summary."""
        chain_str = ' → '.join(self.modes)
        return (
            f"{self.origin_name or _fmt_coord(self.origin)} → "
            f"{self.dest_name or _fmt_coord(self.destination)}  "
            f"[{chain_str}]  "
            f"{self.total_distance_km:.1f}km  "
            f"{self.total_time_min:.0f}min  "
            f"{self.total_emissions_g:.0f}g CO₂"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'origin':             list(self.origin),
            'destination':        list(self.destination),
            'origin_name':        self.origin_name,
            'dest_name':          self.dest_name,
            'legs':               [l.to_dict() for l in self.legs],
            'modes':              self.modes,
            'primary_mode':       self.primary_mode,
            'total_distance_km':  round(self.total_distance_km, 3),
            'total_time_min':     round(self.total_time_min, 1),
            'total_emissions_g':  round(self.total_emissions_g, 1),
            'planned_at_step':    self.planned_at_step,
            'replan_count':       self.replan_count,
        }

    @classmethod
    def from_route_segments(
        cls,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        route_segments: List[Dict[str, Any]],
        origin_name: str = '',
        dest_name: str = '',
        planned_at_step: int = 0,
    ) -> 'TripChain':
        """
        Build a TripChain from the route_segments produced by the router.

        This is the primary constructor used by bdi_planner after a
        successful compute_route_with_segments() call.
        """
        chain = cls(
            origin=origin,
            destination=destination,
            origin_name=origin_name,
            dest_name=dest_name,
            planned_at_step=planned_at_step,
        )
        n = len(route_segments)
        for i, seg in enumerate(route_segments):
            o_name = origin_name if i == 0 else ''
            d_name = dest_name   if i == n - 1 else ''
            leg = TripLeg.from_segment(seg, origin_name=o_name, dest_name=d_name)
            chain.add_leg(leg)
        return chain


# ─────────────────────────────────────────────────────────────────────────────
# TRIP CHAIN PLANNER
# ─────────────────────────────────────────────────────────────────────────────

class TripChainPlanner:
    """
    Builds realistic multimodal TripChains given agent context.

    Called from bdi_planner when a full trip itinerary is needed.  The planner:

    1. Reads the agent's mode preferences, vehicle status, and trip context.
    2. Decides whether this is a single-mode or multimodal trip.
    3. For multimodal trips, selects an appropriate mode chain.
    4. Routes each leg via SpatialEnvironment.compute_route_with_segments().
    5. Returns a complete TripChain.

    Mode chain selection rules
    --------------------------
    The planner picks chains that are contextually sensible:

    * Bike + rail: the agent cycles to the station, boards with their bike,
      exits and cycles to the final destination.
      Precondition: bike_permissive_mode available + bike stored on params.

    * Walk + PT + walk: standard PT trip; walk legs are generated whenever
      the access/egress distance exceeds MIN_TRANSFER_WALK_KM.

    * Car + ferry + car: agent drives to terminal, crosses by ferry,
      continues driving.  Car must be available (vehicle_required or personal).

    * Walk + bus + walk + rail + walk: city bus to mainline station then rail.
      Triggered when rail station is > 1 km from origin but a bus stop is close.

    * Bus + bus + walk: sequential bus journeys without a rail connection.

    * Return trips: if the context marks this as a return journey the chain is
      mirrored (same modes, reversed leg order, swapped endpoints).
    """

    # Maximum walk distance to first PT stop before considering a bus connection
    MAX_WALK_TO_STOP_KM: float = 1.2

    # Threshold below which a PT service is considered "nearby"
    NEARBY_STOP_KM: float = 0.5

    def __init__(self, env: Any):
        """
        Args:
            env: SpatialEnvironment instance (for routing and stop lookup).
        """
        self.env = env

    def plan(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        preferred_modes: List[str],
        context: Dict[str, Any],
        step: int = 0,
    ) -> Optional[TripChain]:
        """
        Plan a complete multimodal trip.

        Args:
            agent_id:        For logging.
            origin:          (lon, lat) start coordinate.
            destination:     (lon, lat) end coordinate.
            preferred_modes: Ordered list from BDI planner (highest preference first).
            context:         Agent context dict (vehicle_required, bike_on_train, etc.)
            step:            Current simulation step.

        Returns:
            TripChain or None if no viable chain found.
        """
        from simulation.spatial.coordinate_utils import haversine_km
        dist_km = haversine_km(origin, destination)

        origin_name = context.get('origin_name', '')
        dest_name   = context.get('dest_name', '')

        # ── Choose chain pattern ──────────────────────────────────────────────
        chains_to_try = self._candidate_chains(
            preferred_modes, context, dist_km,
        )

        for chain_modes in chains_to_try:
            chain = self._route_chain(
                agent_id, origin, destination,
                chain_modes, context, step,
                origin_name=origin_name, dest_name=dest_name,
            )
            if chain is not None and chain.legs:
                logger.info(
                    "✅ %s: TripChain %s  %.1fkm  %d legs",
                    agent_id, chain.summary(), chain.total_distance_km, len(chain.legs),
                )
                return chain

        logger.warning("%s: no viable trip chain from %d candidate patterns", agent_id, len(chains_to_try))
        return None

    def _candidate_chains(
        self,
        preferred_modes: List[str],
        context: Dict[str, Any],
        dist_km: float,
    ) -> List[List[str]]:
        """
        Return ordered list of mode-chain candidates to try.

        Each candidate is a list of modes e.g. ['walk','bus','walk','local_train','walk'].
        The planner tries them in order and returns on the first success.
        """
        candidates: List[List[str]] = []
        has_bike    = 'bike' in preferred_modes
        has_car     = any(m in preferred_modes for m in ('car', 'ev', 'taxi_ev', 'taxi_diesel'))
        has_rail    = any(m in preferred_modes for m in ('local_train', 'intercity_train'))
        has_bus     = 'bus' in preferred_modes
        has_tram    = 'tram' in preferred_modes
        has_ferry   = any(m in preferred_modes for m in ('ferry_diesel', 'ferry_electric'))
        bike_on_train = context.get('bike_on_train', False) and has_bike and has_rail

        rail_mode  = 'intercity_train' if dist_km > 50 else 'local_train'
        ferry_mode = 'ferry_electric' if 'ferry_electric' in preferred_modes else 'ferry_diesel'
        car_mode   = next((m for m in ('ev', 'car') if m in preferred_modes), 'car')

        # Single-mode (always try first for short trips)
        for m in preferred_modes:
            candidates.append([m])

        # Bike + rail + bike (bike on board)
        if bike_on_train:
            candidates.append(['bike', rail_mode, 'bike'])

        # Walk + rail + walk (standard PT rail)
        if has_rail:
            candidates.append(['walk', rail_mode, 'walk'])

        # Walk + tram + walk
        if has_tram:
            candidates.append(['walk', 'tram', 'walk'])

        # Walk + bus + walk
        if has_bus:
            candidates.append(['walk', 'bus', 'walk'])

        # Walk + bus + walk + rail + walk (bus feeder to rail)
        if has_bus and has_rail and dist_km > 5:
            candidates.append(['walk', 'bus', 'walk', rail_mode, 'walk'])

        # Walk + tram + walk + bus + walk
        if has_tram and has_bus:
            candidates.append(['walk', 'tram', 'walk', 'bus', 'walk'])

        # Walk + bus + walk + tram + walk
        if has_bus and has_tram:
            candidates.append(['walk', 'bus', 'walk', 'tram', 'walk'])

        # Walk + bus + walk + bus + walk (two buses)
        if has_bus and dist_km > 8:
            candidates.append(['walk', 'bus', 'walk', 'bus', 'walk'])

        # Car + ferry + car
        if has_car and has_ferry:
            candidates.append([car_mode, ferry_mode, car_mode])

        # Walk + ferry + walk  (foot passenger)
        if has_ferry:
            candidates.append(['walk', ferry_mode, 'walk'])

        # Car + ferry + bus + walk (arrive without own vehicle at destination)
        if has_car and has_ferry and has_bus:
            candidates.append([car_mode, ferry_mode, 'bus', 'walk'])

        # Walk + rail + walk + bus + walk (arrive in city, take bus to final dest)
        if has_rail and has_bus and dist_km > 10:
            candidates.append(['walk', rail_mode, 'walk', 'bus', 'walk'])

        # Walk + rail + walk + tram + walk
        if has_rail and has_tram:
            candidates.append(['walk', rail_mode, 'walk', 'tram', 'walk'])

        return candidates

    def _route_chain(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        modes: List[str],
        context: Dict[str, Any],
        step: int,
        origin_name: str = '',
        dest_name: str = '',
    ) -> Optional[TripChain]:
        """
        Attempt to route a specific mode chain.

        For a chain like ['walk','bus','walk'] the planner:
        1. Snaps origin to the nearest bus stop.
        2. Routes walk leg from origin to stop.
        3. Routes bus from boarding stop to alighting stop nearest destination.
        4. Routes walk leg from alighting stop to final destination.

        For a single-mode chain ['ev'] it routes directly origin→destination.
        """
        from simulation.spatial.coordinate_utils import haversine_km

        if len(modes) == 1:
            return self._route_single(
                agent_id, origin, destination, modes[0], context, step,
                origin_name=origin_name, dest_name=dest_name,
            )

        # Multi-mode: route each leg between waypoints
        # For now use a simplified waypoint model: split at midpoint for
        # interchange modes, or snap to nearest stop for PT modes.
        chain = TripChain(
            origin=origin,
            destination=destination,
            origin_name=origin_name,
            dest_name=dest_name,
            planned_at_step=step,
        )

        waypoints = self._compute_waypoints(origin, destination, modes, context)
        if waypoints is None:
            return None

        for i, mode in enumerate(modes):
            leg_origin = waypoints[i]
            leg_dest   = waypoints[i + 1]

            # Skip trivially short legs
            if haversine_km(leg_origin, leg_dest) < 0.01:
                continue

            try:
                route, segs = self.env.compute_route_with_segments(
                    agent_id=f"{agent_id}_leg{i}_{mode}",
                    origin=leg_origin,
                    dest=leg_dest,
                    mode=mode,
                )
            except Exception as exc:
                logger.debug("%s: leg %d (%s) routing failed: %s", agent_id, i, mode, exc)
                return None

            if not route or len(route) < 2:
                logger.debug("%s: leg %d (%s) returned empty route", agent_id, i, mode)
                return None

            # Build TripLeg from segments (or flat route if no segments)
            if segs:
                for seg in segs:
                    leg = TripLeg.from_segment(seg)
                    leg.origin_name = origin_name if i == 0 else ''
                    leg.dest_name   = dest_name   if i == len(modes) - 1 else ''
                    chain.add_leg(leg)
            else:
                dist = haversine_km(leg_origin, leg_dest)
                chain.add_leg(TripLeg(
                    mode=mode,
                    path=route,
                    label=mode.replace('_', ' ').title(),
                    origin_name=origin_name if i == 0 else '',
                    dest_name=dest_name if i == len(modes) - 1 else '',
                    distance_km=dist,
                ))

        return chain if chain.legs else None

    def _route_single(
        self,
        agent_id: str,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        mode: str,
        context: Dict[str, Any],
        step: int,
        origin_name: str = '',
        dest_name: str = '',
    ) -> Optional[TripChain]:
        """Route a single-mode trip, returning a TripChain."""
        try:
            route, segs = self.env.compute_route_with_segments(
                agent_id=agent_id,
                origin=origin,
                dest=destination,
                mode=mode,
            )
        except Exception as exc:
            logger.debug("%s: single-mode %s routing failed: %s", agent_id, mode, exc)
            return None

        if not route or len(route) < 2:
            return None

        chain = TripChain(
            origin=origin,
            destination=destination,
            origin_name=origin_name,
            dest_name=dest_name,
            planned_at_step=step,
        )

        if segs:
            n = len(segs)
            for i, seg in enumerate(segs):
                leg = TripLeg.from_segment(seg)
                if i == 0:     leg.origin_name = origin_name
                if i == n - 1: leg.dest_name   = dest_name
                chain.add_leg(leg)
        else:
            from simulation.spatial.coordinate_utils import haversine_km
            chain.add_leg(TripLeg(
                mode=mode,
                path=route,
                label=mode.replace('_', ' ').title(),
                origin_name=origin_name,
                dest_name=dest_name,
                distance_km=haversine_km(origin, destination),
            ))

        return chain

    def _compute_waypoints(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        modes: List[str],
        context: Dict[str, Any],
    ) -> Optional[List[Tuple[float, float]]]:
        """
        Compute the ordered waypoints for a multi-mode chain.

        Returns a list of N+1 coordinates for N modes, or None if a
        required transfer point cannot be found.

        For simple walk+PT+walk patterns the waypoints are:
          [origin, nearest_boarding_stop, nearest_alighting_stop, destination]

        For more complex chains intermediate snapping is done per mode pair.
        """
        from simulation.spatial.coordinate_utils import haversine_km

        # Simple case: N legs → N+1 waypoints
        # Place intermediate waypoints at equal fractions along the great-circle
        n = len(modes)
        if n == 1:
            return [origin, destination]

        # For walk+PT+walk: snap to nearest PT stop
        pt_modes = [m for m in modes if m not in ('walk', 'bike')]
        if pt_modes:
            main_mode = pt_modes[0]
            # Try to snap origin/dest to nearest stop via GTFS or rail
            board_coord = self._nearest_stop_coord(origin,      main_mode)
            alight_coord = self._nearest_stop_coord(destination, main_mode)
            if board_coord and alight_coord:
                # Build waypoints from the snapped stops
                wps: List[Tuple[float, float]] = []
                for i, mode in enumerate(modes):
                    if i == 0:
                        wps.append(origin)
                    elif mode == main_mode and i == modes.index(main_mode):
                        wps.append(board_coord)
                    elif mode == 'walk' and i == modes.index(main_mode) + 1:
                        wps.append(alight_coord)
                wps.append(destination)
                if len(wps) == n + 1:
                    return wps

        # Fallback: evenly spaced waypoints along great circle
        wps = [origin]
        lon1, lat1 = origin
        lon2, lat2 = destination
        for i in range(1, n):
            frac = i / n
            wps.append((
                lon1 + frac * (lon2 - lon1),
                lat1 + frac * (lat2 - lat1),
            ))
        wps.append(destination)
        return wps

    def _nearest_stop_coord(
        self,
        coord: Tuple[float, float],
        mode: str,
    ) -> Optional[Tuple[float, float]]:
        """
        Return coordinates of the nearest stop for a given mode, or None.

        Priority:
          1. GTFS transit graph (most precise — platform-level accuracy)
          2. NaPTAN stop registry (DfT authoritative — RLY/TMU type filtered)
          3. None — TripChainPlanner falls back to equidistant waypoints

        The NaPTAN fallback is essential when GTFS is not loaded (no_GTFS runs).
        Without it the waypoint is computed from a great-circle fraction and the
        walk/access leg threads through buildings rather than along streets.
        """
        _RAIL_MODES  = frozenset({'local_train', 'intercity_train', 'freight_rail'})
        _TRAM_MODES  = frozenset({'tram'})

        # ── Tier 1: GTFS transit graph ────────────────────────────────────────
        try:
            G_transit = self.env.get_transit_graph()
            if G_transit is not None:
                from simulation.gtfs.gtfs_graph import GTFSGraph
                builder  = GTFSGraph(None)
                stop_id  = builder.nearest_stop(
                    G_transit, coord, mode_filter=mode, max_distance_m=5000
                )
                if stop_id:
                    node = G_transit.nodes.get(stop_id, {})
                    x = node.get('x')
                    y = node.get('y')
                    if x is not None and y is not None:
                        return (float(x), float(y))
        except Exception:
            pass

        # ── Tier 2: NaPTAN stop registry ─────────────────────────────────────
        # Used when GTFS is absent or returns nothing.  Filter by stop type:
        #   rail/intercity → RLY/RSE stops (National Rail stations)
        #   tram           → TMU stops (Edinburgh Trams, Metrolink etc.)
        try:
            naptan_stops = (
                getattr(self.env, 'naptan_stops', None)
                or getattr(getattr(self.env, 'graph_manager', None), 'naptan_stops', None)
                or []
            )
            if naptan_stops:
                from simulation.spatial.naptan_loader import (
                    nearest_naptan_stop,
                    RAIL_STOP_TYPES,
                )
                _TRAM_STOP_TYPES = frozenset({'TMU'})
                stop_types_filter = (
                    RAIL_STOP_TYPES if mode in _RAIL_MODES
                    else _TRAM_STOP_TYPES if mode in _TRAM_MODES
                    else None   # bus etc.: no type restriction
                )
                hit = nearest_naptan_stop(
                    coord,
                    naptan_stops,
                    stop_types=stop_types_filter,
                    max_km=2.0,
                )
                if hit is not None:
                    return (hit.lon, hit.lat)
        except Exception:
            pass

        return None


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _path_km(path: List[Tuple[float, float]]) -> float:
    """Haversine length of a path."""
    if len(path) < 2:
        return 0.0
    total = 0.0
    for i in range(len(path) - 1):
        lon1, lat1 = path[i]
        lon2, lat2 = path[i + 1]
        total += _haversine_km(lon1, lat1, lon2, lat2)
    return total


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    R = 6371.0
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a  = math.sin(dp / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _fmt_coord(c: Tuple[float, float]) -> str:
    return f"({c[1]:.4f}°N, {c[0]:.4f}°{'E' if c[0] >= 0 else 'W'})"