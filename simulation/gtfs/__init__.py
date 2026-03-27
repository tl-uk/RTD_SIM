"""
simulation/gtfs

GTFS integration layer for RTD_SIM.

Exposes:
    GTFSLoader    — parse static GTFS feeds (zip or directory)
    GTFSGraph     — build NetworkX transit graph from loader output
    load_gtfs     — convenience one-liner

Example usage:
    from simulation.gtfs import load_gtfs

    G_transit, loader = load_gtfs(
        feed_path='data/gtfs/scotrail.zip',
        headway_window=(25200, 34200),   # 07:00–09:30
        service_date='20250401',
    )
    graph_manager.graphs['transit'] = G_transit
"""

from simulation.gtfs.gtfs_loader import GTFSLoader
from simulation.gtfs.gtfs_graph import GTFSGraph
from simulation.gtfs.gtfs_analytics import (
    transit_desert_analysis,
    electrification_opportunity_ranking,
    modal_shift_threshold_analysis,
    emissions_hotspot_detection,
    run_full_gtfs_analysis,
)
from typing import Optional, Tuple, Any


def load_gtfs(
    feed_path: str,
    headway_window: Optional[Tuple[int, int]] = None,
    service_date: Optional[str] = None,
    fuel_overrides: Optional[dict] = None,
    walk_graph: Optional[Any] = None,
) -> Tuple[Optional[Any], GTFSLoader]:
    """
    One-liner: parse a GTFS feed, build the transit graph, and (optionally)
    stitch transfer edges to an OSM walk graph.

    Args:
        feed_path:       Path to GTFS .zip or directory
        headway_window:  (start_s, end_s) for headway computation.
                         Defaults to AM peak 07:00–09:30.
        service_date:    'YYYYMMDD' — filter to services active on this date.
                         None = load all services.
        fuel_overrides:  {route_id: 'electric'|'diesel'|'hydrogen'}
        walk_graph:      OSMnx walk graph — if provided, transfer edges are
                         added so agents can walk to/from stops.

    Returns:
        (G_transit, loader) — the NetworkX graph and the raw loader
        G_transit is None if NetworkX is unavailable.
    """
    loader = GTFSLoader(
        feed_path,
        fuel_overrides=fuel_overrides,
        service_date=service_date,
    ).load()

    headways = loader.compute_headways(time_window=headway_window)
    builder  = GTFSGraph(loader, headways)
    G        = builder.build()

    if G is not None and walk_graph is not None:
        builder.build_transfer_edges(G, walk_graph)

    return G, loader


__all__ = [
    'GTFSLoader', 'GTFSGraph', 'load_gtfs',
    'transit_desert_analysis',
    'electrification_opportunity_ranking',
    'modal_shift_threshold_analysis',
    'emissions_hotspot_detection',
    'run_full_gtfs_analysis',
]