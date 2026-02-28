"""
ui/tabs/shap_analysis_tab.py

SHAP Analysis Visualization Tab
Explains which features drive EV adoption using SHAP values
"""

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np


def render_shap_analysis_tab(results, anim, current_data):
    """
    Render SHAP analysis tab.
    
    Args:
        results: SimulationResults object
        anim: AnimationController
        current_data: Current timestep data
    """
    
    st.subheader("🔍 SHAP Feature Importance Analysis")
    st.caption("Understanding which factors drive EV adoption using explainable AI")
    
    # Check if SD data available
    if not hasattr(results, 'system_dynamics_history') or not results.system_dynamics_history:
        st.warning("""
        ⚠️ **System Dynamics data not available.**
        
        SHAP analysis requires System Dynamics to be enabled.
        """)
        return
    
    sd_history = results.system_dynamics_history
    
    if len(sd_history) < 10:
        st.warning(f"⚠️ Insufficient data: {len(sd_history)} timesteps (need 10+)")
        return
    
    # Check if SHAP module available
    try:
        from analytics.shap_analysis import run_shap_analysis_for_ui
    except ImportError:
        st.error("""
        ❌ **SHAP analysis module not found.**
        
        Please ensure `shap_analysis.py` is in `analytics/` directory.
        """)
        return
    
    # Run analysis (with caching)
    with st.spinner("🔄 Running SHAP analysis... This may take 10-30 seconds..."):
        analysis_results = run_shap_analysis_for_ui(sd_history)
    
    # Check for errors
    if not analysis_results.get('success', False):
        error_msg = analysis_results.get('error', 'Unknown error')
        
        if analysis_results.get('install_required', False):
            st.error(f"""
            ❌ **Missing Dependencies**
            
            {error_msg}
            
            **Installation:**
            ```bash
            pip install shap scikit-learn
            ```
            """)
        else:
            st.error(f"❌ Analysis failed: {error_msg}")
        return
    
    # Extract results
    shap_results = analysis_results['shap_results']
    viz_data = analysis_results['visualizations']
    summary = analysis_results['summary']
    
    # ==================================================================
    # SECTION 1: Overview & Summary
    # ==================================================================
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric(
            "Samples Analyzed",
            f"{analysis_results['n_samples']}",
            help="Number of timesteps analyzed"
        )
    
    with col2:
        st.metric(
            "Features",
            f"{analysis_results['n_features']}",
            help="Number of input features"
        )
    
    with col3:
        st.metric(
            "Base Prediction",
            f"{shap_results.base_value:.5f}",
            help="Expected flow rate (baseline)"
        )
    
    st.markdown("---")
    
    # ==================================================================
    # SECTION 2: Feature Importance Bar Chart
    # ==================================================================
    
    st.markdown("### 🏆 Feature Importance Ranking")
    st.caption("Which features have the largest impact on EV adoption flow?")
    
    importance_df = pd.DataFrame({
        'Feature': viz_data['importance']['features'],
        'Importance': viz_data['importance']['importance']
    })
    
    fig_importance = go.Figure()
    
    fig_importance.add_trace(go.Bar(
        y=importance_df['Feature'],
        x=importance_df['Importance'],
        orientation='h',
        marker=dict(
            color=importance_df['Importance'],
            colorscale='Viridis',
            showscale=True,
            colorbar=dict(title="Importance")
        ),
        text=[f"{val:.5f}" for val in importance_df['Importance']],
        textposition='outside'
    ))
    
    fig_importance.update_layout(
        title="Mean Absolute SHAP Value (Feature Importance)",
        xaxis_title="Mean |SHAP Value|",
        yaxis_title="Feature",
        height=400,
        showlegend=False
    )
    
    st.plotly_chart(fig_importance, use_container_width=True)
    
    # Top 3 features callout
    top_3 = shap_results.top_features[:3]
    st.info(f"""
    💡 **Top 3 Most Important Features:**
    1. **{top_3[0][0]}** (Importance: {top_3[0][1]:.5f})
    2. **{top_3[1][0]}** (Importance: {top_3[1][1]:.5f})
    3. **{top_3[2][0]}** (Importance: {top_3[2][1]:.5f})
    
    These features have the strongest influence on EV adoption flow.
    """)
    
    st.markdown("---")
    
    # ==================================================================
    # SECTION 3: SHAP Values Over Time
    # ==================================================================
    
    st.markdown("### 📈 SHAP Values Over Time (Top 3 Features)")
    st.caption("How feature importance changes throughout the simulation")
    
    fig_timeseries = go.Figure()
    
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c']
    
    for idx, (feature_name, shap_vals) in enumerate(viz_data['timeseries']['features'].items()):
        fig_timeseries.add_trace(go.Scatter(
            x=viz_data['timeseries']['steps'],
            y=shap_vals,
            mode='lines',
            name=feature_name,
            line=dict(color=colors[idx % len(colors)], width=2)
        ))
    
    fig_timeseries.update_layout(
        title="SHAP Value Evolution (Top 3 Features)",
        xaxis_title="Timestep",
        yaxis_title="SHAP Value",
        height=400,
        hovermode='x unified'
    )
    
    st.plotly_chart(fig_timeseries, use_container_width=True)
    
    st.markdown("---")
    
    # ==================================================================
    # SECTION 4: Waterfall Plot (Final Timestep)
    # ==================================================================
    
    st.markdown("### 🌊 Waterfall Plot - Final Timestep Explanation")
    st.caption("How each feature contributes to the final prediction")
    
    waterfall_data = viz_data['waterfall']
    
    # Create waterfall chart
    fig_waterfall = create_waterfall_plot(
        features=waterfall_data['features'],
        shap_values=waterfall_data['shap_values'],
        base_value=waterfall_data['base_value'],
        prediction=waterfall_data['prediction']
    )
    
    st.plotly_chart(fig_waterfall, use_container_width=True)
    
    st.info(f"""
    📊 **Waterfall Interpretation:**
    - **Base Value**: {waterfall_data['base_value']:.5f} (expected flow without features)
    - **Final Prediction**: {waterfall_data['prediction']:.5f} (actual flow)
    - **Features** push the prediction up (positive SHAP) or down (negative SHAP)
    """)
    
    st.markdown("---")
    
    # ==================================================================
    # SECTION 5: Detailed Summary
    # ==================================================================
    
    with st.expander("📋 Detailed SHAP Analysis Summary", expanded=False):
        st.code(summary, language=None)
    
    # ==================================================================
    # SECTION 6: Feature Interaction Analysis
    # ==================================================================
    
    st.markdown("---")
    st.markdown("### 🔗 Feature Interaction Explorer")
    st.caption("Analyze how features interact to influence adoption")
    
    col1, col2 = st.columns(2)
    
    with col1:
        feature1 = st.selectbox(
            "Select Feature 1",
            options=shap_results.feature_names,
            index=0,
            key='shap_feature1'
        )
    
    with col2:
        feature2 = st.selectbox(
            "Select Feature 2",
            options=shap_results.feature_names,
            index=1 if len(shap_results.feature_names) > 1 else 0,
            key='shap_feature2'
        )
    
    if feature1 != feature2:
        try:
            from analytics.shap_analysis import analyze_feature_interactions
            
            interaction_data = analyze_feature_interactions(
                shap_results,
                feature1,
                feature2
            )
            
            # Create scatter plot
            fig_interaction = go.Figure()
            
            fig_interaction.add_trace(go.Scatter(
                x=interaction_data['feature1_values'],
                y=interaction_data['feature2_values'],
                mode='markers',
                marker=dict(
                    size=8,
                    color=interaction_data['feature1_shap'],
                    colorscale='RdBu',
                    showscale=True,
                    colorbar=dict(title=f"SHAP<br>{feature1}")
                ),
                text=[f"SHAP1: {s1:.5f}<br>SHAP2: {s2:.5f}" 
                      for s1, s2 in zip(interaction_data['feature1_shap'], 
                                        interaction_data['feature2_shap'])],
                hovertemplate="<b>%{text}</b><br>" +
                              f"{feature1}: %{{x:.5f}}<br>" +
                              f"{feature2}: %{{y:.5f}}<extra></extra>"
            ))
            
            fig_interaction.update_layout(
                title=f"Feature Interaction: {feature1} vs {feature2}",
                xaxis_title=feature1,
                yaxis_title=feature2,
                height=500
            )
            
            st.plotly_chart(fig_interaction, use_container_width=True)
            
            st.info(f"""
            📊 **SHAP Correlation**: {interaction_data['shap_correlation']:.3f}
            
            {'Strong positive' if interaction_data['shap_correlation'] > 0.5 else
             'Moderate positive' if interaction_data['shap_correlation'] > 0.2 else
             'Weak positive' if interaction_data['shap_correlation'] > 0 else
             'Weak negative' if interaction_data['shap_correlation'] > -0.2 else
             'Moderate negative' if interaction_data['shap_correlation'] > -0.5 else
             'Strong negative'} relationship between SHAP values.
            """)
            
        except Exception as e:
            st.error(f"Interaction analysis failed: {e}")
    else:
        st.warning("Please select different features for interaction analysis.")
    
    # ==================================================================
    # SECTION 7: Export Data
    # ==================================================================
    
    st.markdown("---")
    st.markdown("### 💾 Export SHAP Results")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Export feature importance CSV
        importance_csv = importance_df.to_csv(index=False)
        st.download_button(
            label="📊 Download Feature Importance (CSV)",
            data=importance_csv,
            file_name="shap_feature_importance.csv",
            mime="text/csv"
        )
    
    with col2:
        # Export full SHAP values
        shap_df = pd.DataFrame(
            shap_results.shap_values,
            columns=shap_results.feature_names
        )
        shap_csv = shap_df.to_csv(index=False)
        st.download_button(
            label="📈 Download Full SHAP Values (CSV)",
            data=shap_csv,
            file_name="shap_values_full.csv",
            mime="text/csv"
        )


