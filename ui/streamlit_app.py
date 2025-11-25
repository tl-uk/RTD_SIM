
# ui/streamlit_app.py
from __future__ import annotations
import sys
from pathlib import Path
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parent.parent  # ui/ -> project root
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
import random
import traceback
from simulation.spatial_environment import SpatialEnvironment
from simulation.controller import SimulationController, SimulationConfig
from simulation.event_bus import EventBus
from simulation.data_adapter import DataAdapter
from agent.cognitive_abm import CognitiveAgent
from agent.bdi_planner import BDIPlanner

def _init_session():
    for k, v in {
        "last_df": None,
        "last_agent_rows": None,
        "last_arrivals_df": None,
        "last_metrics_row": None,
        "last_params": None,
        "last_run_ok": False,
        "last_error": "",
    }.items():
        if k not in st.session_state:
            st.session_state[k] = v
_init_session()

st.set_page_config(page_title="RTD_SIM Dashboard", layout="wide")
st.title("RTD_SIM — Phase 3 Dashboard (Snapshot Mode)")

with st.sidebar.form("scenario_form", clear_on_submit=False):
    st.markdown("### Scenario Setup")
    steps = st.number_input("Steps", min_value=50, max_value=10000, value=600, step=50)
    agents_n = st.number_input("Agents", min_value=1, max_value=1000, value=50, step=1)
    place = st.text_input("OSM place (e.g., 'Edinburgh, UK')", value="Edinburgh, UK")
    bbox_str = st.text_input("OSM bbox (north,south,east,west)", value="55.97,55.90,-3.15,-3.30")
    osm_seed = st.checkbox("Seed agents on OSM nodes", value=True)
    smooth_routes = st.checkbox('Smooth routes (densify)', value=True)
    step_minutes = st.number_input("Movement step (minutes per tick)", min_value=0.01, max_value=5.0, value=0.5, step=0.01)
    run_btn = st.form_submit_button("Run Simulation")

@st.cache_data(show_spinner=False)
def _cached_load_osm(place: str | None, bbox: tuple[float, float, float, float] | None, step_minutes_cache: float):
    env = SpatialEnvironment(step_minutes=step_minutes_cache)
    loaded = False
    if place or bbox:
        try:
            env.load_osm_graph(place=place or None, bbox=bbox, network_type='all')
            loaded = True
        except Exception:
            loaded = False
    return env, loaded

def build_env(place: str, bbox_str: str) -> SpatialEnvironment:
    bbox = None
    if bbox_str:
        try:
            n, s, e, w = [float(x.strip()) for x in bbox_str.split(",")]
            bbox = (n, s, e, w)
        except Exception:
            st.warning("Invalid bbox format. Expected: north,south,east,west.")
    env, loaded = _cached_load_osm(place or "", bbox, step_minutes)
    env.step_minutes = step_minutes  # ensure current value
    if loaded:
        st.success("OSM graph loaded.")
    else:
        if place or bbox:
            st.warning("OSM load failed or package not installed. Using straight-line fallback.")
    return env

# PATCH: Edinburgh fallback bounds (lon, lat)
_EDI_LON_MIN, _EDI_LON_MAX = -3.30, -3.15
_EDI_LAT_MIN, _EDI_LAT_MAX = 55.90, 55.97

def _rand_lonlat_edinburgh(rng: random.Random) -> tuple[float, float]:
    return (rng.uniform(_EDI_LON_MIN, _EDI_LON_MAX), rng.uniform(_EDI_LAT_MIN, _EDI_LAT_MAX))  # (lon, lat)

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
                origin, dest = pair  # (lon, lat)
            else:
                # PATCH: Edinburgh fallback if OSM fails to generate pair
                origin = _rand_lonlat_edinburgh(rng)
                dest = _rand_lonlat_edinburgh(rng)
        else:
            # PATCH: Edinburgh fallback instead of (0..5, 0..5)
            origin = _rand_lonlat_edinburgh(rng)
            dest = _rand_lonlat_edinburgh(rng)
        agents.append(CognitiveAgent(
            seed=42+i, agent_id=f'agent_{i+1}',
            desires=desires, planner=planner,
            origin=origin, dest=dest
        ))
    return agents

