"""
ui/tabs/sensitivity_analysis_tab.py

Sensitivity Analysis Tab for System Dynamics
Shows Jacobians, elasticity, regime analysis, and SHAP readiness
"""

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np


def render_sensitivity_analysis_tab(results, anim, current_data):
    """
    Render sensitivity analysis and derivative visualization tab.
    
    Args:
        results: SimulationResults object
        anim: AnimationController
        current_data: Current timestep data
    """
    
    st.subheader("🧮 Sensitivity Analysis - Understanding System Behavior")
    
    # Check if SD data and derivative module available
    sd_history = results.system_dynamics_history
    
    if not sd_history or len(sd_history) == 0:
        st.warning("""
        ⚠️ **System Dynamics data not available.**
        
        Sensitivity analysis requires System Dynamics to be enabled.
        """)
        return
    
    try:
        from analytics.sd_derivative_analysis import (
            compute_sensitivity_metrics,
            analyze_mode_switches,
            prepare_shap_data
        )
    except ImportError:
        st.error("""
        ❌ **Derivative analysis module not found.**
        
        Please ensure `sd_derivative_analysis.py` is in `analytics/` directory.
        """)
        return
    
    # Get current state
    current_step = min(anim.current_step, len(sd_history) - 1)
    current = sd_history[current_step]
    
    # Extract parameters
    ev_adoption = current['ev_adoption']
    ev_flow = current.get('ev_adoption_flow', 0)
    r = current.get('ev_growth_rate_r', 0.05)
    K = current.get('ev_carrying_capacity_K', 0.80)
    infra_feedback = 0.02  # Default
    social_feedback = 0.03  # Default
    
    # Compute sensitivity metrics
    try:
        sensitivity = compute_sensitivity_metrics(
            ev_adoption=ev_adoption,
            r=r,
            K=K,
            infra_feedback=infra_feedback,
            social_feedback=social_feedback,
            current_flow=ev_flow,
            infrastructure_capacity=1.0
        )
    except Exception as e:
        st.error(f"Error computing sensitivity: {e}")
        return
    
    # ==================================================================
    # SECTION 1: Current State Overview
    # ==================================================================
    
    st.markdown("### 📊 Current System State")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "EV Adoption",
            f"{ev_adoption:.1%}",
            delta=f"{ev_flow*100:.3f}%/step",
            help="Current adoption level and rate of change"
        )
    
    with col2:
        regime = "FEEDBACK" if sensitivity.in_feedback_regime else "LOGISTIC"
        st.metric(
            "Regime",
            regime,
            delta="Network effects" if sensitivity.in_feedback_regime else "Exponential",
            help="Which dynamics dominate the system"
        )
    
    with col3:
        threshold_status = "NEAR" if sensitivity.near_threshold else "STABLE"
        st.metric(
            "Threshold Status",
            threshold_status,
            delta="Critical!" if sensitivity.near_threshold else "Normal",
            delta_color="inverse" if sensitivity.near_threshold else "normal",
            help="Proximity to discrete mode switch"
        )
    
    with col4:
        dominant = max(
            sensitivity.feature_contributions.items(),
            key=lambda x: abs(x[1])
        )[0] if sensitivity.feature_contributions else "Unknown"
        st.metric(
            "Dominant Driver",
            dominant.title(),
            help="Which feedback loop is strongest"
        )
    
    # ==================================================================
    # SECTION 2: Jacobian Matrix (Partial Derivatives)
    # ==================================================================
    
    st.markdown("---")
    st.markdown("### 🎯 Jacobian Matrix - Local Sensitivity")
    st.caption("How the system responds to small parameter changes")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        sign = "+" if sensitivity.dEV_dr >= 0 else ""
        st.metric(
            "∂(dEV/dt)/∂r",
            f"{sign}{sensitivity.dEV_dr:.6f}",
            help="Derivative w.r.t. growth rate"
        )
    
    with col2:
        sign = "+" if sensitivity.dEV_dK >= 0 else ""
        st.metric(
            "∂(dEV/dt)/∂K",
            f"{sign}{sensitivity.dEV_dK:.6f}",
            help="Derivative w.r.t. carrying capacity"
        )
    
    with col3:
        sign = "+" if sensitivity.dEV_dInfra >= 0 else ""
        st.metric(
            "∂(dEV/dt)/∂infra",
            f"{sign}{sensitivity.dEV_dInfra:.6f}",
            help="Derivative w.r.t. infrastructure feedback"
        )
    
    with col4:
        sign = "+" if sensitivity.dEV_dSocial >= 0 else ""
        st.metric(
            "∂(dEV/dt)/∂social",
            f"{sign}{sensitivity.dEV_dSocial:.6f}",
            help="Derivative w.r.t. social influence"
        )
    
    # Interpretation
    with st.expander("📖 Understanding Jacobians", expanded=False):
        st.markdown("""
        **Jacobian elements** show how sensitive the growth rate is to each parameter:
        
        - **Positive derivative**: Increasing parameter → faster growth
        - **Negative derivative**: Increasing parameter → slower growth (e.g., when EV > K)
        - **Large magnitude**: Parameter has strong leverage
        - **Near zero**: Parameter has little effect at current state
        
        **Example:** If ∂f/∂K = 0.05, then increasing K by 0.01 → flow increases by ~0.0005/step
        """)
    
    # ==================================================================
    # SECTION 3: Parameter Elasticity
    # ==================================================================
    
    st.markdown("---")
    st.markdown("### 📈 Parameter Elasticity - Normalized Sensitivity")
    st.caption("% change in output for 1% change in parameter")
    
    # Create elasticity comparison chart
    elasticity_data = {
        'Parameter': ['Growth Rate (r)', 'Carrying Capacity (K)', 
                     'Infrastructure', 'Social Influence'],
        'Elasticity': [
            sensitivity.elasticity_r,
            sensitivity.elasticity_K,
            sensitivity.elasticity_infra,
            sensitivity.elasticity_social
        ]
    }
    
    df_elasticity = pd.DataFrame(elasticity_data)
    
    fig = go.Figure()
    
    # Color code by magnitude
    colors = ['red' if e < 0 else 'green' if e > 0.5 else 'orange' 
              for e in df_elasticity['Elasticity']]
    
    fig.add_trace(go.Bar(
        x=df_elasticity['Parameter'],
        y=df_elasticity['Elasticity'],
        marker_color=colors,
        text=[f"{e:.3f}" for e in df_elasticity['Elasticity']],
        textposition='outside'
    ))
    
    fig.update_layout(
        title="Parameter Elasticity (% change for 1% parameter change)",
        xaxis_title="Parameter",
        yaxis_title="Elasticity",
        height=400,
        showlegend=False
    )
    
    # Add horizontal line at 1.0 (proportional response)
    fig.add_hline(y=1.0, line_dash="dash", line_color="gray",
                  annotation_text="Proportional (1:1)")
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Elasticity metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("ε(r)", f"{sensitivity.elasticity_r:.3f}")
    with col2:
        st.metric("ε(K)", f"{sensitivity.elasticity_K:.3f}")
    with col3:
        st.metric("ε(infra)", f"{sensitivity.elasticity_infra:.3f}")
    with col4:
        st.metric("ε(social)", f"{sensitivity.elasticity_social:.3f}")
    
    # Policy recommendation based on elasticity
    max_leverage_param = max(
        [('r', sensitivity.elasticity_r),
         ('K', sensitivity.elasticity_K),
         ('infra', sensitivity.elasticity_infra),
         ('social', sensitivity.elasticity_social)],
        key=lambda x: abs(x[1])
    )
    
    if abs(max_leverage_param[1]) > 0.8:
        st.success(f"""
        💡 **Policy Insight**: **{max_leverage_param[0].upper()}** has the highest leverage 
        (elasticity = {max_leverage_param[1]:.3f}). Focus interventions here for maximum impact!
        """)
    
    # ==================================================================
    # SECTION 4: Feature Contributions (SHAP-Ready)
    # ==================================================================
    
    st.markdown("---")
    st.markdown("### 🔍 Feature Contributions - What Drives Adoption?")
    st.caption("Decomposition of growth into contributing factors")
    
    # Get contributions
    contributions = sensitivity.feature_contributions
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Stacked bar chart of contributions
        fig = go.Figure()
        
        fig.add_trace(go.Bar(
            name='Logistic',
            x=['Current Flow'],
            y=[contributions.get('logistic', 0)],
            marker_color='#1f77b4'
        ))
        
        fig.add_trace(go.Bar(
            name='Infrastructure',
            x=['Current Flow'],
            y=[contributions.get('infrastructure', 0)],
            marker_color='#ff7f0e'
        ))
        
        fig.add_trace(go.Bar(
            name='Social',
            x=['Current Flow'],
            y=[contributions.get('social', 0)],
            marker_color='#2ca02c'
        ))
        
        fig.update_layout(
            barmode='stack',
            title="Flow Decomposition",
            yaxis_title="Contribution",
            height=300
        )
        
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.markdown("**Contribution Breakdown:**")
        total = contributions.get('total', 1)
        if total > 0:
            st.write(f"- Logistic: {contributions.get('logistic', 0)/total*100:.1f}%")
            st.write(f"- Infrastructure: {contributions.get('infrastructure', 0)/total*100:.1f}%")
            st.write(f"- Social: {contributions.get('social', 0)/total*100:.1f}%")
        
        dominant_feature = max(contributions.items(), key=lambda x: abs(x[1]))[0]
        st.info(f"🎯 **{dominant_feature.title()}** dominates")
    
    # ==================================================================
    # SECTION 5: Mode Switches & Regime Changes
    # ==================================================================
    
    st.markdown("---")
    st.markdown("### 🔄 Mode Switches - Discrete Transitions")
    st.caption("When the system crosses thresholds and changes behavior")
    
    # Detect mode switches
    try:
        switches = analyze_mode_switches(sd_history)
        
        if switches:
            st.success(f"✅ Detected {len(switches)} mode switch(es)")
            
            switch_data = []
            for sw in switches:
                switch_data.append({
                    'Step': sw['step'],
                    'Type': sw['type'].replace('_', ' ').title(),
                    'From': sw['from_mode'].replace('_', ' ').title(),
                    'To': sw['to_mode'].replace('_', ' ').title(),
                    'Adoption at Switch': f"{sw['adoption_at_switch']:.1%}"
                })
            
            st.dataframe(pd.DataFrame(switch_data), hide_index=True)
            
            # Visualize switches on timeline
            fig = go.Figure()
            
            adoptions = [h['ev_adoption'] for h in sd_history]
            steps = list(range(len(sd_history)))
            
            fig.add_trace(go.Scatter(
                x=steps,
                y=adoptions,
                mode='lines',
                name='EV Adoption',
                line=dict(color='#1f77b4', width=2)
            ))
            
            # Mark switches
            for sw in switches:
                fig.add_vline(
                    x=sw['step'],
                    line_dash="dash",
                    line_color="red",
                    annotation_text=sw['type'].replace('_', ' '),
                    annotation_position="top"
                )
            
            fig.update_layout(
                title="Mode Switches on Adoption Timeline",
                xaxis_title="Step",
                yaxis_title="EV Adoption",
                height=400
            )
            
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("ℹ️ No mode switches detected in this simulation")
    
    except Exception as e:
        st.warning(f"Could not analyze mode switches: {e}")
    


# Utility function for integration
def check_derivative_module_available():
    """Check if derivative analysis module is available."""
    try:
        from analytics.sd_derivative_analysis import compute_sensitivity_metrics
        return True
    except ImportError:
        return False