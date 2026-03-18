"""
simulation/setup/environment_setup.py

This module implements the environment and infrastructure initialization for the 
simulation setup process. It includes functions to load the OSM graph based on user 
configuration (place name or bounding box), and to set up the charging infrastructure 
if enabled.

The `setup_environment` function handles loading the spatial environment, including 
support for multi-city inputs by generating an appropriate bounding box. It also 
verifies that the graph is loaded successfully and that congestion tracking is available 
if requested.

The `setup_infrastructure` function initializes the infrastructure manager and populates 
it with charging stations based on the specified configuration. It supports both 
city-scale and regional-scale setups, and logs key metrics about the infrastructure for 
verification.

Ensure that the environment and infrastructure are properly initialized before proceeding 
to agent creation and simulation execution, as they are critical components of the system.

Ensure that OSM longatitude and latitude are correctly handled in the bounding box 
(west, south, east, north) format when loading the graph.

NOTE: The OSM graph loading now supports multi-city inputs by detecting patterns in the 
place name and generating a bounding box that covers all specified cities. This allows 
users to easily set up simulations that span multiple urban areas without needing to 
manually specify complex bounding boxes.

"""

from __future__ import annotations
import random
import logging
from pathlib import Path
from typing import Optional, Tuple

from simulation.spatial_environment import SpatialEnvironment
from simulation.infrastructure.infrastructure_manager import InfrastructureManager
from simulation.config.simulation_config import SimulationConfig

logger = logging.getLogger(__name__)


def setup_environment(config: SimulationConfig, progress_callback=None) -> SpatialEnvironment:
    """
    Initialize spatial environment with OSM graph.

    Args:
        config: SimulationConfig instance
        progress_callback: Optional callback(progress: float, message: str)
    Returns:
        SpatialEnvironment instance with loaded graph
    """
    if progress_callback:
        progress_callback(0.1, "🗺️ Loading environment...")
    
    cache_dir = Path.home() / ".rtd_sim_cache" / "osm_graphs"
    env = SpatialEnvironment(
        step_minutes=1.0,
        cache_dir=cache_dir,
        use_congestion=config.use_congestion
    )
    
    if config.use_osm:
        # Load OSM graph
        if config.extended_bbox:
            # Use pre-defined bbox
            west, south, east, north = config.extended_bbox
            
            logger.info(f"Loading extended region: bbox=({west}, {south}, {east}, {north})")
            
            env.load_osm_graph(
                bbox=(north, south, east, west),
                network_type='drive',
                use_cache=True
            )
            
            region_name = config.region_name or "Custom Region"
            
        elif config.place:
            # Check if multi-city input
            is_multi, bbox = detect_multi_city_input(config.place)
            
            if is_multi and bbox:
                # Multi-city: Use generated bbox
                north, south, east, west = bbox[3], bbox[1], bbox[2], bbox[0]
                
                logger.info(f"Multi-city corridor: {config.place}")
                logger.info(f"Generated bbox: ({west}, {south}, {east}, {north})")
                
                env.load_osm_graph(
                    bbox=(north, south, east, west),
                    network_type='drive',
                    use_cache=True
                )
                
                region_name = config.region_name or config.place
            
            else:
                # Single city: Use place name
                logger.info(f"Loading city: {config.place}")
                env.load_osm_graph(
                    place=config.place,
                    network_type='drive',
                    use_cache=True
                )
                region_name = config.place
            
        else:
            logger.warning("No place or bbox specified")
            return env
        
        # Verify graph loaded
        if not env.graph_loaded:
            logger.error("❌ Graph failed to load!")
            raise RuntimeError("OSM graph loading failed")
        
        stats = env.get_graph_stats()
        logger.info(f"✅ Loaded {region_name}: {stats['nodes']:,} nodes, {stats['edges']:,} edges")
        
        if progress_callback:
            progress_callback(0.15, f"✅ Loaded {region_name}")
        
        # Verify congestion if enabled
        if config.use_congestion:
            try:
                if hasattr(env, 'congestion_manager') and env.congestion_manager:
                    logger.info("✅ Congestion tracking enabled")
                elif hasattr(env, 'get_congestion_heatmap'):
                    test_heatmap = env.get_congestion_heatmap()
                    logger.info(f"✅ Congestion tracking enabled ({len(test_heatmap)} edges)")
                else:
                    logger.warning("⚠️ Congestion requested but not available")
            except Exception as e:
                logger.warning(f"⚠️ Congestion initialization failed: {e}")
    
    if progress_callback:
        progress_callback(0.2, "✅ Environment loaded")
    
    return env


