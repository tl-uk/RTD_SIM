# streamlit_app.py
import streamlit as st
from pathlib import Path
import random

# IMPORTANT: import your RTD_SIM modules (ensure editable install or sys.path guard)
from simulation.spatial_environment import SpatialEnvironment
from simulation.controller import SimulationController, SimulationConfig
from simulation.event_bus import EventBus
from simulation.data_adapter import DataAdapter
from agent.cognitive_abm import CognitiveAgent
from agent.bdi_planner import BDIPlanner

st.set_page_config(page_title="RTD_SIM Dashboard", layout="wide")
st.title("RTD_SIM — Phase 3 Dashboard (Snapshot Mode)")

# Sidebar controls
steps = st.sidebar.number_input("Steps", min_value=50, max_value=2000, value=300, step=50)
agents_n = st.sidebar.number_input("Agents", min_value=1, max_value=200, value=25, step=1)
place = st.sidebar.text_input("OSM place (e.g., 'Edinburgh, UK')", value="")
bbox_str = st.sidebar.text_input("OSM bbox (north,south,east,west)", value="")
osm_seed = st.sidebar.checkbox("Seed agents on OSM nodes", value=True)

# Build env
env = SpatialEnvironment(step_minutes=0.1)  # faster movement per tick for demo
if place or bbox_str:
    bbox = None
    if bbox_str:
        try:
            n,s,e,w = [float(x.strip()) for x in bbox_str.split(",")]
            bbox = (n,s,e,w)
        except Exception:
            st.warning("Invalid bbox format. Expected: north,south,east,west.")
    try:
        env.load_osm_graph(place=place or None, bbox=bbox, network_type='all')
        st.success("OSM graph loaded.")
    except Exception:
        st.warning("OSM load failed. Using straight-line fallback.")

# Make agents
planner = BDIPlanner()
rng = random.Random(123)
agents = []
for i in range(agents_n):
    desires = {'eco': [0.8,0.3,0.5][i%3], 'time': [0.4,0.7,0.5][i%3],
               'cost': [0.2,0.4,0.5][i%3], 'comfort': [0.3,0.5,0.4][i%3], 'risk': [0.3,0.2,0.3][i%3]}
    if osm_seed and env.graph_loaded and env.osmnx_available and env.G is not None:
        pair = env.get_random_origin_dest()
        if pair:
            origin, dest = pair
        else:
            origin = (rng.uniform(0, 5), rng.uniform(0, 5))
            dest = (rng.uniform(0, 5), rng.uniform(0, 5))
    else:
        origin = (rng.uniform(0, 5), rng.uniform(0, 5))
        dest = (rng.uniform(0, 5), rng.uniform(0, 5))
    a = CognitiveAgent(seed=42+i, agent_id=f'agent_{i+1}', desires=desires, planner=planner, origin=origin, dest=dest)
    agents.append(a)

# Run snapshot
bus = EventBus()
data = DataAdapter()
cfg = SimulationConfig(steps=int(steps))
ctl = SimulationController(bus, model=None, data_adapter=data, config=cfg, agents=agents, environment=env)
bus.subscribe('state_updated', lambda step, state: data.append_log(step, state))
bus.subscribe('metrics_updated', lambda metrics: data.append_log(metrics.get('step', 0), metrics))
ctl.run_steps(cfg.steps)

# Visuals
import pandas as pd
from streamlit_folium import st_folium
import folium
import plotly.express as px

log = data.get_log()
df = pd.DataFrame(log)

st.subheader("Modal Share & Emissions")
# Latest metrics row
metrics_df = df[df['modal_share'].notna()] if 'modal_share' in df.columns else pd.DataFrame()
if not metrics_df.empty:
    latest = metrics_df.iloc[-1]
    st.write(f"Total Emissions (g): {latest.get('emissions_total_g')}")
    ms = latest.get('modal_share', {})
    ms_pairs = [{'mode': k, 'count': v} for k,v in (ms.items() if isinstance(ms, dict) else [])]
    if ms_pairs:
        st.bar_chart(pd.DataFrame(ms_pairs).set_index('mode')['count'])

# Map of final agent positions
st.subheader("Final Agent Positions")
m = folium.Map(location=[55.95, -3.19], zoom_start=12)  # center on Edinburgh by default
if not df.empty and 'agent_id' in df.columns and 'location' in df.columns:
    final = df.sort_values('t').groupby('agent_id').tail(1)
    for _, row in final.iterrows():
        loc = row.get('location')
        if isinstance(loc, (list, tuple)) and len(loc) == 2:
            # (lon, lat) if seeded on OSM; may be synthetic otherwise
            lon, lat = loc
            folium.Marker([lat, lon], popup=f"{row.get('agent_id')} ({row.get('mode')})").add_to(m)
st_folium(m, width=900, height=500)

st.subheader("Raw log (head)")
st.dataframe(df.head(20))