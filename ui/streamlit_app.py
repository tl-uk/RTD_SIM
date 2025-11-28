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
st.title("🚗 RTD_SIM — Phase 2.1 (OSM Optimized)")

# Sidebar form
with st.sidebar.form("scenario_form", clear_on_submit=False):
    st.markdown("### 🎯 Scenario Setup")
    
    # Basic parameters
    steps = st.number_input("Steps", min_value=10, max_value=500, value=100, step=10)
    agents_n = st.number_input("Agents", min_value=1, max_value=50, value=10, step=1)
    step_minutes = st.number_input("Movement step (min/tick)", min_value=0.1, max_value=5.0, value=0.5, step=0.1)
    
    st.markdown("---")
    st.markdown("### 🗺️ OSM Configuration")
    
    use_osm = st.checkbox("Enable OSM routing", value=False, help="Download and use real street networks")
    
    if use_osm:
        osm_method = st.radio("Load method", ["Place name", "Bounding box"])
        
        if osm_method == "Place name":
            place = st.text_input("Place (e.g., 'Edinburgh, UK')", value="Edinburgh, UK")
            bbox_str = ""
        else:
            place = ""
            bbox_str = st.text_input(
                "Bbox (north,south,east,west)", 
                value="55.97,55.90,-3.15,-3.30",
                help="Example: 55.97,55.90,-3.15,-3.30"
            )
        
        network_type = st.selectbox(
            "Network type",
            ["all", "drive", "walk", "bike"],
            index=0,
            help="all = complete network, drive = roads only, walk/bike = pedestrian/cycle paths"
        )
        
        osm_seed = st.checkbox("Seed agents on OSM nodes", value=True)
        use_cache = st.checkbox("Use cached graphs", value=True, help="Speed up repeated loads")
    else:
        place = ""
        bbox_str = ""
        network_type = "all"
        osm_seed = False
        use_cache = True
        st.info("Using Edinburgh fallback coordinates (no OSM)")
    
    st.markdown("---")
    st.markdown("### 🎨 Visualization")
    smooth_routes = st.checkbox("Densify routes", value=False, help="Add intermediate points for smoother lines")
    
    run_btn = st.form_submit_button("🚀 Run Simulation", type="primary")

# Edinburgh fallback bounds
_EDI_LON_MIN, _EDI_LON_MAX = -3.30, -3.15
_EDI_LAT_MIN, _EDI_LAT_MAX = 55.90, 55.97

def _rand_lonlat_edinburgh(rng: random.Random) -> tuple[float, float]:
    return (rng.uniform(_EDI_LON_MIN, _EDI_LON_MAX), rng.uniform(_EDI_LAT_MIN, _EDI_LAT_MAX))

# Build environment with progress
def build_env(place: str, bbox_str: str, use_osm: bool, network_type: str, use_cache: bool) -> SpatialEnvironment:
    """Build environment with OSM caching."""
    
    # Always create environment with cache directory
    cache_dir = Path.home() / ".rtd_sim_cache" / "osm_graphs"
    env = SpatialEnvironment(step_minutes=step_minutes, cache_dir=cache_dir)
    
    if not use_osm:
        st.success("✅ Using Edinburgh fallback (no OSM)")
        return env
    
    # Parse bbox if provided
    bbox = None
    if bbox_str:
        try:
            parts = [float(x.strip()) for x in bbox_str.split(",")]
            if len(parts) == 4:
                bbox = tuple(parts)
            else:
                st.error("Bbox must have 4 values: north,south,east,west")
                return env
        except Exception:
            st.error("Invalid bbox format")
            return env
    
    # Load graph with spinner
    with st.spinner("Loading OSM graph (this may take 30-60s on first load)..."):
        env.load_osm_graph(
            place=place or None,
            bbox=bbox,
            network_type=network_type,
            use_cache=use_cache
        )
    
    # Show stats
    stats = env.get_graph_stats()
    if stats["loaded"]:
        st.success(f"✅ OSM graph loaded: {stats['nodes']:,} nodes, {stats['edges']:,} edges")
        st.info(f"📦 Cache location: {cache_dir}")
    else:
        st.warning("⚠️ OSM load failed. Using fallback.")
    
    return env

