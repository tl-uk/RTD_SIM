from __future__ import annotations
import sys
from pathlib import Path
import random
import traceback
import ast
import pandas as pd
import plotly.express as px
import folium
import numpy as np
from streamlit_folium import st_folium

# Project root setup
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
from simulation.spatial_environment import SpatialEnvironment
from simulation.controller import SimulationController, SimulationConfig
from simulation.event_bus import EventBus
from simulation.data_adapter import DataAdapter
from agent.cognitive_abm import CognitiveAgent
from agent.bdi_planner import BDIPlanner

# Initialize session state
def _init_session():
    for k, v in {
        "last_df": None,
        "last_agent_rows": None,
        "last_arrivals_df": None,
        "last_metrics_row": None,
        "last_params": None,
        "last_run_ok": False,
        "last_error": "",
        "env": None,
    }.items():
        if k not in st.session_state:
            st.session_state[k] = v
_init_session()

# Page config
st.set_page_config(page_title="RTD_SIM Dashboard", layout="wide")
st.title("RTD_SIM — Phase 4 Dashboard (Performance Patched)")

# Sidebar form with SAFE DEFAULTS
with st.sidebar.form("scenario_form", clear_on_submit=False):
    st.markdown("### Scenario Setup")
    st.info("🔧 Performance patch: Start small (10 agents, 100 steps)")
    steps = st.number_input("Steps", min_value=10, max_value=500, value=100, step=10)
    agents_n = st.number_input("Agents", min_value=1, max_value=50, value=10, step=1)
    
    use_osm = st.checkbox("Enable OSM routing (slower)", value=False)
    
    if use_osm:
        place = st.text_input("OSM place", value="Edinburgh, UK")
        bbox_str = st.text_input("OSM bbox (n,s,e,w)", value="55.97,55.90,-3.15,-3.30")
        osm_seed = st.checkbox("Seed agents on OSM nodes", value=True)
    else:
        place = ""
        bbox_str = ""
        osm_seed = False
        st.warning("Using Edinburgh fallback coordinates (fast)")
    
    smooth_routes = st.checkbox("Smooth routes (very slow!)", value=False)
    step_minutes = st.number_input("Movement step (min/tick)", min_value=0.1, max_value=5.0, value=0.5, step=0.1)
    run_btn = st.form_submit_button("Run Simulation", type="primary")

# Cache OSM load
@st.cache_data(show_spinner=False)
def _cached_load_osm(place: str | None, bbox: tuple | None, step_minutes_cache: float):
    env = SpatialEnvironment(step_minutes=step_minutes_cache)
    loaded = False
    if place or bbox:
        try:
            env.load_osm_graph(place=place or None, bbox=bbox, network_type="all")
            loaded = True
        except Exception:
            loaded = False
    return env, loaded

def build_env(place: str, bbox_str: str, use_osm: bool) -> SpatialEnvironment:
    if not use_osm:
        env = SpatialEnvironment(step_minutes=step_minutes)
        st.success("✅ Using Edinburgh fallback (no OSM)")
        return env
    
    bbox = None
    if bbox_str:
        try:
            n, s, e, w = [float(x.strip()) for x in bbox_str.split(",")]
            bbox = (n, s, e, w)
        except Exception:
            st.warning("Invalid bbox format. Using fallback.")
            return SpatialEnvironment(step_minutes=step_minutes)
    
    with st.spinner("Loading OSM graph..."):
        env, loaded = _cached_load_osm(place or "", bbox, step_minutes)
    
    env.step_minutes = step_minutes
    if loaded:
        st.success("✅ OSM graph loaded (WGS84)")
    else:
        st.warning("⚠️ OSM load failed. Using fallback.")
    return env

# Edinburgh fallback bounds
_EDI_LON_MIN, _EDI_LON_MAX = -3.30, -3.15
_EDI_LAT_MIN, _EDI_LAT_MAX = 55.90, 55.97

def _rand_lonlat_edinburgh(rng: random.Random) -> tuple[float, float]:
    return (rng.uniform(_EDI_LON_MIN, _EDI_LON_MAX), rng.uniform(_EDI_LAT_MIN, _EDI_LAT_MAX))

