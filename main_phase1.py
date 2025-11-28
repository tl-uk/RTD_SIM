"""
RTD_SIM Phase 1 Baseline - Clean Foundation
============================================
Stripped-down version focusing on:
- 5 agents max
- No OSM (Edinburgh bbox coordinates only)
- Simple Streamlit UI
- Event bus + controller pattern
- CSV export

Usage:
    streamlit run main_phase1.py
"""

from __future__ import annotations
import sys
from pathlib import Path
import random
import pandas as pd
import plotly.express as px
import folium
from streamlit_folium import st_folium

# Project root
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
from simulation.event_bus import EventBus
from simulation.controller import SimulationController, SimulationConfig
from simulation.data_adapter import DataAdapter
from agent.cognitive_abm import CognitiveAgent
from agent.bdi_planner import BDIPlanner

# Simple environment without OSM
class SimpleEnvironment:
    """Lightweight environment for Phase 1 - no OSM dependencies"""
    
    def __init__(self, step_minutes: float = 1.0):
        self.step_minutes = step_minutes
        self.speeds_km_min = {
            'walk': 0.083,  # ~5 km/h
            'bike': 0.25,   # ~15 km/h
            'bus': 0.33,    # ~20 km/h
            'car': 0.5,     # ~30 km/h
            'ev': 0.5,      # ~30 km/h
        }
    
    def compute_route(self, agent_id: str, origin: tuple, dest: tuple, mode: str) -> list:
        """Straight-line route for Phase 1"""
        return [origin, dest]
    
    def get_speed_km_min(self, mode: str) -> float:
        return self.speeds_km_min.get(mode, 0.1)
    
    def estimate_travel_time(self, route: list, mode: str) -> float:
        if len(route) < 2:
            return 0.0
        dist = self._distance(route)
        speed = self.get_speed_km_min(mode)
        return dist / speed if speed > 0 else float('inf')
    
    def estimate_monetary_cost(self, route: list, mode: str) -> float:
        costs = {'walk': 0.0, 'bike': 0.0, 'bus': 1.5, 'car': 3.0, 'ev': 2.0}
        return costs.get(mode, 1.0)
    
    def estimate_comfort(self, route: list, mode: str) -> float:
        comfort = {'walk': 0.5, 'bike': 0.6, 'bus': 0.7, 'car': 0.8, 'ev': 0.85}
        return comfort.get(mode, 0.5)
    
    def estimate_risk(self, route: list, mode: str) -> float:
        risk = {'walk': 0.2, 'bike': 0.3, 'bus': 0.15, 'car': 0.25, 'ev': 0.20}
        return risk.get(mode, 0.2)
    
    def estimate_emissions(self, route: list, mode: str) -> float:
        grams_per_km = {'walk': 0.0, 'bike': 0.0, 'bus': 80.0, 'car': 180.0, 'ev': 60.0}
        dist = self._distance(route)
        return grams_per_km.get(mode, 100.0) * dist
    
    def _distance(self, route: list) -> float:
        """Cartesian distance for Phase 1"""
        if len(route) < 2:
            return 0.0
        total = 0.0
        for i in range(len(route) - 1):
            x1, y1 = route[i]
            x2, y2 = route[i + 1]
            total += ((x2 - x1)**2 + (y2 - y1)**2)**0.5
        return total
    
    def _segment_distance_km(self, a: tuple, b: tuple) -> float:
        """Segment distance for movement"""
        return ((b[0] - a[0])**2 + (b[1] - a[1])**2)**0.5
    
    def advance_along_route(self, route: list, idx: int, offset: float, mode: str) -> tuple:
        """Move agent along route"""
        if not route or len(route) < 2:
            return 0, 0.0, route[0] if route else (0.0, 0.0)
        
        distance_to_move = self.get_speed_km_min(mode) * self.step_minutes
        current_idx = max(0, min(idx, len(route) - 2))
        current_offset = max(0.0, offset)
        
        while distance_to_move > 1e-9 and current_idx < len(route) - 1:
            seg_start = route[current_idx]
            seg_end = route[current_idx + 1]
            seg_length = self._segment_distance_km(seg_start, seg_end)
            remaining_on_seg = seg_length - current_offset
            
            if distance_to_move < remaining_on_seg:
                # Move partway along segment
                frac = (current_offset + distance_to_move) / seg_length if seg_length > 0 else 1.0
                new_x = seg_start[0] + frac * (seg_end[0] - seg_start[0])
                new_y = seg_start[1] + frac * (seg_end[1] - seg_start[1])
                return current_idx, current_offset + distance_to_move, (new_x, new_y)
            else:
                # Move to next segment
                distance_to_move -= remaining_on_seg
                current_idx += 1
                current_offset = 0.0
        
        return len(route) - 2, 0.0, route[-1]


# Edinburgh bbox coordinates (lon, lat)
EDI_LON_MIN, EDI_LON_MAX = -3.30, -3.15
EDI_LAT_MIN, EDI_LAT_MAX = 55.90, 55.97

def random_edinburgh_point(rng: random.Random) -> tuple:
    """Generate random point in Edinburgh bbox"""
    return (
        rng.uniform(EDI_LON_MIN, EDI_LON_MAX),
        rng.uniform(EDI_LAT_MIN, EDI_LAT_MAX)
    )

