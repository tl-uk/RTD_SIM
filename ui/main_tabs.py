"""
ui/main_tabs.py

Main visualization tabs: Map, charts, network, infrastructure, scenario report.
"""

import streamlit as st
import sys
from pathlib import Path

# Add parent directory to path
parent_dir = Path(__file__).resolve().parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from visualiser.visualization import (
    render_map,
    render_mode_adoption_chart,
    render_emissions_chart,
    render_infrastructure_metrics,
    render_cascade_chart,
    get_current_stats,
    get_mode_distribution,
    MODE_COLORS_HEX,
)


def render_main_tabs(results, anim, current_data):
    """
    Render main content area tabs.
    
    Args:
        results: SimulationResults object
        anim: AnimationController
        current_data: Current timestep data
    """
    agent_states = current_data['agent_states']
    metrics = current_data.get('metrics', {})
    
    # Build tab list
    tab_names = ["🗺️ Map", "📈 Mode Adoption", "🎯 Impact", "🌐 Network"]
    if results.infrastructure:
        tab_names.append("🔌 Infrastructure")
    if results.scenario_report:
        tab_names.append("📋 Scenario Report")
    
    tabs = st.tabs(tab_names)
    
    # Tab 0: Map
    with tabs[0]:
        _render_map_tab(results, anim, agent_states, metrics)
    
    # Tab 1: Mode Adoption
    with tabs[1]:
        _render_mode_adoption_tab(results, anim, agent_states)
    
    # Tab 2: Impact
    with tabs[2]:
        _render_impact_tab(results)
    
    # Tab 3: Network
    with tabs[3]:
        _render_network_tab(results)
    
    # Tab 4: Infrastructure (conditional)
    if results.infrastructure:
        with tabs[4]:
            _render_infrastructure_tab(results)
    
    # Tab 5: Scenario Report (conditional)
    if results.scenario_report:
        tab_idx = 5 if results.infrastructure else 4
        with tabs[tab_idx]:
            _render_scenario_report_tab(results)


def _render_map_tab(results, anim, agent_states, metrics):
    """Render map visualization tab."""
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
    
    # Current stats
    stats = get_current_stats(agent_states, metrics)
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Arrivals", stats['arrivals'])
    col2.metric("Most Popular", stats['most_popular_mode'])
    col3.metric("Emissions", stats['total_emissions'])
    col4.metric("Agents w/ Routes", stats['agents_with_routes'])


def _render_mode_adoption_tab(results, anim, agent_states):
    """Render mode adoption charts."""
    st.subheader("📈 Mode Adoption Over Time")
    
    fig = render_mode_adoption_chart(results.adoption_history, anim.current_step)
    st.plotly_chart(fig, use_container_width=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**Peak Adoption:**")
        for mode in ['walk', 'bike', 'bus', 'car', 'ev', 'van_electric', 'van_diesel']:
            if mode in results.adoption_history and results.adoption_history[mode]:
                peak = max(results.adoption_history[mode]) * 100
                color = MODE_COLORS_HEX.get(mode, '#888888')
                st.markdown(
                    f"<span style='color:{color}'>●</span> {mode.capitalize()}: {peak:.1f}%", 
                    unsafe_allow_html=True
                )
    
    with col2:
        st.markdown("**Current Share:**")
        mode_dist = get_mode_distribution(agent_states)
        for _, row in mode_dist.iterrows():
            st.markdown(
                f"<span style='color:{row['color']}'>●</span> {row['mode']}: {row['percentage']:.1f}%", 
                unsafe_allow_html=True
            )


def _render_impact_tab(results):
    """Render environmental impact tab."""
    st.subheader("🎯 Environmental Impact")
    
    fig = render_emissions_chart(results.time_series)
    st.plotly_chart(fig, use_container_width=True)


def _render_network_tab(results):
    """Render social network analysis tab."""
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


def _render_infrastructure_tab(results):
    """Render infrastructure metrics tab."""
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


def _render_scenario_report_tab(results):
    """
    🆕 Phase 4.5B: Render scenario report tab.
    Shows what policies were applied and their expected outcomes.
    """
    st.subheader("📋 Applied Scenario Report")
    
    report = results.scenario_report
    
    # Scenario overview
    st.markdown(f"### {report['name']}")
    st.write(report['description'])
    
    st.markdown("---")
    
    # Applied policies
    st.markdown("### 🔧 Applied Policies")
    
    for policy in report['policies']:
        with st.expander(f"{policy['parameter']} ({policy['target']})", expanded=True):
            col1, col2 = st.columns([1, 2])
            
            with col1:
                st.write(f"**Value:** {policy['value']}")
                if policy.get('mode'):
                    st.write(f"**Mode:** {policy['mode']}")
            
            with col2:
                # Describe what this policy does
                description = _get_policy_description(policy)
                st.info(description)
    
    st.markdown("---")
    
    # Expected outcomes
    st.markdown("### 🎯 Expected Outcomes")
    
    for outcome, value in report['expected_outcomes'].items():
        col1, col2 = st.columns([2, 1])
        with col1:
            st.write(outcome.replace('_', ' ').title())
        with col2:
            st.metric("", f"{value:+.1%}")


def _get_policy_description(policy):
    """Get human-readable description of policy."""
    param = policy['parameter']
    value = policy['value']
    mode = policy.get('mode', 'all modes')
    
    descriptions = {
        'cost_reduction': f"Reduces cost for {mode} by {value}%",
        'cost_multiplier': f"Multiplies cost for {mode} by {value}x",
        'speed_multiplier': f"Multiplies speed for {mode} by {value}x",
        'add_chargers': f"Adds {value} charging stations",
        'charging_cost_multiplier': f"Multiplies charging costs by {value}x",
        'increase_capacity': f"Increases grid capacity by {value}x",
    }
    
    return descriptions.get(param, f"Modifies {param} to {value}")