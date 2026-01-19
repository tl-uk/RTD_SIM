"""
ui/tabs/map_tab.py

Map visualization tab - extracted from main_tabs.py
"""

import streamlit as st
import sys
from pathlib import Path

parent_dir = Path(__file__).resolve().parent.parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from visualiser.visualization import render_map, get_current_stats


def render_map_tab(results, anim, current_data):
    """
    Render map visualization tab.
    
    Args:
        results: SimulationResults object
        anim: AnimationController
        current_data: Current timestep data
    """
    agent_states = current_data['agent_states']
    metrics = current_data.get('metrics', {})
    
    st.subheader(f"Live View - Step {anim.current_step + 1}/{anim.total_steps}")
    
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