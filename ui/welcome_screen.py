"""
ui/welcome_screen.py

UI modules: Welcome screen and status footer
"""

import streamlit as st
from visualiser.visualization import MODE_COLORS_HEX


def render_welcome_screen():
    """Render welcome screen when no simulation is running."""
    st.info("👈 Configure parameters in the sidebar and click **Run Simulation**")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 🎯 Quick Start")
        st.markdown("1. Select region (City or Regional)")
        st.markdown("2. Choose user & job stories")
        st.markdown("3. Enable infrastructure")
        st.markdown("4. **(Optional)** Select policy scenario")
        st.markdown("5. Click **Run Simulation**")
    
    with col2:
        st.markdown("### 🎨 Color Guide")
        for mode, color in MODE_COLORS_HEX.items():
            st.markdown(
                f"<span style='color:{color};font-size:20px'>●</span> {mode.capitalize()}", 
                unsafe_allow_html=True
            )
    
    # Phase 4.5B info box
    st.markdown("---")
    st.info("""
    **🆕 Features:**
    - Policy scenario testing (EV subsidies, congestion charges, etc.)
    - Automated outcome comparison
    - YAML-based scenario configuration
    - Runtime policy injection
    """)
