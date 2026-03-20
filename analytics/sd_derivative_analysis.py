"""
analytics/sd_derivative_analysis.py

Derivative and Sensitivity Analysis for Hybrid System Dynamics
Computes Jacobians, sensitivities, and prepares data for SHAP analysis

This module bridges continuous (differential equations) and discrete (event-driven)
dynamics for cyber-physical systems and digital twin applications.
"""

import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class SensitivityMetrics:
    """Container for sensitivity analysis results."""
    # Jacobian elements (partial derivatives)
    dEV_dr: float  # ∂(dEV/dt)/∂r
    dEV_dK: float  # ∂(dEV/dt)/∂K
    dEV_dInfra: float  # ∂(dEV/dt)/∂infrastructure_feedback
    dEV_dSocial: float  # ∂(dEV/dt)/∂social_influence
    
    # Parameter elasticity (normalized sensitivity)
    elasticity_r: float  # % change in flow per % change in r
    elasticity_K: float
    elasticity_infra: float
    elasticity_social: float
    
    # Mode indicators
    in_logistic_regime: bool  # True if logistic term dominates
    in_feedback_regime: bool  # True if feedbacks dominate
    near_threshold: bool  # True if close to discrete transition
    
    # Feature importance (for SHAP)
    feature_contributions: Dict[str, float]


def compute_jacobian(
    ev_adoption: float,
    r: float,
    K: float,
    infra_feedback: float,
    social_feedback: float,
    infrastructure_capacity: float = 1.0
) -> np.ndarray:
    """
    Compute Jacobian matrix of SD equations.
    
    For the system:
        dEV/dt = f(EV, r, K, infra, social)
    
    Compute:
        J = [∂f/∂r, ∂f/∂K, ∂f/∂infra, ∂f/∂social]
    
    Args:
        ev_adoption: Current EV adoption (0-1)
        r: Growth rate
        K: Carrying capacity
        infra_feedback: Infrastructure feedback strength
        social_feedback: Social influence strength
        infrastructure_capacity: Normalized infrastructure index
    
    Returns:
        Jacobian as 1D array [∂f/∂r, ∂f/∂K, ∂f/∂infra, ∂f/∂social]
    """
    
    EV = ev_adoption
    
    # ∂f/∂r: Derivative w.r.t. growth rate
    # f = r·EV·(1 - EV/K) + ...
    # ∂f/∂r = EV·(1 - EV/K)
    df_dr = EV * (1 - EV / K) if K > 0 else 0
    
    # ∂f/∂K: Derivative w.r.t. carrying capacity
    # Full equation: r*EV*(1-EV/K) + infra*EV*cap + s*EV*(1-EV/K)
    # Both logistic and social terms depend on K:
    #   d/dK [r*EV*(1-EV/K)] = r*EV*(EV/K²)
    #   d/dK [s*EV*(1-EV/K)] = s*EV*(EV/K²)
    # Total: df/dK = (r + social_feedback) * EV * (EV/K²)
    df_dK = (r + social_feedback) * EV * (EV / (K**2)) if K > 0 else 0
 
    # ∂f/∂infra: Derivative w.r.t. infrastructure feedback
    # f = ... + infra·EV·infrastructure_capacity
    # ∂f/∂infra = EV·infrastructure_capacity
    df_dinfra = EV * infrastructure_capacity
 
    # ∂f/∂social: Derivative w.r.t. social influence
    # Social term is s*EV*(1-EV/K) — bounded by carrying capacity K
    # ∂f/∂social = EV·(1-EV/K)
    df_dsocial = EV * (1.0 - EV / K) if K > 0 else 0
    
    return np.array([df_dr, df_dK, df_dinfra, df_dsocial])


def compute_elasticity(
    jacobian: np.ndarray,
    params: Dict[str, float],
    current_flow: float
) -> Dict[str, float]:
    """
    Compute parameter elasticity (normalized sensitivity).
    
    Elasticity = (∂f/∂p) × (p/f)
    
    Interpretation: % change in output for 1% change in parameter
    
    Args:
        jacobian: Jacobian array [∂f/∂r, ∂f/∂K, ∂f/∂infra, ∂f/∂social]
        params: Dict with keys 'r', 'K', 'infra', 'social'
        current_flow: Current dEV/dt value
    
    Returns:
        Dict of elasticities for each parameter
    """
    
    if abs(current_flow) < 1e-10:
        # Avoid division by zero
        return {
            'r': 0.0,
            'K': 0.0,
            'infrastructure': 0.0,
            'social': 0.0
        }
    
    # Elasticity = (∂f/∂p) × (p/f)
    elasticity_r = jacobian[0] * params['r'] / current_flow
    elasticity_K = jacobian[1] * params['K'] / current_flow
    elasticity_infra = jacobian[2] * params['infrastructure'] / current_flow
    elasticity_social = jacobian[3] * params['social'] / current_flow
    
    return {
        'r': elasticity_r,
        'K': elasticity_K,
        'infrastructure': elasticity_infra,
        'social': elasticity_social
    }


