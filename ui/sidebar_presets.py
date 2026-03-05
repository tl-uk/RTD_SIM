"""
ui/sidebar_presets.py

This module implements the Preset configuration selector for sidebar.
- Integrates with ConfigurationPresets system.
- Provides UI for selecting and previewing presets, as well as building custom configurations.
- Includes explanations and warnings for policy-triggering presets.
- Allows parameter overrides while maintaining preset defaults for flexibility.
- Ensures that users understand the implications of their choices, especially when 
  selecting presets that are designed to trigger policy actions.
  
"""

import streamlit as st
from simulation.config.presets import ConfigurationPresets


def render_preset_selector():
    """
    Render preset configuration selector in sidebar.
    
    Returns:
        Tuple of (use_preset: bool, preset_config: SimulationConfig or None)
    """
    
    st.markdown("### 🎯 Configuration Presets")
    
    use_preset = st.checkbox(
        "Use Configuration Preset",
        value=False,
        help="Load pre-configured settings optimized for specific scenarios",
        key="use_preset_config"
    )
    
    if not use_preset:
        return False, None
    
    # Get available presets
    presets = ConfigurationPresets.list_presets()
    
    # Preset selector
    selected_preset = st.selectbox(
        "Select Preset",
        options=list(presets.keys()),
        format_func=lambda x: f"{x.replace('_', ' ').title()}",
        help="Choose a pre-configured scenario",
        key="preset_selector"
    )
    
    # Show description
    st.info(f"💡 {presets[selected_preset]}")
    
    # Preview preset parameters
    with st.expander("📋 Preset Parameters", expanded=False):
        preset_config = ConfigurationPresets.get_preset(selected_preset)
        
        st.markdown("**Infrastructure:**")
        st.write(f"- Grid Capacity: {preset_config.infrastructure.grid_capacity_mw} MW")
        st.write(f"- Chargers: {preset_config.infrastructure.num_chargers}")
        st.write(f"- Charger Density: {preset_config.infrastructure.charger_density_multiplier}x")
        
        st.markdown("**Agents:**")
        st.write(f"- Number: {preset_config.num_agents}")
        st.write(f"- Eco Desire: {preset_config.agents.behavior.eco_desire_mean:.2f}")
        st.write(f"- Initial EV Adoption: {preset_config.agents.behavior.initial_ev_adoption*100:.0f}%")
        st.write(f"- Cost Sensitivity: {preset_config.agents.behavior.cost_sensitivity_mean:.2f}")
        
        st.markdown("**Policy:**")
        st.write(f"- Grid Trigger: {preset_config.policy.thresholds.grid_intervention_threshold*100:.0f}%")
        st.write(f"- EV Target: {preset_config.policy.thresholds.ev_adoption_target*100:.0f}%")
    
    # Allow parameter overrides
    with st.expander("⚙️ Override Parameters (Optional)", expanded=False):
        st.markdown("Adjust specific parameters while keeping preset defaults for others.")
        
        override_grid = st.checkbox("Override Grid Capacity")
        if override_grid:
            preset_config.infrastructure.grid_capacity_mw = st.slider(
                "Grid Capacity (MW)",
                min_value=10.0, max_value=200.0,
                value=preset_config.infrastructure.grid_capacity_mw,
                key="override_grid_capacity"
            )
        
        override_agents = st.checkbox("Override Number of Agents")
        if override_agents:
            preset_config.num_agents = st.slider(
                "Number of Agents",
                min_value=50, max_value=500,
                value=preset_config.num_agents,
                key="override_num_agents"
            )
        
        override_eco = st.checkbox("Override Eco Desire")
        if override_eco:
            preset_config.agents.behavior.eco_desire_mean = st.slider(
                "Eco Desire (mean)",
                min_value=0.0, max_value=1.0,
                value=preset_config.agents.behavior.eco_desire_mean,
                step=0.05,
                key="override_eco_desire"
            )
    
    # Warning for policy-trigger presets
    if selected_preset in ['high_ev_demand', 'grid_stress_test', 'rapid_adoption']:
        st.success("✅ This preset is designed to trigger policy actions!")
    
    return True, preset_config


