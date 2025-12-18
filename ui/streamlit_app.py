#!/usr/bin/env python3
"""
RTD_SIM Unified Visualization - MERGED VERSION
Combines working auto-play from phase4_viz with color fixes and realistic influence

Key features:
- ✅ Working auto-play animation
- ✅ Story selection dropdowns
- ✅ Congestion toggle
- ✅ Color-coded agents by mode
- ✅ Realistic social influence
- ✅ Manual step controls
"""

from __future__ import annotations
import sys
from pathlib import Path
import random
import traceback
import time
from collections import Counter, defaultdict

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
    from agent.user_stories import UserStoryParser
    from agent.job_stories import JobStoryParser
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
    'walk': [34, 197, 94],
    'bike': [59, 130, 246],
    'bus': [245, 158, 11],
    'car': [239, 68, 68],
    'ev': [168, 85, 245],
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
        
        # Story selection
        st.markdown("---")
        st.markdown("### 📖 Story Selection")
        
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
        else:
            user_stories = []
            job_stories = []
        
        # Advanced features
        st.markdown("---")
        st.markdown("### 🔬 Advanced Features")
        
        use_congestion = st.checkbox("Enable Congestion", value=False,
                                     help="Track and visualize traffic congestion")
        
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
        
        st.markdown("---")
        run_btn = st.form_submit_button("🚀 Run Simulation", 
                                        type="primary", 
                                        use_container_width=True)
    
    # Animation controls (after simulation) - WORKING VERSION FROM OLD FILE
    if st.session_state.simulation_run and st.session_state.animation_controller:
        st.markdown("---")
        st.header("🎬 Animation Controls")
        
        anim = st.session_state.animation_controller
        
        # Manual step buttons
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            if st.button("⏮️", help="Reset", use_container_width=True, key='reset_btn'):
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
            if st.button("⏭️", help="End", use_container_width=True, key='end_btn'):
                anim.seek(anim.total_steps - 1)
                st.rerun()
        
        # Auto-play toggle - WORKING VERSION
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

# ============================================================================
# Simulation Execution
# ============================================================================

def run_simulation(steps, num_agents, place, use_osm, user_stories, job_stories,
                   use_congestion, enable_social, use_realistic, decay_rate, habit_weight):
    """Run complete simulation with progress tracking."""
    
    progress = st.progress(0, "Initializing...")
    status = st.empty()
    
    try:
        # Environment
        status.info("🗺️ Loading environment...")
        cache_dir = Path.home() / ".rtd_sim_cache" / "osm_graphs"
        env = SpatialEnvironment(step_minutes=1.0, cache_dir=cache_dir, 
                                use_congestion=use_congestion)
        
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
        
        if PHASE_4_AVAILABLE and user_stories and job_stories:
            agents = generate_balanced_population(
                num_agents=num_agents,
                user_story_ids=user_stories,
                job_story_ids=job_stories,
                origin_dest_generator=random_od,
                planner=planner,
                seed=42
            )
            status.success(f"✅ Created {len(agents)} story-driven agents")
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
            status.info("Using basic agents")
        
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
                try:
                    agent.step(env)
                except:
                    agent.step()
                
                # Social influence
                if network:
                    mode_costs = getattr(agent.state, 'mode_costs', {})
                    if mode_costs:
                        adjusted = network.apply_social_influence(
                            agent.state.agent_id, mode_costs,
                            influence_strength=0.15,
                            conformity_pressure=0.15
                        )
                        best_mode = min(adjusted, key=adjusted.get)
                        agent.state.mode = best_mode
                    
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
            
            congestion_heatmap = env.congestion_heatmap if use_congestion else None
            time_series.store_timestep(step, agent_states, congestion_heatmap, metrics)
            
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
    run_simulation(steps, num_agents, place, use_osm, user_stories, job_stories,
                   use_congestion, enable_social, use_realistic, decay_rate, habit_weight)
    st.rerun()

# ============================================================================
# Main Visualization
# ============================================================================

