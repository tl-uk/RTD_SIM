"""
ui/tabs/map_tab.py

Map visualization tab with fragment-based rendering.
Map updates reactively without full page rerun
"""

import streamlit as st
from visualiser.visualization import (
    render_map,
    get_current_stats,
)
from ui.widgets.policy_status_widget import render_policy_status_widget

# Note: This tab is designed to be lightweight and reactive, with the map rendered as a 
# fragment that updates independently when display options change. This allows users to 
# toggle visibility of agents, routes, and infrastructure without triggering a full page 
# rerun, ensuring a smoother user experience.
def render_map_tab(results, anim, current_data):
    """
    Render map visualization tab.
    
    Args:
        results: SimulationResults
        anim: AnimationController
        current_data: Current timestep data
    """
    
    agent_states = current_data['agent_states']
    metrics = current_data.get('metrics', {})
    
    # Get config from session state
    config = st.session_state.get('last_config')
    
    # Build header with temporal info if available
    header = f"Live View - Step {anim.current_step + 1}/{anim.total_steps}"
    
    if hasattr(results, 'temporal_engine') and results.temporal_engine:
        time_info = results.temporal_engine.get_time_info(anim.current_step)
        header += f" | 📅 {time_info['date']} {time_info['time'][:5]}"
    
    st.subheader(header)
    
    # Use fragment to isolate map rendering
    # This allows display options to update the map without full page rerun
    show_rail = st.sidebar.checkbox("Show Rail Network (OpenRailMap)", value=True)
    show_gtfs = st.sidebar.checkbox("Show Transit Routes (GTFS)", value=True)
    show_gtfs_stops = st.sidebar.checkbox("Show Transit Stops (GTFS)", value=False)
    gtfs_electric_only = st.sidebar.checkbox("Electric routes only", value=False)

    # Resolve the SpatialEnvironment so render_map can fetch the rail graph.
    env = getattr(results, 'env', None) or getattr(results, 'spatial_environment', None)

    render_map_fragment(
        agent_states, results.infrastructure, show_rail,
        env=env,
        show_gtfs=show_gtfs,
        show_gtfs_stops=show_gtfs_stops,
        gtfs_electric_only=gtfs_electric_only,
    )
    
    st.markdown("---")
    
    # Current stats
    stats = get_current_stats(agent_states, metrics)
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Arrivals", stats['arrivals'])
    col2.metric("Most Popular", stats['most_popular_mode'])
    col3.metric("Emissions", stats['total_emissions'])
    col4.metric("Agents w/ Routes", stats['agents_with_routes'])
    
    st.markdown("---")
    
    # Policy Status Widget (if policy active)
    if config and hasattr(results, 'policy_status') and results.policy_status:
        render_policy_status_widget(results, anim.current_step, config)

# Fragment for map rendering - updates independently when display options change
# This prevents full page reruns when checkboxes are toggled, improving performance and 
# user experience.
@st.fragment
def render_map_fragment(
    agent_states,
    infrastructure_manager,
    show_rail,
    env=None,
    show_gtfs=False,
    show_gtfs_stops=False,
    gtfs_electric_only=False,
):
    """
    Render map as a fragment - updates independently when display options change.

    Args:
        agent_states:           Current agent state list.
        infrastructure_manager: InfrastructureManager instance.
        show_rail:              Whether to render the OpenRailMap / spine layer.
        env:                    SpatialEnvironment — carries the rail and transit
                                graphs that render_map() needs.
        show_gtfs:              Render GTFS service path layer.
        show_gtfs_stops:        Render GTFS stop marker layer.
        gtfs_electric_only:     Only show zero-emission routes in GTFS layer.
    """
    deck = render_map(
        agent_states=agent_states,
        show_agents=st.session_state.get('show_agents', True),
        show_routes=st.session_state.get('show_routes', True),
        show_infrastructure=st.session_state.get('show_infrastructure', True),
        show_rail=show_rail,
        show_gtfs=show_gtfs,
        show_gtfs_stops=show_gtfs_stops,
        gtfs_electric_only=gtfs_electric_only,
        infrastructure_manager=infrastructure_manager,
        env=env,
    )

    st.pydeck_chart(deck, width='stretch')