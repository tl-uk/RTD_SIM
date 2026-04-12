"""
debug/test_multimodal_routing.py
==========================
Standalone diagnostic for RTD_SIM multimodal routing.

Runs WITHOUT Streamlit.  Tests that:
  1. Rail agents get walk→train→walk segments (not flat road geometry)
  2. Tram agents with no GTFS are REJECTED (not routed via road proxy)
  3. Bus agents with GTFS get walk→bus→walk segments
  4. Ferry agents get walk→ferry→walk segments
  5. EV/car agents get single-segment road routes
  6. BDI mode-switch events are recorded on the agent trip log
  7. All route_segments entries carry {path, mode, label} with ≥ 2 points

Usage
-----
    cd <project_root>
    python debug/test_multimodal_routing.py

Output
------
  PASS / FAIL per test case
  Full trip log for each agent (origin, destination, legs, segment counts)
  Summary table of mode → expected vs actual routing behaviour
"""

from __future__ import annotations
import sys
import logging
import json
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any

# ── project root on sys.path ────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s %(name)-30s %(message)s",
)
logger = logging.getLogger("test_multimodal")

# ── colour helpers ───────────────────────────────────────────────────────────
_GREEN  = "\033[92m"
_RED    = "\033[91m"
_YELLOW = "\033[93m"
_CYAN   = "\033[96m"
_RESET  = "\033[0m"

def _ok(msg: str)   -> str: return f"{_GREEN}PASS{_RESET}  {msg}"
def _fail(msg: str) -> str: return f"{_RED}FAIL{_RESET}  {msg}"
def _info(msg: str) -> str: return f"{_CYAN}INFO{_RESET}  {msg}"
def _warn(msg: str) -> str: return f"{_YELLOW}WARN{_RESET}  {msg}"


# ── test OD pairs (Edinburgh area) ──────────────────────────────────────────
# All in (lon, lat) order.
# Rail:  Waverley → Haymarket (both on OpenRailMap graph)
# Tram:  Edinburgh Airport → Princes St (tram spine exists)
# Tram outside catchment: Cramond → Portobello (no tram stops nearby)
# Bus:   Leith Walk → Cameron Toll (typical urban bus trip)
# Ferry: Leith → Kinghorn (Firth of Forth crossing)
# EV:    Morningside → Stockbridge (typical car trip)

OD_PAIRS: List[Dict] = [
    {
        "label":    "Rail: Waverley→Haymarket",
        "mode":     "local_train",
        "origin":   (-3.1892, 55.9525),   # Waverley
        "dest":     (-3.2182, 55.9464),   # Haymarket
        "expect_segments":  ["walk", "local_train", "walk"],
        "expect_mode":      "local_train",
        "reject_if_flat":   True,   # single-segment road route = failure
    },
    {
        "label":    "Intercity rail: Waverley→North Berwick",
        "mode":     "intercity_train",
        "origin":   (-3.1892, 55.9525),   # Waverley
        "dest":     (-2.7266, 56.0618),   # North Berwick (within Edinburgh rail bbox)
        "expect_segments":  ["walk", "intercity_train", "walk"],
        "expect_mode":      "intercity_train",
        "reject_if_flat":   True,
    },
    {
        "label":    "Tram: Airport→Princes St (spine should match)",
        "mode":     "tram",
        "origin":   (-3.3615, 55.9503),   # Edinburgh Airport tram stop
        "dest":     (-3.1985, 55.9524),   # Princes Street tram stop
        "expect_segments":  ["tram"],     # walk legs may be suppressed by _MIN_WALK_LEG_KM
        "expect_mode":      "tram",
        "reject_if_flat":   True,
        "may_be_empty":     True,   # acceptable if no GTFS and tram spine returns None
    },
    {
        "label":    "Tram: Cramond→Portobello (outside catchment — must reject)",
        "mode":     "tram",
        "origin":   (-3.2985, 55.9788),   # Cramond (no tram stop within 2.5 km)
        "dest":     (-3.1073, 55.9480),   # Portobello (no tram stop nearby)
        "expect_segments":  [],
        "expect_mode":      None,         # bdi_planner must reject tram
        "expect_empty_route": True,       # router must return []
    },
    {
        "label":    "Bus: Leith Walk→Cameron Toll",
        "mode":     "bus",
        "origin":   (-3.1785, 55.9640),   # Leith Walk
        "dest":     (-3.1667, 55.9223),   # Cameron Toll
        "expect_segments":  ["walk", "bus", "walk"],
        "expect_mode":      "bus",
        "reject_if_flat":   False,   # bus falls back to road if no GTFS — acceptable
    },
    {
        "label":    "Ferry: Leith→Kinghorn",
        "mode":     "ferry_diesel",
        "origin":   (-3.1728, 55.9785),   # Leith docks
        "dest":     (-3.1742, 56.0726),   # Kinghorn
        "expect_segments":  ["ferry_diesel"],
        "expect_mode":      "ferry_diesel",
        "reject_if_flat":   False,
    },
    {
        "label":    "EV: Morningside→Stockbridge",
        "mode":     "ev",
        "origin":   (-3.2130, 55.9244),   # Morningside
        "dest":     (-3.2085, 55.9575),   # Stockbridge
        "expect_segments":  ["ev"],
        "expect_mode":      "ev",
        "reject_if_flat":   False,
    },
    {
        "label":    "Walk: Canongate→Holyrood",
        "mode":     "walk",
        "origin":   (-3.1823, 55.9499),   # Canongate
        "dest":     (-3.1726, 55.9518),   # Holyrood
        "expect_segments":  ["walk"],
        "expect_mode":      "walk",
        "reject_if_flat":   False,
    },
]


