"""
ui/widgets/policy_parameter_controls.py

Enhanced parameter controls for fine-tuning policy configurations.
Provides advanced sliders for infrastructure, agent behavior, and policy thresholds.

UPDATED: Realistic value ranges for real-world scenarios
"""

import streamlit as st
from simulation.config import SimulationConfig


def render_policy_parameter_controls():
    """
    Render enhanced parameter controls in sidebar.
    
    Returns:
        Dict with parameter overrides, or None if not using custom controls
    """
    
    st.markdown("### ⚙️ Advanced Parameters")
    
    use_advanced = st.checkbox(
        "Enable Advanced Parameter Controls",
        value=False,
        help="Fine-tune infrastructure, agents, and policy thresholds",
        key="use_advanced_params"
    )
    
    # Store state for other widgets
    st.session_state.use_advanced_params = use_advanced
    
    if not use_advanced:
        return None
    
    st.info("💡 These parameters control all simulation settings")
    
    params = {}
    
    # Infrastructure Parameters
    with st.expander("🔌 Infrastructure Configuration", expanded=True):
        params['infrastructure'] = _render_infrastructure_controls()
    
    # Agent Behavior Parameters
    with st.expander("🧠 Agent Behavior", expanded=True):
        params['agents'] = _render_agent_controls()
    
    # Policy Threshold Parameters
    with st.expander("📊 Policy Thresholds", expanded=False):
        params['policy'] = _render_policy_threshold_controls()
    
    # Budget Constraints
    with st.expander("💰 Budget Constraints", expanded=False):
        params['budget'] = _render_budget_controls()
    
    return params


def _render_infrastructure_controls():
    """Render infrastructure parameter controls."""
    
    st.markdown("**Grid & Power**")
    
    col1, col2 = st.columns(2)
    
    with col1:
        grid_capacity = st.slider(
            "Grid Capacity (MW)",
            min_value=1.0,
            max_value=500.0,
            value=50.0,
            step=1.0,
            help="Total electrical grid capacity\n1-10 MW: Stress test\n20-100 MW: City district\n200+ MW: Large region"
        )
        
        # Show context
        if grid_capacity < 10:
            st.caption("🔥 Stress test - High utilization expected")
        elif grid_capacity < 50:
            st.caption("🏘️ District scale")
        elif grid_capacity < 150:
            st.caption("🏙️ City scale")
        else:
            st.caption("🌆 Regional scale")
    
    with col2:
        grid_reserve = st.slider(
            "Grid Reserve Margin (%)",
            min_value=0,
            max_value=30,
            value=10,
            help="Safety margin for grid operations"
        )
    
    st.markdown("**Charging Infrastructure**")
    
    col1, col2 = st.columns(2)
    
    with col1:
        num_chargers = st.slider(
            "Number of Chargers",
            min_value=5,
            max_value=300,
            value=50,
            help="Total charging stations deployed"
        )
    
    with col2:
        charger_density = st.slider(
            "Charger Density Multiplier",
            min_value=0.3,
            max_value=5.0,
            value=1.0,
            step=0.1,
            help="Spatial density\n0.3-0.7: Sparse (rural)\n1.0: Normal\n2.0+: Dense (urban)"
        )
    
    st.markdown("**Dynamic Expansion**")
    
    col1, col2 = st.columns(2)
    
    with col1:
        allow_expansion = st.checkbox(
            "Allow Dynamic Expansion",
            value=True,
            help="Enable infrastructure to expand during simulation"
        )
    
    with col2:
        expansion_trigger = st.slider(
            "Expansion Trigger (%)",
            min_value=40,
            max_value=95,
            value=70,
            disabled=not allow_expansion,
            help="Utilization % that triggers infrastructure expansion"
        )
    
    cost_per_charger = st.number_input(
        "Cost per Charger (£)",
        min_value=5000,
        max_value=200000,
        value=25000,
        step=5000,
        help="Investment cost for each new charger\nTypical: £20k-30k\nFast charger: £40k-100k"
    )
    
    return {
        'grid_capacity_mw': grid_capacity,
        'grid_reserve_margin': grid_reserve / 100.0,
        'num_chargers': int(num_chargers),
        'charger_density_multiplier': charger_density,
        'allow_dynamic_expansion': allow_expansion,
        'expansion_trigger_threshold': expansion_trigger / 100.0,
        'expansion_cost_per_charger': float(cost_per_charger),
    }


