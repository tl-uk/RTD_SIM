"""
ui/tabs/map_tab.py

Map visualization tab.

Layout
──────
  The sidebar (sidebar_config.py) owns ALL map layer toggles and the
  basemap style selector.  This tab renders:
    • Header with step / temporal info
    • Full-width pydeck map (fragment-isolated so toggles don't rerun the page)
    • KPI strip (arrivals, most popular mode, emissions, agents with routes)
    • Policy status widget (when active)

  All session_state keys read here are written by sidebar_config.py:
      show_agents, show_routes, show_infrastructure,
      show_rail, show_gtfs_routes, show_gtfs_stops, show_gtfs_electric_only,
      show_naptan_stops, show_ferry_routes,
      map_style_name, maptiler_key
"""

from __future__ import annotations

import streamlit as st

from visualiser.visualization import render_map, get_current_stats
from visualiser.style_config import (
    DEFAULT_MAP_STYLE_NAME,
    LAYER_DEFAULTS,
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

    # ── Map (full width, fragment-isolated) ────────────────────────────────────
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


# ── Map fragment ───────────────────────────────────────────────────────────────

@st.fragment
def _render_map_fragment(agent_states, results, env):
    """
    Render pydeck map as a Streamlit fragment.

    Fragment isolation means sidebar checkbox changes only re-run this
    function, not the entire page, giving a smooth UI when switching layers.
    All toggle state is read from session_state (written by sidebar_config.py).
    """
    style_name    = st.session_state.get('map_style_name', DEFAULT_MAP_STYLE_NAME)
    maptiler_key  = st.session_state.get('maptiler_key', '')
    map_style_url = get_map_style_url(style_name, maptiler_key)

    ss = st.session_state
    D  = LAYER_DEFAULTS

    deck = render_map(
        agent_states           = agent_states,
        show_agents            = ss.get('show_agents',             D['agents']),
        show_routes            = ss.get('show_routes',             D['routes']),
        show_infrastructure    = ss.get('show_infrastructure',     D['infrastructure']),
        show_rail              = ss.get('show_rail',               D['rail']),
        # Canonical key is show_gtfs_routes (sidebar writes this).
        # Fall back to show_gtfs for backward compat with old session states.
        show_gtfs              = ss.get('show_gtfs_routes',        ss.get('show_gtfs', D['gtfs_routes'])),
        show_gtfs_stops        = ss.get('show_gtfs_stops',         D['gtfs_stops']),
        show_gtfs_electric_only= ss.get('show_gtfs_electric_only', D['gtfs_electric_only']),
        show_naptan_stops      = ss.get('show_naptan_stops',       D['naptan_stops']),
        show_ferry_routes      = ss.get('show_ferry_routes',       D['ferry_routes']),
        infrastructure_manager = results.infrastructure,
        env                    = env,
        map_style              = map_style_url,
    )

    st.pydeck_chart(deck, width='stretch')