# ============================================================
# Infrastructure Setup
# ============================================================
def setup_infrastructure(
    config: SimulationConfig,
    progress_callback=None,
    env=None,
) -> Optional[InfrastructureManager]:
    """
    Initialize infrastructure manager with charging stations.
    
    Args:
        config: SimulationConfig instance
        progress_callback: Optional callback(progress: float, message: str)
    
    Returns:
        InfrastructureManager or None if disabled
    """
    if not config.enable_infrastructure:
        return None
    
    if progress_callback:
        progress_callback(0.25, "🔌 Setting up infrastructure...")
    
    infrastructure = InfrastructureManager(grid_capacity_mw=config.grid_capacity_mw)
    
    # Determine spatial bounds for charger placement
    if config.extended_bbox:
        # Regional scale - place chargers across extended region
        west, south, east, north = config.extended_bbox
        logger.info(f"Populating infrastructure across extended region")
        
        for i in range(config.num_chargers):
            lon = random.uniform(west, east)
            lat = random.uniform(south, north)
            
            infrastructure.add_charging_station(
                station_id=f"regional_{i:03d}",
                location=(lon, lat),
                charger_type=random.choice(['level2', 'dcfast']),
                num_ports=random.choice([2, 4, 6]),
                power_kw=7.0 if i % 5 != 0 else 50.0,
                cost_per_kwh=0.15 if i % 5 != 0 else 0.25,
                owner_type='public'
            )
        
        # Add depots in major cities
        depot_locations = [
            (-4.25, 55.86, "glasgow"),
            (-3.19, 55.95, "edinburgh"),
        ]
        
        for i, (lon, lat, city) in enumerate(depot_locations):
            infrastructure.add_depot(
                depot_id=f"depot_{city}_{i:02d}",
                location=(lon, lat),
                depot_type=random.choice(['delivery', 'freight']),
                num_chargers=random.choice([10, 20]),
                charger_power_kw=50.0
            )
    else:
        # City scale - use default Edinburgh placement
        infrastructure.populate_edinburgh_chargers(
            num_public=config.num_chargers,
            num_depot=config.num_depots
        )
    
    # Snap stations to OSM road nodes (prevents sea/field placement)
    if env is not None and env.graph_loaded:
        _snap_stations_to_roads(infrastructure, env)
    else:
        logger.warning(
            'setup_infrastructure: env not provided — stations NOT snapped to roads. '
            'Pass env=env to fix sea/field marker placement.'
        )

    metrics = infrastructure.get_infrastructure_metrics()
    logger.info(f"✅ Infrastructure: {metrics['charging_stations']} stations, "
                f"{metrics['total_ports']} ports, {metrics['depots']} depots")

    if progress_callback:
        progress_callback(0.3, "✅ Infrastructure ready")

    return infrastructure


# ============================================================
# Multi-City Input Detection Utility
# ============================================================
def detect_multi_city_input(place: str) -> Tuple[bool, Optional[tuple]]:
    """
    Detect if place string is multi-city and convert to bbox.
    
    Args:
        place: User input string
    
    Returns:
        (is_multi_city, bbox or None)
    
    Examples:
        "Edinburgh, Newcastle" → (True, bbox)
        "Edinburgh, UK" → (False, None)
        "Dover → Edinburgh" → (True, bbox)
    """
    # Check for multi-city patterns
    # Pattern 1: Multiple cities with comma (but not country)
    # Pattern 2: Arrow notation "A → B"
    
    # Known city database (expand as needed)
    KNOWN_CITIES = {
        'edinburgh', 'glasgow', 'aberdeen', 'newcastle', 'manchester',
        'london', 'birmingham', 'leeds', 'liverpool', 'bristol',
        'dover', 'southampton', 'cardiff', 'belfast', 'inverness'
    }
    
    # Check for arrow notation
    if '→' in place or '->' in place:
        return True, _parse_corridor_input(place)
    
    # Split by comma
    parts = [p.strip().lower() for p in place.split(',')]
    
    # If more than 2 parts and multiple are cities, it's multi-city
    if len(parts) >= 2:
        city_count = sum(1 for p in parts if p in KNOWN_CITIES)
        
        if city_count >= 2:
            # Multi-city detected
            logger.info(f"Detected multi-city input: {place}")
            bbox = _create_multi_city_bbox(parts)
            return True, bbox
    
    # Single city
    return False, None


