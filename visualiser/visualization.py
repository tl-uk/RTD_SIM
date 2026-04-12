# visualiser/visualization.py

"""
visualization.py

All visualization logic separated from UI orchestration.
Handles map rendering, charts, infrastructure visualization, and animation controls.
"""

from __future__ import annotations
from typing import List, Dict, Optional, Any
from collections import Counter
from ui.components.rail_visualizer import create_rail_layer
from ui.components.gtfs_visualizer import create_gtfs_service_layer, create_gtfs_stops_layer

import logging

logger = logging.getLogger(__name__)

import pydeck as pdk
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

MODE_COLORS_RGB = {
    # Personal transport
    'walk': [34, 197, 94],      # Green
    'bike': [59, 130, 246],     # Blue
    'bus': [245, 158, 11],      # Orange
    'car': [239, 68, 68],       # Red
    'ev': [168, 85, 245],       # Purple
    
    # Micro-delivery
    'cargo_bike': [34, 197, 94],      # Bright green
    
    # Light freight (vans)
    'van_electric': [16, 185, 129],   # Teal green
    'van_diesel': [107, 114, 128],    # Gray
    
    # Medium freight (trucks)
    'truck_electric': [74, 222, 128],  # Light green
    'truck_diesel': [120, 113, 108],   # Brown-gray
    
    # Heavy freight (HGVs)
    'hgv_electric': [52, 211, 153],    # Aqua green
    'hgv_diesel': [75, 85, 99],        # Dark gray
    'hgv_hydrogen': [96, 165, 250],    # Light blue
    
    # Public transport
    'tram': [255, 193, 7],        # Amber/Yellow (Edinburgh trams)
    'local_train': [33, 150, 243], # Blue
    'intercity_train': [63, 81, 181], # Indigo
    
    # Maritime
    'ferry_diesel': [0, 150, 136],   # Teal
    'ferry_electric': [0, 188, 212], # Cyan
    
    # Aviation
    'flight_domestic': [244, 67, 54], # Red
    'flight_electric': [233, 30, 99], # Pink
    
    # Micro-mobility
    'e_scooter': [139, 195, 74],   # Light green
}

MODE_COLORS_HEX = {
    'walk': '#22c55e',
    'bike': '#3b82f6',
    'bus': '#f59e0b',
    'car': '#ef4444',
    'ev': '#a855f7',
    'cargo_bike': '#22c55e',
    'van_electric': '#10b981',
    'van_diesel': '#6b7280',
    'truck_electric': '#4ade80',
    'truck_diesel': '#78716c',
    'hgv_electric': '#34d399',
    'hgv_diesel': '#4b5563',
    'hgv_hydrogen': '#60a5fa',
    'tram': '#ffc107',
    'local_train': '#2196f3',
    'intercity_train': '#3f51b5',
    'ferry_diesel': '#009688',
    'ferry_electric': '#00bcd4',
    'flight_domestic': '#f44336',
    'flight_electric': '#e91e63',
    'e_scooter': '#8bc34a',
}


_MODE_EMOJI = {
    'walk': '🚶', 'bike': '🚲', 'cargo_bike': '📦🚲',
    'e_scooter': '🛴', 'bus': '🚌', 'tram': '🚋',
    'car': '🚗', 'ev': '🔋', 'van_electric': '🔋🚐',
    'van_diesel': '🚐', 'truck_electric': '🔋🚛',
    'truck_diesel': '🚛', 'hgv_electric': '🔋🚚',
    'hgv_diesel': '🚚', 'hgv_hydrogen': '💧🚚',
    'local_train': '🚆', 'intercity_train': '🚄',
    'ferry_diesel': '⛴️', 'ferry_electric': '🛳️',
    'flight_domestic': '✈️', 'flight_electric': '✈️',
}


