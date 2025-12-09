#!/usr/bin/env python3
"""
RTD_SIM Phase 2.3 - Advanced Visualization (FIXED)

Fixes:
- Multiple basemap options (including offline-friendly)
- Better animation loop
- Debug mode
- Explicit rerun handling
"""

from __future__ import annotations
import sys
from pathlib import Path
import random
import traceback
import time

# Project root setup
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
import pydeck as pdk
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from simulation.spatial_environment import SpatialEnvironment
from simulation.controller import SimulationController, SimulationConfig
from simulation.event_bus import EventBus
from agent.cognitive_abm import CognitiveAgent
from agent.bdi_planner import BDIPlanner

# Import visualization modules
from visualiser.data_adapters import (
    AgentDataAdapter, RouteDataAdapter, CongestionDataAdapter, TimeSeriesStorage
)
from visualiser.animation_controller import AnimationController, LayerManager
from visualiser.style_config import (
    MODE_COLORS, MODE_COLORS_HEX, AGENT_RADIUS_PIXELS, AGENT_OPACITY,
    ROUTE_WIDTH_PIXELS, ROUTE_OPACITY, ANIMATION_VIEW_STATE, Z_ORDER
)

# ============================================================================
# Page Configuration
# ============================================================================

st.set_page_config(
    page_title="RTD_SIM Phase 2.3 - Fixed",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================================
# Session State Initialization
# ============================================================================

def init_session_state():
    """Initialize all session state variables."""
    defaults = {
        'simulation_run': False,
        'time_series': None,
        'env': None,
        'animation_controller': None,
        'layer_manager': LayerManager(),
        'last_error': '',
        'debug_mode': False,
        'last_rerun_time': 0,
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# ============================================================================
# Title and Header
# ============================================================================

st.title("🚀 RTD_SIM Phase 2.3 - Fixed Visualization")

# Debug toggle
col1, col2 = st.columns([3, 1])
with col1:
    st.markdown("**Real-time agent animation | Interactive playback**")
with col2:
    debug = st.checkbox("Debug Mode", value=st.session_state.debug_mode)
    st.session_state.debug_mode = debug

# ============================================================================
# Sidebar - Simulation Configuration
# ============================================================================

with st.sidebar:
    st.header("⚙️ Simulation Setup")
    
    with st.form("sim_config"):
        # Basic parameters
        steps = st.number_input("Simulation Steps", 10, 500, 50, 10)
        num_agents = st.number_input("Number of Agents", 1, 100, 10, 5)
        step_minutes = st.number_input("Step Duration (min)", 0.1, 5.0, 0.5, 0.1)
        
        st.markdown("---")
        st.markdown("### 🗺️ Location")
        
        use_osm = st.checkbox("Use OpenStreetMap", value=True)
        
        if use_osm:
            place = st.text_input("Place Name", "Edinburgh, UK")
            network_type = st.selectbox("Network Type", ["all", "drive", "walk", "bike"])
            use_cache = st.checkbox("Use Cache", value=True)
        else:
            place = ""
            network_type = "all"
            use_cache = True
        
        st.markdown("---")
        st.markdown("### 🚦 Features")
        
        use_congestion = st.checkbox("Enable Congestion Tracking", value=False,
                                     help="Disable for faster initial testing")
        
        st.markdown("---")
        run_button = st.form_submit_button("🚀 Run Simulation", type="primary", use_container_width=True)
    
    # Animation controls (after simulation runs)
    if st.session_state.simulation_run and st.session_state.animation_controller:
        st.markdown("---")
        st.header("🎬 Animation Controls")
        
        anim = st.session_state.animation_controller
        
        # Play/pause button
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("⏮️", help="Reset", use_container_width=True):
                anim.stop()
                st.rerun()
        with col2:
            play_label = "⏸️ Pause" if anim.is_playing else "▶️ Play"
            if st.button(play_label, use_container_width=True):
                anim.toggle_play_pause()
                st.rerun()
        with col3:
            if st.button("⏭️", help="End", use_container_width=True):
                anim.seek(anim.total_steps - 1)
                st.rerun()
        
        # Time slider
        current_step = st.slider(
            "Timestep",
            0, anim.total_steps - 1,
            anim.current_step,
            key='time_slider'
        )
        
        if current_step != anim.current_step:
            anim.seek(current_step)
        
        # Speed control
        speed = st.select_slider(
            "Speed",
            options=[0.25, 0.5, 1.0, 2.0, 4.0],
            value=anim.speed_multiplier,
            format_func=lambda x: f"{x}x"
        )
        if speed != anim.speed_multiplier:
            anim.set_speed(speed)
        
        # Loop control
        loop = st.checkbox("Loop", value=anim.loop)
        if loop != anim.loop:
            anim.set_loop(loop)
        
        # Progress info
        progress = anim.get_progress()
        st.progress(progress, text=f"Step {anim.current_step + 1}/{anim.total_steps}")
        
        # Debug info
        if st.session_state.debug_mode:
            st.markdown("---")
            st.markdown("**Debug Info**")
            st.json({
                'is_playing': anim.is_playing,
                'current_step': anim.current_step,
                'speed': anim.speed_multiplier,
                'fps': anim.fps,
                'frame_duration': f"{anim.frame_duration:.3f}s",
            })
        
        st.markdown("---")
        st.header("👁️ Layer Visibility")
        
        layer_mgr = st.session_state.layer_manager
        
        for layer_name in ['agents', 'routes', 'congestion']:
            current = layer_mgr.is_visible(layer_name)
            new_val = st.checkbox(
                layer_name.capitalize(),
                value=current,
                key=f'layer_{layer_name}'
            )
            if new_val != current:
                layer_mgr.set_visible(layer_name, new_val)

# ============================================================================
# Simulation Execution
# ============================================================================

def run_simulation(steps, num_agents, place, use_osm, network_type, 
                   use_cache, step_minutes, use_congestion):
    """Execute simulation and store all timesteps."""
    
    progress_bar = st.progress(0, "Initializing...")
    status = st.empty()
    
    try:
        # Initialize environment
        status.info("🗺️ Loading environment...")
        cache_dir = Path.home() / ".rtd_sim_cache" / "osm_graphs"
        env = SpatialEnvironment(
            step_minutes=step_minutes,
            cache_dir=cache_dir,
            use_congestion=use_congestion
        )
        
        if use_osm:
            env.load_osm_graph(
                place=place or None,
                network_type=network_type,
                use_cache=use_cache
            )
            stats = env.get_graph_stats()
            status.success(f"✅ Loaded: {stats['nodes']:,} nodes, {stats['edges']:,} edges")
        
        progress_bar.progress(20)
        
        # Create agents
        status.info("🤖 Creating agents...")
        planner = BDIPlanner()
        agents = []
        
        for i in range(num_agents):
            desires = {
                "eco": [0.8, 0.3, 0.5][i % 3],
                "time": [0.4, 0.7, 0.5][i % 3],
                "cost": [0.2, 0.4, 0.5][i % 3],
                "comfort": [0.3, 0.5, 0.4][i % 3],
                "risk": [0.3, 0.2, 0.3][i % 3],
            }
            
            if use_osm and env.graph_loaded:
                pair = env.get_random_origin_dest()
                origin, dest = pair if pair else ((0, 0), (1, 1))
            else:
                origin = (random.uniform(-3.3, -3.15), random.uniform(55.9, 55.97))
                dest = (random.uniform(-3.3, -3.15), random.uniform(55.9, 55.97))
            
            agents.append(CognitiveAgent(
                seed=42 + i,
                agent_id=f"agent_{i+1}",
                desires=desires,
                planner=planner,
                origin=origin,
                dest=dest
            ))
        
        progress_bar.progress(30)
        
        # Setup simulation
        status.info("⚙️ Initializing simulation...")
        bus = EventBus()
        config = SimulationConfig(steps=steps)
        controller = SimulationController(
            bus, model=None, data_adapter=None,
            config=config, agents=agents, environment=env
        )
        
        # Create time series storage
        time_series = TimeSeriesStorage()
        
        # Run simulation with timestep storage
        status.info("🏃 Running simulation...")
        controller.start()
        
        for step in range(steps):
            controller.step()
            
            # Store agent states
            agent_states = []
            for agent in agents:
                agent_states.append({
                    'agent_id': agent.state.agent_id,
                    'location': agent.state.location,
                    'mode': agent.state.mode,
                    'arrived': agent.state.arrived,
                    'route': agent.state.route,
                    'distance_km': agent.state.distance_km,
                    'emissions_g': agent.state.emissions_g,
                    'travel_time_min': agent.state.travel_time_min,
                })
            
            # Get congestion if enabled
            congestion_heatmap = None
            if use_congestion and env.congestion_manager:
                congestion_heatmap = env.get_congestion_heatmap()
                
                for agent in agents:
                    if not agent.state.arrived and agent.state.route:
                        env.update_agent_congestion(agent.state.agent_id, None)
                
                env.advance_congestion_time()
            
            # Calculate metrics
            metrics = {
                'arrivals': sum(1 for a in agents if a.state.arrived),
                'total_emissions': sum(a.state.emissions_g for a in agents),
                'total_distance': sum(a.state.distance_km for a in agents),
            }
            
            # Store timestep
            time_series.store_timestep(step, agent_states, congestion_heatmap, metrics)
            
            # Update progress
            if step % max(1, steps // 10) == 0:
                progress_pct = 30 + int((step / steps) * 60)
                progress_bar.progress(progress_pct, f"Step {step}/{steps}")
        
        controller.stop()
        
        # Finalize
        progress_bar.progress(100, "✅ Complete!")
        status.success(f"✅ Simulation complete: {steps} steps, {num_agents} agents")
        
        # Store in session state
        st.session_state.simulation_run = True
        st.session_state.time_series = time_series
        st.session_state.env = env
        st.session_state.animation_controller = AnimationController(
            total_steps=steps,
            fps=5  # Lower FPS for more reliable updates
        )
        st.session_state.last_error = ''
        
        # Auto-enable agents layer
        st.session_state.layer_manager.set_visible('agents', True)
        
        return True
        
    except Exception as e:
        error_msg = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
        st.session_state.last_error = error_msg
        status.error("❌ Simulation failed")
        with st.expander("Error Details"):
            st.code(error_msg)
        return False
    finally:
        progress_bar.empty()

# Execute simulation if button clicked
if run_button:
    run_simulation(
        steps, num_agents, place, use_osm, network_type,
        use_cache, step_minutes, use_congestion
    )
    st.rerun()

# ============================================================================
# Main Visualization Area
# ============================================================================

if not st.session_state.simulation_run:
    st.info("👈 Configure simulation parameters and click 'Run Simulation' to begin")
    st.markdown("---")
    st.markdown("### 🎯 Quick Start")
    st.markdown("1. Use default settings (10 agents, 50 steps)")
    st.markdown("2. Disable congestion for faster testing")
    st.markdown("3. Click 'Run Simulation'")
    st.markdown("4. Wait ~20 seconds")
    st.markdown("5. Click '▶️ Play' to start animation")
    st.stop()

# Get current timestep data
time_series = st.session_state.time_series
anim = st.session_state.animation_controller
layer_mgr = st.session_state.layer_manager
env = st.session_state.env

current_data = time_series.get_timestep(anim.current_step)

if not current_data:
    st.error("No data available for current timestep")
    st.stop()

agent_states = current_data['agent_states']
congestion_heatmap = current_data.get('congestion_heatmap', {})
metrics = current_data.get('metrics', {})

# ============================================================================
# Deck.gl Map Visualization
# ============================================================================

st.subheader(f"🗺️ Live Simulation - Step {anim.current_step + 1}/{anim.total_steps}")

# Map style selector - ONLY Carto options (no Mapbox token needed)
map_style_options = {
    "Light": "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
    "Dark": "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
    "Voyager": "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json",
}

selected_style = st.selectbox(
    "Map Style",
    options=list(map_style_options.keys()),
    index=0  # Default to Light
)

map_style = map_style_options[selected_style]

# Prepare layers
layers = []

# Agent layer
if layer_mgr.is_visible('agents'):
    agent_df = AgentDataAdapter.agents_to_dataframe(agent_states, anim.current_step)
    
    if not agent_df.empty:
        if st.session_state.debug_mode:
            st.write("Agent data sample:")
            st.dataframe(agent_df.head())
        
        agent_layer = pdk.Layer(
            'ScatterplotLayer',
            data=agent_df,
            get_position='[lon, lat]',
            get_color='color',
            get_radius=AGENT_RADIUS_PIXELS,
            radius_scale=1,
            radius_min_pixels=5,
            radius_max_pixels=15,
            pickable=True,
            opacity=AGENT_OPACITY,
            stroked=True,
            filled=True,
            line_width_min_pixels=1,
            get_line_color=[255, 255, 255],
        )
        layers.append(agent_layer)

# Routes layer
if layer_mgr.is_visible('routes'):
    route_df = RouteDataAdapter.routes_to_dataframe(agent_states)
    
    if not route_df.empty:
        if st.session_state.debug_mode:
            st.write(f"Route data: {len(route_df)} routes")
        
        route_layer = pdk.Layer(
            'PathLayer',
            data=route_df,
            get_path='path',
            get_color='color',
            width_scale=1,
            width_min_pixels=ROUTE_WIDTH_PIXELS,
            pickable=True,
            opacity=ROUTE_OPACITY,
        )
        layers.append(route_layer)

# Congestion layer
if layer_mgr.is_visible('congestion') and congestion_heatmap and env:
    graph = env.graph_manager.primary_graph
    if graph:
        congestion_df = CongestionDataAdapter.congestion_to_dataframe(
            congestion_heatmap, graph
        )
        
        if not congestion_df.empty:
            if st.session_state.debug_mode:
                st.write(f"Congestion: {len(congestion_df)} edges")
            
            congestion_layer = pdk.Layer(
                'PathLayer',
                data=congestion_df,
                get_path='path',
                get_color='color',
                get_width='width',
                width_scale=1,
                width_min_pixels=2,
                pickable=True,
                opacity=0.8,
            )
            layers.append(congestion_layer)

# Calculate view state from agent positions
view_state = ANIMATION_VIEW_STATE.copy()
if agent_states:
    lons = [s['location'][0] for s in agent_states if s.get('location')]
    lats = [s['location'][1] for s in agent_states if s.get('location')]
    if lons and lats:
        view_state['longitude'] = sum(lons) / len(lons)
        view_state['latitude'] = sum(lats) / len(lats)

# Create deck
deck = pdk.Deck(
    layers=layers,
    initial_view_state=pdk.ViewState(**view_state),
    tooltip={
        'html': '<b>Agent:</b> {agent_id}<br/><b>Mode:</b> {mode}<br/><b>Arrived:</b> {arrived}',
        'style': {
            'backgroundColor': 'rgba(0, 0, 0, 0.8)',
            'color': 'white',
        }
    },
    map_style=map_style,
)

st.pydeck_chart(deck, width='stretch')

if st.session_state.debug_mode:
    st.write(f"**Layers:** {len(layers)}")
    st.write(f"**Map style:** {map_style}")

# ============================================================================
# Real-time Metrics
# ============================================================================

st.markdown("---")
st.subheader("📊 Current Metrics")

col1, col2, col3, col4 = st.columns(4)

arrivals = metrics.get('arrivals', 0)
total_agents = len(agent_states)
emissions = metrics.get('total_emissions', 0)
distance = metrics.get('total_distance', 0)

col1.metric("Arrivals", f"{arrivals}/{total_agents}")
col2.metric("Total Emissions", f"{emissions:.1f} g")
col3.metric("Total Distance", f"{distance:.2f} km")

# Modal share
modes = [s['mode'] for s in agent_states]
from collections import Counter
mode_counts = Counter(modes)
col4.metric("Active Modes", len(mode_counts))

# Show mode breakdown
with st.expander("Mode Breakdown"):
    mode_df = pd.DataFrame([
        {'Mode': mode, 'Count': count}
        for mode, count in mode_counts.items()
    ])
    st.dataframe(mode_df)

# ============================================================================
# Auto-advance animation (SIMPLIFIED & FIXED)
# ============================================================================

# Auto-advance if playing
if anim.is_playing:
    # Small delay to control speed
    time.sleep(0.2)  # 5 FPS
    
    # Advance one step
    if anim.current_step < anim.total_steps - 1:
        anim.current_step += 1
        st.rerun()
    else:
        # Reached end
        if anim.loop:
            anim.current_step = 0
            st.rerun()
        else:
            anim.pause()
            st.rerun()

# ============================================================================
# Footer
# ============================================================================

st.markdown("---")
st.caption("**RTD_SIM Phase 2.3 (Fixed)** | Real-Time Decarbonization Simulator")