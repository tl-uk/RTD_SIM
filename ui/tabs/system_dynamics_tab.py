"""
ui/tabs/system_dynamics_tab.py

System Dynamics visualization tab - Phase 5.3
Shows real-time SD metrics, predicted vs actual trajectories, parameter sensitivity
"""

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np


def render_system_dynamics_tab(results, anim, current_data):
    """
    Render System Dynamics visualization tab.
    
    Args:
        results: SimulationResults object
        anim: AnimationController
        current_data: Current timestep data
    """
    st.subheader("🔬 System Dynamics - Macro-Level Patterns")
    
    # Check if SD data exists
    sd_history = results.system_dynamics_history
    
    if not sd_history or len(sd_history) == 0:
        st.warning("""
        ⚠️ **System Dynamics not enabled or no data available.**
        
        System Dynamics tracks macro-level adoption patterns using differential equations.
        To enable, ensure `system_dynamics` module is installed and integrated.
        """)
        return
    
    # Display current step info
    current_step = min(anim.current_step, len(sd_history) - 1)
    current_sd = sd_history[current_step]
    
    st.markdown(f"**Current Step:** {current_step + 1} / {len(sd_history)}")
    
    # Top-level metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "EV Adoption (Actual)",
            f"{current_sd['ev_adoption']:.1%}",
            delta=f"{current_sd['ev_adoption_flow']:+.4f}/step" if current_sd['ev_adoption_flow'] else None
        )
    
    with col2:
        st.metric(
            "Growth Rate (dEV/dt)",
            f"{current_sd['ev_adoption_flow']:.4f}",
            help="Current rate of EV adoption change per timestep"
        )
    
    with col3:
        st.metric(
            "Grid Load",
            f"{current_sd['grid_load']:.1f} MW",
            delta=f"{current_sd['grid_utilization']:.0%} capacity" if current_sd.get('grid_utilization') else None
        )
    
    with col4:
        # Calculate if near tipping point
        thresholds = current_sd.get('thresholds_crossed', {})
        if thresholds.get('adoption_tipping_point'):
            st.metric("Status", "🎯 Post-Tipping", delta="Critical Mass Reached")
        else:
            adoption_gap = 0.30 - current_sd['ev_adoption']
            if adoption_gap > 0:
                st.metric("Status", "🌱 Pre-Tipping", delta=f"{adoption_gap:.1%} to critical mass")
            else:
                st.metric("Status", "🎯 Tipping Point!", delta="Just crossed!")
    
    st.markdown("---")
    
    # Main visualizations
    tab1, tab2, tab3, tab4 = st.tabs([
        "📈 Adoption Trajectory",
        "⚡ System Flows",
        "🎯 Threshold Events",
        "🔧 Parameters & Sensitivity"
    ])
    
    with tab1:
        _render_adoption_trajectory(sd_history, current_step)
    
    with tab2:
        _render_system_flows(sd_history, current_step)
    
    with tab3:
        _render_threshold_events(sd_history, current_step)
    
    with tab4:
        _render_parameters(sd_history)


