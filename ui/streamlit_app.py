#!/usr/bin/env python3
"""
RTD_SIM Unified Visualization
Phases 1-4.1: Complete integration with clear, intuitive visualization

Key features:
- Color-coded agents by mode (walk=green, bike=blue, bus=orange, car=red, EV=purple)
- Story-driven agent generation
- Social network influence (realistic or deterministic)
- Clear, actionable plots and metrics
"""

from __future__ import annotations
import sys
from pathlib import Path
import random
import traceback
import time
from collections import Counter, defaultdict
import statistics

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

from simulation.spatial_environment import SpatialEnvironment
from simulation.controller import SimulationController, SimulationConfig
from simulation.event_bus import EventBus
from agent.bdi_planner import BDIPlanner

# Phase 3+4 imports
try:
    from agent.story_driven_agent import generate_balanced_population
    from agent.social_network import SocialNetwork
    from agent.social_influence_dynamics import (
        RealisticSocialInfluence,
        enhance_social_network_with_realism,
        calculate_satisfaction
    )
    PHASE_4_AVAILABLE = True
except ImportError:
    PHASE_4_AVAILABLE = False

# Visualization
from visualiser.data_adapters import TimeSeriesStorage
from visualiser.animation_controller import AnimationController

# ============================================================================
# Configuration
# ============================================================================

MODE_COLORS_RGB = {
    'walk': [34, 197, 94],    # Green
    'bike': [59, 130, 246],    # Blue
    'bus': [245, 158, 11],     # Orange/Amber
    'car': [239, 68, 68],      # Red
    'ev': [168, 85, 245],      # Purple
}

MODE_COLORS_HEX = {
    'walk': '#22c55e',
    'bike': '#3b82f6',
    'bus': '#f59e0b',
    'car': '#ef4444',
    'ev': '#a855f7',
}