def compute_feature_contributions(
    ev_adoption: float,
    r: float,
    K: float,
    infra_feedback: float,
    social_feedback: float,
    infrastructure_capacity: float = 1.0
) -> Dict[str, float]:
    """
    Compute feature contributions for SHAP-style analysis.
    
    Decomposes dEV/dt into additive contributions:
        flow = logistic + infrastructure + social
    
    Args:
        ev_adoption: Current EV adoption
        r, K: Logistic parameters
        infra_feedback, social_feedback: Feedback strengths
        infrastructure_capacity: Infrastructure index
    
    Returns:
        Dict with feature contributions
    """
    
    EV = ev_adoption
    
    # Logistic component
    logistic = r * EV * (1 - EV / K) if K > 0 else 0
    
    # Infrastructure feedback component
    infrastructure = infra_feedback * EV * infrastructure_capacity
    
    # Social influence: bounded by K (consistent with system_dynamics.py)
    # s * EV * (1 - EV/K) — peaks at EV = K/2, goes to 0 at EV = K
    social = social_feedback * EV * (1.0 - EV / K) if K > 0 else 0
    
    # Total flow
    total_flow = logistic + infrastructure + social
    
    # Normalized contributions (as fractions of total)
    if abs(total_flow) > 1e-10:
        return {
            'logistic': logistic / total_flow,
            'infrastructure': infrastructure / total_flow,
            'social': social / total_flow,
            'total': 1.0  # Should sum to 1
        }
    else:
        return {
            'logistic': 0.0,
            'infrastructure': 0.0,
            'social': 0.0,
            'total': 0.0
        }


def analyze_regime(
    contributions: Dict[str, float],
    ev_adoption: float,
    thresholds: Dict[str, float] = None
) -> Dict[str, bool]:
    """
    Determine which dynamical regime the system is in.
    
    Args:
        contributions: Feature contributions dict
        ev_adoption: Current adoption level
        thresholds: Optional custom thresholds
    
    Returns:
        Dict of boolean regime indicators
    """
    
    if thresholds is None:
        thresholds = {
            'tipping_point': 0.30,
            'near_threshold_margin': 0.05,
            'feedback_dominance': 0.5
        }
    
    # Regime detection
    in_logistic = abs(contributions.get('logistic', 0)) > abs(contributions.get('infrastructure', 0) + contributions.get('social', 0))
    in_feedback = (contributions.get('infrastructure', 0) + contributions.get('social', 0)) > abs(contributions.get('logistic', 0))
    
    # Check if near discrete threshold
    near_threshold = abs(ev_adoption - thresholds['tipping_point']) < thresholds['near_threshold_margin']
    
    return {
        'in_logistic_regime': in_logistic,
        'in_feedback_regime': in_feedback,
        'near_threshold': near_threshold,
        'above_tipping_point': ev_adoption > thresholds['tipping_point']
    }


def compute_sensitivity_metrics(
    ev_adoption: float,
    r: float,
    K: float,
    infra_feedback: float,
    social_feedback: float,
    current_flow: float,
    infrastructure_capacity: float = 1.0
) -> SensitivityMetrics:
    """
    Compute comprehensive sensitivity metrics for current state.
    
    This is the main function to call for sensitivity analysis.
    
    Args:
        ev_adoption: Current EV adoption (0-1)
        r: Growth rate
        K: Carrying capacity
        infra_feedback: Infrastructure feedback strength
        social_feedback: Social influence strength
        current_flow: Current dEV/dt
        infrastructure_capacity: Infrastructure index
    
    Returns:
        SensitivityMetrics object
    """
    
    # Compute Jacobian
    jacobian = compute_jacobian(
        ev_adoption, r, K, infra_feedback, social_feedback, infrastructure_capacity
    )
    
    # Compute elasticity
    params = {
        'r': r,
        'K': K,
        'infrastructure': infra_feedback,
        'social': social_feedback
    }
    elasticity = compute_elasticity(jacobian, params, current_flow)
    
    # Compute feature contributions
    contributions = compute_feature_contributions(
        ev_adoption, r, K, infra_feedback, social_feedback, infrastructure_capacity
    )
    
    # Determine regime
    regime = analyze_regime(contributions, ev_adoption)
    
    return SensitivityMetrics(
        dEV_dr=jacobian[0],
        dEV_dK=jacobian[1],
        dEV_dInfra=jacobian[2],
        dEV_dSocial=jacobian[3],
        elasticity_r=elasticity['r'],
        elasticity_K=elasticity['K'],
        elasticity_infra=elasticity['infrastructure'],
        elasticity_social=elasticity['social'],
        in_logistic_regime=regime['in_logistic_regime'],
        in_feedback_regime=regime['in_feedback_regime'],
        near_threshold=regime['near_threshold'],
        feature_contributions=contributions
    )


