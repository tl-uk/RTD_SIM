"""
visualiser/transit_layers.py

Unified pydeck layer builder for all transit network overlays.

REPLACES ui/components/rail_visualizer.py (which is now a thin shim
that imports create_rail_layer from here for backwards compatibility).

Layers produced
───────────────
  Rail (mainline)     — dark grey/charcoal PathLayer, width 3 px
  Tram / light rail   — amber PathLayer, width 2 px
  Subway              — purple PathLayer, width 2 px
  Bus corridors       — orange dashed PathLayer (GTFS shapes or OSM route relations)
  Ferry routes        — teal arc PathLayer (from ferry_network.py graph)
  Air routes          — grey great-circle arc PathLayer (abstract, between airports)
  Walk network        — green, thin, only when explicitly requested (rarely shown)
  Cycle network       — blue, thin PathLayer
  Contraflow cycling  — bright cyan dashed PathLayer
  Contraflow bus      — bright orange dashed PathLayer
  Transit stops       — ScatterplotLayer (dots, colour-coded by mode)

Data sources (with / without GTFS)
────────────────────────────────────
  With GTFS:
    Bus/tram shape geometry → GTFS transit graph edge shape_coords
    Stop positions          → GTFS transit graph node x/y
    Service labels          → GTFS route_short_names edge attribute

  Without GTFS:
    Rail / tram / subway    → OSMnx graph loaded by rail_network.fetch_rail_graph()
    Bus corridors           → Overpass route=bus relations (fetch on demand, cached)
    Stop positions          → transit_stop_loader.load_transit_stops() (Overpass)
    Ferry routes            → ferry_network.py graph (already used by router)

One-way / contraflow
──────────────────────
  OSMnx graphs respect edge direction (oneway= tags are baked in during
  graph construction).  The contraflow layers make the invisible bidirectional
  exception visible:
    - Contraflow cycle lanes: fetched from transit_stop_loader.fetch_contraflow_cycling()
    - Contraflow bus lanes:   fetched from transit_stop_loader.fetch_contraflow_bus()
  These layers are informational overlays only (they do not modify routing).
  Routing already works correctly because OSMnx builds the cycle/walk graph
  with oneway:bicycle=no respected.

Public API
──────────
  create_transit_network_layers(env, options) -> Dict[str, pdk.Layer]
      Returns a dict of named pydeck layers.  The caller (render_map) inserts
      them into the deck in the correct Z-order (infrastructure first).

  create_rail_layer(G_rail) -> Optional[pdk.Layer]
      Thin compatibility shim kept for the existing import in visualization.py.

  get_stop_layer(stops_by_mode, mode_families) -> Optional[pdk.Layer]
      ScatterplotLayer of transit stop positions.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import pydeck as pdk
    _PDK = True
except ImportError:
    _PDK = False
    logger.warning("pydeck not available — transit_layers will return None for all layers")

try:
    import pandas as pd
    _PD = True
except ImportError:
    _PD = False

# ── Colour palette ─────────────────────────────────────────────────────────────
# RGBA tuples.  All transit infrastructure layers sit beneath agent markers
# (lower Z-order) and use semi-transparency so they don't obscure the agents.

_COLOURS = {
    # Track / route lines
    "rail":              [60,  60,  60,  200],   # charcoal — mainline rail
    "tram":              [220, 160,  30,  200],   # amber — tram / light rail
    "subway":            [140,  40, 180,  200],   # purple — metro / subway
    "bus_corridor":      [245, 130,  30,  160],   # orange — bus route shapes
    "ferry":             [  0, 130, 110,  180],   # teal — ferry (matches ferry_network)
    "air":               [180, 180, 200,  130],   # steel grey — great-circle arc
    "walk":              [ 34, 197,  94,  120],   # green — footways
    "cycle":             [ 59, 130, 246,  140],   # blue — cycleways
    "contraflow_cycle":  [  0, 230, 230,  220],   # bright cyan
    "contraflow_bus":    [255, 140,   0,  220],   # bright orange

    # Stop / station dots
    "stop_rail":         [ 60,  60,  60,  230],
    "stop_tram":         [220, 160,  30,  230],
    "stop_subway":       [140,  40, 180,  230],
    "stop_bus":          [245, 130,  30,  200],
    "stop_ferry":        [  0, 130, 110,  220],
}

_WIDTHS = {
    "rail":            3,
    "tram":            2,
    "subway":          2,
    "bus_corridor":    1,
    "ferry":           2,
    "air":             1,
    "walk":            1,
    "cycle":           1,
    "contraflow_cycle":2,
    "contraflow_bus":  2,
}

_STOP_RADIUS = {
    "rail":   120,   # metres (visible at zoom 12)
    "tram":    60,
    "subway":  80,
    "bus":     35,
    "ferry":  100,
}


# ── Geometry helpers ───────────────────────────────────────────────────────────

def _edge_to_path(G, u, v, data: dict) -> List[List[float]]:
    """
    Extract [lon, lat] point list from a NetworkX edge.
    Prefers Shapely LineString geometry; falls back to endpoint nodes.
    """
    geom = data.get("geometry")
    if geom is not None and hasattr(geom, "coords"):
        return [[float(c[0]), float(c[1])] for c in geom.coords]

    shape = data.get("shape_coords")
    if shape:
        return [[float(c[0]), float(c[1])] for c in shape]

    # Endpoint fallback — straight line between nodes
    try:
        u_d = G.nodes[u]
        v_d = G.nodes[v]
        return [
            [float(u_d["x"]), float(u_d["y"])],
            [float(v_d["x"]), float(v_d["y"])],
        ]
    except (KeyError, TypeError):
        return []


def _graph_to_path_rows(
    G,
    railway_filter: Optional[str] = None,
) -> List[Dict]:
    """
    Convert all edges of a NetworkX MultiDiGraph to path dicts for pydeck.

    Args:
        G:                NetworkX graph.
        railway_filter:   If set, only include edges where data['railway']
                          matches this value (e.g. 'tram', 'rail').
    """
    rows = []
    if G is None:
        return rows
    seen_edges = set()   # avoid duplicate forward/reverse edges
    for u, v, _key, data in G.edges(keys=True, data=True):
        canonical = (min(u, v), max(u, v))
        if canonical in seen_edges:
            continue
        seen_edges.add(canonical)

        if railway_filter:
            if data.get("railway") != railway_filter and data.get("mode") != railway_filter:
                continue

        path = _edge_to_path(G, u, v, data)
        if len(path) >= 2:
            rows.append({"path": path, "name": data.get("name", "")})
    return rows


def _coords_to_path_rows(
    polylines: List[List[Tuple[float, float]]],
) -> List[Dict]:
    """Convert a list of (lon,lat) polylines to path dicts."""
    return [
        {"path": [[float(c[0]), float(c[1])] for c in pl]}
        for pl in polylines
        if len(pl) >= 2
    ]


def _make_path_layer(
    rows: List[Dict],
    layer_id: str,
    colour: List[int],
    width_px: int = 2,
    dashed: bool = False,
) -> Optional[Any]:
    """
    Build a pydeck PathLayer from a list of {path, name} dicts.
    Returns None if pydeck or pandas is unavailable, or rows is empty.
    """
    if not _PDK or not _PD or not rows:
        return None
    df = pd.DataFrame(rows)
    kwargs = dict(
        id=layer_id,
        data=df,
        get_path="path",
        get_color=colour,
        width_min_pixels=width_px,
        width_max_pixels=width_px + 1,
        pickable=False,
    )
    if dashed:
        # pydeck PathLayer supports dash_array via get_dash_array
        kwargs["get_dash_array"] = [6, 4]
        kwargs["dash_justified"] = True
    return pdk.Layer("PathLayer", **kwargs)


# ── GTFS shape extraction ──────────────────────────────────────────────────────

def _gtfs_shapes_for_mode(G_transit, mode: str) -> List[Dict]:
    """
    Extract route shape polylines from the GTFS transit graph for a given mode.

    The transit graph stores shape_coords on each edge and route_short_names
    as a list.  We deduplicate shapes per route to avoid drawing the same
    line for both directions.
    """
    if G_transit is None:
        return []

    rows = []
    seen_shapes: set = set()

    for u, v, _key, data in G_transit.edges(keys=True, data=True):
        if data.get("mode") != mode:
            continue
        shape = data.get("shape_coords") or []
        if len(shape) < 2:
            continue
        # Use first+last coord as a cheap deduplication key
        shape_key = (shape[0], shape[-1])
        rev_key   = (shape[-1], shape[0])
        if shape_key in seen_shapes or rev_key in seen_shapes:
            continue
        seen_shapes.add(shape_key)

        names = data.get("route_short_names", [])
        label = ", ".join(str(n) for n in names[:3]) if names else ""
        rows.append({
            "path": [[float(c[0]), float(c[1])] for c in shape],
            "name": label,
        })

    return rows


# ── Bus route relations fetch ──────────────────────────────────────────────────

def _fetch_bus_route_relations(
    south: float, west: float, north: float, east: float,
    timeout_s: int = 30,
) -> List[Dict]:
    """
    Fetch OSM route=bus relations from Overpass and return path rows.
    Used when GTFS is not loaded to draw bus corridor shapes.
    Cached at module level per session (one bbox per run).
    """
    global _BUS_ROUTES_CACHE, _BUS_ROUTES_FETCHED
    if _BUS_ROUTES_FETCHED:
        return _BUS_ROUTES_CACHE

    _BUS_ROUTES_FETCHED = True

    from urllib import parse as _up, request as _ur, error as _ue
    import json

    query = (
        f"[out:json][timeout:{timeout_s}];\n"
        f"relation[\"route\"=\"bus\"]({south},{west},{north},{east});\n"
        "out body geom;"
    )
    body = _up.urlencode({"data": query}).encode("utf-8")

    try:
        req = _ur.Request(
            "https://overpass-api.de/api/interpreter",
            data=body, method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "RTD_SIM_TransitLayers/1.0",
            },
        )
        with _ur.urlopen(req, timeout=timeout_s + 5) as resp:
            raw = json.loads(resp.read())
    except Exception as exc:
        logger.warning("transit_layers: bus route fetch failed: %s", exc)
        _BUS_ROUTES_CACHE = []
        return []

    rows = []
    for el in raw.get("elements", []):
        if el.get("type") != "relation":
            continue
        coords = []
        for member in el.get("members", []):
            if member.get("type") != "way":
                continue
            for pt in member.get("geometry", []):
                try:
                    coords.append([float(pt["lon"]), float(pt["lat"])])
                except (KeyError, TypeError):
                    continue
        if len(coords) >= 2:
            tags = el.get("tags", {})
            rows.append({
                "path": coords,
                "name": tags.get("ref", tags.get("name", "")),
            })

    logger.info("transit_layers: %d bus route relations from Overpass", len(rows))
    _BUS_ROUTES_CACHE = rows
    return rows


_BUS_ROUTES_CACHE: List[Dict] = []
_BUS_ROUTES_FETCHED: bool = False


# ── Public API ─────────────────────────────────────────────────────────────────

def create_transit_network_layers(
    env=None,
    show_rail:             bool = True,
    show_tram:             bool = True,
    show_subway:           bool = False,
    show_bus_corridors:    bool = False,
    show_ferry:            bool = True,
    show_air:              bool = False,
    show_walk:             bool = False,
    show_cycle:            bool = False,
    show_contraflow:       bool = False,
    show_stops:            bool = False,
    use_gtfs:              bool = True,
) -> Dict[str, Any]:
    """
    Build all transit network pydeck layers for the map overlay.

    Args:
        env:                SpatialEnvironment (provides graph_manager, bbox,
                            and optionally the GTFS transit graph).
        show_*:             Toggle individual layer families.
        use_gtfs:           If True, prefer GTFS shape_coords over OSMnx geometry.
                            Ignored when GTFS graph is not loaded.

    Returns:
        Dict mapping layer name → pdk.Layer (or None if unavailable).
        The caller (render_map) filters for non-None and inserts at Z=0.

    Layer Z-order (insert lowest first):
        rail → tram → subway → bus_corridors → ferry → air
        → walk → cycle → contraflow → stops → agents (top)
    """
    layers: Dict[str, Any] = {}

    if not _PDK:
        return layers

    # ── Resolve graphs from env ───────────────────────────────────────────────
    gm          = getattr(env, "graph_manager", None)
    G_rail      = gm.get_graph("rail")      if gm else None
    G_tram      = gm.get_graph("tram")      if gm else None
    G_walk      = gm.get_graph("walk")      if gm else None
    G_bike      = gm.get_graph("bike")      if gm else None
    G_ferry     = gm.get_graph("ferry")     if gm else None
    G_transit   = None
    if use_gtfs and env is not None:
        _router = getattr(env, "router", getattr(env, "_router", None))
        if _router is not None:
            G_transit = getattr(_router, "_transit_graph", None)
            if G_transit is None and hasattr(_router, "_get_transit_graph"):
                try:
                    G_transit = _router._get_transit_graph()
                except Exception:
                    pass

    # ── Bbox for Overpass queries ─────────────────────────────────────────────
    bbox_sw_ne: Optional[Tuple[float, float, float, float]] = None  # (south, west, north, east)
    if env is not None:
        G_drive = gm.get_graph("drive") if gm else None
        if G_drive is not None and len(G_drive.nodes) > 0:
            xs = [d["x"] for _, d in G_drive.nodes(data=True)]
            ys = [d["y"] for _, d in G_drive.nodes(data=True)]
            bbox_sw_ne = (min(ys), min(xs), max(ys), max(xs))

    south = bbox_sw_ne[0] if bbox_sw_ne else 55.85
    west  = bbox_sw_ne[1] if bbox_sw_ne else -3.40
    north = bbox_sw_ne[2] if bbox_sw_ne else 56.00
    east  = bbox_sw_ne[3] if bbox_sw_ne else -3.05

    # ── Rail ──────────────────────────────────────────────────────────────────
    if show_rail:
        rows = []
        if G_transit and use_gtfs:
            rows = _gtfs_shapes_for_mode(G_transit, "local_train")
            rows += _gtfs_shapes_for_mode(G_transit, "intercity_train")
            rows += _gtfs_shapes_for_mode(G_transit, "freight_rail")
        if not rows and G_rail is not None:
            # OSMnx rail graph — exclude tram edges so they appear only in tram layer
            rows = [
                r for r in _graph_to_path_rows(G_rail)
                # Include all unless we have a dedicated tram graph (avoids duplication)
            ]
        layers["rail"] = _make_path_layer(rows, "rail_layer", _COLOURS["rail"], _WIDTHS["rail"])

    # ── Tram ──────────────────────────────────────────────────────────────────
    if show_tram:
        rows = []
        if G_transit and use_gtfs:
            rows = _gtfs_shapes_for_mode(G_transit, "tram")
        if not rows and G_tram is not None:
            rows = _graph_to_path_rows(G_tram, railway_filter="tram")
            if not rows:
                rows = _graph_to_path_rows(G_tram)
        if not rows and G_rail is not None:
            # Extract tram edges from the combined rail graph
            rows = _graph_to_path_rows(G_rail, railway_filter="tram")
        if not rows and bbox_sw_ne:
            # Overpass route=tram relations as last resort
            try:
                from simulation.spatial.rail_network import fetch_tram_relations_overpass
                _bbox_n_s_e_w = (north, south, east, west)  # rail_network convention
                polylines = fetch_tram_relations_overpass(_bbox_n_s_e_w)
                rows = _coords_to_path_rows(polylines)
            except Exception as exc:
                logger.debug("transit_layers: tram overpass fallback failed: %s", exc)
        layers["tram"] = _make_path_layer(rows, "tram_layer", _COLOURS["tram"], _WIDTHS["tram"])

    # ── Subway ────────────────────────────────────────────────────────────────
    if show_subway:
        rows = []
        if G_transit and use_gtfs:
            rows = _gtfs_shapes_for_mode(G_transit, "subway")
        if not rows and G_rail is not None:
            rows = _graph_to_path_rows(G_rail, railway_filter="subway")
        layers["subway"] = _make_path_layer(
            rows, "subway_layer", _COLOURS["subway"], _WIDTHS["subway"]
        )

    # ── Bus corridors ─────────────────────────────────────────────────────────
    if show_bus_corridors:
        rows = []
        if G_transit and use_gtfs:
            rows = _gtfs_shapes_for_mode(G_transit, "bus")
        if not rows and bbox_sw_ne:
            rows = _fetch_bus_route_relations(south, west, north, east)
        layers["bus_corridors"] = _make_path_layer(
            rows, "bus_corridor_layer",
            _COLOURS["bus_corridor"], _WIDTHS["bus_corridor"],
        )

    # ── Ferry ─────────────────────────────────────────────────────────────────
    if show_ferry and G_ferry is not None:
        rows = []
        if G_transit and use_gtfs:
            rows = (
                _gtfs_shapes_for_mode(G_transit, "ferry_diesel")
                + _gtfs_shapes_for_mode(G_transit, "ferry_electric")
            )
        if not rows:
            # ferry_network graph stores shape_coords on each edge
            for u, v, _key, data in G_ferry.edges(keys=True, data=True):
                shape = data.get("shape_coords") or []
                if len(shape) >= 2:
                    rows.append({
                        "path": [[float(c[0]), float(c[1])] for c in shape],
                        "name": data.get("name", ""),
                    })
                else:
                    path = _edge_to_path(G_ferry, u, v, data)
                    if len(path) >= 2:
                        rows.append({"path": path, "name": data.get("name", "")})
        layers["ferry"] = _make_path_layer(
            rows, "ferry_layer", _COLOURS["ferry"], _WIDTHS["ferry"]
        )

    # ── Air (great-circle arcs) ───────────────────────────────────────────────
    if show_air:
        rows = []
        try:
            from simulation.spatial.air_network import get_or_build_airport_graph
            G_air = get_or_build_airport_graph(
                bbox=(north, south, east, west)
            ) if env is not None else None
            if G_air is not None:
                for u, v, _key, data in G_air.edges(keys=True, data=True):
                    shape = data.get("shape_coords") or []
                    if len(shape) >= 2:
                        rows.append({
                            "path": [[float(c[0]), float(c[1])] for c in shape],
                            "name": data.get("name", ""),
                        })
                    else:
                        path = _edge_to_path(G_air, u, v, data)
                        if len(path) >= 2:
                            rows.append({"path": path, "name": ""})
        except Exception as exc:
            logger.debug("transit_layers: air graph failed: %s", exc)
        layers["air"] = _make_path_layer(
            rows, "air_layer", _COLOURS["air"], _WIDTHS["air"]
        )

    # ── Walk / Cycle (rarely shown — can be dense) ────────────────────────────
    if show_walk and G_walk is not None:
        rows = _graph_to_path_rows(G_walk)
        layers["walk"] = _make_path_layer(
            rows, "walk_layer", _COLOURS["walk"], _WIDTHS["walk"]
        )

    if show_cycle and G_bike is not None:
        rows = _graph_to_path_rows(G_bike)
        layers["cycle"] = _make_path_layer(
            rows, "cycle_layer", _COLOURS["cycle"], _WIDTHS["cycle"]
        )

    # ── Contraflow infrastructure ─────────────────────────────────────────────
    if show_contraflow and bbox_sw_ne:
        try:
            from simulation.spatial.transit_stop_loader import (
                fetch_contraflow_cycling,
                fetch_contraflow_bus,
            )
            cf_cycle = fetch_contraflow_cycling(south, west, north, east)
            if cf_cycle:
                cf_rows = [
                    {"path": [[float(c[0]), float(c[1])] for c in seg["coords"]]}
                    for seg in cf_cycle
                ]
                layers["contraflow_cycle"] = _make_path_layer(
                    cf_rows, "contraflow_cycle_layer",
                    _COLOURS["contraflow_cycle"], _WIDTHS["contraflow_cycle"],
                    dashed=True,
                )

            cf_bus = fetch_contraflow_bus(south, west, north, east)
            if cf_bus:
                cb_rows = [
                    {"path": [[float(c[0]), float(c[1])] for c in seg["coords"]]}
                    for seg in cf_bus
                ]
                layers["contraflow_bus"] = _make_path_layer(
                    cb_rows, "contraflow_bus_layer",
                    _COLOURS["contraflow_bus"], _WIDTHS["contraflow_bus"],
                    dashed=True,
                )
        except Exception as exc:
            logger.warning("transit_layers: contraflow fetch failed: %s", exc)

    # ── Transit stop markers ──────────────────────────────────────────────────
    if show_stops:
        stop_layer = _build_stop_layer(env, G_transit, south, west, north, east)
        if stop_layer is not None:
            layers["stops"] = stop_layer

    _log_layer_summary(layers)
    return layers


def _build_stop_layer(env, G_transit, south, west, north, east) -> Optional[Any]:
    """Build a ScatterplotLayer of all transit stop positions."""
    if not _PDK or not _PD:
        return None

    stop_rows = []

    # ── From GTFS transit graph ───────────────────────────────────────────────
    if G_transit is not None:
        for node_id, data in G_transit.nodes(data=True):
            mode = data.get("mode", "bus")
            x = data.get("x")
            y = data.get("y")
            if x is None or y is None:
                continue
            col = _COLOURS.get(f"stop_{mode}", _COLOURS["stop_bus"])
            stop_rows.append({
                "position": [float(x), float(y)],
                "color":    col,
                "name":     data.get("name", str(node_id)),
                "mode":     mode,
                "radius":   _STOP_RADIUS.get(mode, 40),
            })

    # ── From Overpass (no GTFS) ───────────────────────────────────────────────
    if not stop_rows:
        try:
            from simulation.spatial.transit_stop_loader import load_transit_stops
            bbox_convention = (north, south, east, west)   # RTD_SIM (n,s,e,w)
            stops_by_mode = load_transit_stops(
                bbox_convention,
                mode_families=["rail", "tram", "subway", "bus", "ferry"],
            )
            for mf, stops in stops_by_mode.items():
                col = _COLOURS.get(f"stop_{mf}", _COLOURS["stop_bus"])
                r   = _STOP_RADIUS.get(mf, 40)
                for s in stops:
                    stop_rows.append({
                        "position": [s.lon, s.lat],
                        "color":    col,
                        "name":     s.name,
                        "mode":     mf,
                        "radius":   r,
                    })
        except Exception as exc:
            logger.debug("transit_layers: stop layer overpass failed: %s", exc)

    if not stop_rows:
        return None

    df = pd.DataFrame(stop_rows)
    return pdk.Layer(
        "ScatterplotLayer",
        id="transit_stops_layer",
        data=df,
        get_position="position",
        get_fill_color="color",
        get_radius="radius",
        radius_min_pixels=2,
        radius_max_pixels=8,
        pickable=True,
        get_tooltip="name",
    )


def _log_layer_summary(layers: Dict[str, Any]) -> None:
    active = [k for k, v in layers.items() if v is not None]
    empty  = [k for k, v in layers.items() if v is None]
    if active:
        logger.info("✅ Transit layers built: %s", ", ".join(active))
    if empty:
        logger.debug("Transit layers unavailable (no data): %s", ", ".join(empty))


# ── Backwards-compatibility shim ──────────────────────────────────────────────

def create_rail_layer(G_rail) -> Optional[Any]:
    """
    Thin shim for the existing `from ui.components.rail_visualizer import create_rail_layer`
    import in visualization.py.

    Builds a single combined rail+tram PathLayer from a raw NetworkX graph.
    For the full multi-layer build, call create_transit_network_layers() instead.
    """
    if G_rail is None or not _PDK or not _PD:
        return None
    rows = _graph_to_path_rows(G_rail)
    if not rows:
        return None
    return _make_path_layer(rows, "rail_layer_compat", _COLOURS["rail"], _WIDTHS["rail"])


def get_stop_layer(
    stops_by_mode: Dict[str, list],
    mode_families: Optional[List[str]] = None,
) -> Optional[Any]:
    """
    Build a stop ScatterplotLayer directly from a transit_stop_loader result.

    Args:
        stops_by_mode:  Dict returned by transit_stop_loader.load_transit_stops().
        mode_families:  Subset of modes to include.  None = all.
    """
    if not _PDK or not _PD:
        return None

    rows = []
    for mf, stops in stops_by_mode.items():
        if mode_families and mf not in mode_families:
            continue
        col = _COLOURS.get(f"stop_{mf}", _COLOURS["stop_bus"])
        r   = _STOP_RADIUS.get(mf, 40)
        for s in stops:
            rows.append({
                "position": [s.lon, s.lat],
                "color":    col,
                "name":     s.name,
                "mode":     mf,
                "radius":   r,
            })

    if not rows:
        return None

    df = pd.DataFrame(rows)
    return pdk.Layer(
        "ScatterplotLayer",
        id="transit_stops_layer",
        data=df,
        get_position="position",
        get_fill_color="color",
        get_radius="radius",
        radius_min_pixels=2,
        radius_max_pixels=8,
        pickable=True,
    )