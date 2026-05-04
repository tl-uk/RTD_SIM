"""
simulation/spatial/trip_chain_builder.py

Authoritative multimodal trip structure generator for RTD_SIM.

Converts a single trunk mode (e.g. 'local_train') into an ordered list of
TripLegs:

    access_leg  (walk / car / bus)
    trunk_leg   (tram / rail / ferry — anchored to physical infrastructure)
    egress_leg  (walk / bus / taxi)

This enforces the boarding / alighting semantics that were missing when the
router treated every mode as a flat polyline.  The leg *paths* contain only
the endpoint coordinates; actual route geometry is filled in by the caller
(bdi_planner.py) via env.compute_route_with_segments() for each leg.

CONTRACT with trip_chain.py
----------------------------
- TripLeg requires: mode, path, label
- path must have at least two points: [origin_coord, dest_coord]
- The caller replaces the stub path with real routed geometry.

Stop-snapping priority
-----------------------
1. Router.snap_to_transit_stop()  →  GTFS (platform accuracy) then NaPTAN
2. Direct NaPTAN query            →  DfT authoritative stop registry
3. ValueError raised              →  caller catches and skips this mode

FusedIdentity.access_modes compatibility
-----------------------------------------
If FusedIdentity does not define access_modes, __post_init__ adds it
from allowed_modes filtered to short-leg candidates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from simulation.config.modes import is_routeable
from simulation.spatial.naptan_loader import (
    nearest_naptan_stop,
    RAIL_STOP_TYPES,
    RAIL_ONLY_STOP_TYPES,
)
from simulation.spatial.trip_chain import TripLeg

logger = logging.getLogger(__name__)

Coord = Tuple[float, float]

_FERRY_STOP_TYPES = frozenset({'FER', 'FBT'})
# Edinburgh Trams uses MET in NaPTAN, not TMU — include both for portability
_TRAM_STOP_TYPES  = frozenset({'TMU', 'MET'})

# Maximum km from origin/dest to nearest stop before rejecting the mode
_MAX_STOP_SNAP_KM = 5.0


# ---------------------------------------------------------------------------
# FusedIdentity.access_modes compatibility
# ---------------------------------------------------------------------------

def _ensure_access_modes(fused_identity: Any) -> None:
    """Populate access_modes on FusedIdentity if missing or empty.

    FusedIdentity is a dataclass so hasattr() is always True — the check
    must also guard against an empty list, which means PersonaFusion didn't
    resolve any access candidates (common for transit-only personas whose
    job override sets access_modes=[] by default).
    """
    if fused_identity is None:
        return
    existing = getattr(fused_identity, 'access_modes', None)
    if existing:          # non-None AND non-empty — leave it
        return
    _CANDIDATES = ['walk', 'bike', 'e_scooter', 'bus',
                   'taxi_ev', 'taxi_diesel', 'car', 'ev']
    allowed = set(getattr(fused_identity, 'allowed_modes', []))
    fused_identity.access_modes = [m for m in _CANDIDATES if m in allowed] or ['walk']


# ---------------------------------------------------------------------------
# TripChainBuilder
# ---------------------------------------------------------------------------

@dataclass
class TripChainBuilder:
    """
    Build a list of TripLegs for a structured multimodal journey.

    The builder snaps origin/destination to physical infrastructure and
    returns leg stubs.  bdi_planner.actions_for() routes each stub through
    the appropriate graph to produce real geometry.
    """

    env:            Any   # SpatialEnvironment
    fused_identity: Any   # FusedIdentity | None

    def __post_init__(self) -> None:
        _ensure_access_modes(self.fused_identity)

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------

    def build(
        self,
        origin: Coord,
        destination: Coord,
        trunk_mode: str,
        agent_id: str = 'agent',
        context: Optional[Dict[str, Any]] = None,
    ) -> List[TripLeg]:
        """
        Return an ordered list of TripLeg stubs for a journey using trunk_mode.

        Args:
            origin:      (lon, lat) departure coordinate.
            destination: (lon, lat) arrival coordinate.
            trunk_mode:  Primary transport mode (e.g. 'local_train').
            agent_id:    For log messages only.
            context:     BDI agent context dict (passed through).

        Returns:
            Ordered list of TripLeg objects with two-point stub paths.

        Raises:
            ValueError: Mode not permitted, or no stop/terminal found.

        Dispatch order
        --------------
        Structured modes (rail/tram/ferry/air) are checked FIRST, before the
        is_routeable() short-circuit.  Phase 10b made local_train, tram, and
        ferry routeable=True in modes.py so that the BDI planner reaches the
        router rather than make_synthetic_route().  However TripChainBuilder
        must still enforce stop-snapping for these modes — the is_routeable()
        flag controls OSMnx graph access, not whether stop-snapping is needed.
        """
        allowed = getattr(getattr(self, 'fused_identity', None), 'allowed_modes', None)
        if allowed is not None and trunk_mode not in allowed:
            raise ValueError(
                f"Mode '{trunk_mode}' not in FusedIdentity.allowed_modes "
                f"for agent {agent_id}"
            )

        context = context or {}

        # ── Structured modes: always build access + trunk + egress legs ───────
        # Checked BEFORE is_routeable() because their routeable flag was changed
        # to True in Phase 10b; stop-snapping is still required regardless.
        if trunk_mode in ('local_train', 'intercity_train', 'freight_rail', 'tram'):
            return self._build_rail_like(origin, destination, trunk_mode, agent_id)

        if trunk_mode.startswith('ferry'):
            return self._build_ferry(origin, destination, trunk_mode, agent_id)

        if trunk_mode.startswith('flight'):
            return self._build_air(origin, destination, trunk_mode, agent_id)

        # ── Generic single-leg for any remaining routeable mode ───────────────
        if is_routeable(trunk_mode):
            return [TripLeg(
                mode=trunk_mode,
                path=[origin, destination],
                label=trunk_mode.replace('_', ' ').title(),
            )]

        raise ValueError(f"Unsupported trunk mode: {trunk_mode!r}")

    # ------------------------------------------------------------------
    # RAIL / TRAM
    # ------------------------------------------------------------------

    def _build_rail_like(
        self,
        origin: Coord,
        destination: Coord,
        mode: str,
        agent_id: str,
    ) -> List[TripLeg]:
        origin_coord = self._snap_stop(origin,      mode, agent_id, 'boarding')
        dest_coord   = self._snap_stop(destination, mode, agent_id, 'alighting')

        # Reject stops that are physically the same (different NaPTAN IDs,
        # same platform) or identical coords. Uses a 50m threshold — any
        # board→alight distance under 50m is effectively the same stop.
        try:
            from simulation.spatial.coordinate_utils import haversine_km as _hkm
            _board_alight_m = _hkm(origin_coord, dest_coord) * 1000
        except Exception:
            # Fallback: Euclidean proxy (degrees × 111km) — good enough for 50m check.
            _dx = (origin_coord[0] - dest_coord[0]) * 111320 * 0.64  # lon at ~56°N
            _dy = (origin_coord[1] - dest_coord[1]) * 111320
            _board_alight_m = (_dx**2 + _dy**2) ** 0.5
        if origin_coord == dest_coord or _board_alight_m < 50:
            raise ValueError(
                f"{mode} {agent_id}: boarding stop ≈ alighting stop "
                f"({_board_alight_m:.0f}m apart) — too close for a meaningful "
                f"trunk leg. Rejecting to prevent zero-distance route."
            )

        access_mode = self._pick_access_mode()
        egress_mode = self._pick_access_mode()

        logger.debug(
            "%s: %s  board=%s  alight=%s  access=%s  egress=%s",
            agent_id, mode, origin_coord, dest_coord, access_mode, egress_mode,
        )

        return [
            TripLeg(mode=access_mode,
                    path=[origin, origin_coord],
                    label=access_mode.replace('_', ' ').title()),
            TripLeg(mode=mode,
                    path=[origin_coord, dest_coord],
                    label=mode.replace('_', ' ').title()),
            TripLeg(mode=egress_mode,
                    path=[dest_coord, destination],
                    label=egress_mode.replace('_', ' ').title()),
        ]

    # ------------------------------------------------------------------
    # FERRY
    # ------------------------------------------------------------------

    def _build_ferry(
        self,
        origin: Coord,
        destination: Coord,
        mode: str,
        agent_id: str,
    ) -> List[TripLeg]:
        origin_coord = self._snap_ferry_terminal(origin,      agent_id, 'origin')
        dest_coord   = self._snap_ferry_terminal(destination, agent_id, 'dest')

        access_mode = self._pick_access_mode()
        egress_mode = self._pick_access_mode()

        return [
            TripLeg(mode=access_mode,
                    path=[origin, origin_coord],
                    label=access_mode.replace('_', ' ').title()),
            TripLeg(mode=mode,
                    path=[origin_coord, dest_coord],
                    label=mode.replace('_', ' ').title()),
            TripLeg(mode=egress_mode,
                    path=[dest_coord, destination],
                    label=egress_mode.replace('_', ' ').title()),
        ]

    # ------------------------------------------------------------------
    # AIR
    # ------------------------------------------------------------------

    def _build_air(
        self,
        origin: Coord,
        destination: Coord,
        mode: str,
        agent_id: str,
    ) -> List[TripLeg]:
        try:
            from simulation.spatial.air_network import snap_to_airport
            G_air = self.env.graph_manager.get_graph('air')
            o_id  = snap_to_airport(origin,      G_air)
            d_id  = snap_to_airport(destination, G_air)
            if o_id is None or d_id is None:
                raise ValueError("No airport found within range")
            o = G_air.nodes[o_id]
            d = G_air.nodes[d_id]
            origin_coord: Coord = (float(o['x']), float(o['y']))
            dest_coord:   Coord = (float(d['x']), float(d['y']))
        except Exception as exc:
            raise ValueError(f"Airport snap failed for {agent_id}: {exc}") from exc

        car = self._pick_access_mode(prefer='car')
        return [
            TripLeg(mode=car,  path=[origin, origin_coord],
                    label=car.replace('_', ' ').title()),
            TripLeg(mode=mode, path=[origin_coord, dest_coord],
                    label=mode.replace('_', ' ').title()),
            TripLeg(mode=car,  path=[dest_coord, destination],
                    label=car.replace('_', ' ').title()),
        ]

    # ------------------------------------------------------------------
    # STOP / TERMINAL SNAPPING
    # ------------------------------------------------------------------

    def _snap_stop(
        self,
        coord:    Coord,
        mode:     str,
        agent_id: str,
        role:     str,
    ) -> Coord:
        """
        Return (lon, lat) of the nearest stop for mode.

        Tier 1: Router.snap_to_transit_stop()  (GTFS + NaPTAN)
        Tier 2: Direct NaPTAN nearest_naptan_stop()
        Raises ValueError if nothing found within _MAX_STOP_SNAP_KM.
        """
        # Tier 1 — router (has GTFS + NaPTAN internally)
        router = getattr(self.env, 'router', None)
        if router is not None and hasattr(router, 'snap_to_transit_stop'):
            result = router.snap_to_transit_stop(
                coord, mode,
                max_distance_m=int(_MAX_STOP_SNAP_KM * 1000),
            )
            if result is not None:
                return result

        # Tier 2 — direct NaPTAN
        naptan = (
            getattr(getattr(self.env, 'graph_manager', None), 'naptan_stops', None)
            or getattr(self.env, 'naptan_stops', [])
        )
        if naptan:
            stop_types: Optional[frozenset]
            if mode == 'tram':
                stop_types = _TRAM_STOP_TYPES
            elif mode in ('ferry_diesel', 'ferry_electric'):
                stop_types = _FERRY_STOP_TYPES
            elif mode in ('local_train', 'intercity_train', 'freight_rail'):
                # CRITICAL: use RLY-only set, never MET (tram stops) or FER.
                # Edinburgh has 74 MET stops vs 20 RLY stops; without this
                # filter, rail agents snap to tram stops and the trunk leg
                # routing fails because the tram stop has no rail graph node.
                stop_types = RAIL_ONLY_STOP_TYPES
            else:
                stop_types = RAIL_STOP_TYPES

            hit = nearest_naptan_stop(
                coord, naptan,
                stop_types=stop_types,
                max_km=_MAX_STOP_SNAP_KM,
            )
            if hit is not None:
                return (hit.lon, hit.lat)

        raise ValueError(
            f"No {mode} {role} stop within {_MAX_STOP_SNAP_KM:.0f} km of "
            f"({coord[1]:.4f}N, {abs(coord[0]):.4f}W) — agent {agent_id}"
        )

    def _snap_ferry_terminal(
        self,
        coord:    Coord,
        agent_id: str,
        role:     str,
    ) -> Coord:
        """
        Return (lon, lat) of the nearest ferry terminal.

        Tier 1: snap_to_ferry_terminal() via ferry graph
        Tier 2: snap_to_transit_stop() with FER/FBT type filter
        Raises ValueError if nothing found.
        """
        # Tier 1 — ferry graph
        try:
            from simulation.spatial.ferry_network import snap_to_ferry_terminal
            G_ferry = (
                (getattr(self.env, 'get_ferry_graph', None) or (lambda: None))()
                or getattr(getattr(self.env, 'graph_manager', None),
                           'get_graph', lambda _: None)('ferry')
            )
            if G_ferry is not None:
                nid = snap_to_ferry_terminal(coord, G_ferry,
                                             max_km=_MAX_STOP_SNAP_KM)
                if nid is not None:
                    n = G_ferry.nodes[nid]
                    return (float(n['x']), float(n['y']))
        except Exception as _exc:
            logger.debug("Ferry terminal snap failed (%s): %s", agent_id, _exc)

        # Tier 2 — router NaPTAN with ferry stop types
        router = getattr(self.env, 'router', None)
        if router is not None and hasattr(router, 'snap_to_transit_stop'):
            result = router.snap_to_transit_stop(
                coord, 'ferry_diesel',
                max_distance_m=int(_MAX_STOP_SNAP_KM * 1000),
            )
            if result is not None:
                return result
            
        # Tier 3: transit_stop_loader — works for any city, no NaPTAN required
        try:
            from simulation.spatial.transit_stop_loader import load_transit_stops, nearest_stop as _nearest
            _mode_fam = (
                'tram'  if mode == 'tram' else
                'ferry' if mode in ('ferry_diesel', 'ferry_electric') else
                'rail'  if mode in ('local_train', 'intercity_train', 'freight_rail') else
                'bus'
            )
            _drive = getattr(getattr(self.env, 'graph_manager', None), 'get_graph', lambda _: None)('drive')
            if _drive is not None and len(_drive.nodes) > 0:
                _xs = [d['x'] for _,d in _drive.nodes(data=True)]
                _ys = [d['y'] for _,d in _drive.nodes(data=True)]
                _bbox = (max(_ys), min(_ys), max(_xs), min(_xs))
                _stops_d = load_transit_stops(_bbox, [_mode_fam])
                _stop = _nearest(_stops_d.get(_mode_fam, []), coord,
                                max_km=_MAX_STOP_SNAP_KM)
                if _stop is not None:
                    return (_stop.lon, _stop.lat)
        except Exception as _tsl_e:
            logger.debug("trip_chain_builder _snap_stop Tier 3 failed: %s", _tsl_e)

        raise ValueError(...)  # existing raise stays

        raise ValueError(
            f"No ferry terminal within {_MAX_STOP_SNAP_KM:.0f} km of "
            f"({coord[1]:.4f}N, {abs(coord[0]):.4f}W) — {agent_id} {role}"
        )

    # ------------------------------------------------------------------
    # ACCESS MODE SELECTION
    # ------------------------------------------------------------------

    def _pick_access_mode(self, prefer: str = 'walk') -> str:
        """
        Return the highest-priority routable access/egress mode.

        Iterates fused_identity.access_modes in declared order.
        Falls back to prefer ('walk' by default) if nothing matches.
        """
        fi = getattr(self, 'fused_identity', None)
        if fi is None:
            return prefer
        for m in getattr(fi, 'access_modes', []):
            if is_routeable(m):
                return m
        return prefer