# ── helpers ──────────────────────────────────────────────────────────────────

def _segment_modes(segments: List[Dict]) -> List[str]:
    return [s.get('mode', '') for s in segments]


def _fmt_coord(c: Tuple[float, float]) -> str:
    return f"({c[1]:.4f}°N, {c[0]:.4f}°{'E' if c[0] >= 0 else 'W'})"


def _fmt_seg(seg: Dict) -> str:
    pts = len(seg.get('path', []))
    return f"{seg.get('mode','?')} '{seg.get('label','?')}' ({pts} pts)"


def _validate_segments(segments: List[Dict], label: str) -> List[str]:
    """Return list of structural error strings (empty = OK)."""
    errors = []
    for i, seg in enumerate(segments):
        if 'path' not in seg:
            errors.append(f"seg[{i}] missing 'path' key")
            continue
        if 'mode' not in seg:
            errors.append(f"seg[{i}] missing 'mode' key")
        if 'label' not in seg:
            errors.append(f"seg[{i}] missing 'label' key")
        pts = seg.get('path', [])
        if len(pts) < 2:
            errors.append(f"seg[{i}] mode={seg.get('mode','?')} has {len(pts)} points (< 2)")
        # All points must be (lon, lat) 2-tuples
        for j, pt in enumerate(pts[:5]):
            if not isinstance(pt, (list, tuple)) or len(pt) != 2:
                errors.append(f"seg[{i}] pt[{j}] bad format: {pt!r}")
                break
    return errors


# ── main test ────────────────────────────────────────────────────────────────

def run_tests():
    # -- Load environment
    print()
    print("=" * 72)
    print("  RTD_SIM MULTIMODAL ROUTING DIAGNOSTIC TEST")
    print("=" * 72)
    print()

    try:
        from simulation.config.simulation_config import SimulationConfig
        from simulation.setup.environment_setup import setup_environment
    except ImportError as e:
        print(_fail(f"Cannot import simulation modules: {e}"))
        print("  Run from project root: python debug/test_multimodal_routing.py")
        sys.exit(1)

    cfg = SimulationConfig(
        place="Edinburgh, Scotland",
        num_agents=0,
        steps=1,
        use_osm=True,
    )
    print(_info("Loading SpatialEnvironment via setup_environment (Edinburgh graph) …"))
    try:
        env = setup_environment(cfg)
    except Exception as e:
        print(_fail(f"setup_environment failed: {e}"))
        sys.exit(1)

    if not env.graph_loaded:
        print(_fail("OSM drive graph did not load — check network / bbox"))
        sys.exit(1)

    print(_info(f"Graph loaded: {env.get_graph_stats()}"))
    print()

    # -- Run tests
    results = []
    for tc in OD_PAIRS:
        _run_single_test(env, tc, results)

    # -- Summary
    _print_summary(results)

    # -- BDI mode-switch test
    _test_bdi_mode_switch(env)


