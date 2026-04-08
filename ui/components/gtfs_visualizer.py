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
import math
from typing import Any, List, Optional, Dict

logger = logging.getLogger(__name__)

try:
    import pydeck as pdk
    _PDK = True
except ImportError:
    _PDK = False
    logger.warning("pydeck not available — GTFS layers disabled")

# ── Straight-line threshold for edges without shape geometry ─────────────────
# BODS shapes.txt is incomplete for many routes.  When shape_coords is missing
# the fallback is a 2-point straight line between stops, which draws visibly
# across roads, parks and open water.
#
# 0.08 km (80 m) — only render shapeless edges for stops that are essentially
# adjacent (e.g. two stops on the same block).  Anything longer produces a
# visible straight diagonal that misrepresents the real route.  The previous
# value of 0.3 km let 300 m diagonals through, causing the "routes crossing
# land" artefact seen in the GTFS display PDF.
_MAX_SHAPELESS_KM: float = 0.08


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Haversine distance in km between two (lon, lat) points."""
    R = 6371.0
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


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
    # Deduplicate: when multiple parallel edges share the same stop pair AND the
    # same shape geometry (common for services with multiple trips), only render
    # once.  This reduces PathLayer row count from ~10k to a few hundred for
    # typical BODS feeds, which dramatically improves map rendering performance.
    _seen_paths: set = set()

    for u, v, attrs in G_transit.edges(data=True):
        mode     = attrs.get('mode', 'bus')
        fuel     = attrs.get('fuel_type', 'diesel')
        headway  = attrs.get('headway_s', 3600)
        shape    = attrs.get('shape_coords', [])

        # ── Skip transfer / walk edges injected by build_transfer_edges() ──
        # These carry mode='walk', highway='transfer', headway_s=0 and must
        # never appear as coloured service lines on the map.
        if mode == 'walk' or attrs.get('highway') == 'transfer':
            continue

        if show_electric_only and fuel not in ('electric', 'hydrogen'):
            continue

        if not shape:
            u_d = G_transit.nodes.get(u, {})
            v_d = G_transit.nodes.get(v, {})
            u_lon, u_lat = u_d.get('x', 0), u_d.get('y', 0)
            v_lon, v_lat = v_d.get('x', 0), v_d.get('y', 0)
            # Skip long shapeless edges — they draw straight lines across water.
            # BODS shapes.txt is missing for many cross-Forth bus services.
            if _haversine_km(u_lon, u_lat, v_lon, v_lat) > _MAX_SHAPELESS_KM:
                continue
            shape = [[u_lon, u_lat], [v_lon, v_lat]]

        color = _mode_color(mode, fuel)

        # Deduplicate: skip if this (u, v, mode) combination already rendered.
        # Parallel edges for the same stop pair and mode add visual noise without
        # information value — only the first (best-shape) edge is needed.
        _edge_key = (u, v, mode)
        if _edge_key in _seen_paths:
            continue
        _seen_paths.add(_edge_key)

        # ── Build a meaningful service label ────────────────────────────────
        short_names = attrs.get('route_short_names', [])
        long_names  = attrs.get('route_long_names',  [])
        if short_names:
            service_label = ' / '.join(short_names[:4])
        elif long_names:
            service_label = long_names[0][:40]
        else:
            service_label = mode.replace('_', ' ').title()

        # ── Headway display — guard against zero (transfer edge artefact) ──
        if headway > 0:
            headway_str = f"{headway // 60} min"
        else:
            headway_str = "on-demand"

        path_data.append({
            'path':    [[float(lon), float(lat)] for lon, lat in shape],
            'color':   color,
            'width':   max(1, 8 - headway // 600),   # more frequent = wider line
            'tooltip_html': (
                f"<b>{service_label}</b><br/>"
                f"{mode.replace('_', ' ').title()} · {fuel}<br/>"
                f"Headway: {headway_str}"
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

        # ── Skip pure walk/transfer nodes (OSM walk graph nodes stitched in) ─
        # These have no route_types, no name, and are not GTFS stop_ids.
        if not attrs.get('stop_id') and not attrs.get('name'):
            continue

        # Collect served route short names from outgoing service edges
        served_shorts: list = []
        for _, _, edata in G_transit.edges(stop_id, data=True):
            if edata.get('mode', 'walk') == 'walk' or edata.get('highway') == 'transfer':
                continue
            for sn in edata.get('route_short_names', []):
                if sn and sn not in served_shorts:
                    served_shorts.append(sn)
        routes_str = ', '.join(served_shorts[:6]) if served_shorts else ''

        # Compute average headway across all outgoing service edges
        out_edges = [
            d for _, _, d in G_transit.edges(stop_id, data=True)
            if d.get('mode', 'walk') != 'walk' and d.get('highway') != 'transfer'
        ]
        if out_edges:
            avg_headway = sum(d.get('headway_s', 3600) for d in out_edges) / len(out_edges)
        else:
            avg_headway = 3600

        # Radius: frequent stops bigger (headway 120s → max, 3600s → min)
        freq_ratio = max(0.0, min(1.0, 1.0 - (avg_headway - 120) / 3480))
        radius_px  = min_radius_px + int(freq_ratio * (max_radius_px - min_radius_px))

        wheelchair = attrs.get('wheelchair', False)
        name       = attrs.get('name', stop_id)
        headway_str = f"{int(avg_headway // 60)} min" if avg_headway > 0 else "on-demand"

        stop_data.append({
            'lon':         float(lon),
            'lat':         float(lat),
            'radius_px':   radius_px,
            'r': 255, 'g': 200, 'b': 50,   # amber fill for all stops
            'tooltip_html': (
                f"<b>{name}</b><br/>"
                + (f"Routes: {routes_str}<br/>" if routes_str else '')
                + f"Avg headway: {headway_str}"
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