def _render_agent_controls():
    """Render agent behavior parameter controls."""
    
    st.markdown("**Desires & Preferences**")
    
    col1, col2 = st.columns(2)
    
    with col1:
        eco_desire = st.slider(
            "Eco Desire (mean)",
            min_value=0.0,
            max_value=1.0,
            value=0.5,
            step=0.05,
            help="Environmental consciousness\n0.3: Low\n0.5: Moderate\n0.8: High"
        )
        
        cost_sensitivity = st.slider(
            "Cost Sensitivity (mean)",
            min_value=0.0,
            max_value=1.0,
            value=0.5,
            step=0.05,
            help="Price sensitivity\n0.3: Low\n0.5: Moderate\n0.8: High"
        )
    
    with col2:
        time_sensitivity = st.slider(
            "Time Sensitivity (mean)",
            min_value=0.0,
            max_value=1.0,
            value=0.5,
            step=0.05,
            help="Time consciousness\n0.3: Low\n0.5: Moderate\n0.8: High"
        )
        
        comfort_desire = st.slider(
            "Comfort Desire (mean)",
            min_value=0.0,
            max_value=1.0,
            value=0.5,
            step=0.05,
            help="Comfort preference\n0.3: Low\n0.5: Moderate\n0.8: High"
        )
    
    st.markdown("**Initial Adoption**")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        initial_ev = st.slider(
            "Initial EV (%)",
            min_value=0,
            max_value=60,
            value=5,
            help="Starting EV users\nUK 2024: ~5%\nNorway 2024: ~25%\nTarget: 30-50%"
        )
    
    with col2:
        initial_bike = st.slider(
            "Initial Bike (%)",
            min_value=0,
            max_value=60,
            value=10,
            help="Starting cyclists\nUK: ~10%\nNetherlands: ~27%"
        )
    
    with col3:
        initial_transit = st.slider(
            "Initial Transit (%)",
            min_value=0,
            max_value=70,
            value=15,
            help="Starting transit users\nUK urban: ~15-20%\nLondon: ~40%"
        )
    
    st.markdown("**Social Network**")
    
    col1, col2 = st.columns(2)
    
    with col1:
        decay_rate = st.slider(
            "Influence Decay Rate",
            min_value=0.0,
            max_value=0.5,
            value=0.15,
            step=0.05,
            help="How quickly social influence fades\n0.05: Slow\n0.15: Moderate\n0.30: Fast"
        )
    
    with col2:
        habit_weight = st.slider(
            "Habit Weight",
            min_value=0.0,
            max_value=0.9,
            value=0.4,
            step=0.1,
            help="Resistance to change\n0.2: Low inertia\n0.4: Moderate\n0.7: High inertia"
        )
    
    return {
        'eco_desire_mean': eco_desire,
        'cost_sensitivity_mean': cost_sensitivity,
        'time_sensitivity_mean': time_sensitivity,
        'comfort_desire_mean': comfort_desire,
        'initial_ev_adoption': initial_ev / 100.0,
        'initial_bike_adoption': initial_bike / 100.0,
        'initial_transit_adoption': initial_transit / 100.0,
        'decay_rate': decay_rate,
        'habit_weight': habit_weight,
    }


def _render_policy_threshold_controls():
    """Render policy threshold parameter controls."""
    
    st.markdown("**Intervention Thresholds**")
    
    col1, col2 = st.columns(2)
    
    with col1:
        grid_intervention = st.slider(
            "Grid Intervention (%)",
            min_value=40,
            max_value=95,
            value=70,
            help="Grid utilization that triggers expansion\n40-60: Aggressive\n70: Standard\n80+: Conservative"
        )
        
        grid_critical = st.slider(
            "Grid Critical (%)",
            min_value=70,
            max_value=100,
            value=90,
            help="Critical threshold for emergency actions"
        )
    
    with col2:
        ev_target = st.slider(
            "EV Adoption Target (%)",
            min_value=10,
            max_value=100,
            value=50,
            help="Target EV adoption\nUK 2030: 30%\nUK 2035: 50%\nUK 2050: 100%"
        )
        
        ev_warning = st.slider(
            "EV Warning Threshold (%)",
            min_value=0,
            max_value=30,
            value=10,
            help="Warn if adoption falls below this"
        )
    
    st.markdown("**Congestion Thresholds**")
    
    col1, col2 = st.columns(2)
    
    with col1:
        congestion_threshold = st.slider(
            "Congestion Threshold (%)",
            min_value=30,
            max_value=80,
            value=60,
            help="Road utilization triggering policies"
        )
    
    with col2:
        congestion_charge = st.slider(
            "Congestion Charge Trigger (%)",
            min_value=50,
            max_value=95,
            value=75,
            help="Threshold for congestion charges"
        )
    
    return {
        'grid_intervention_threshold': grid_intervention / 100.0,
        'grid_critical_threshold': grid_critical / 100.0,
        'ev_adoption_target': ev_target / 100.0,
        'ev_adoption_warning': ev_warning / 100.0,
        'congestion_threshold': congestion_threshold / 100.0,
        'congestion_charge_trigger': congestion_charge / 100.0,
    }


