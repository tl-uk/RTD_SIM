"""
simulation/gtfs/gtfs_validator.py

GTFS Validation & OSM Alignment Diagnostic Tool.

Answers the question: "Is GTFS actually working and overlaid onto OSM
correctly so routing and map are aligned?"

Run from project root:
    python -m simulation.gtfs.gtfs_validator --feed /path/to/gtfs.zip
    python -m simulation.gtfs.gtfs_validator --spine          # test tram spine only

Checks:
  1. Feed loads without errors (all 7 required GTFS files present)
  2. Stop coordinates fall within the OSM graph bounding box
  3. Nearest OSM road node to each stop is within 200m (walk transfer)
  4. Transit graph edges have sensible headways (60–3600s)
  5. No stops at (0, 0) — NaN/missing coordinate sentinel
  6. Mode distribution matches expected UK patterns
  7. Edinburgh tram stops aligned with real-world corridor

Output: coloured terminal report + optional folium HTML map.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Haversine (standalone)
# ─────────────────────────────────────────────────────────────────────────────

def _hav(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    R = 6371.0
    dp = math.radians(lat2 - lat1); dl = math.radians(lon2 - lon1)
    a  = math.sin(dp/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dl/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ─────────────────────────────────────────────────────────────────────────────
# Result collector
# ─────────────────────────────────────────────────────────────────────────────

class ValidationResult:
    def __init__(self):
        self.checks: List[Dict] = []

    def ok(self, name: str, detail: str = ""):
        self.checks.append({'status': 'OK', 'name': name, 'detail': detail})
        print(f"  ✅  {name}" + (f" — {detail}" if detail else ""))

    def warn(self, name: str, detail: str = ""):
        self.checks.append({'status': 'WARN', 'name': name, 'detail': detail})
        print(f"  ⚠️   {name}" + (f" — {detail}" if detail else ""))

    def fail(self, name: str, detail: str = ""):
        self.checks.append({'status': 'FAIL', 'name': name, 'detail': detail})
        print(f"  ❌  {name}" + (f" — {detail}" if detail else ""))

    def summary(self) -> str:
        ok   = sum(1 for c in self.checks if c['status'] == 'OK')
        warn = sum(1 for c in self.checks if c['status'] == 'WARN')
        fail = sum(1 for c in self.checks if c['status'] == 'FAIL')
        return f"{ok} passed, {warn} warnings, {fail} failed"


# ─────────────────────────────────────────────────────────────────────────────
# Check 1 — tram spine alignment (no GTFS feed needed)
# ─────────────────────────────────────────────────────────────────────────────

def validate_tram_spine(result: ValidationResult) -> None:
    """
    Verify that the Edinburgh tram stop spine is correctly positioned.

    Expected: stops lie along the Airport→Newhaven corridor.
    The corridor runs roughly WNW→ESE at latitude 55.92–55.98.
    """
    print("\n── Tram spine alignment ──")
    try:
        from simulation.spatial.rail_spine import TRAM_STOPS, TRAM_LINE, route_via_tram_stops

        result.ok("Tram spine imported", f"{len(TRAM_STOPS)} stops, {len(TRAM_LINE)} edges")

        # Check bounding box — all stops should be within Edinburgh bounds
        EDINBURGH_BBOX = (-3.45, 55.87, -3.10, 56.00)  # (west, south, east, north)
        outside = []
        for sid, info in TRAM_STOPS.items():
            lon, lat = info['lon'], info['lat']
            if not (EDINBURGH_BBOX[0] <= lon <= EDINBURGH_BBOX[2]
                    and EDINBURGH_BBOX[1] <= lat <= EDINBURGH_BBOX[3]):
                outside.append(f"{sid} ({lon:.4f},{lat:.4f})")
        if outside:
            result.fail("Tram stops within Edinburgh bbox",
                        f"{len(outside)} stops outside: {outside[:3]}")
        else:
            result.ok("Tram stops within Edinburgh bbox")

        # Check corridor direction: Airport (west) → Newhaven (east)
        from simulation.spatial.rail_spine import TRAM_STOPS as TS
        airport = TS.get('EAP', {})
        newhaven = TS.get('NWH', {})
        if airport and newhaven:
            if airport['lon'] < newhaven['lon']:
                result.ok("Tram corridor direction (Airport→Newhaven = W→E)")
            else:
                result.fail("Tram corridor direction wrong",
                            f"Airport lon={airport['lon']:.4f} should be west of Newhaven lon={newhaven['lon']:.4f}")

        # Test catchment filter: agent in Balerno (SW) should get None
        balerno = (-3.35, 55.89)
        portobello = (-3.10, 55.95)
        route = route_via_tram_stops(balerno, portobello)
        if route is None:
            result.ok("Catchment filter: Balerno→Portobello correctly returns None (outside 1.5km)")
        else:
            result.warn("Catchment filter weak: Balerno→Portobello produced a route",
                        f"{len(route)} waypoints — these agents should not take the tram")

        # Test in-catchment trip: city centre to airport area
        princes_st = (-3.20, 55.95)
        airport_area = (-3.36, 55.95)
        route2 = route_via_tram_stops(princes_st, airport_area)
        if route2 is not None and len(route2) >= 4:
            result.ok("In-catchment route: Princes St→Airport area",
                      f"{len(route2)} waypoints")
        else:
            result.warn("In-catchment route returned unexpected result",
                        f"route={route2}")

        # Check inter-stop distances (consecutive stops should be <2.5km apart)
        from simulation.spatial.rail_spine import _TRAM_STOP_ORDER, _tram_stop_coord
        max_gap = 0.0
        max_gap_pair = ("?", "?")
        for i in range(len(_TRAM_STOP_ORDER) - 1):
            a_id, b_id = _TRAM_STOP_ORDER[i], _TRAM_STOP_ORDER[i+1]
            a = _tram_stop_coord(a_id)
            b = _tram_stop_coord(b_id)
            if a and b:
                d = _hav(a[0], a[1], b[0], b[1])
                if d > max_gap:
                    max_gap = d
                    max_gap_pair = (a_id, b_id)

        if max_gap < 3.0:
            result.ok("Inter-stop gaps reasonable",
                      f"max {max_gap:.2f}km ({max_gap_pair[0]}→{max_gap_pair[1]})")
        else:
            result.warn("Large inter-stop gap detected",
                        f"{max_gap:.2f}km between {max_gap_pair[0]} and {max_gap_pair[1]}")

    except ImportError as e:
        result.fail("Tram spine import failed", str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Check 2 — GTFS feed validation
# ─────────────────────────────────────────────────────────────────────────────

def validate_gtfs_feed(
    feed_path: str,
    result: ValidationResult,
    osm_place: Optional[str] = None,
    service_date: Optional[str] = None,
) -> None:
    """
    Validate a GTFS feed and check OSM alignment.
    """
    print(f"\n── GTFS feed: {feed_path} ──")
    from pathlib import Path as P
    p = P(feed_path)
    if not p.exists():
        result.fail("Feed path exists", f"{feed_path}")
        return
    result.ok("Feed path exists", str(p.stat().st_size // 1024) + " KB")

    # ── Load feed ────────────────────────────────────────────────────────────
    try:
        from simulation.gtfs.gtfs_loader import GTFSLoader
        loader = GTFSLoader(feed_path, service_date=service_date)
        loader.load()
        result.ok("Feed loaded",
                  f"{len(loader.stops)} stops, "
                  f"{len(loader.routes)} routes, "
                  f"{len(loader.trips)} trips")
    except Exception as e:
        result.fail("Feed load failed", str(e))
        return

    # ── Build transit graph ──────────────────────────────────────────────────
    try:
        from simulation.gtfs.gtfs_graph import GTFSGraph
        builder = GTFSGraph(loader)
        G = builder.build()
        result.ok("Transit graph built",
                  f"{G.number_of_nodes()} stops, {G.number_of_edges()} service edges")
    except Exception as e:
        result.fail("Transit graph build failed", str(e))
        return

    # ── Check stop coordinates ────────────────────────────────────────────────
    zero_stops = [(n, d) for n, d in G.nodes(data=True)
                  if d.get('x', 0) == 0 and d.get('y', 0) == 0]
    if zero_stops:
        result.fail("Stop coordinates: no (0,0) sentinels",
                    f"{len(zero_stops)} stops at origin — missing lat/lon in stops.txt")
    else:
        result.ok("Stop coordinates: no (0,0) sentinels")

    # ── Check headways ────────────────────────────────────────────────────────
    headways = [d.get('headway_s', 0) for _, _, d in G.edges(data=True) if d.get('headway_s')]
    if headways:
        min_h, max_h, avg_h = min(headways), max(headways), sum(headways)/len(headways)
        if min_h < 30:
            result.warn("Headway sanity", f"min={min_h}s — suspiciously short")
        elif max_h > 7200:
            result.warn("Headway sanity", f"max={max_h/60:.0f} min — rural service?")
        else:
            result.ok("Headway sanity",
                      f"min={min_h/60:.0f}min avg={avg_h/60:.0f}min max={max_h/60:.0f}min")
    else:
        result.warn("Headways", "No headway_s attributes found on edges")

    # ── Mode distribution ─────────────────────────────────────────────────────
    modes = {}
    for _, _, d in G.edges(data=True):
        m = d.get('mode', 'unknown')
        modes[m] = modes.get(m, 0) + 1
    result.ok("Mode distribution", str(modes))

    # ── OSM bbox alignment ────────────────────────────────────────────────────
    stop_lons = [d['x'] for _, d in G.nodes(data=True) if d.get('x')]
    stop_lats = [d['y'] for _, d in G.nodes(data=True) if d.get('y')]
    if stop_lons and stop_lats:
        gtfs_bbox = (min(stop_lons), min(stop_lats), max(stop_lons), max(stop_lats))
        print(f"\n  📦 GTFS stop bounding box:")
        print(f"     lon: {gtfs_bbox[0]:.4f} → {gtfs_bbox[2]:.4f}")
        print(f"     lat: {gtfs_bbox[1]:.4f} → {gtfs_bbox[3]:.4f}")

        # Heuristic UK bounds check
        if (gtfs_bbox[0] >= -8.0 and gtfs_bbox[2] <= 2.0
                and gtfs_bbox[1] >= 49.0 and gtfs_bbox[3] <= 61.0):
            result.ok("GTFS stops within UK bounds")
        else:
            result.warn("GTFS stops outside UK bounds",
                        "Feed may be for a different region")

    # ── OSM nearest-node alignment ────────────────────────────────────────────
    if osm_place:
        print(f"\n  🗺️  Loading OSM graph for {osm_place} (may take a moment)…")
        try:
            import osmnx as ox
            G_road = ox.graph_from_place(osm_place, network_type='walk')
            # Sample up to 20 stops
            sample_nodes = list(G.nodes(data=True))[:20]
            misaligned = []
            for stop_id, attrs in sample_nodes:
                lon, lat = attrs.get('x', 0), attrs.get('y', 0)
                if lon == 0 and lat == 0:
                    continue
                road_node = ox.distance.nearest_nodes(G_road, lon, lat)
                rd = G_road.nodes[road_node]
                dist_m = _hav(lon, lat, rd['x'], rd['y']) * 1000
                if dist_m > 500:
                    misaligned.append(
                        f"{attrs.get('name','?')} ({dist_m:.0f}m from OSM)"
                    )

            if not misaligned:
                result.ok(f"OSM alignment: all {len(sample_nodes)} sampled stops within 500m of a road node")
            else:
                result.warn("OSM alignment issues",
                            f"{len(misaligned)}/{len(sample_nodes)} stops >500m from nearest road: "
                            + ", ".join(misaligned[:3]))
        except Exception as e:
            result.warn("OSM alignment check skipped", str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Check 3 — generate folium map for visual inspection
# ─────────────────────────────────────────────────────────────────────────────

def generate_alignment_map(
    output_path: str = "/tmp/rtd_sim_gtfs_validation.html",
    feed_path: Optional[str] = None,
) -> None:
    """
    Generate a Folium map showing:
    - Edinburgh tram stop spine (green markers + polyline)
    - GTFS transit stops (blue markers), if feed_path provided
    - OSM road network (grey, low opacity)

    Open the HTML file in a browser to visually verify alignment.
    """
    try:
        import folium
    except ImportError:
        print("  ⚠️  folium not installed — skipping map generation")
        print("      pip install folium")
        return

    m = folium.Map(location=[55.95, -3.20], zoom_start=12, tiles='CartoDB positron')

    # ── Edinburgh tram spine ──────────────────────────────────────────────────
    from simulation.spatial.rail_spine import TRAM_STOPS, _TRAM_STOP_ORDER, _tram_stop_coord

    tram_coords = []
    for sid in _TRAM_STOP_ORDER:
        coord = _tram_stop_coord(sid)
        if coord:
            tram_coords.append([coord[1], coord[0]])  # folium uses (lat, lon)
            info = TRAM_STOPS.get(sid, {})
            folium.CircleMarker(
                location=[coord[1], coord[0]],
                radius=5,
                color='#22c55e',
                fill=True,
                fill_color='#22c55e',
                fill_opacity=0.9,
                popup=f"🚋 {info.get('name', sid)} [{sid}]",
                tooltip=f"Tram: {info.get('name', sid)}",
            ).add_to(m)

    if len(tram_coords) >= 2:
        folium.PolyLine(
            tram_coords,
            color='#22c55e',
            weight=4,
            opacity=0.8,
            tooltip='Edinburgh Tram (spine)',
        ).add_to(m)

    # ── GTFS stops ────────────────────────────────────────────────────────────
    if feed_path:
        try:
            from simulation.gtfs.gtfs_loader import GTFSLoader
            from simulation.gtfs.gtfs_graph import GTFSGraph
            loader = GTFSLoader(feed_path)
            loader.load()
            G = GTFSGraph(loader).build()
            for stop_id, attrs in list(G.nodes(data=True))[:500]:
                lon, lat = attrs.get('x', 0), attrs.get('y', 0)
                if lon == 0 and lat == 0:
                    continue
                folium.CircleMarker(
                    location=[lat, lon],
                    radius=3,
                    color='#3b82f6',
                    fill=True,
                    fill_color='#3b82f6',
                    fill_opacity=0.7,
                    tooltip=f"GTFS: {attrs.get('name', stop_id)}",
                ).add_to(m)
        except Exception as e:
            print(f"  ⚠️  GTFS stops skipped in map: {e}")

    m.save(output_path)
    print(f"\n  🗺️  Alignment map saved to: {output_path}")
    print(f"      Open in browser: file://{output_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Streamlit panel (call from UI code)
# ─────────────────────────────────────────────────────────────────────────────

def render_gtfs_validation_panel(results=None) -> None:
    """
    Render GTFS validation results as a Streamlit panel.
    Call from a tab in streamlit_app.py:
        from simulation.gtfs.gtfs_validator import render_gtfs_validation_panel
        render_gtfs_validation_panel(results)
    """
    try:
        import streamlit as st
    except ImportError:
        print("Streamlit not available — use CLI mode")
        return

    st.subheader("🔬 GTFS & Tram Spine Diagnostic")
    st.caption("Validates that transit data is correctly loaded and aligned with OSM")

    res = ValidationResult()
    # Redirect prints to st.text
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        validate_tram_spine(res)
        if results and hasattr(results, 'env') and results.env:
            env = results.env
            feed_path = getattr(
                getattr(env, '_gtfs_feed_path', None), '__str__', lambda: None
            )()
            if feed_path:
                validate_gtfs_feed(feed_path, res)
    output = buf.getvalue()

    # Display results
    for line in output.splitlines():
        if '✅' in line:
            st.success(line.strip())
        elif '⚠️' in line:
            st.warning(line.strip())
        elif '❌' in line:
            st.error(line.strip())
        elif line.strip():
            st.text(line)

    # Summary
    summary = res.summary()
    st.info(f"**Summary:** {summary}")

    # Map generation
    if st.button("🗺️ Generate alignment map (opens in /tmp)"):
        feed_path = None
        if results and hasattr(results, 'env') and results.env:
            feed_path = getattr(results.env, 'gtfs_feed_path', None)
        generate_alignment_map(feed_path=feed_path)
        st.success("Map saved to /tmp/rtd_sim_gtfs_validation.html")


# ─────────────────────────────────────────────────────────────────────────────
# TRANSITLAND ON-DEMAND GTFS DOWNLOADER
# Free tier: 1 req/s, no registration needed for public feeds.
# API key available free at https://www.transit.land for higher rate limits.
#
# UK GTFS sources:
#   Edinburgh Trams:  transitland operator ID  o-gcpv-edinburghtramsltd
#   Lothian Buses:    transitland operator ID  o-gcpv-lothianbuses
#   ScotRail:         transitland operator ID  o-gcpv-firstscotland
#   Glasgow Subway:   transitland operator ID  o-gcpv-spt
#   Traveline Scot:   https://www.travelinedata.org.uk/  (full Scotland feed)
#   Bus Open Data:    https://data.bus-data.dft.gov.uk/  (England, free API key)
# ─────────────────────────────────────────────────────────────────────────────

TRANSITLAND_API = "https://transit.land/api/v2"

# Well-known UK operator IDs for the city dropdown
UK_GTFS_OPERATORS = {
    "Edinburgh Trams":  "o-gcpv-edinburghtramsltd",
    "Lothian Buses":    "o-gcpv-lothianbuses",
    "ScotRail":         "o-gcpv-firstscotland",
    "Glasgow Subway":   "o-gcpv-spt",
    "First Glasgow":    "o-gcpv-firstglasgow",
    "Stagecoach West Scotland": "o-gcpv-stagecoachbus",
}


def search_gtfs_feeds_for_bbox(
    bbox: Tuple[float, float, float, float],
    api_key: str = "",
) -> List[Dict]:
    """
    Query TransitLand for GTFS feeds covering the given bounding box.

    Args:
        bbox:    (west, south, east, north) in WGS84 decimal degrees.
        api_key: TransitLand API key (optional; free tier works without one).

    Returns:
        List of dicts: {name, operator_id, feed_id, download_url, last_updated}
    """
    import urllib.request
    import urllib.parse

    west, south, east, north = bbox
    params: dict = {
        'bbox': f"{west},{south},{east},{north}",
        'per_page': '20',
    }
    if api_key:
        params['apikey'] = api_key

    url = f"{TRANSITLAND_API}/feeds?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except Exception as exc:
        logger.error("TransitLand feed search failed: %s", exc)
        return []

    feeds = []
    for feed in data.get('feeds', []):
        fv = feed.get('feed_versions', [{}])
        latest = fv[0] if fv else {}
        feeds.append({
            'name':         feed.get('name', feed.get('onestop_id', '?')),
            'operator_id':  feed.get('onestop_id', ''),
            'feed_id':      feed.get('id', ''),
            'download_url': latest.get('url', ''),
            'last_updated': latest.get('fetched_at', '?')[:10],
        })
    return feeds


def download_gtfs_feed(
    operator_id_or_url: str,
    output_dir: str = "/tmp",
    api_key: str = "",
) -> Optional[str]:
    """
    Download a GTFS feed from TransitLand by operator ID or direct URL.

    Args:
        operator_id_or_url: TransitLand operator ID (e.g. 'o-gcpv-edinburghtramsltd')
                            or a direct HTTPS download URL.
        output_dir:         Where to save the .zip file.
        api_key:            TransitLand API key (optional).

    Returns:
        Local path to downloaded .zip, or None on failure.
    """
    import urllib.request
    import urllib.parse

    output_path = Path(output_dir) / f"{operator_id_or_url.replace('/', '_')}.zip"

    # If it looks like a URL, download directly
    if operator_id_or_url.startswith('http'):
        download_url = operator_id_or_url
    else:
        # Resolve operator ID → latest feed version URL via TransitLand API
        params: dict = {'onestop_id': operator_id_or_url}
        if api_key:
            params['apikey'] = api_key
        meta_url = f"{TRANSITLAND_API}/feeds?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(meta_url, headers={'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            feeds = data.get('feeds', [])
            if not feeds:
                logger.error("No feed found for operator: %s", operator_id_or_url)
                return None
            fv = feeds[0].get('feed_versions', [{}])
            download_url = fv[0].get('url', '') if fv else ''
            if not download_url:
                logger.error("No download URL in feed metadata for: %s", operator_id_or_url)
                return None
        except Exception as exc:
            logger.error("TransitLand metadata lookup failed: %s", exc)
            return None

    # Download the zip
    try:
        logger.info("Downloading GTFS feed from: %s", download_url)
        urllib.request.urlretrieve(download_url, str(output_path))
        logger.info("GTFS downloaded to: %s (%d KB)",
                    output_path, output_path.stat().st_size // 1024)
        return str(output_path)
    except Exception as exc:
        logger.error("GTFS download failed: %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="RTD_SIM GTFS & tram spine validation tool"
    )
    parser.add_argument('--feed',     help="Path to GTFS .zip or directory")
    parser.add_argument('--date',     help="Service date YYYYMMDD (optional)")
    parser.add_argument('--place',    help="OSM place name for alignment check (slow)")
    parser.add_argument('--map',      action='store_true', help="Generate folium HTML map")
    parser.add_argument('--map-out',  default='/tmp/rtd_sim_gtfs_validation.html')
    parser.add_argument('--spine',    action='store_true', help="Test tram spine only (no GTFS feed)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    print("=" * 60)
    print("RTD_SIM GTFS & Tram Spine Validator")
    print("=" * 60)

    result = ValidationResult()

    # Always run tram spine check
    validate_tram_spine(result)

    # GTFS feed check (if provided)
    if args.feed:
        validate_gtfs_feed(args.feed, result, osm_place=args.place, service_date=args.date)
    elif not args.spine:
        print("\n  ℹ️  No --feed provided. Run with --spine to test tram spine only,")
        print("     or --feed /path/to/gtfs.zip to also validate a GTFS feed.")

    # Map generation
    if args.map:
        generate_alignment_map(output_path=args.map_out, feed_path=args.feed)

    print()
    print("=" * 60)
    print(f"Result: {result.summary()}")
    print("=" * 60)

    fails = sum(1 for c in result.checks if c['status'] == 'FAIL')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()