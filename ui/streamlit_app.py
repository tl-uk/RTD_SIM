#!/usr/bin/env python3
"""
RTD_SIM Unified Visualization - REFACTORED VERSION

Clean separation of concerns:
- This file: UI orchestration only (~200 lines)
- simulation_runner.py: All simulation logic
- visualization.py: All visualization logic
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

# Import our clean modules
from simulation.simulation_runner import SimulationConfig, run_simulation
from visualiser.visualization import (  # ← Updated path
    render_map,
    render_mode_adoption_chart,
    render_emissions_chart,
    render_infrastructure_metrics,
    render_cascade_chart,
    get_current_stats,
    get_mode_distribution,
    render_agent_distribution_analysis,
    MODE_COLORS_HEX,
)
from visualiser.animation_controller import AnimationController

# Phase 4 availability check
try:
    from agent.user_stories import UserStoryParser
    from agent.job_stories import JobStoryParser
    PHASE_4_AVAILABLE = True
except ImportError:
    PHASE_4_AVAILABLE = False

# ============================================================================
# Page Configuration
# ============================================================================

st.set_page_config(
    page_title="RTD_SIM - Transport Decarbonization Simulator",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================================
# Session State
# ============================================================================

def init_session_state():
    """Initialize session state variables."""
    defaults = {
        'simulation_run': False,
        'results': None,
        'animation_controller': None,
        'show_agents': True,
        'show_routes': False,
        'show_infrastructure': True,  # NEW: Default ON for Phase 4.5
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# ============================================================================
# Title
# ============================================================================

st.title("🚦 RTD_SIM - Real-Time Transport Decarbonization Simulator")
st.markdown("**Phase 4.5: Infrastructure-Aware Agent-Based Model**")

# ============================================================================
# Sidebar Configuration
# ============================================================================

with st.sidebar:
    st.header("⚙️ Simulation Configuration")
    
    with st.form("config_form"):
        # Basic settings
        st.markdown("### 📊 Basic Settings")
        steps = st.number_input("Simulation Steps", 20, 200, 100, 20)
        num_agents = st.number_input("Number of Agents", 10, 100, 50, 10)
        
        # Location
        st.markdown("---")
        st.markdown("### 🗺️ Location")
        use_osm = st.checkbox("Use Real Street Network", value=True)
        if use_osm:
            place = st.text_input("City", "Edinburgh, UK")
        else:
            place = ""
        
        # Story selection
        st.markdown("---")
        st.markdown("### 📖 Story Selection")
        
        user_stories = []
        job_stories = []
        
        if PHASE_4_AVAILABLE:
            try:
                user_parser = UserStoryParser()
                job_parser = JobStoryParser()
                available_users = user_parser.list_available_stories()
                available_jobs = job_parser.list_available_stories()
                
                user_stories = st.multiselect(
                    "User Stories",
                    available_users,
                    default=available_users[:min(5, len(available_users))],
                    help="Select which personas to include"
                )
                
                job_stories = st.multiselect(
                    "Job Stories", 
                    available_jobs,
                    default=available_jobs[:min(5, len(available_jobs))],
                    help="Select which job contexts to include"
                )
            except:
                st.warning("Stories not found - using defaults")
                user_stories = ['eco_warrior', 'budget_student', 'business_commuter']
                job_stories = ['morning_commute', 'flexible_leisure']
        
        # Advanced features
        st.markdown("---")
        st.markdown("### 🔬 Advanced Features")
        
        use_congestion = st.checkbox("Enable Congestion", value=False)
        
        # Infrastructure (NEW for Phase 4.5)
        st.markdown("**🔌 Infrastructure (Phase 4.5)**")
        enable_infrastructure = st.checkbox("Enable Infrastructure Awareness", value=True,
            help="EV range constraints, charging stations, grid capacity")
        
        if enable_infrastructure:
            with st.expander("⚙️ Infrastructure Parameters"):
                num_chargers = st.slider("Public Chargers", 10, 100, 50, 10)
                num_depots = st.slider("Commercial Depots", 1, 20, 5, 1)
                grid_capacity_mw = st.slider("Grid Capacity (MW)", 100, 500, 2000, 1000, 100)
        else:
            num_chargers = 0
            num_depots = 0
            grid_capacity_mw = 1000
        
        # Social networks
        if PHASE_4_AVAILABLE:
            enable_social = st.checkbox("Enable Social Networks", value=True)
            
            if enable_social:
                use_realistic = st.checkbox("Use Realistic Influence", value=True)
                
                if use_realistic:
                    with st.expander("⚙️ Influence Parameters"):
                        decay_rate = st.slider("Decay Rate", 0.05, 0.30, 0.15, 0.05)
                        habit_weight = st.slider("Habit Weight", 0.0, 0.6, 0.4, 0.1)
                else:
                    decay_rate = 0.0
                    habit_weight = 0.0
            else:
                use_realistic = False
                decay_rate = 0.0
                habit_weight = 0.0
        else:
            enable_social = False
            use_realistic = False
            decay_rate = 0.0
            habit_weight = 0.0
        
        st.markdown("---")
        run_btn = st.form_submit_button("🚀 Run Simulation", 
                                        type="primary", 
                                        use_container_width=True)
    
    # Diagnostics Panel (NEW - for debugging Phase 4.5)
    if st.session_state.simulation_run:
        with st.expander("🔍 Infrastructure Diagnostics", expanded=False):
            results = st.session_state.results
            
            # EV agent count
            ev_agents = [a for a in results.agents if a.state.mode == 'ev']
            st.metric("EV Agents", f"{len(ev_agents)}/{len(results.agents)} ({len(ev_agents)/len(results.agents)*100:.1f}%)")
            
            # Agents with charger info
            agents_with_charger_info = sum(
                1 for a in results.agents 
                if hasattr(a.state, 'action_params') 
                and a.state.action_params
                and 'nearest_charger' in a.state.action_params
            )
            st.metric("Agents w/ Charger Info", f"{agents_with_charger_info}/{len(results.agents)}")
            
            # Infrastructure state
            if results.infrastructure:
                current_charging = len(results.infrastructure.agent_charging_state)
                st.metric("Currently Charging", current_charging)
                
                # Peak charging (from history)
                if results.infrastructure.historical_utilization:
                    peak_util = max(results.infrastructure.historical_utilization)
                    peak_load = peak_util * results.infrastructure.grid_regions['default'].capacity_mw
                    st.metric("Peak Grid Load", f"{peak_load:.1f} MW ({peak_util:.1%})")
                
                # Charging attempts log
                st.markdown("**Charging Activity:**")
                occupied = sum(s.currently_occupied for s in results.infrastructure.charging_stations.values())
                total_ports = sum(s.num_ports for s in results.infrastructure.charging_stations.values())
                st.write(f"- Occupied ports: {occupied}/{total_ports}")
                st.write(f"- Active charging sessions: {current_charging}")
                
                # Show sample agent params
                st.markdown("**Sample EV Agent Params:**")
                for a in ev_agents[:3]:
                    if hasattr(a.state, 'action_params') and a.state.action_params:
                        st.code(f"{a.state.agent_id}: distance={a.state.distance_km:.1f}km, arrived={a.state.arrived}")
                        if 'nearest_charger' in a.state.action_params:
                            st.code(f"  charger: {a.state.action_params.get('nearest_charger')}")
                    else:
                        st.code(f"{a.state.agent_id}: NO PARAMS")
    
    # Animation controls (after simulation)
    if st.session_state.simulation_run and st.session_state.animation_controller:
        st.markdown("---")
        st.header("🎬 Animation Controls")
        
        anim = st.session_state.animation_controller
        
        # Manual step buttons
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            if st.button("⮜", help="Reset", use_container_width=True, key='reset_btn'):
                anim.stop()
                st.rerun()
        with col2:
            if st.button("◀️", help="Step Back", use_container_width=True, key='back_btn'):
                if anim.current_step > 0:
                    anim.current_step -= 1
                    st.rerun()
        with col3:
            if st.button("▶️", help="Step Forward", use_container_width=True, key='fwd_btn'):
                if anim.current_step < anim.total_steps - 1:
                    anim.current_step += 1
                    st.rerun()
        with col4:
            if st.button("⭢", help="End", use_container_width=True, key='end_btn'):
                anim.seek(anim.total_steps - 1)
                st.rerun()
        
        # Auto-play toggle
        st.markdown("---")
        auto_play = st.checkbox("▶️ Auto-Play", value=anim.is_playing, key='auto_play')
        if auto_play != anim.is_playing:
            if auto_play:
                anim.play()
            else:
                anim.pause()
            st.rerun()
        
        # Time slider
        current_step = st.slider(
            "Timeline",
            0, anim.total_steps - 1,
            anim.current_step,
            key='time_slider'
        )
        
        if current_step != anim.current_step:
            anim.seek(current_step)
            st.rerun()
        
        st.progress(anim.get_progress(), 
                   text=f"Step {anim.current_step + 1}/{anim.total_steps}")
        
        # Layer visibility
        st.markdown("---")
        st.markdown("**Display Options**")
        st.session_state.show_agents = st.checkbox("Show Agents", 
            value=st.session_state.show_agents)
        st.session_state.show_routes = st.checkbox("Show Routes", 
            value=st.session_state.show_routes)
        st.session_state.show_infrastructure = st.checkbox("Show Infrastructure", 
            value=st.session_state.show_infrastructure)

# ============================================================================
# Simulation Execution
# ============================================================================

if run_btn:
    # Create config
    config = SimulationConfig(
        steps=steps,
        num_agents=num_agents,
        place=place,
        use_osm=use_osm,
        user_stories=user_stories,
        job_stories=job_stories,
        use_congestion=use_congestion,
        enable_social=enable_social,
        use_realistic_influence=use_realistic,
        decay_rate=decay_rate,
        habit_weight=habit_weight,
        enable_infrastructure=enable_infrastructure,
        num_chargers=num_chargers,
        num_depots=num_depots,
        grid_capacity_mw=grid_capacity_mw,
    )
    
    # Progress tracking
    progress_bar = st.progress(0, "Initializing...")
    status_text = st.empty()
    
    def update_progress(progress: float, message: str):
        progress_bar.progress(progress, message)
        status_text.info(message)
    
    # Run simulation
    results = run_simulation(config, progress_callback=update_progress)
    
    # Store results
    if results.success:
        st.session_state.simulation_run = True
        st.session_state.results = results
        st.session_state.animation_controller = AnimationController(
            total_steps=config.steps, fps=5
        )
        status_text.success("✅ Simulation complete!")
        progress_bar.empty()
        time.sleep(1)
        st.rerun()
    else:
        status_text.error(f"❌ Simulation failed: {results.error_message}")
        progress_bar.empty()

# ============================================================================
# Main Visualization
# ============================================================================

if not st.session_state.simulation_run:
    st.info("👈 Configure parameters in the sidebar and click **Run Simulation**")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 🎯 Quick Start")
        st.markdown("1. Select user & job stories")
        st.markdown("2. Enable infrastructure (Phase 4.5)")
        st.markdown("3. Click **Run Simulation**")
        st.markdown("4. Use animation controls")
    
    with col2:
        st.markdown("### 🎨 Color Guide")
        for mode, color in MODE_COLORS_HEX.items():
            st.markdown(f"<span style='color:{color};font-size:20px'>●</span> {mode.capitalize()}", 
                       unsafe_allow_html=True)
    
    st.stop()

# Get data
results = st.session_state.results
anim = st.session_state.animation_controller

current_data = results.time_series.get_timestep(anim.current_step)
if not current_data:
    st.error("No data available")
    st.stop()

agent_states = current_data['agent_states']
metrics = current_data.get('metrics', {})

# ============================================================================
# Tabs
# ============================================================================

tab_names = ["🗺️ Map", "📈 Mode Adoption", "🎯 Impact", "🌐 Network"]
if results.infrastructure:
    tab_names.append("🔌 Infrastructure")

tabs = st.tabs(tab_names)

# TAB 1: MAP
with tabs[0]:
    st.subheader(f"Live View - Step {anim.current_step + 1}/{anim.total_steps}")
    
    # Render map
    deck = render_map(
        agent_states=agent_states,
        show_agents=st.session_state.show_agents,
        show_routes=st.session_state.show_routes,
        show_infrastructure=st.session_state.show_infrastructure,
        infrastructure_manager=results.infrastructure,
    )
    
    st.pydeck_chart(deck, use_container_width=True)
    
    # Current stats
    st.markdown("---")
    stats = get_current_stats(agent_states, metrics)
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Arrivals", stats['arrivals'])
    col2.metric("Most Popular", stats['most_popular_mode'])
    col3.metric("Emissions", stats['total_emissions'])
    col4.metric("Agents w/ Routes", stats['agents_with_routes'])

# TAB 2: MODE ADOPTION
with tabs[1]:
    st.subheader("📈 Mode Adoption Over Time")
    
    fig = render_mode_adoption_chart(results.adoption_history, anim.current_step)
    st.plotly_chart(fig, use_container_width=True)
    
    # Statistics
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**Peak Adoption:**")
        for mode in ['walk', 'bike', 'bus', 'car', 'ev']:
            if mode in results.adoption_history and results.adoption_history[mode]:
                peak = max(results.adoption_history[mode]) * 100
                color = MODE_COLORS_HEX[mode]
                st.markdown(f"<span style='color:{color}'>●</span> {mode.capitalize()}: {peak:.1f}%", 
                           unsafe_allow_html=True)
    
    with col2:
        st.markdown("**Current Share:**")
        mode_dist = get_mode_distribution(agent_states)
        for _, row in mode_dist.iterrows():
            st.markdown(f"<span style='color:{row['color']}'>●</span> {row['mode']}: {row['percentage']:.1f}%", 
                       unsafe_allow_html=True)

# TAB 3: IMPACT
with tabs[2]:
    st.subheader("🎯 Environmental Impact")
    
    fig = render_emissions_chart(results.time_series)
    st.plotly_chart(fig, use_container_width=True)

# TAB 4: NETWORK
with tabs[3]:
    st.subheader("🌐 Social Network Analysis")
    
    if results.network:
        net_metrics = results.network.get_network_metrics()
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Connections", net_metrics.total_ties)
        col2.metric("Avg Degree", f"{net_metrics.avg_degree:.1f}")
        col3.metric("Clustering", f"{net_metrics.clustering_coefficient:.2f}")
        
        if results.cascade_events:
            st.markdown("### 🌊 Cascade Events")
            fig = render_cascade_chart(results.cascade_events)
            if fig:
                st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Social network not enabled")

# TAB 5: INFRASTRUCTURE (NEW)
if results.infrastructure:
    with tabs[4]:
        st.subheader("🔌 Infrastructure Metrics")
        
        infra_data = render_infrastructure_metrics(results.infrastructure)
        metrics = infra_data['metrics']
        
        col1, col2, col3, col4 = st.columns(4)
        
        col1.metric(
            "Charger Utilization",
            f"{metrics['utilization']:.1%}",
            delta="High" if metrics['utilization'] > 0.7 else "Normal"
        )
        
        col2.metric(
            "Grid Load",
            f"{metrics['grid_load_mw']:.1f} MW",
            delta=f"{metrics['grid_utilization']:.0%}"
        )
        
        col3.metric(
            "Queued Agents",
            metrics['queued_agents'],
            delta="⚠️" if metrics['queued_agents'] > 10 else "✅"
        )
        
        col4.metric(
            "Hotspots",
            len(infra_data['hotspots']),
            delta="Critical" if len(infra_data['hotspots']) > 5 else "OK"
        )
        
        # Grid stress over time
        if infra_data['grid_figure']:
            st.plotly_chart(infra_data['grid_figure'], use_container_width=True)

# ============================================================================
# Auto-advance animation
# ============================================================================

if anim.is_playing:
    time.sleep(0.3 / anim.speed_multiplier)
    if anim.current_step < anim.total_steps - 1:
        anim.current_step += 1
        st.rerun()
    else:
        anim.pause()
        st.rerun()

# ============================================================================
# Footer
# ============================================================================

st.markdown("---")

col1, col2 = st.columns([2, 1])

with col1:
    if results.infrastructure:
        st.success("✅ **Infrastructure-Aware Mode** - Phase 4.5 Active")
    elif results.network and st.session_state.get('use_realistic_influence'):
        st.success("✅ **Realistic Social Influence Active**")
    elif results.network:
        st.info("📊 **Deterministic Influence Active**")
    else:
        st.info("🔷 **No Social Influence**")

with col2:
    if results.desire_std:
        std = results.desire_std
        st.metric(
            "Desire Diversity",
            f"σ={std['eco']:.3f}",
            delta="Good" if std['eco'] > 0.15 else "Low",
            delta_color="normal" if std['eco'] > 0.15 else "inverse"
        )

st.caption("**RTD_SIM** - Real-Time Decarbonization Simulator | Phase 4.5 Infrastructure-Aware")