if not st.session_state.simulation_run:
    st.info("👈 Configure parameters in the sidebar and click **Run Simulation**")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 🎯 Quick Start")
        st.markdown("1. Select user & job stories")
        st.markdown("2. Click **Run Simulation**")
        st.markdown("3. Use animation controls")
        st.markdown("4. Explore results in tabs")
    
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
    
    layers = []
    
    # Agents layer - WORKING COLOR FIX
    if st.session_state.show_agents:
        agent_data = []
        for state in agent_states:
            loc = state.get('location')
            if loc and len(loc) == 2:
                mode = state.get('mode', 'walk')
                color_rgb = MODE_COLORS_RGB.get(mode, [128, 128, 128])
                
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
    
    # Routes layer
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
    col2.metric("Most Popular", mode_counts.most_common(1)[0][0].capitalize() if mode_counts else "N/A")
    col3.metric("Emissions", f"{emissions:.0f} g CO₂")
    col4.metric("Active Modes", len(mode_counts))

# TAB 2: MODE ADOPTION
with tab2:
    st.subheader("📈 Mode Adoption Over Time")
    
    fig = go.Figure()
    
    for mode in ['walk', 'bike', 'bus', 'car', 'ev']:
        if mode in adoption_history and adoption_history[mode]:
            fig.add_trace(go.Scatter(
                x=list(range(len(adoption_history[mode]))),
                y=[v * 100 for v in adoption_history[mode]],
                mode='lines',
                name=mode.capitalize(),
                line=dict(width=3, color=MODE_COLORS_HEX[mode])
            ))
    
    fig.add_vline(x=anim.current_step, line_dash="dash", line_color="red",
                 annotation_text="Now")
    
    fig.update_layout(
        xaxis_title="Time Step",
        yaxis_title="Adoption Rate (%)",
        hovermode='x unified',
        height=400,
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Statistics
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
        total = len(agent_states)
        for mode, count in mode_counts.most_common():
            pct = (count / total) * 100
            color = MODE_COLORS_HEX.get(mode, '#808080')
            st.markdown(f"<span style='color:{color}'>●</span> {mode.capitalize()}: {pct:.1f}%", 
                       unsafe_allow_html=True)

# TAB 3: IMPACT
with tab3:
    st.subheader("🎯 Environmental Impact")
    
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
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=metrics_df['step'],
            y=metrics_df['emissions'],
            mode='lines',
            fill='tozeroy',
            line=dict(color='#ef4444', width=3),
        ))
        
        fig.update_layout(
            title="Total CO₂ Emissions",
            xaxis_title="Time Step",
            yaxis_title="Emissions (g CO₂)",
        )
        
        st.plotly_chart(fig, use_container_width=True)

# TAB 4: NETWORK
with tab4:
    st.subheader("🌐 Social Network Analysis")
    
    if network:
        net_metrics = network.get_network_metrics()
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Connections", net_metrics.total_ties)
        col2.metric("Avg Degree", f"{net_metrics.avg_degree:.1f}")
        col3.metric("Clustering", f"{net_metrics.clustering_coefficient:.2f}")
        
        if st.session_state.cascade_events:
            st.markdown("### 🌊 Cascade Events")
            cascade_df = pd.DataFrame(st.session_state.cascade_events)
            
            if not cascade_df.empty:
                fig = px.scatter(
                    cascade_df,
                    x='step',
                    y='size',
                    color='mode',
                    color_discrete_map=MODE_COLORS_HEX,
                )
                st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Social network not enabled")

# ============================================================================
# Auto-advance animation - WORKING VERSION FROM OLD FILE
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

if st.session_state.use_realistic_influence:
    st.success("✅ **Realistic Social Influence Active** - Natural adoption patterns")
elif network:
    st.info("📊 **Deterministic Influence Active** - Traditional model")
else:
    st.info("📷 **No Social Influence** - Independent decisions")

st.caption("**RTD_SIM** - Real-Time Decarbonization Simulator | Phase 1-4.1")