def _parse_corridor_input(place: str) -> tuple:
    """Parse 'Origin → Destination' format."""
    # Split by arrow
    if '→' in place:
        parts = place.split('→')
    else:
        parts = place.split('->')
    
    if len(parts) != 2:
        return None
    
    origin = parts[0].strip()
    dest = parts[1].strip()
    
    # Hardcoded city coordinates (expand as needed)
    CITY_COORDS = {
        'edinburgh': (55.9533, -3.1883),
        'glasgow': (55.8642, -4.2518),
        'aberdeen': (57.1497, -2.0943),
        'newcastle': (54.9783, -1.6178),
        'manchester': (53.4808, -2.2426),
        'london': (51.5074, -0.1278),
        'dover': (51.1279, 1.3134),
        'birmingham': (52.4862, -1.8904),
    }
    
    origin_lower = origin.split(',')[0].strip().lower()
    dest_lower = dest.split(',')[0].strip().lower()
    
    if origin_lower in CITY_COORDS and dest_lower in CITY_COORDS:
        origin_coords = CITY_COORDS[origin_lower]
        dest_coords = CITY_COORDS[dest_lower]
        
        # Create bbox covering both cities with 30km margin
        lats = [origin_coords[0], dest_coords[0]]
        lons = [origin_coords[1], dest_coords[1]]
        
        # Add 0.3 degree margin (~30km)
        bbox = (
            min(lons) - 0.3,  # west
            min(lats) - 0.3,  # south
            max(lons) + 0.3,  # east
            max(lats) + 0.3   # north
        )
        
        logger.info(f"Created corridor bbox: {origin} → {dest}")
        return bbox
    
    return None


def _create_multi_city_bbox(cities: list) -> tuple:
    """Create bbox covering multiple cities."""
    
    # Hardcoded coordinates for common UK cities
    CITY_COORDS = {
        'edinburgh': (55.9533, -3.1883),
        'glasgow': (55.8642, -4.2518),
        'aberdeen': (57.1497, -2.0943),
        'newcastle': (54.9783, -1.6178),
        'manchester': (53.4808, -2.2426),
        'london': (51.5074, -0.1278),
        'dover': (51.1279, 1.3134),
        'birmingham': (52.4862, -1.8904),
        'leeds': (53.8008, -1.5491),
        'liverpool': (53.4084, -2.9916),
    }
    
    # Get coordinates for recognized cities
    coords = []
    for city in cities:
        city_clean = city.split(',')[0].strip().lower()
        if city_clean in CITY_COORDS:
            coords.append(CITY_COORDS[city_clean])
    
    if len(coords) < 2:
        logger.warning(f"Could not find coordinates for cities: {cities}")
        return None
    
    # Calculate bounding box
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    
    # Add 0.2 degree margin (~20km)
    bbox = (
        min(lons) - 0.2,  # west
        min(lats) - 0.2,  # south
        max(lons) + 0.2,  # east
        max(lats) + 0.2   # north
    )
    
    logger.info(f"Created multi-city bbox covering: {', '.join([c for c in cities if c.split(',')[0].strip().lower() in CITY_COORDS])}")
    
    return bbox


def _snap_stations_to_roads(infrastructure, env) -> None:
    """
    Move every charging station onto its nearest OSM drive-network node.

    Random bbox coordinates land in the Firth of Forth (~20% of Edinburgh
    bbox is sea) and on the Pentland Hills. Snapping to the drive graph
    ensures every marker sits on an actual road junction.
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
        "Snapped %d/%d charging stations to OSM road nodes", snapped, total
    )