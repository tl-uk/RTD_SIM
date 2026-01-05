"""
simulation/setup/environment_setup.py

Environment and infrastructure initialization.
Handles OSM graph loading and charging infrastructure setup.
"""

from __future__ import annotations
import random
import logging
from pathlib import Path
from typing import Optional

from simulation.spatial_environment import SpatialEnvironment
from simulation.infrastructure_manager import InfrastructureManager
from simulation.config.simulation_config import SimulationConfig

logger = logging.getLogger(__name__)


def setup_environment(config: SimulationConfig, progress_callback=None) -> SpatialEnvironment:
    """
    Initialize spatial environment with OSM graph.
    
    Args:
        config: SimulationConfig instance
        progress_callback: Optional callback(progress: float, message: str)
    
    Returns:
        Configured SpatialEnvironment
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
            west, south, east, north = config.extended_bbox
            logger.info(f"Loading extended region: bbox {config.extended_bbox}")
            env.load_osm_graph(bbox=(north, south, east, west), use_cache=True)
            region_name = "Central Scotland"
        elif config.place:
            logger.info(f"Loading city: {config.place}")
            env.load_osm_graph(place=config.place, use_cache=True)
            region_name = config.place
        else:
            logger.warning("No place or bbox specified")
            return env
        
        stats = env.get_graph_stats()
        logger.info(f"✅ Loaded {region_name}: {stats['nodes']:,} nodes")
        
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


def setup_infrastructure(config: SimulationConfig, progress_callback=None) -> Optional[InfrastructureManager]:
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
    
    metrics = infrastructure.get_infrastructure_metrics()
    logger.info(f"✅ Infrastructure: {metrics['charging_stations']} stations, "
                f"{metrics['total_ports']} ports, {metrics['depots']} depots")
    
    if progress_callback:
        progress_callback(0.3, "✅ Infrastructure ready")
    
    return infrastructure