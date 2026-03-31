"""
ui/components/gtfs_visualizer.py

Pydeck layer definitions for GTFS transit data:
  - Service paths (PathLayer)   — coloured by mode and fuel type
  - Stop markers (ScatterplotLayer) — sized by service frequency

These layers sit on top of the OpenRailMap GeoJsonLayer and beneath
the agent ScatterplotLayer in the map stack.

Color scheme is intentionally distinct from MODE_COLORS_RGB in
visualization.py so GTFS service lines read clearly on the base map.
"""

from __future__ import annotations
import logging
from typing import Any, List, Optional, Dict

logger = logging.getLogger(__name__)

try:
    import pydeck as pdk
    _PDK = True
except ImportError:
    _PDK = False
    logger.warning("pydeck not available — GTFS layers disabled")


# ── Per-mode stroke colours (RGBA) ────────────────────────────────────────────
_MODE_PATH_COLORS: Dict[str, List[int]] = {
    'bus':             [245, 158, 11, 200],   # amber
    'tram':            [255, 220, 50, 220],   # yellow
    'local_train':     [33, 150, 243, 200],   # blue
    'intercity_train': [63, 81, 181, 200],    # indigo
    'ferry_diesel':    [0, 150, 136, 180],    # teal
    'ferry_electric':  [0, 210, 220, 200],    # cyan
}

_FUEL_BRIGHTNESS_BOOST = 40   # electric routes get this added to R, G, B


def _mode_color(mode: str, fuel: str) -> List[int]:
    base = _MODE_PATH_COLORS.get(mode, [128, 128, 128, 180])
    color = base[:]
    if fuel == 'electric':
        color = [min(255, c + _FUEL_BRIGHTNESS_BOOST) for c in color[:3]] + [color[3]]
    return color


def create_gtfs_service_layer(
    G_transit: Any,
    show_electric_only: bool = False,
) -> Optional[Any]:
    """
    Build a pydeck PathLayer showing GTFS service route geometries.

    Each edge in the transit graph contributes one path segment.  Where
    shapes.txt was present in the feed the path follows the real vehicle
    trajectory; otherwise a straight line between stops is used.

    Args:
        G_transit:           NetworkX transit graph from GTFSGraph.build()
        show_electric_only:  If True, only render zero-emission routes.

    Returns:
        pydeck.Layer or None if unavailable.
    """
    if not _PDK or G_transit is None:
        return None

    path_data = []

    for u, v, attrs in G_transit.edges(data=True):
        mode     = attrs.get('mode', 'bus')
        fuel     = attrs.get('fuel_type', 'diesel')
        headway  = attrs.get('headway_s', 3600)
        shape    = attrs.get('shape_coords', [])

        if show_electric_only and fuel not in ('electric', 'hydrogen'):
            continue

        if not shape:
            u_d = G_transit.nodes.get(u, {})
            v_d = G_transit.nodes.get(v, {})
            shape = [
                [u_d.get('x', 0), u_d.get('y', 0)],
                [v_d.get('x', 0), v_d.get('y', 0)],
            ]

        color = _mode_color(mode, fuel)

        path_data.append({
            'path':    [[float(lon), float(lat)] for lon, lat in shape],
            'color':   color,
            'width':   max(1, 8 - headway // 600),   # more frequent = wider line
            'tooltip': (
                f"<b>{mode.replace('_', ' ').title()}</b><br/>"
                f"Fuel: {fuel}<br/>"
                f"Headway: {headway // 60} min"
            ),
        })

    if not path_data:
        return None

    return pdk.Layer(
        'PathLayer',
        data           = path_data,
        get_path       = 'path',
        get_color      = 'color',
        get_width      = 'width',
        width_min_pixels = 1,
        width_max_pixels = 8,
        pickable       = True,
        auto_highlight = True,
        highlight_color = [255, 255, 255, 80],
    )


def create_gtfs_stops_layer(
    G_transit: Any,
    min_radius_px: int = 3,
    max_radius_px: int = 9,
) -> Optional[Any]:
    """
    Build a pydeck ScatterplotLayer showing GTFS stop locations.

    Stop radius scales with service frequency (inverse of average headway
    across all edges at that stop).  High-frequency interchanges appear as
    larger dots; hourly rural stops as tiny dots.

    Args:
        G_transit:     NetworkX transit graph from GTFSGraph.build()
        min_radius_px: Minimum rendered radius in pixels.
        max_radius_px: Maximum rendered radius in pixels.

    Returns:
        pydeck.Layer or None.
    """
    if not _PDK or G_transit is None:
        return None

    stop_data = []

    for stop_id, attrs in G_transit.nodes(data=True):
        lon = attrs.get('x', 0)
        lat = attrs.get('y', 0)
        if lon == 0 and lat == 0:
            continue

        # Compute average headway across all outgoing edges
        out_edges = list(G_transit.edges(stop_id, data=True))
        if out_edges:
            avg_headway = sum(
                d.get('headway_s', 3600) for _, _, d in out_edges
            ) / len(out_edges)
        else:
            avg_headway = 3600

        # Radius: frequent stops bigger (headway 120s → max, 3600s → min)
        freq_ratio = max(0.0, min(1.0, 1.0 - (avg_headway - 120) / 3480))
        radius_px  = min_radius_px + int(freq_ratio * (max_radius_px - min_radius_px))

        wheelchair = attrs.get('wheelchair', False)
        name       = attrs.get('name', stop_id)

        stop_data.append({
            'lon':         float(lon),
            'lat':         float(lat),
            'radius_px':   radius_px,
            'r': 255, 'g': 200, 'b': 50,   # amber fill for all stops
            'tooltip_html':     (
                f"<b>{name}</b><br/>"
                f"Stop ID: {stop_id}<br/>"
                f"Avg headway: {int(avg_headway // 60)} min"
                + ("<br/>♿ Wheelchair accessible" if wheelchair else "")
            ),
        })

    if not stop_data:
        return None

    return pdk.Layer(
        'ScatterplotLayer',
        data              = stop_data,
        get_position      = '[lon, lat]',
        get_fill_color    = '[r, g, b, 220]',
        get_radius        = 'radius_px',
        radius_min_pixels = min_radius_px,
        radius_max_pixels = max_radius_px,
        pickable          = True,
        stroked           = True,
        line_width_min_pixels = 0,
    )