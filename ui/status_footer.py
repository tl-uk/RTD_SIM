"""
ui/status_footer.py

This module implements the status footer for the simulation results page. 
It displays active features such as scenario presets, infrastructure-aware mode, 
and social influence type. It also shows a metric for desire diversity 
(standard deviation) to indicate how varied agent preferences are. 

The footer provides a quick overview of the current simulation state and 
key metrics, to help understand the implications of configuration choices 
and the dynamics of the system.

Status footer showing active features and system capabilities.
"""

import streamlit as st


def render_status_footer(results):
    """
    Render status footer showing system capabilities.
    
    Args:
        results: SimulationResults object
    """
    st.markdown("---")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Show active features
        if results.scenario_report:
            st.success(f"✅ **Scenario Active:** {results.scenario_report['name']}")
        elif results.infrastructure:
            st.success("✅ **Infrastructure-Aware Mode** - Active")
        elif results.network:
            if hasattr(results, 'use_realistic_influence') and results.use_realistic_influence:
                st.success("✅ **Realistic Social Influence Active**")
            else:
                st.info("📊 **Deterministic Influence Active**")
        else:
            st.info("📷 **No Social Influence**")
    
    with col2:
        # Show desire diversity metric
        if results.desire_std:
            std = results.desire_std
            st.metric(
                "Desire Diversity",
                f"σ={std['eco']:.3f}",
                delta="Good" if std['eco'] > 0.15 else "Low",
                delta_color="normal" if std['eco'] > 0.15 else "inverse"
            )