def render_custom_preset_builder():
    """
    Render custom preset builder (advanced users).
    
    Returns:
        SimulationConfig or None
    """
    
    st.markdown("### 🎨 Custom Configuration")
    
    st.info("""
    Build a custom configuration from scratch.
    For most users, we recommend using presets above.
    """)
    
    # Infrastructure
    st.markdown("#### 🔌 Infrastructure")
    col1, col2 = st.columns(2)
    
    with col1:
        grid_capacity = st.slider(
            "Grid Capacity (MW)",
            min_value=10.0, max_value=200.0, value=100.0,
            help="Lower values trigger grid interventions",
            key="custom_grid_capacity"
        )
        
        num_chargers = st.slider(
            "Number of Chargers",
            min_value=10, max_value=100, value=50,
            key="custom_num_chargers"
        )
    
    with col2:
        charger_density = st.slider(
            "Charger Density Multiplier",
            min_value=0.5, max_value=3.0, value=1.0, step=0.1,
            help="1.0 = normal density, higher = more chargers",
            key="custom_charger_density"
        )
    
    # Agent Behavior
    st.markdown("#### 🧠 Agent Behavior")
    col1, col2 = st.columns(2)
    
    with col1:
        eco_desire = st.slider(
            "Eco Desire (mean)",
            min_value=0.0, max_value=1.0, value=0.5, step=0.05,
            help="Higher = more environmentally conscious",
            key="custom_eco_desire"
        )
        
        cost_sensitivity = st.slider(
            "Cost Sensitivity (mean)",
            min_value=0.0, max_value=1.0, value=0.5, step=0.05,
            help="Higher = more cost-conscious",
            key="custom_cost_sensitivity"
        )
    
    with col2:
        initial_ev = st.slider(
            "Initial EV Adoption (%)",
            min_value=0, max_value=50, value=5,
            help="Starting percentage of EV users",
            key="custom_initial_ev"
        ) / 100.0
        
        num_agents = st.slider(
            "Number of Agents",
            min_value=50, max_value=500, value=100,
            key="custom_num_agents"
        )
    
    # Policy Thresholds
    st.markdown("#### 📊 Policy Thresholds")
    col1, col2 = st.columns(2)
    
    with col1:
        grid_trigger = st.slider(
            "Grid Intervention Threshold (%)",
            min_value=50, max_value=95, value=70,
            help="Grid utilization that triggers expansion",
            key="custom_grid_trigger"
        ) / 100.0
        
        ev_target = st.slider(
            "EV Adoption Target (%)",
            min_value=10, max_value=100, value=50,
            help="Policy success target",
            key="custom_ev_target"
        ) / 100.0
    
    with col2:
        budget_limit = st.number_input(
            "Budget Limit (£)",
            min_value=100000, max_value=10000000, value=1000000,
            step=100000,
            help="Total infrastructure budget",
            key="custom_budget_limit"
        )
    
    # Build custom config
    if st.button("🏗️ Build Custom Configuration", type="primary"):
        custom_config = ConfigurationPresets.custom_from_params(
            grid_capacity_mw=grid_capacity,
            num_chargers=num_chargers,
            charger_density_multiplier=charger_density,
            eco_desire_mean=eco_desire,
            cost_sensitivity_mean=cost_sensitivity,
            initial_ev_adoption=initial_ev,
            num_agents=num_agents,
            grid_intervention_threshold=grid_trigger,
            ev_adoption_target=ev_target,
            budget_limit=budget_limit
        )
        
        st.success("✅ Custom configuration created!")
        
        # Preview
        with st.expander("Preview Configuration"):
            st.json({
                'infrastructure': {
                    'grid_capacity_mw': grid_capacity,
                    'num_chargers': num_chargers,
                    'charger_density': charger_density
                },
                'agents': {
                    'num_agents': num_agents,
                    'eco_desire': eco_desire,
                    'cost_sensitivity': cost_sensitivity,
                    'initial_ev_adoption': initial_ev
                },
                'policy': {
                    'grid_trigger': grid_trigger,
                    'ev_target': ev_target,
                    'budget_limit': budget_limit
                }
            })
        
        return custom_config
    
    return None