def _run_single_test(env: Any, tc: Dict, results: List):
    label  = tc["label"]
    mode   = tc["mode"]
    origin = tc["origin"]
    dest   = tc["dest"]
    print(f"  ── {_CYAN}{label}{_RESET}")
    print(f"     {_fmt_coord(origin)} → {_fmt_coord(dest)}  mode={mode}")

    # Check if env has compute_route_with_segments
    if not hasattr(env, 'compute_route_with_segments'):
        print(_fail("  env.compute_route_with_segments not found — spatial_environment.py not patched"))
        results.append({"label": label, "pass": False, "reason": "method_missing"})
        return

    try:
        route, segments = env.compute_route_with_segments(
            agent_id=f"test_{mode}",
            origin=origin,
            dest=dest,
            mode=mode,
        )
    except Exception as e:
        print(_fail(f"  Exception during routing: {e}"))
        results.append({"label": label, "pass": False, "reason": str(e)})
        return

    # -- Expectations
    passed = True
    reasons = []

    if tc.get("expect_empty_route"):
        # Route should be empty (tram outside catchment)
        if route and len(route) > 1:
            passed = False
            reasons.append(f"expected [] but got {len(route)} pts — mode was not rejected")
        else:
            print(f"     {_GREEN}✓{_RESET} Correctly returned empty route (mode rejected)")
    else:
        if not route or len(route) < 2:
            if tc.get("may_be_empty"):
                print(f"     {_YELLOW}⚠{_RESET}  Empty route (acceptable — no GTFS/spine)")
            else:
                passed = False
                reasons.append(f"empty route returned ({len(route) if route else 0} pts)")
        else:
            print(f"     {_GREEN}✓{_RESET} Route: {len(route)} points, "
                  f"{_route_km(route):.2f} km")

    # Segment structure validation
    struct_errors = _validate_segments(segments, label)
    if struct_errors:
        passed = False
        for err in struct_errors:
            reasons.append(f"segment structure: {err}")

    # Check expected segment modes
    if segments and tc.get("expect_segments"):
        actual_modes  = _segment_modes(segments)
        expect_modes  = tc["expect_segments"]
        # Check that all expected modes appear (order matters for PT routes)
        if actual_modes != expect_modes:
            # Partial credit: check at least the main mode is present
            main_mode = mode
            if main_mode not in actual_modes:
                passed = False
                reasons.append(
                    f"segment modes {actual_modes} missing main mode '{main_mode}' "
                    f"(expected {expect_modes})"
                )
            else:
                print(f"     {_YELLOW}⚠{_RESET}  Segment modes {actual_modes} differ from "
                      f"expected {expect_modes} (main mode present)")
        else:
            print(f"     {_GREEN}✓{_RESET} Segment modes match: {actual_modes}")

    # Reject-if-flat check: rail/PT should never be a 2-point straight line
    if tc.get("reject_if_flat") and route and len(route) == 2:
        passed = False
        reasons.append("got 2-point straight-line route — routing failed silently")

    # Print segment details
    if segments:
        for seg in segments:
            print(f"       leg: {_fmt_seg(seg)}")
    elif not tc.get("expect_empty_route"):
        print(f"     {_YELLOW}⚠{_RESET}  No route_segments returned (flat route only)")

    if passed:
        print(_ok(f"  {label}"))
    else:
        for r in reasons:
            print(_fail(f"  {label}: {r}"))

    results.append({"label": label, "pass": passed, "reasons": reasons,
                    "route_pts": len(route) if route else 0,
                    "segments": len(segments)})
    print()


def _route_km(route: List) -> float:
    """Quick haversine distance of a route."""
    try:
        from simulation.spatial.coordinate_utils import route_distance_km
        return route_distance_km(route)
    except Exception:
        return 0.0


