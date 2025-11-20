# ui/streamlit_app.py
from __future__ import annotations

import sys
from pathlib import Path
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parent.parent  # go up from ui/ to project root
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
import random

from simulation.spatial_environment import SpatialEnvironment
from simulation.controller import SimulationController, SimulationConfig
from simulation.event_bus import EventBus
from simulation.data_adapter import DataAdapter
from agent.cognitive_abm import CognitiveAgent
from agent.bdi_planner import BDIPlanner

st.set_page_config(page_title="RTD_SIM Dashboard", layout="wide")
st.title("RTD_SIM — Phase 3 Dashboard (Snapshot Mode)")

# Sidebar controls
st.sidebar.header("Scenario Setup")
steps = st.sidebar.number_input("Steps", min_value=50, max_value=5000, value=300, step=50)
agents_n = st.sidebar.number_input("Agents", min_value=1, max_value=500, value=25, step=1)
place = st.sidebar.text_input("OSM place (e.g., 'Edinburgh, UK')", value="")
bbox_str = st.sidebar.text_input("OSM bbox (north,south,east,west)", value="")
osm_seed = st.sidebar.checkbox("Seed agents on OSM nodes", value=True)
step_minutes = st.sidebar.number_input("Movement step (minutes per tick)", min_value=0.01, max_value=5.0, value=0.1, step=0.01)

run_btn = st.sidebar.button("Run Simulation")

def build_env() -> SpatialEnvironment:
    env = SpatialEnvironment(step_minutes=step_minutes)
    if place or bbox_str:
        bbox = None
        if bbox_str:
            try:
                n, s, e, w = [float(x.strip()) for x in bbox_str.split(",")]
                bbox = (n, s, e, w)
            except Exception:
                st.warning("Invalid bbox format. Expected: north,south,east,west")
        try:
            env.load_osm_graph(place=place or None, bbox=bbox, network_type='all')
            st.success("OSM graph loaded.")
        except Exception:
            st.warning("OSM load failed. Using straight-line fallback.")
    return env

def build_agents(env: SpatialEnvironment, n: int, use_osm_seed: bool) -> list:
    planner = BDIPlanner()
    rng = random.Random(123)
    agents = []
    for i in range(n):
        desires = {
            'eco': [0.8, 0.3, 0.5][i % 3],
            'time': [0.4, 0.7, 0.5][i % 3],
            'cost': [0.2, 0.4, 0.5][i % 3],
            'comfort': [0.3, 0.5, 0.4][i % 3],
            'risk': [0.3, 0.2, 0.3][i % 3],
        }
        if use_osm_seed and env.graph_loaded and env.osmnx_available and env.G is not None:
            pair = env.get_random_origin_dest()
            if pair:
                origin, dest = pair
            else:
                origin = (rng.uniform(0, 5), rng.uniform(0, 5))
                dest = (rng.uniform(0, 5), rng.uniform(0, 5))
        else:
            origin = (rng.uniform(0, 5), rng.uniform(0, 5))
            dest = (rng.uniform(0, 5), rng.uniform(0, 5))
        a = CognitiveAgent(seed=42+i, agent_id=f'agent_{i+1}',
                           desires=desires, planner=planner,
                           origin=origin, dest=dest)
        agents.append(a)
    return agents

