"""
ui/tabs/map_tab.py

Map visualization tab with live policy status widget.
"""

import streamlit as st
from visualiser.visualization import (
    render_map,
    get_current_stats,
)
from ui.widgets.policy_status_widget import render_policy_status_widget


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
    
    # Render map
    deck = render_map(
        agent_states=agent_states,
        show_agents=st.session_state.show_agents,
        show_routes=st.session_state.show_routes,
        show_infrastructure=st.session_state.show_infrastructure,
        infrastructure_manager=results.infrastructure,
    )
    
    st.pydeck_chart(deck, use_container_width=True)
    
    st.markdown("---")
    
    # Current stats
    stats = get_current_stats(agent_states, metrics)
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Arrivals", stats['arrivals'])
    col2.metric("Most Popular", stats['most_popular_mode'])
    col3.metric("Emissions", stats['total_emissions'])
    col4.metric("Agents w/ Routes", stats['agents_with_routes'])
    
    st.markdown("---")
    
    # ADD: Policy Status Widget (if policy active)
    if config and hasattr(results, 'policy_status') and results.policy_status:
        render_policy_status_widget(results, anim.current_step, config)