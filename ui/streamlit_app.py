#!/usr/bin/env python3
"""
RTD_SIM Unified Visualization - Phase 5.1 Refactored
Main entry point with modular tab components

CHANGES:
- Import individual tab modules from ui/tabs/
- Initialize policy engine before simulation
- Pass policy_engine to simulation loop
- Render combined scenarios tab if policy active
"""

from __future__ import annotations
import sys
from pathlib import Path
import time

# Project root setup
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

# Import UI modules
from ui.sidebar_config import render_sidebar_config
from ui.diagnostics_panel import render_diagnostics_panel
from ui.animation_controls import render_animation_controls
from ui.welcome_screen import render_welcome_screen
from ui.status_footer import render_status_footer

# Import individual tab modules
from ui.tabs import (
    render_map_tab,
    render_mode_adoption_tab,
    render_impact_tab,
    render_network_tab,
    render_infrastructure_tab,
    render_scenario_report_tab,
    render_combined_scenarios_tab,
    render_environmental_tab,  # NEW
)

# Import simulation core
from simulation.simulation_runner import run_simulation
from visualiser.animation_controller import AnimationController

# NEW: Import policy engine initialization
from simulation.execution.dynamic_policies import initialize_policy_engine

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
        # NEW: Policy engine state
        'policy_engine': None,
        'combined_scenario_active': False,
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# Header
st.title("🚦 RTD_SIM - Real-Time Transport Decarbonization Simulator")
st.markdown("**Phase 5.1: Dynamic Policy Engine with Scenario Combinations**")

# Show active region
if st.session_state.simulation_run and st.session_state.current_region:
    results = st.session_state.results
    if results.env and results.env.graph_loaded:
        stats = results.env.get_graph_stats()
        
        # Show region info with policy status
        info_text = f"🗺️ **Active Region**: {st.session_state.current_region} | {stats['nodes']:,} nodes, {stats['edges']:,} edges"
        
        # Add policy status if active
        if st.session_state.combined_scenario_active:
            info_text += " | 🔗 **Combined Scenario Active**"
        
        st.info(info_text)

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
    
    # Run simulation (will handle policy engine internally via config)
    # Store config in session state for debugging
    st.session_state.last_config = config
    
    results = run_simulation(config, progress_callback=update_progress)
    
    if results.success:
        st.session_state.simulation_run = True
        st.session_state.results = results
        st.session_state.animation_controller = AnimationController(
            total_steps=config.steps, fps=5
        )
        
        # Store region name from config
        if hasattr(config, 'region_name') and config.region_name:
            st.session_state.current_region = config.region_name
        elif config.extended_bbox:
            st.session_state.current_region = "Custom Region (BBox)"
        elif config.place:
            st.session_state.current_region = config.place
        else:
            st.session_state.current_region = "Unknown Region"
        
        # Check if combined scenario was active (PATCHED for Phase 5.1)
        # Force tab to appear if combined scenario was selected in config
        if config.combined_scenario_data is not None:
            st.session_state.combined_scenario_active = True
            st.session_state.combined_scenario_name = config.combined_scenario_data.get('name', 'Unknown')
            
            # If policy_status missing, create minimal version for tab display
            if not hasattr(results, 'policy_status') or not results.policy_status:
                # Get infrastructure instance from results
                infrastructure = results.infrastructure
                
                # Safely calculate metrics
                grid_util = 0.0
                charger_util = 0.0
                
                if infrastructure:
                    try:
                        grid_util = infrastructure.grid.get_utilization()
                        metrics = infrastructure.get_infrastructure_metrics()
                        charger_util = metrics.get('charger_utilization', 0.0)
                    except Exception as e:
                        import logging
                        logging.warning(f"Could not get infrastructure metrics: {e}")
                
                results.policy_status = {
                    'scenario_name': config.combined_scenario_data.get('name', 'Unknown'),
                    'base_scenarios': config.combined_scenario_data.get('base_scenarios', []),
                    'rules_triggered': 0,
                    'total_interaction_rules': len(config.combined_scenario_data.get('interaction_rules', [])),
                    'active_feedback_loops': 0,
                    'simulation_state': {
                        'ev_adoption': 0.0,
                        'grid_utilization': grid_util,
                        'charger_utilization': charger_util,
                    },
                    'constraints': {},
                }
                st.warning("⚠️ Policy engine data incomplete - showing minimal status")
        else:
            st.session_state.combined_scenario_active = False
        
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

# ============================================================================
# Build dynamic tab list based on what's available
# ============================================================================
tab_configs = [
    ("🗺️ Map", render_map_tab),
    ("📈 Mode Adoption", render_mode_adoption_tab),
    ("🎯 Impact", render_impact_tab),
    ("🌐 Network", render_network_tab),
]

# Add infrastructure tab if available
if results.infrastructure:
    tab_configs.append(("🔌 Infrastructure", render_infrastructure_tab))

# Add scenario report tab if simple scenario active
if results.scenario_report:
    tab_configs.append(("📋 Scenario Report", render_scenario_report_tab))

# Add combined scenarios tab if combined scenario was active
if st.session_state.combined_scenario_active:
    tab_configs.append(("🔗 Combined Policies", render_combined_scenarios_tab))

# Add environmental tab if weather or air quality tracking enabled
if config.weather_enabled or config.track_air_quality:
    tab_configs.append(("🌍 Environmental", render_environmental_tab))

# Create tabs
tab_names = [name for name, _ in tab_configs]
tabs = st.tabs(tab_names)

# Render each tab
for i, (_, render_func) in enumerate(tab_configs):
    with tabs[i]:
        render_func(results, anim, current_data)

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

st.caption("**RTD_SIM** - Phase 5.1: Dynamic Policy Engine | Combined Scenario Framework Active")