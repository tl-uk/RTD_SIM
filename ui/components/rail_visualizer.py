"""
ui/components/rail_visualizer.py

Pydeck layer definitions for the rail/tram network.
"""

import pydeck as pdk
import osmnx as ox

def create_rail_layer(G_rail):
    """
    Converts a NetworkX rail graph into a Pydeck GeoJsonLayer.
    """
    if G_rail is None:
        return None
        
    # Convert edges to GeoDataFrame
    _, edges = ox.graph_to_gdfs(G_rail)
    
    return pdk.Layer(
        "GeoJsonLayer",
        edges.__geo_interface__,
        get_line_color=[255, 140, 0, 150],  # Distinct Orange for Rail
        get_line_width=3,
        pickable=True,
        auto_highlight=True,
    )

def create_train_path_layer(path_coords):
    """
    Visualizes the active path of a train agent.
    path_coords: List of [lon, lat] tuples following track geometry.
    """
    return pdk.Layer(
        "PathLayer",
        [{"path": path_coords}],
        get_color=[255, 255, 255],  # White for active routing
        width_min_pixels=4,
        rounded=True
    )