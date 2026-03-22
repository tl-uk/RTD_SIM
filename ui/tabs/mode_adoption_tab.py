"""
ui/tabs/mode_adoption_tab.py

This module contains the rendering function for the Mode Adoption tab in the RTD_SIM UI. 

It visualizes the adoption of different transportation modes over time, showing both 
historical trends and current distribution. The tab is designed to provide insights into 
how different policies and scenarios impact mode choice among agents in the simulation.

"""

import streamlit as st
import sys
from pathlib import Path

parent_dir = Path(__file__).resolve().parent.parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from visualiser.visualization import (
    render_mode_adoption_chart,
    get_mode_distribution,
    MODE_COLORS_HEX
)

# Added anim and current_data parameters to maintain consistency with other tabs, even 
# if not used directly in this function. This allows for future enhancements where we 
# might want to use animation state or current data for more dynamic visualisations.
def render_mode_adoption_tab(results, anim, current_data):
    """
    Render mode adoption charts.
    
    Args:
        results: SimulationResults object
        anim: AnimationController
        current_data: Current timestep data
    """
    agent_states = current_data['agent_states']
    
    st.subheader("📈 Mode Adoption Over Time")
    
    # Render adoption chart
    fig = render_mode_adoption_chart(results.adoption_history, anim.current_step)
    st.plotly_chart(fig, width='stretch')
    
    # Two-column layout
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**Peak Adoption:**")
        
        # Show peak adoption for each mode
        for mode in ['walk', 'bike', 'bus', 'car', 'ev', 'van_electric', 'van_diesel', 
                     'truck_electric', 'truck_diesel', 'hgv_electric', 'hgv_diesel']:
            if mode in results.adoption_history and results.adoption_history[mode]:
                peak = max(results.adoption_history[mode])
                total_agents = len(agent_states)
                peak_pct = (peak / total_agents * 100) if total_agents > 0 else 0
                color = MODE_COLORS_HEX.get(mode, '#888888')
                st.markdown(
                    f"<span style='color:{color}'>●</span> {mode.replace('_', ' ').title()}: {peak_pct:.1f}%", 
                    unsafe_allow_html=True
                )
    
    with col2:
        st.markdown("**Current Share:**")
        
        # Call get_mode_distribution with just agent_states
        # The function should calculate mode distribution from agent_states directly
        mode_dist = get_mode_distribution(agent_states)
        
        # Display current distribution
        for _, row in mode_dist.iterrows():
            st.markdown(
                f"<span style='color:{row['color']}'>●</span> {row['mode']}: {row['percentage']:.1f}%", 
                unsafe_allow_html=True
            )