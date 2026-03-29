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
    
    # All display toggles are controlled from the sidebar Map Display section
    # (sidebar_config.py) and written to session_state.  Read them here so the
    # map fragment refreshes whenever a checkbox changes.
    show_rail              = st.session_state.get('show_rail',              True)
    show_gtfs              = st.session_state.get('show_gtfs',              True)
    show_gtfs_stops        = st.session_state.get('show_gtfs_stops',        False)
    show_gtfs_electric_only = st.session_state.get('show_gtfs_electric_only', False)

    # Resolve the SpatialEnvironment so render_map can fetch rail + transit graphs.
    env = getattr(results, 'env', None) or getattr(results, 'spatial_environment', None)

    render_map_fragment(
        agent_states, results.infrastructure, show_rail, env=env,
        show_gtfs=show_gtfs,
        show_gtfs_stops=show_gtfs_stops,
        show_gtfs_electric_only=show_gtfs_electric_only,
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
    show_gtfs: bool = True,
    show_gtfs_stops: bool = False,
    show_gtfs_electric_only: bool = False,
):
    """
    Render map as a fragment — updates independently when display options change.

    All 7 display toggles (agents/routes/infra + rail/gtfs/stops/electric) should be
    read from session_state in render_map_tab() and passed in as arguments so
    that @st.fragment re-renders only this section when a checkbox changes.

    Args:
        agent_states:              Current agent state list.
        infrastructure_manager:    InfrastructureManager instance.
        show_rail:                 Render OpenRailMap / station spine layer.
        env:                       SpatialEnvironment — carries rail + transit graphs.
        show_gtfs:                 Render GTFS service path layer.
        show_gtfs_stops:           Render GTFS stop marker layer.
        show_gtfs_electric_only:   Filter GTFS layer to zero-emission routes only.
    """
    deck = render_map(
        agent_states=agent_states,
        show_agents=st.session_state.get('show_agents', True),
        show_routes=st.session_state.get('show_routes', True),
        show_infrastructure=st.session_state.get('show_infrastructure', True),
        show_rail=show_rail,
        infrastructure_manager=infrastructure_manager,
        env=env,
        show_gtfs=show_gtfs,
        show_gtfs_stops=show_gtfs_stops,
        show_gtfs_electric_only=show_gtfs_electric_only,
    )
    st.pydeck_chart(deck, width='stretch')