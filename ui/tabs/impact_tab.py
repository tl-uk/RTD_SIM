"""
ui/tabs/impact_tab.py

Impact visualization tab - extracted from main_tabs.py

"""

import streamlit as st
import sys
from pathlib import Path

parent_dir = Path(__file__).resolve().parent.parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from visualiser.visualization import render_emissions_chart, render_cascade_chart

def render_impact_tab(results):
    """
    Render impact visualization tab.
    
    Args:
        results: SimulationResults object
    """
    st.subheader("🎯 Impact Analysis")
    
    # Emissions Chart
    st.markdown("**Emissions Over Time**")
    emissions_chart = render_emissions_chart(results.emissions_history)
    st.altair_chart(emissions_chart, use_container_width=True)
    
    st.markdown("---")
    
    # Cascade Chart
    st.markdown("**Mode Shift Cascade Effects**")
    cascade_chart = render_cascade_chart(results.cascade_effects)
    st.altair_chart(cascade_chart, use_container_width=True)

    # st.subheader("🎯 Environmental Impact")
    
    # fig = render_emissions_chart(results.time_series)
    # st.plotly_chart(fig, width='stretch')