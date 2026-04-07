"""
ui/tabs/map_tab.py

Map visualization tab.

Layout
──────
  Left column (controls, 1/4 width):
    • Map Style selector — Carto (no key) and MapTiler styles (free key)
    • MapTiler API key input (only shown when a MapTiler style is selected)
    • Layer toggles, grouped:
        Agents & Routes
        Transport Infrastructure (chargers)
        Transit Network (rail, GTFS, NaPTAN, ferry)
        Environment (congestion)

  Right column (map, 3/4 width):
    • pydeck map rendered as @st.fragment so toggles don't trigger full reruns
    • KPI strip (arrivals, most popular mode, emissions, agents with routes)
    • Policy status widget (when policy active)

NaPTAN without GTFS
───────────────────
NaPTAN station markers work independently of GTFS.  When toggled on, the
authoritative UK rail/ferry/tram stop markers are overlaid from env.naptan_stops
(loaded during setup_environment()).  GTFS is not required.

MapTiler key
────────────
Free tier: 100k tile requests/month.  Sufficient for local development.
Register at https://cloud.maptiler.com/auth/widget?mode=signup
Store key in:
  • Streamlit sidebar input (session_state['maptiler_key'])
  • Environment variable: MAPTILER_API_KEY
"""

from __future__ import annotations

import os
import streamlit as st

from visualiser.visualization import render_map, get_current_stats
from visualiser.style_config import (
    MAP_STYLES,
    DEFAULT_MAP_STYLE_NAME,
    LAYER_DEFAULTS,
    LAYER_LABELS,
    get_map_style_url,
)
from ui.widgets.policy_status_widget import render_policy_status_widget


def render_map_tab(results, anim, current_data):
    """
    Render the Map tab.

    Args:
        results:      SimulationResults
        anim:         AnimationController
        current_data: Current timestep data dict
    """
    agent_states = current_data['agent_states']
    metrics      = current_data.get('metrics', {})
    config       = st.session_state.get('last_config')
    env          = (getattr(results, 'env', None)
                    or getattr(results, 'spatial_environment', None))

    # ── Header ─────────────────────────────────────────────────────────────────
    header = f"Live View — Step {anim.current_step + 1}/{anim.total_steps}"
    if hasattr(results, 'temporal_engine') and results.temporal_engine:
        ti = results.temporal_engine.get_time_info(anim.current_step)
        header += f"  ·  📅 {ti['date']}  {ti['time'][:5]}"
    st.subheader(header)

    # ── Two-column layout ──────────────────────────────────────────────────────
    col_controls, col_map = st.columns([1, 3], gap="small")

    with col_controls:
        _render_map_controls(results, env)

    with col_map:
        _render_map_fragment(agent_states, results, env)

    # ── KPI strip ──────────────────────────────────────────────────────────────
    st.markdown("---")
    stats = get_current_stats(agent_states, metrics)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Arrivals",         stats['arrivals'])
    c2.metric("Most Popular",     stats['most_popular_mode'])
    c3.metric("Emissions",        stats['total_emissions'])
    c4.metric("Agents w/ Routes", stats['agents_with_routes'])

    # ── Policy widget ──────────────────────────────────────────────────────────
    if config and hasattr(results, 'policy_status') and results.policy_status:
        st.markdown("---")
        render_policy_status_widget(results, anim.current_step, config)


# ── Controls panel ─────────────────────────────────────────────────────────────