def analyze_mode_switches(
    sd_history: List[Dict],
    thresholds: Dict[str, float] = None
) -> List[Dict]:
    """
    Detect discrete mode switches in hybrid system trajectory.
    
    Args:
        sd_history: List of SD history dicts
        thresholds: Optional custom thresholds
    
    Returns:
        List of mode switch events with step and type
    """
    
    if thresholds is None:
        thresholds = {'tipping_point': 0.30}
    
    switches = []
    
    for i in range(1, len(sd_history)):
        prev = sd_history[i-1]
        curr = sd_history[i]
        
        prev_adoption = prev['ev_adoption']
        curr_adoption = curr['ev_adoption']
        
        # Detect tipping point crossing
        if prev_adoption < thresholds['tipping_point'] <= curr_adoption:
            switches.append({
                'step': i,
                'type': 'tipping_point_crossed',
                'from_mode': 'sub_critical',
                'to_mode': 'super_critical',
                'adoption_at_switch': curr_adoption
            })
        
        # Detect regime changes based on flow dominance
        prev_metrics = compute_sensitivity_metrics(
            prev_adoption,
            prev.get('ev_growth_rate_r', 0.05),
            prev.get('ev_carrying_capacity_K', 0.80),
            0.02, 0.03,  # Default feedback strengths
            prev.get('ev_adoption_flow', 0)
        )
        
        curr_metrics = compute_sensitivity_metrics(
            curr_adoption,
            curr.get('ev_growth_rate_r', 0.05),
            curr.get('ev_carrying_capacity_K', 0.80),
            0.02, 0.03,
            curr.get('ev_adoption_flow', 0)
        )
        
        # Detect regime switch
        if prev_metrics.in_logistic_regime and curr_metrics.in_feedback_regime:
            switches.append({
                'step': i,
                'type': 'regime_switch',
                'from_mode': 'logistic_dominated',
                'to_mode': 'feedback_dominated',
                'adoption_at_switch': curr_adoption
            })
    
    return switches


def prepare_shap_data(
    sd_history: List[Dict]
) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """
    Prepare data for SHAP analysis.
    
    Returns:
        X: Feature matrix (parameters and states)
        y: Target values (flow rates)
        feature_names: List of feature names
    """
    
    feature_names = [
        'ev_adoption',
        'growth_rate_r',
        'carrying_capacity_K',
        'infrastructure_feedback',
        'social_influence',
        'infrastructure_capacity'
    ]
    
    X = []
    y = []
    
    for entry in sd_history:
        features = [
            entry['ev_adoption'],
            entry.get('ev_growth_rate_r', 0.05),
            entry.get('ev_carrying_capacity_K', 0.80),
            0.02,  # Infrastructure feedback (default)
            0.03,  # Social influence (default)
            1.0    # Infrastructure capacity (normalized)
        ]
        
        X.append(features)
        y.append(entry['ev_adoption_flow'])
    
    return np.array(X), np.array(y), feature_names


# Example usage for integration with SD tab
def analyze_sd_trajectory(sd_history: List[Dict]) -> Dict:
    """
    Comprehensive analysis of SD trajectory for UI display.
    
    Args:
        sd_history: SD history from simulation
    
    Returns:
        Dict with all sensitivity and derivative analysis results
    """
    
    if not sd_history or len(sd_history) < 10:
        return {'error': 'Insufficient data'}
    
    # Get current state
    current = sd_history[-1]
    
    # Compute current sensitivity
    current_sensitivity = compute_sensitivity_metrics(
        ev_adoption=current['ev_adoption'],
        r=current.get('ev_growth_rate_r', 0.05),
        K=current.get('ev_carrying_capacity_K', 0.80),
        infra_feedback=0.02,
        social_feedback=0.03,
        current_flow=current['ev_adoption_flow']
    )
    
    # Detect mode switches
    switches = analyze_mode_switches(sd_history)
    
    # Prepare SHAP data
    X, y, feature_names = prepare_shap_data(sd_history)
    
    return {
        'current_sensitivity': current_sensitivity,
        'mode_switches': switches,
        'shap_ready_data': {
            'X': X,
            'y': y,
            'feature_names': feature_names
        },
        'n_switches': len(switches),
        'dominant_feature': max(
            {k: v for k, v in current_sensitivity.feature_contributions.items()
             if k != 'total'}.items(),
            key=lambda x: abs(x[1])
        )[0] if current_sensitivity.feature_contributions else None
    }