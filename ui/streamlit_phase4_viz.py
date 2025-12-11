#!/usr/bin/env python3
"""
RTD_SIM Phase 3+4 - Story-Driven Agents + Social Networks Visualization

New features:
- Story-driven agent generation (Phase 3)
- Social network visualization (Phase 4)
- Peer influence tracking
- Cascade detection overlay
- Agent story explanations
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
from collections import Counter

from simulation.spatial_environment import SpatialEnvironment
from simulation.controller import SimulationController, SimulationConfig
from simulation.event_bus import EventBus

# Phase 3: Story-driven agents
from agent.story_driven_agent import (
    StoryDrivenAgent, 
    generate_balanced_population,
    generate_agents_from_stories
)
from agent.user_stories import UserStoryParser
from agent.job_stories import JobStoryParser
from agent.bdi_planner import BDIPlanner

# Phase 4: Social networks
from agent.social_network import SocialNetwork

# Visualization
from visualiser.data_adapters import (
    AgentDataAdapter, RouteDataAdapter, CongestionDataAdapter, TimeSeriesStorage
)
from visualiser.animation_controller import AnimationController, LayerManager
from visualiser.style_config import (
    MODE_COLORS, MODE_COLORS_HEX, AGENT_RADIUS_PIXELS, AGENT_OPACITY,
    ROUTE_WIDTH_PIXELS, ROUTE_OPACITY, ANIMATION_VIEW_STATE
)

# ============================================================================
# Page Configuration
# ============================================================================

st.set_page_config(
    page_title="RTD_SIM Phase 3+4 - Story Agents + Social Networks",
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
        'agents': None,
        'network': None,
        'animation_controller': None,
        'layer_manager': LayerManager(),
        'last_error': '',
        'debug_mode': False,
        'show_stories': True,
        'show_network': True,
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# ============================================================================
# Title and Header
# ============================================================================

st.title("🚀 RTD_SIM Phase 3+4 Visualization")
st.markdown("**Story-Driven Agents | Social Network Influence | Cascade Detection**")

# ============================================================================
# Sidebar - Configuration
# ============================================================================

with st.sidebar:
    st.header("⚙️ Simulation Setup")
    
    with st.form("sim_config"):
        # Basic parameters
        steps = st.number_input("Simulation Steps", 10, 200, 50, 10)
        num_agents = st.number_input("Number of Agents", 10, 200, 50, 10)
        step_minutes = st.number_input("Step Duration (min)", 0.1, 5.0, 1.0, 0.1)
        
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
        st.markdown("### 👥 Story-Driven Agents (Phase 3)")
        
        # Load available stories
        try:
            user_parser = UserStoryParser()
            job_parser = JobStoryParser()
            available_users = user_parser.list_available_stories()
            available_jobs = job_parser.list_available_stories()
            
            user_stories = st.multiselect(
                "User Stories",
                available_users,
                default=available_users[:3] if len(available_users) >= 3 else available_users
            )
            
            job_stories = st.multiselect(
                "Job Stories", 
                available_jobs,
                default=available_jobs[:3] if len(available_jobs) >= 3 else available_jobs
            )
        except:
            st.warning("Stories not found - using basic agents")
            user_stories = []
            job_stories = []
        
        st.markdown("---")
        st.markdown("### 🕸️ Social Network (Phase 4)")
        
        enable_network = st.checkbox("Enable Social Network", value=True)
        
        if enable_network:
            network_topology = st.selectbox(
                "Network Topology",
                ["homophily", "small_world", "scale_free", "random"]
            )
            
            network_k = st.slider(
                "Average Connections",
                2, 10, 5,
                help="Average number of social connections per agent"
            )
            
            influence_strength = st.slider(
                "Peer Influence Strength",
                0.0, 0.5, 0.2, 0.05,
                help="How much peers affect mode choice"
            )
        else:
            network_topology = "small_world"
            network_k = 4
            influence_strength = 0.0
        
        st.markdown("---")
        st.markdown("### 🚦 Other Features")
        
        use_congestion = st.checkbox("Enable Congestion", value=False)
        
        st.markdown("---")
        run_button = st.form_submit_button("🚀 Run Simulation", type="primary", use_container_width=True)
    
    # Animation controls (after simulation runs)
    if st.session_state.simulation_run and st.session_state.animation_controller:
        st.markdown("---")
        st.header("🎬 Animation Controls")
        
        anim = st.session_state.animation_controller
        
        # Play/pause button row
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
        
        # Auto-play
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
            "Timestep",
            0, anim.total_steps - 1,
            anim.current_step,
            key='time_slider'
        )
        
        if current_step != anim.current_step:
            anim.seek(current_step)
        
        st.markdown("---")
        progress = anim.get_progress()
        st.progress(progress, text=f"Step {anim.current_step + 1}/{anim.total_steps}")
        
        st.markdown("---")
        st.header("👁️ Layer Visibility")
        
        layer_mgr = st.session_state.layer_manager
        
        for layer_name in ['agents', 'routes', 'network']:
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

def run_simulation(steps, num_agents, place, use_osm, network_type, use_cache, 
                   step_minutes, use_congestion, user_stories, job_stories,
                   enable_network, network_topology, network_k, influence_strength):
    """Execute simulation with story-driven agents and social network."""
    
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
        status.info("🤖 Creating story-driven agents...")
        planner = BDIPlanner()
        
        # Origin-destination generator
        def random_od_generator():
            if use_osm and env.graph_loaded:
                pair = env.get_random_origin_dest()
                return pair if pair else ((-3.19, 55.95), (-3.15, 55.97))
            else:
                return (
                    (random.uniform(-3.3, -3.15), random.uniform(55.9, 55.97)),
                    (random.uniform(-3.3, -3.15), random.uniform(55.9, 55.97))
                )
        
        # Generate agents
        if user_stories and job_stories:
            # Story-driven generation
            agents = generate_balanced_population(
                num_agents=num_agents,
                user_story_ids=user_stories,
                job_story_ids=job_stories,
                origin_dest_generator=random_od_generator,
                planner=planner,
                seed=42
            )
            status.success(f"✅ Generated {len(agents)} story-driven agents")
        else:
            # Fallback to basic agents
            from agent.cognitive_abm import CognitiveAgent
            agents = []
            for i in range(num_agents):
                origin, dest = random_od_generator()
                agents.append(CognitiveAgent(
                    seed=42 + i,
                    agent_id=f"agent_{i+1}",
                    desires={'eco': 0.5, 'time': 0.5, 'cost': 0.5},
                    planner=planner,
                    origin=origin,
                    dest=dest
                ))
            status.info("Using basic agents (stories not available)")
        
        progress_bar.progress(40)
        
        # Build social network
        network = None
        if enable_network:
            status.info("🕸️ Building social network...")
            network = SocialNetwork(
                topology=network_topology,
                influence_enabled=True
            )
            network.build_network(agents, k=network_k, seed=42)
            
            net_metrics = network.get_network_metrics()
            status.success(f"✅ Network: {net_metrics.total_ties} connections, "
                         f"avg degree={net_metrics.avg_degree:.1f}")
        
        progress_bar.progress(50)
        
        # Setup simulation
        status.info("⚙️ Running simulation...")
        bus = EventBus()
        config = SimulationConfig(steps=steps)
        controller = SimulationController(
            bus, model=None, data_adapter=None,
            config=config, agents=agents, environment=env
        )
        
        time_series = TimeSeriesStorage()
        controller.start()
        
        # Run simulation
        for step in range(steps):
            # Apply social influence before agent steps
            if network and influence_strength > 0:
                for agent in agents:
                    if not agent.state.arrived:
                        # Simple influence application
                        peer_modes = network.get_peer_mode_share(agent.state.agent_id)
                        # Influence would be applied in planner - simplified here
            
            # Agent steps
            controller.step()
            
            # Store states
            agent_states = []
            for agent in agents:
                state_dict = {
                    'agent_id': agent.state.agent_id,
                    'location': agent.state.location,
                    'mode': agent.state.mode,
                    'arrived': agent.state.arrived,
                    'route': agent.state.route,
                    'distance_km': agent.state.distance_km,
                    'emissions_g': agent.state.emissions_g,
                    'travel_time_min': agent.state.travel_time_min,
                }
                
                # Add story info if available
                if hasattr(agent, 'user_story_id'):
                    state_dict['user_story'] = agent.user_story_id
                    state_dict['job_story'] = agent.job_story_id
                
                agent_states.append(state_dict)
            
            # Record network snapshot
            if network:
                network.record_mode_snapshot()
            
            metrics = {
                'arrivals': sum(1 for a in agents if a.state.arrived),
                'total_emissions': sum(a.state.emissions_g for a in agents),
                'total_distance': sum(a.state.distance_km for a in agents),
            }
            
            time_series.store_timestep(step, agent_states, None, metrics)
            
            if step % max(1, steps // 10) == 0:
                progress_pct = 50 + int((step / steps) * 45)
                progress_bar.progress(progress_pct, f"Step {step}/{steps}")
        
        controller.stop()
        
        # Finalize
        progress_bar.progress(100, "✅ Complete!")
        status.success(f"✅ Simulation complete: {steps} steps, {len(agents)} agents")
        
        # Store in session state
        st.session_state.simulation_run = True
        st.session_state.time_series = time_series
        st.session_state.env = env
        st.session_state.agents = agents
        st.session_state.network = network
        st.session_state.animation_controller = AnimationController(
            total_steps=steps,
            fps=5
        )
        st.session_state.last_error = ''
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
        steps, num_agents, place, use_osm, network_type, use_cache,
        step_minutes, use_congestion, user_stories, job_stories,
        enable_network, network_topology, network_k, influence_strength
    )
    st.rerun()

# ============================================================================
# Main Visualization Area
# ============================================================================

if not st.session_state.simulation_run:
    st.info("👈 Configure simulation and click 'Run Simulation'")
    st.markdown("---")
    st.markdown("### 🎯 What's New in Phase 3+4")
    st.markdown("✅ **Story-Driven Agents**: Generate agents from user + job stories")
    st.markdown("✅ **Social Networks**: Agents influence each other's mode choices")
    st.markdown("✅ **Cascade Detection**: Identify viral adoption patterns")
    st.markdown("✅ **Explainability**: Agents explain their decisions")
    st.stop()

# Get data
time_series = st.session_state.time_series
anim = st.session_state.animation_controller
layer_mgr = st.session_state.layer_manager
env = st.session_state.env
agents = st.session_state.agents
network = st.session_state.network

current_data = time_series.get_timestep(anim.current_step)

if not current_data:
    st.error("No data available")
    st.stop()

agent_states = current_data['agent_states']
metrics = current_data.get('metrics', {})

# ============================================================================
# Map Visualization
# ============================================================================

st.subheader(f"🗺️ Simulation - Step {anim.current_step + 1}/{anim.total_steps}")

map_style = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"

layers = []

# Agent layer
if layer_mgr.is_visible('agents'):
    agent_df = AgentDataAdapter.agents_to_dataframe(agent_states, anim.current_step)
    
    if not agent_df.empty:
        agent_layer = pdk.Layer(
            'ScatterplotLayer',
            data=agent_df,
            get_position='[lon, lat]',
            get_color='color',
            get_radius=AGENT_RADIUS_PIXELS,
            radius_scale=1,
            radius_min_pixels=8,
            radius_max_pixels=20,
            pickable=True,
            opacity=AGENT_OPACITY,
            stroked=True,
            filled=True,
            line_width_min_pixels=2,
            get_line_color=[255, 255, 255],
        )
        layers.append(agent_layer)

# Routes layer
if layer_mgr.is_visible('routes'):
    route_df = RouteDataAdapter.routes_to_dataframe(agent_states)
    if not route_df.empty:
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

# Network connections layer
if layer_mgr.is_visible('network') and network:
    # Create network edges for visualization
    network_edges = []
    for u, v in network.G.edges():
        agent_u = network._agent_registry.get(u)
        agent_v = network._agent_registry.get(v)
        
        if agent_u and agent_v:
            loc_u = agent_u.state.location
            loc_v = agent_v.state.location
            
            if loc_u and loc_v:
                strength = network.G[u][v].get('strength', 0.5)
                network_edges.append({
                    'path': [list(loc_u), list(loc_v)],
                    'strength': strength,
                    'color': [100, 100, 100, int(strength * 100)]
                })
    
    if network_edges:
        network_df = pd.DataFrame(network_edges)
        network_layer = pdk.Layer(
            'PathLayer',
            data=network_df,
            get_path='path',
            get_color='color',
            width_scale=1,
            width_min_pixels=1,
            opacity=0.3,
        )
        layers.append(network_layer)

# View state
view_state = ANIMATION_VIEW_STATE.copy()
if agent_states:
    lons = [s['location'][0] for s in agent_states if s.get('location')]
    lats = [s['location'][1] for s in agent_states if s.get('location')]
    if lons and lats:
        view_state['longitude'] = sum(lons) / len(lons)
        view_state['latitude'] = sum(lats) / len(lats)

deck = pdk.Deck(
    layers=layers,
    initial_view_state=pdk.ViewState(**view_state),
    tooltip={
        'html': '<b>Agent:</b> {agent_id}<br/><b>Mode:</b> {mode}<br/><b>Story:</b> {user_story}',
        'style': {
            'backgroundColor': 'rgba(0, 0, 0, 0.8)',
            'color': 'white',
        }
    },
    map_style=map_style,
)

st.pydeck_chart(deck, width='stretch')

# ============================================================================
# Metrics Dashboard
# ============================================================================

st.markdown("---")

# Create tabs for different views
tab1, tab2, tab3, tab4 = st.tabs(["📊 Metrics", "📖 Stories", "🕸️ Network", "🌊 Cascades"])

with tab1:
    st.subheader("Current Metrics")
    
    col1, col2, col3, col4 = st.columns(4)
    
    arrivals = metrics.get('arrivals', 0)
    total_agents = len(agent_states)
    emissions = metrics.get('total_emissions', 0)
    distance = metrics.get('total_distance', 0)
    
    col1.metric("Arrivals", f"{arrivals}/{total_agents}")
    col2.metric("Total Emissions", f"{emissions:.1f} g")
    col3.metric("Total Distance", f"{distance:.2f} km")
    
    modes = [s['mode'] for s in agent_states]
    mode_counts = Counter(modes)
    col4.metric("Active Modes", len(mode_counts))
    
    # Mode distribution chart
    if mode_counts:
        mode_df = pd.DataFrame([
            {'Mode': mode, 'Count': count}
            for mode, count in mode_counts.most_common()
        ])
        fig = px.bar(mode_df, x='Mode', y='Count', title='Mode Distribution')
        st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("Story Distribution")
    
    if agents and hasattr(agents[0], 'user_story_id'):
        user_dist = Counter(a.user_story_id for a in agents)
        job_dist = Counter(a.job_story_id for a in agents)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**User Stories**")
            for story, count in user_dist.most_common():
                st.write(f"{story}: {count}")
        
        with col2:
            st.markdown("**Job Stories**")
            for story, count in job_dist.most_common():
                st.write(f"{story}: {count}")
        
        # Sample agent explanation
        if agents:
            st.markdown("---")
            st.markdown("**Sample Agent Explanation**")
            sample_agent = agents[0]
            if hasattr(sample_agent, 'explain_decision'):
                explanation = sample_agent.explain_decision(sample_agent.state.mode)
                st.info(explanation)
    else:
        st.info("Story information not available (using basic agents)")

with tab3:
    st.subheader("Social Network Analysis")
    
    if network:
        net_metrics = network.get_network_metrics()
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Connections", net_metrics.total_ties)
        col2.metric("Avg Degree", f"{net_metrics.avg_degree:.1f}")
        col3.metric("Clustering", f"{net_metrics.clustering_coefficient:.3f}")
        
        st.markdown("**Mode Distribution in Network**")
        if net_metrics.mode_distribution:
            mode_net_df = pd.DataFrame([
                {'Mode': mode, 'Share': share}
                for mode, share in net_metrics.mode_distribution.items()
            ])
            fig = px.pie(mode_net_df, values='Share', names='Mode', title='Network Mode Share')
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Social network not enabled")

with tab4:
    st.subheader("Cascade Detection")
    
    if network:
        # Check for cascades
        cascade_found = False
        for mode in ['bike', 'car', 'bus', 'walk']:
            cascade, clusters = network.detect_cascade(mode, threshold=0.15, min_cluster_size=5)
            if cascade:
                cascade_found = True
                st.success(f"🌊 **{mode.upper()} CASCADE DETECTED!**")
                st.write(f"   - Number of clusters: {len(clusters)}")
                st.write(f"   - Largest cluster: {max(len(c) for c in clusters)} agents")
        
        if not cascade_found:
            st.info("No cascades detected yet")
        
        # Tipping point check
        st.markdown("---")
        st.markdown("**Tipping Point Analysis**")
        for mode in ['bike', 'car', 'bus']:
            tipping = network.detect_tipping_point(mode, history_window=10)
            if tipping:
                st.warning(f"⚡ {mode.upper()} adoption accelerating (tipping point!)")
    else:
        st.info("Social network not enabled")

# ============================================================================
# Auto-advance
# ============================================================================

if anim.is_playing:
    time.sleep(0.3 / anim.speed_multiplier)
    if anim.current_step < anim.total_steps - 1:
        anim.current_step += 1
        st.rerun()
    else:
        anim.pause()
        st.rerun()

st.markdown("---")
st.caption("**RTD_SIM Phase 3+4** | Story-Driven Agents + Social Networks")