def run_snapshot(steps: int, agents_n: int, place: str, bbox_str: str, osm_seed: bool):
    env = build_env(place, bbox_str)
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
    import pandas as pd, ast
    df = pd.DataFrame(data.get_log())

    # Robust parsing: location (tuple), route (list of tuples)
    if 'location' in df.columns:
        def _parse_loc(v):
            if isinstance(v, (list, tuple)):
                return tuple(v)
            if isinstance(v, str):
                try:
                    parsed = ast.literal_eval(v)
                    return tuple(parsed) if isinstance(parsed, (list, tuple)) else v
                except Exception:
                    return v
            return v
        df['location'] = df['location'].apply(_parse_loc)

    if 'route' in df.columns:
        def _parse_route(v):
            if isinstance(v, list):
                return v
            if isinstance(v, str):
                try:
                    parsed = ast.literal_eval(v)
                    return parsed if isinstance(parsed, list) else v
                except Exception:
                    return v
            return v
        df['route'] = df['route'].apply(_parse_route)

    agent_rows = df[df['agent_id'].notna()].sort_values('t').groupby('agent_id').tail(1)
    arrivals_df = agent_rows[agent_rows['arrived'] == True]
    metrics_rows = df[df['modal_share'].notna()] if 'modal_share' in df.columns else pd.DataFrame()
    last_metrics = metrics_rows.iloc[-1] if not metrics_rows.empty else None

    st.session_state.last_df = df
    st.session_state.last_agent_rows = agent_rows
    st.session_state.last_arrivals_df = arrivals_df
    st.session_state.last_metrics_row = last_metrics
    st.session_state.last_params = {
        "steps": steps, "agents_n": agents_n, "place": place,
        "bbox": bbox_str, "osm_seed": osm_seed, "step_minutes": step_minutes
    }
    st.session_state.last_run_ok = True
    st.session_state.last_error = ""

if run_btn:
    try:
        run_snapshot(steps, agents_n, place, bbox_str, osm_seed)
    except Exception as e:
        st.session_state.last_run_ok = False
        st.session_state.last_error = "".join(traceback.format_exception_only(type(e), e))
        st.error(f"Simulation failed: {st.session_state.last_error}")

df = st.session_state.last_df
agent_rows = st.session_state.last_agent_rows
arrivals_df = st.session_state.last_arrivals_df
last_metrics = st.session_state.last_metrics_row

if not st.session_state.last_run_ok or df is None:
    st.info("No successful simulation yet. Configure parameters and click 'Run Simulation'.")
    if st.session_state.last_error:
        st.code(st.session_state.last_error)
    st.stop()

# --- Sidebar Diagnostics (PATCH) ---
st.sidebar.subheader("Coordinate Diagnostics")
if agent_rows is not None and not agent_rows.empty:
    try:
        lats = [loc[1] for loc in agent_rows['location'] if isinstance(loc, (list, tuple))]  # ABM stores (lon, lat)
        lons = [loc[0] for loc in agent_rows['location'] if isinstance(loc, (list, tuple))]
        st.sidebar.write({
            "min_lat": round(min(lats), 6),
            "max_lat": round(max(lats), 6),
            "min_lon": round(min(lons), 6),
            "max_lon": round(max(lons), 6),
        })
    except Exception:
        st.sidebar.warning("Diagnostics failed to compute min/max lat/lon.")

# Debug counts (verify agent numbers)
st.subheader("Debug Counts")
configured_agents = st.session_state.last_params.get("agents_n")
unique_agents = len(agent_rows['agent_id'].unique()) if agent_rows is not None and not agent_rows.empty else 0
arrivals_count = len(arrivals_df) if arrivals_df is not None else 0
cA, cB, cC = st.columns(3)
cA.metric("Configured agents", configured_agents)
cB.metric("Unique agent_id emitted", unique_agents)
cC.metric("Arrivals", arrivals_count)

# KPIs
st.subheader("Key Performance Indicators (Snapshot)")
col1, col2, col3, col4, col5 = st.columns(5)
mean_tt = round(arrivals_df['travel_time_min'].mean(), 2) if arrivals_df is not None and not arrivals_df.empty else None
total_emissions = round(float(agent_rows['emissions_g'].sum()), 2) if agent_rows is not None and not agent_rows.empty else 0.0
total_distance = round(float(agent_rows['distance_km'].sum()), 3) if agent_rows is not None and not agent_rows.empty else 0.0
mean_dwell = round(arrivals_df['dwell_time_min'].mean(), 2) if arrivals_df is not None and not arrivals_df.empty else None
col1.metric("Arrivals", arrivals_count)
col2.metric("Mean Travel Time (min, arrived)", mean_tt if mean_tt is not None else "-")
col3.metric("Total Emissions (g)", total_emissions)
col4.metric("Total Distance (km)", total_distance)
col5.metric("Mean Dwell (min, arrived)", mean_dwell if mean_dwell is not None else "-")

# Modal share
st.subheader("Modal Share (latest metrics)")
import pandas as pd, ast
ms_pairs = []
if last_metrics is not None:
    ms = last_metrics.get('modal_share', {})
    if isinstance(ms, dict):
        ms_pairs = [{'mode': k, 'count': v} for k, v in ms.items()]
    else:
        try:
            parsed = ast.literal_eval(str(ms))
            if isinstance(parsed, dict):
                ms_pairs = [{'mode': k, 'count': v} for k, v in parsed.items()]
        except Exception:
            pass

if ms_pairs:
    ms_df = pd.DataFrame(ms_pairs)
    st.bar_chart(ms_df.set_index('mode')['count'])