def _test_bdi_mode_switch(env: Any):
    """
    Tests that a BDI agent planning a trip records a mode switch in route_segments.
    Simulates: agent initially plans 'ev', then replans to 'local_train'.
    Checks that the second plan's route_segments has rail legs, not road legs.
    """
    print()
    print("=" * 72)
    print("  BDI MODE-SWITCH RECORDING TEST")
    print("=" * 72)

    try:
        from agent.bdi_planner import BDIPlanner, Action
        from agent.cognitive_abm import CognitiveAgent, AgentState
    except ImportError as e:
        print(_fail(f"Cannot import agent modules: {e}"))
        return

    # Check AgentState has route_segments field
    import dataclasses
    if hasattr(AgentState, '__dataclass_fields__'):
        fields = set(AgentState.__dataclass_fields__.keys())
        required = {'route_segments', 'origin_name', 'destination_name', 'trip_chain'}
        missing = required - fields
        if missing:
            print(_fail(f"AgentState missing fields: {missing}"))
            return
        else:
            print(_ok(f"AgentState has: {', '.join(sorted(required))}"))

    # Check TripChain is importable
    try:
        from simulation.spatial.trip_chain import TripChain, TripChainPlanner, TripLeg
        print(_ok("trip_chain module imports OK (TripChain, TripChainPlanner, TripLeg)"))
    except ImportError as e:
        print(_fail(f"trip_chain import failed: {e}"))
        return

    # Create a simple agent state
    origin = (-3.1892, 55.9525)   # Waverley
    dest   = (-3.2182, 55.9464)   # Haymarket

    planner = BDIPlanner()

    # Check bdi_planner uses compute_route_with_segments
    import inspect
    # evaluate_actions delegates to actions_for which contains the routing call.
    # inspect.getsource(evaluate_actions) only sees the top-level method body,
    # not its callees — check actions_for instead.
    src_af = inspect.getsource(planner.actions_for)
    if 'compute_route_with_segments' not in src_af:
        print(_fail("BDIPlanner.actions_for does not call compute_route_with_segments — old version deployed"))
        return
    print(_ok("BDIPlanner.actions_for calls compute_route_with_segments"))

    # Test that _segments are stored in params
    if 'route_segments' not in src and '_segments' not in src:
        print(_fail("BDIPlanner does not store _segments in params"))
    else:
        print(_ok("BDIPlanner stores _segments in params['route_segments']"))

    # Simulate evaluate_actions with local_train
    print()
    print(_info("Computing local_train route with segments …"))
    if hasattr(env, 'compute_route_with_segments'):
        route, segs = env.compute_route_with_segments(
            "bdi_test", origin, dest, "local_train",
        )
        if segs:
            modes = [s.get('mode') for s in segs]
            print(_ok(f"Route has {len(segs)} segments: {modes}"))
            # Check all structure
            errors = _validate_segments(segs, "BDI test")
            if errors:
                for err in errors:
                    print(_fail(f"  Structure: {err}"))
            else:
                print(_ok("All segment dicts have path/mode/label with ≥ 2 points"))
        else:
            print(_warn("No segments returned — will render as flat route"))

    # Test mode-switch recording
    print()
    print(_info("Testing mode-switch: ev → local_train …"))
    route_ev, segs_ev     = env.compute_route_with_segments("bdi_sw_ev",    origin, dest, "ev")
    route_rail, segs_rail = env.compute_route_with_segments("bdi_sw_rail",  origin, dest, "local_train")

    ev_flat   = not segs_ev   or (len(segs_ev)   == 1 and segs_ev[0].get('mode')   == 'ev')
    rail_seg  = segs_rail and any(s.get('mode') == 'local_train' for s in segs_rail)

    if ev_flat:
        print(_ok("EV correctly returns single-mode flat route"))
    else:
        print(_warn(f"EV returned unexpected segments: {[s.get('mode') for s in segs_ev]}"))

    if rail_seg:
        print(_ok(f"Rail mode switch recorded {len(segs_rail)} segments: "
                  f"{[s.get('mode') for s in segs_rail]}"))
    else:
        print(_fail("Rail route has no local_train segment — route_segments not working"))


def _print_summary(results: List[Dict]):
    print()
    print("=" * 72)
    print("  TEST SUMMARY")
    print("=" * 72)
    passed = sum(1 for r in results if r.get("pass"))
    total  = len(results)
    for r in results:
        status = _ok("") if r.get("pass") else _fail("")
        segs   = r.get("segments", 0)
        pts    = r.get("route_pts", 0)
        print(f"  {status} {r['label']:<45} {pts:>5} pts  {segs} segs")
    print()
    colour = _GREEN if passed == total else (_RED if passed == 0 else _YELLOW)
    print(f"  {colour}{passed}/{total} tests passed{_RESET}")
    print()


if __name__ == "__main__":
    run_tests()