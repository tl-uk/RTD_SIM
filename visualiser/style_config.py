# visualiser/style_config.py
"""
Visualization styling configuration for Phase 2.3

Centralizes all colors, sizes, and visual parameters.
"""

from typing import Dict, List, Tuple

# Mode colors (RGB 0-255)
MODE_COLORS = {
    'walk': [34, 197, 94],    # Green
    'bike': [59, 130, 246],    # Blue
    'bus': [245, 158, 11],     # Orange
    'car': [239, 68, 68],      # Red
    'ev': [168, 85, 245],      # Purple
}

# Mode colors as hex (for legends, etc.)
MODE_COLORS_HEX = {
    'walk': '#22c55e',
    'bike': '#3b82f6',
    'bus': '#f59e0b',
    'car': '#ef4444',
    'ev': '#a855f7',
}

# Agent marker styling
AGENT_RADIUS_PIXELS = 8
AGENT_OPACITY = 0.8

# Route line styling
ROUTE_WIDTH_PIXELS = 3
ROUTE_OPACITY = 0.6

# Congestion heatmap colors (normalized 0-1 to RGB)
def get_congestion_color(factor: float) -> List[int]:
    """
    Map congestion factor to color gradient.
    
    Args:
        factor: Congestion factor (1.0 = no congestion, 3.0 = max)
    
    Returns:
        RGB color [0-255, 0-255, 0-255]
    """
    # Normalize to 0-1 range
    normalized = min(1.0, max(0.0, (factor - 1.0) / 2.0))
    
    # Green (no congestion) -> Yellow -> Red (high congestion)
    if normalized < 0.5:
        # Green to Yellow
        r = int(255 * (normalized * 2))
        g = 255
        b = 0
    else:
        # Yellow to Red
        r = 255
        g = int(255 * (1 - (normalized - 0.5) * 2))
        b = 0
    
    return [r, g, b]

# Congestion line width (thicker = more congested)
CONGESTION_MIN_WIDTH = 2
CONGESTION_MAX_WIDTH = 10

def get_congestion_width(factor: float) -> float:
    """Map congestion factor to line width."""
    normalized = min(1.0, (factor - 1.0) / 2.0)
    return CONGESTION_MIN_WIDTH + (CONGESTION_MAX_WIDTH - CONGESTION_MIN_WIDTH) * normalized

# 3D building colors
BUILDING_COLOR = [200, 200, 200, 180]  # RGBA
BUILDING_ELEVATION_SCALE = 1.0

# Map view defaults
DEFAULT_VIEW_STATE = {
    'latitude': 55.9533,
    'longitude': -3.1883,
    'zoom': 12,
    'pitch': 0,
    'bearing': 0,
}

ANIMATION_VIEW_STATE = {
    'latitude': 55.9533,
    'longitude': -3.1883,
    'zoom': 13,
    'pitch': 0,  # Keep flat for better compatibility
    'bearing': 0,
}

# Default map style (Carto - no API key needed)
DEFAULT_MAP_STYLE = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"

# Layer z-order (higher = on top)
Z_ORDER = {
    'network': 0,
    'congestion': 1,
    'routes': 2,
    'agents': 3,
    'labels': 4,
}

# Tooltip styling
TOOLTIP_STYLE = {
    'backgroundColor': 'rgba(0, 0, 0, 0.8)',
    'color': 'white',
    'fontSize': '12px',
    'padding': '8px',
    'borderRadius': '4px',
}