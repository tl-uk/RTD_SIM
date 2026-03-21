"""
ui/streamlit_app.py

RTD_SIM Unified Visualization
Main entry point with policy diagnostics properly integrated

FIXES:
- Wiring in OLLMA

To run: streamlit run ui/streamlit_app.py
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
# Import log capture (ADD THIS LINE)
from ui.log_capture import init_log_capture

# Import startup manager — auto-starts Ollama and checks Redis
from services.startup_manager import get_startup_manager

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

try:
    from ui.tabs.cognition_tab import render_cognition_tab
    COGNITION_TAB_AVAILABLE = True
except ImportError:
    COGNITION_TAB_AVAILABLE = False


# Import policy diagnostics
from ui.tabs.policy_diagnostics_tab import render_policy_diagnostics_tab

# Import System Dynamics tab
from ui.tabs.system_dynamics_tab import render_system_dynamics_tab

# Import Sensitivity Analysis tab
from ui.tabs.sensitivity_analysis_tab import render_sensitivity_analysis_tab
from ui.report_generator import render_report_generator_button

# Import SHAP Analysis tab
from ui.tabs.shap_analysis_tab import render_shap_analysis_tab

# Import Combination Report tab (Agent validation)
try:
    from ui.tabs.combination_report_tab import render_combination_report_tab
    COMBINATION_REPORT_AVAILABLE = True
except ImportError:
    COMBINATION_REPORT_AVAILABLE = False
    import logging
    logging.warning("Combination report tab not available")

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

    # Initialize log capture first so every subsequent log line is captured.
    if 'log_capture' not in st.session_state:
        st.session_state.log_capture = init_log_capture()
        import logging
        logger = logging.getLogger(__name__)
        logger.info("=" * 80)
        logger.info("RTD_SIM STREAMLIT APP STARTED")
        logger.info(f"Log file : {st.session_state.log_capture.get_log_path()}")
        logger.info(f"Log dir  : {st.session_state.log_capture.log_dir}")
        logger.info("=" * 80)

    # Service startup — auto-starts Ollama if not running, checks Redis.
    # Runs once per session; idempotent on reruns.
    if 'startup_manager' not in st.session_state:
        get_startup_manager()  # creates, checks services, stores in session_state

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
        'current_animation_step': 0,  # CRITICAL: Preserve step across reruns
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# Header
st.title("🚦 RTD_SIM - Real-Time Transport Decarbonization Simulator")
st.markdown("**Phase 10: Interactive Events & LLM Configuration**")

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
    # Show service status (Ollama, Redis) — collapsed by default
    if 'startup_manager' in st.session_state:
        st.session_state.startup_manager.render_status_sidebar()
    config, run_btn = render_sidebar_config()

# Run simulation
if run_btn:
    progress_bar = st.progress(0, "Initializing...")
    status_text = st.empty()
    
    def update_progress(progress: float, message: str):
        progress_bar.progress(progress, message)
        status_text.info(message)
    
    # Store config BEFORE running simulation so diagnostics can access 
    # it even if simulation fails
    st.session_state.last_config = config
    
    results = run_simulation(config, progress_callback=update_progress)
    
    if results.success:
        st.session_state.simulation_run = True
        st.session_state.results = results
        st.session_state.animation_controller = AnimationController(
            total_steps=config.steps, fps=5
        )
        # Reset animation step when starting new simulation
        st.session_state.current_animation_step = 0
        
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

# NOTE: Restore animation position from session state
# This preserves the step when checkboxes trigger reruns
if anim and 'current_animation_step' in st.session_state:
    anim.current_step = st.session_state.current_animation_step

# Sidebar panels
with st.sidebar:
    render_diagnostics_panel(results)
    
    # ======== TEMPORAL PROGRESS DISPLAY =========
    if hasattr(results, 'temporal_engine') and results.temporal_engine:
        st.markdown("---")
        st.markdown("### ⏰ Simulation Time")
        
        time_info = results.temporal_engine.get_time_info(anim.current_step)
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Date", time_info['date'])
        with col2:
            st.metric("Time", time_info['time'])
        
        # Context
        days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        day_name = days[time_info['day_of_week']]
        season = time_info['season'].capitalize()
        
        context = [f"**{day_name}**", f"**{season}**"]
        if time_info['is_rush_hour']:
            context.append("🚗 Rush Hour")
        if time_info['is_weekend']:
            context.append("📅 Weekend")
        
        st.caption(" | ".join(context))
        
        progress_str = results.temporal_engine.get_progress_string(anim.current_step)
        st.caption(f"📊 {progress_str}")
    
    # ======== ACTIVE EVENTS DISPLAY ========
    if hasattr(results, 'event_generator') and results.event_generator:
        active_events = results.event_generator.get_active_events()
        if active_events:
            st.markdown("---")
            st.markdown("### 🎲 Active Events")
            
            event_icons = {
                'traffic_congestion': '🚗',
                'weather_disruption': '🌧️',
                'infrastructure_failure': '🔌',
                'grid_stress': '⚡',
            }
            
            for event in active_events:
                icon = event_icons.get(event.event_type.value, '⚠️')
                st.caption(f"{icon} **{event.description}**")
                st.caption(f"   Remaining: {event.steps_remaining} steps")
                
                if event.impact_data:
                    impact_str = ", ".join([f"{k}: {v}" for k, v in list(event.impact_data.items())[:2]])
                    st.caption(f"   Impact: {impact_str}")
            
            st.caption(f"📊 {len(active_events)} active event(s)")
    
    render_animation_controls(anim)
    
    # Phase 5.4: Report Generator
    if config:
        render_report_generator_button(results, config)

    # Always show where the current log file is so it is easy to find
    # across different machines / launch directories.
    if 'log_capture' in st.session_state:
        st.markdown("---")
        log_path = st.session_state.log_capture.get_log_path()
        st.caption(f"📄 Log: `{log_path}`")

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

if COGNITION_TAB_AVAILABLE and results.agents and any(
    hasattr(a, 'user_story') for a in results.agents
):
    tab_configs.append(("🧠 Agent Cognition", render_cognition_tab))

if results.scenario_report:
    tab_configs.append(("📋 Scenario Report", render_scenario_report_tab))

if st.session_state.combined_scenario_active:
    tab_configs.append(("🔗 Combined Policies", render_combined_scenarios_tab))

if config.weather_enabled or config.track_air_quality:
    tab_configs.append(("🌤️ Environmental", render_environmental_tab))

if config.enable_analytics:
    tab_configs.append(("📊 Analytics", render_analytics_tab))

# System Dynamics tab (show if attribute exists - tab handles empty data internally)
if hasattr(results, 'system_dynamics_history'):
    tab_configs.append(("🔬 System Dynamics", render_system_dynamics_tab))

# Sensitivity Analysis tab (show if SD data and derivative module available)
if hasattr(results, 'system_dynamics_history') and results.system_dynamics_history:
    try:
        from analytics.sd_derivative_analysis import compute_sensitivity_metrics
        tab_configs.append(("🧮 Sensitivity Analysis", render_sensitivity_analysis_tab))
    except ImportError:
        pass  # Module not available, skip tab

# SHAP Analysis tab 
if hasattr(results, 'system_dynamics_history') and results.system_dynamics_history:
    try:
        from analytics.shap_analysis import run_shap_analysis_for_ui
        tab_configs.append(("🔍 SHAP Analysis", render_shap_analysis_tab))
    except ImportError:
        pass # Module not available, skip tab

# ALWAYS show Policy Diagnostics (handles both cases internally)
tab_configs.append(("🔍 Policy Diagnostics", render_policy_diagnostics_tab))

# Combination Report tab (ALWAYS show - doesn't need simulation results)
if COMBINATION_REPORT_AVAILABLE:
    tab_configs.append(("🔍 Agent Combinations", render_combination_report_tab))

# Create and render tabs
tab_names = [name for name, _ in tab_configs]

# HACK: Hidden marker forces tab refresh when display options change
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
        elif tab_name == "🔍 Agent Combinations":
            # Combination report needs no arguments (loads stories itself)
            render_func()
        elif tab_name == "🔬 System Dynamics":
            # SD tab needs all three args
            render_func(results, anim, current_data)
        else:
            # Standard tabs
            render_func(results, anim, current_data)

# Status footer
render_status_footer(results)

st.caption("**RTD_SIM** - Interactive Policy Configuration")