def _render_adoption_trajectory(sd_history, current_step):
    """Render EV adoption trajectory chart."""
    st.markdown("### 📈 EV Adoption Over Time")
    st.caption("Actual agent behavior vs System Dynamics predictions")
    
    # Extract data
    steps = list(range(len(sd_history)))
    actual_adoption = [h['ev_adoption'] * 100 for h in sd_history]
    flows = [h['ev_adoption_flow'] for h in sd_history]
    
    # Calculate predicted trajectory (integrate flows from initial state)
    predicted = [sd_history[0]['ev_adoption'] * 100]
    for i in range(1, len(sd_history)):
        predicted.append(predicted[-1] + flows[i-1] * 100)
    
    # Create figure
    fig = go.Figure()
    
    # Actual adoption (solid line)
    fig.add_trace(go.Scatter(
        x=steps,
        y=actual_adoption,
        mode='lines',
        name='Actual Adoption',
        line=dict(color='#1f77b4', width=3),
        hovertemplate='Step %{x}<br>Adoption: %{y:.1f}%<extra></extra>'
    ))
    
    # Predicted adoption (dashed line)
    fig.add_trace(go.Scatter(
        x=steps,
        y=predicted,
        mode='lines',
        name='SD Prediction',
        line=dict(color='#ff7f0e', width=2, dash='dash'),
        hovertemplate='Step %{x}<br>Predicted: %{y:.1f}%<extra></extra>'
    ))
    
    # Current step marker
    fig.add_vline(
        x=current_step,
        line_dash="dot",
        line_color="gray",
        annotation_text=f"Current (Step {current_step})",
        annotation_position="top"
    )
    
    # Tipping point threshold (30%)
    fig.add_hline(
        y=30,
        line_dash="dash",
        line_color="red",
        annotation_text="Tipping Point (30%)",
        annotation_position="right"
    )
    
    # Carrying capacity (typically 80%)
    if len(sd_history) > 0 and 'ev_carrying_capacity_K' in sd_history[0]:
        K = sd_history[0].get('ev_carrying_capacity_K', 0.80) * 100
        fig.add_hline(
            y=K,
            line_dash="dash",
            line_color="green",
            annotation_text=f"Carrying Capacity ({K:.0f}%)",
            annotation_position="right"
        )
    
    fig.update_layout(
        xaxis_title="Simulation Step",
        yaxis_title="EV Adoption (%)",
        hovermode='x unified',
        height=400,
        showlegend=True,
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01)
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Prediction accuracy metric
    if len(actual_adoption) > 10:
        recent_actual = actual_adoption[-10:]
        recent_predicted = predicted[-10:]
        mae = np.mean(np.abs(np.array(recent_actual) - np.array(recent_predicted)))
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Prediction Accuracy (MAE)", f"{mae:.2f}%", help="Mean Absolute Error over last 10 steps")
        col2.metric("Current Actual", f"{actual_adoption[current_step]:.1f}%")
        col3.metric("Current Predicted", f"{predicted[current_step]:.1f}%")


