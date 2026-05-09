"""
simulation/spatial/trip_planner.py

Multimodal trip planner for RTD_SIM.

ARCHITECTURE
────────────
This module implements the trip planning layer that was missing from RTD_SIM.
BDIPlanner evaluates modes; TripChainBuilder builds 3-leg transit chains.
Neither component can plan:

  • Multi-stop passenger journeys  (home → shops → gym → home)
  • Freight distribution runs      (depot → 12 delivery addresses → depot)
  • Intermodal freight             (van to hub → cargo bike last-mile)
  • Bus-as-freight scenarios       (parcel tray on tram, DfT trial)
  • Gig-economy delivery           (restaurant → A → B → C on e-scooter)

TripPlanner fills this gap.  It is the single entry point for any journey
that requires planning — from a simple A→B walk to a multi-day freight run.

DESIGN PRINCIPLES
─────────────────
1. Every trip is a TripPlan: an ordered list of TripLeg objects.
   A TripLeg has a mode, route geometry, payload (for freight), and dwell
   time (time spent at intermediate stops).

2. Passenger trips and freight trips share the same planner.  The difference
   is in the constraints passed in:
     - Passenger: time_budget, comfort, accessibility, carbon_limit
     - Freight:   payload_kg, payload_m3, time_windows, stop_priority,
                  vehicle_capacity, allowed_modes

3. Multi-stop sequencing uses nearest-neighbour with 2-opt improvement for
   freight delivery runs (TSP approximation).  For passenger trips with
   named waypoints the sequence is fixed by the user story.

4. Intermodal transfer points are resolved using the existing NaPTAN stop
   registry and GTFS transit graph — the same data sources as TripChainBuilder.
   The planner adds the concept of a TRANSFER NODE: a location where payload
   or person switches mode (e.g. van drops parcels at tram stop; parcels
   travel on tram; cargo bike picks up at destination tram stop).

5. Bus-as-freight: when allowed_modes includes bus/tram/rail for a freight
   agent, the planner uses the transit graph for the trunk leg and cargo
   bike or walking for last-mile delivery.  This enables DfT what-if analysis
   of public-transport-integrated freight.

INTEGRATION
───────────
  from simulation.spatial.trip_planner import TripPlanner, TripPlan, TripConstraints

  planner = TripPlanner(env)

  # Passenger: single destination
  plan = planner.plan(
      origin      = agent.state.location,
      destination = agent.state.destination,
      constraints = TripConstraints(persona='business_commuter', carbon_limit_g=500),
  )

  # Freight: multi-stop delivery run
  plan = planner.plan(
      origin      = depot_coord,
      destination = depot_coord,           # return to depot
      waypoints   = delivery_addresses,    # list of (lon, lat)
      constraints = TripConstraints(
          vehicle_type   = 'freight',
          payload_kg     = 120.0,
          time_windows   = {addr: (9*3600, 17*3600) for addr in delivery_addresses},
          allowed_modes  = ['van_diesel', 'cargo_bike', 'walk'],
          optimise_stops = True,           # reorder waypoints for efficiency
      ),
  )

  # Bus-as-freight (DfT what-if)
  plan = planner.plan(
      origin      = sorting_office_coord,
      destination = sorting_office_coord,
      waypoints   = parcel_addresses,
      constraints = TripConstraints(
          vehicle_type   = 'freight',
          payload_kg     = 30.0,           # within bus parcel tray limit
          allowed_modes  = ['tram', 'bus', 'walk'],
          carbon_limit_g = 100.0,          # force low-carbon routing
      ),
  )
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

Coord = Tuple[float, float]


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class TripConstraints:
    """
    Constraints and preferences for trip planning.

    Shared by passenger and freight trips.  Passenger-specific fields are
    ignored for freight and vice versa.
    """
    # ── Identity ──────────────────────────────────────────────────────────────
    persona: str = 'default'                # bdi_planner persona type
    vehicle_type: str = 'personal'          # 'personal' | 'freight' | 'transit'

    # ── Mode selection ────────────────────────────────────────────────────────
    allowed_modes: List[str] = field(default_factory=list)
    # Empty = all modes available to this persona/vehicle_type.
    # Explicit list restricts planning to those modes only — used for
    # freight scenarios where the operator specifies the fleet.
    preferred_mode: Optional[str] = None
    # If set, the planner will prefer this mode but still fall back to others
    # when it is unavailable or over-capacity.

    # ── Passenger constraints ─────────────────────────────────────────────────
    time_budget_s: float = float('inf')     # maximum total journey time (seconds)
    carbon_limit_g: float = float('inf')    # maximum CO₂e (grams)
    accessibility: bool = False             # require accessible vehicles/stops
    max_walk_km: float = 2.0               # maximum walking distance per leg

    # ── Freight constraints ───────────────────────────────────────────────────
    payload_kg: float = 0.0
    payload_m3: float = 0.0
    payload_type: str = 'general'           # 'parcel' | 'food' | 'refrigerated' | 'general'
    time_windows: Dict[Coord, Tuple[float, float]] = field(default_factory=dict)
    # Maps each waypoint coord to (earliest_arrival_s, latest_arrival_s)
    # relative to journey start.  Empty = no time constraints.
    optimise_stops: bool = False            # reorder waypoints for TSP efficiency
    return_to_origin: bool = False          # must return to origin (freight round-trip)

    # ── Intermodal transfer ───────────────────────────────────────────────────
    allow_mode_change: bool = True
    # When True, the planner may split the journey across multiple modes.
    # When False, a single mode is used throughout (useful for freight where
    # loading/unloading at every transfer point is impractical).

    max_transfers: int = 3
    # Maximum number of mode changes.  Set to 0 for direct journeys.


@dataclass
class TripLeg:
    """
    A single leg within a TripPlan.

    mode:          Transport mode string (e.g. 'bus', 'walk', 'cargo_bike').
    origin:        (lon, lat) start of this leg.
    destination:   (lon, lat) end of this leg.
    route:         Ordered list of (lon, lat) waypoints following the road/path.
    distance_km:   Estimated distance of this leg.
    duration_s:    Estimated travel time in seconds.
    emissions_g:   Estimated CO₂e in grams.
    dwell_s:       Time spent at destination before next leg begins (delivery
                   dwell, bus wait, interchange walk).
    payload_kg:    Payload carried on this leg (freight use).
    service_id:    GTFS route short name, if applicable.
    label:         Human-readable description for tooltip display.
    is_access:     True if this is a walk/bike access/egress leg.
    is_transfer:   True if this leg is an interchange walk between modes.
    """
    mode: str
    origin: Coord
    destination: Coord
    route: List[Coord] = field(default_factory=list)
    distance_km: float = 0.0
    duration_s: float = 0.0
    emissions_g: float = 0.0
    dwell_s: float = 0.0
    payload_kg: float = 0.0
    service_id: str = ''
    label: str = ''
    is_access: bool = False
    is_transfer: bool = False


@dataclass
class TripPlan:
    """
    Complete multimodal trip: an ordered list of TripLegs.

    A TripPlan is the output of TripPlanner.plan().  It replaces the
    current 'best.route' flat list that BDIPlanner returns, which cannot
    represent mode changes, dwell times, or intermediate stops.
    """
    legs: List[TripLeg] = field(default_factory=list)
    total_distance_km: float = 0.0
    total_duration_s: float = 0.0
    total_emissions_g: float = 0.0
    total_cost: float = 0.0
    feasible: bool = True
    rejection_reason: str = ''

    # Metadata
    origin: Optional[Coord] = None
    destination: Optional[Coord] = None
    waypoints: List[Coord] = field(default_factory=list)
    constraints: Optional[TripConstraints] = None

    def flat_route(self) -> List[Coord]:
        """
        Return the concatenated route geometry across all legs.

        Used when the downstream consumer (visualization, route_index tracking)
        expects a flat list of (lon, lat) waypoints.  Mode-change points are
        included once (not duplicated at leg boundaries).
        """
        coords: List[Coord] = []
        for leg in self.legs:
            if leg.route:
                if coords and leg.route[0] == coords[-1]:
                    coords.extend(leg.route[1:])
                else:
                    coords.extend(leg.route)
            elif leg.origin and leg.destination:
                if not coords:
                    coords.append(leg.origin)
                if leg.destination != coords[-1]:
                    coords.append(leg.destination)
        return coords

    def primary_mode(self) -> str:
        """Return the mode of the longest non-access, non-transfer leg."""
        trunk = [l for l in self.legs if not l.is_access and not l.is_transfer]
        if not trunk:
            return self.legs[0].mode if self.legs else 'walk'
        return max(trunk, key=lambda l: l.distance_km).mode

    def route_segments(self) -> List[Dict]:
        """
        Return route_segments in the format expected by visualization.py.

        Each segment dict matches the schema written by bdi_planner.py's
        TripChain routing block, so the existing visualiser works unchanged.
        """
        segs = []
        for leg in self.legs:
            if not leg.route:
                continue
            segs.append({
                'mode':             leg.mode,
                'coords':           leg.route,
                'distance_km':      leg.distance_km,
                'service_id':       leg.service_id,
                'label':            leg.label or leg.mode.replace('_', ' ').title(),
                'is_access':        leg.is_access,
                'is_transfer':      leg.is_transfer,
                'dwell_s':          leg.dwell_s,
                'payload_kg':       leg.payload_kg,
            })
        return segs


# ── TripPlanner ───────────────────────────────────────────────────────────────

class TripPlanner:
    """
    Multimodal trip planner.

    Plans journeys for passenger and freight agents across all registered
    transport networks: walk, bus (GTFS), tram, rail, ferry, drive, cycle.

    The planner is stateless — each call to plan() is independent.
    """

    # Emission factors g CO₂e/km (fallback when modes.py not available)
    _EMIT: Dict[str, float] = {
        'walk': 0, 'bike': 0, 'e_scooter': 0, 'cargo_bike': 0,
        'bus': 82, 'tram': 35, 'local_train': 41, 'intercity_train': 41,
        'car': 170, 'ev': 0, 'van_diesel': 150, 'van_electric': 0,
        'cargo_bike': 0, 'ferry_diesel': 115,
    }
    # Speed km/h (fallback)
    _SPEED: Dict[str, float] = {
        'walk': 5, 'bike': 15, 'e_scooter': 20, 'cargo_bike': 18,
        'bus': 30, 'tram': 25, 'local_train': 80, 'intercity_train': 150,
        'car': 50, 'ev': 50, 'van_diesel': 50, 'van_electric': 50,
        'ferry_diesel': 30,
    }
    # Payload capacity kg (0 = passenger mode, no freight)
    _CAPACITY_KG: Dict[str, float] = {
        'walk': 15, 'bike': 5, 'e_scooter': 5, 'cargo_bike': 100,
        'van_electric': 800, 'van_diesel': 1000,
        'truck_electric': 5000, 'truck_diesel': 10000,
        'bus': 500,          # parcel tray / DfT bus-as-freight trial
        'tram': 300,         # tram parcel tray
        'local_train': 2000, # rail parcels
    }

    def __init__(self, env: Any):
        self.env = env
        self._router = getattr(env, 'router', None)
        self._gm = getattr(env, 'graph_manager', None)

    # ── Public API ────────────────────────────────────────────────────────────

    def plan(
        self,
        origin: Coord,
        destination: Coord,
        waypoints: Optional[List[Coord]] = None,
        constraints: Optional[TripConstraints] = None,
    ) -> TripPlan:
        """
        Plan a trip from origin to destination, optionally via waypoints.

        For freight with optimise_stops=True, waypoints are reordered using
        nearest-neighbour TSP before routing.

        Returns a TripPlan.  If no feasible plan exists, TripPlan.feasible
        is False and TripPlan.rejection_reason explains why.
        """
        if constraints is None:
            constraints = TripConstraints()

        plan = TripPlan(
            origin      = origin,
            destination = destination,
            waypoints   = list(waypoints or []),
            constraints = constraints,
        )

        # ── Resolve stop sequence ─────────────────────────────────────────────
        stops = self._resolve_stop_sequence(origin, destination, waypoints, constraints)

        # ── Build legs between consecutive stops ──────────────────────────────
        all_legs: List[TripLeg] = []
        for i in range(len(stops) - 1):
            leg_origin = stops[i]
            leg_dest   = stops[i + 1]
            dwell_s    = self._stop_dwell(leg_dest, i, constraints)

            leg = self._plan_leg(
                leg_origin, leg_dest, constraints, dwell_s,
                stop_index=i, total_stops=len(stops) - 1,
            )
            if leg is None:
                plan.feasible = False
                plan.rejection_reason = (
                    f"No feasible route for leg {i+1}/{len(stops)-1}: "
                    f"{leg_origin} → {leg_dest}"
                )
                logger.warning("TripPlanner: %s", plan.rejection_reason)
                return plan
            all_legs.extend(leg if isinstance(leg, list) else [leg])

        plan.legs = all_legs
        plan.total_distance_km = sum(l.distance_km for l in all_legs)
        plan.total_duration_s  = sum(l.duration_s + l.dwell_s for l in all_legs)
        plan.total_emissions_g = sum(l.emissions_g for l in all_legs)
        plan.feasible = True

        # ── Constraint validation ─────────────────────────────────────────────
        if plan.total_duration_s > constraints.time_budget_s:
            plan.feasible = False
            plan.rejection_reason = (
                f"Total journey {plan.total_duration_s/60:.0f} min exceeds "
                f"time budget {constraints.time_budget_s/60:.0f} min"
            )
        if plan.total_emissions_g > constraints.carbon_limit_g:
            plan.feasible = False
            plan.rejection_reason = (
                f"Total emissions {plan.total_emissions_g:.0f} g CO₂e exceeds "
                f"carbon limit {constraints.carbon_limit_g:.0f} g"
            )

        return plan

    def plan_freight_run(
        self,
        depot: Coord,
        delivery_addresses: List[Coord],
        constraints: Optional[TripConstraints] = None,
    ) -> TripPlan:
        """
        Plan a full freight distribution run from depot, visiting all
        delivery addresses, and returning to depot.

        Convenience wrapper around plan() with return_to_origin=True and
        optimise_stops=True.  This is the entry point for:
          - Postal delivery rounds
          - Food delivery multi-drop
          - Van driver day route
          - Cargo bike last-mile (for electric-freight scenarios)
          - Bus-as-freight / tram-as-freight DfT trials
        """
        if constraints is None:
            constraints = TripConstraints(vehicle_type='freight')
        constraints.return_to_origin = True
        constraints.optimise_stops   = True

        all_stops = [depot] + delivery_addresses + [depot]
        return self.plan(
            origin      = depot,
            destination = depot,
            waypoints   = delivery_addresses,
            constraints = constraints,
        )

    # ── Stop sequencing ───────────────────────────────────────────────────────

    def _resolve_stop_sequence(
        self,
        origin: Coord,
        destination: Coord,
        waypoints: Optional[List[Coord]],
        constraints: TripConstraints,
    ) -> List[Coord]:
        """
        Return the ordered list of stops to visit.

        For passenger trips: [origin, *waypoints, destination]
        For freight with optimise_stops=True: TSP-optimised waypoint order.
        """
        if not waypoints:
            return [origin, destination]

        if not constraints.optimise_stops:
            return [origin] + list(waypoints) + [destination]

        # ── Nearest-neighbour TSP with 2-opt improvement ──────────────────────
        unvisited = list(waypoints)
        ordered   = [origin]
        current   = origin

        while unvisited:
            nearest = min(unvisited, key=lambda w: _haversine_km(current, w))
            ordered.append(nearest)
            unvisited.remove(nearest)
            current = nearest

        ordered.append(destination)

        # 2-opt improvement (single pass)
        improved = True
        while improved:
            improved = False
            for i in range(1, len(ordered) - 2):
                for j in range(i + 1, len(ordered) - 1):
                    before = (
                        _haversine_km(ordered[i-1], ordered[i])
                        + _haversine_km(ordered[j],   ordered[j+1])
                    )
                    after  = (
                        _haversine_km(ordered[i-1], ordered[j])
                        + _haversine_km(ordered[i],   ordered[j+1])
                    )
                    if after < before - 1e-9:
                        ordered[i:j+1] = ordered[i:j+1][::-1]
                        improved = True

        return ordered

    # ── Leg planning ──────────────────────────────────────────────────────────

    def _plan_leg(
        self,
        origin: Coord,
        destination: Coord,
        constraints: TripConstraints,
        dwell_s: float,
        stop_index: int,
        total_stops: int,
    ) -> Optional[List[TripLeg]]:
        """
        Plan a single leg.  May return multiple legs if an intermodal
        transfer is needed (e.g. walk to bus stop, ride bus, walk to delivery).

        Returns None if no feasible route exists.
        """
        dist_km = _haversine_km(origin, destination)

        # ── Choose mode for this leg ──────────────────────────────────────────
        mode = self._choose_mode(origin, destination, dist_km, constraints)
        if mode is None:
            return None

        # ── Route the leg ─────────────────────────────────────────────────────
        route = self._route_leg(origin, destination, mode, constraints)
        if route is None or len(route) < 2:
            # Try fallback to walk for short legs
            if dist_km <= constraints.max_walk_km:
                mode  = 'walk'
                route = self._route_leg(origin, destination, 'walk', constraints)
            if route is None or len(route) < 2:
                return None

        actual_dist = _route_distance_km(route)
        speed       = self._SPEED.get(mode, 30.0)
        duration_s  = (actual_dist / speed) * 3600.0
        emissions_g = actual_dist * self._EMIT.get(mode, 0.0)

        leg = TripLeg(
            mode        = mode,
            origin      = origin,
            destination = destination,
            route       = route,
            distance_km = actual_dist,
            duration_s  = duration_s,
            emissions_g = emissions_g,
            dwell_s     = dwell_s,
            payload_kg  = constraints.payload_kg,
            label       = self._leg_label(mode, stop_index, total_stops),
        )

        # ── Add access/egress walk legs for transit modes ─────────────────────
        if mode in ('bus', 'tram', 'local_train', 'intercity_train', 'ferry_diesel'):
            return self._wrap_with_access_egress(leg, origin, destination, constraints)

        return [leg]

    def _wrap_with_access_egress(
        self,
        trunk_leg: TripLeg,
        origin: Coord,
        destination: Coord,
        constraints: TripConstraints,
    ) -> List[TripLeg]:
        """
        Wrap a transit leg with walk access and egress legs.

        This is the correct structure for any transit journey:
          [walk to stop] → [ride transit] → [walk from stop]
        """
        legs: List[TripLeg] = []
        max_walk = constraints.max_walk_km

        # Access leg (origin → boarding stop)
        if trunk_leg.origin != origin:
            access_route = self._route_walk(origin, trunk_leg.origin, max_walk)
            if access_route and len(access_route) >= 2:
                d = _route_distance_km(access_route)
                legs.append(TripLeg(
                    mode        = 'walk',
                    origin      = origin,
                    destination = trunk_leg.origin,
                    route       = access_route,
                    distance_km = d,
                    duration_s  = (d / 5.0) * 3600,
                    is_access   = True,
                    label       = 'Walk to stop',
                ))

        legs.append(trunk_leg)

        # Egress leg (alighting stop → destination)
        if trunk_leg.destination != destination:
            egress_route = self._route_walk(trunk_leg.destination, destination, max_walk)
            if egress_route and len(egress_route) >= 2:
                d = _route_distance_km(egress_route)
                legs.append(TripLeg(
                    mode        = 'walk',
                    origin      = trunk_leg.destination,
                    destination = destination,
                    route       = egress_route,
                    distance_km = d,
                    duration_s  = (d / 5.0) * 3600,
                    is_access   = True,
                    label       = 'Walk from stop',
                    dwell_s     = trunk_leg.dwell_s,
                ))
            trunk_leg.dwell_s = 0.0  # dwell attributed to egress leg

        return legs

    # ── Mode selection ────────────────────────────────────────────────────────

    def _choose_mode(
        self,
        origin: Coord,
        dest: Coord,
        dist_km: float,
        c: TripConstraints,
    ) -> Optional[str]:
        """
        Select the best feasible mode for a leg given constraints.

        Priority for passenger: preferred_mode → transit → drive → walk/bike
        Priority for freight:   preferred_mode → allowed_modes in distance order
        """
        allowed = set(c.allowed_modes) if c.allowed_modes else None

        def _ok(mode: str) -> bool:
            if allowed is not None and mode not in allowed:
                return False
            if c.payload_kg > 0:
                cap = self._CAPACITY_KG.get(mode, 0.0)
                if cap < c.payload_kg:
                    return False
            return True

        # Explicit preference
        if c.preferred_mode and _ok(c.preferred_mode):
            return c.preferred_mode

        # Short trips: walk or bike
        if dist_km <= c.max_walk_km and _ok('walk'):
            return 'walk'
        if dist_km <= 5.0 and _ok('bike'):
            return 'bike'
        if dist_km <= 5.0 and _ok('cargo_bike') and c.payload_kg > 0:
            return 'cargo_bike'

        # Medium trips: bus/tram
        if dist_km <= 30.0:
            for m in ('tram', 'bus'):
                if _ok(m):
                    return m

        # Longer trips: rail/drive
        for m in ('local_train', 'intercity_train', 'ev', 'car',
                  'van_electric', 'van_diesel'):
            if _ok(m):
                return m

        # Very long: any allowed mode
        if allowed:
            for m in sorted(allowed):
                if _ok(m):
                    return m

        # Default fallback
        if _ok('walk'):
            return 'walk'
        if _ok('car'):
            return 'car'
        return None

    # ── Routing dispatch ──────────────────────────────────────────────────────

    def _route_leg(
        self,
        origin: Coord,
        dest: Coord,
        mode: str,
        constraints: TripConstraints,
    ) -> Optional[List[Coord]]:
        """
        Route a single leg using the appropriate network layer.

        Dispatches to:
          walk/bike/e_scooter → _route_walk (walk_footways or walk graph)
          bus/tram            → _route_transit (GTFS transit graph)
          local_train etc.    → router._compute_intermodal_route
          car/ev/van          → router._compute_road_route
          ferry               → router._compute_ferry_route
        """
        if self._router is None:
            return None

        agent_id = f"trip_planner_{mode}"

        try:
            if mode in ('walk', 'bike', 'e_scooter', 'cargo_bike'):
                return self._route_walk(origin, dest, constraints.max_walk_km)

            elif mode in ('bus', 'tram'):
                result = self._router.compute_route(agent_id, origin, dest, mode, {})
                return result if result and len(result) >= 2 else None

            elif mode in ('local_train', 'intercity_train', 'freight_rail'):
                result = self._router.compute_route(agent_id, origin, dest, mode, {})
                return result if result and len(result) >= 2 else None

            elif mode in ('car', 'ev', 'van_diesel', 'van_electric',
                          'truck_diesel', 'truck_electric'):
                result = self._router._compute_road_route(
                    agent_id, origin, dest, 'car', {}
                )
                return result if result and len(result) >= 2 else None

            elif mode in ('ferry_diesel', 'ferry_electric'):
                result = self._router.compute_route(agent_id, origin, dest, mode, {})
                return result if result and len(result) >= 2 else None

        except Exception as exc:
            logger.debug("TripPlanner._route_leg(%s): %s", mode, exc)

        return None

    def _route_walk(
        self,
        origin: Coord,
        dest: Coord,
        max_km: float = 2.0,
    ) -> Optional[List[Coord]]:
        """Route a walk leg using walk_footways → walk → None (no interpolation)."""
        if self._router is None:
            return None
        result = self._router._compute_access_leg(
            'trip_planner_walk', origin, dest, max_straight_km=max_km
        )
        # Return None rather than a straight-line fallback — the caller can
        # decide whether to accept a shorter leg or reject the route.
        if not result or len(result) < 2:
            return None
        return result

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _stop_dwell(
        self,
        stop: Coord,
        index: int,
        c: TripConstraints,
    ) -> float:
        """Return dwell time at a stop in seconds."""
        if c.time_windows and stop in c.time_windows:
            earliest, latest = c.time_windows[stop]
            return max(0.0, earliest)
        # Default dwell: 2 min for freight delivery, 0 for transit
        if c.vehicle_type == 'freight':
            return 120.0
        return 0.0

    def _leg_label(self, mode: str, index: int, total: int) -> str:
        name = mode.replace('_', ' ').title()
        if total <= 1:
            return name
        return f"{name} (stop {index+1}/{total})"


# ── Module-level helpers ──────────────────────────────────────────────────────

def _haversine_km(a: Coord, b: Coord) -> float:
    R  = 6371.0
    dp = math.radians(b[1] - a[1])
    dl = math.radians(b[0] - a[0])
    h  = (math.sin(dp/2)**2
          + math.cos(math.radians(a[1])) * math.cos(math.radians(b[1]))
          * math.sin(dl/2)**2)
    return 2 * R * math.atan2(math.sqrt(h), math.sqrt(1-h))


def _route_distance_km(route: List[Coord]) -> float:
    return sum(_haversine_km(route[i], route[i+1]) for i in range(len(route)-1))