def _render_map_controls(results, env):
    """Render the left-column map controls panel."""

    # ── Map style selector ─────────────────────────────────────────────────────
    st.markdown("**🗺️ Map style**")

    style_names    = list(MAP_STYLES.keys())
    current_style  = st.session_state.get('map_style_name', DEFAULT_MAP_STYLE_NAME)

    selected_style = st.selectbox(
        "Basemap",
        options=style_names,
        index=style_names.index(current_style) if current_style in style_names else 0,
        key="_map_style_select",
        label_visibility="collapsed",
        help="Carto styles work without an API key. MapTiler styles need a free key.",
    )
    st.session_state['map_style_name'] = selected_style
    style_info = MAP_STYLES[selected_style]
    st.caption(style_info["description"])
    if style_info.get("ferry_lanes"):
        st.caption("✅ Shows ferry lanes & maritime routes")

    # MapTiler API key (only when a MapTiler style is selected)
    if style_info["key_required"]:
        stored_key = (st.session_state.get('maptiler_key', '')
                      or os.environ.get('MAPTILER_API_KEY', ''))
        api_key = st.text_input(
            "MapTiler API key",
            value=stored_key,
            type="password",
            key="_maptiler_key_input",
            placeholder="Get free key at cloud.maptiler.com",
            help=(
                "Free tier: 100k requests/month.\n"
                "https://cloud.maptiler.com/auth/widget?mode=signup\n"
                "Or set env var: MAPTILER_API_KEY"
            ),
        )
        st.session_state['maptiler_key'] = api_key
        if not api_key:
            st.warning("No key → Carto Voyager fallback")

    st.markdown("---")

    # ── Agents & Routes ────────────────────────────────────────────────────────
    st.markdown("**Agents & Routes**")
    _toggle("agents")
    _toggle("routes")
    st.markdown("---")

    # ── Infrastructure ─────────────────────────────────────────────────────────
    st.markdown("**Infrastructure**")
    has_infra = results.infrastructure is not None
    _toggle("infrastructure", disabled=not has_infra,
            disabled_reason="No infrastructure loaded")
    st.markdown("---")

    # ── Transport network ──────────────────────────────────────────────────────
    st.markdown("**Transport Network**")

    has_rail = (
        env is not None
        and hasattr(env, 'graph_manager')
        and env.graph_manager.get_graph('rail') is not None
    )
    _toggle("rail", disabled=not has_rail,
            disabled_reason="Rail graph not loaded (OpenRailMap offline)")

    has_gtfs = (
        env is not None
        and hasattr(env, 'get_transit_graph')
        and env.get_transit_graph() is not None
    )
    _toggle("gtfs_routes", disabled=not has_gtfs, disabled_reason="No GTFS feed loaded")
    _toggle("gtfs_stops",  disabled=not has_gtfs, disabled_reason="No GTFS feed loaded")
    if (st.session_state.get('show_gtfs_routes')
            or st.session_state.get('show_gtfs_stops')):
        _toggle("gtfs_electric_only")

    naptan_stops = (env is not None and hasattr(env, 'naptan_stops')
                    and getattr(env, 'naptan_stops', None))
    has_naptan = bool(naptan_stops)
    _toggle(
        "naptan_stops",
        disabled=not has_naptan,
        disabled_reason=(
            "NaPTAN not loaded. "
            "Place NAPTAN_National_Stops.csv in data/naptan/"
        ),
    )
    if has_naptan and st.session_state.get('show_naptan_stops'):
        st.caption(f"📍 {len(naptan_stops)} NaPTAN stops")

    _toggle("ferry_routes")
    if (st.session_state.get('show_ferry_routes')
            and not style_info.get("ferry_lanes")):
        st.caption("💡 MapTiler OSM or Ocean shows built-in ferry lanes")

    st.markdown("---")

    # ── Environment ────────────────────────────────────────────────────────────
    st.markdown("**Environment**")
    has_cong = (env is not None and hasattr(env, 'congestion_manager')
                and env.congestion_manager is not None)
    _toggle("congestion", disabled=not has_cong,
            disabled_reason="Enable congestion in Advanced Settings")


def _toggle(
    layer_key:       str,
    disabled:        bool = False,
    disabled_reason: str  = "",
):
    """
    Render a single layer toggle checkbox, persisted in session_state.

    Uses a unique key per layer so Streamlit widget state is stable across reruns.
    """
    info    = LAYER_LABELS[layer_key]
    ss_key  = f"show_{layer_key}"
    default = LAYER_DEFAULTS.get(layer_key, False)
    current = st.session_state.get(ss_key, default)
    label   = f"{info['emoji']} {info['label']}"

    if disabled:
        st.checkbox(label, value=False, key=f"_lyr_{layer_key}",
                    disabled=True, help=disabled_reason)
        st.session_state[ss_key] = False
    else:
        new_val = st.checkbox(label, value=current,
                              key=f"_lyr_{layer_key}", help=info["help"])
        st.session_state[ss_key] = new_val


# ── Map fragment ───────────────────────────────────────────────────────────────

@st.fragment
def _render_map_fragment(agent_states, results, env):
    """
    Render pydeck map as a Streamlit fragment.

    Fragment isolation means checkbox toggles only re-run this function,
    not the entire page, giving a smooth UI when switching layers.
    """
    style_name   = st.session_state.get('map_style_name', DEFAULT_MAP_STYLE_NAME)
    maptiler_key = st.session_state.get('maptiler_key', '')
    map_style_url = get_map_style_url(style_name, maptiler_key)

    ss = st.session_state
    D  = LAYER_DEFAULTS

    deck = render_map(
        agent_states        = agent_states,
        show_agents         = ss.get('show_agents',             D['agents']),
        show_routes         = ss.get('show_routes',             D['routes']),
        show_infrastructure = ss.get('show_infrastructure',     D['infrastructure']),
        show_rail           = ss.get('show_rail',               D['rail']),
        show_gtfs           = ss.get('show_gtfs_routes',        D['gtfs_routes']),
        show_gtfs_stops     = ss.get('show_gtfs_stops',         D['gtfs_stops']),
        gtfs_electric_only  = ss.get('show_gtfs_electric_only', D['gtfs_electric_only']),
        show_naptan_stops   = ss.get('show_naptan_stops',       D['naptan_stops']),
        show_ferry_routes   = ss.get('show_ferry_routes',       D['ferry_routes']),
        infrastructure_manager = results.infrastructure,
        env                 = env,
        map_style           = map_style_url,
    )

    st.pydeck_chart(deck, width='stretch')