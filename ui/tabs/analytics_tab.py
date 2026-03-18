"""
ui/tabs/analytics_tab.py

Analytics visualization tab.
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from typing import Dict, List


def render_analytics_tab(results, anim=None, current_data=None):
    """Render comprehensive analytics tab.
    
    Args:
        results: SimulationResults object
        anim: AnimationController (optional, not used in this tab)
        current_data: Current timestep data (optional, not used in this tab)
    """
    st.title("📊 Advanced Analytics")
    
    # Each sub-tab has its own guard — no top-level gate here so that
    # Policy ROI renders independently of journey_tracker availability.
    
    # Create tabs for different analytics sections
    tab1, tab2, tab3, tab4 = st.tabs([
        "🚶 Journey Insights",
        "📈 Adoption Dynamics",
        "💰 Policy ROI",
        "🌐 Network Efficiency"
    ])
    
    # =========================================================================
    # TAB 1: Journey Insights
    # =========================================================================
    with tab1:
        render_journey_insights(results)
    
    # =========================================================================
    # TAB 2: Adoption Dynamics
    # =========================================================================
    with tab2:
        render_adoption_dynamics(results)
    
    # =========================================================================
    # TAB 3: Policy ROI
    # =========================================================================
    with tab3:
        render_policy_roi(results)
    
    # =========================================================================
    # TAB 4: Network Efficiency
    # =========================================================================
    with tab4:
        render_network_efficiency(results)


def render_journey_insights(results):
    """Journey-level analysis."""
    st.header("🚶 Journey Analysis")
    
    journey_tracker = results.journey_tracker
    
    # Summary metrics
    summary = journey_tracker.get_summary_statistics()

    # Guard: journey_tracker returns empty dict when no journeys were recorded (0-agent run).
    # All downstream keys (completion_rate, total_distance_km etc.) are absent → KeyError crash.
    if not summary.get('total_journeys'):
        st.info("No journeys recorded. Run the simulation with agents to see journey analytics.")
        return

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Journeys", f"{summary.get('total_journeys', 0):,}")
    col2.metric("Completion Rate", f"{summary.get('completion_rate', 0):.1%}")
    col3.metric("Total Distance", f"{summary.get('total_distance_km', 0):.0f} km")
    col4.metric("Total Emissions", f"{summary.get('total_emissions_kg', 0):.0f} kg")
    
    # Journey time distribution
    st.subheader("⏱️ Journey Time Distribution")
    stats = journey_tracker.get_journey_statistics()
    
    if 'time' in stats:
        time_stats = stats['time']
        
        fig = go.Figure()
        fig.add_trace(go.Box(
            y=[time_stats['mean']] * 100,  # Placeholder
            name="Journey Times",
            boxmean='sd'
        ))
        fig.update_layout(
            title="Journey Time Distribution",
            yaxis_title="Time (minutes)",
            height=300
        )
        st.plotly_chart(fig, use_container_width=True)
        
        # Show statistics
        col1, col2, col3 = st.columns(3)
        col1.metric("Average", f"{time_stats['mean']:.1f} min")
        col2.metric("Median", f"{time_stats['median']:.1f} min")
        col3.metric("Max", f"{time_stats['max']:.1f} min")
    
    # Decision factors importance
    st.subheader("🎯 Decision Factors")
    factors = journey_tracker.analyze_decision_factors()
    
    if factors:
        df = pd.DataFrame([
            {'Factor': factor, 'Importance': importance}
            for factor, importance in factors.items()
        ])
        
        fig = px.bar(
            df,
            x='Factor',
            y='Importance',
            title="What Drives Mode Choice?",
            labels={'Importance': 'Importance (%)'}
        )
        st.plotly_chart(fig, use_container_width=True)
    
    # Weather impact
    st.subheader("🌤️ Weather Impact")
    weather_impact = journey_tracker.analyze_weather_impact()
    
    if weather_impact:
        # === PHASE 7.2: WEATHER IMPACT FROM JOURNEY TRACKER ===
        if hasattr(results, 'journey_tracker') and results.journey_tracker:
            weather_stats = results.journey_tracker.get_weather_impact_stats()
            
            # Display in existing weather impact chart
            weather_df = pd.DataFrame({
                'Condition': ['Clear', 'Cold', 'Rain', 'Ice'],
                'Journeys': [
                    weather_stats['clear'],
                    weather_stats['cold'],
                    weather_stats['rain'],
                    weather_stats['ice']
                ]
            })

            # Display the weather impact data
            fig = px.bar(
                weather_df,
                x='Condition',
                y='Journeys',
                title="Weather Impact on Journeys",
                labels={'Journeys': 'Number of Journeys'},
                color='Condition',
                color_discrete_map={
                    'Clear': '#90EE90',
                    'Cold': '#87CEEB',
                    'Rain': '#4682B4',
                    'Ice': '#B0C4DE'
                }
            )
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No weather impact data available yet.")

def render_adoption_dynamics(results):
    """Mode share evolution and tipping points."""
    st.header("📈 Mode Share Evolution")

    mode_share_analyzer = results.mode_share_analyzer

    # Guard: adoption_history is empty when agents=0. go.Figure loop is safe (no crash),
    # but the chart is a blank axes that confuses users. Return early with a clear message.
    if not results.adoption_history:
        st.info("No adoption history recorded. Run the simulation with agents to see mode share dynamics.")
        return
    
    # Plot adoption history
    fig = go.Figure()
    
    for mode, history in results.adoption_history.items():
        fig.add_trace(go.Scatter(
            x=list(range(len(history))),
            y=history,
            name=mode,
            mode='lines'
        ))
    
    # Mark tipping points - NO OVERLAPPING LABELS!
    if 'tipping_points' in results.analytics_summary:
        tipping_points = results.analytics_summary['tipping_points']
        
        # Add vertical lines WITHOUT annotations
        for tp in tipping_points:
            fig.add_vline(
                x=tp.step if hasattr(tp, 'step') else tp['step'],
                line_dash="dash",
                line_color="red",
                line_width=1.5
                # NO annotation_text - prevents overlap!
            )
        
        # Add ONE legend entry for all tipping points
        if tipping_points:
            fig.add_trace(go.Scatter(
                x=[tipping_points[0].step],  # Just for legend positioning
                y=[0],  # Bottom of chart
                mode='lines',
                line=dict(color='red', dash='dash', width=1.5),
                name=f'🎯 Tipping Points ({len(tipping_points)})',
                showlegend=True,
                hoverinfo='skip'
            ))
    
    fig.update_layout(
        title="Mode Adoption Over Time",
        xaxis_title="Step",
        yaxis_title="Adoption (%)",
        height=500,
        legend=dict(
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="left",
            x=1.02,
            bgcolor="rgba(255,255,255,0.9)",
            bordercolor="rgba(0,0,0,0.2)",
            borderwidth=1
        ),
        margin=dict(r=120)  # Extra space for legend
    )
    st.plotly_chart(fig, use_container_width=True)
    
    # Tipping point details
    if 'tipping_points' in results.analytics_summary:
        st.subheader("🎯 Detected Tipping Points")
        
        tipping_points = results.analytics_summary['tipping_points']
        
        if tipping_points:
            for i, tp in enumerate(tipping_points):
                # Support both TippingPoint objects and dicts
                _get = (lambda t, k: getattr(t, k)) if hasattr(tp, 'step') else (lambda t, k: t[k])
                with st.expander(f"Tipping Point {i+1}: {_get(tp,'mode')} at step {_get(tp,'step')}"):
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Adoption Before", f"{_get(tp,'adoption_before'):.1f}%")
                    col2.metric("Adoption After", f"{_get(tp,'adoption_after'):.1f}%")
                    col3.metric("Velocity", f"{_get(tp,'velocity'):.2f}% per step")
                    
                    st.write(f"**Trigger**: {_get(tp,'trigger')}")
                    sig = getattr(tp, 'statistical_significance', None) if hasattr(tp, 'step') else tp.get('statistical_significance')
                    if sig is not None:
                        st.write(f"**Significance**: p={sig:.3f}")
        else:
            st.info("No tipping points detected in this simulation.")
    
    # Transition flows (Sankey diagram)
    st.subheader("🔄 Mode Transitions")
    
    transitions = mode_share_analyzer.get_transition_flows()
    
    if transitions:
        # Filter out any remaining self-loops defensively
        transitions = [f for f in transitions if f['source'] != f['target']]
    
    if transitions:
        # Create Sankey diagram
        sources = []
        targets = []
        values = []
        labels = []
        
        unique_modes = set()
        for flow in transitions:
            unique_modes.add(flow['source'])
            unique_modes.add(flow['target'])
        
        mode_to_idx = {mode: i for i, mode in enumerate(sorted(unique_modes))}
        labels = sorted(unique_modes)
        
        for flow in transitions:
            sources.append(mode_to_idx[flow['source']])
            targets.append(mode_to_idx[flow['target']])
            values.append(flow['value'])
        
        # Create color palette - cycle Set3 so it never runs short (Set3 has only 12 colors)
        import plotly.colors as pc
        palette = pc.qualitative.Set3
        node_colors = [palette[i % len(palette)] for i in range(len(labels))]
        
        fig = go.Figure(data=[go.Sankey(
            node=dict(
                pad=20,
                thickness=25,
                line=dict(color="rgba(0,0,0,0.5)", width=1),
                label=labels,
                color=node_colors,
                hovertemplate='%{label}<br>%{value} total<extra></extra>'
                # NO x, y, align - let Plotly auto-position based on flows!
            ),
            link=dict(
                source=sources,
                target=targets,
                value=values,
                color="rgba(200,200,200,0.2)",  # Light gray
                hovertemplate='%{source.label} → %{target.label}<br>%{value} trips<extra></extra>',
                line=dict(color="rgba(0,0,0,0.1)", width=0.5)  # Subtle link borders
            ),
            arrangement='snap',  # Better auto-arrangement
            valueformat=".0f",
            valuesuffix=" trips",
            textfont=dict(
                size=14,
                family="Arial, sans-serif",
                color="rgba(0,0,0,0.9)"
            )
        )])
        
        fig.update_layout(
            title=dict(
                text="Mode Transition Flows",
                font=dict(size=18, color='black')
            ),
            height=700,  # Taller for better visibility
            font=dict(size=14, color='black', family="Arial, sans-serif"),
            plot_bgcolor='white',
            paper_bgcolor='white',
            margin=dict(l=40, r=40, t=60, b=40),
            hoverlabel=dict(
                bgcolor="white",
                font_size=13,
                font_family="Arial"
            ),
            dragmode=False  # Disable dragging - prevents rubber-banding
        )
        
        # Prevent interaction to avoid rubber-banding
        fig.update_xaxes(fixedrange=True)
        fig.update_yaxes(fixedrange=True)
        
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No mode transitions recorded yet. Transitions appear when agents switch modes during the simulation.")


def render_policy_roi(results):
    """Policy impact and ROI analysis."""
    st.header("💰 Policy Impact & ROI")
    
    policy_impact_analyzer = results.policy_impact_analyzer
    
    if not policy_impact_analyzer or not policy_impact_analyzer.impacts:
        st.info("No policy impacts recorded.")
        return
    
    # Summary metrics
    summary = policy_impact_analyzer.generate_summary_report()
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Policies Evaluated", summary['policies_evaluated'])
    col2.metric("Total Emissions Saved", f"{summary['total_emissions_saved']:.0f} kg")
    col3.metric("Total Agents Affected", summary['total_agents_affected'])
    
    # Policy comparison table
    st.subheader("📊 Policy Comparison")
    
    policy_data = []
    for policy in summary['policies']:
        row = {
            'Policy': policy['name'],
            'Agents Affected': policy['agents_affected'],
            'Emissions Saved (kg)': f"{policy['emissions_saved_kg']:.0f}",
            'Confidence': f"{policy['confidence']:.0%}",
        }
        
        if 'roi' in policy:
            roi = policy['roi']
            row['Cost'] = f"£{roi['cost']:,.0f}"
            row['BCR'] = f"{roi['benefit_cost_ratio']:.2f}x"
            row['Payback (days)'] = f"{roi['payback_days']:.0f}"
        
        policy_data.append(row)
    
    st.dataframe(pd.DataFrame(policy_data), use_container_width=True)
    
    # Individual policy details
    st.subheader("🔍 Policy Details")
    
    for policy in summary['policies']:
        with st.expander(f"Policy: {policy['name']}"):
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**Direct Impact**")
                st.write(f"- Agents affected: {policy['agents_affected']}")
                st.write(f"- Emissions saved: {policy['emissions_saved_kg']:.0f} kg")
                st.write(f"- Confidence: {policy['confidence']:.0%}")
            
            with col2:
                if 'roi' in policy:
                    roi = policy['roi']
                    st.write("**Financial Analysis**")
                    st.write(f"- Total cost: £{roi['cost']:,.0f}")
                    st.write(f"- Benefit-cost ratio: {roi['benefit_cost_ratio']:.2f}x")
                    st.write(f"- Payback period: {roi['payback_days']:.0f} days")
                    st.write(f"- NPV: £{roi['npv']:,.0f}")
            
            if policy.get('mode_switches'):
                st.write("**Mode Switches**")
                for mode, change in policy['mode_switches'].items():
                    st.write(f"- {mode}: {change:+.1f}%")


def render_network_efficiency(results):
    """Network and infrastructure efficiency."""
    st.header("🌐 Network Performance")
    
    network_efficiency = results.network_efficiency_tracker
    
    if not network_efficiency:
        st.info("Network efficiency tracking not enabled.")
        return
    
    # VKT Summary
    st.subheader("🚗 Vehicle Kilometers Traveled")

    vkt = network_efficiency.get_vkt_summary()

    # Guard: vkt dicts are empty when no agents moved (0-agent run or all agents stuck).
    # px.bar / px.pie raise ValueError("'Mode' is not a column in data_frame") on empty DataFrames.
    if not vkt.get('total_vkt_km'):
        st.info("No vehicle distance data recorded. Agents must complete journeys for VKT metrics.")
        return

    col1, col2 = st.columns(2)

    with col1:
        st.metric("Total VKT", f"{vkt['total_vkt_km']:,.0f} km")

        # By mode chart — guard against empty by_mode dict
        by_mode = vkt.get('by_mode', {})
        if by_mode:
            vkt_by_mode = pd.DataFrame([
                {'Mode': mode, 'VKT': km}
                for mode, km in by_mode.items()
            ])
            fig = px.bar(
                vkt_by_mode,
                x='Mode',
                y='VKT',
                title="VKT by Mode"
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No per-mode VKT data available.")

    with col2:
        # By vehicle type — guard against empty by_vehicle_type dict.
        # px.pie also crashes on empty DataFrame (no 'Type' column).
        by_vtype = vkt.get('by_vehicle_type', {})
        if by_vtype:
            vkt_by_type = pd.DataFrame([
                {'Type': vtype, 'VKT': km}
                for vtype, km in by_vtype.items()
            ])
            fig = px.pie(
                vkt_by_type,
                values='VKT',
                names='Type',
                title="VKT by Vehicle Type"
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No per-vehicle-type VKT data available.")
    
    # Bottlenecks
    st.subheader("🚧 Infrastructure Bottlenecks")
    
    if 'bottlenecks' in results.analytics_summary:
        bottlenecks = results.analytics_summary['bottlenecks']
        
        if bottlenecks:
            st.warning(f"⚠️ {len(bottlenecks)} bottlenecks identified")
            
            for i, bottleneck in enumerate(bottlenecks):
                with st.expander(f"Bottleneck {i+1}: {bottleneck.bottleneck_type}"):
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Severity", f"{bottleneck.severity:.0%}")
                    col2.metric("Affected Agents", bottleneck.affected_agents)
                    col3.metric("Congestion Factor", f"{bottleneck.congestion_factor:.1f}x")
                    
                    st.write(f"**Recommendation**: {bottleneck.recommendation}")
        else:
            st.success("✅ No significant bottlenecks detected")
    
    # Infrastructure utilization
    st.subheader("📊 Infrastructure Utilization")
    
    summary = network_efficiency.generate_summary_report()
    
    if 'infrastructure' in summary:
        infra = summary['infrastructure']
        
        col1, col2 = st.columns(2)
        col1.metric("Avg Charger Utilization", f"{infra['avg_charger_utilization']:.1%}")
        col2.metric("Avg Grid Utilization", f"{infra['avg_grid_utilization']:.1%}")
        
        col1.metric("Peak Grid Load", f"{infra['peak_grid_load']:.2f} MW")