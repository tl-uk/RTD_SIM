"""
analytics/shap_analysis.py

SHAP (SHapley Additive exPlanations) Analysis for System Dynamics
Explains which features drive EV adoption flow at each timestep

Requirements:
    pip install shap scikit-learn

Usage:
    from analytics.shap_analysis import analyze_shap, create_shap_visualizations
    
    shap_results = analyze_shap(sd_history)
    figs = create_shap_visualizations(shap_results)
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class ShapResults:
    """Container for SHAP analysis results."""
    shap_values: np.ndarray  # SHAP values for each feature
    base_value: float  # Expected value (baseline)
    feature_names: List[str]  # Names of features
    X: np.ndarray  # Feature matrix
    y: np.ndarray  # Target values (flow rates)
    feature_importance: Dict[str, float]  # Absolute mean SHAP values
    top_features: List[Tuple[str, float]]  # Ranked features


def prepare_shap_features(sd_history: List[Dict]) -> Tuple[pd.DataFrame, np.ndarray, List[str]]:
    """
    Prepare feature matrix for SHAP analysis from SD history.
    
    Args:
        sd_history: List of SD history dicts
    
    Returns:
        X_df: Feature DataFrame with named columns
        y: Target values (flow rates)
        feature_names: List of feature names
    """
    
    if not sd_history or len(sd_history) < 10:
        raise ValueError("Insufficient data: need at least 10 timesteps")
    
    feature_data = []
    targets = []
    
    for entry in sd_history:
        features = {
            'ev_adoption': entry['ev_adoption'],
            'growth_rate_r': entry.get('ev_growth_rate_r', 0.05),
            'carrying_capacity_K': entry.get('ev_carrying_capacity_K', 0.80),
            'infrastructure_feedback': 0.02,  # Default
            'social_influence': 0.03,  # Default
            'infrastructure_capacity': 1.0,  # Normalized
            
            # Derived features
            'adoption_squared': entry['ev_adoption'] ** 2,
            'distance_to_capacity': entry.get('ev_carrying_capacity_K', 0.80) - entry['ev_adoption'],
            'logistic_term': entry.get('ev_growth_rate_r', 0.05) * entry['ev_adoption'] * 
                            (1 - entry['ev_adoption'] / entry.get('ev_carrying_capacity_K', 0.80)),
        }
        
        feature_data.append(features)
        targets.append(entry['ev_adoption_flow'])
    
    X_df = pd.DataFrame(feature_data)
    y = np.array(targets)
    feature_names = list(X_df.columns)
    
    return X_df, y, feature_names


def analyze_shap(
    sd_history: List[Dict],
    model_type: str = 'tree'
) -> ShapResults:
    """
    Perform SHAP analysis on system dynamics data.
    
    Args:
        sd_history: List of SD history dicts
        model_type: 'tree' (default) or 'linear'
    
    Returns:
        ShapResults object containing SHAP values and analysis
    """
    
    try:
        import shap
        from sklearn.ensemble import RandomForestRegressor
        from sklearn.linear_model import LinearRegression
    except ImportError:
        raise ImportError(
            "SHAP analysis requires: pip install shap scikit-learn"
        )
    
    # Prepare data
    X_df, y, feature_names = prepare_shap_features(sd_history)
    X = X_df.values
    
    logger.info(f"SHAP analysis: {len(X)} samples, {len(feature_names)} features")
    
    # Train model
    if model_type == 'tree':
        model = RandomForestRegressor(n_estimators=100, random_state=42, max_depth=5)
        model.fit(X, y)
        explainer = shap.TreeExplainer(model)
    else:  # linear
        model = LinearRegression()
        model.fit(X, y)
        explainer = shap.LinearExplainer(model, X)
    
    # Compute SHAP values
    shap_values = explainer.shap_values(X)
    
    # If TreeExplainer returns 2D array for regression, it's already correct
    if isinstance(shap_values, list):
        shap_values = shap_values[0]
    
    # Compute feature importance (mean absolute SHAP value)
    feature_importance = {}
    for i, name in enumerate(feature_names):
        feature_importance[name] = np.mean(np.abs(shap_values[:, i]))
    
    # Rank features
    top_features = sorted(
        feature_importance.items(),
        key=lambda x: x[1],
        reverse=True
    )
    
    # Base value (expected value)
    base_value = explainer.expected_value
    if isinstance(base_value, np.ndarray):
        base_value = float(base_value[0])
    
    return ShapResults(
        shap_values=shap_values,
        base_value=float(base_value),
        feature_names=feature_names,
        X=X,
        y=y,
        feature_importance=feature_importance,
        top_features=top_features
    )


def create_shap_visualizations(shap_results: ShapResults) -> Dict[str, any]:
    """
    Create visualization-ready data structures from SHAP results.
    
    Args:
        shap_results: ShapResults object
    
    Returns:
        Dictionary with plot data for different visualizations
    """
    
    # Feature importance bar chart data
    importance_data = {
        'features': [name for name, _ in shap_results.top_features],
        'importance': [val for _, val in shap_results.top_features]
    }
    
    # Waterfall data for a sample timestep (e.g., final step)
    final_step_idx = -1
    waterfall_data = {
        'features': shap_results.feature_names,
        'shap_values': shap_results.shap_values[final_step_idx, :].tolist(),
        'feature_values': shap_results.X[final_step_idx, :].tolist(),
        'base_value': shap_results.base_value,
        'prediction': float(shap_results.y[final_step_idx])
    }
    
    # Beeswarm plot data (for showing distribution of SHAP values)
    beeswarm_data = {}
    for i, name in enumerate(shap_results.feature_names):
        beeswarm_data[name] = {
            'shap_values': shap_results.shap_values[:, i].tolist(),
            'feature_values': shap_results.X[:, i].tolist()
        }
    
    # Time series data (SHAP values over time for top features)
    top_3_features = [name for name, _ in shap_results.top_features[:3]]
    timeseries_data = {
        'steps': list(range(len(shap_results.shap_values))),
        'features': {}
    }
    
    for i, name in enumerate(shap_results.feature_names):
        if name in top_3_features:
            timeseries_data['features'][name] = shap_results.shap_values[:, i].tolist()
    
    return {
        'importance': importance_data,
        'waterfall': waterfall_data,
        'beeswarm': beeswarm_data,
        'timeseries': timeseries_data
    }


def get_shap_summary(shap_results: ShapResults, top_n: int = 5) -> str:
    """
    Generate human-readable summary of SHAP analysis.
    
    Args:
        shap_results: ShapResults object
        top_n: Number of top features to include
    
    Returns:
        Summary text
    """
    
    summary = []
    summary.append("=" * 80)
    summary.append("SHAP FEATURE IMPORTANCE ANALYSIS")
    summary.append("=" * 80)
    summary.append("")
    
    summary.append(f"📊 Analyzed {len(shap_results.X)} timesteps")
    summary.append(f"🎯 Base prediction (expected flow): {shap_results.base_value:.5f}")
    summary.append("")
    
    summary.append(f"🏆 TOP {top_n} MOST IMPORTANT FEATURES:")
    summary.append("-" * 80)
    
    for rank, (feature, importance) in enumerate(shap_results.top_features[:top_n], 1):
        pct = (importance / sum(shap_results.feature_importance.values())) * 100
        summary.append(f"{rank}. {feature:30} | Importance: {importance:.5f} ({pct:.1f}%)")
    
    summary.append("")
    summary.append("💡 INTERPRETATION:")
    summary.append("-" * 80)
    
    top_feature = shap_results.top_features[0][0]
    summary.append(f"The most influential feature is **{top_feature}**.")
    summary.append(f"This feature has the largest impact on predicting EV adoption flow.")
    summary.append("")
    summary.append("Use SHAP values to understand:")
    summary.append("  • Which features drive adoption at different timesteps")
    summary.append("  • How feature importance changes over time")
    summary.append("  • Which interventions would have maximum impact")
    summary.append("")
    
    summary.append("=" * 80)
    
    return "\n".join(summary)


def analyze_feature_interactions(
    shap_results: ShapResults,
    feature1: str,
    feature2: str
) -> Dict[str, any]:
    """
    Analyze interaction effects between two features.
    
    Args:
        shap_results: ShapResults object
        feature1: Name of first feature
        feature2: Name of second feature
    
    Returns:
        Dictionary with interaction data
    """
    
    if feature1 not in shap_results.feature_names or feature2 not in shap_results.feature_names:
        raise ValueError(f"Features not found: {feature1}, {feature2}")
    
    idx1 = shap_results.feature_names.index(feature1)
    idx2 = shap_results.feature_names.index(feature2)
    
    # Compute correlation between SHAP values
    shap_corr = np.corrcoef(
        shap_results.shap_values[:, idx1],
        shap_results.shap_values[:, idx2]
    )[0, 1]
    
    # Scatter plot data
    scatter_data = {
        'feature1_name': feature1,
        'feature2_name': feature2,
        'feature1_values': shap_results.X[:, idx1].tolist(),
        'feature2_values': shap_results.X[:, idx2].tolist(),
        'feature1_shap': shap_results.shap_values[:, idx1].tolist(),
        'feature2_shap': shap_results.shap_values[:, idx2].tolist(),
        'shap_correlation': float(shap_corr)
    }
    
    return scatter_data


# Example integration function for Streamlit
def run_shap_analysis_for_ui(sd_history: List[Dict]) -> Dict[str, any]:
    """
    Convenience function to run complete SHAP analysis for UI display.
    
    Args:
        sd_history: SD history from simulation
    
    Returns:
        Dictionary with all analysis results and visualizations
    """
    
    if not sd_history or len(sd_history) < 10:
        return {
            'error': 'Insufficient data for SHAP analysis (need 10+ timesteps)',
            'success': False
        }
    
    try:
        # Run SHAP analysis
        shap_results = analyze_shap(sd_history, model_type='tree')
        
        # Create visualizations
        viz_data = create_shap_visualizations(shap_results)
        
        # Generate summary
        summary = get_shap_summary(shap_results, top_n=5)
        
        return {
            'success': True,
            'shap_results': shap_results,
            'visualizations': viz_data,
            'summary': summary,
            'n_samples': len(sd_history),
            'n_features': len(shap_results.feature_names)
        }
        
    except ImportError as e:
        return {
            'error': str(e),
            'success': False,
            'install_required': True
        }
    except Exception as e:
        logger.error(f"SHAP analysis failed: {e}")
        return {
            'error': f"Analysis failed: {str(e)}",
            'success': False
        }