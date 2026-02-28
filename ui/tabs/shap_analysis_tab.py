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
    
    # REVERSE order so most important features appear at TOP
    importance_df = importance_df.iloc[::-1]
    
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
        showlegend=False,
        margin=dict(r=150),  # Right margin for text labels
        xaxis=dict(
            range=[0, max(importance_df['Importance']) * 1.15]  # Extend x-axis by 15%
        )
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

    # ==================================================================
    # SHAP Dependence Plots
    # ==================================================================

    st.markdown("---")
    st.markdown("### 📊 SHAP Dependence Analysis")
    st.caption("How individual features affect predictions across their value range")

    # Let user select feature to analyze
    col1, col2 = st.columns([1, 1])

    with col1:
        selected_feature = st.selectbox(
            "Select Feature to Analyze",
            options=shap_results.feature_names,
            index=0,  # Default to most important
            key='dependence_feature',
            help="Shows how this feature's value affects its impact on predictions"
        )

    with col2:
        # Optional: select interaction feature
        interaction_options = ['auto'] + shap_results.feature_names
        selected_interaction = st.selectbox(
            "Color by Feature (Interaction)",
            options=interaction_options,
            index=0,  # Default to auto
            key='interaction_feature',
            help="Colors points by another feature to show interactions"
        )

    # Get indices
    feature_idx = shap_results.feature_names.index(selected_feature)

    if selected_interaction == 'auto':
        # Auto-detect best interaction feature (highest correlation with main feature's SHAP)
        correlations = []
        for i, fname in enumerate(shap_results.feature_names):
            if i != feature_idx:
                corr = np.corrcoef(
                    shap_results.shap_values[:, feature_idx],
                    shap_results.X[:, i]
                )[0, 1]
                correlations.append((i, fname, abs(corr)))
        
        if correlations:
            interaction_idx = max(correlations, key=lambda x: x[2])[0]
            interaction_name = shap_results.feature_names[interaction_idx]
        else:
            interaction_idx = None
            interaction_name = None
    else:
        interaction_idx = shap_results.feature_names.index(selected_interaction)
        interaction_name = selected_interaction

    # Create dependence plot
    fig_dependence = go.Figure()

    if interaction_idx is not None:
        # Color by interaction feature
        fig_dependence.add_trace(go.Scatter(
            x=shap_results.X[:, feature_idx],
            y=shap_results.shap_values[:, feature_idx],
            mode='markers',
            marker=dict(
                size=8,
                color=shap_results.X[:, interaction_idx],
                colorscale='RdYlBu_r',
                showscale=True,
                colorbar=dict(title=interaction_name),
                line=dict(width=0.5, color='white')
            ),
            text=[f"SHAP: {sv:.5f}<br>{interaction_name}: {iv:.5f}" 
                for sv, iv in zip(shap_results.shap_values[:, feature_idx],
                                shap_results.X[:, interaction_idx])],
            hovertemplate=f"<b>{selected_feature}: %{{x:.5f}}</b><br>" +
                        "%{text}<extra></extra>"
        ))
    else:
        # No interaction
        fig_dependence.add_trace(go.Scatter(
            x=shap_results.X[:, feature_idx],
            y=shap_results.shap_values[:, feature_idx],
            mode='markers',
            marker=dict(
                size=8,
                color='#1f77b4',
                line=dict(width=0.5, color='white')
            ),
            text=[f"SHAP: {sv:.5f}" for sv in shap_results.shap_values[:, feature_idx]],
            hovertemplate=f"<b>{selected_feature}: %{{x:.5f}}</b><br>" +
                        "%{text}<extra></extra>"
        ))

    # Add horizontal line at SHAP=0 (neutral)
    fig_dependence.add_hline(
        y=0,
        line_dash="dash",
        line_color="gray",
        annotation_text="Neutral (no effect)",
        annotation_position="right"
    )

    fig_dependence.update_layout(
        title=f"SHAP Dependence: {selected_feature}",
        xaxis_title=f"{selected_feature} Value",
        yaxis_title=f"SHAP Value (Impact on Prediction)",
        height=500,
        showlegend=False
    )

    st.plotly_chart(fig_dependence, use_container_width=True)

    # Interpretation guide
    with st.expander("📖 How to Read Dependence Plots", expanded=False):
        st.markdown(f"""
        **SHAP Dependence Plot** shows how **{selected_feature}** affects predictions:
        
        **X-axis**: Value of {selected_feature}
        - Left → Low values
        - Right → High values
        
        **Y-axis**: SHAP value (contribution to prediction)
        - **Positive** (above 0) → Feature **increases** flow prediction
        - **Negative** (below 0) → Feature **decreases** flow prediction
        - **Zero line** → Feature has no effect
        
        **Color** (if interaction enabled): {interaction_name if interaction_name else "None"}
        - Shows how another feature modifies the effect
        - **Red points**: High interaction feature value
        - **Blue points**: Low interaction feature value
        
        **Key Patterns to Look For:**
        
        1. **Linear relationship**: Straight line = proportional effect
        2. **Threshold effect**: Sharp change at specific value = tipping point
        3. **Saturation**: Flattening curve = diminishing returns
        4. **Interaction**: Color patterns = combined effects
        
        **Example Interpretations:**
        
        - **Upward slope**: Higher feature value → stronger positive impact
        - **Downward slope**: Higher feature value → stronger negative impact
        - **Horizontal**: Feature value doesn't matter (constant effect)
        - **U-shape**: Optimal value in middle
        - **Inverted U**: Extremes better than middle
        """)

    # Key insights for selected feature
    st.markdown("#### 💡 Key Insights")

    # Compute statistics
    feature_vals = shap_results.X[:, feature_idx]
    shap_vals = shap_results.shap_values[:, feature_idx]

    min_val, max_val = feature_vals.min(), feature_vals.max()
    avg_shap = shap_vals.mean()
    shap_range = shap_vals.max() - shap_vals.min()

    # Detect relationship type
    if shap_range < 0.00001:
        relationship = "Constant (no variation)"
    else:
        # Simple correlation to detect direction
        corr = np.corrcoef(feature_vals, shap_vals)[0, 1]
        if abs(corr) > 0.7:
            relationship = "Strong positive" if corr > 0 else "Strong negative"
        elif abs(corr) > 0.3:
            relationship = "Moderate positive" if corr > 0 else "Moderate negative"
        else:
            relationship = "Non-linear or weak"

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            "Relationship Type",
            relationship,
            help="How feature value correlates with SHAP value"
        )

    with col2:
        st.metric(
            "Average Impact",
            f"{avg_shap:.5f}",
            help="Mean SHAP value across all timesteps"
        )

    with col3:
        st.metric(
            "Impact Range",
            f"{shap_range:.5f}",
            help="Difference between max and min SHAP values"
        )

    # Specific insight based on feature
    if 'logistic' in selected_feature.lower():
        if avg_shap < -0.0001:
            st.warning(f"""
            ⚠️ **{selected_feature}** has **negative average impact**
            
            This indicates the system is **saturated** (EV adoption > carrying capacity).
            The logistic growth term is acting as a **brake** on further adoption.
            
            **Policy implication**: Increase carrying capacity (K) to allow continued growth.
            """)
        else:
            st.info(f"""
            ℹ️ **{selected_feature}** shows typical logistic growth behavior.
            Positive impact when EV < K, negative when EV > K.
            """)

    elif 'adoption' in selected_feature.lower():
        if corr > 0:
            st.success(f"""
            ✅ **{selected_feature}** has **positive impact**
            
            Higher adoption levels lead to stronger growth (momentum effect).
            This suggests positive feedback loops are active.
            """)
        else:
            st.info(f"""
            ℹ️ **{selected_feature}** relationship is complex.
            Effect varies depending on other system conditions.
            """)

    elif 'saturation' in selected_feature.lower():
        st.info(f"""
        📊 **{selected_feature}** shows capacity dynamics
        
        - Low values (EV << K): Strong positive growth potential
        - High values (EV ≈ K): Growth slows (approaching limit)
        - Values > 1: System over capacity
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