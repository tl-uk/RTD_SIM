"""
ui/streamlit_app.py

RTD_SIM Unified Visualization - Phase 5.2 Fixed
Main entry point with policy diagnostics properly integrated

FIXES:
- Policy Diagnostics tab no longer duplicated
- Config properly stored in session state
- Tab always shows (handles both policy/no-policy cases)
- Proper parameter passing to diagnostics tab
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
    render_environmental_tab,
    render_analytics_tab,
)

# Import policy diagnostics
from ui.tabs.policy_diagnostics_tab import render_policy_diagnostics_tab

# Import System Dynamics tab (Phase 5.3)
from ui.tabs.system_dynamics_tab import render_system_dynamics_tab

# Import Sensitivity Analysis tab (Phase 5.4)
from ui.tabs.sensitivity_analysis_tab import render_sensitivity_analysis_tab
from ui.report_generator import render_report_generator_button

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
        'show_routes': True,  # Routes default ON
        'show_infrastructure': True,
        'current_region': None,
        'policy_engine': None,
        'combined_scenario_active': False,
        'last_config': None,  # CRITICAL: Store config for diagnostics
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# Header
st.title("🚦 RTD_SIM - Real-Time Transport Decarbonization Simulator")
st.markdown("**Phase 5.2: Interactive Policy Configuration**")

# Show active region
if st.session_state.simulation_run and st.session_state.current_region:
    results = st.session_state.results
    if results.env and results.env.graph_loaded:
        stats = results.env.get_graph_stats()
        info_text = f"🗺️ **Active Region**: {st.session_state.current_region} | {stats['nodes']:,} nodes, {stats['edges']:,} edges"
        
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
    
    # CRITICAL: Store config BEFORE running simulation
    st.session_state.last_config = config
    
    results = run_simulation(config, progress_callback=update_progress)
    
    if results.success:
        st.session_state.simulation_run = True
        st.session_state.results = results
        st.session_state.animation_controller = AnimationController(
            total_steps=config.steps, fps=5
        )
        
        # Store region name
        if hasattr(config, 'region_name') and config.region_name:
            st.session_state.current_region = config.region_name
        elif config.extended_bbox:
            st.session_state.current_region = "Custom Region (BBox)"
        elif config.place:
            st.session_state.current_region = config.place
        else:
            st.session_state.current_region = "Unknown Region"
        
        # Check if combined scenario was active
        if config.combined_scenario_data is not None:
            st.session_state.combined_scenario_active = True
            
            # Ensure policy_status exists
            if not hasattr(results, 'policy_status') or not results.policy_status:
                infrastructure = results.infrastructure
                grid_util = 0.0
                charger_util = 0.0
                
                if infrastructure:
                    try:
                        grid_util = infrastructure.grid.get_utilization()
                        metrics = infrastructure.get_infrastructure_metrics()
                        charger_util = metrics.get('charger_utilization', 0.0)
                    except:
                        pass
                
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
        else:
            st.session_state.combined_scenario_active = False
        
        status_text.success("✅ Simulation complete!")
        progress_bar.empty()
        time.sleep(1)
        st.rerun()
    else:
        status_text.error(f"❌ Simulation failed: {results.error_message}")
        progress_bar.empty()

# Main content
if not st.session_state.simulation_run:
    render_welcome_screen()
    st.stop()

results = st.session_state.results
anim = st.session_state.animation_controller
config = st.session_state.last_config

# Sidebar panels
with st.sidebar:
    render_diagnostics_panel(results)
    render_animation_controls(anim)
    
    # Phase 5.4: Report Generator
    if config:
        render_report_generator_button(results, config)

# Get current timestep data
if isinstance(results.time_series, list):
    current_data = results.time_series[anim.current_step] if anim.current_step < len(results.time_series) else None
else:
    current_data = results.time_series.get_timestep(anim.current_step)
    
if not current_data:
    st.error("No data available")
    st.stop()

# Build tab list
tab_configs = [
    ("🗺️ Map", render_map_tab),
    ("📈 Mode Adoption", render_mode_adoption_tab),
    ("🎯 Impact", render_impact_tab),
    ("🌐 Network", render_network_tab),
]

if results.infrastructure:
    tab_configs.append(("🔌 Infrastructure", render_infrastructure_tab))

if results.scenario_report:
    tab_configs.append(("📋 Scenario Report", render_scenario_report_tab))

if st.session_state.combined_scenario_active:
    tab_configs.append(("🔗 Combined Policies", render_combined_scenarios_tab))

if config.weather_enabled or config.track_air_quality:
    tab_configs.append(("🌤️ Environmental", render_environmental_tab))

if config.enable_analytics:
    tab_configs.append(("📊 Analytics", render_analytics_tab))

# Phase 5.3: System Dynamics tab (show if attribute exists - tab handles empty data internally)
if hasattr(results, 'system_dynamics_history'):
    tab_configs.append(("🔬 System Dynamics", render_system_dynamics_tab))

# Phase 5.4: Sensitivity Analysis tab (show if SD data and derivative module available)
if hasattr(results, 'system_dynamics_history') and results.system_dynamics_history:
    try:
        from analytics.sd_derivative_analysis import compute_sensitivity_metrics
        tab_configs.append(("🧮 Sensitivity Analysis", render_sensitivity_analysis_tab))
    except ImportError:
        pass  # Module not available, skip tab

# ALWAYS show Policy Diagnostics (handles both cases internally)
tab_configs.append(("🔍 Policy Diagnostics", render_policy_diagnostics_tab))

# Create and render tabs
tab_names = [name for name, _ in tab_configs]

# WORKAROUND: Hidden marker forces tab refresh when display options change
# This invisible HTML comment triggers Streamlit's change detection
st.markdown(
    f"<!-- refresh:{st.session_state.show_agents}:{st.session_state.show_routes}:{st.session_state.show_infrastructure}:{anim.current_step} -->", 
    unsafe_allow_html=True
)

tabs = st.tabs(tab_names)

for i, (tab_name, render_func) in enumerate(tab_configs):
    with tabs[i]:
        if tab_name == "🔍 Policy Diagnostics":
            # Diagnostics needs config, not current_data
            render_func(results, config)
        elif tab_name == "🔬 System Dynamics":
            # SD tab needs all three args
            render_func(results, anim, current_data)
        else:
            # Standard tabs
            render_func(results, anim, current_data)

# Status footer
render_status_footer(results)

# Auto-play
if anim.is_playing:
    time.sleep(0.3 / anim.speed_multiplier)
    if anim.current_step < anim.total_steps - 1:
        anim.current_step += 1
        st.rerun()
    else:
        anim.pause()
        st.rerun()

st.caption("**RTD_SIM** - Interactive Policy Configuration")