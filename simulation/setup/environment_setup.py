"""
simulation/setup/environment_setup.py

Environment and infrastructure initialisation for the simulation setup phase.

Graph loading strategy
----------------------
Three OSM network graphs are loaded in sequence:

  1. 'drive'  — car, bus, van, truck, HGV routing (always loaded first).
  2. 'walk'   — pedestrian routing for transit access/egress legs.
               Without this graph, every walk from an agent's origin to the
               nearest rail station or bus stop is an interpolated straight line,
               producing the diagonal artefacts visible across parks, rivers,
               and the Firth of Forth.
  3. 'bike'   — cycle network for bike, cargo_bike, and e_scooter routing.

All three are loaded from the same place/bbox so they share a consistent
geographic extent.  Disk caches are keyed separately per network type,
so re-running after the initial download is fast.

NaPTAN integration
------------------
After the rail graph is registered, `naptan_loader.build_transfer_nodes()`
is called to download the DfT NaPTAN rail stop dataset (cached 30 days).
The resulting stop list is stored on the environment as `env.naptan_stops`
so the Router's intermodal snap can use precise platform coordinates
(from the government's authoritative dataset) rather than approximating
from OpenRailMap node centroids.

Multi-city input
----------------
detect_multi_city_input() recognises corridor notation ("Edinburgh →
Glasgow") and comma-separated city lists.  When detected, a bounding box
is generated and used in place of a single-city OSMnx place query.

Infrastructure placement
------------------------
setup_infrastructure() derives the drive-graph bbox for charger placement
and then snaps every station to its nearest road node so markers never
appear in the sea or on hillside farmland.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Optional, Tuple

from simulation.spatial_environment import SpatialEnvironment
from simulation.infrastructure.infrastructure_manager import InfrastructureManager
from simulation.config.simulation_config import SimulationConfig

logger = logging.getLogger(__name__)


# ============================================================
# ENVIRONMENT SETUP
# ============================================================

def setup_environment(
    config: SimulationConfig,
    progress_callback=None,
) -> SpatialEnvironment:
    """
    Initialise the spatial environment with OSM graphs, rail, and GTFS data.

    Loading sequence
    ----------------
    1. Drive graph  — always loaded first; used for routing and bbox derivation.
    2. Walk graph   — loaded immediately after drive; required for proper
                      pedestrian access/egress legs to rail stations and bus stops.
    3. Bike graph   — loaded for bike/cargo_bike/e_scooter mode routing.
    4. Rail graph   — OpenRailMap via OSMnx (largest connected component kept).
    5. NaPTAN stops — DfT authoritative rail/metro stop coordinates (cached 30d).
    6. GTFS transit — bus/tram/ferry stops + headways when feed path provided.

    Args:
        config:            SimulationConfig instance.
        progress_callback: Optional callback(progress: float, message: str).

    Returns:
        SpatialEnvironment with all available graphs registered.
    """
    if progress_callback:
        progress_callback(0.10, "🗺️ Loading environment…")

    cache_dir = Path.home() / ".rtd_sim_cache" / "osm_graphs"
    env = SpatialEnvironment(
        step_minutes   = 1.0,
        cache_dir      = cache_dir,
        use_congestion = config.use_congestion,
    )

    if not config.use_osm:
        if progress_callback:
            progress_callback(0.20, "✅ Environment loaded (no OSM)")
        return env

    # ── Determine place / bbox ────────────────────────────────────────────────
    if config.extended_bbox:
        west, south, east, north = config.extended_bbox
        bbox        = (north, south, east, west)   # SpatialEnvironment convention
        region_name = config.region_name or "Custom Region"
        place       = None
        logger.info(
            "Loading extended region: bbox=(%.4f, %.4f, %.4f, %.4f)",
            west, south, east, north,
        )
    elif config.place:
        is_multi, mc_bbox = detect_multi_city_input(config.place)
        if is_multi and mc_bbox:
            west, south, east, north = mc_bbox
            bbox        = (north, south, east, west)
            region_name = config.region_name or config.place
            place       = None
            logger.info(
                "Multi-city corridor: %s — bbox=(%.4f, %.4f, %.4f, %.4f)",
                config.place, west, south, east, north,
            )
        else:
            bbox        = None
            place       = config.place
            region_name = config.place
            logger.info("Loading city: %s", config.place)
    else:
        logger.warning("No place or bbox specified — returning empty environment")
        return env

    # ── 1. Drive graph ────────────────────────────────────────────────────────
    if progress_callback:
        progress_callback(0.11, "🛣️ Loading drive network…")

    env.load_osm_graph(
        place        = place,
        bbox         = bbox,
        network_type = 'drive',
        use_cache    = True,
    )

    if not env.graph_loaded:
        logger.error("❌ Drive graph failed to load")
        raise RuntimeError("OSM drive graph loading failed")

    stats = env.get_graph_stats()
    logger.info(
        "✅ Drive graph: %s — %d nodes, %d edges",
        region_name, stats['nodes'], stats['edges'],
    )
    if progress_callback:
        progress_callback(0.13, f"✅ Drive network loaded ({stats['nodes']:,} nodes)")

    # ── 2. Walk graph ─────────────────────────────────────────────────────────
    # Critical for transit access/egress legs.  Without the walk graph every
    # leg from an agent's home address to a rail station or bus stop falls back
    # to an interpolated straight line, producing diagonal artefacts on the map.
    if progress_callback:
        progress_callback(0.14, "🚶 Loading walk network…")
    try:
        env.load_osm_graph(
            place        = place,
            bbox         = bbox,
            network_type = 'walk',
            use_cache    = True,
        )
        G_walk = env.graph_manager.get_graph('walk')
        if G_walk is not None:
            logger.info(
                "✅ Walk graph: %d nodes, %d edges",
                G_walk.number_of_nodes(), G_walk.number_of_edges(),
            )
        else:
            logger.warning("⚠️  Walk graph load returned None — access/egress legs will use straight lines")
    except Exception as exc:
        logger.warning("Walk graph load failed (non-fatal): %s", exc)

    # ── 3. Bike graph ─────────────────────────────────────────────────────────
    # Required for bike, cargo_bike, and e_scooter routing.  Without it these
    # modes silently fall back to the drive graph, routing cyclists on motorways.
    if progress_callback:
        progress_callback(0.15, "🚲 Loading cycle network…")
    try:
        env.load_osm_graph(
            place        = place,
            bbox         = bbox,
            network_type = 'bike',
            use_cache    = True,
        )
        G_bike = env.graph_manager.get_graph('bike')
        if G_bike is not None:
            logger.info(
                "✅ Bike graph: %d nodes, %d edges",
                G_bike.number_of_nodes(), G_bike.number_of_edges(),
            )
        else:
            logger.warning("⚠️  Bike graph load returned None")
    except Exception as exc:
        logger.warning("Bike graph load failed (non-fatal): %s", exc)

    if progress_callback:
        progress_callback(0.16, "✅ Road networks loaded")

    # ── 3.5 Ferry graph ───────────────────────────────────────────────────────
    # Load ferry route geometry from Overpass API (or hardcoded UK spine as
    # fallback).  Registered as graphs['ferry'] on the GraphManager so both the
    # Router and the Visualiser can access it.  Ferry routes are always shown on
    # the OSM map regardless of whether GTFS is loaded — they are infrastructure
    # layers, not GTFS layers.  A 2° bbox expansion inside fetch_ferry_graph()
    # ensures cross-sea terminals outside the drive graph area are captured.
    if progress_callback:
        progress_callback(0.155, "⛴️ Loading ferry network…")
    try:
        from simulation.spatial.rail_network import get_or_fallback_ferry_graph
        G_ferry = get_or_fallback_ferry_graph(env)
        if G_ferry is not None and hasattr(G_ferry, 'number_of_nodes') and G_ferry.number_of_nodes() > 0:
            env.graph_manager.graphs['ferry'] = G_ferry
            logger.info(
                "✅ Ferry graph: %d terminals, %d routes",
                G_ferry.number_of_nodes(),
                G_ferry.number_of_edges() // 2,   # bi-directional, so halve
            )
        elif G_ferry is not None:
            # Graph object returned but lacks NetworkX API — store anyway
            env.graph_manager.graphs['ferry'] = G_ferry
            logger.info("✅ Ferry graph registered")
        else:
            logger.warning("⚠️  Ferry graph returned None — ferry routing uses great-circle lines")
    except Exception as exc:
        logger.warning("Ferry graph load failed (non-fatal): %s", exc)

    # ── 4. Rail graph (OpenRailMap + largest-component extraction) ────────────
    if progress_callback:
        progress_callback(0.17, "🚆 Loading rail network…")
    try:
        rail_loaded = env.load_rail_graph()
        if rail_loaded:
            G_rail = env.get_rail_graph()
            logger.info(
                "✅ Rail graph ready: %d nodes, %d edges",
                G_rail.number_of_nodes() if G_rail else 0,
                G_rail.number_of_edges() if G_rail else 0,
            )
        else:
            logger.warning(
                "⚠️  Rail graph unavailable — rail agents use station-spine routing"
            )
    except Exception as exc:
        logger.warning("Rail graph load failed (non-fatal): %s", exc)

    # ── 5. NaPTAN stop data ───────────────────────────────────────────────────
    # Downloads the DfT's authoritative rail/metro stop coordinates (cached 30d).
    # Stored on env.naptan_stops so the Router can snap intermodal transfer nodes
    # to precise platform positions rather than OpenRailMap node centroids.
    if progress_callback:
        progress_callback(0.18, "📍 Loading NaPTAN stop data…")
    try:
        from simulation.spatial.naptan_loader import download_naptan

        # Derive spatial filter from drive graph bounds.
        naptan_bbox = None
        drive = env.graph_manager.get_graph('drive')
        if drive is not None and drive.number_of_nodes() > 0:
            xs = [d['x'] for _, d in drive.nodes(data=True)]
            ys = [d['y'] for _, d in drive.nodes(data=True)]
            # NaPTAN uses (north, south, east, west) convention.
            naptan_bbox = (
                max(ys) + 0.3,   # north  (+0.3° padding for cross-boundary stops)
                min(ys) - 0.3,   # south
                max(xs) + 0.3,   # east
                min(xs) - 0.3,   # west
            )

        naptan_stops = download_naptan(bbox=naptan_bbox)
        env.naptan_stops = naptan_stops   # stash for Router access
        logger.info(
            "✅ NaPTAN: %d stops loaded (bbox=%s)",
            len(naptan_stops), naptan_bbox is not None,
        )
    except Exception as exc:
        logger.warning(
            "NaPTAN load failed (non-fatal): %s — rail snap uses OpenRailMap nodes",
            exc,
        )
        env.naptan_stops = []

    # ── 6. GTFS transit graph ─────────────────────────────────────────────────
    gtfs_path = getattr(config, 'gtfs_feed_path', None)
    if gtfs_path:
        if progress_callback:
            progress_callback(0.19, "🚌 Loading GTFS transit data…")
        try:
            gtfs_loaded = env.load_gtfs_graph(
                feed_path      = gtfs_path,
                service_date   = getattr(config, 'gtfs_service_date',   None),
                fuel_overrides = getattr(config, 'gtfs_fuel_overrides', None),
            )
            if gtfs_loaded:
                G_transit = env.get_transit_graph()
                logger.info(
                    "✅ GTFS transit graph ready: %d stops, %d service edges",
                    G_transit.number_of_nodes() if G_transit else 0,
                    G_transit.number_of_edges() if G_transit else 0,
                )
            else:
                logger.warning("⚠️  GTFS load failed — bus/tram use drive-proxy routing")
        except Exception as exc:
            logger.warning("GTFS load failed (non-fatal): %s", exc)
    else:
        logger.debug("No gtfs_feed_path in config — GTFS transit routing skipped")

    # ── Congestion tracking ───────────────────────────────────────────────────
    if config.use_congestion:
        try:
            if getattr(env, 'congestion_manager', None):
                logger.info("✅ Congestion tracking enabled")
            elif hasattr(env, 'get_congestion_heatmap'):
                hm = env.get_congestion_heatmap()
                logger.info("✅ Congestion tracking enabled (%d edges)", len(hm))
            else:
                logger.warning("⚠️  Congestion requested but CongestionManager not available")
        except Exception as exc:
            logger.warning("Congestion initialisation failed: %s", exc)

    if progress_callback:
        progress_callback(0.20, "✅ Environment loaded")

    return env


# ============================================================
# INFRASTRUCTURE SETUP
# ============================================================

def setup_infrastructure(
    config: SimulationConfig,
    progress_callback=None,
    env=None,
) -> Optional[InfrastructureManager]:
    """
    Initialise infrastructure manager with charging stations and depots.

    Charger placement
    -----------------
    Station coordinates are derived from the drive graph spatial bounds when
    available.  After random placement, every station is snapped to its nearest
    OSM road node so markers sit on actual road junctions and never appear in
    the sea, on hilltops, or in parks.

    Args:
        config:            SimulationConfig instance.
        progress_callback: Optional callback(progress: float, message: str).
        env:               SpatialEnvironment — used for bbox derivation and
                           road-node snapping.  Pass None to skip snapping.

    Returns:
        InfrastructureManager or None if infrastructure is disabled.
    """
    if not config.enable_infrastructure:
        return None

    if progress_callback:
        progress_callback(0.25, "🔌 Setting up infrastructure…")

    infrastructure = InfrastructureManager(grid_capacity_mw=config.grid_capacity_mw)

    # ── Determine charger placement bbox ─────────────────────────────────────
    if config.extended_bbox:
        west, south, east, north = config.extended_bbox
        logger.info("Populating infrastructure across extended region")

        for i in range(config.num_chargers):
            lon = random.uniform(west, east)
            lat = random.uniform(south, north)
            infrastructure.add_charging_station(
                station_id   = f"regional_{i:03d}",
                location     = (lon, lat),
                charger_type = random.choice(['level2', 'dcfast']),
                num_ports    = random.choice([2, 4, 6]),
                power_kw     = 7.0 if i % 5 != 0 else 50.0,
                cost_per_kwh = 0.15 if i % 5 != 0 else 0.25,
                owner_type   = 'public',
            )

        depot_locations = [
            (-4.25, 55.86, "glasgow"),
            (-3.19, 55.95, "edinburgh"),
        ]
        for i, (dlon, dlat, city) in enumerate(depot_locations):
            infrastructure.add_depot(
                depot_id       = f"depot_{city}_{i:02d}",
                location       = (dlon, dlat),
                depot_type     = random.choice(['delivery', 'freight']),
                num_chargers   = random.choice([10, 20]),
                charger_power_kw = 50.0,
            )

    else:
        # City scale — derive bbox from drive graph node coordinates.
        if env is not None and env.graph_loaded:
            try:
                drive_graph = env.graph_manager.get_graph('drive')
                if drive_graph is not None and drive_graph.number_of_nodes() > 0:
                    lons  = [d['x'] for _, d in drive_graph.nodes(data=True)]
                    lats  = [d['y'] for _, d in drive_graph.nodes(data=True)]
                    west  = min(lons)
                    east  = max(lons)
                    south = min(lats)
                    north = max(lats)
                    logger.info(
                        "setup_infrastructure: bbox from drive graph "
                        "(%.4f, %.4f, %.4f, %.4f)",
                        west, south, east, north,
                    )
                else:
                    raise ValueError("Drive graph has no nodes")
            except Exception as exc:
                logger.error(
                    "setup_infrastructure: could not derive bbox from drive graph — %s. "
                    "Infrastructure placement skipped.",
                    exc,
                )
                return infrastructure
        else:
            logger.error(
                "setup_infrastructure: no graph loaded and no extended_bbox. "
                "Infrastructure placement skipped."
            )
            return infrastructure

        for i in range(config.num_chargers):
            lon = random.uniform(west, east)
            lat = random.uniform(south, north)
            infrastructure.add_charging_station(
                station_id   = f"public_{i:03d}",
                location     = (lon, lat),
                charger_type = 'dcfast' if i % 5 == 0 else 'level2',
                num_ports    = random.choice([2, 4, 6]),
                power_kw     = 50.0 if i % 5 == 0 else 7.0,
                cost_per_kwh = 0.25 if i % 5 == 0 else 0.15,
                owner_type   = 'public',
            )

        for i in range(config.num_depots):
            lon = west + (east - west) * (i + 0.5) / max(config.num_depots, 1)
            lat = south + (north - south) * 0.5
            infrastructure.add_depot(
                depot_id       = f"depot_{i:02d}",
                location       = (lon, lat),
                depot_type     = 'delivery',
                num_chargers   = 10,
                charger_power_kw = 150.0,
            )

    # ── Snap stations to road nodes ───────────────────────────────────────────
    # Random bbox coordinates land in the Firth of Forth (~20 % of Edinburgh
    # bbox is sea) and on the Pentland Hills.  Snapping every station to the
    # nearest OSM drive-network node places markers on actual road junctions.
    if env is not None and env.graph_loaded:
        _snap_stations_to_roads(infrastructure, env)
    else:
        logger.warning(
            "setup_infrastructure: env not provided — stations NOT snapped to roads. "
            "Pass env=env to fix sea/field placement."
        )

    metrics = infrastructure.get_infrastructure_metrics()
    logger.info(
        "✅ Infrastructure: %d stations, %d ports, %d depots",
        metrics['charging_stations'], metrics['total_ports'], metrics['depots'],
    )
    if progress_callback:
        progress_callback(0.30, "✅ Infrastructure ready")

    return infrastructure


# ============================================================
# MULTI-CITY INPUT DETECTION
# ============================================================

def detect_multi_city_input(place: str) -> Tuple[bool, Optional[tuple]]:
    """
    Detect if place string is multi-city and convert to a bounding box.

    Recognised patterns
    -------------------
    • Corridor notation: "Edinburgh → Glasgow"  or  "Edinburgh -> Glasgow"
    • Comma-separated cities: "Edinburgh, Newcastle"
      (only when both parts are in the known city database — "Edinburgh, UK"
      is correctly treated as a single-city query)

    Args:
        place: User-supplied place string.

    Returns:
        (True, bbox_tuple) when multi-city is detected.
        (False, None)      for a single city / unrecognised input.
    """
    KNOWN_CITIES = {
        'edinburgh', 'glasgow', 'aberdeen', 'newcastle', 'manchester',
        'london', 'birmingham', 'leeds', 'liverpool', 'bristol',
        'dover', 'southampton', 'cardiff', 'belfast', 'inverness',
    }

    if '→' in place or '->' in place:
        return True, _parse_corridor_input(place)

    parts = [p.strip().lower() for p in place.split(',')]
    if len(parts) >= 2:
        city_count = sum(1 for p in parts if p in KNOWN_CITIES)
        if city_count >= 2:
            logger.info("Detected multi-city input: %s", place)
            return True, _create_multi_city_bbox(parts)

    return False, None


def _parse_corridor_input(place: str) -> Optional[tuple]:
    """Parse 'Origin → Destination' corridor notation into a bbox tuple."""
    parts = place.split('→') if '→' in place else place.split('->')
    if len(parts) != 2:
        return None

    # (lat, lon) for each city
    CITY_COORDS = {
        'edinburgh':   (55.9533, -3.1883),
        'glasgow':     (55.8642, -4.2518),
        'aberdeen':    (57.1497, -2.0943),
        'newcastle':   (54.9783, -1.6178),
        'manchester':  (53.4808, -2.2426),
        'london':      (51.5074, -0.1278),
        'dover':       (51.1279,  1.3134),
        'birmingham':  (52.4862, -1.8904),
    }

    o_key = parts[0].strip().split(',')[0].strip().lower()
    d_key = parts[1].strip().split(',')[0].strip().lower()

    if o_key not in CITY_COORDS or d_key not in CITY_COORDS:
        return None

    lats = [CITY_COORDS[o_key][0], CITY_COORDS[d_key][0]]
    lons = [CITY_COORDS[o_key][1], CITY_COORDS[d_key][1]]
    pad  = 0.30   # ~30 km margin

    bbox = (
        min(lons) - pad,   # west
        min(lats) - pad,   # south
        max(lons) + pad,   # east
        max(lats) + pad,   # north
    )
    logger.info("Created corridor bbox: %s → %s", o_key, d_key)
    return bbox


def _create_multi_city_bbox(cities: list) -> Optional[tuple]:
    """Create a bounding box covering multiple recognised city names."""
    CITY_COORDS = {
        'edinburgh':   (55.9533, -3.1883),
        'glasgow':     (55.8642, -4.2518),
        'aberdeen':    (57.1497, -2.0943),
        'newcastle':   (54.9783, -1.6178),
        'manchester':  (53.4808, -2.2426),
        'london':      (51.5074, -0.1278),
        'dover':       (51.1279,  1.3134),
        'birmingham':  (52.4862, -1.8904),
        'leeds':       (53.8008, -1.5491),
        'liverpool':   (53.4084, -2.9916),
    }

    coords = []
    for city in cities:
        key = city.split(',')[0].strip().lower()
        if key in CITY_COORDS:
            coords.append(CITY_COORDS[key])

    if len(coords) < 2:
        logger.warning("Could not find coordinates for cities: %s", cities)
        return None

    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    pad  = 0.20   # ~20 km margin

    bbox = (
        min(lons) - pad,   # west
        min(lats) - pad,   # south
        max(lons) + pad,   # east
        max(lats) + pad,   # north
    )
    logger.info("Created multi-city bbox: %s", ', '.join(c.split(',')[0].strip() for c in cities))
    return bbox


# ============================================================
# ROAD SNAPPING UTILITY
# ============================================================

def _snap_stations_to_roads(infrastructure, env) -> None:
    """
    Move every charging station onto its nearest OSM drive-network node.

    Random bbox coordinates can land in the Firth of Forth, on the Pentland
    Hills, or in a park.  Snapping to the drive graph guarantees every marker
    sits on an actual road junction that agents can route to.

    Args:
        infrastructure: InfrastructureManager with stations already added.
        env:            SpatialEnvironment with drive graph loaded.
    """
    drive_graph = env.graph_manager.get_graph('drive')
    if drive_graph is None:
        logger.warning("_snap_stations_to_roads: no drive graph — skipping")
        return

    total   = len(infrastructure.charging_stations)
    snapped = 0

    for station in infrastructure.charging_stations.values():
        node = env._get_nearest_node(station.location, 'drive')
        if node is not None:
            station.location = (
                float(drive_graph.nodes[node]['x']),
                float(drive_graph.nodes[node]['y']),
            )
            snapped += 1

    logger.info(
        "Snapped %d / %d charging stations to OSM road nodes",
        snapped, total,
    )