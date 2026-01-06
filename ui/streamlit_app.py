#!/usr/bin/env python3
"""
RTD_SIM Unified Visualization - Phase 4.5B Ready
Main entry point with modular UI components

This should be placed in: RTD_SIM/ui/streamlit_app.py
"""

from __future__ import annotations
import sys
from pathlib import Path
import time

# Project root setup - adjust based on location of this file
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parent.parent  # Go up from ui/ to RTD_SIM/
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

# Import UI modules (from same directory)
from ui.sidebar_config import render_sidebar_config
from ui.diagnostics_panel import render_diagnostics_panel
from ui.animation_controls import render_animation_controls
from ui.main_tabs import render_main_tabs
from ui.welcome_screen import render_welcome_screen
from ui.status_footer import render_status_footer

# Import simulation core
from simulation.simulation_runner import run_simulation
from visualiser.animation_controller import AnimationController

# Initialize Streamlit
st.set_page_config(
    page_title="RTD_SIM - Transport Decarbonization Simulator",
    layout="wide",
    initial_sidebar_state="expanded"
)

def init_session_state():
    """Initialize session state variables."""
    defaults = {
        'simulation_run': False,
        'results': None,
        'animation_controller': None,
        'show_agents': True,
        'show_routes': False,
        'show_infrastructure': True,
        'current_region': None,
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# Header
st.title("🚦 RTD_SIM - Real-Time Transport Decarbonization Simulator")
st.markdown("**Phase 4.5B: Policy Scenario Framework**")

# Show active region
if st.session_state.simulation_run and st.session_state.current_region:
    results = st.session_state.results
    if results.env and results.env.graph_loaded:
        stats = results.env.get_graph_stats()
        st.info(f"🗺️ **Active Region**: {st.session_state.current_region} | "
               f"{stats['nodes']:,} nodes, {stats['edges']:,} edges")

# Sidebar configuration
with st.sidebar:
    config, run_btn = render_sidebar_config()

# Run simulation
if run_btn:
    progress_bar = st.progress(0, "Initializing...")
    status_text = st.empty()
    
    def update_progress(progress: float, message: str):
        progress_bar.progress(progress, message)
        status_text.info(message)
    
    results = run_simulation(config, progress_callback=update_progress)
    
    if results.success:
        st.session_state.simulation_run = True
        st.session_state.results = results
        st.session_state.animation_controller = AnimationController(
            total_steps=config.steps, fps=5
        )
        
        # Store region name
        if config.extended_bbox:
            st.session_state.current_region = "Central Scotland (Edinburgh-Glasgow)"
        elif config.place:
            st.session_state.current_region = config.place
        else:
            st.session_state.current_region = "Unknown Region"
        
        status_text.success("✅ Simulation complete!")
        progress_bar.empty()
        time.sleep(1)
        st.rerun()
    else:
        status_text.error(f"❌ Simulation failed: {results.error_message}")
        progress_bar.empty()

# Main content area
if not st.session_state.simulation_run:
    render_welcome_screen()
    st.stop()

# Simulation running - show controls and results
results = st.session_state.results
anim = st.session_state.animation_controller

# Diagnostics panel (in sidebar)
with st.sidebar:
    render_diagnostics_panel(results)

# Animation controls (in sidebar)
with st.sidebar:
    render_animation_controls(anim)

# Main visualization tabs
# Handle time_series as list of dicts
if isinstance(results.time_series, list):
    current_data = results.time_series[anim.current_step] if anim.current_step < len(results.time_series) else None
else:
    current_data = results.time_series.get_timestep(anim.current_step)
    
if not current_data:
    st.error("No data available")
    st.stop()

render_main_tabs(results, anim, current_data)

# Status footer
render_status_footer(results)

# Auto-play logic
if anim.is_playing:
    time.sleep(0.3 / anim.speed_multiplier)
    if anim.current_step < anim.total_steps - 1:
        anim.current_step += 1
        st.rerun()
    else:
        anim.pause()
        st.rerun()

st.caption("**RTD_SIM** - Phase 4.5B: Policy Scenario Framework | Policy Testing Ready")