def _render_budget_controls():
    """Render budget constraint controls."""
    
    budget_limit = st.number_input(
        "Total Budget Limit (£)",
        min_value=50000,
        max_value=50000000,
        value=1000000,
        step=100000,
        help="Total infrastructure budget\n£500k: Small city\n£1-5M: Medium city\n£10M+: Major city"
    )
    
    budget_warning = st.slider(
        "Budget Warning Threshold (%)",
        min_value=50,
        max_value=95,
        value=80,
        help="Warn when budget utilization reaches this level"
    )
    
    track_roi = st.checkbox(
        "Track ROI & Cost Recovery",
        value=True,
        help="Monitor return on investment for infrastructure spending"
    )
    
    if track_roi:
        discount_rate = st.slider(
            "ROI Discount Rate (%)",
            min_value=0,
            max_value=20,
            value=5,
            help="Annual discount rate\n3-5%: Low\n5-8%: Moderate\n10%+: High"
        )
    else:
        discount_rate = 5
    
    return {
        'default_budget_limit': float(budget_limit),
        'budget_warning_threshold': budget_warning / 100.0,
        'calculate_policy_roi': track_roi,
        'roi_discount_rate': discount_rate / 100.0,
    }


def apply_parameter_overrides(config: SimulationConfig, params: dict):
    """
    Apply parameter overrides to config.
    
    Args:
        config: Base SimulationConfig
        params: Dictionary from render_policy_parameter_controls()
        
    Returns:
        Modified config
    """
    
    if params is None:
        return config
    
    # Apply infrastructure overrides
    if 'infrastructure' in params:
        infra = params['infrastructure']
        config.infrastructure.grid_capacity_mw = infra['grid_capacity_mw']
        config.infrastructure.grid_reserve_margin = infra['grid_reserve_margin']
        config.infrastructure.num_chargers = infra['num_chargers']
        config.infrastructure.charger_density_multiplier = infra['charger_density_multiplier']
        config.infrastructure.allow_dynamic_expansion = infra['allow_dynamic_expansion']
        config.infrastructure.expansion_trigger_threshold = infra['expansion_trigger_threshold']
        config.infrastructure.expansion_cost_per_charger = infra['expansion_cost_per_charger']
    
    # Apply agent overrides
    if 'agents' in params:
        agents = params['agents']
        config.agents.behavior.eco_desire_mean = agents['eco_desire_mean']
        config.agents.behavior.cost_sensitivity_mean = agents['cost_sensitivity_mean']
        config.agents.behavior.time_sensitivity_mean = agents['time_sensitivity_mean']
        config.agents.behavior.comfort_desire_mean = agents['comfort_desire_mean']
        config.agents.behavior.initial_ev_adoption = agents['initial_ev_adoption']
        config.agents.behavior.initial_bike_adoption = agents['initial_bike_adoption']
        config.agents.behavior.initial_transit_adoption = agents['initial_transit_adoption']
        config.agents.social_network.decay_rate = agents['decay_rate']
        config.agents.social_network.habit_weight = agents['habit_weight']
    
    # Apply policy threshold overrides
    if 'policy' in params:
        policy = params['policy']
        config.policy.thresholds.grid_intervention_threshold = policy['grid_intervention_threshold']
        config.policy.thresholds.grid_critical_threshold = policy['grid_critical_threshold']
        config.policy.thresholds.ev_adoption_target = policy['ev_adoption_target']
        config.policy.thresholds.ev_adoption_warning = policy['ev_adoption_warning']
        config.policy.thresholds.congestion_threshold = policy['congestion_threshold']
        config.policy.thresholds.congestion_charge_trigger = policy['congestion_charge_trigger']
    
    # Apply budget overrides
    if 'budget' in params:
        budget = params['budget']
        config.policy.thresholds.default_budget_limit = budget['default_budget_limit']
        config.policy.thresholds.budget_warning_threshold = budget['budget_warning_threshold']
        config.analytics.calculate_policy_roi = budget['calculate_policy_roi']
        config.analytics.roi_discount_rate = budget['roi_discount_rate']
    
    return config