def build_agents(env: SpatialEnvironment, n: int, use_osm_seed: bool) -> list:
    planner = BDIPlanner()
    rng = random.Random(123)
    agents = []
    
    for i in range(n):
        desires = {
            "eco": [0.8, 0.3, 0.5][i % 3],
            "time": [0.4, 0.7, 0.5][i % 3],
            "cost": [0.2, 0.4, 0.5][i % 3],
            "comfort": [0.3, 0.5, 0.4][i % 3],
            "risk": [0.3, 0.2, 0.3][i % 3],
        }
        
        if use_osm_seed and env.graph_loaded and env.osmnx_available and env.G is not None:
            pair = env.get_random_origin_dest()
            if pair:
                origin, dest = pair
            else:
                origin = _rand_lonlat_edinburgh(rng)
                dest = _rand_lonlat_edinburgh(rng)
        else:
            origin = _rand_lonlat_edinburgh(rng)
            dest = _rand_lonlat_edinburgh(rng)
        
        agents.append(CognitiveAgent(
            seed=42 + i, 
            agent_id=f"agent_{i+1}", 
            desires=desires, 
            planner=planner, 
            origin=origin, 
            dest=dest
        ))
    
    return agents

def _safe_parse_tuple(v):
    if isinstance(v, (list, tuple)):
        return tuple(v)
    if isinstance(v, str):
        try:
            parsed = ast.literal_eval(v)
            return tuple(parsed) if isinstance(parsed, (list, tuple)) else None
        except Exception:
            return None
    return None

def _safe_parse_list(v):
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            parsed = ast.literal_eval(v)
            return parsed if isinstance(parsed, list) else None
        except Exception:
            return None
    return None