def create_waterfall_plot(features, shap_values, base_value, prediction):
    """
    Create a waterfall plot showing feature contributions.
    
    Args:
        features: List of feature names
        shap_values: List of SHAP values
        base_value: Base prediction value
        prediction: Final prediction
    
    Returns:
        Plotly figure
    """
    
    # Sort by absolute SHAP value
    sorted_indices = np.argsort([abs(v) for v in shap_values])[::-1]
    top_n = min(10, len(features))  # Show top 10
    
    sorted_features = [features[i] for i in sorted_indices[:top_n]]
    sorted_shap = [shap_values[i] for i in sorted_indices[:top_n]]
    
    # Calculate cumulative values
    cumulative = [base_value]
    for val in sorted_shap:
        cumulative.append(cumulative[-1] + val)
    
    # Create waterfall
    fig = go.Figure()
    
    # Base value
    fig.add_trace(go.Bar(
        name='Base',
        x=['Base Value'],
        y=[base_value],
        marker_color='lightgray',
        text=[f"{base_value:.5f}"],
        textposition='outside'
    ))
    
    # Feature contributions
    colors = ['green' if v > 0 else 'red' for v in sorted_shap]
    
    for i, (feature, shap_val) in enumerate(zip(sorted_features, sorted_shap)):
        fig.add_trace(go.Bar(
            name=feature,
            x=[feature],
            y=[shap_val],
            base=cumulative[i],
            marker_color=colors[i],
            text=[f"{shap_val:+.5f}"],
            textposition='outside',
            showlegend=False
        ))
    
    # Final prediction
    fig.add_trace(go.Bar(
        name='Prediction',
        x=['Final'],
        y=[prediction],
        marker_color='blue',
        text=[f"{prediction:.5f}"],
        textposition='outside'
    ))
    
    fig.update_layout(
        title="Feature Contributions (Waterfall)",
        xaxis_title="Features",
        yaxis_title="Flow Rate",
        height=500,
        showlegend=False
    )
    
    return fig