st.set_page_config(
    page_title="RTD_SIM - Transport Decarbonization Simulator",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================================
# Session State
# ============================================================================

def init_session_state():
    defaults = {
        'simulation_run': False,
        'time_series': None,
        'env': None,
        'agents': None,
        'network': None,
        'influence_system': None,
        'animation_controller': None,
        'adoption_history': defaultdict(list),
        'cascade_events': [],
        'use_realistic_influence': True,
        'show_agents': True,
        'show_routes': False,
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# ============================================================================
# Title
# ============================================================================

st.title("🚦 RTD_SIM - Real-Time Transport Decarbonization Simulator")
st.markdown("**Interactive agent-based model | Story-driven behavior | Social influence dynamics**")

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
        
        # Advanced features
        st.markdown("---")
        st.markdown("### 🔬 Social Influence")
        
        if PHASE_4_AVAILABLE:
            enable_social = st.checkbox("Enable Social Networks", value=True,
                                       help="Agents influence each other's mode choices")
            
            if enable_social:
                use_realistic = st.checkbox("Use Realistic Influence", value=True,
                    help="Realistic: influences decay, habits form\nDeterministic: permanent influence")
                
                if use_realistic:
                    with st.expander("⚙️ Influence Parameters"):
                        decay_rate = st.slider("Decay Rate", 0.05, 0.30, 0.15, 0.05,
                            help="How fast peer influences fade")
                        habit_weight = st.slider("Habit Weight", 0.0, 0.6, 0.4, 0.1,
                            help="Importance of habit formation")
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
            st.info("Install Phase 4 packages for social networks")
        
        st.markdown("---")
        run_btn = st.form_submit_button("🚀 Run Simulation", 
                                        type="primary", 
                                        use_container_width=True)
    
    # Animation controls (after simulation)
    if st.session_state.simulation_run and st.session_state.animation_controller:
        st.markdown("---")
        st.header("🎬 Playback")
        
        anim = st.session_state.animation_controller
        
        # Controls
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("⏮️", use_container_width=True, key='reset'):
                anim.stop()
                st.rerun()
        
        with col2:
            # ✅ FIX: Better state management for play/pause
            play_label = "⏸️" if anim.is_playing else "▶️"
            if st.button(play_label, use_container_width=True, key='play'):
                anim.toggle_play_pause()
                st.rerun()
        
        with col3:
            if st.button("⏭️", use_container_width=True, key='end'):
                anim.seek(anim.total_steps - 1)
                st.rerun()
        
        # Slider
        step = st.slider("Timeline", 0, anim.total_steps - 1, anim.current_step,
                        key='timeline')
        if step != anim.current_step:
            anim.seek(step)
            st.rerun()  # FIX: Add rerun after seek
        
        st.progress(anim.get_progress(), 
                text=f"Step {anim.current_step + 1}/{anim.total_steps}")
        
        # Layer visibility
        st.markdown("---")
        st.markdown("**Display Options**")
        st.session_state.show_agents = st.checkbox("Show Agents", 
            value=st.session_state.show_agents)
        st.session_state.show_routes = st.checkbox("Show Routes", 
            value=st.session_state.show_routes)

# ============================================================================
# Simulation Execution
# ============================================================================

def run_simulation(steps, num_agents, place, use_osm, enable_social, 
                   use_realistic, decay_rate, habit_weight):
    """Run complete simulation with progress tracking."""
    
    progress = st.progress(0, "Initializing...")
    status = st.empty()
    
    try:
        # Environment
        status.info("🗺️ Loading environment...")
        cache_dir = Path.home() / ".rtd_sim_cache" / "osm_graphs"
        env = SpatialEnvironment(step_minutes=1.0, cache_dir=cache_dir, 
                                use_congestion=False)
        
        if use_osm and place:
            env.load_osm_graph(place=place, use_cache=True)
            stats = env.get_graph_stats()
            status.success(f"✅ Loaded {stats['nodes']:,} nodes")
        
        progress.progress(20)
        
        # Agents
        status.info("🤖 Creating agents...")
        planner = BDIPlanner()
        
        def random_od():
            if use_osm and env.graph_loaded:
                pair = env.get_random_origin_dest()
                return pair if pair else ((-3.19, 55.95), (-3.15, 55.97))
            return (
                (random.uniform(-3.3, -3.15), random.uniform(55.9, 55.97)),
                (random.uniform(-3.3, -3.15), random.uniform(55.9, 55.97))
            )
        
        if PHASE_4_AVAILABLE:
            agents = generate_balanced_population(
                num_agents=num_agents,
                user_story_ids=['eco_warrior', 'budget_student', 'business_commuter', 
                                'busy_parent', 'accessibility_user', 'delivery_driver'],
                job_story_ids=['morning_commute', 'flexible_leisure', 'school_run',
                            'delivery_job', 'emergency_trip'],
                origin_dest_generator=random_od,
                planner=planner,
                seed=42
            )
        else:
            from agent.cognitive_abm import CognitiveAgent
            agents = []
            for i in range(num_agents):
                origin, dest = random_od()
                agents.append(CognitiveAgent(
                    seed=42 + i,
                    agent_id=f"agent_{i+1}",
                    desires={'eco': 0.5, 'time': 0.5, 'cost': 0.5},
                    planner=planner,
                    origin=origin,
                    dest=dest
                ))
        
        status.success(f"✅ Created {len(agents)} agents")
        progress.progress(35)
        
        # Social network
        network = None
        influence_system = None
        
        if enable_social and PHASE_4_AVAILABLE:
            status.info("🌐 Building social network...")
            network = SocialNetwork(topology='homophily', influence_enabled=True)
            network.build_network(agents, k=5, seed=42)
            
            if use_realistic:
                influence_system = RealisticSocialInfluence(
                    decay_rate=decay_rate,
                    habit_weight=habit_weight,
                    experience_weight=0.4,
                    peer_weight=0.2
                )
                enhance_social_network_with_realism(network, influence_system)
                status.success("✅ Realistic influence enabled")
            else:
                status.success("✅ Deterministic influence enabled")
        
        progress.progress(50)
        
        # Run simulation
        status.info("🏃 Running simulation...")
        
        time_series = TimeSeriesStorage()
        adoption_history = defaultdict(list)
        cascade_events = []
        
        for step in range(steps):
            if influence_system:
                influence_system.advance_time()
            
            # Agent steps
            agent_states = []
            for agent in agents:
                # Pass environment to agent.step()
                try:
                    agent.step(env)  # Make sure 'env' is passed
                except Exception as e:
                    # Fallback without environment (agents won't move)
                    agent.step()
                    print(f"Warning: Agent {agent.state.agent_id} stepped without environment: {e}")

                # Social influence
                if network:
                    # Use the agent's actual BDI-computed costs
                    mode_costs = agent.state.mode_costs
                    if mode_costs:  # Only apply influence if agent has evaluated costs
                        adjusted = network.apply_social_influence(
                            agent.state.agent_id, mode_costs,
                            influence_strength=0.15,
                            conformity_pressure=0.15
                        )
                        best_mode = min(adjusted, key=adjusted.get)
                        agent.state.mode = best_mode
                    
                    # Track satisfaction
                    if influence_system and not agent.state.arrived:
                        satisfaction = calculate_satisfaction(
                            agent, env,
                            actual_time=agent.state.travel_time_min,
                            expected_time=10.0,
                            actual_cost=1.0,
                            expected_cost=1.0
                        )
                        influence_system.record_mode_usage(
                            agent.state.agent_id,
                            agent.state.mode,
                            satisfaction
                        )
                
                agent_states.append({
                    'agent_id': agent.state.agent_id,
                    'location': agent.state.location,
                    'mode': agent.state.mode,
                    'arrived': agent.state.arrived,
                    'route': agent.state.route,
                    'distance_km': agent.state.distance_km,
                    'emissions_g': agent.state.emissions_g,
                })
            
            # Track metrics
            if network:
                network.record_mode_snapshot()
            
            mode_counts = Counter(a.state.mode for a in agents)
            for mode in ['walk', 'bike', 'bus', 'car', 'ev']:
                adoption_history[mode].append(mode_counts.get(mode, 0) / len(agents))
            
            # Cascade detection
            if network:
                for mode in mode_counts.keys():
                    cascade, clusters = network.detect_cascade(mode, threshold=0.15)
                    if cascade:
                        cascade_events.append({
                            'step': step,
                            'mode': mode,
                            'size': max(len(c) for c in clusters) if clusters else 0
                        })
            
            metrics = {
                'arrivals': sum(1 for a in agents if a.state.arrived),
                'emissions': sum(a.state.emissions_g for a in agents),
                'distance': sum(a.state.distance_km for a in agents),
            }
            
            time_series.store_timestep(step, agent_states, None, metrics)
            
            if step % max(1, steps // 10) == 0:
                progress.progress(50 + int(45 * step / steps))
        
        progress.progress(100, "✅ Complete!")
        status.success(f"✅ Simulation complete: {len(cascade_events)} cascades detected")
        
        # Store results
        st.session_state.simulation_run = True
        st.session_state.time_series = time_series
        st.session_state.env = env
        st.session_state.agents = agents
        st.session_state.network = network
        st.session_state.influence_system = influence_system
        st.session_state.adoption_history = adoption_history
        st.session_state.cascade_events = cascade_events
        st.session_state.use_realistic_influence = use_realistic
        st.session_state.animation_controller = AnimationController(
            total_steps=steps, fps=5
        )
        
        return True
        
    except Exception as e:
        error_msg = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
        status.error("❌ Simulation failed")
        with st.expander("Error Details"):
            st.code(error_msg)
        return False
    finally:
        progress.empty()

if run_btn:
    run_simulation(steps, num_agents, place, use_osm, enable_social,
                   use_realistic, decay_rate, habit_weight)
    st.rerun()

# ============================================================================
# Main Visualization
# ============================================================================

if not st.session_state.simulation_run:
    st.info("👈 Configure parameters in the sidebar and click **Run Simulation**")
    
    # Quick start guide
    st.markdown("---")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 🎯 Quick Start")
        st.markdown("1. Keep default settings")
        st.markdown("2. Click **Run Simulation**")
        st.markdown("3. Wait ~30 seconds")
        st.markdown("4. Explore results in tabs below")
    
    with col2:
        st.markdown("### 🎨 Color Guide")
        for mode, color in MODE_COLORS_HEX.items():
            st.markdown(f"<span style='color:{color};font-size:20px'>●</span> {mode.capitalize()}", 
                       unsafe_allow_html=True)
    
    st.stop()

# Get data
time_series = st.session_state.time_series
anim = st.session_state.animation_controller
agents = st.session_state.agents
network = st.session_state.network
adoption_history = st.session_state.adoption_history

current_data = time_series.get_timestep(anim.current_step)
if not current_data:
    st.error("No data available")
    st.stop()

agent_states = current_data['agent_states']
metrics = current_data.get('metrics', {})

# ============================================================================
# Tabs
# ============================================================================

tab1, tab2, tab3, tab4 = st.tabs(["🗺️ Map", "📈 Mode Adoption", "🎯 Impact", "🌐 Network"])

# TAB 1: MAP
with tab1:
    st.subheader(f"Live View - Step {anim.current_step + 1}/{anim.total_steps}")
    
    # 🔬 DIAGNOSTIC SECTION - Add this
    with st.expander("🔬 DIAGNOSTIC: Data Inspection", expanded=False):
        st.markdown("### Agent States Raw Data")
        if agent_states:
            sample = agent_states[0]
            st.write("Sample agent_states[0]:", sample)
            st.write("Type of location:", type(sample.get('location')))
            st.write("Type of mode:", type(sample.get('mode')))
            
        st.markdown("### Color Lookup Test")
        test_modes = ['walk', 'bike', 'bus', 'car', 'ev']
        for mode in test_modes:
            color = MODE_COLORS_RGB.get(mode, [128, 128, 128])
            st.write(f"{mode}: {color} (type: {type(color)})")
            st.write(f"  → RGBA: {[int(color[0]), int(color[1]), int(color[2]), 255]}")
        
        st.markdown("### DataFrame Construction Test")
        # Test with minimal data
        test_data = []
        for state in agent_states[:3]:  # Just first 3 agents
            loc = state.get('location')
            if loc and len(loc) == 2:
                mode = state.get('mode', 'walk')
                color_rgb = MODE_COLORS_RGB.get(mode, [128, 128, 128])
                
                test_row = {
                    'lon': float(loc[0]),
                    'lat': float(loc[1]),
                    'color': [int(color_rgb[0]), int(color_rgb[1]), int(color_rgb[2]), 255],
                    'mode': mode,
                }
                test_data.append(test_row)
                st.write(f"Row for {mode}:", test_row)
        
        if test_data:
            test_df = pd.DataFrame(test_data)
            st.write("Test DataFrame:")
            st.write(test_df) # st.dataframe(test_df) / st.table(test_df) for static display
            st.write("DataFrame dtypes:")
            st.write(test_df.dtypes)
            st.write("Sample color column value:")
            st.write(test_df.iloc[0]['color'])
            st.write("Type of color column value:")
            st.write(type(test_df.iloc[0]['color']))
    
    # Continue with normal map rendering...
    layers = []
    
    # Agents layer with COLOR BY MODE
    if st.session_state.show_agents:
        agent_data = []
        for state in agent_states:
            loc = state.get('location')
            if loc and len(loc) == 2:
                mode = state.get('mode', 'walk')
                color_rgb = MODE_COLORS_RGB.get(mode, [128, 128, 128])
                
                # Split RGB into separate columns (avoids pandas Series issue)
                agent_data.append({
                    'lon': float(loc[0]),
                    'lat': float(loc[1]),
                    'r': int(color_rgb[0]),
                    'g': int(color_rgb[1]),
                    'b': int(color_rgb[2]),
                    'agent_id': state.get('agent_id', ''),
                    'mode': mode,
                    'arrived': state.get('arrived', False),
                })
        
        if agent_data:
            agent_df = pd.DataFrame(agent_data)
            agent_layer = pdk.Layer(
                'ScatterplotLayer',
                data=agent_df,
                get_position='[lon, lat]',
                get_fill_color='[r, g, b]',
                get_radius=10,
                radius_min_pixels=6,
                radius_max_pixels=15,
                pickable=True,
                opacity=0.8,
                stroked=True,
                filled=True,
                line_width_min_pixels=2,
                get_line_color=[255, 255, 255],
            )
            layers.append(agent_layer)
    
    # Routes layer with COLOR BY MODE
    if st.session_state.show_routes:
        route_data = []
        for state in agent_states:
            route = state.get('route')
            if route and len(route) >= 2:
                mode = state.get('mode', 'walk')
                path = [[float(pt[0]), float(pt[1])] for pt in route if len(pt) == 2]
                if len(path) >= 2:
                    color_rgb = MODE_COLORS_RGB.get(mode, [128, 128, 128])
                    route_data.append({
                        'path': path,
                        'r': int(color_rgb[0]),
                        'g': int(color_rgb[1]),
                        'b': int(color_rgb[2]),
                        'mode': mode,
                    })
        
        if route_data:
            route_df = pd.DataFrame(route_data)
            route_layer = pdk.Layer(
                'PathLayer',
                data=route_df,
                get_path='path',
                get_color='[r, g, b]',
                width_min_pixels=3,
                opacity=0.6,
            )
            layers.append(route_layer)
    
    # View state
    if agent_states:
        lons = [s['location'][0] for s in agent_states if s.get('location')]
        lats = [s['location'][1] for s in agent_states if s.get('location')]
        if lons and lats:
            center_lon = sum(lons) / len(lons)
            center_lat = sum(lats) / len(lats)
        else:
            center_lon, center_lat = -3.19, 55.95
    else:
        center_lon, center_lat = -3.19, 55.95
    
    view_state = pdk.ViewState(
        longitude=center_lon,
        latitude=center_lat,
        zoom=13,
        pitch=0,
        bearing=0
    )
    
    deck = pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        tooltip={
            'html': '<b>{agent_id}</b><br/>Mode: {mode}<br/>Arrived: {arrived}',
            'style': {'backgroundColor': 'rgba(0,0,0,0.8)', 'color': 'white'}
        },
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
    )
    
    st.pydeck_chart(deck, use_container_width=True)
    
    # Current stats
    st.markdown("---")
    col1, col2, col3, col4 = st.columns(4)
    
    mode_counts = Counter(s['mode'] for s in agent_states)
    arrivals = metrics.get('arrivals', 0)
    emissions = metrics.get('emissions', 0)
    
    col1.metric("Arrivals", f"{arrivals}/{len(agent_states)}")
    col2.metric("Most Popular Mode", mode_counts.most_common(1)[0][0].capitalize() if mode_counts else "N/A")
    col3.metric("Total Emissions", f"{emissions:.0f} g CO₂")
    col4.metric("Active Modes", len(mode_counts))
    
    # DEBUG: Show color distribution
    with st.expander("🎨 Debug: Agent Colors"):
        st.markdown("**Agents by mode (should be different colors):**")
        for mode, count in mode_counts.most_common():
            color_hex = MODE_COLORS_HEX.get(mode, '#808080')
            color_rgb = MODE_COLORS_RGB.get(mode, [128, 128, 128])
            st.markdown(
                f"<span style='color:{color_hex};font-size:24px'>●</span> "
                f"{mode.capitalize()}: {count} agents (RGB: {color_rgb})",
                unsafe_allow_html=True
            )
        
        # Show first 5 agents' actual data
        st.markdown("**First 5 agents in data:**")
        for i, state in enumerate(agent_states[:5]):
            mode = state.get('mode', 'unknown')
            color_hex = MODE_COLORS_HEX.get(mode, '#808080')
            st.markdown(
                f"<span style='color:{color_hex};font-size:20px'>●</span> "
                f"{state.get('agent_id')}: {mode}",
                unsafe_allow_html=True
            )

# TAB 2: MODE ADOPTION
with tab2:
    st.subheader("📈 How Transport Modes Are Being Adopted")
    
    st.markdown("""
    **What this shows:** The percentage of agents using each transport mode over time.
    
    - **Rising lines** = mode becoming more popular
    - **Falling lines** = people switching away
    - **Flat lines** = stable usage
    """)
    
    # Create adoption plot
    fig = go.Figure()
    
    for mode in ['walk', 'bike', 'bus', 'car', 'ev']:
        if mode in adoption_history and adoption_history[mode]:
            fig.add_trace(go.Scatter(
                x=list(range(len(adoption_history[mode]))),
                y=[v * 100 for v in adoption_history[mode]],  # Convert to percentage
                mode='lines',
                name=mode.capitalize(),
                line=dict(width=3, color=MODE_COLORS_HEX[mode])
            ))
    
    fig.add_vline(x=anim.current_step, line_dash="dash", line_color="red",
                 annotation_text="Now", annotation_position="top")
    
    fig.update_layout(
        xaxis_title="Time Step",
        yaxis_title="Adoption Rate (%)",
        hovermode='x unified',
        height=400,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    
    st.plotly_chart(fig, width='stretch')
    
    # Key insights
    st.markdown("---")
    st.markdown("### 🔍 Key Insights")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**Peak Adoption:**")
        for mode in ['walk', 'bike', 'bus', 'car', 'ev']:
            if mode in adoption_history and adoption_history[mode]:
                peak = max(adoption_history[mode]) * 100
                color = MODE_COLORS_HEX[mode]
                st.markdown(f"<span style='color:{color}'>●</span> {mode.capitalize()}: {peak:.1f}%", 
                           unsafe_allow_html=True)
    
    with col2:
        st.markdown("**Current Share:**")
        mode_counts = Counter(s['mode'] for s in agent_states)
        total = len(agent_states)
        for mode, count in mode_counts.most_common():
            pct = (count / total) * 100
            color = MODE_COLORS_HEX.get(mode, '#808080')
            st.markdown(f"<span style='color:{color}'>●</span> {mode.capitalize()}: {pct:.1f}%", 
                       unsafe_allow_html=True)
    
    # Social influence effect
    if st.session_state.use_realistic_influence:
        st.info("""
        ✅ **Realistic Influence Active:** You'll see modes rise and fall naturally as:
        - Peer influences decay over time
        - Agents form habits with modes they use repeatedly
        - Personal experience matters more than peer pressure
        """)
    elif network:
        st.warning("""
        ⚠️ **Deterministic Influence Active:** Modes will trend toward 80-100% adoption (unrealistic).
        Enable "Use Realistic Influence" to see more natural patterns.
        """)

# TAB 3: IMPACT
with tab3:
    st.subheader("🎯 Environmental & Efficiency Impact")
    
    st.markdown("""
    **What this shows:** The real-world impact of transport mode choices.
    
    - **Emissions** = CO₂ pollution (lower is better)
    - **Distance** = Total travel distance
    - **Efficiency** = Emissions per kilometer traveled
    """)
    
    # Get full time series
    all_metrics = []
    for step_idx in range(len(time_series)):
        data = time_series.get_timestep(step_idx)
        if data:
            all_metrics.append({
                'step': step_idx,
                'emissions': data['metrics'].get('emissions', 0),
                'distance': data['metrics'].get('distance', 0),
            })
    
    if all_metrics:
        metrics_df = pd.DataFrame(all_metrics)
        metrics_df['efficiency'] = metrics_df['emissions'] / metrics_df['distance'].replace(0, 1)
        
        # Emissions over time
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=metrics_df['step'],
            y=metrics_df['emissions'],
            mode='lines',
            name='Total Emissions',
            line=dict(color='#ef4444', width=3),
            fill='tozeroy',
            fillcolor='rgba(239, 68, 68, 0.2)'
        ))
        
        fig.add_vline(x=anim.current_step, line_dash="dash", line_color="red",
                     annotation_text="Now")
        
        fig.update_layout(
            title="Total CO₂ Emissions Over Time",
            xaxis_title="Time Step",
            yaxis_title="Emissions (g CO₂)",
            height=300
        )
        
        st.plotly_chart(fig, width='stretch')
        
        # Key metrics
        col1, col2, col3 = st.columns(3)
        
        current_emissions = metrics_df.iloc[-1]['emissions']
        peak_emissions = metrics_df['emissions'].max()
        avg_efficiency = metrics_df['efficiency'].mean()
        
        col1.metric("Current Emissions", f"{current_emissions:.0f} g CO₂")
        col2.metric("Peak Emissions", f"{peak_emissions:.0f} g CO₂")
        col3.metric("Avg Efficiency", f"{avg_efficiency:.1f} g/km")
        
        # Interpretation
        st.markdown("---")
        st.markdown("### 💡 What This Means")
        
        if current_emissions < peak_emissions * 0.8:
            st.success(f"""
            ✅ **Emissions are decreasing!** Current emissions are {((1 - current_emissions/peak_emissions)*100):.0f}% below peak.
            This suggests agents are shifting to lower-emission modes (walking, cycling, electric).
            """)
        elif current_emissions > peak_emissions * 0.9:
            st.warning("""
            ⚠️ **Emissions remain high.** Most agents are still using high-emission modes (cars, buses).
            Consider policy interventions to encourage walking, cycling, or electric vehicles.
            """)
        else:
            st.info("""
            ℹ️ **Emissions are moderate.** There's a mix of transport modes being used.
            """)

# TAB 4: NETWORK
with tab4:
    st.subheader("🌐 Social Network Analysis")
    
    if network:
        st.markdown("""
        **What this shows:** How agents are socially connected and influence each other's choices.
        
        - **Connections** = Social ties between agents
        - **Cascades** = When a mode choice spreads virally through the network
        - **Clustering** = How tightly grouped the network is
        """)
        
        # Network metrics
        net_metrics = network.get_network_metrics()
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Agents", net_metrics.total_agents)
        col2.metric("Connections", net_metrics.total_ties)
        col3.metric("Avg Connections", f"{net_metrics.avg_degree:.1f}")
        col4.metric("Clustering", f"{net_metrics.clustering_coefficient:.2f}")
        
        # Cascade events
        if st.session_state.cascade_events:
            st.markdown("---")
            st.markdown("### 🌊 Cascade Events (Viral Adoption)")
            
            st.markdown("""
            **Cascades** occur when many agents adopt the same mode due to peer influence.
            Large cascades indicate strong social influence effects.
            """)
            
            cascade_df = pd.DataFrame(st.session_state.cascade_events)
            
            if not cascade_df.empty:
                fig = px.scatter(
                    cascade_df,
                    x='step',
                    y='size',
                    color='mode',
                    color_discrete_map=MODE_COLORS_HEX,
                    title="Cascade Events Over Time",
                    labels={'step': 'Time Step', 'size': 'Cascade Size (agents)', 'mode': 'Mode'}
                )
                fig.update_traces(marker=dict(size=12))
                st.plotly_chart(fig, width='stretch')
                
                st.markdown(f"**Total cascades detected:** {len(cascade_df)}")
        else:
            st.info("No cascades detected yet. Cascades occur when mode choices spread rapidly through the network.")
        
        # Influence explanation
        st.markdown("---")
        st.markdown("### 🔬 Influence Dynamics")
        
        if st.session_state.use_realistic_influence and st.session_state.influence_system:
            influence_system = st.session_state.influence_system
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("**System Parameters:**")
                st.write(f"- Decay Rate: {influence_system.decay_rate:.0%} per step")
                st.write(f"- Habit Weight: {influence_system.habit_weight:.0%}")
                st.write(f"- Experience Weight: {influence_system.experience_weight:.0%}")
                st.write(f"- Peer Weight: {influence_system.peer_weight:.0%}")
            
            with col2:
                st.markdown("**What This Means:**")
                st.write("- 🔻 Influences fade over time")
                st.write("- 🔄 Repeated use builds habits")
                st.write("- 💭 Personal experience matters")
                st.write("- 👥 Peers have some influence")
            
            st.success("""
            ✅ **Realistic Mode:** This produces natural adoption patterns where modes rise and fall,
            similar to real-world behavior. Peak adoption typically reaches 30-50%.
            """)
        
        elif network:
            st.warning("""
            ⚠️ **Deterministic Mode:** Peer influences are permanent and don't decay.
            This typically leads to unrealistic 80-100% adoption of popular modes.
            
            **Recommendation:** Enable "Use Realistic Influence" in sidebar for more natural behavior.
            """)
    
    else:
        st.info("""
        Social networks are not enabled for this simulation.
        
        Enable "Social Networks" in the sidebar to see:
        - How agents influence each other's mode choices
        - Cascade effects (viral adoption)
        - Network topology effects
        """)

# ============================================================================
# Auto-advance animation
# ============================================================================

if st.session_state.simulation_run and st.session_state.animation_controller:
    anim = st.session_state.animation_controller
    
    if anim.is_playing:
        # FIX: Use time.sleep with shorter delay for smoother animation
        import time
        time.sleep(0.2)
        
        # Advance to next frame
        if anim.current_step < anim.total_steps - 1:
            anim.current_step += 1
        else:
            # Reached end
            if anim.loop:
                anim.current_step = 0
            else:
                anim.is_playing = False  # ✅ FIX: Set flag directly instead of calling pause()
        
        # Force immediate rerun
        st.rerun()

# ============================================================================
# Footer
# ============================================================================

st.markdown("---")

# Status indicator
if st.session_state.use_realistic_influence:
    st.success("✅ **Realistic Social Influence Active** - Natural adoption patterns with decay and habits")
elif network:
    st.info("📊 **Deterministic Influence Active** - Traditional social influence model")
else:
    st.info("🔷 **No Social Influence** - Agents decide independently")

st.caption("**RTD_SIM** - Real-Time Decarbonization Simulator | Agent-Based Transport Model")