def run_snapshot(steps: int, agents_n: int, place: str, bbox_str: str, osm_seed: bool, use_osm: bool):
    """Run simulation with progress feedback"""
    
    # Build environment
    progress = st.progress(0, "Building environment...")
    env = build_env(place, bbox_str, use_osm)
    st.session_state.env = env
    
    # Build agents
    progress.progress(10, f"Creating {agents_n} agents...")
    agents = build_agents(env, int(agents_n), osm_seed)
    
    # Setup simulation
    progress.progress(20, "Initializing simulation...")
    bus = EventBus()
    data = DataAdapter()
    cfg = SimulationConfig(steps=int(steps))
    ctl = SimulationController(bus, model=None, data_adapter=data, config=cfg, agents=agents, environment=env)
    
    bus.subscribe("state_updated", lambda step, state: data.append_log(step, state))
    bus.subscribe("metrics_updated", lambda metrics: data.append_log(metrics.get("step", 0), metrics))
    
    # Run simulation with progress updates
    ctl.start()
    progress.progress(30, "Running simulation...")
    
    # Run in chunks to show progress
    chunk_size = max(1, cfg.steps // 10)
    for chunk in range(10):
        if not ctl._running:
            break
        for _ in range(chunk_size):
            if ctl._current_step >= cfg.steps:
                break
            ctl.step()
        progress.progress(30 + chunk * 6, f"Step {ctl._current_step}/{cfg.steps}")
    
    ctl.stop()
    progress.progress(90, "Processing results...")
    
    # Process data
    df = pd.DataFrame(data.get_log())
    if "location" in df.columns:
        df["location"] = df["location"].apply(_safe_parse_tuple)
    if "route" in df.columns:
        df["route"] = df["route"].apply(_safe_parse_list)
    
    agent_rows = df[df["agent_id"].notna()].sort_values("t").groupby("agent_id").tail(1) if "agent_id" in df.columns else pd.DataFrame()
    arrivals_df = agent_rows[agent_rows["arrived"] == True] if not agent_rows.empty and "arrived" in agent_rows.columns else pd.DataFrame()
    metrics_rows = df[df["modal_share"].notna()] if "modal_share" in df.columns else pd.DataFrame()
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
    
    progress.progress(100, "Complete!")
    progress.empty()

# Run simulation on button click
if run_btn:
    if agents_n > 30 or steps > 300:
        st.warning("⚠️ Large simulation may take 30-60 seconds. Consider reducing agents/steps.")
    
    try:
        run_snapshot(steps, agents_n, place, bbox_str, osm_seed, use_osm)
    except Exception as e:
        st.session_state.last_run_ok = False
        st.session_state.last_error = "".join(traceback.format_exception_only(type(e), e))
        st.error(f"❌ Simulation failed: {st.session_state.last_error}")

# Load cached results
df = st.session_state.last_df
agent_rows = st.session_state.last_agent_rows
arrivals_df = st.session_state.last_arrivals_df
last_metrics = st.session_state.last_metrics_row
env = st.session_state.get("env", None)

if not st.session_state.last_run_ok or df is None:
    st.info("👈 Configure parameters and click 'Run Simulation'")
    if st.session_state.last_error:
        with st.expander("Error Details"):
            st.code(st.session_state.last_error)
    st.stop()

# KPIs
st.subheader("📊 Key Performance Indicators")
col1, col2, col3, col4, col5 = st.columns(5)
arrivals_count = len(arrivals_df)
mean_tt = round(arrivals_df["travel_time_min"].mean(), 2) if arrivals_count > 0 else None
total_emissions = round(float(agent_rows["emissions_g"].sum()), 2) if "emissions_g" in agent_rows.columns else 0.0
total_distance = round(float(agent_rows["distance_km"].sum()), 3) if "distance_km" in agent_rows.columns else 0.0
mean_dwell = round(arrivals_df["dwell_time_min"].mean(), 2) if arrivals_count > 0 else None

col1.metric("Arrivals", arrivals_count)
col2.metric("Mean Travel Time", f"{mean_tt} min" if mean_tt else "-")
col3.metric("Total Emissions", f"{total_emissions} g")
col4.metric("Total Distance", f"{total_distance} km")
col5.metric("Mean Dwell", f"{mean_dwell} min" if mean_dwell else "-")

# Modal share
st.subheader("🚗 Modal Share")
if last_metrics is not None:
    ms = last_metrics.get("modal_share", {})
    if isinstance(ms, dict) and ms:
        ms_df = pd.DataFrame([{"mode": k, "count": v} for k, v in ms.items()])
        fig = px.bar(ms_df, x="mode", y="count", title="Final Modal Distribution")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No modal share data")
else:
    st.info("No modal share data")

# Distributions
st.subheader("📈 Distributions (Arrived Agents)")
if arrivals_count > 0:
    c1, c2 = st.columns(2)
    with c1:
        fig_tt = px.histogram(arrivals_df, x="travel_time_min", nbins=20, title="Travel Time (min)")
        st.plotly_chart(fig_tt, use_container_width=True)
    with c2:
        fig_dw = px.histogram(arrivals_df, x="dwell_time_min", nbins=20, title="Dwell Time (min)")
        st.plotly_chart(fig_dw, use_container_width=True)
else:
    st.info("No arrived agents yet")

# Map
st.subheader("🗺️ Final Agent Positions")
center_lat, center_lon = 55.95, -3.19
latlon_list = []

if not agent_rows.empty and "location" in agent_rows.columns:
    for _, row in agent_rows.iterrows():
        loc = row.get("location")
        if isinstance(loc, (list, tuple)) and len(loc) == 2:
            latlon_list.append((loc[1], loc[0]))

if latlon_list:
    arr = np.array(latlon_list)
    center_lat, center_lon = float(arr[:, 0].mean()), float(arr[:, 1].mean())

m = folium.Map(location=[center_lat, center_lon], zoom_start=12)

# Add markers (limit to 50 for performance)
if not agent_rows.empty and "location" in agent_rows.columns:
    for idx, row in agent_rows.head(50).iterrows():
        loc = row.get("location")
        if isinstance(loc, (list, tuple)) and len(loc) == 2:
            lon, lat = loc
            mode = row.get("mode", "")
            color = {"walk": "green", "bike": "blue", "bus": "orange", "car": "red", "ev": "purple"}.get(mode, "gray")
            folium.CircleMarker(
                [lat, lon],
                radius=5,
                color=color,
                fill=True,
                popup=f"{row.get('agent_id', '')} ({mode})",
            ).add_to(m)

# Optional route drawing (expensive!)
show_routes = st.checkbox("Draw routes (slow for >10 agents)", value=False)
if show_routes and env is not None and "route" in agent_rows.columns:
    route_limit = st.slider("Max routes to draw", 1, len(agent_rows), min(10, len(agent_rows)))
    for idx, r in agent_rows.head(route_limit).iterrows():
        r_raw = r.get("route")
        if isinstance(r_raw, list) and len(r_raw) >= 2:
            poly_pts = r_raw
            if smooth_routes:
                try:
                    poly_pts = env.densify_route(r_raw, step_meters=20.0)
                except Exception:
                    pass
            poly = [(pt[1], pt[0]) for pt in poly_pts if isinstance(pt, (list, tuple)) and len(pt) == 2]
            if poly:
                folium.PolyLine(poly, color="gray", weight=2, opacity=0.4).add_to(m)

st_folium(m, width=1000, height=500)

# Expandable debug panel
with st.expander("🔍 Debug Panel"):
    if df is not None and not df.empty:
        st.write("**Dataframe shape:**", df.shape)
        st.write("**Columns:**", list(df.columns))
        st.dataframe(df.head(10), use_container_width=True)
    else:
        st.info("No data")

# Download results
if df is not None and not df.empty:
    csv = df.to_csv(index=False)
    st.download_button(
        "💾 Download Full Log (CSV)",
        csv,
        "rtd_sim_results.csv",
        "text/csv",
    )