def build_agents(env: SpatialEnvironment, n: int, use_osm_seed: bool) -> list:
    """Create agents with optional OSM seeding."""
    planner = BDIPlanner()
    rng = random.Random(123)
    agents = []
    
    # Precompute nearest nodes if using OSM seeding
    if use_osm_seed and env.graph_loaded:
        points = []
        for _ in range(n * 2):  # Origin + dest for each agent
            coord = env.get_random_node_coords()
            if coord:
                points.append(coord)
        if points:
            env.precompute_nearest_nodes(points)
            st.info(f"✅ Precomputed nearest nodes for {len(points)} points")
    
    for i in range(n):
        # Desire profiles (3 types)
        desires = {
            "eco": [0.8, 0.3, 0.5][i % 3],
            "time": [0.4, 0.7, 0.5][i % 3],
            "cost": [0.2, 0.4, 0.5][i % 3],
            "comfort": [0.3, 0.5, 0.4][i % 3],
            "risk": [0.3, 0.2, 0.3][i % 3],
        }
        
        # Generate origin/dest
        if use_osm_seed and env.graph_loaded:
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

def run_snapshot(steps: int, agents_n: int, place: str, bbox_str: str, 
                osm_seed: bool, use_osm: bool, network_type: str, use_cache: bool):
    """Run simulation with progress feedback."""
    
    progress = st.progress(0, "Initializing...")
    
    # Build environment
    progress.progress(5, "Building environment...")
    env = build_env(place, bbox_str, use_osm, network_type, use_cache)
    st.session_state.env = env
    
    # Build agents
    progress.progress(15, f"Creating {agents_n} agents...")
    agents = build_agents(env, int(agents_n), osm_seed)
    
    # Setup simulation
    progress.progress(25, "Initializing simulation...")
    bus = EventBus()
    data = DataAdapter()
    cfg = SimulationConfig(steps=int(steps))
    ctl = SimulationController(bus, model=None, data_adapter=data, config=cfg, agents=agents, environment=env)
    
    bus.subscribe("state_updated", lambda step, state: data.append_log(step, state))
    bus.subscribe("metrics_updated", lambda metrics: data.append_log(metrics.get("step", 0), metrics))
    
    # Run simulation
    progress.progress(30, "Running simulation...")
    ctl.start()
    
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
    
    # Process data
    progress.progress(90, "Processing results...")
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
    
    progress.progress(100, "✅ Complete!")
    progress.empty()

# Run button handler
if run_btn:
    if agents_n > 30 or steps > 300:
        st.warning("⚠️ Large simulation may take 1-2 minutes")
    
    try:
        run_snapshot(steps, agents_n, place, bbox_str, osm_seed, use_osm, network_type, use_cache)
    except Exception as e:
        st.session_state.last_run_ok = False
        st.session_state.last_error = "".join(traceback.format_exception_only(type(e), e))
        st.error(f"❌ Simulation failed")
        with st.expander("Error Details"):
            st.code(st.session_state.last_error)

# Load results
df = st.session_state.last_df
agent_rows = st.session_state.last_agent_rows
arrivals_df = st.session_state.last_arrivals_df
last_metrics = st.session_state.last_metrics_row
env = st.session_state.get("env", None)

if not st.session_state.last_run_ok or df is None:
    st.info("👈 Configure parameters and click 'Run Simulation'")
    
    # Show cache management
    st.markdown("---")
    st.markdown("### 📦 OSM Cache Management")
    cache_dir = Path.home() / ".rtd_sim_cache" / "osm_graphs"
    if cache_dir.exists():
        cache_files = list(cache_dir.glob("*.pkl"))
        st.write(f"Cached graphs: {len(cache_files)}")
        if cache_files:
            total_size = sum(f.stat().st_size for f in cache_files) / (1024**2)
            st.write(f"Total size: {total_size:.1f} MB")
            if st.button("🗑️ Clear Cache"):
                if env:
                    env.clear_cache()
                st.success("Cache cleared!")
                st.rerun()
    
    if st.session_state.last_error:
        with st.expander("Previous Error"):
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

