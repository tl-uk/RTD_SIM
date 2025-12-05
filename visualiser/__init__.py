# visualiser/__init__.py
"""
RTD_SIM Phase 2.3 - Advanced Visualization Module

Provides:
- Animated agent movement visualization
- Congestion heatmaps
- Interactive playback controls
- Time series analysis
"""

from visualiser.animation_controller import AnimationController, LayerManager
from visualiser.data_adapters import (
    AgentDataAdapter,
    RouteDataAdapter,
    CongestionDataAdapter,
    TimeSeriesStorage,
)
from visualiser.style_config import (
    MODE_COLORS,
    MODE_COLORS_HEX,
    get_congestion_color,
    get_congestion_width,
)

__all__ = [
    'AnimationController',
    'LayerManager',
    'AgentDataAdapter',
    'RouteDataAdapter',
    'CongestionDataAdapter',
    'TimeSeriesStorage',
    'MODE_COLORS',
    'MODE_COLORS_HEX',
    'get_congestion_color',
    'get_congestion_width',
]

__version__ = '2.3.0'