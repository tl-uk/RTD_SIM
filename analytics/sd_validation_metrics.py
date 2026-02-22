"""
analytics/sd_validation_metrics.py

System Dynamics Validation Metrics
Comprehensive error analysis for SD predictions vs actual behavior
"""

import numpy as np
from typing import Dict, List, Tuple
from dataclasses import dataclass


@dataclass
class ValidationMetrics:
    """Container for SD validation metrics."""
    mae: float  # Mean Absolute Error
    rmse: float  # Root Mean Square Error
    mape: float  # Mean Absolute Percentage Error
    r_squared: float  # Coefficient of determination
    max_error: float  # Maximum single error
    
    # Error distribution
    q25_error: float  # 25th percentile error
    median_error: float  # 50th percentile error
    q75_error: float  # 75th percentile error
    
    # Diagnostic flags
    has_outliers: bool  # True if RMSE > 2*MAE
    consistent_bias: bool  # True if mean error != 0
    mean_bias: float  # Average signed error (over/under prediction)
    
    # Sample info
    n_samples: int
    prediction_quality: str  # 'excellent', 'good', 'fair', 'poor'


def compute_validation_metrics(
    actual: List[float],
    predicted: List[float],
    name: str = "adoption"
) -> ValidationMetrics:
    """
    Compute comprehensive validation metrics for SD predictions.
    
    Args:
        actual: Actual values from agent simulation
        predicted: Predicted values from SD model
        name: Variable name for logging
    
    Returns:
        ValidationMetrics object
    """
    
    actual_arr = np.array(actual)
    predicted_arr = np.array(predicted)
    
    # Basic validation
    if len(actual) != len(predicted):
        raise ValueError(f"Length mismatch: actual={len(actual)}, predicted={len(predicted)}")
    
    n = len(actual)
    
    # Compute errors
    errors = np.abs(actual_arr - predicted_arr)
    squared_errors = (actual_arr - predicted_arr) ** 2
    signed_errors = actual_arr - predicted_arr
    
    # Core metrics
    mae = np.mean(errors)
    rmse = np.sqrt(np.mean(squared_errors))
    
    # MAPE (handle zero values)
    with np.errstate(divide='ignore', invalid='ignore'):
        percentage_errors = np.abs((actual_arr - predicted_arr) / actual_arr) * 100
        percentage_errors = percentage_errors[~np.isnan(percentage_errors)]
        mape = np.mean(percentage_errors) if len(percentage_errors) > 0 else 0
    
    # R-squared
    ss_res = np.sum(squared_errors)
    ss_tot = np.sum((actual_arr - np.mean(actual_arr)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
    
    # Error distribution
    max_error = np.max(errors)
    q25_error = np.percentile(errors, 25)
    median_error = np.median(errors)
    q75_error = np.percentile(errors, 75)
    
    # Diagnostic checks
    has_outliers = rmse > (2 * mae)
    mean_bias = np.mean(signed_errors)
    consistent_bias = abs(mean_bias) > (0.1 * mae)  # Bias > 10% of MAE
    
    # Quality assessment
    if mae < 0.05 and rmse < 0.08:
        quality = "excellent"
    elif mae < 0.10 and rmse < 0.15:
        quality = "good"
    elif mae < 0.20 and rmse < 0.30:
        quality = "fair"
    else:
        quality = "poor"
    
    return ValidationMetrics(
        mae=mae,
        rmse=rmse,
        mape=mape,
        r_squared=r_squared,
        max_error=max_error,
        q25_error=q25_error,
        median_error=median_error,
        q75_error=q75_error,
        has_outliers=has_outliers,
        consistent_bias=consistent_bias,
        mean_bias=mean_bias,
        n_samples=n,
        prediction_quality=quality
    )


def analyze_temporal_drift(
    actual: List[float],
    predicted: List[float],
    window_size: int = 20
) -> Dict[str, List[float]]:
    """
    Analyze how prediction error changes over time.
    
    Args:
        actual: Actual values
        predicted: Predicted values
        window_size: Rolling window size
    
    Returns:
        Dict with temporal metrics
    """
    
    actual_arr = np.array(actual)
    predicted_arr = np.array(predicted)
    errors = np.abs(actual_arr - predicted_arr)
    
    # Rolling MAE
    rolling_mae = []
    for i in range(len(errors) - window_size + 1):
        window = errors[i:i + window_size]
        rolling_mae.append(np.mean(window))
    
    # Early vs late error
    n = len(errors)
    early_mae = np.mean(errors[:n//3])
    middle_mae = np.mean(errors[n//3:2*n//3])
    late_mae = np.mean(errors[2*n//3:])
    
    return {
        'rolling_mae': rolling_mae,
        'early_mae': early_mae,
        'middle_mae': middle_mae,
        'late_mae': late_mae,
        'error_trend': 'improving' if late_mae < early_mae else 'degrading'
    }


def generate_validation_report(
    metrics: ValidationMetrics,
    temporal: Dict[str, any],
    variable_name: str = "EV Adoption"
) -> str:
    """
    Generate human-readable validation report.
    
    Args:
        metrics: ValidationMetrics object
        temporal: Temporal drift analysis
        variable_name: Name of variable being validated
    
    Returns:
        Formatted report string
    """
    
    report = []
    report.append("=" * 80)
    report.append(f"SYSTEM DYNAMICS VALIDATION REPORT: {variable_name}")
    report.append("=" * 80)
    
    # Overall quality
    quality_emoji = {
        'excellent': '🎯',
        'good': '✅',
        'fair': '⚠️',
        'poor': '❌'
    }
    
    report.append(f"\nOverall Quality: {quality_emoji[metrics.prediction_quality]} {metrics.prediction_quality.upper()}")
    report.append(f"Samples: {metrics.n_samples}")
    report.append("")
    
    # Core metrics
    report.append("PREDICTION ACCURACY")
    report.append("-" * 80)
    report.append(f"MAE (Mean Absolute Error):       {metrics.mae:.4f} ({metrics.mae*100:.2f}%)")
    report.append(f"RMSE (Root Mean Square Error):   {metrics.rmse:.4f} ({metrics.rmse*100:.2f}%)")
    report.append(f"MAPE (Mean Abs % Error):         {metrics.mape:.2f}%")
    report.append(f"R² (Coefficient of Determination): {metrics.r_squared:.4f}")
    report.append("")
    
    # Error distribution
    report.append("ERROR DISTRIBUTION")
    report.append("-" * 80)
    report.append(f"Maximum Error:   {metrics.max_error:.4f} ({metrics.max_error*100:.2f}%)")
    report.append(f"75th Percentile: {metrics.q75_error:.4f}")
    report.append(f"Median Error:    {metrics.median_error:.4f}")
    report.append(f"25th Percentile: {metrics.q25_error:.4f}")
    report.append("")
    
    # Diagnostics
    report.append("DIAGNOSTIC FLAGS")
    report.append("-" * 80)
    
    if metrics.has_outliers:
        report.append(f"⚠️  OUTLIERS DETECTED: RMSE ({metrics.rmse:.4f}) > 2×MAE ({2*metrics.mae:.4f})")
        report.append("    → Some predictions are WAY off. Investigate large errors.")
    else:
        report.append(f"✅ No outliers: RMSE ≈ MAE (consistent error distribution)")
    
    report.append("")
    
    if metrics.consistent_bias:
        direction = "OVER-predicting" if metrics.mean_bias > 0 else "UNDER-predicting"
        report.append(f"⚠️  SYSTEMATIC BIAS: {direction} by {abs(metrics.mean_bias):.4f} on average")
        report.append("    → Model has consistent directional error.")
    else:
        report.append(f"✅ No systematic bias: Mean bias = {metrics.mean_bias:.4f}")
    
    report.append("")
    
    # Temporal analysis
    if temporal:
        report.append("TEMPORAL ANALYSIS")
        report.append("-" * 80)
        report.append(f"Early Steps MAE:  {temporal['early_mae']:.4f}")
        report.append(f"Middle Steps MAE: {temporal['middle_mae']:.4f}")
        report.append(f"Late Steps MAE:   {temporal['late_mae']:.4f}")
        
        if temporal['error_trend'] == 'improving':
            report.append("✅ Error IMPROVING over time (model adapts)")
        else:
            report.append("⚠️  Error DEGRADING over time (model drift)")
        
        report.append("")
    
    # Interpretation
    report.append("INTERPRETATION")
    report.append("-" * 80)
    
    if metrics.prediction_quality == 'excellent':
        report.append("🎯 Model predictions are highly accurate!")
        report.append("   SD equations closely match agent behavior.")
        report.append("   Parameters are well-calibrated.")
    elif metrics.prediction_quality == 'good':
        report.append("✅ Model predictions are reliable for most purposes.")
        report.append("   Minor discrepancies expected in complex scenarios.")
    elif metrics.prediction_quality == 'fair':
        report.append("⚠️  Model predictions show moderate error.")
        report.append("   Consider parameter tuning or adding feedback terms.")
    else:
        report.append("❌ Model predictions have significant error.")
        report.append("   Parameters may need recalibration.")
        report.append("   Check for missing feedback loops or constraints.")
    
    report.append("")
    report.append("=" * 80)
    
    return "\n".join(report)


# Example usage for SD tab integration
def validate_sd_predictions(sd_history: List[Dict]) -> Tuple[ValidationMetrics, Dict, str]:
    """
    Convenience function to validate SD predictions from history.
    
    Args:
        sd_history: List of SD history dicts from simulation
    
    Returns:
        (metrics, temporal_analysis, report_text)
    """
    
    if not sd_history or len(sd_history) < 10:
        return None, None, "❌ Insufficient data for validation (need 10+ steps)"
    
    # Extract actual and predicted adoption
    actual = [h['ev_adoption'] for h in sd_history]
    
    # Compute theoretical prediction
    r = sd_history[0].get('ev_growth_rate_r', 0.05)
    K = sd_history[0].get('ev_carrying_capacity_K', 0.80)
    EV0 = sd_history[0]['ev_adoption']
    
    predicted = []
    for t in range(len(sd_history)):
        if EV0 > 0:
            ev_t = K / (1 + ((K - EV0) / EV0) * np.exp(-r * t))
        else:
            ev_t = 0
        predicted.append(ev_t)
    
    # Compute metrics
    metrics = compute_validation_metrics(actual, predicted, "EV Adoption")
    temporal = analyze_temporal_drift(actual, predicted)
    report = generate_validation_report(metrics, temporal, "EV Adoption")
    
    return metrics, temporal, report