col1.metric("Arrivals", f"{arrivals_count}/{len(agent_rows)}")
col2.metric("Mean Travel Time", f"{mean_tt} min" if mean_tt else "-")
col3.metric("Total Emissions", f"{total_emissions} g")
col4.metric("Total Distance", f"{total_distance} km")
col5.metric("Mean Dwell", f"{mean_dwell} min" if mean_dwell else "-")

# Modal share
st.subheader("🚦 Modal Share")
if last_metrics is not None:
    ms = last_metrics.get("modal_share", {})
    if isinstance(ms, dict) and ms:
        ms_df = pd.DataFrame([{"mode": k, "count": v} for k, v in ms.items()])
        fig = px.bar(ms_df, x="mode", y="count", title="Final Modal Distribution",
                    color="mode", color_discrete_map={
                        "walk": "#22c55e", "bike": "#3b82f6", "bus": "#f59e0b",
                        "car": "#ef4444", "ev": "#a855f7"
                    })
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
        fig_tt = px.histogram(arrivals_df, x="travel_time_min", nbins=20, title="Travel Time Distribution")
        st.plotly_chart(fig_tt, use_container_width=True)
    with c2:
        fig_dist = px.histogram(arrivals_df, x="distance_km", nbins=20, title="Distance Distribution")
        st.plotly_chart(fig_dist, use_container_width=True)
else:
    st.info("No arrived agents yet")

# Map
st.subheader("🗺️ Agent Positions & Routes")
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

# Add markers
if not agent_rows.empty and "location" in agent_rows.columns:
    for idx, row in agent_rows.head(50).iterrows():
        loc = row.get("location")
        if isinstance(loc, (list, tuple)) and len(loc) == 2:
            lon, lat = loc
            mode = row.get("mode", "")
            color_map = {"walk": "green", "bike": "blue", "bus": "orange", "car": "red", "ev": "purple"}
            
            folium.CircleMarker(
                [lat, lon],
                radius=6,
                color=color_map.get(mode, "gray"),
                fill=True,
                fillOpacity=0.7,
                popup=f"<b>{row.get('agent_id', '')}</b><br>Mode: {mode}<br>Arrived: {row.get('arrived', False)}",
                tooltip=row.get('agent_id', '')
            ).add_to(m)

# Routes
show_routes = st.checkbox("Show routes", value=False)
if show_routes and "route" in agent_rows.columns:
    route_limit = st.slider("Max routes", 1, min(20, len(agent_rows)), min(10, len(agent_rows)))
    
    for idx, r in agent_rows.head(route_limit).iterrows():
        r_raw = r.get("route")
        if isinstance(r_raw, list) and len(r_raw) >= 2:
            poly_pts = r_raw
            if smooth_routes and env is not None:
                try:
                    poly_pts = env.densify_route(r_raw, step_meters=20.0)
                except Exception:
                    pass
            
            poly = [(pt[1], pt[0]) for pt in poly_pts if isinstance(pt, (list, tuple)) and len(pt) == 2]
            if poly:
                mode = r.get("mode", "")
                color_map = {"walk": "green", "bike": "blue", "bus": "orange", "car": "red", "ev": "purple"}
                folium.PolyLine(
                    poly, 
                    color=color_map.get(mode, "gray"),
                    weight=3,
                    opacity=0.6
                ).add_to(m)

st_folium(m, width=1000, height=500)

# Download & debug
col_dl, col_dbg = st.columns([1, 1])

with col_dl:
    if df is not None and not df.empty:
        csv = df.to_csv(index=False)
        st.download_button(
            "💾 Download Results (CSV)",
            csv,
            "rtd_sim_results.csv",
            "text/csv",
        )

with col_dbg:
    with st.expander("🔍 Debug Info"):
        if env:
            stats = env.get_graph_stats()
            st.json(stats)
        if df is not None:
            st.write(f"Dataframe shape: {df.shape}")
            st.dataframe(df.head(10))