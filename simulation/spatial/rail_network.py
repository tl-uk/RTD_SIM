"""
simulation/spatial/rail_network.py

Handles fetching and processing of rail/tram infrastructure via OSMnx.
Includes logic for 'Transfer Nodes' to link rail and road layers.
"""

import osmnx as ox
import networkx as nx
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

def fetch_rail_graph(bbox: Tuple[float, float, float, float]) -> Optional[nx.MultiDiGraph]:
    """
    Downloads rail/tram infrastructure using OpenRailMap filters.
    bbox: (north, south, east, west)
    """
    # Canonical OpenRailMap filters
    rail_filter = '["railway"~"rail|tram|subway|light_rail"]'
    
    try:
        G_rail = ox.graph_from_bbox(
            bbox[0], bbox[1], bbox[2], bbox[3],
            custom_filter=rail_filter,
            retain_all=True,
            simplify=True
        )
        logger.info(f"Successfully fetched rail graph with {len(G_rail.nodes)} nodes.")
        return G_rail
    except Exception as e:
        logger.error(f"Failed to fetch rail data: {e}")
        return None

def link_to_road_network(G_rail: nx.MultiDiGraph, G_road: nx.MultiDiGraph, radius_m: int = 300):
    """
    Creates virtual 'Transfer Edges' between rail stations and the nearest road nodes.
    This allows agents to 'walk' to the station in the simulation.
    """
    stations = [n for n, d in G_rail.nodes(data=True) if d.get('railway') == 'station']
    links_added = 0
    
    for station in stations:
        point = (G_rail.nodes[station]['y'], G_rail.nodes[station]['x'])
        # Find nearest node in the road graph
        target_road_node = ox.distance.nearest_nodes(G_road, point[1], point[0])
        
        # Add a bi-directional walking link with a time penalty (10 mins / 0.16 hours)
        # Using a synthetic length to represent the 'transfer cost'
        G_rail.add_edge(station, target_road_node, length=radius_m, highway='transfer', time_h=0.16)
        G_road.add_edge(target_road_node, station, length=radius_m, highway='transfer', time_h=0.16)
        links_added += 1
        
    logger.info(f"Linked {links_added} stations to the road network.")