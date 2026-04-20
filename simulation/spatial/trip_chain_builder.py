from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple, Optional

from simulation.spatial.naptan_loader import (
    nearest_naptan_stop,
    RAIL_STOP_TYPES,
)
from simulation.config.modes import is_routeable
from simulation.spatial.trip_chain import TripLeg
from simulation.spatial.air_network import snap_to_airport
from simulation.spatial.ferry_network import snap_to_ferry_terminal


Coord = Tuple[float, float]


@dataclass
class TripChainBuilder:
    """
    Authoritative multimodal trip structure generator.

    Produces a *legal* sequence of TripLegs BEFORE routing is attempted.
    """

    env: any  # SpatialEnvironment
    fused_identity: any  # FusedIdentity

    # ─────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────
    def build(
        self,
        origin: Coord,
        destination: Coord,
        trunk_mode: str,
    ) -> List[TripLeg]:
        """
        Return an ordered list of TripLegs describing a *legal* trip.
        Raises ValueError if no legal structure exists.
        """

        if trunk_mode not in self.fused_identity.allowed_modes:
            raise ValueError(f"Mode {trunk_mode} not permitted by FusedIdentity")

        # Purely routeable mode (walk, bike, car, ev, etc.)
        if is_routeable(trunk_mode):
            return [
                TripLeg(
                    mode=trunk_mode,
                    path=[],
                    start=origin,
                    end=destination,
                )
            ]

        # Abstract trunk modes
        if trunk_mode in ("local_train", "intercity_train", "tram"):
            return self._build_rail_like(origin, destination, trunk_mode)

        if trunk_mode.startswith("ferry"):
            return self._build_ferry(origin, destination, trunk_mode)

        if trunk_mode.startswith("flight"):
            return self._build_air(origin, destination, trunk_mode)

        raise ValueError(f"Unsupported trunk mode: {trunk_mode}")

    # ─────────────────────────────────────────────────────────────
    # RAIL / TRAM (GTFS → NaPTAN fallback)
    # ─────────────────────────────────────────────────────────────
    def _build_rail_like(
        self,
        origin: Coord,
        destination: Coord,
        mode: str,
    ) -> List[TripLeg]:

        # 1. Try GTFS stops (if graph present)
        G_t = self.env.get_transit_graph()
        if G_t is not None:
            origin_stop = self.env.router.snap_to_transit_stop(origin, mode)
            dest_stop = self.env.router.snap_to_transit_stop(destination, mode)
        else:
            origin_stop = dest_stop = None

        # 2. Fallback to NaPTAN (authoritative)
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

        legs: List[TripLeg] = []

        # Access leg
        access_mode = self._pick_access_mode(origin)
        legs.append(
            TripLeg(
                mode=access_mode,
                path=[],
                start=origin,
                end=(origin_stop.lon, origin_stop.lat),
                transfer_point=origin_stop.common_name,
            )
        )

        # Trunk leg
        legs.append(
            TripLeg(
                mode=mode,
                path=[],
                start=(origin_stop.lon, origin_stop.lat),
                end=(dest_stop.lon, dest_stop.lat),
                transfer_point=f"{origin_stop.common_name} → {dest_stop.common_name}",
            )
        )

        # Egress leg
        egress_mode = self._pick_access_mode(destination)
        legs.append(
            TripLeg(
                mode=egress_mode,
                path=[],
                start=(dest_stop.lon, dest_stop.lat),
                end=destination,
                transfer_point=dest_stop.common_name,
            )
        )

        return legs

    # ─────────────────────────────────────────────────────────────
    # FERRY
    # ─────────────────────────────────────────────────────────────
    def _build_ferry(
        self, origin: Coord, destination: Coord, mode: str
    ) -> List[TripLeg]:

        G_f = self.env.get_ferry_graph()

        origin_term = snap_to_ferry_terminal(origin, G_f)
        dest_term = snap_to_ferry_terminal(destination, G_f)

        if origin_term is None or dest_term is None:
            raise ValueError("No ferry terminal found")

        o = G_f.nodes[origin_term]
        d = G_f.nodes[dest_term]

        access = self._pick_access_mode(origin)
        egress = self._pick_access_mode(destination)

        return [
            TripLeg(mode=access, path=[], start=origin, end=(o["x"], o["y"])),
            TripLeg(
                mode=mode,
                path=[],
                start=(o["x"], o["y"]),
                end=(d["x"], d["y"]),
            ),
            TripLeg(mode=egress, path=[], start=(d["x"], d["y"]), end=destination),
        ]

    # ─────────────────────────────────────────────────────────────
    # AIR
    # ─────────────────────────────────────────────────────────────
    def _build_air(
        self, origin: Coord, destination: Coord, mode: str
    ) -> List[TripLeg]:

        G_air = self.env.graph_manager.get_graph("air")

        orig_icao = snap_to_airport(origin, G_air)
        dest_icao = snap_to_airport(destination, G_air)

        if not orig_icao or not dest_icao:
            raise ValueError("No airport found")

        o = G_air.nodes[orig_icao]
        d = G_air.nodes[dest_icao]

        return [
            TripLeg(mode="car", path=[], start=origin, end=(o["x"], o["y"])),
            TripLeg(
                mode=mode,
                path=[],
                start=(o["x"], o["y"]),
                end=(d["x"], d["y"]),
            ),
            TripLeg(mode="car", path=[], start=(d["x"], d["y"]), end=destination),
        ]

    # ─────────────────────────────────────────────────────────────
    # UTILS
    # ─────────────────────────────────────────────────────────────
    def _pick_access_mode(self, coord: Coord) -> str:
        for m in self.fused_identity.access_modes:
            if is_routeable(m):
                return m
        return "walk"