else:
    st.info("No modal share data available.")

# Distributions (Arrived Agents)
st.subheader("Distributions (Arrived Agents)")
import plotly.express as px
if arrivals_df is not None and not arrivals_df.empty:
    c1, c2 = st.columns(2)
    fig_tt = px.histogram(arrivals_df, x='travel_time_min', nbins=20, title='Travel Time (min)')
    fig_dw = px.histogram(arrivals_df, x='dwell_time_min', nbins=20, title='Dwell Time (min)')
    c1.plotly_chart(fig_tt, use_container_width=True, key="tt_hist")
    c2.plotly_chart(fig_dw, use_container_width=True, key="dw_hist")
else:
    st.info("No arrived agents to build distributions.")

# Map (final positions + routes)
st.subheader("Final Agent Positions + Routes")
from streamlit_folium import st_folium
import folium
import numpy as np

# Dynamic center from final positions
latlon_list = []
if agent_rows is not None and not agent_rows.empty:
    for _, row in agent_rows.iterrows():
        loc = row.get('location')
        if isinstance(loc, (list, tuple)) and len(loc) == 2:
            lon, lat = loc  # ABM state is (lon, lat)
            latlon_list.append((lat, lon))

center_lat, center_lon = 55.95, -3.19
if latlon_list:
    arr = np.array(latlon_list)
    center_lat = float(arr[:, 0].mean())
    center_lon = float(arr[:, 1].mean())

m = folium.Map(location=[center_lat, center_lon], zoom_start=12)

# Plot final markers
if agent_rows is not None and not agent_rows.empty:
    for _, row in agent_rows.iterrows():
        loc = row.get('location')
        if isinstance(loc, (list, tuple)) and len(loc) == 2:
            lon, lat = loc  # (lon, lat) -> flip to [lat, lon]
            popup = f"{row.get('agent_id')} ({row.get('mode')}) " \
                    f"TT={row.get('travel_time_min')} min " \
                    f"DW={row.get('dwell_time_min')} min"
            folium.Marker([lat, lon], popup=popup).add_to(m)

# Draw all routes (optional)
show_routes = st.checkbox("Draw all agent routes", value=False)
if show_routes and 'route' in df.columns and agent_rows is not None and not agent_rows.empty:
    last_rows = df.sort_values('t').groupby('agent_id').tail(1)
    for _, r in last_rows.iterrows():
        r_raw = r.get('route')
        if isinstance(r_raw, list) and r_raw and len(r_raw) >= 2:
            # Flip each (lon, lat) to (lat, lon) for rendering
            poly = [(pt[1], pt[0]) for pt in r_raw if isinstance(pt, (list, tuple)) and len(pt) == 2]
            folium.PolyLine(poly, color='gray', weight=2, opacity=0.6).add_to(m)


# When drawing routes:
if show_routes and 'route' in df.columns:
    r_raw = r.get('route')
    if isinstance(r_raw, list) and len(r_raw) >= 2:
        if smooth_routes:
            r_raw = env.densify_route(r_raw, step_meters=20.0)
        poly = [(pt[1], pt[0]) for pt in r_raw]
        folium.PolyLine(poly, color='gray', weight=2, opacity=0.6).add_to(m)


# Highlight selected agent & route
agent_ids = list(agent_rows['agent_id'].unique()) if agent_rows is not None and not agent_rows.empty else []
selected_agent = st.selectbox("Select agent to highlight", options=agent_ids) if agent_ids else None
if selected_agent:
    sel_last = agent_rows[agent_rows['agent_id'] == selected_agent]
    if not sel_last.empty:
        loc = sel_last.iloc[-1].get('location')
        if isinstance(loc, (list, tuple)) and len(loc) == 2:
            lon, lat = loc
            m.location = [lat, lon]
            m.zoom_start = 14
            folium.CircleMarker([lat, lon], radius=7, color='red', fill=True, fill_opacity=0.8,
                                popup=f"{selected_agent} (final)").add_to(m)
        agent_df = df[df['agent_id'] == selected_agent].sort_values('t')
        if 'route' in agent_df.columns and not agent_df.empty:
            last_route_raw = agent_df.iloc[-1]['route']
            if isinstance(last_route_raw, list) and last_route_raw and len(last_route_raw) >= 2:
                polyline = [(pt[1], pt[0]) for pt in last_route_raw if isinstance(pt, (list, tuple)) and len(pt) == 2]
                folium.PolyLine(polyline, color='blue', weight=3, opacity=0.9,
                                popup=f"Route of {selected_agent}").add_to(m)

st_folium(m, width=1000, height=520, key="final_positions_map")

# Raw log
st.subheader("Raw log (head)")
st.dataframe(df.head(20), use_container_width=True)
st.subheader("Raw log (tail)")
st.dataframe(df.tail(20), use_container_width=True)
