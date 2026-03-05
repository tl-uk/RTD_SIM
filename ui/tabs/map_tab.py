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
    
    st.subheader(f"Live View - Step {anim.current_step + 1}/{anim.total_steps}")
    
    # Use fragment to isolate map rendering
    # This allows display options to update the map without full page rerun
    render_map_fragment(agent_states, results.infrastructure)
    
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
def render_map_fragment(agent_states, infrastructure_manager):
    """
    Render map as a fragment - updates independently when display options change.
    
    This prevents full page reruns when checkboxes are toggled.
    """
    
    # Render map with current display settings from session state
    deck = render_map(
        agent_states=agent_states,
        show_agents=st.session_state.get('show_agents', True),
        show_routes=st.session_state.get('show_routes', True),
        show_infrastructure=st.session_state.get('show_infrastructure', True),
        infrastructure_manager=infrastructure_manager,
    )
    
    st.pydeck_chart(deck, use_container_width=True)