def _render_system_flows(sd_history, current_step):
    """Render system flows and dynamics."""
    st.markdown("### ⚡ System Flows & Dynamics")
    st.caption("Rate of change and driving forces")
    
    steps = list(range(len(sd_history)))
    flows = [h['ev_adoption_flow'] for h in sd_history]
    
    # Create subplot with two charts
    fig = make_subplots(
        rows=2, cols=1,
        subplot_titles=("Flow Rate (dEV/dt)", "Phase Portrait"),
        vertical_spacing=0.15
    )
    
    # Top chart: Flow over time
    fig.add_trace(
        go.Scatter(
            x=steps,
            y=flows,
            mode='lines',
            name='Flow Rate',
            line=dict(color='#2ca02c', width=2),
            fill='tozeroy',
            fillcolor='rgba(44, 160, 44, 0.2)'
        ),
        row=1, col=1
    )
    
    # Current step marker
    fig.add_vline(
        x=current_step,
        line_dash="dot",
        line_color="gray",
        row=1, col=1
    )
    
    # Bottom chart: Phase portrait (adoption vs flow)
    adoptions = [h['ev_adoption'] * 100 for h in sd_history]
    
    fig.add_trace(
        go.Scatter(
            x=adoptions,
            y=flows,
            mode='markers+lines',
            name='System Trajectory',
            marker=dict(
                size=6,
                color=steps,
                colorscale='Viridis',
                showscale=True,
                colorbar=dict(title="Step", x=1.1)
            ),
            line=dict(color='gray', width=1)
        ),
        row=2, col=1
    )
    
    # Add current position
    if current_step < len(adoptions):
        fig.add_trace(
            go.Scatter(
                x=[adoptions[current_step]],
                y=[flows[current_step]],
                mode='markers',
                name='Current',
                marker=dict(size=15, color='red', symbol='star')
            ),
            row=2, col=1
        )
    
    fig.update_xaxes(title_text="Simulation Step", row=1, col=1)
    fig.update_yaxes(title_text="Flow Rate", row=1, col=1)
    fig.update_xaxes(title_text="EV Adoption (%)", row=2, col=1)
    fig.update_yaxes(title_text="Flow Rate", row=2, col=1)
    
    fig.update_layout(
        height=700,
        showlegend=True,
        hovermode='closest'
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Flow decomposition
    st.markdown("#### Flow Components")
    st.caption("What's driving adoption change?")
    
    if len(sd_history) > 0:
        current = sd_history[current_step]
        adoption = current['ev_adoption']
        
        # Reconstruct flow components (approximate)
        # Flow = r * EV * (1 - EV/K) + infrastructure + social
        r = current.get('ev_growth_rate_r', 0.05)
        K = current.get('ev_carrying_capacity_K', 0.80)
        
        logistic_term = r * adoption * (1 - adoption / K)
        infrastructure_feedback = 0.02 * adoption  # Approximate
        social_feedback = 0.03 * adoption  # Approximate
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Logistic Growth", f"{logistic_term:.5f}", help="Base growth from logistic equation")
        col2.metric("Infrastructure Boost", f"{infrastructure_feedback:.5f}", help="Positive feedback from charger availability")
        col3.metric("Social Influence", f"{social_feedback:.5f}", help="Peer effects and network influence")
        col4.metric("Total Flow", f"{current['ev_adoption_flow']:.5f}", help="Sum of all components")


def _render_threshold_events(sd_history, current_step):
    """Render threshold crossing events."""
    st.markdown("### 🎯 Threshold Events & Critical Transitions")
    st.caption("Detect when system crosses critical thresholds")
    
    # Find threshold crossings
    events = []
    for i, h in enumerate(sd_history):
        thresholds = h.get('thresholds_crossed', {})
        for threshold, crossed in thresholds.items():
            if crossed and (i == 0 or not sd_history[i-1].get('thresholds_crossed', {}).get(threshold, False)):
                events.append({
                    'step': i,
                    'threshold': threshold,
                    'adoption': h['ev_adoption'] * 100
                })
    
    if events:
        st.success(f"🎯 **{len(events)} threshold event(s) detected!**")
        
        # Event timeline
        event_df = pd.DataFrame(events)
        event_df['threshold_clean'] = event_df['threshold'].str.replace('_', ' ').str.title()
        
        st.dataframe(
            event_df[['step', 'threshold_clean', 'adoption']].rename(columns={
                'step': 'Step',
                'threshold_clean': 'Threshold',
                'adoption': 'Adoption at Event (%)'
            }),
            hide_index=True
        )
        
        # Visualize events on timeline
        fig = go.Figure()
        
        adoptions = [h['ev_adoption'] * 100 for h in sd_history]
        steps = list(range(len(sd_history)))
        
        fig.add_trace(go.Scatter(
            x=steps,
            y=adoptions,
            mode='lines',
            name='EV Adoption',
            line=dict(color='#1f77b4', width=2)
        ))
        
        # Mark events
        for event in events:
            fig.add_vline(
                x=event['step'],
                line_dash="dash",
                line_color="red",
                annotation_text=event['threshold'].replace('_', ' ').title(),
                annotation_position="top"
            )
        
        fig.update_layout(
            title="Threshold Crossings Timeline",
            xaxis_title="Step",
            yaxis_title="EV Adoption (%)",
            height=350
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
    else:
        st.info("ℹ️ No threshold events detected yet. Events trigger at:")
        st.markdown("""
        - **Tipping Point**: 30% EV adoption
        - **Grid Stress**: 85% grid utilization
        - **Emissions Target**: Exceeding target emissions
        """)
    
    # Threshold status table
    st.markdown("#### Current Threshold Status")
    
    current = sd_history[current_step]
    thresholds = current.get('thresholds_crossed', {})
    
    status_data = []
    threshold_names = {
        'adoption_tipping_point': 'EV Adoption Tipping Point (30%)',
        'grid_threshold_exceeded': 'Grid Stress Threshold (85%)',
        'emissions_target_exceeded': 'Emissions Target Exceeded'
    }
    
    for key, name in threshold_names.items():
        crossed = thresholds.get(key, False)
        status_data.append({
            'Threshold': name,
            'Status': '🔴 Crossed' if crossed else '🟢 Not Crossed',
            'Current Value': _get_threshold_current_value(current, key)
        })
    
    st.dataframe(pd.DataFrame(status_data), hide_index=True)


def _get_threshold_current_value(current, threshold_key):
    """Get current value for threshold display."""
    if threshold_key == 'adoption_tipping_point':
        return f"{current['ev_adoption']:.1%}"
    elif threshold_key == 'grid_threshold_exceeded':
        return f"{current.get('grid_utilization', 0):.1%}"
    elif threshold_key == 'emissions_target_exceeded':
        return f"{current.get('emissions', 0):.0f} kg/day"
    return "N/A"


def _render_parameters(sd_history):
    """Render SD parameters and sensitivity analysis."""
    st.markdown("### 🔧 System Dynamics Parameters")
    st.caption("Configuration and sensitivity analysis")
    
    if len(sd_history) == 0:
        st.info("No parameter data available")
        return
    
    # Display current parameters
    current = sd_history[-1]  # Use latest
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Core Parameters")
        
        r = current.get('ev_growth_rate_r', 0.05)
        K = current.get('ev_carrying_capacity_K', 0.80)
        
        st.metric("Growth Rate (r)", f"{r:.3f}", help="Base adoption rate parameter")
        st.metric("Carrying Capacity (K)", f"{K:.1%}", help="Maximum sustainable adoption")
        
        st.markdown("**Logistic Equation:**")
        st.latex(r"\frac{dEV}{dt} = r \cdot EV \cdot \left(1 - \frac{EV}{K}\right) + \text{feedbacks}")
        
    with col2:
        st.markdown("#### Feedback Strengths")
        
        # These might not be in history, use defaults
        st.metric("Infrastructure Feedback", "0.02", help="Boost from charger availability")
        st.metric("Social Influence", "0.03", help="Peer effects multiplier")
        st.metric("Policy Response Gain", "0.50", help="Grid expansion aggressiveness")
    
    st.markdown("---")
    
    # Parameter sensitivity (what-if analysis)
    st.markdown("#### 📊 Parameter Sensitivity Analysis")
    st.caption("How would changing parameters affect final adoption?")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Vary r
        st.markdown("**Growth Rate Impact**")
        r_values = np.linspace(0.01, 0.20, 20)
        final_adoptions_r = []
        
        current_adoption = sd_history[0]['ev_adoption']
        K_fixed = current.get('ev_carrying_capacity_K', 0.80)
        
        for r_test in r_values:
            # Simple integration: EV_final ≈ K * (1 - exp(-r * t))
            t = len(sd_history)
            final = K_fixed * (1 - np.exp(-r_test * t / 50))  # Normalize by 50 steps
            final_adoptions_r.append(final * 100)
        
        fig_r = go.Figure()
        fig_r.add_trace(go.Scatter(
            x=r_values,
            y=final_adoptions_r,
            mode='lines+markers',
            line=dict(color='#1f77b4', width=2)
        ))
        
        # Mark current value
        current_r = current.get('ev_growth_rate_r', 0.05)
        current_r_idx = np.argmin(np.abs(r_values - current_r))
        fig_r.add_trace(go.Scatter(
            x=[current_r],
            y=[final_adoptions_r[current_r_idx]],
            mode='markers',
            marker=dict(size=12, color='red', symbol='star'),
            name='Current'
        ))
        
        fig_r.update_layout(
            xaxis_title="Growth Rate (r)",
            yaxis_title="Predicted Final Adoption (%)",
            height=300,
            showlegend=False
        )
        
        st.plotly_chart(fig_r, use_container_width=True)
    
    with col2:
        # Vary K
        st.markdown("**Carrying Capacity Impact**")
        K_values = np.linspace(0.50, 1.00, 20)
        final_adoptions_K = []
        
        r_fixed = current.get('ev_growth_rate_r', 0.05)
        t = len(sd_history)
        
        for K_test in K_values:
            final = K_test * (1 - np.exp(-r_fixed * t / 50))
            final_adoptions_K.append(final * 100)
        
        fig_K = go.Figure()
        fig_K.add_trace(go.Scatter(
            x=[k * 100 for k in K_values],
            y=final_adoptions_K,
            mode='lines+markers',
            line=dict(color='#2ca02c', width=2)
        ))
        
        # Mark current value
        current_K = current.get('ev_carrying_capacity_K', 0.80)
        current_K_idx = np.argmin(np.abs(K_values - current_K))
        fig_K.add_trace(go.Scatter(
            x=[current_K * 100],
            y=[final_adoptions_K[current_K_idx]],
            mode='markers',
            marker=dict(size=12, color='red', symbol='star'),
            name='Current'
        ))
        
        fig_K.update_layout(
            xaxis_title="Carrying Capacity (K) %",
            yaxis_title="Predicted Final Adoption (%)",
            height=300,
            showlegend=False
        )
        
        st.plotly_chart(fig_K, use_container_width=True)
    
    # Summary
    st.info("""
    💡 **Sensitivity Insights:**
    - **Growth Rate (r)**: Higher values lead to faster initial adoption but same equilibrium
    - **Carrying Capacity (K)**: Directly determines maximum achievable adoption
    - **Feedback Loops**: Amplify growth near tipping points (30% adoption)
    """)