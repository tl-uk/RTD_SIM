"""
simulation/routing/raptor_router.py

Lightweight RAPTOR-style transit router for RTD_SIM.

WHY RAPTOR, NOT DIJKSTRA
────────────────────────
Dijkstra on the GTFS transit multigraph cannot stay on one physical service.
Every stop pair shared by routes 7, 11, and 25 has a single merged edge with
route_short_names=['7','11','25'].  Dijkstra finds the globally cheapest path
through this graph and freely mixes services — riding route 11's edges for two
stops, switching to route 25's edges for three stops, switching back.  The
result is a journey that no real vehicle makes.

RAPTOR (Delling et al., ALENEX 2012) avoids this by never operating on a
graph at all.  Instead it works in rounds on *route ordered stop sequences*:

  Round 0  (direct, 0 transfers):
    Scan each route serving origin_stop.
    Does dest_stop appear later in this route's sequence?  If so record a
    direct journey.

  Round 1  (one transfer):
    For every stop reachable directly from origin on any single route,
    scan routes departing from that transfer stop.
    Does dest_stop appear later in any of those routes?  If so record the
    two-leg journey.

  Round 2+ are rarely needed for urban Edinburgh; the algorithm stops as
  soon as no new stops are marked or MAX_ROUNDS is reached.

RTD_SIM ADAPTATIONS
────────────────────
The BODS GTFS feed has no real-time timetable for the simulation clock, so
RTD_SIM uses a *frequency-based* cost model instead of departure times:

    cost(leg) = avg_travel_time_s + headway_s / 2   (expected wait)

This means "earliest arrival" collapses to "minimum generalised cost" and
the standard RAPTOR label τ_k(p) becomes a cost label rather than a time.

JOURNEY RESULT
──────────────
The router returns a ``RaptorJourney``: a list of ``RaptorLeg`` objects.
Each leg has a route short name and the ordered list of stop IDs.  Geometry
is assembled by the caller (Router._compute_gtfs_route) from the transit
graph edges.

USAGE
─────
    from simulation.routing.raptor_router import RaptorRouter
    rr = RaptorRouter(G_transit)
    journey = rr.route(origin_stop_id, dest_stop_id)
    if journey:
        for leg in journey.legs:
            print(leg.route, leg.stops)   # e.g. '25', ['stop_A', ..., 'stop_B']
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Maximum number of transfer rounds.  Round 0 = direct; round 1 = one transfer.
# Edinburgh bus network rarely needs >1 transfer for a single OD pair.
_MAX_ROUNDS = 2

# Walking-transfer footpath cost added when changing routes at the same stop
# (same physical stop, no walking — just wait for the next route).
_TRANSFER_PENALTY_S = 180.0   # 3 min default in-station transfer time


@dataclass
class RaptorLeg:
    """A single transit leg: board route at ``stops[0]``, alight at ``stops[-1]``."""
    route:       str              # route short name, e.g. '25'
    stops:       List[str]        # ordered list of stop IDs for this leg
    travel_s:    float = 0.0      # estimated in-vehicle time (seconds)
    headway_s:   float = 3600.0   # average headway for expected-wait calculation

    @property
    def board_stop(self) -> str:
        return self.stops[0]

    @property
    def alight_stop(self) -> str:
        return self.stops[-1]

    @property
    def n_stops(self) -> int:
        return len(self.stops)


@dataclass
class RaptorJourney:
    """A complete transit journey: one or more legs with 0 or more transfers."""
    legs:     List[RaptorLeg] = field(default_factory=list)
    cost_s:   float = 0.0          # total generalised cost in seconds

    @property
    def n_transfers(self) -> int:
        return max(0, len(self.legs) - 1)

    @property
    def all_stops(self) -> List[str]:
        """Flat list of all stop IDs visited, deduplicating transfer points."""
        result: List[str] = []
        for leg in self.legs:
            if result and result[-1] == leg.stops[0]:
                result.extend(leg.stops[1:])
            else:
                result.extend(leg.stops)
        return result


class RaptorRouter:
    """
    Frequency-based RAPTOR router for RTD_SIM.

    Constructed once per session from the built transit graph.  Thread-safe
    (read-only access to pre-built index structures after __init__).

    Args:
        G_transit:  The NetworkX MultiDiGraph produced by GTFSGraph.build().
                    Must have G.graph['route_stop_sequences'],
                    G.graph['stop_routes'], and G.graph['route_avg_times'].
    """

    def __init__(self, G_transit) -> None:
        self._G = G_transit

        # Pull pre-built index structures from the graph
        self._route_seqs:  Dict[str, List[List[str]]]           = (
            G_transit.graph.get('route_stop_sequences', {})
        )
        self._stop_routes: Dict[str, List[str]]                  = (
            G_transit.graph.get('stop_routes', {})
        )
        self._route_times: Dict[str, Dict[Tuple[str,str], float]] = (
            G_transit.graph.get('route_avg_times', {})
        )

        # Pre-build headway lookup from graph edges (stop_id_u, stop_id_v → headway_s)
        self._headways: Dict[Tuple[str,str], float] = {}
        if G_transit is not None:
            for u, v, edata in G_transit.edges(data=True):
                key = (u, v)
                if key not in self._headways:
                    self._headways[key] = float(edata.get('headway_s', 3600))

        if not self._route_seqs:
            logger.warning(
                "RaptorRouter: G_transit has no 'route_stop_sequences' — "
                "GTFSGraph was built without RAPTOR index.  "
                "Re-run GTFSGraph.build() with the updated gtfs_graph.py."
            )

    # ── Public API ────────────────────────────────────────────────────────────

    def route(
        self,
        origin_stop:  str,
        dest_stop:    str,
        mode_filter:  Optional[str] = None,
        max_rounds:   int = _MAX_ROUNDS,
    ) -> Optional[RaptorJourney]:
        """
        Find the lowest-cost journey from origin_stop to dest_stop.

        Round k finds journeys using exactly k transfers (k+1 routes).
        The algorithm stops as soon as no new stops are improved or
        max_rounds is reached.

        Transfer penalty
        ----------------
        In each round k > 0, a boarding penalty of _TRANSFER_PENALTY_S is
        added ONCE per leg at the boarding stop (not per intermediate stop).
        This correctly models the wait for the next vehicle after transferring.

        Boarding update ("catch an earlier trip")
        -----------------------------------------
        While scanning a route sequence forward, if a stop in the sequence
        has a BETTER (lower) cost label than the current boarding cost, the
        boarding point is advanced to that stop.  This is the RAPTOR
        "et(r, p)" optimisation: the rider catches the cheapest available
        boarding point along the route, not necessarily the first one.

        Args:
            origin_stop:  GTFS stop_id of the boarding point.
            dest_stop:    GTFS stop_id of the alighting point.
            mode_filter:  RTD_SIM mode string ('bus', 'tram', 'local_train').
                          None accepts any mode.
            max_rounds:   Maximum transfer rounds.  Round 0 = direct (0
                          transfers); round 1 = 1 transfer; round 2 = 2
                          transfers (3 buses).  Default _MAX_ROUNDS = 2.

        Returns:
            RaptorJourney or None when no path is found within max_rounds.
        """
        if not self._route_seqs:
            return None
        if origin_stop == dest_stop:
            return None
        if origin_stop not in self._stop_routes:
            logger.debug("RAPTOR: origin stop '%s' not in index", origin_stop)
            return None

        # cost_labels[stop_id] = best generalised cost (seconds) to reach stop.
        # Origin costs 0; everything else starts infinite.
        cost_labels: Dict[str, float] = {origin_stop: 0.0}

        # parent[stop_id] = the RaptorLeg used to reach this stop on the best
        # known path.  Overwritten whenever a cheaper path is found.
        parent: Dict[str, RaptorLeg] = {}

        # Stops improved in the PREVIOUS round — only routes touching these
        # need to be scanned in the current round (RAPTOR marking optimisation).
        marked: set = {origin_stop}

        best_journey: Optional[RaptorJourney] = None
        best_cost = float('inf')

        for round_k in range(max_rounds + 1):
            if not marked:
                break

            # ── Collect candidate routes ──────────────────────────────────────
            # For each marked stop, add the routes serving it to the candidate
            # set.  Store the earliest marked stop per route so we know where
            # to begin scanning the sequence (RAPTOR Fig. 1 optimisation).
            #
            # "Earliest" here means the marked stop that appears first in the
            # route's stop sequence — we resolve this during scanning below.
            candidate_routes: Dict[str, set] = {}   # route_name → {marked stops in route}
            for stop_id in marked:
                for rn in self._stop_routes.get(stop_id, []):
                    if mode_filter and not self._route_matches_mode(rn, mode_filter):
                        continue
                    if rn not in candidate_routes:
                        candidate_routes[rn] = set()
                    candidate_routes[rn].add(stop_id)

            new_marked: set = set()

            # ── Scan each candidate route ─────────────────────────────────────
            for route_name, route_marked_stops in candidate_routes.items():
                seqs = self._route_seqs.get(route_name, [])

                for seq in seqs:
                    # Find the index of the first stop in this sequence that
                    # (a) is in route_marked_stops AND (b) has a finite cost.
                    # This is where we may board; we scan forward from here.
                    board_idx = -1
                    for i, sid in enumerate(seq):
                        if (sid in route_marked_stops
                                and cost_labels.get(sid, math.inf) < math.inf):
                            board_idx = i
                            break
                    if board_idx < 0:
                        continue

                    # ── Boarding cost at the initial board stop ───────────────
                    # Transfer penalty is added ONCE here (if this is a
                    # connecting leg in round k > 0), not on every subsequent
                    # stop.  This correctly models waiting at the transfer stop
                    # for the next vehicle.
                    cur_board_idx  = board_idx
                    cur_board_cost = cost_labels.get(seq[board_idx], math.inf)
                    if round_k > 0:
                        cur_board_cost += _TRANSFER_PENALTY_S

                    # ── Forward scan ─────────────────────────────────────────
                    for idx in range(board_idx, len(seq)):
                        sid = seq[idx]

                        # ── "Catch an earlier trip" update ───────────────────
                        # If a stop along the route has a cheaper cost label
                        # than our current boarding cost (possibly because
                        # another route reached it more cheaply in a previous
                        # round), advance the boarding point here.
                        # This mirrors RAPTOR's et(r, p) update.
                        candidate_board = cost_labels.get(sid, math.inf)
                        if round_k > 0:
                            candidate_board += _TRANSFER_PENALTY_S
                        if candidate_board < cur_board_cost:
                            cur_board_cost = candidate_board
                            cur_board_idx  = idx

                        # The current boarding stop itself is not a destination.
                        if idx == cur_board_idx:
                            continue

                        # ── Compute arrival cost at sid ───────────────────────
                        leg_stops    = seq[cur_board_idx : idx + 1]
                        leg_travel_s = self._leg_cost(route_name, leg_stops)
                        arrival_cost = cur_board_cost + leg_travel_s

                        # Target pruning: don't update if we already know a
                        # better path to dest_stop (RAPTOR §3.1 pruning).
                        if arrival_cost >= best_cost:
                            continue

                        if arrival_cost < cost_labels.get(sid, math.inf):
                            cost_labels[sid] = arrival_cost
                            parent[sid] = RaptorLeg(
                                route     = route_name,
                                stops     = leg_stops,
                                travel_s  = leg_travel_s,
                                headway_s = self._headways.get(
                                    (seq[cur_board_idx], sid), 3600.0
                                ),
                            )
                            new_marked.add(sid)

                            if sid == dest_stop:
                                best_cost    = arrival_cost
                                best_journey = self._reconstruct(
                                    parent, dest_stop, arrival_cost
                                )

            marked = new_marked

        if best_journey:
            logger.debug(
                "RAPTOR %s→%s: %d leg(s), %d transfer(s), %.0fs cost",
                origin_stop, dest_stop,
                len(best_journey.legs),
                best_journey.n_transfers,
                best_journey.cost_s,
            )
        else:
            logger.debug(
                "RAPTOR: no path %s→%s (mode=%s, max_rounds=%d)",
                origin_stop, dest_stop, mode_filter, max_rounds,
            )
        return best_journey

    def routes_serving_stop(self, stop_id: str) -> List[str]:
        """Return the list of route short names serving a given stop."""
        return list(self._stop_routes.get(stop_id, []))

    def direct_route(self, origin_stop: str, dest_stop: str) -> Optional[str]:
        """
        Return the short name of any single route serving both stops in the
        correct order, or None if no direct route exists.

        Prefers routes where origin appears earlier relative to destination
        (shorter detour).
        """
        origin_routes = set(self._stop_routes.get(origin_stop, []))
        dest_routes   = set(self._stop_routes.get(dest_stop,   []))
        shared        = origin_routes & dest_routes

        best_rn, best_gap = None, float('inf')
        for rn in shared:
            for seq in self._route_seqs.get(rn, []):
                if origin_stop in seq and dest_stop in seq:
                    oi = seq.index(origin_stop)
                    di = seq.index(dest_stop)
                    if oi < di and (di - oi) < best_gap:
                        best_gap = di - oi
                        best_rn  = rn
        return best_rn

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _leg_cost(self, route_name: str, stop_seq: List[str]) -> float:
        """
        Compute the generalised cost (seconds) for riding route_name through
        the given stop sequence.

        cost = sum of avg_travel_time_s per segment + headway_s/2 (expected wait)
        """
        times = self._route_times.get(route_name, {})
        travel = 0.0
        for i in range(len(stop_seq) - 1):
            u, v    = stop_seq[i], stop_seq[i + 1]
            travel += times.get((u, v), 60.0)   # default 60s if not in index

        # Expected wait = headway / 2
        hw_key  = (stop_seq[0], stop_seq[1]) if len(stop_seq) > 1 else None
        headway = self._headways.get(hw_key, 3600.0) if hw_key else 3600.0
        return travel + headway / 2.0

    def _route_matches_mode(self, route_name: str, mode_filter: str) -> bool:
        """Check if a route's edges match the mode filter."""
        G = self._G
        if G is None:
            return True
        # Sample one edge for this route name — mode is stored on graph edges
        for _, _, edata in G.edges(data=True):
            if route_name in edata.get('route_short_names', []):
                return edata.get('mode', 'bus') == mode_filter
        return True   # default: allow if no edge found (mode unknown)

    def _reconstruct(
        self,
        parent:    Dict[str, RaptorLeg],
        dest_stop: str,
        cost:      float,
    ) -> RaptorJourney:
        """
        Walk parent pointers back from dest_stop to build the ordered leg list.

        Each stop has at most one parent leg (the best-cost leg that reached it).
        Walking back from dest_stop through leg.board_stop chains up the legs
        in reverse order; reversing the list gives the forward journey.

        Cycle guard: ``visited`` prevents infinite loops if the parent chain
        ever points back to a stop already seen (should not occur in a correct
        RAPTOR run, but guards against data anomalies).
        """
        legs:    List[RaptorLeg] = []
        current: str             = dest_stop
        visited: set             = set()

        while current in parent and current not in visited:
            visited.add(current)
            leg = parent[current]
            legs.append(leg)
            current = leg.board_stop

        legs.reverse()
        return RaptorJourney(legs=legs, cost_s=cost)
