"""
ui/tabs/gtfs_analytics_tab.py

GTFS Transit Analytics tab for RTD_SIM.

Displays the four post-simulation analytics panels computed by
simulation/gtfs/gtfs_analytics.py:

  Panel 1 — Transit Desert Map
    Pydeck HeatmapLayer showing where agents lack walkable, frequent transit.
    Answers: "Where does poor transit force car dependency?"

  Panel 2 — Electrification Opportunity Ranking
    Bar chart of diesel routes ranked by annual CO₂ saving potential.
    Answers: "Which routes should be electrified first?"

  Panel 3 — Modal Shift Threshold Analysis
    Funnel chart of car users by how much headway improvement flips them.
    Answers: "What frequency investment is needed to achieve modal shift?"

  Panel 4 — Emissions Hotspot Map
    Pydeck HeatmapLayer of CO₂ burden by grid cell.
    Answers: "Which corridors are the highest-priority decarbonisation targets?"

Tab is visible only when GTFS data was loaded for the simulation run.
If no GTFS data is present it shows a setup guide instead.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import streamlit as st

logger = logging.getLogger(__name__)

try:
    import plotly.graph_objects as go
    import plotly.express as px
    _PLOTLY = True
except ImportError:
    _PLOTLY = False

try:
    import pydeck as pdk
    import pandas as pd
    _PDK = True
except ImportError:
    _PDK = False


# ── Colour constants (match MODE_COLORS_HEX from visualization.py) ────────────
_MODE_COLORS = {
    'bus':             '#f59e0b',
    'tram':            '#ffc107',
    'local_train':     '#2196f3',
    'intercity_train': '#3f51b5',
    'ferry_diesel':    '#009688',
    'ferry_electric':  '#00bcd4',
    'car':             '#ef4444',
    'ev':              '#a855f7',
    'walk':            '#22c55e',
    'bike':            '#3b82f6',
}


# ── Main entry point ──────────────────────────────────────────────────────────

def render_gtfs_analytics_tab(results: Dict[str, Any], agents: list, env: Any) -> None:
    """
    Render the GTFS Transit Analytics tab.

    Args:
        results: Simulation results dict from run_simulation().
        agents:  Agent list (used for on-demand analytics if pre-computed absent).
        env:     SpatialEnvironment (for on-demand analytics).
    """
    st.header("GTFS Transit Analytics")

    # ── Check whether GTFS data / analytics are available ─────────────────
    gtfs_report = results.get('gtfs_analytics')
    has_transit = env is not None and hasattr(env, 'get_transit_graph') and \
                  env.get_transit_graph() is not None

    if not has_transit and gtfs_report is None:
        _render_setup_guide()
        return

    # ── Run analytics on-demand if not pre-computed ───────────────────────
    if gtfs_report is None:
        with st.spinner("Computing GTFS analytics…"):
            try:
                from simulation.gtfs.gtfs_analytics import run_full_gtfs_analysis
                policy_context = {
                    'value_of_time_gbp_h':  10.0,
                    'energy_price_gbp_km':   0.12,
                    'carbon_tax_gbp_tco2':   0.0,
                }
                gtfs_report = run_full_gtfs_analysis(
                    agents         = agents,
                    results        = results,
                    env            = env,
                    policy_context = policy_context,
                )
            except Exception as exc:
                st.error(f"GTFS analytics failed: {exc}")
                logger.error("GTFS tab analytics error: %s", exc)
                return

    # ── Top-level KPIs ────────────────────────────────────────────────────
    _render_kpi_strip(gtfs_report)

    st.markdown("---")

    # ── Four panels in 2×2 grid ───────────────────────────────────────────
    col_l, col_r = st.columns(2)

    with col_l:
        _render_transit_desert_panel(gtfs_report.get('transit_deserts', {}))

    with col_r:
        _render_electrification_panel(gtfs_report.get('electrification', []))

    st.markdown("---")

    col_l2, col_r2 = st.columns(2)

    with col_l2:
        _render_modal_shift_panel(gtfs_report.get('modal_shift', {}))

    with col_r2:
        _render_emissions_hotspot_panel(gtfs_report.get('emissions_hotspots', {}))

    st.markdown("---")

    # ── Policy lever recommendations ──────────────────────────────────────
    _render_policy_levers(gtfs_report)

    # ── Raw data expander (for research export) ───────────────────────────
    with st.expander("Export raw analytics data"):
        _render_raw_export(gtfs_report)


# ── KPI strip ─────────────────────────────────────────────────────────────────

def _render_kpi_strip(report: Dict) -> None:
    deserts  = report.get('transit_deserts', {}).get('summary', {})
    shift    = report.get('modal_shift', {})
    hotspots = report.get('emissions_hotspots', {})
    elec     = report.get('electrification', [])

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Agents in transit deserts",
        f"{deserts.get('pct_desert', 0):.1f}%",
        help="Origin points with poor walk access and infrequent service.",
    )
    col2.metric(
        "Near modal-shift threshold",
        f"{shift.get('near_tipping_pct', 0):.1f}%",
        help="Car users flippable with ≤5 min headway improvement.",
    )
    col3.metric(
        "Top route saving",
        f"{elec[0].get('savings_tco2_yr', 0):.0f} tCO₂/yr" if elec else "—",
        help="Annual CO₂ saving from electrifying the highest-impact diesel route.",
    )
    col4.metric(
        "Total route emissions",
        f"{hotspots.get('total_emissions_g', 0) / 1e6:.1f} tCO₂",
        help="Total agent emissions across all steps, projected onto the grid.",
    )


# ── Panel 1: Transit Desert Map ───────────────────────────────────────────────

def _render_transit_desert_panel(deserts: Dict) -> None:
    st.subheader("Transit desert map")

    summary = deserts.get('summary', {})
    n_desert = summary.get('desert_agents', 0)
    n_total  = summary.get('total_agents', 1)

    if n_total:
        st.caption(
            f"{n_desert} of {n_total} agent origins score above 0.65 "
            f"({summary.get('pct_desert', 0):.1f}%). "
            "Darker red = worse access."
        )

    heatmap_data = deserts.get('heatmap_data', [])

    if not heatmap_data or not _PDK:
        st.info("No heatmap data — run simulation with GTFS feed loaded.")
        return

    df = pd.DataFrame(heatmap_data)

    layer = pdk.Layer(
        'HeatmapLayer',
        data         = df,
        get_position = '[lon, lat]',
        get_weight   = 'score',
        radiusPixels = 40,
        intensity    = 1,
        threshold    = 0.05,
        color_range  = [
            [65, 182, 196],    # cyan — good access
            [127, 205, 187],
            [199, 233, 180],
            [255, 237, 160],
            [253, 141, 60],
            [240, 59, 32],     # red — transit desert
        ],
    )

    _lon = df['lon'].mean()
    _lat = df['lat'].mean()

    deck = pdk.Deck(
        layers=[layer],
        initial_view_state=pdk.ViewState(
            longitude=_lon, latitude=_lat, zoom=10, pitch=0
        ),
        map_style='light',
    )
    st.pydeck_chart(deck)


# ── Panel 2: Electrification Opportunity ─────────────────────────────────────

def _render_electrification_panel(electrification: list) -> None:
    st.subheader("Electrification opportunity ranking")

    if not electrification:
        st.info("No diesel/hybrid routes found. Either the feed has no combustion routes "
                "or GTFS data was not loaded.")
        return

    top = electrification[:12]  # top 12 for readability

    labels   = [f"{r['short_name']} ({r['mode'][:3]})" for r in top]
    savings  = [r['savings_tco2_yr'] for r in top]
    feasible = [r['feasible_bev'] for r in top]
    colors   = ['#22c55e' if f else '#f59e0b' for f in feasible]

    if not _PLOTLY:
        st.dataframe(pd.DataFrame(top)[
            ['short_name', 'mode', 'total_km', 'avg_emissions_g_km',
             'savings_tco2_yr', 'feasible_bev', 'replacement_mode']
        ])
        return

    fig = go.Figure(go.Bar(
        x            = savings,
        y            = labels,
        orientation  = 'h',
        marker_color = colors,
        text         = [f"{s:.0f} tCO₂" for s in savings],
        textposition = 'outside',
        hovertemplate = (
            "<b>%{y}</b><br>"
            "Saving: %{x:.0f} tCO₂/yr<br>"
            "<extra></extra>"
        ),
    ))

    fig.update_layout(
        xaxis_title  = "Estimated CO₂ saving (tCO₂/yr)",
        yaxis        = dict(autorange='reversed'),
        height       = max(250, len(top) * 28 + 80),
        margin       = dict(l=10, r=80, t=20, b=40),
        showlegend   = False,
    )

    # Legend annotation
    fig.add_annotation(
        text="Green = BEV-feasible  Orange = needs depot charging",
        xref="paper", yref="paper", x=0, y=-0.12,
        showarrow=False, font_size=11,
    )

    st.plotly_chart(fig, use_container_width=True)

    feasible_n = sum(1 for r in electrification if r['feasible_bev'])
    st.caption(
        f"{feasible_n} of {len(electrification)} diesel routes are BEV-feasible "
        f"at current range. Total saving if all electrified: "
        f"{sum(r['savings_tco2_yr'] for r in electrification):.0f} tCO₂/yr."
    )


# ── Panel 3: Modal Shift Threshold ────────────────────────────────────────────

def _render_modal_shift_panel(modal_shift: Dict) -> None:
    st.subheader("Modal shift threshold")

    flip_counts = modal_shift.get('flip_counts', {})
    n_road      = modal_shift.get('total_road', 0)
    car_ratio   = modal_shift.get('car_ratio', 1.0)

    if not n_road:
        st.info("No car/road-mode agents found in this simulation run.")
        return

    bands  = ['0-5min', '5-15min', '15-30min', '>30min', 'never']
    counts = [flip_counts.get(b, 0) for b in bands]
    pcts   = [c / n_road * 100 for c in counts]

    band_labels = [
        'Already competitive',
        'Small improvement (5-15 min)',
        'Significant improvement (15-30 min)',
        'Major investment needed (>30 min)',
        'No transit within range',
    ]
    bar_colors = ['#22c55e', '#86efac', '#fbbf24', '#f97316', '#ef4444']

    if not _PLOTLY:
        df = pd.DataFrame({'Band': band_labels, 'Agents': counts, 'Pct': pcts})
        st.dataframe(df)
    else:
        fig = go.Figure(go.Bar(
            x            = pcts,
            y            = band_labels,
            orientation  = 'h',
            marker_color = bar_colors,
            text         = [f"{p:.1f}%" for p in pcts],
            textposition = 'outside',
            hovertemplate="<b>%{y}</b><br>%{x:.1f}% of car users<extra></extra>",
        ))
        fig.update_layout(
            xaxis_title = "% of car-mode agents",
            yaxis       = dict(autorange='reversed'),
            height      = 260,
            margin      = dict(l=10, r=60, t=20, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)

    near_pct = modal_shift.get('near_tipping_pct', 0)

    if car_ratio < 1.0:
        st.caption(
            f"Average car/transit cost ratio: **{car_ratio:.2f}** — car is still cheaper. "
            f"A carbon price or fuel duty increase would close the gap for "
            f"{near_pct:.1f}% of agents with ≤5 min headway improvement."
        )
    else:
        st.caption(
            f"Average car/transit cost ratio: **{car_ratio:.2f}** — transit is already "
            f"cost-competitive on average. {near_pct:.1f}% of agents are near the "
            "switching threshold."
        )

    # Policy levers
    levers = modal_shift.get('policy_levers', {})
    if levers:
        with st.expander("Policy lever recommendations"):
            for lever, text in levers.items():
                st.markdown(f"**{lever.replace('_', ' ').title()}:** {text}")


# ── Panel 4: Emissions Hotspot Map ───────────────────────────────────────────

def _render_emissions_hotspot_panel(hotspots: Dict) -> None:
    st.subheader("Emissions hotspot map")

    total_g      = hotspots.get('total_emissions_g', 0)
    grid_summary = hotspots.get('grid_summary', {})
    hotspot_list = hotspots.get('hotspots', [])

    st.caption(
        f"{grid_summary.get('cells_with_emissions', 0)} active 500m grid cells. "
        f"Total: {total_g / 1e6:.2f} tCO₂. "
        f"Peak cell: {grid_summary.get('max_cell_g', 0):.0f} g."
    )

    if not hotspot_list or not _PDK:
        st.info("No hotspot data — run simulation with GTFS feed loaded.")
        return

    df = pd.DataFrame([
        {
            'lon':        h['center'][0],
            'lat':        h['center'][1],
            'emissions':  h['total_emissions_g'],
            'top_mode':   h['top_mode'],
            'agents':     h['agent_count'],
            'tooltip':    (
                f"<b>{h['top_mode']}</b><br>"
                f"Emissions: {h['total_emissions_g']:.0f} g<br>"
                f"Agents: {h['agent_count']}"
            ),
        }
        for h in hotspot_list
    ])

    max_emit = df['emissions'].max() or 1.0
    df['weight'] = df['emissions'] / max_emit

    layer = pdk.Layer(
        'HeatmapLayer',
        data         = df,
        get_position = '[lon, lat]',
        get_weight   = 'weight',
        radiusPixels = 45,
        intensity    = 1.2,
        threshold    = 0.02,
        color_range  = [
            [254, 235, 226],
            [252, 187, 161],
            [252, 141, 89],
            [239, 101, 72],
            [215, 48, 31],
            [153, 0, 13],
        ],
    )

    deck = pdk.Deck(
        layers=[layer],
        initial_view_state=pdk.ViewState(
            longitude=df['lon'].mean(),
            latitude=df['lat'].mean(),
            zoom=10, pitch=0,
        ),
        map_style='light',
        tooltip={'html': '{tooltip}'},
    )
    st.pydeck_chart(deck)

    # Mode breakdown table
    if _PLOTLY and len(hotspot_list) > 0:
        mode_totals: Dict[str, float] = {}
        for h in hotspot_list:
            for mode, emit in h.get('mode_breakdown', {}).items():
                mode_totals[mode] = mode_totals.get(mode, 0) + emit

        if mode_totals:
            sorted_modes = sorted(mode_totals.items(), key=lambda x: x[1], reverse=True)
            modes   = [m for m, _ in sorted_modes[:8]]
            emit_mt = [e / 1e6 for _, e in sorted_modes[:8]]
            colors  = [_MODE_COLORS.get(m, '#888888') for m in modes]

            fig = go.Figure(go.Bar(
                x=modes, y=emit_mt,
                marker_color=colors,
                text=[f"{v:.3f}" for v in emit_mt],
                textposition='outside',
            ))
            fig.update_layout(
                yaxis_title="tCO₂",
                height=200,
                margin=dict(l=10, r=10, t=10, b=40),
            )
            st.plotly_chart(fig, use_container_width=True)


# ── Policy levers summary ─────────────────────────────────────────────────────

def _render_policy_levers(report: Dict) -> None:
    """Consolidate policy recommendations from all four analytics panels."""
    st.subheader("Policy synthesis")

    deserts   = report.get('transit_deserts', {}).get('summary', {})
    shift     = report.get('modal_shift', {})
    elec_list = report.get('electrification', [])

    pct_desert = deserts.get('pct_desert', 0)
    near_pct   = shift.get('near_tipping_pct', 0)
    car_ratio  = shift.get('car_ratio', 1.0)
    top_elec   = elec_list[0] if elec_list else {}

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("**Accessibility**")
        if pct_desert > 30:
            st.error(
                f"{pct_desert:.0f}% of agents are in transit deserts. "
                "New stop placement or demand-responsive transport needed."
            )
        elif pct_desert > 15:
            st.warning(
                f"{pct_desert:.0f}% of agents lack good transit access. "
                "Consider extending existing routes to uncovered origins."
            )
        else:
            st.success(
                f"Only {pct_desert:.0f}% of agents in transit deserts. "
                "Network coverage is relatively good."
            )

    with col2:
        st.markdown("**Frequency investment**")
        if near_pct > 25:
            st.success(
                f"{near_pct:.0f}% of car users are within 5 min of switching. "
                "Targeted frequency increases would produce measurable modal shift."
            )
        elif near_pct > 10:
            st.warning(
                f"{near_pct:.0f}% of car users near tipping. "
                "Frequency improvements combined with integrated fares recommended."
            )
        else:
            st.info(
                f"Only {near_pct:.0f}% near tipping. Modal shift requires structural "
                "changes beyond frequency — consider congestion pricing or Park & Ride."
            )
        if car_ratio < 0.8:
            st.error(
                f"Car/transit cost ratio {car_ratio:.2f} — transit is significantly "
                "cheaper but agents are not switching. Habit/reliability barriers likely."
            )

    with col3:
        st.markdown("**Electrification priority**")
        if top_elec:
            feasible_count = sum(1 for r in elec_list if r.get('feasible_bev'))
            total_saving   = sum(r.get('savings_tco2_yr', 0) for r in elec_list)
            st.info(
                f"Route **{top_elec.get('short_name', '?')}** is highest-impact: "
                f"{top_elec.get('savings_tco2_yr', 0):.0f} tCO₂/yr. "
                f"{feasible_count} of {len(elec_list)} routes are BEV-feasible. "
                f"Full fleet: {total_saving:.0f} tCO₂/yr total saving."
            )
        else:
            st.success("All routes appear to be zero-emission already.")


# ── Raw data export ───────────────────────────────────────────────────────────

def _render_raw_export(report: Dict) -> None:
    import json

    st.markdown("Download analytics results as JSON for further analysis.")

    elec = report.get('electrification', [])
    shift_detail = report.get('modal_shift', {}).get('agent_detail', [])
    desert_scores = report.get('transit_deserts', {}).get('scores', {})

    col1, col2, col3 = st.columns(3)

    with col1:
        if elec:
            st.download_button(
                "Download electrification ranking",
                data=json.dumps(elec, indent=2),
                file_name="gtfs_electrification.json",
                mime="application/json",
            )

    with col2:
        if shift_detail:
            st.download_button(
                "Download modal shift detail",
                data=json.dumps(shift_detail, indent=2),
                file_name="gtfs_modal_shift.json",
                mime="application/json",
            )

    with col3:
        if desert_scores:
            export = [{'agent_id': k, 'desert_score': v}
                      for k, v in desert_scores.items()]
            st.download_button(
                "Download transit desert scores",
                data=json.dumps(export, indent=2),
                file_name="gtfs_transit_deserts.json",
                mime="application/json",
            )


# ── Setup guide (no GTFS data) ────────────────────────────────────────────────

def _render_setup_guide() -> None:
    st.info(
        "No GTFS transit data was loaded for this simulation run. "
        "Add a GTFS feed to unlock transit analytics."
    )

    st.markdown("""
### How to enable GTFS analytics

1. **Download a GTFS feed** for your study region:
   - Scotland/UK: [Traveline National Dataset](https://www.travelinedata.org.uk)
   - ScotRail: [Rail Delivery Group GTFS](https://raildeliverygroup.com/gtfs)
   - Bus Open Data Service: [BODS](https://data.bus-data.dft.gov.uk)
   - Edinburgh trams: check Lothian Buses open data portal

2. **Set the feed path** in your simulation config or sidebar:
   ```python
   config.gtfs_feed_path    = "/path/to/gtfs.zip"
   config.gtfs_service_date = "20250401"   # optional: filter to one day
   config.run_gtfs_analytics = True
   ```

3. **Re-run the simulation.** The GTFS loader will parse stop schedules,
   compute headways, and build a transit graph. Bus, tram, and ferry agents
   will route via real service geometry instead of the drive-graph proxy.

4. **This tab** will then show transit desert scores, electrification
   opportunity rankings, modal shift thresholds, and emissions hotspots.
""")