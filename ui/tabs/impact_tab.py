# ============================================================================
# ui/tabs/impact_tab.py
# ============================================================================

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

from visualiser.visualization import render_emissions_chart

def render_impact_tab(results, anim, current_data):  # FIXED: Added anim, current_data
    """
    Render environmental impact tab.
    
    Args:
        results: SimulationResults object
        anim: AnimationController (not used but kept for consistency)
        current_data: Current timestep data (not used but kept for consistency)
    """
    st.subheader("🎯 Environmental Impact")
    
    fig = render_emissions_chart(results.time_series)
    st.plotly_chart(fig, use_container_width=True)
