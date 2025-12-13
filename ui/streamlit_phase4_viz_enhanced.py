#!/usr/bin/env python3
"""
RTD_SIM Phase 4.1 - Enhanced Visualization with Realistic Social Influence

Features:
- Toggle between Deterministic and Realistic influence
- Real-time influence metrics display
- Habit formation visualization
- Adoption curve comparison
- Social network overlay
- Agent influence state inspection
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
from plotly.subplots import make_subplots

from simulation.spatial_environment import SpatialEnvironment
from simulation.controller import SimulationController, SimulationConfig
from simulation.event_bus import EventBus
from agent.cognitive_abm import CognitiveAgent
from agent.bdi_planner import BDIPlanner

# Phase 3+4 imports
from agent.story_driven_agent import generate_balanced_population
from agent.social_network import SocialNetwork

# Phase 4.1 imports
from agent.social_influence_dynamics import (
    RealisticSocialInfluence,
    enhance_social_network_with_realism,
    calculate_satisfaction
)

# Visualization modules
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
    page_title="RTD_SIM Phase 4.1 - Realistic Social Influence",
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
        # Phase 4.1 specific
        'network': None,
        'influence_system': None,
        'agents': None,
        'adoption_history': defaultdict(list),
        'cascade_events': [],
        'use_realistic_influence': True,
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# ============================================================================
# Title and Header
# ============================================================================

st.title("🚀 RTD_SIM Phase 4.1 - Realistic Social Influence")

col1, col2 = st.columns([3, 1])
with col1:
    st.markdown("**Story-driven agents + Social networks + Realistic influence dynamics**")
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
        steps = st.number_input("Simulation Steps", 10, 500, 100, 10)
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
        st.markdown("### 🔬 Phase 4.1: Realistic Influence")
        
        use_realistic = st.checkbox(
            "Enable Realistic Influence",
            value=True,
            help="Toggle between deterministic and realistic social influence"
        )
        
        if use_realistic:
            st.markdown("**Influence Parameters:**")
            decay_rate = st.slider("Decay Rate", 0.05, 0.30, 0.15, 0.05,
                                  help="How fast peer influence fades (per step)")
            habit_weight = st.slider("Habit Weight", 0.0, 0.6, 0.4, 0.1,
                                    help="Importance of habit formation")
            experience_weight = st.slider("Experience Weight", 0.0, 0.6, 0.4, 0.1,
                                         help="Importance of personal experience")
            peer_weight = st.slider("Peer Weight", 0.0, 0.6, 0.2, 0.1,
                                   help="Importance of peer influence")
        else:
            decay_rate = 0.0
            habit_weight = 0.0
            experience_weight = 0.0
            peer_weight = 1.0
        
        st.markdown("---")
        st.markdown("### 👥 Agent Population")
        
        user_stories = st.multiselect(
            "User Stories",
            ['eco_warrior', 'budget_student', 'business_commuter', 
             'concerned_parent', 'freight_operator', 'rural_resident'],
            default=['eco_warrior', 'budget_student', 'business_commuter']
        )
        
        job_stories = st.multiselect(
            "Job Contexts",
            ['morning_commute', 'school_run_then_work', 'flexible_leisure',
             'shopping_trip', 'freight_delivery_route'],
            default=['morning_commute', 'flexible_leisure']
        )
        
        st.markdown("---")
        st.markdown("### 🌐 Social Network")
        
        network_topology = st.selectbox(
            "Network Topology",
            ["homophily", "small_world", "scale_free", "random"],
            help="How agents are socially connected"
        )
        
        avg_degree = st.slider("Avg Connections", 2, 10, 5, 1,
                              help="Average number of social connections per agent")
        
        st.markdown("---")
        run_button = st.form_submit_button("🚀 Run Simulation", type="primary", 
                                          use_container_width=True)
    
    # Animation controls (after simulation runs)
    if st.session_state.simulation_run and st.session_state.animation_controller:
        st.markdown("---")
        st.header("🎬 Animation Controls")
        
        anim = st.session_state.animation_controller
        
        # Play/pause button row
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            if st.button("⮐️", help="Reset", use_container_width=True, key='reset_btn'):
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
            if st.button("⭐️", help="End", use_container_width=True, key='end_btn'):
                anim.seek(anim.total_steps - 1)
                st.rerun()
        
        # Auto-play toggle
        st.markdown("---")
        col_play, col_loop = st.columns(2)
        with col_play:
            auto_play = st.checkbox(
                "▶️ Auto-Play",
                value=anim.is_playing,
                key='auto_play_toggle'
            )
            if auto_play != anim.is_playing:
                if auto_play:
                    anim.play()
                else:
                    anim.pause()
                st.rerun()
        
        with col_loop:
            loop = st.checkbox("🔁 Loop", value=anim.loop, key='loop_toggle')
            if loop != anim.loop:
                anim.set_loop(loop)
        
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
            "⚡ Speed",
            options=[0.25, 0.5, 1.0, 2.0, 4.0],
            value=anim.speed_multiplier,
            format_func=lambda x: f"{x}x",
            key='speed_slider'
        )
        if speed != anim.speed_multiplier:
            anim.set_speed(speed)
        
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

def run_simulation(steps, num_agents, place, use_osm, network_type, 
                   use_cache, step_minutes, use_realistic,
                   decay_rate, habit_weight, experience_weight, peer_weight,
                   user_stories, job_stories, network_topology, avg_degree):
    """Execute Phase 4.1 simulation with realistic influence."""
    
    progress_bar = st.progress(0, "Initializing...")
    status = st.empty()
    
    try:
        # Initialize environment
        status.info("🗺️ Loading environment...")
        cache_dir = Path.home() / ".rtd_sim_cache" / "osm_graphs"
        env = SpatialEnvironment(
            step_minutes=step_minutes,
            cache_dir=cache_dir,
            use_congestion=False
        )
        
        if use_osm:
            env.load_osm_graph(
                place=place or None,
                network_type=network_type,
                use_cache=use_cache
            )
            stats = env.get_graph_stats()
            status.success(f"✅ Loaded: {stats['nodes']:,} nodes, {stats['edges']:,} edges")
        
        progress_bar.progress(15)
        
        # Create agents with stories
        status.info("🤖 Creating story-driven agents...")
        planner = BDIPlanner()
        
        def random_od_generator():
            if use_osm and env.graph_loaded:
                pair = env.get_random_origin_dest()
                return pair if pair else ((-3.19, 55.95), (-3.15, 55.97))
            else:
                return (
                    (-3.25 + random.random()*0.1, 55.93 + random.random()*0.05),
                    (-3.15 + random.random()*0.1, 55.97 + random.random()*0.05)
                )
        
        agents = generate_balanced_population(
            num_agents=num_agents,
            user_story_ids=user_stories,
            job_story_ids=job_stories,
            origin_dest_generator=random_od_generator,
            planner=planner,
            seed=42
        )
        
        status.success(f"✅ Generated {len(agents)} story-driven agents")
        progress_bar.progress(30)
        
        # Build social network
        status.info("🌐 Building social network...")
        network = SocialNetwork(
            topology=network_topology,
            influence_enabled=True
        )
        
        network.build_network(agents, k=avg_degree, seed=42)
        
        metrics = network.get_network_metrics()
        status.success(
            f"✅ Network: {metrics.total_agents} agents, "
            f"{metrics.total_ties} connections, "
            f"clustering={metrics.clustering_coefficient:.3f}"
        )
        progress_bar.progress(45)
        
        # Add realistic influence if enabled
        influence_system = None
        if use_realistic:
            status.info("🔬 Enabling realistic social influence...")
            influence_system = RealisticSocialInfluence(
                decay_rate=decay_rate,
                habit_weight=habit_weight,
                experience_weight=experience_weight,
                peer_weight=peer_weight
            )
            enhance_social_network_with_realism(network, influence_system)
            status.success("✅ Realistic influence enabled")
        else:
            status.info("📊 Using deterministic influence")
        
        progress_bar.progress(50)
        
        # Run simulation with tracking
        status.info("🏃 Running simulation...")
        
        time_series = TimeSeriesStorage()
        adoption_history = defaultdict(list)
        cascade_events = []
        
        for step in range(steps):
            # Advance time for decay
            if influence_system:
                influence_system.advance_time()
            
            # Each agent takes a step
            agent_states = []
            for agent in agents:
                try:
                    state = agent.step(env)
                except:
                    state = agent.step()
                
                # Apply social influence
                if network.influence_enabled:
                    mode_costs = {
                        'walk': 1.0,
                        'bike': 0.9,
                        'bus': 0.8,
                        'car': 1.2,
                        'ev': 1.0
                    }
                    
                    adjusted_costs = network.apply_social_influence(
                        agent.state.agent_id,
                        mode_costs
                    )
                    
                    # Choose best mode
                    best_mode = min(adjusted_costs, key=adjusted_costs.get)
                    agent.state.mode = best_mode
                
                # Record satisfaction for realistic influence
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
                
                # Store state
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
            
            # Record mode snapshot
            network.record_mode_snapshot()
            
            # Track adoption rates
            mode_counts = Counter(a.state.mode for a in agents)
            for mode in ['bike', 'bus', 'car', 'walk', 'ev']:
                adoption_history[mode].append(mode_counts.get(mode, 0) / len(agents))
            
            # Check for cascades
            for mode in mode_counts.keys():
                cascade, clusters = network.detect_cascade(mode, threshold=0.15, min_cluster_size=5)
                if cascade:
                    cascade_events.append({
                        'step': step,
                        'mode': mode,
                        'clusters': len(clusters),
                        'largest_cluster': max(len(c) for c in clusters) if clusters else 0
                    })
            
            # Calculate metrics
            metrics = {
                'arrivals': sum(1 for a in agents if a.state.arrived),
                'total_emissions': sum(a.state.emissions_g for a in agents),
                'total_distance': sum(a.state.distance_km for a in agents),
            }
            
            # Store timestep
            time_series.store_timestep(step, agent_states, None, metrics)
            
            # Update progress
            if step % max(1, steps // 10) == 0:
                progress_pct = 50 + int((step / steps) * 45)
                progress_bar.progress(progress_pct, f"Step {step}/{steps}")
        
        # Finalize
        progress_bar.progress(100, "✅ Complete!")
        status.success(
            f"✅ Simulation complete: {steps} steps, "
            f"{len(cascade_events)} cascades detected"
        )
        
        # Store in session state
        st.session_state.simulation_run = True
        st.session_state.time_series = time_series
        st.session_state.env = env
        st.session_state.network = network
        st.session_state.influence_system = influence_system
        st.session_state.agents = agents
        st.session_state.adoption_history = adoption_history
        st.session_state.cascade_events = cascade_events
        st.session_state.use_realistic_influence = use_realistic
        st.session_state.animation_controller = AnimationController(
            total_steps=steps,
            fps=5
        )
        st.session_state.last_error = ''
        
        # Auto-enable layers
        st.session_state.layer_manager.set_visible('agents', True)
        st.session_state.layer_manager.set_visible('routes', False)
        
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
        use_cache, step_minutes, use_realistic,
        decay_rate, habit_weight, experience_weight, peer_weight,
        user_stories, job_stories, network_topology, avg_degree
    )
    st.rerun()

# ============================================================================
# Main Visualization Area
# ============================================================================

if not st.session_state.simulation_run:
    st.info("👈 Configure simulation parameters and click 'Run Simulation' to begin")
    st.markdown("---")
    st.markdown("### 🎯 Phase 4.1 Quick Start")
    st.markdown("1. **Enable Realistic Influence** (default: ON)")
    st.markdown("2. Keep default settings (50 agents, 100 steps)")
    st.markdown("3. Click 'Run Simulation'")
    st.markdown("4. Observe adoption curves and volatility")
    st.markdown("5. Compare with deterministic mode (turn OFF realistic influence)")
    st.stop()

# Get current data
time_series = st.session_state.time_series
anim = st.session_state.animation_controller
layer_mgr = st.session_state.layer_manager
env = st.session_state.env
network = st.session_state.network
influence_system = st.session_state.influence_system
agents = st.session_state.agents
adoption_history = st.session_state.adoption_history

current_data = time_series.get_timestep(anim.current_step)

if not current_data:
    st.error("No data available for current timestep")
    st.stop()

agent_states = current_data['agent_states']
metrics = current_data.get('metrics', {})

# ============================================================================
# Tab Layout
# ============================================================================

tab1, tab2, tab3, tab4 = st.tabs([
    "🗺️ Map Visualization", 
    "📊 Adoption Curves", 
    "🔬 Influence Dynamics",
    "🌐 Network Analysis"
])

# ============================================================================
# TAB 1: Map Visualization
# ============================================================================

with tab1:
    st.subheader(f"🗺️ Live Simulation - Step {anim.current_step + 1}/{anim.total_steps}")
    
    # Map style selector
    map_style_options = {
        "Light": "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        "Dark": "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
        "Voyager": "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json",
    }
    
    selected_style = st.selectbox("Map Style", list(map_style_options.keys()), index=0)
    map_style = map_style_options[selected_style]
    
    # Prepare layers
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
    
    # Calculate view state
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
            'style': {'backgroundColor': 'rgba(0, 0, 0, 0.8)', 'color': 'white'}
        },
        map_style=map_style,
    )
    
    st.pydeck_chart(deck, width='stretch')
    
    # Current metrics
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
    mode_counts = Counter(modes)
    col4.metric("Active Modes", len(mode_counts))

# ============================================================================
# TAB 2: Adoption Curves
# ============================================================================

with tab2:
    st.subheader("📈 Mode Adoption Over Time")
    
    # Create adoption plot
    fig = go.Figure()
    
    for mode in ['bike', 'bus', 'car', 'walk', 'ev']:
        if mode in adoption_history and adoption_history[mode]:
            fig.add_trace(go.Scatter(
                x=list(range(len(adoption_history[mode]))),
                y=adoption_history[mode],
                mode='lines',
                name=mode.capitalize(),
                line=dict(width=2)
            ))
    
    # Add current timestep marker
    fig.add_vline(
        x=anim.current_step,
        line_dash="dash",
        line_color="red",
        annotation_text="Current"
    )
    
    fig.update_layout(
        xaxis_title="Time Step",
        yaxis_title="Adoption Rate",
        yaxis=dict(tickformat='.0%'),
        hovermode='x unified',
        height=500
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Statistics
    st.markdown("---")
    st.subheader("📊 Adoption Statistics")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**Peak Adoption Rates:**")
        for mode in ['bike', 'bus', 'car', 'walk', 'ev']:
            if mode in adoption_history and adoption_history[mode]:
                peak = max(adoption_history[mode])
                st.metric(f"{mode.capitalize()}", f"{peak:.1%}")
    
    with col2:
        st.markdown("**Volatility (Std Dev):**")
        for mode in ['bike', 'bus', 'car', 'walk', 'ev']:
            if mode in adoption_history and len(adoption_history[mode]) > 1:
                volatility = statistics.stdev(adoption_history[mode])
                st.metric(f"{mode.capitalize()}", f"{volatility:.3f}")
    
    # Cascade events
    if st.session_state.cascade_events:
        st.markdown("---")
        st.subheader("🌊 Cascade Events Detected")
        
        cascade_df = pd.DataFrame(st.session_state.cascade_events)
        st.dataframe(cascade_df, use_container_width=True)

# ============================================================================
# TAB 3: Influence Dynamics
# ============================================================================

with tab3:
    if st.session_state.use_realistic_influence and influence_system:
        st.subheader("🔬 Realistic Influence Dynamics")
        
        # Show influence parameters
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**System Parameters:**")
            st.metric("Decay Rate", f"{influence_system.decay_rate:.2%}")
            st.metric("Habit Weight", f"{influence_system.habit_weight:.2%}")
        
        with col2:
            st.markdown("** **")
            st.metric("Experience Weight", f"{influence_system.experience_weight:.2%}")
            st.metric("Peer Weight", f"{influence_system.peer_weight:.2%}")
        
        # Agent state inspection
        st.markdown("---")
        st.subheader("👤 Agent Influence States")
        
        # Select agent to inspect
        agent_ids = [a.state.agent_id for a in agents]
        selected_agent_id = st.selectbox("Select Agent", agent_ids)
        
        if selected_agent_id:
            state_summary = influence_system.get_agent_state_summary(selected_agent_id)
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown(f"**Agent: {selected_agent_id}**")
                st.metric("Influence Memories", state_summary['influence_memories'])
                st.metric("Current Time", state_summary['current_time'])
            
            with col2:
                st.markdown("**Habit States:**")
                if state_summary['habits']:
                    for mode, habit_info in state_summary['habits'].items():
                        st.markdown(f"**{mode.capitalize()}:**")
                        st.write(f"  - Strength: {habit_info['strength']:.2%}")
                        st.write(f"  - Consecutive uses: {habit_info['consecutive_uses']}")
                        st.write(f"  - Satisfaction: {habit_info['satisfaction']:.2%}")
                else:
                    st.info("No habits formed yet")
        
        # Behavior explanation
        st.markdown("---")
        st.subheader("💡 Behavior Explanation")
        
        st.info("""
        **Realistic Influence Features:**
        
        - **Temporal Decay**: Peer influences fade over time (not permanent)
        - **Habit Formation**: Repeated use builds inertia (harder to switch)
        - **Experience Weighting**: Personal satisfaction overrides peer pressure
        - **Saturation**: Only recent influences matter (prevents over-accumulation)
        - **Fashion Cycles**: Popular modes become less attractive over time
        
        **Result:** Non-monotonic adoption curves (30-50% peaks) that match real-world behavior!
        """)
    
    else:
        st.subheader("📊 Deterministic Influence Mode")
        
        st.warning("""
        **Deterministic influence is active.**
        
        This mode uses the original Phase 4 social influence without:
        - Temporal decay (influences are permanent)
        - Habit formation (no switching resistance)
        - Experience weighting (only peers matter)
        
        **Expected behavior:** Monotonic increase to 80-100% adoption (unrealistic)
        
        💡 **Enable Realistic Influence** in the sidebar to see the difference!
        """)

# ============================================================================
# TAB 4: Network Analysis
# ============================================================================

with tab4:
    st.subheader("🌐 Social Network Analysis")
    
    if network:
        # Network metrics
        net_metrics = network.get_network_metrics()
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Total Agents", net_metrics.total_agents)
            st.metric("Total Connections", net_metrics.total_ties)
        
        with col2:
            st.metric("Avg Degree", f"{net_metrics.avg_degree:.2f}")
            st.metric("Clustering Coeff", f"{net_metrics.clustering_coefficient:.3f}")
        
        with col3:
            st.metric("Network Density", f"{net_metrics.network_density:.3f}")
            st.metric("Strong Tie Ratio", f"{net_metrics.strong_tie_ratio:.2%}")
        
        # Mode distribution
        st.markdown("---")
        st.subheader("📊 Current Mode Distribution")
        
        mode_dist_df = pd.DataFrame([
            {'Mode': mode, 'Share': share}
            for mode, share in net_metrics.mode_distribution.items()
        ])
        
        if not mode_dist_df.empty:
            fig = px.bar(
                mode_dist_df,
                x='Mode',
                y='Share',
                title="Modal Share Across Network"
            )
            fig.update_yaxes(tickformat='.0%')
            st.plotly_chart(fig, use_container_width=True)
        
        # Cascade detection
        st.markdown("---")
        st.subheader("🌊 Cascade Detection")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.metric("Cascade Active", "Yes" if net_metrics.cascade_active else "No")
        
        with col2:
            st.metric("Tipping Point", "Reached" if net_metrics.tipping_point_reached else "Not yet")
        
        # Influence history
        if network._influence_history:
            st.markdown("---")
            st.subheader("📈 Influence Events")
            st.metric("Total Influence Events", len(network._influence_history))
            
            # Show recent events
            with st.expander("Recent Influence Events (Last 10)"):
                for event in network._influence_history[-10:]:
                    st.json(event)
    else:
        st.warning("No network data available")

# ============================================================================
# Auto-advance animation
# ============================================================================

if anim.is_playing:
    delay = 0.2 / anim.speed_multiplier
    time.sleep(delay)
    
    if anim.current_step < anim.total_steps - 1:
        anim.current_step += 1
        st.rerun()
    elif anim.loop:
        anim.current_step = 0
        st.rerun()
    else:
        anim.pause()
        st.rerun()

# ============================================================================
# Footer
# ============================================================================

st.markdown("---")

# Show comparison if realistic influence enabled
if st.session_state.use_realistic_influence:
    st.success("""
    ✅ **Realistic Social Influence Active**
    
    You are seeing enhanced social dynamics with temporal decay, habit formation, 
    and experience weighting. This prevents over-deterministic cascades and produces 
    realistic adoption curves (30-50% peaks with volatility).
    """)
else:
    st.info("""
    📊 **Deterministic Influence Active**
    
    You are seeing the original Phase 4 behavior. Expect monotonic increases 
    to 80-100% adoption. Toggle "Enable Realistic Influence" in the sidebar 
    to see the difference!
    """)

st.caption("**RTD_SIM Phase 4.1** | Realistic Social Influence | Story-Driven BDI Agents")