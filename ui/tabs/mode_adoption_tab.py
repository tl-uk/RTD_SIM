"""
ui/tabs/mode_adoption_tab.py

Mode Adoption visualization tab - extracted from main_tabs.py
"""

import streamlit as st
import sys
from pathlib import Path

parent_dir = Path(__file__).resolve().parent.parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from visualiser.visualization import render_mode_adoption_chart, get_mode_distribution, MODE_COLORS_HEX 

def render_mode_adoption_tab(results, anim, agent_states):
    """
    Render mode adoption tab.
    
    Args:
        results: SimulationResults object
        anim: AnimationController
        agent_states: Current agent states
    """
    st.subheader("🚍 Mode Adoption Over Time")
    
    # Get mode distribution data
    mode_distribution = get_mode_distribution(agent_states, results.modes)
    
    # Render chart
    chart = render_mode_adoption_chart(
        mode_distribution=mode_distribution,
        modes=results.modes,
        mode_colors=MODE_COLORS_HEX,
        current_step=anim.current_step,
        total_steps=anim.total_steps,
    )
    
    st.altair_chart(chart, use_container_width=True)

   
    
    # fig = render_mode_adoption_chart(results.adoption_history, anim.current_step)
    # st.plotly_chart(fig, width='stretch')
    
    # col1, col2 = st.columns(2)
    
    # with col1:
    #     st.markdown("**Peak Adoption:**")
    #     for mode in ['walk', 'bike', 'bus', 'car', 'ev', 'van_electric', 'van_diesel']:
    #         if mode in results.adoption_history and results.adoption_history[mode]:
    #             peak = max(results.adoption_history[mode]) * 100
    #             color = MODE_COLORS_HEX.get(mode, '#888888')
    #             st.markdown(
    #                 f"<span style='color:{color}'>●</span> {mode.capitalize()}: {peak:.1f}%", 
    #                 unsafe_allow_html=True
    #             )
    
    # with col2:
    #     st.markdown("**Current Share:**")
    #     mode_dist = get_mode_distribution(agent_states)
    #     for _, row in mode_dist.iterrows():
    #         st.markdown(
    #             f"<span style='color:{row['color']}'>●</span> {row['mode']}: {row['percentage']:.1f}%", 
    #             unsafe_allow_html=True
    #         )