def run_snapshot():
    env = build_env()
    agents = build_agents(env, int(agents_n), osm_seed)

    # Sim
    bus = EventBus()
    data = DataAdapter()
    cfg = SimulationConfig(steps=int(steps))
    ctl = SimulationController(bus, model=None, data_adapter=data, config=cfg, agents=agents, environment=env)
    bus.subscribe('state_updated', lambda step, state: data.append_log(step, state))
    bus.subscribe('metrics_updated', lambda metrics: data.append_log(metrics.get('step', 0), metrics))
    ctl.run_steps(cfg.steps)

    # Build DF
    import pandas as pd
    df = pd.DataFrame(data.get_log())

    # KPIs
    col1, col2, col3, col4, col5 = st.columns(5)
    # Aggregates from final per-agent rows
    agent_rows = df[df['agent_id'].notna()].sort_values('t').groupby('agent_id').tail(1)
    arrivals_df = agent_rows[agent_rows['arrived'] == True]
    arrivals_count = len(arrivals_df)
    mean_tt = round(arrivals_df['travel_time_min'].mean(), 2) if not arrivals_df.empty else None
    total_emissions = round(float(agent_rows['emissions_g'].sum()), 2) if not agent_rows.empty else 0.0
    total_distance = round(float(agent_rows['distance_km'].sum()), 3) if not agent_rows.empty else 0.0
    mean_dwell = round(arrivals_df['dwell_time_min'].mean(), 2) if not arrivals_df.empty else None

    col1.metric("Arrivals", arrivals_count)
    col2.metric("Mean Travel Time (min, arrived)", mean_tt if mean_tt is not None else "-")
    col3.metric("Total Emissions (g)", total_emissions)
    col4.metric("Total Distance (km)", total_distance)
    col5.metric("Mean Dwell (min, arrived)", mean_dwell if mean_dwell is not None else "-")

    # Modal share (from last metrics row)
    st.subheader("Modal Share")
    if 'modal_share' in df.columns:
        metrics_rows = df[df['modal_share'].notna()]
        if not metrics_rows.empty:
            latest = metrics_rows.iloc[-1]
            ms = latest['modal_share']
            if isinstance(ms, dict):
                ms_pairs = [{'mode': k, 'count': v} for k, v in ms.items()]
            else:
                # Try to parse dict-like strings if any
                try:
                    import ast
                    parsed = ast.literal_eval(str(ms))
                    ms_pairs = [{'mode': k, 'count': v} for k, v in parsed.items()] if isinstance(parsed, dict) else []
                except Exception:
                    ms_pairs = []
            if ms_pairs:
                ms_df = pd.DataFrame(ms_pairs)
                st.bar_chart(ms_df.set_index('mode')['count'])
            else:
                st.info("No modal share data in latest metrics.")
        else:
            st.info("No metrics rows found.")
    else:
        st.info("No modal_share column in log.")

    # Distributions (travel time & dwell)
    st.subheader("Distributions (Arrived Agents)")
    import plotly.express as px
    if not arrivals_df.empty:
        c1, c2 = st.columns(2)
        fig_tt = px.histogram(arrivals_df, x='travel_time_min', nbins=20, title='Travel Time (min)')
        fig_dw = px.histogram(arrivals_df, x='dwell_time_min', nbins=20, title='Dwell Time (min)')
        c1.plotly_chart(fig_tt, use_container_width=True)
        c2.plotly_chart(fig_dw, use_container_width=True)
    else:
        st.info("No arrived agents to build distributions.")

    # Map of final agent positions
    st.subheader("Final Agent Positions")
    from streamlit_folium import st_folium
    import folium
    # Default center (Edinburgh)
    m = folium.Map(location=[55.95, -3.19], zoom_start=12)
    if not agent_rows.empty:
        for _, row in agent_rows.iterrows():
            loc = row.get('location')
            if isinstance(loc, (list, tuple)) and len(loc) == 2:
                lon, lat = loc
                popup = f"{row.get('agent_id')} ({row.get('mode')}) | TT={row.get('travel_time_min')} min | DW={row.get('dwell_time_min')} min"
                # If lon/lat (OSM) → use [lat, lon], else still plot (may look skewed)
                folium.Marker([lat, lon], popup=popup).add_to(m)
    st_folium(m, width=1000, height=500)

    # Raw log (head/tail)
    st.subheader("Raw log (head)")
    st.dataframe(df.head(20))
    st.subheader("Raw log (tail)")
    st.dataframe(df.tail(20))

if run_btn:
    run_snapshot()
else:
    st.info("Configure parameters on the left and click 'Run Simulation'.")