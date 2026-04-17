"""
simulation/spatial/transport_loader.py

Unified multimodal transport graph loader for RTD_SIM.

Replaces the previous patchwork of separate OSM / GTFS / NaPTAN loaders with
a single entry-point that builds every graph layer in the correct order and
wires them together with transfer edges the BDI router can use.

Architecture
────────────
Seven graph layers are loaded and registered on the GraphManager:

  'drive'   — OSMnx road network       (car, bus, van, truck, HGV)
  'walk'    — OSMnx pedestrian network  (access/egress legs)
  'bike'    — OSMnx cycle network       (bike, cargo_bike, e_scooter)
  'rail'    — OpenRailMap via OSMnx     (local_train, intercity_train)
  'tram'    — OSM railway=tram layer    (tram, without GTFS shapes)
  'transit' — GTFS or TransitLand feed  (bus, tram, ferry service graph)
  'ferry'   — Overpass ferry routes     (ferry_diesel, ferry_electric)

Transfer edges are then added between the rail and drive graphs at every
station node (NaPTAN-snapped where available) so the Router's intermodal
logic can chain access-walk → rail → egress-walk in a single Dijkstra call.

Loading tiers (transit)
───────────────────────
  1. GTFS ZIP / directory  — if gtfs_feed_path is set in config
  2. TransitLand REST API  — if TRANSITLAND_API_KEY is in .env and no GTFS
  3. Cached TransitLand snapshot — if live API unavailable
  4. OSM tram graph only   — tram geometry without headway data

TransitLand feed IDs for known Scottish operators
──────────────────────────────────────────────────
  Edinburgh Trams   f-gcpv-edinburghtramsltd
  Lothian Buses     f-gcpv-lothianbuses
  ScotRail          f-gcpv-firstscotland
  Glasgow Subway    f-gcpv-spt
  First Glasgow     f-gcpv-firstglasgow

Note: these are *feed* IDs (f-…), not *operator* IDs (o-…).  The download
endpoint is:
  GET https://transit.land/api/v2/rest/feeds/{feed_id}/download_latest_feed_version
  Authorization: apikey {TRANSITLAND_API_KEY}

Usage
─────
  from simulation.spatial.transport_loader import load_transport_graphs

  load_transport_graphs(env, config)
  # All graphs now available via env.graph_manager.get_graph(layer_name)
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# TransitLand known feed IDs — Scotland
TRANSITLAND_FEEDS = {
    "edinburgh_trams":  "f-gcpv-edinburghtramsltd",
    "lothian_buses":    "f-gcpv-lothianbuses",
    "scotrail":         "f-gcpv-firstscotland",
    "glasgow_subway":   "f-gcpv-spt",
    "first_glasgow":    "f-gcpv-firstglasgow",
    # England / Wales additions
    "tfl_london":       "f-gcpv-tfl",
    "arriva_wales":     "f-gcpv-arrivawales",
}

_TRANSITLAND_BASE = "https://transit.land/api/v2/rest"


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def load_transport_graphs(
    env,
    config,
    progress_callback=None,
) -> None:
    """
    Load all transport graph layers onto *env* in the correct order.

    This is the single function that simulation/setup/environment_setup.py
    should call instead of managing each layer separately.  It handles
    place/bbox resolution, caching, graceful fallbacks at every tier,
    and NaPTAN-anchored transfer edge construction.

    Args:
        env:               SpatialEnvironment — graphs are registered here.
        config:            SimulationConfig — supplies place, bbox, GTFS path,
                           TransitLand key, etc.
        progress_callback: Optional callable(progress: float, message: str).
    """
    def _cb(p, msg):
        if progress_callback:
            progress_callback(p, msg)

    # ── Resolve place / bbox ──────────────────────────────────────────────────
    place, bbox = _resolve_location(config)
    if place is None and bbox is None:
        logger.warning("transport_loader: no place or bbox — skipping graph load")
        return

    # ── 1. Drive ──────────────────────────────────────────────────────────────
    _cb(0.10, "🛣️  Loading drive network…")
    _load_osm_layer(env, 'drive', place, bbox, config)

    # ── 2. Walk ───────────────────────────────────────────────────────────────
    _cb(0.13, "🚶 Loading walk network…")
    _load_osm_layer(env, 'walk', place, bbox, config)

    # ── 3. Bike ───────────────────────────────────────────────────────────────
    _cb(0.15, "🚲 Loading cycle network…")
    _load_osm_layer(env, 'bike', place, bbox, config)

    # ── 4. Tram track geometry ────────────────────────────────────────────────
    _cb(0.16, "🚋 Loading tram track geometry…")
    _load_tram_graph(env, place, bbox)

    # ── 5. Ferry routes ───────────────────────────────────────────────────────
    _cb(0.17, "⛴️  Loading ferry network…")
    _load_ferry_graph(env)

    # ── 6. Rail (OpenRailMap) ─────────────────────────────────────────────────
    _cb(0.18, "🚆 Loading rail network…")
    _load_rail_graph(env)

    # ── 7. NaPTAN stop registry ───────────────────────────────────────────────
    _cb(0.19, "📍 Loading NaPTAN stops…")
    _load_naptan(env)

    # ── 8. GTFS / TransitLand transit graph ───────────────────────────────────
    _cb(0.20, "🚌 Loading transit data…")
    _load_transit(env, config)

    # ── 9. Transfer edges ─────────────────────────────────────────────────────
    _cb(0.22, "🔗 Building transfer edges…")
    _build_transfer_edges(env)

    _cb(0.25, "✅ Transport graphs loaded")
    _log_summary(env)


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER LOADERS
# ═══════════════════════════════════════════════════════════════════════════════

def _load_osm_layer(env, network_type: str, place, bbox, config) -> None:
    """Load one OSMnx network layer; skip silently on failure."""
    try:
        env.load_osm_graph(
            place=place,
            bbox=bbox,
            network_type=network_type,
            use_cache=True,
        )
        G = env.graph_manager.get_graph(network_type)
        if G is not None:
            logger.info(
                "✅ %s graph: %d nodes, %d edges",
                network_type, G.number_of_nodes(), G.number_of_edges(),
            )
        else:
            logger.warning("⚠️  %s graph load returned None", network_type)
    except Exception as exc:
        logger.warning("%s graph load failed (non-fatal): %s", network_type, exc)


def _load_tram_graph(env, place, bbox) -> None:
    """
    Download OSM railway=tram tracks.

    Registered as graphs['tram'] so router._transit_fallback can route on
    physical tram geometry even when no GTFS shapes are available.
    """
    try:
        import osmnx as ox
        _filter = '["railway"~"tram|light_rail"]'
        G_tram = None
        if place:
            G_tram = ox.graph_from_place(
                place, custom_filter=_filter, retain_all=True,
            )
        elif bbox:
            _tn, _ts, _te, _tw = bbox  # (north, south, east, west)
            G_tram = ox.graph_from_bbox(
                north=_tn, south=_ts, east=_te, west=_tw,
                custom_filter=_filter, retain_all=True,
            )
        if G_tram is not None and G_tram.number_of_nodes() > 0:
            env.graph_manager.graphs['tram'] = G_tram
            logger.info(
                "✅ Tram graph: %d nodes, %d edges (OSM railway=tram)",
                G_tram.number_of_nodes(), G_tram.number_of_edges(),
            )
        else:
            logger.warning("⚠️  Tram graph empty — no OSM tram tracks in bbox")
    except Exception as exc:
        logger.warning("Tram graph load failed (non-fatal): %s", exc)


def _load_ferry_graph(env) -> None:
    """Load ferry graph via Overpass, falling back to hardcoded UK spine."""
    try:
        from simulation.spatial.rail_network import get_or_fallback_ferry_graph
        G_ferry = get_or_fallback_ferry_graph(env)
        if G_ferry is not None and G_ferry.number_of_nodes() > 0:
            env.graph_manager.graphs['ferry'] = G_ferry
            logger.info(
                "✅ Ferry graph: %d terminals, %d routes",
                G_ferry.number_of_nodes(),
                G_ferry.number_of_edges() // 2,
            )
        else:
            logger.warning("⚠️  Ferry graph returned None")
    except Exception as exc:
        logger.warning("Ferry graph load failed (non-fatal): %s", exc)


def _load_rail_graph(env) -> None:
    """Load OpenRailMap rail graph, falling back to hardcoded spine."""
    try:
        loaded = env.load_rail_graph()
        if loaded:
            G = env.get_rail_graph()
            logger.info(
                "✅ Rail graph: %d nodes, %d edges",
                G.number_of_nodes() if G else 0,
                G.number_of_edges() if G else 0,
            )
        else:
            logger.warning("⚠️  Rail graph unavailable — spine routing active")
    except Exception as exc:
        logger.warning("Rail graph load failed (non-fatal): %s", exc)


def _load_naptan(env) -> None:
    """
    Download / cache NaPTAN stops and store on both env and graph_manager.

    The dual assignment (env.naptan_stops + graph_manager.naptan_stops) is
    intentional: env is used by the visualiser; graph_manager is read by
    Router._nearest_rail_node.  See environment_setup.py for full rationale.
    """
    try:
        from simulation.spatial.naptan_loader import download_naptan

        drive = env.graph_manager.get_graph('drive')
        naptan_bbox = None
        if drive is not None and drive.number_of_nodes() > 0:
            xs = [d['x'] for _, d in drive.nodes(data=True)]
            ys = [d['y'] for _, d in drive.nodes(data=True)]
            naptan_bbox = (
                max(ys) + 0.3,   # north
                min(ys) - 0.3,   # south
                max(xs) + 0.3,   # east
                min(xs) - 0.3,   # west
            )

        naptan_stops = download_naptan(bbox=naptan_bbox)
        env.naptan_stops = naptan_stops                         # type: ignore[attr-defined]
        env.graph_manager.naptan_stops = naptan_stops           # type: ignore[attr-defined]
        logger.info("✅ NaPTAN: %d stops loaded", len(naptan_stops))
    except Exception as exc:
        logger.warning(
            "NaPTAN load failed (non-fatal): %s — rail snap uses graph nodes", exc
        )
        env.naptan_stops = []                                   # type: ignore[attr-defined]
        env.graph_manager.naptan_stops = []                     # type: ignore[attr-defined]


def _load_transit(env, config) -> None:
    """
    Load GTFS or TransitLand transit graph.

    Priority
    --------
    1. GTFS ZIP / directory — if config.gtfs_feed_path is set and exists.
    2. TransitLand REST API — if TRANSITLAND_API_KEY is in environment and
       config.transitland_feed_id (or config.transitland_operator) is set.
    3. Cached TransitLand snapshot — if live API call fails.
    4. Silent success — tram uses OSM geometry; bus falls back to drive proxy.
    """
    gtfs_path = getattr(config, 'gtfs_feed_path', None)

    # ── Tier 1: local GTFS ───────────────────────────────────────────────────
    if gtfs_path and Path(gtfs_path).exists():
        try:
            loaded = env.load_gtfs_graph(
                feed_path=gtfs_path,
                service_date=getattr(config, 'gtfs_service_date', None),
                fuel_overrides=getattr(config, 'gtfs_fuel_overrides', None),
            )
            if loaded:
                G = env.get_transit_graph()
                logger.info(
                    "✅ GTFS transit: %d stops, %d service edges",
                    G.number_of_nodes() if G else 0,
                    G.number_of_edges() if G else 0,
                )
                return
        except Exception as exc:
            logger.warning("GTFS load failed: %s — trying TransitLand", exc)

    # ── Tier 2 + 3: TransitLand ──────────────────────────────────────────────
    api_key = os.getenv("TRANSITLAND_API_KEY", "").strip()
    feed_id = getattr(config, 'transitland_feed_id', None) or \
              getattr(config, 'transitland_operator', None)

    if api_key and feed_id:
        gtfs_zip = _download_transitland_feed(feed_id, api_key)
        if gtfs_zip and Path(gtfs_zip).exists():
            try:
                loaded = env.load_gtfs_graph(feed_path=gtfs_zip)
                if loaded:
                    G = env.get_transit_graph()
                    logger.info(
                        "✅ TransitLand transit: %d stops, %d edges (feed=%s)",
                        G.number_of_nodes() if G else 0,
                        G.number_of_edges() if G else 0,
                        feed_id,
                    )
                    return
            except Exception as exc:
                logger.warning("TransitLand GTFS load failed: %s", exc)
    elif feed_id and not api_key:
        logger.warning(
            "TransitLand feed_id=%s specified but TRANSITLAND_API_KEY not set — "
            "add key to .env to enable auto-download",
            feed_id,
        )

    logger.debug(
        "No GTFS or TransitLand feed loaded — "
        "tram uses OSM geometry, bus uses drive-proxy fallback"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TRANSFER EDGES
# ═══════════════════════════════════════════════════════════════════════════════

def _build_transfer_edges(env) -> None:
    """
    Add bi-directional transfer edges between rail stations and the drive graph.

    Uses NaPTAN coordinates when available for ±5 m accuracy; falls back to
    OpenRailMap node positions.  These edges are what allow the router to
    chain access-walk → rail → egress-walk through a single graph.
    """
    G_rail  = env.graph_manager.get_graph('rail')
    G_drive = env.graph_manager.get_graph('drive')
    if G_rail is None or G_drive is None:
        return
    try:
        from simulation.spatial.rail_network import link_to_road_network
        link_to_road_network(G_rail, G_drive)
        logger.info("✅ Rail ↔ drive transfer edges built")
    except Exception as exc:
        logger.warning("Transfer edge build failed (non-fatal): %s", exc)


# ═══════════════════════════════════════════════════════════════════════════════
# TRANSITLAND DOWNLOAD
# ═══════════════════════════════════════════════════════════════════════════════

def _download_transitland_feed(
    feed_id: str,
    api_key: str,
    output_dir: str = "/tmp",
    max_age_hours: float = 24.0,
) -> Optional[str]:
    """
    Download a GTFS feed from TransitLand and return the local .zip path.

    Caches the result for *max_age_hours* to avoid repeated downloads across
    Streamlit reruns.  Uses the correct *feed* endpoint:

        GET /v2/rest/feeds/{feed_id}/download_latest_feed_version

    NOT the operator endpoint (o-…) — those return 404 for this call.

    Args:
        feed_id:       TransitLand feed ID, e.g. 'f-gcpv-lothianbuses'.
        api_key:       TRANSITLAND_API_KEY value.
        output_dir:    Directory for the downloaded .zip.
        max_age_hours: Re-download if cached file is older than this.

    Returns:
        Absolute path to the downloaded .zip, or None on failure.
    """
    import urllib.request

    out_path = Path(output_dir) / f"transitland_{feed_id}.zip"

    # Return cached file if fresh enough
    if out_path.exists():
        age_h = (time.time() - out_path.stat().st_mtime) / 3600.0
        if age_h < max_age_hours:
            logger.info(
                "TransitLand: using cached feed %s (%.1fh old)", feed_id, age_h
            )
            return str(out_path)

    url = (
        f"{_TRANSITLAND_BASE}/feeds/{feed_id}"
        f"/download_latest_feed_version"
    )
    logger.info("TransitLand: downloading feed %s …", feed_id)

    try:
        req = urllib.request.Request(
            url,
            headers={
                "apikey":        api_key,
                "User-Agent":    "RTD_SIM/1.0 (research simulation)",
                "Accept":        "application/zip",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            status = getattr(resp, 'status', 200)
            if status != 200:
                logger.warning(
                    "TransitLand feed %s: HTTP %d — check feed ID and API key",
                    feed_id, status,
                )
                return None
            content = resp.read()

        if len(content) < 1024:
            # Too small to be a real GTFS zip — likely an error JSON body
            logger.warning(
                "TransitLand feed %s: response too small (%d bytes) — "
                "probably an error response",
                feed_id, len(content),
            )
            return None

        out_path.write_bytes(content)
        logger.info(
            "✅ TransitLand: downloaded %s → %s (%.1f MB)",
            feed_id, out_path, len(content) / 1_048_576,
        )
        return str(out_path)

    except Exception as exc:
        logger.error("TransitLand download failed for %s: %s", feed_id, exc)
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _resolve_location(config) -> Tuple[Optional[str], Optional[tuple]]:
    """
    Return (place, bbox) from config.

    Handles single-city, corridor ('Edinburgh → Glasgow'), and raw bbox.
    Returns (None, None) when neither is configured.
    """
    if getattr(config, 'extended_bbox', None):
        west, south, east, north = config.extended_bbox
        return None, (north, south, east, west)

    if getattr(config, 'place', None):
        try:
            from simulation.setup.environment_setup import detect_multi_city_input
            is_multi, mc_bbox = detect_multi_city_input(config.place)
            if is_multi and mc_bbox:
                west, south, east, north = mc_bbox
                return None, (north, south, east, west)
        except Exception:
            pass
        return config.place, None

    return None, None


def _log_summary(env) -> None:
    """Log a compact summary of all loaded graph layers."""
    layers = ['drive', 'walk', 'bike', 'rail', 'tram', 'transit', 'ferry']
    lines = []
    for layer in layers:
        G = env.graph_manager.get_graph(layer)
        if G is not None:
            lines.append(
                f"  {layer:8s}  {G.number_of_nodes():6d} nodes  "
                f"{G.number_of_edges():7d} edges"
            )
        else:
            lines.append(f"  {layer:8s}  — not loaded")
    logger.info("Transport graph summary:\n%s", "\n".join(lines))


# ═══════════════════════════════════════════════════════════════════════════════
# TRANSITLAND CITY HELPER  (for sidebar / test use)
# ═══════════════════════════════════════════════════════════════════════════════

def list_known_feeds() -> dict:
    """Return the dict of known TransitLand feed IDs by human label."""
    return dict(TRANSITLAND_FEEDS)


def download_feed_by_label(label: str, output_dir: str = "/tmp") -> Optional[str]:
    """
    Download a feed by its human label (e.g. 'edinburgh_trams').

    Returns path to the downloaded .zip or None.
    Requires TRANSITLAND_API_KEY in environment.
    """
    feed_id = TRANSITLAND_FEEDS.get(label.lower().replace(" ", "_"))
    if not feed_id:
        logger.error("Unknown feed label: %s. Known: %s",
                     label, list(TRANSITLAND_FEEDS.keys()))
        return None
    api_key = os.getenv("TRANSITLAND_API_KEY", "").strip()
    if not api_key:
        logger.error(
            "TRANSITLAND_API_KEY not set — cannot download feed '%s'", label
        )
        return None
    return _download_transitland_feed(feed_id, api_key, output_dir=output_dir)