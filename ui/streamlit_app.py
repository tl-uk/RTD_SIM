#!/usr/bin/env python3
"""
RTD_SIM Unified Visualization - REFACTORED VERSION
Phase 4.5 with Extended Regional Support
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
from visualiser.visualization import (
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

st.title("🚦 RTD_SIM - Real-Time Transport Decarbonization Simulator")
st.markdown("**Phase 4.5E-Lite: Multi-Scale Infrastructure**")

# Show active region if simulation running
if st.session_state.simulation_run and st.session_state.current_region:
    results = st.session_state.results
    if results.env and results.env.graph_loaded:
        stats = results.env.get_graph_stats()
        st.info(f"🗺️ **Active Region**: {st.session_state.current_region} | "
               f"{stats['nodes']:,} nodes, {stats['edges']:,} edges")

with st.sidebar:
    st.header("⚙️ Simulation Configuration")
    
    with st.form("config_form"):
        st.markdown("### 📊 Basic Settings")
        steps = st.number_input("Simulation Steps", 20, 200, 100, 20)
        num_agents = st.number_input("Number of Agents", 10, 100, 50, 10)
        
        st.markdown("---")
        st.markdown("### 🗺️ Location")
        use_osm = st.checkbox("Use Real Street Network", value=True)
        if use_osm:
            region_choice = st.selectbox(
                "Region",
                options=['Edinburgh City', 'Central Scotland (Edinburgh-Glasgow)', 'Custom Place'],
                index=0,
                help="Select spatial extent for simulation"
            )
            
            if region_choice == 'Edinburgh City':
                place = "Edinburgh, UK"
                extended_bbox = None
                st.info("📍 City scale: ~30km radius, good for walk/bike/car/EV")
            elif region_choice == 'Central Scotland (Edinburgh-Glasgow)':
                place = None
                extended_bbox = (-4.50, 55.70, -2.90, 56.10)  # (west, south, east, north)
                st.success("📦 Regional scale: ~100km, enables freight between cities")
            else:
                place = st.text_input("City/Place Name", "Edinburgh, UK")
                extended_bbox = None
        else:
            place = ""
            extended_bbox = None
        
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
        
        st.markdown("---")
        st.markdown("### 🔬 Advanced Features")
        
        use_congestion = st.checkbox("Enable Congestion", value=False)
        
        st.markdown("**🔌 Infrastructure (Phase 4.5)**")
        enable_infrastructure = st.checkbox("Enable Infrastructure Awareness", value=True,
            help="EV range constraints, charging stations, grid capacity")
        
        if enable_infrastructure:
            with st.expander("⚙️ Infrastructure Parameters"):
                num_chargers = st.slider("Public Chargers", 10, 100, 50, 10)
                num_depots = st.slider("Commercial Depots", 1, 20, 5, 1)
                grid_capacity_mw = st.slider("Grid Capacity (MW)", 100, 2000, 1000, 100)
        else:
            num_chargers = 0
            num_depots = 0
            grid_capacity_mw = 1000
        
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
    
    # Diagnostics Panel
    if st.session_state.simulation_run:
        with st.expander("🔍 Infrastructure Diagnostics", expanded=False):
            results = st.session_state.results
            
            st.markdown("### 📊 Mode Distribution Analysis")
            
            # Count all modes
            mode_counts = {}
            for agent in results.agents:
                mode = agent.state.mode
                mode_counts[mode] = mode_counts.get(mode, 0) + 1
            
            # Display as table
            mode_data = []
            for mode in ['walk', 'bike', 'bus', 'car', 'ev', 'van_electric', 'van_diesel']:
                count = mode_counts.get(mode, 0)
                pct = (count / len(results.agents) * 100) if results.agents else 0
                mode_data.append({
                    'Mode': mode,
                    'Count': count,
                    'Percentage': f"{pct:.1f}%"
                })
            
            import pandas as pd
            st.dataframe(pd.DataFrame(mode_data), use_container_width=True)
            
            # Highlight freight modes
            freight_count = mode_counts.get('van_electric', 0) + mode_counts.get('van_diesel', 0)
            if freight_count == 0:
                st.error(f"❌ **NO FREIGHT MODES DETECTED** ({freight_count}/50 agents)")
                st.warning("This indicates mode filtering or job context issues")
            else:
                st.success(f"✅ **Freight modes active**: {freight_count}/50 agents ({freight_count/50*100:.1f}%)")
            
            st.markdown("---")
            st.markdown("### 🔌 Infrastructure Status")
            
            # EV-specific metrics
            ev_agents = [a for a in results.agents if a.state.mode in ['ev', 'van_electric']]
            st.metric("EV/Van Electric Agents", f"{len(ev_agents)}/{len(results.agents)} ({len(ev_agents)/len(results.agents)*100:.1f}%)")
            
            # Agent context analysis
            st.markdown("### 🎭 Agent Context Analysis")
            
            job_types = {}
            vehicle_required_count = 0
            
            for agent in results.agents:
                # Get job type
                job_id = getattr(agent, 'job_story_id', 'unknown')
                job_types[job_id] = job_types.get(job_id, 0) + 1
                
                # Check vehicle_required flag
                context = getattr(agent, 'agent_context', {})
                if context.get('vehicle_required', False):
                    vehicle_required_count += 1
            
            st.write(f"**Agents with vehicle_required=True**: {vehicle_required_count}/{len(results.agents)}")
            
            if vehicle_required_count == 0:
                st.error("❌ **CRITICAL**: No agents have vehicle_required flag set!")
                st.info("💡 This means job_contexts.yaml is missing `vehicle_required: true` parameter")
            
            st.markdown("**Job Story Distribution:**")
            for job_id, count in sorted(job_types.items(), key=lambda x: x[1], reverse=True):
                st.write(f"- {job_id}: {count} agents")
            
            st.markdown("---")
            st.markdown("### 🚗 Sample Agent Details")
            
            # Show first 5 agents with full context
            for i, agent in enumerate(results.agents[:5]):
                with st.expander(f"Agent {i+1}: {agent.state.agent_id}"):
                    st.write(f"**Mode**: {agent.state.mode}")
                    st.write(f"**Distance**: {agent.state.distance_km:.1f} km")
                    st.write(f"**Arrived**: {agent.state.arrived}")
                    
                    # Show origin/dest
                    origin = getattr(agent, 'origin', None)
                    dest = getattr(agent, 'dest', None)
                    if origin and dest:
                        from simulation.spatial.coordinate_utils import haversine_km
                        trip_dist = haversine_km(origin, dest)
                        st.write(f"**Trip Distance (O-D)**: {trip_dist:.1f} km")
                    
                    # Show job context
                    context = getattr(agent, 'agent_context', {})
                    st.write(f"**Agent Context**:")
                    st.json(context)
                    
                    # Show available modes (if we can access planner)
                    job_id = getattr(agent, 'job_story_id', None)
                    if job_id:
                        st.write(f"**Job Story**: {job_id}")
            
            st.markdown("---")
            st.markdown("### ⚡ Grid & Charging Analysis")
            
            if results.infrastructure:
                # Current charging state
                current_charging = len(results.infrastructure.agent_charging_state)
                st.metric("Currently Charging", current_charging)
                
                # Check grid load calculation
                grid = results.infrastructure.grid_regions['default']
                st.write(f"**Grid Capacity**: {grid.capacity_mw:.1f} MW")
                st.write(f"**Current Load**: {grid.current_load_mw:.3f} MW")
                st.write(f"**Utilization**: {grid.utilization():.2%}")
                
                # Debug: Calculate expected load
                expected_load_kw = 0.0
                for agent_id, state in results.infrastructure.agent_charging_state.items():
                    station_id = state.get('station_id')
                    if station_id in results.infrastructure.charging_stations:
                        station = results.infrastructure.charging_stations[station_id]
                        expected_load_kw += station.power_kw
                
                st.write(f"**Expected Load (calculated)**: {expected_load_kw/1000:.3f} MW")
                
                if grid.current_load_mw == 0 and current_charging > 0:
                    st.error("❌ **BUG DETECTED**: Agents are charging but grid load = 0!")
                    st.info("💡 Check `infrastructure_manager.update_grid_load()` - status field issue")
                
                # Charging station utilization
                occupied = sum(s.currently_occupied for s in results.infrastructure.charging_stations.values())
                total_ports = sum(s.num_ports for s in results.infrastructure.charging_stations.values())
                st.write(f"**Station Utilization**: {occupied}/{total_ports} ports ({occupied/total_ports*100:.1f}%)")
                
                # Show charging agents
                if current_charging > 0:
                    st.markdown("**Active Charging Sessions:**")
                    for agent_id, state in list(results.infrastructure.agent_charging_state.items())[:5]:
                        station_id = state.get('station_id', 'unknown')
                        status = state.get('status', 'unknown')
                        duration = state.get('duration_min', 0)
                        st.write(f"- {agent_id}: {station_id} ({status}, {duration:.0f}min)")
                
                # Peak utilization
                if results.infrastructure.historical_utilization:
                    peak_util = max(results.infrastructure.historical_utilization)
                    avg_util = sum(results.infrastructure.historical_utilization) / len(results.infrastructure.historical_utilization)
                    st.write(f"**Peak Utilization**: {peak_util:.1%}")
                    st.write(f"**Average Utilization**: {avg_util:.1%}")
            
            st.markdown("---")
            st.markdown("### 🧪 Mode Filtering Test")
            
            # Test mode filtering for a sample agent
            if results.agents:
                test_agent = results.agents[0]
                context = getattr(test_agent, 'agent_context', {})
                
                # Try to access planner
                planner = getattr(test_agent, 'planner', None)
                if planner:
                    st.write("**Testing mode filtering for first agent:**")
                    st.write(f"Context: {context}")
                    
                    # Calculate trip distance
                    origin = getattr(test_agent, 'origin', None)
                    dest = getattr(test_agent, 'dest', None)
                    
                    if origin and dest:
                        from simulation.spatial.coordinate_utils import haversine_km
                        trip_distance = haversine_km(origin, dest)
                        
                        # Call the filter function
                        available_modes = planner._filter_modes_by_context(context, trip_distance)
                        
                        st.write(f"**Trip Distance**: {trip_distance:.1f} km")
                        st.write(f"**Available Modes**: {available_modes}")
                        
                        if 'van_electric' not in available_modes and 'van_diesel' not in available_modes:
                            st.error("❌ Freight modes NOT in available modes!")
                            if context.get('vehicle_required'):
                                st.error("❌ vehicle_required=True but freight modes excluded - BDI planner bug!")
                            else:
                                st.warning("⚠️ vehicle_required=False - job context not propagating")
    
            st.markdown("---")
            st.markdown("### 🔍 Freight Agent Deep Dive")

            # Find agents with freight jobs
            freight_agents = [
                a for a in results.agents
                if hasattr(a, 'job_story_id')
                and ('freight' in a.job_story_id.lower() or 'delivery' in a.job_story_id.lower())
            ]

            if freight_agents:
                st.write(f"**Found {len(freight_agents)} freight/delivery agents**")
                
                # Check first 3 freight agents
                for i, agent in enumerate(freight_agents[:3]):
                    with st.expander(f"Freight Agent {i+1}: {agent.state.agent_id}", expanded=(i==0)):
                        context = getattr(agent, 'agent_context', {})
                        origin = getattr(agent, 'origin', None)
                        dest = getattr(agent, 'dest', None)
                        planner = getattr(agent, 'planner', None)
                        
                        st.write(f"**Job Story**: {agent.job_story_id}")
                        st.write(f"**User Story**: {agent.user_story_id}")
                        st.write(f"**Mode Chosen**: {agent.state.mode}")
                        st.write(f"**Distance Traveled**: {agent.state.distance_km:.1f} km")
                        
                        st.write(f"**Agent Context**:")
                        st.json(context)
                        
                        # Test mode filtering for this specific agent
                        if origin and dest and planner:
                            try:
                                from simulation.spatial.coordinate_utils import haversine_km
                                trip_distance = haversine_km(origin, dest)
                                
                                st.write(f"**Trip Distance (O-D)**: {trip_distance:.1f} km")
                                
                                # Call the filter function with DEBUG
                                available_modes = planner._filter_modes_by_context(context, trip_distance)
                                
                                st.write(f"**Available Modes from Filter**: {available_modes}")
                                
                                # Check if freight modes are in the list
                                has_freight = 'van_electric' in available_modes or 'van_diesel' in available_modes
                                
                                if has_freight:
                                    st.success("✅ Freight modes ARE AVAILABLE")
                                    
                                    # But agent didn't choose them - why?
                                    if agent.state.mode not in ['van_electric', 'van_diesel']:
                                        st.error(f"⚠️ Agent chose {agent.state.mode} instead of freight mode")
                                        st.write("**Possible reasons:**")
                                        st.write("1. BDI cost function prefers the chosen mode")
                                        st.write("2. Freight mode not feasible (infrastructure check)")
                                        st.write("3. Agent desires favor non-freight modes")
                                        
                                        # Show agent desires
                                        desires = getattr(agent, 'desires', {})
                                        st.write(f"**Agent Desires**: {desires}")
                                else:
                                    st.error("❌ Freight modes NOT AVAILABLE")
                                    st.write("**BUG CONFIRMED!** Mode filtering is wrong")
                                    st.write(f"Context shows vehicle_required={context.get('vehicle_required')}")
                                    st.write(f"But filter returned: {available_modes}")
                                    
                            except Exception as e:
                                st.error(f"Error testing mode filter: {e}")
                                import traceback
                                st.code(traceback.format_exc())
                        else:
                            st.warning("Cannot test - missing origin/dest/planner")
            else:
                st.warning("No freight/delivery agents found - check job story selection")


    # Animation controls
    if st.session_state.simulation_run and st.session_state.animation_controller:
        st.markdown("---")
        st.header("🎬 Animation Controls")
        
        anim = st.session_state.animation_controller
        
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
        
        st.markdown("---")
        auto_play = st.checkbox("▶️ Auto-Play", value=anim.is_playing, key='auto_play')
        if auto_play != anim.is_playing:
            if auto_play:
                anim.play()
            else:
                anim.pause()
            st.rerun()
        
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
        
        st.markdown("---")
        st.markdown("**Display Options**")
        st.session_state.show_agents = st.checkbox("Show Agents", 
            value=st.session_state.show_agents)
        st.session_state.show_routes = st.checkbox("Show Routes", 
            value=st.session_state.show_routes)
        st.session_state.show_infrastructure = st.checkbox("Show Infrastructure", 
            value=st.session_state.show_infrastructure)

if run_btn:
    config = SimulationConfig(
        steps=steps,
        num_agents=num_agents,
        place=place,
        extended_bbox=extended_bbox,
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

if not st.session_state.simulation_run:
    st.info("👈 Configure parameters in the sidebar and click **Run Simulation**")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 🎯 Quick Start")
        st.markdown("1. Select region (City or Regional)")
        st.markdown("2. Choose user & job stories")
        st.markdown("3. Enable infrastructure")
        st.markdown("4. Click **Run Simulation**")
    
    with col2:
        st.markdown("### 🎨 Color Guide")
        for mode, color in MODE_COLORS_HEX.items():
            st.markdown(f"<span style='color:{color};font-size:20px'>●</span> {mode.capitalize()}", 
                       unsafe_allow_html=True)
    
    st.stop()

results = st.session_state.results
anim = st.session_state.animation_controller

current_data = results.time_series.get_timestep(anim.current_step)
if not current_data:
    st.error("No data available")
    st.stop()

agent_states = current_data['agent_states']
metrics = current_data.get('metrics', {})

tab_names = ["🗺️ Map", "📈 Mode Adoption", "🎯 Impact", "🌐 Network"]
if results.infrastructure:
    tab_names.append("🔌 Infrastructure")

tabs = st.tabs(tab_names)

with tabs[0]:
    st.subheader(f"Live View - Step {anim.current_step + 1}/{anim.total_steps}")
    
    deck = render_map(
        agent_states=agent_states,
        show_agents=st.session_state.show_agents,
        show_routes=st.session_state.show_routes,
        show_infrastructure=st.session_state.show_infrastructure,
        infrastructure_manager=results.infrastructure,
    )
    
    st.pydeck_chart(deck, use_container_width=True)
    
    st.markdown("---")
    stats = get_current_stats(agent_states, metrics)
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Arrivals", stats['arrivals'])
    col2.metric("Most Popular", stats['most_popular_mode'])
    col3.metric("Emissions", stats['total_emissions'])
    col4.metric("Agents w/ Routes", stats['agents_with_routes'])

with tabs[1]:
    st.subheader("📈 Mode Adoption Over Time")
    
    fig = render_mode_adoption_chart(results.adoption_history, anim.current_step)
    st.plotly_chart(fig, use_container_width=True)
    
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

with tabs[2]:
    st.subheader("🎯 Environmental Impact")
    
    fig = render_emissions_chart(results.time_series)
    st.plotly_chart(fig, use_container_width=True)

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
        
        if infra_data['grid_figure']:
            st.plotly_chart(infra_data['grid_figure'], use_container_width=True)

if anim.is_playing:
    time.sleep(0.3 / anim.speed_multiplier)
    if anim.current_step < anim.total_steps - 1:
        anim.current_step += 1
        st.rerun()
    else:
        anim.pause()
        st.rerun()

st.markdown("---")

col1, col2 = st.columns([2, 1])

with col1:
    if results.infrastructure:
        st.success("✅ **Infrastructure-Aware Mode** - Phase 4.5E-Lite Active")
    elif results.network and use_realistic:
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

st.caption("**RTD_SIM** - Phase 4.5E-Lite: Multi-Scale Infrastructure | Glasgow-Edinburgh Corridor Ready")