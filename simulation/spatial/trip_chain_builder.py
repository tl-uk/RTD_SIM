from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple, Any

from simulation.config.modes import is_routeable
from simulation.spatial.naptan_loader import (
    nearest_naptan_stop,
    RAIL_STOP_TYPES,
)
from simulation.spatial.trip_chain import TripLeg
from simulation.spatial.air_network import snap_to_airport
from simulation.spatial.ferry_network import snap_to_ferry_terminal

Coord = Tuple[float, float]


@dataclass
class TripChainBuilder:
    """
    Authoritative multimodal trip structure generator.

    CONTRACT (aligned with trip_chain.py):
    - TripLeg requires: mode, path, label
    - Geometry is defined ONLY by TripLeg.path
    - Leg start = path[0], leg end = path[-1]
    """

    env: Any              # SpatialEnvironment
    fused_identity: Any   # FusedIdentity

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------
    def build(
        self,
        origin: Coord,
        destination: Coord,
        trunk_mode: str,
    ) -> List[TripLeg]:
        if trunk_mode not in self.fused_identity.allowed_modes:
            raise ValueError(f"Mode '{trunk_mode}' not permitted by FusedIdentity")

        # --------------------------------------------------------------
        # Routeable single-leg modes (walk, bike, car, ev, etc.)
        # --------------------------------------------------------------
        if is_routeable(trunk_mode):
            return [
                TripLeg(
                    mode=trunk_mode,
                    path=[origin, destination],
                    label=trunk_mode.replace("_", " ").title(),
                )
            ]

        # --------------------------------------------------------------
        # Structured / abstract modes
        # --------------------------------------------------------------
        if trunk_mode in ("local_train", "intercity_train", "tram"):
            return self._build_rail_like(origin, destination, trunk_mode)

        if trunk_mode.startswith("ferry"):
            return self._build_ferry(origin, destination, trunk_mode)

        if trunk_mode.startswith("flight"):
            return self._build_air(origin, destination, trunk_mode)

        raise ValueError(f"Unsupported trunk mode: {trunk_mode}")

    # ------------------------------------------------------------------
    # RAIL / TRAM (GTFS → NaPTAN fallback)
    # ------------------------------------------------------------------
    def _build_rail_like(
        self,
        origin: Coord,
        destination: Coord,
        mode: str,
    ) -> List[TripLeg]:
        origin_stop = dest_stop = None

        # Prefer GTFS if present
        if self.env.get_transit_graph() is not None:
            origin_stop = self.env.router.snap_to_transit_stop(origin, mode)
            dest_stop = self.env.router.snap_to_transit_stop(destination, mode)

        # Fallback to NaPTAN
        if origin_stop is None or dest_stop is None:
            stops = self.env.graph_manager.naptan_stops
            if not stops:
                raise ValueError("No NaPTAN stops available")

            origin_stop = nearest_naptan_stop(
                origin, stops, stop_types=RAIL_STOP_TYPES
            )
            dest_stop = nearest_naptan_stop(
                destination, stops, stop_types=RAIL_STOP_TYPES
            )

        if origin_stop is None or dest_stop is None:
            raise ValueError("No valid boarding/alighting stop found")

        access_mode = self._pick_access_mode(origin)
        egress_mode = self._pick_access_mode(destination)

        return [
            TripLeg(
                mode=access_mode,
                path=[origin, (origin_stop.lon, origin_stop.lat)],
                label=access_mode.replace("_", " ").title(),
            ),
            TripLeg(
                mode=mode,
                path=[
                    (origin_stop.lon, origin_stop.lat),
                    (dest_stop.lon, dest_stop.lat),
                ],
                label=mode.replace("_", " ").title(),
            ),
            TripLeg(
                mode=egress_mode,
                path=[(dest_stop.lon, dest_stop.lat), destination],
                label=egress_mode.replace("_", " ").title(),
            ),
        ]

    # ------------------------------------------------------------------
    # FERRY
    # ------------------------------------------------------------------
    def _build_ferry(
        self,
        origin: Coord,
        destination: Coord,
        mode: str,
    ) -> List[TripLeg]:
        G = self.env.get_ferry_graph()
        o_id = snap_to_ferry_terminal(origin, G)
        d_id = snap_to_ferry_terminal(destination, G)

        if o_id is None or d_id is None:
            raise ValueError("No ferry terminal found")

        o = G.nodes[o_id]
        d = G.nodes[d_id]

        access_mode = self._pick_access_mode(origin)
        egress_mode = self._pick_access_mode(destination)

        return [
            TripLeg(
                mode=access_mode,
                path=[origin, (o["x"], o["y"])],
                label=access_mode.replace("_", " ").title(),
            ),
            TripLeg(
                mode=mode,
                path=[(o["x"], o["y"]), (d["x"], d["y"])],
                label=mode.replace("_", " ").title(),
            ),
            TripLeg(
                mode=egress_mode,
                path=[(d["x"], d["y"]), destination],
                label=egress_mode.replace("_", " ").title(),
            ),
        ]

    # ------------------------------------------------------------------
    # AIR
    # ------------------------------------------------------------------
    def _build_air(
        self,
        origin: Coord,
        destination: Coord,
        mode: str,
    ) -> List[TripLeg]:
        G = self.env.graph_manager.get_graph("air")
        o_id = snap_to_airport(origin, G)
        d_id = snap_to_airport(destination, G)

        if o_id is None or d_id is None:
            raise ValueError("No airport found")

        o = G.nodes[o_id]
        d = G.nodes[d_id]

        return [
            TripLeg(
                mode="car",
                path=[origin, (o["x"], o["y"])],
                label="Car",
            ),
            TripLeg(
                mode=mode,
                path=[(o["x"], o["y"]), (d["x"], d["y"])],
                label=mode.replace("_", " ").title(),
            ),
            TripLeg(
                mode="car",
                path=[(d["x"], d["y"]), destination],
                label="Car",
            ),
        ]

    # ------------------------------------------------------------------
    # UTILS
    # ------------------------------------------------------------------
    def _pick_access_mode(self, coord: Coord) -> str:
        for m in self.fused_identity.access_modes:
            if is_routeable(m):
                return m
        return "walk"