def render_map(
    agent_states: List[Dict],
    show_agents: bool = True,
    show_routes: bool = False,
    show_infrastructure: bool = False,
    show_rail: bool = False,
    show_gtfs: bool = False,
    show_gtfs_stops: bool = False,
    show_gtfs_electric_only: bool = False,
    show_naptan_stops: bool = False,
    show_ferry_routes: bool = True,
    infrastructure_manager: Optional[Any] = None,
    env: Optional[Any] = None,
    center_lon: float = -3.19,
    center_lat: float = 55.95,
    zoom: int = 13,
    map_style: Optional[str] = None,
    **kwargs,
) -> pdk.Deck:
    """
    Render interactive map with agents, routes, and infrastructure.
    
    Args:
        agent_states:              List of agent state dicts
        show_agents:               Show agent markers
        show_routes:               Show agent route polylines
        show_infrastructure:       Show charging station markers
        show_rail:                 Overlay rail network (OpenRailMap or spine)
        show_gtfs:                 Overlay GTFS service route lines
        show_gtfs_stops:           Overlay GTFS stop markers
        show_gtfs_electric_only:   Filter GTFS to electric services only
        show_naptan_stops:         Overlay NaPTAN rail/ferry/tram station markers
        infrastructure_manager:    InfrastructureManager instance
        env:                       SpatialEnvironment (for rail/GTFS/NaPTAN graphs)
        center_lon:                Map centre longitude
        center_lat:                Map centre latitude
        zoom:                      Initial zoom level
        map_style:                 GL JSON style URL. None = Carto Positron default.
    
    Returns:
        pydeck.Deck instance
    """
    layers = []
    
    # ── Ferry / Shipping Lane Layer (always rendered when data available) ─────
    # Ferry routes are physical infrastructure like roads and rail — they are
    # shown on the map regardless of whether GTFS is loaded or any ferry agents
    # are present.  Rendered as dashed teal paths (matching standard mapping
    # conventions) at the very bottom of the layer stack.
    _ferry_graph = None
    _env_arg     = env or kwargs.get('env') or kwargs.get('spatial_environment')
    if _env_arg is not None and hasattr(_env_arg, 'get_ferry_graph'):
        _ferry_graph = _env_arg.get_ferry_graph()
    if _ferry_graph is None and infrastructure_manager is not None:
        _gm = getattr(infrastructure_manager, 'graph_manager', None)
        if _gm is not None:
            _ferry_graph = _gm.get_graph('ferry')

    if show_ferry_routes and _ferry_graph is not None and _ferry_graph.number_of_nodes() > 1:
        try:
            ferry_routes = []
            seen_pairs: set = set()
            for u, v, data in _ferry_graph.edges(data=True):
                # Deduplicate bi-directional pairs so each route appears once.
                key = (min(str(u), str(v)), max(str(u), str(v)))
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                shape = data.get('shape_coords')
                if shape and len(shape) >= 2:
                    route_name = data.get('name', 'Ferry route')
                    ferry_routes.append({
                        'path': [[float(c[0]), float(c[1])] for c in shape],
                        'tooltip_html': f'<b>⛴️ {route_name}</b><br/>Ferry / shipping lane',
                    })
            if ferry_routes:
                ferry_df    = pd.DataFrame(ferry_routes)
                ferry_layer = pdk.Layer(
                    'PathLayer',
                    data=ferry_df,
                    get_path='path',
                    get_color=[0, 150, 136, 210],   # Teal #009688 — matches MODE_COLORS_RGB
                    width_min_pixels=2,
                    width_max_pixels=6,
                    width_scale=1,
                    dash_array=[8, 6],               # Dashed — standard map convention
                    pickable=True,
                    auto_highlight=True,
                )
                layers.insert(0, ferry_layer)
                logger.info(
                    "✅ Ferry waterway layer: %d routes", len(ferry_routes)
                )
        except Exception as _ferr:
            logger.warning("Ferry layer failed: %s", _ferr)
    
    # The rail graph lives on the SpatialEnvironment (passed as env kwarg),
    # not on InfrastructureManager.  Accept either so callers can pass what
    # they have.
    if show_rail:
        G_rail = None
        # Prefer an explicit env / spatial_environment argument
        env_arg = kwargs.get('env') or kwargs.get('spatial_environment')
        if env_arg is not None and hasattr(env_arg, 'get_rail_graph'):
            G_rail = env_arg.get_rail_graph()
        # Fallback: infrastructure_manager may carry a graph_manager reference
        elif infrastructure_manager is not None:
            gm = getattr(infrastructure_manager, 'graph_manager', None)
            if gm is not None:
                G_rail = gm.get_graph('rail')

        if G_rail is not None:
            try:
                rail_layer = create_rail_layer(G_rail)
                if rail_layer:
                    layers.insert(0, rail_layer)   # under all other layers
                    logger.info("✅ Rail layer added (%d nodes)", len(G_rail.nodes))
            except Exception as exc:
                logger.warning("Rail layer failed: %s", exc)
        elif show_rail:
            logger.debug("show_rail=True but rail graph not yet loaded")

    # ── GTFS Transit Layer ────────────────────────────────────────────────────
    # Service path geometry from shapes.txt; stop markers sized by frequency.
    # Inserted between the OpenRailMap layer and the agent layer.
    if show_gtfs or show_gtfs_stops:
        G_transit = None
        env_arg = env or kwargs.get('env') or kwargs.get('spatial_environment')
        if env_arg is not None and hasattr(env_arg, 'get_transit_graph'):
            G_transit = env_arg.get_transit_graph()
        elif infrastructure_manager is not None:
            gm = getattr(infrastructure_manager, 'graph_manager', None)
            if gm is not None:
                G_transit = gm.get_graph('transit')

        if G_transit is not None:
            try:
                if show_gtfs:
                    svc_layer = create_gtfs_service_layer(
                        G_transit,
                        show_electric_only=show_gtfs_electric_only,
                    )
                    if svc_layer:
                        layers.insert(0, svc_layer)
                        logger.info(
                            "✅ GTFS service layer added (%d edges)", G_transit.number_of_edges()
                        )
                if show_gtfs_stops:
                    stop_layer = create_gtfs_stops_layer(G_transit)
                    if stop_layer:
                        layers.append(stop_layer)   # on top — stops should be clickable
                        logger.info(
                            "✅ GTFS stops layer added (%d stops)", G_transit.number_of_nodes()
                        )
            except Exception as exc:
                logger.warning("GTFS layer failed: %s", exc)
        elif show_gtfs:
            logger.debug("show_gtfs=True but transit graph not yet loaded")

    # ========================================================================
    # Agents Layer
    # ========================================================================
    if agent_states:
        agent_data = []

        # Pre-build the set of agents currently charging so we can annotate
        # EV agents in their tooltip without an extra dict lookup per agent.
        _charging_agents: set = set()
        if infrastructure_manager and hasattr(infrastructure_manager, 'sessions'):
            try:
                _charging_agents = set(infrastructure_manager.sessions.get_charging_agents())
            except Exception:
                pass

        _EV_MODES = {'ev', 'van_electric', 'truck_electric', 'hgv_electric'}

        for state in agent_states:
            loc = state.get('location')
            if loc and len(loc) == 2:
                mode       = state.get('mode', 'walk')
                agent_id   = state.get('agent_id', '')
                arrived    = state.get('arrived', False)
                distance   = state.get('distance_km', 0.0)
                emissions  = state.get('emissions_g', 0.0)
                color_rgb  = MODE_COLORS_RGB.get(mode, [128, 128, 128])
                is_ev      = mode in _EV_MODES
                is_charging = agent_id in _charging_agents

                mode_label = f"{_MODE_EMOJI.get(mode, '🚗')} {mode.replace('_', ' ').title()}"

                # Status line
                if arrived:
                    status_html = '✅ Arrived'
                elif is_ev and is_charging:
                    status_html = '⚡ Charging'
                else:
                    status_html = '🔄 En route'

                # EV-specific line
                ev_line = ''
                if is_ev and not is_charging:
                    ev_line = '<br/>🔋 EV — not charging'
                elif is_ev and is_charging:
                    ev_line = '<br/>⚡ At charging station'

                # Origin / destination — always shown so users understand where
                # the agent is going regardless of whether it has arrived.
                origin_name = state.get('origin_name', '') or state.get('home_name', '')
                dest_name   = state.get('destination_name', '') or state.get('dest_name', '')
                od_lines    = ''
                if origin_name:
                    od_lines += f'<br/>🏠 From: {origin_name}'
                if dest_name:
                    od_lines += f'<br/>🏁 To: {dest_name}'

                # Public-transport service details
                pt_lines = ''
                service_id = state.get('service_id', '') or state.get('route_id', '')
                dest_stop  = state.get('destination_stop', '') or state.get('alighting_stop', '')
                operator   = state.get('operator', '')
                if service_id or dest_stop:
                    svc_str  = service_id or ''
                    stop_str = dest_stop  or ''
                    pt_label = f'{svc_str} {stop_str}'.strip()
                    pt_prefix = _MODE_EMOJI.get(mode, '🚌')
                    pt_lines  = f'<br/>{pt_prefix} {pt_label}'
                if operator:
                    pt_lines += f'<br/>🏢 {operator}'

                tooltip_html = (
                    f'<b>{agent_id}</b><br/>'
                    f'Mode: {mode_label}<br/>'
                    f'Status: {status_html}'
                    f'{od_lines}'
                    f'{pt_lines}<br/>'
                    f'Distance: {distance:.1f} km<br/>'
                    f'Emissions: {emissions:.0f} g CO₂'
                    f'{ev_line}'
                )

                agent_data.append({
                    'lon': float(loc[0]),
                    'lat': float(loc[1]),
                    'r': int(color_rgb[0]),
                    'g': int(color_rgb[1]),
                    'b': int(color_rgb[2]),
                    'tooltip_html': tooltip_html,
                })
        
        if agent_data:
            agent_df = pd.DataFrame(agent_data)
            agent_layer = pdk.Layer(
                'ScatterplotLayer',
                data=agent_df,
                get_position='[lon, lat]',
                get_fill_color='[r, g, b]',
                get_radius=10,
                radius_min_pixels=6,
                radius_max_pixels=15,
                pickable=True,
                opacity=0.8,
                stroked=True,
                filled=True,
                line_width_min_pixels=2,
                get_line_color=[255, 255, 255],
            )
            layers.append(agent_layer)
    
    # ========================================================================
    # Routes Layer — all agents, per-segment colour coding
    # ========================================================================
    # Routes are displayed for ALL transport modes.  RTD_SIM agents use
    # Bayesian and Markov models and may switch between private and public
    # transport mid-journey in response to social or environmental events.
    # Hiding any mode would misrepresent that multimodal behaviour.
    #
    # Styling is differentiated by mode category so the map remains readable:
    #   • Active travel (walk, bike, e_scooter, cargo_bike) — thin, dashed
    #   • Private vehicle (car, ev, van, truck, hgv)        — medium, solid
    #   • Public transport (bus, tram, train, ferry)        — bold, solid
    #
    # When an agent's state carries `route_segments` metadata from
    # compute_route_with_segments(), each walk/transit/ferry leg is rendered
    # with its own correct colour.  Without segments the whole route uses the
    # agent's current mode colour.

    _ACTIVE_MODES  = frozenset({'walk', 'bike', 'e_scooter', 'cargo_bike'})
    _PRIVATE_MODES = frozenset({
        'car', 'ev', 'taxi_ev', 'taxi_diesel',
        'van_electric', 'van_diesel',
        'truck_electric', 'truck_diesel',
        'hgv_electric', 'hgv_diesel', 'hgv_hydrogen',
    })
    _PT_MODES = frozenset({
        'bus', 'tram',
        'local_train', 'intercity_train', 'freight_rail',
        'ferry_diesel', 'ferry_electric',
        'flight_domestic', 'flight_electric',
    })

    if show_routes and agent_states:
        logger.info(
            "🔍 ROUTE RENDERING: %d agents (all modes)",
            len(agent_states),
        )

        # Collect per-segment route rows keyed by mode for batched PathLayers.
        # {mode_str: [{path, r, g, b, agent_id, tooltip_html}, ...]}
        segment_rows: Dict[str, list] = {}

        for idx, state in enumerate(agent_states):
            mode      = state.get('mode', 'walk')
            agent_id  = state.get('agent_id', f'agent_{idx}')
            arrived   = state.get('arrived', False)
            distance  = state.get('distance_km', 0.0)
            emissions = state.get('emissions_g', 0.0)

            # ── Rich tooltip ────────────────────────────────────────────────
            mode_label    = f"{_MODE_EMOJI.get(mode, '🚗')} {mode.replace('_', ' ').title()}"
            status_html   = '✅ Arrived' if arrived else '🔄 En route'
            origin_name   = state.get('origin_name', '') or state.get('home_name', '')
            dest_name     = state.get('destination_name', '') or state.get('dest_name', '')
            service_id    = state.get('service_id', '') or state.get('route_id', '')
            dest_stop     = state.get('destination_stop', '') or state.get('alighting_stop', '')

            od_html = ''
            if origin_name or dest_name:
                od_html = (
                    f'<br/>🏠 From: {origin_name or "?"}'
                    f'<br/>🏁 To: {dest_name or "?"}'
                )
            svc_html = ''
            if service_id or dest_stop:
                svc_html = f'<br/>{_MODE_EMOJI.get(mode,"🚌")} {(service_id + " " + dest_stop).strip()}'

            base_tooltip = (
                f'<b>{agent_id}</b><br/>'
                f'Mode: {mode_label}<br/>'
                f'Status: {status_html}'
                f'{od_html}'
                f'{svc_html}<br/>'
                f'Distance: {distance:.1f} km<br/>'
                f'Emissions: {emissions:.0f} g CO₂'
            )

            # ── Try per-segment colouring first ──────────────────────────────
            route_segments = state.get('route_segments')
            if route_segments and isinstance(route_segments, list) and len(route_segments) > 0:
                for seg in route_segments:
                    seg_mode  = seg.get('mode', mode)
                    seg_label = seg.get('label', seg_mode.replace('_', ' ').title())
                    seg_path  = seg.get('path', [])
                    if not seg_path or len(seg_path) < 2:
                        continue
                    try:
                        path_list = [
                            [float(pt[0]), float(pt[1])]
                            for pt in seg_path
                            if isinstance(pt, (list, tuple)) and len(pt) == 2
                        ]
                    except Exception:
                        continue
                    if len(path_list) < 2:
                        continue
                    color = MODE_COLORS_RGB.get(seg_mode, [128, 128, 128])

                    # Segment-level distance from segment dict (TripLeg.to_dict includes it)
                    seg_dist_km = seg.get('distance_km') or seg.get('dist_km') or 0.0
                    seg_dist_str = f'{seg_dist_km:.1f} km' if seg_dist_km > 0 else ''
                    seg_emit_g  = seg.get('emissions_g', 0.0)
                    seg_emit_str = f' · {seg_emit_g:.0f} g CO₂' if seg_emit_g > 0 else ''

                    seg_tooltip = (
                        f'<b>{agent_id}</b><br/>'
                        f'{_MODE_EMOJI.get(seg_mode, "🚗")} <b>{seg_label}</b><br/>'
                        + (f'{seg_dist_str}{seg_emit_str}<br/>' if seg_dist_str else '')
                        + (f'🏠 {seg.get("origin_name","") or ""}<br/>' if seg.get("origin_name") else '')
                        + (f'🏁 {seg.get("dest_name","") or ""}<br/>' if seg.get("dest_name") else '')
                        + (f'{od_html}' if od_html and not seg.get("origin_name") else '')
                        + svc_html
                    )
                    if seg_mode not in segment_rows:
                        segment_rows[seg_mode] = []
                    segment_rows[seg_mode].append({
                        'path': path_list,
                        'r': int(color[0]), 'g': int(color[1]), 'b': int(color[2]),
                        'agent_id': agent_id,
                        'tooltip_html': seg_tooltip,
                    })
                continue   # segments handled — skip flat-route fallback

            # ── Flat route fallback ──────────────────────────────────────────
            route = state.get('route')
            if not route or len(route) < 2:
                continue
            try:
                path_list = [
                    [float(pt[0]), float(pt[1])]
                    for pt in route
                    if isinstance(pt, (list, tuple)) and len(pt) == 2
                ]
            except Exception as exc:
                logger.warning("Route %d parse failed: %s", idx, exc)
                continue
            if len(path_list) < 2:
                continue

            color_rgb = MODE_COLORS_RGB.get(mode, [128, 128, 128])
            # Subtle per-agent variation to distinguish overlapping same-mode routes
            v = (idx % 10) * 12
            r = min(255, max(40, color_rgb[0] + (v if idx % 2 == 0 else -v // 2)))
            g = min(255, max(40, color_rgb[1] + (v if idx % 3 == 1 else -v // 2)))
            b = min(255, max(40, color_rgb[2] + (v if idx % 4 == 2 else -v // 2)))

            if mode not in segment_rows:
                segment_rows[mode] = []
            segment_rows[mode].append({
                'path': path_list,
                'r': int(r), 'g': int(g), 'b': int(b),
                'agent_id': agent_id,
                'tooltip_html': base_tooltip,
            })

        # ── Build one PathLayer per mode — styling matched to category ───────
        total_segs = sum(len(v) for v in segment_rows.values())
        logger.info(
            "📊 ROUTE SUMMARY: %d route segments across %d mode types",
            total_segs, len(segment_rows),
        )

        for seg_mode, rows in segment_rows.items():
            if not rows:
                continue
            is_active  = seg_mode in _ACTIVE_MODES
            is_private = seg_mode in _PRIVATE_MODES
            is_pt      = seg_mode in _PT_MODES
            # Active travel: thin dashed. Private: medium. PT/ferry: bold.
            w_min   = 1 if is_active else (2 if is_private else 3)
            w_max   = 3 if is_active else (5 if is_private else 7)
            opacity = 0.50 if is_active else (0.70 if is_private else 0.92)
            alpha   = 130  if is_active else (170 if is_private else 210)

            layer_kwargs: Dict = dict(
                data=rows,
                get_path='path',
                get_color=f'[r, g, b, {alpha}]',
                width_min_pixels=w_min,
                width_max_pixels=w_max,
                width_scale=1,
                opacity=opacity,
                pickable=True,
                auto_highlight=True,
            )
            if is_active:
                layer_kwargs['dash_array'] = [6, 4]

            layers.append(pdk.Layer('PathLayer', **layer_kwargs))
            logger.info(
                "✅ Route layer [%s/%s]: %d segments",
                seg_mode,
                'active' if is_active else ('private' if is_private else 'PT'),
                len(rows),
            )

    elif show_routes and not agent_states:
        logger.warning("show_routes=True but agent_states is empty")
    
    # ========================================================================
    # Infrastructure Layer - SMALLER & MORE TRANSPARENT
    # ========================================================================
    if show_infrastructure and infrastructure_manager:
        station_data = []
        
        # ✅ FIX: Limit to reasonable number of stations for performance
        stations_to_show = list(infrastructure_manager.charging_stations.items())
        if len(stations_to_show) > 200:
            # Sample 200 stations instead of showing all 3000+
            import random
            stations_to_show = random.sample(stations_to_show, 200)
        
        for station_id, station in stations_to_show:
            occupancy = station.occupancy_rate()
            
            # Color by occupancy (green=free, red=full)
            r = int(occupancy * 255)
            g = int((1 - occupancy) * 255)
            b = 0
            
            free_ports = max(0, station.num_ports - station.currently_occupied)
            queue_len  = len(station.queue)

            avail_icon = '🔴 Full' if free_ports == 0 else '🟢 Available'

            # Occupancy bar (5 chars wide)
            filled = round(occupancy * 5)
            occ_bar = '█' * filled + '░' * (5 - filled)

            # Charger type display
            type_labels = {
                'level2': 'Level 2 (7 kW)',
                'dcfast':  'DC Fast (50 kW)',
                'depot':   'Depot (150 kW)',
                'home':    'Home (3.6 kW)',
            }
            type_label = type_labels.get(station.charger_type, station.charger_type)

            queue_line = f'<br/>⏳ Queue: {queue_len} waiting' if queue_len > 0 else ''

            tooltip_html = (
                f'<b>⚡ {station_id}</b><br/>'
                f'Type: {type_label}<br/>'
                f'{avail_icon}<br/>'
                f'Ports: {free_ports}/{station.num_ports} free<br/>'
                f'Load: [{occ_bar}] {occupancy:.0%}'
                f'{queue_line}'
            )

            station_data.append({
                'lon': station.location[0],
                'lat': station.location[1],
                'r': r,
                'g': g,
                'b': b,
                'tooltip_html': tooltip_html,
            })
        
        if station_data:
            station_df = pd.DataFrame(station_data)
            station_layer = pdk.Layer(
                'ScatterplotLayer',
                data=station_df,
                get_position='[lon, lat]',
                get_fill_color='[r, g, b, 150]',  # ✅ FIX: Lower opacity (150 vs 200)
                get_radius=8,  # ✅ FIX: Smaller (8 vs 15)
                radius_min_pixels=4,  # ✅ FIX: Smaller (4 vs 8)
                radius_max_pixels=10,  # ✅ FIX: Smaller (10 vs 20)
                pickable=True,
                opacity=0.4,  # ✅ FIX: More transparent (0.4 vs 0.7)
                stroked=True,
                get_line_color=[50, 50, 50],
                line_width_min_pixels=1,  # ✅ FIX: Thinner stroke
            )
            # Add infrastructure layer FIRST so agents render on top
            layers.insert(0, station_layer)

            # Hotspot ring layer — bright red pulsing ring around overloaded stations
            hotspot_ids = set(infrastructure_manager.get_hotspots(threshold=0.5))
            hotspot_data = [
                {
                    'lon': s.location[0],
                    'lat': s.location[1],
                    'tooltip_html': (
                        f'<b>🔴 Hotspot: {sid}</b><br/>'
                        f'Type: {s.charger_type}<br/>'
                        f'Ports: {s.currently_occupied}/{s.num_ports} occupied<br/>'
                        f'Load: {s.occupancy_rate():.0%}'
                    ),
                }
                for sid, s in infrastructure_manager.charging_stations.items()
                if sid in hotspot_ids
            ]
            if hotspot_data:
                hotspot_df = pd.DataFrame(hotspot_data)
                hotspot_layer = pdk.Layer(
                    'ScatterplotLayer',
                    data=hotspot_df,
                    get_position='[lon, lat]',
                    get_fill_color=[255, 0, 0, 0],       # transparent fill
                    get_line_color=[255, 50, 50, 220],    # bright red ring
                    get_radius=20,
                    radius_min_pixels=12,
                    radius_max_pixels=28,
                    line_width_min_pixels=3,
                    stroked=True,
                    filled=True,
                    pickable=True,
                )
                layers.insert(0, hotspot_layer)   # below stations so rings show around them

    # ========================================================================
    # NaPTAN Station Markers
    # ========================================================================
    # NaPTAN is the UK government's authoritative stop dataset: rail stations,
    # ferry terminals, tram stops.  Works independently of GTFS.
    # NaptanStop objects use ATTRIBUTE access (.lon, .lat, .common_name, .stop_type)
    # NOT dict .get() — they are dataclass instances, not plain dicts.
    if show_naptan_stops and env is not None:
        naptan_stops = getattr(env, 'naptan_stops', None)
        if naptan_stops:
            try:
                naptan_data = []
                for stop in naptan_stops:
                    try:
                        # Attribute access — NaptanStop is a slotted class, not a dict
                        lon  = float(getattr(stop, 'lon',  getattr(stop, 'longitude', 0)))
                        lat  = float(getattr(stop, 'lat',  getattr(stop, 'latitude',  0)))
                        if lon == 0.0 and lat == 0.0:
                            continue
                        stype = str(getattr(stop, 'stop_type', '')).lower()
                        name  = str(getattr(stop, 'common_name', getattr(stop, 'name', '')))
                        # Colour by stop type
                        if any(t in stype for t in ('rail', 'rsp', 'rstp', 'train')):
                            r, g, b = 33, 150, 243   # blue — rail
                            icon = '🚆'
                        elif any(t in stype for t in ('ferry', 'fbt', 'port', 'harbour')):
                            r, g, b = 0, 188, 212    # cyan — ferry
                            icon = '⛴️'
                        elif any(t in stype for t in ('tram', 'plat', 'met')):
                            r, g, b = 255, 193, 7    # amber — tram/metro
                            icon = '🚋'
                        else:
                            r, g, b = 33, 150, 243   # blue — default
                            icon = '📍'
                        naptan_data.append({
                            'lon': lon, 'lat': lat,
                            'r': r, 'g': g, 'b': b,
                            'tooltip_html': (
                                f'<b>{icon} {name or "NaPTAN stop"}</b><br/>'
                                f'Type: {stype.upper() or "Stop"}'
                            ),
                        })
                    except Exception:
                        continue
                if naptan_data:
                    naptan_df    = pd.DataFrame(naptan_data)
                    naptan_layer = pdk.Layer(
                        'ScatterplotLayer',
                        data=naptan_df,
                        get_position='[lon, lat]',
                        get_fill_color='[r, g, b, 220]',
                        get_radius=8,
                        radius_min_pixels=5,
                        radius_max_pixels=14,
                        pickable=True,
                        stroked=True,
                        get_line_color=[255, 255, 255, 200],
                        line_width_min_pixels=1,
                    )
                    layers.append(naptan_layer)
                    logger.info("✅ NaPTAN layer: %d stops", len(naptan_data))
            except Exception as _ne:
                logger.warning("NaPTAN layer failed: %s", _ne)
    if agent_states:
        lons = [s['location'][0] for s in agent_states if s.get('location')]
        lats = [s['location'][1] for s in agent_states if s.get('location')]
        if lons and lats:
            center_lon = sum(lons) / len(lons)
            center_lat = sum(lats) / len(lats)
    
    view_state = pdk.ViewState(
        longitude=center_lon,
        latitude=center_lat,
        zoom=zoom,
        pitch=0,
        bearing=0
    )

    # ── Resolve map style ──────────────────────────────────────────────────────
    _default_style = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
    _map_style     = map_style or _default_style

    # ── pydeck tooltip ─────────────────────────────────────────────────────────
    # pydeck stubs type tooltip as bool; cast to Any satisfies type checkers.
    from typing import cast as _cast, Any as _Any
    _tooltip = _cast(_Any, {
        'html':  '{tooltip_html}',
        'style': {
            'backgroundColor': 'rgba(0,0,0,0.85)',
            'color':           'white',
            'fontSize':        '13px',
            'padding':         '8px 12px',
            'borderRadius':    '6px',
            'lineHeight':      '1.6',
        },
    })

    # ========================================================================
    # Create Deck
    # ========================================================================
    deck = pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        tooltip=_tooltip,
        map_style=_map_style,
    )
    
    return deck


# Update render_mode_adoption_chart to include all modes
def render_mode_adoption_chart(
    adoption_history: Dict[str, List[float]],
    current_step: int,
    height: int = 400
) -> go.Figure:
    """Render mode adoption over time chart with all modes."""
    fig = go.Figure()
    
    # ALL MODES (updated)
    all_modes = [
        'walk', 'bike', 'cargo_bike', 'e_scooter',
        'bus', 'car', 'ev',
        'tram', 'local_train', 'intercity_train',  # NEW
        'ferry_diesel', 'ferry_electric',  # NEW
        'flight_domestic', 'flight_electric',  # NEW
        'van_electric', 'van_diesel',
        'truck_electric', 'truck_diesel',
        'hgv_electric', 'hgv_diesel', 'hgv_hydrogen'
    ]
    
    for mode in all_modes:
        if mode in adoption_history and adoption_history[mode]:
            fig.add_trace(go.Scatter(
                x=list(range(len(adoption_history[mode]))),
                y=[v * 100 for v in adoption_history[mode]],
                mode='lines',
                name=mode.replace('_', ' ').title(),
                line=dict(width=3, color=MODE_COLORS_HEX.get(mode, '#808080'))
            ))
    
    fig.add_vline(x=current_step, line_dash="dash", line_color="red",
                 annotation_text="Now")
    
    fig.update_layout(
        xaxis_title="Time Step",
        yaxis_title="Adoption Rate (%)",
        hovermode='x unified',
        height=height,
        legend=dict(
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="left",
            x=1.02
        )
    )
    
    return fig


def render_emissions_chart(
    time_series: Any,
    height: int = 400
) -> go.Figure:
    """
    Render cumulative emissions chart.
    
    Args:
        time_series: TimeSeriesStorage instance
        height: Chart height in pixels
    
    Returns:
        Plotly Figure
    """
    all_metrics = []
    for step_idx in range(len(time_series)):
        data = time_series.get_timestep(step_idx)
        if data:
            # FIX: Calculate from agent_states instead of metrics
            agent_states = data.get('agent_states', [])
            total_emissions = sum(s.get('emissions_g', 0) for s in agent_states)
            total_distance = sum(s.get('distance_km', 0) for s in agent_states)
            
            all_metrics.append({
                'step': step_idx,
                'emissions': total_emissions,
                'distance': total_distance,
            })
    
    if not all_metrics:
        return go.Figure()
    
    metrics_df = pd.DataFrame(all_metrics)
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=metrics_df['step'],
        y=metrics_df['emissions'],
        mode='lines',
        fill='tozeroy',
        line=dict(color='#ef4444', width=3),
        name='Emissions'
    ))
    
    fig.update_layout(
        title="Total CO₂ Emissions",
        xaxis_title="Time Step",
        yaxis_title="Emissions (g CO₂)",
        height=height,
    )
    
    return fig


def render_infrastructure_metrics(
    infrastructure_manager: Any,
    height: int = 400
) -> Dict[str, Any]:
    """
    Render infrastructure metrics and charts.
    
    Args:
        infrastructure_manager: InfrastructureManager instance
        height: Chart height in pixels
    
    Returns:
        Dict with metrics and figures
    """
    metrics = infrastructure_manager.get_infrastructure_metrics()
    
    # Grid utilization chart with thresholds
    grid_fig = None
    if infrastructure_manager.historical_utilization:
        import plotly.graph_objects as go
        
        grid_fig = go.Figure()
        
        # Main utilization line
        grid_fig.add_trace(go.Scatter(
            y=[v * 100 for v in infrastructure_manager.historical_utilization],
            mode='lines',
            name='Grid Utilization',
            line=dict(color='#3b82f6', width=3),
            fill='tozeroy',
            fillcolor='rgba(59, 130, 246, 0.2)'
        ))
        
        # Add threshold lines
        grid_fig.add_hline(
            y=95, 
            line_dash="dash", 
            line_color="red",
            annotation_text="Critical (95%)",
            annotation_position="right"
        )
        
        grid_fig.add_hline(
            y=70, 
            line_dash="dot", 
            line_color="orange",
            annotation_text="High (70%)",
            annotation_position="right"
        )
        
        grid_fig.update_layout(
            title="Grid Utilization Over Time",
            yaxis_title="Utilization (%)",
            xaxis_title="Time Step",
            height=height,
            hovermode='x unified',
            showlegend=True
        )
    
    # Hotspot map
    hotspots = infrastructure_manager.get_hotspots(threshold=0.5)
    
    return {
        'metrics': metrics,
        'grid_figure': grid_fig,
        'hotspots': hotspots,
    }


def render_cascade_chart(
    cascade_events: List[Dict],
    height: int = 400
) -> Optional[go.Figure]:
    """
    Render cascade events chart.
    
    Args:
        cascade_events: List of cascade event dicts
        height: Chart height in pixels
    
    Returns:
        Plotly Figure or None if no events
    """
    if not cascade_events:
        return None
    
    cascade_df = pd.DataFrame(cascade_events)
    
    fig = px.scatter(
        cascade_df,
        x='step',
        y='growth',
        color='mode',
        color_discrete_map=MODE_COLORS_HEX,
        title="Cascade Events",
        labels={'step': 'Time Step', 'growth': 'Cascade Growth', 'mode': 'Mode'},
        height=height,
    )
    
    return fig


def get_current_stats(agent_states: List[Dict], metrics: Dict) -> Dict[str, Any]:
    """
    Calculate current statistics for display.
    
    Args:
        agent_states: List of agent state dicts
        metrics: Aggregated metrics dict
    
    Returns:
        Dict of formatted statistics
    """
    mode_counts = Counter(s['mode'] for s in agent_states)
    
    # FIX: Calculate arrivals from agent_states, not metrics
    arrivals = sum(1 for s in agent_states if s.get('arrived', False))
    
    # FIX: Calculate emissions from agent_states
    emissions = sum(s.get('emissions_g', 0) for s in agent_states)
    
    agents_with_routes = sum(1 for s in agent_states 
                            if s.get('route') and len(s.get('route', [])) > 0)
    
    most_popular = mode_counts.most_common(1)[0][0].capitalize() if mode_counts else "N/A"
    
    return {
        'arrivals': f"{arrivals}/{len(agent_states)}",
        'most_popular_mode': most_popular,
        'total_emissions': f"{emissions:.0f} g CO₂",
        'agents_with_routes': f"{agents_with_routes}/{len(agent_states)}",
        'mode_counts': mode_counts,
    }


def get_mode_distribution(agent_states: List[Dict]) -> pd.DataFrame:
    """
    Get current mode distribution as DataFrame.
    
    Args:
        agent_states: List of agent state dicts
    
    Returns:
        DataFrame with mode distribution
    """
    mode_counts = Counter(s['mode'] for s in agent_states)
    total = len(agent_states)
    
    data = []
    for mode in ['walk', 'bike', 'bus', 'car', 'ev']:
        count = mode_counts.get(mode, 0)
        pct = (count / total * 100) if total > 0 else 0
        
        data.append({
            'mode': mode.capitalize(),
            'count': count,
            'percentage': pct,
            'color': MODE_COLORS_HEX[mode]
        })
    
    return pd.DataFrame(data)


def render_agent_distribution_analysis(agents: List[Any]) -> Dict[str, Any]:
    """
    Analyze and visualize agent distribution.
    
    Args:
        agents: List of agents
    
    Returns:
        Dict with distribution metrics and figures
    """
    if not agents or not hasattr(agents[0], 'user_story_id'):
        return {'available': False}
    
    import statistics
    
    # Calculate diversity metrics
    eco_values = [a.desires.get('eco', 0) for a in agents]
    time_values = [a.desires.get('time', 0) for a in agents]
    cost_values = [a.desires.get('cost', 0) for a in agents]
    
    eco_std = statistics.stdev(eco_values) if len(eco_values) > 1 else 0
    time_std = statistics.stdev(time_values) if len(time_values) > 1 else 0
    cost_std = statistics.stdev(cost_values) if len(cost_values) > 1 else 0
    
    # Story distributions
    user_dist = Counter(a.user_story_id for a in agents)
    job_dist = Counter(a.job_story_id for a in agents)
    
    return {
        'available': True,
        'diversity': {
            'eco_std': eco_std,
            'time_std': time_std,
            'cost_std': cost_std,
        },
        'user_distribution': dict(user_dist),
        'job_distribution': dict(job_dist),
        'sample_agents': agents[:10],  # First 10 for display
    }