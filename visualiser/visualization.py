# visualiser/visualization.py

"""
visualization.py

All visualization logic separated from UI orchestration.
Handles map rendering, charts, infrastructure visualization, and animation controls.
"""

from __future__ import annotations
from typing import List, Dict, Optional, Any
from collections import Counter

import pydeck as pdk
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

MODE_COLORS_RGB = {
    'walk': [34, 197, 94],
    'bike': [59, 130, 246],
    'bus': [245, 158, 11],
    'car': [239, 68, 68],
    'ev': [168, 85, 245],
    'van_electric': [16, 185, 129],   # NEW: Green for electric van
    'van_diesel': [107, 114, 128],    # NEW: Gray for diesel van
}

MODE_COLORS_HEX = {
    'walk': '#22c55e',
    'bike': '#3b82f6',
    'bus': '#f59e0b',
    'car': '#ef4444',
    'ev': '#a855f7',
    'van_electric': '#10b981',  # NEW
    'van_diesel': '#6b7280',    # NEW
}


def render_map(
    agent_states: List[Dict],
    show_agents: bool = True,
    show_routes: bool = False,
    show_infrastructure: bool = False,
    infrastructure_manager: Optional[Any] = None,
    center_lon: float = -3.19,
    center_lat: float = 55.95,
    zoom: int = 13
) -> pdk.Deck:
    """
    Render interactive map with agents, routes, and infrastructure.
    
    Args:
        agent_states: List of agent state dicts
        show_agents: Show agent markers
        show_routes: Show agent routes
        show_infrastructure: Show charging stations
        infrastructure_manager: InfrastructureManager instance
        center_lon: Map center longitude
        center_lat: Map center latitude
        zoom: Map zoom level
    
    Returns:
        pydeck.Deck instance
    """
    layers = []
    
    # ========================================================================
    # Agents Layer
    # ========================================================================
    if show_agents and agent_states:
        agent_data = []
        for state in agent_states:
            loc = state.get('location')
            if loc and len(loc) == 2:
                mode = state.get('mode', 'walk')
                color_rgb = MODE_COLORS_RGB.get(mode, [128, 128, 128])
                
                agent_data.append({
                    'lon': float(loc[0]),
                    'lat': float(loc[1]),
                    'r': int(color_rgb[0]),
                    'g': int(color_rgb[1]),
                    'b': int(color_rgb[2]),
                    'agent_id': state.get('agent_id', ''),
                    'mode': mode,
                    'arrived': state.get('arrived', False),
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
    # Routes Layer
    # ========================================================================
    if show_routes and agent_states:
        route_data = []
        
        for state in agent_states:
            route = state.get('route')
            if route and len(route) >= 2:
                mode = state.get('mode', 'walk')
                try:
                    path = [[float(pt[0]), float(pt[1])] for pt in route 
                           if isinstance(pt, (list, tuple)) and len(pt) == 2]
                    
                    if len(path) >= 2:
                        color_rgb = MODE_COLORS_RGB.get(mode, [128, 128, 128])
                        route_data.append({
                            'path': path,
                            'r': int(color_rgb[0]),
                            'g': int(color_rgb[1]),
                            'b': int(color_rgb[2]),
                            'mode': mode,
                            'agent_id': state.get('agent_id', ''),
                        })
                except:
                    pass
        
        if route_data:
            route_df = pd.DataFrame(route_data)
            route_layer = pdk.Layer(
                'PathLayer',
                data=route_df,
                get_path='path',
                get_color='[r, g, b]',
                width_min_pixels=3,
                opacity=0.6,
                pickable=True,
            )
            layers.append(route_layer)
    
    # ========================================================================
    # Infrastructure Layer (NEW)
    # ========================================================================
    if show_infrastructure and infrastructure_manager:
        station_data = []
        
        for station_id, station in infrastructure_manager.charging_stations.items():
            occupancy = station.occupancy_rate()
            
            # Color by occupancy (green=free, red=full)
            r = int(occupancy * 255)
            g = int((1 - occupancy) * 255)
            b = 0
            
            station_data.append({
                'lon': station.location[0],
                'lat': station.location[1],
                'r': r,
                'g': g,
                'b': b,
                'station_id': station_id,
                'type': station.charger_type,
                'occupancy': occupancy,
                'available': station.is_available(),
                'free_ports': max(0, station.num_ports - station.currently_occupied),
                'total_ports': station.num_ports,
            })
        
        if station_data:
            station_df = pd.DataFrame(station_data)
            station_layer = pdk.Layer(
                'ScatterplotLayer',
                data=station_df,
                get_position='[lon, lat]',
                get_fill_color='[r, g, b, 200]',
                get_radius=15,
                radius_min_pixels=8,
                radius_max_pixels=20,
                pickable=True,
                opacity=0.7,
                stroked=True,
                get_line_color=[50, 50, 50],
                line_width_min_pixels=2,
            )
            layers.append(station_layer)
    
    # ========================================================================
    # View State
    # ========================================================================
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
    
    # ========================================================================
    # Create Deck
    # ========================================================================
    deck = pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        tooltip={
            'html': '<b>{agent_id}{station_id}</b><br/>'
                   'Mode: {mode}<br/>'
                   'Type: {type}<br/>'
                   'Occupancy: {occupancy:.0%}<br/>'
                   'Free: {free_ports}/{total_ports}',
            'style': {'backgroundColor': 'rgba(0,0,0,0.8)', 'color': 'white'}
        },
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
    )
    
    return deck


def render_mode_adoption_chart(
    adoption_history: Dict[str, List[float]],
    current_step: int,
    height: int = 400
) -> go.Figure:
    """
    Render mode adoption over time chart.
    
    Args:
        adoption_history: Dict mapping mode to adoption rates over time
        current_step: Current simulation step (for vertical line)
        height: Chart height in pixels
    
    Returns:
        Plotly Figure
    """
    fig = go.Figure()
    
    for mode in ['walk', 'bike', 'bus', 'car', 'ev', 'van_electric', 'van_diesel']:  # NEW
        if mode in adoption_history and adoption_history[mode]:
            fig.add_trace(go.Scatter(
                x=list(range(len(adoption_history[mode]))),
                y=[v * 100 for v in adoption_history[mode]],
                mode='lines',
                name=mode.capitalize(),
                line=dict(width=3, color=MODE_COLORS_HEX[mode])
            ))
    
    fig.add_vline(x=current_step, line_dash="dash", line_color="red",
                 annotation_text="Now")
    
    fig.update_layout(
        xaxis_title="Time Step",
        yaxis_title="Adoption Rate (%)",
        hovermode='x unified',
        height=height,
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
    
    # Grid utilization chart
    grid_fig = None
    if infrastructure_manager.historical_utilization:
        grid_fig = go.Figure()
        grid_fig.add_trace(go.Scatter(
            y=[v * 100 for v in infrastructure_manager.historical_utilization],
            mode='lines',
            name='Grid Utilization',
            line=dict(color='orange', width=2)
        ))
        
        grid_fig.add_hline(y=95, line_dash="dash", line_color="red",
                          annotation_text="Critical Threshold")
        
        grid_fig.update_layout(
            title="Grid Utilization Over Time",
            yaxis_title="Utilization (%)",
            xaxis_title="Time Step",
            height=height,
        )
    
    # Hotspot map
    hotspots = infrastructure_manager.get_hotspots(threshold=0.8)
    
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