def create_agents(n: int, env: SimpleEnvironment) -> list:
    """Create n agents with random origins/destinations"""
    planner = BDIPlanner()
    rng = random.Random(42)
    agents = []
    
    desire_profiles = [
        {'eco': 0.8, 'time': 0.4, 'cost': 0.2, 'comfort': 0.3, 'risk': 0.3},  # Eco-friendly
        {'eco': 0.3, 'time': 0.8, 'cost': 0.4, 'comfort': 0.5, 'risk': 0.2},  # Time-focused
        {'eco': 0.5, 'time': 0.5, 'cost': 0.8, 'comfort': 0.4, 'risk': 0.3},  # Cost-conscious
    ]
    
    for i in range(n):
        origin = random_edinburgh_point(rng)
        dest = random_edinburgh_point(rng)
        desires = desire_profiles[i % len(desire_profiles)]
        
        agent = CognitiveAgent(
            seed=42 + i,
            agent_id=f"agent_{i+1}",
            desires=desires,
            planner=planner,
            origin=origin,
            dest=dest
        )
        agents.append(agent)
    
    return agents

def run_simulation(steps: int, n_agents: int) -> pd.DataFrame:
    """Run simulation and return results DataFrame"""
    
    # Setup
    env = SimpleEnvironment(step_minutes=0.5)
    agents = create_agents(n_agents, env)
    bus = EventBus()
    data = DataAdapter()
    config = SimulationConfig(steps=steps)
    
    # Controller
    controller = SimulationController(
        bus=bus,
        model=None,
        data_adapter=data,
        config=config,
        agents=agents,
        environment=env
    )
    
    # Event subscriptions
    bus.subscribe("state_updated", lambda step, state: data.append_log(step, state))
    bus.subscribe("metrics_updated", lambda metrics: data.append_log(metrics.get("step", 0), metrics))
    
    # Run
    progress_bar = st.progress(0, "Running simulation...")
    controller.start()
    
    for i in range(steps):
        controller.step()
        if i % 10 == 0:
            progress_bar.progress((i + 1) / steps, f"Step {i + 1}/{steps}")
    
    controller.stop()
    progress_bar.empty()
    
    # Return results
    return pd.DataFrame(data.get_log())


# Streamlit UI
st.set_page_config(page_title="RTD_SIM Phase 1", layout="wide")
st.title("🚗 RTD_SIM - Phase 1 Clean Baseline")

st.sidebar.header("Simulation Parameters")
steps = st.sidebar.slider("Steps", 10, 200, 100, 10)
n_agents = st.sidebar.slider("Agents", 1, 5, 3, 1)

if st.sidebar.button("🚀 Run Simulation", type="primary"):
    with st.spinner("Running simulation..."):
        df = run_simulation(steps, n_agents)
        st.session_state.results = df

# Display results
if "results" in st.session_state:
    df = st.session_state.results
    
    # Filter agent rows
    agent_df = df[df["agent_id"].notna()].copy()
    final_df = agent_df.groupby("agent_id").tail(1)
    
    # KPIs
    st.subheader("📊 Key Metrics")
    col1, col2, col3, col4 = st.columns(4)
    
    arrivals = final_df[final_df["arrived"] == True]
    col1.metric("Agents", n_agents)
    col2.metric("Arrivals", len(arrivals))
    col3.metric("Total Emissions (g)", round(final_df["emissions_g"].sum(), 1))
    col4.metric("Total Distance (km)", round(final_df["distance_km"].sum(), 2))
    
    # Modal share
    if not final_df.empty:
        st.subheader("🚦 Modal Share")
        mode_counts = final_df["mode"].value_counts().reset_index()
        mode_counts.columns = ["mode", "count"]
        fig_modes = px.bar(mode_counts, x="mode", y="count", title="Final Mode Choice")
        st.plotly_chart(fig_modes, use_container_width=True)
    
    # Travel time distribution
    if len(arrivals) > 0:
        st.subheader("⏱️ Travel Time Distribution")
        fig_tt = px.histogram(arrivals, x="travel_time_min", nbins=15, title="Travel Time (minutes)")
        st.plotly_chart(fig_tt, use_container_width=True)
    
    # Map
    st.subheader("🗺️ Agent Positions")
    center_lat = (EDI_LAT_MIN + EDI_LAT_MAX) / 2
    center_lon = (EDI_LON_MIN + EDI_LON_MAX) / 2
    
    m = folium.Map(location=[center_lat, center_lon], zoom_start=12)
    
    # Add markers
    for _, row in final_df.iterrows():
        loc = row.get("location")
        if isinstance(loc, (list, tuple)) and len(loc) == 2:
            lon, lat = loc
            mode = row.get("mode", "unknown")
            color_map = {
                "walk": "green",
                "bike": "blue", 
                "bus": "orange",
                "car": "red",
                "ev": "purple"
            }
            
            folium.CircleMarker(
                location=[lat, lon],
                radius=8,
                color=color_map.get(mode, "gray"),
                fill=True,
                popup=f"{row['agent_id']}<br>Mode: {mode}<br>Arrived: {row['arrived']}",
                tooltip=row['agent_id']
            ).add_to(m)
    
    st_folium(m, width=1000, height=500)
    
    # Data export
    st.subheader("💾 Export Data")
    csv = df.to_csv(index=False)
    st.download_button(
        "Download CSV",
        csv,
        "rtd_sim_phase1.csv",
        "text/csv"
    )
    
    # Raw data viewer
    with st.expander("🔍 View Raw Data"):
        st.dataframe(df.head(50), use_container_width=True)

else:
    st.info("👈 Configure parameters and click 'Run Simulation' to start")
    
    st.markdown("""
    ### Phase 1 Features
    - ✅ 1-5 agents (clean, fast testing)
    - ✅ Edinburgh bbox (no OSM dependency)
    - ✅ BDI planning with mode choice
    - ✅ Movement along routes
    - ✅ Arrival tracking
    - ✅ Emissions & distance metrics
    - ✅ Simple Folium map
    - ✅ CSV export
    
    ### Next Steps (Phase 2+)
    - OSM integration for real street networks
    - Deck.gl for advanced visualization
    - Real-time streaming with MQTT
    - Social network effects
    - System dynamics integration
    """)