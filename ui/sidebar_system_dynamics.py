"""
ui/sidebar_system_dynamics.py

System Dynamics parameter controls for sidebar
Phase 5.3: Interactive SD configuration
"""

import streamlit as st
from simulation.config.system_dynamics_config import SystemDynamicsConfig


def render_sd_parameters_section():
    """
    Render System Dynamics parameters section in sidebar.
    
    Returns:
        SystemDynamicsConfig with user-selected parameters, or None if using defaults
    """
    
    with st.expander("🔬 System Dynamics Parameters", expanded=False):
        st.markdown("""
        Configure macro-level dynamics parameters.
        These control how EV adoption evolves system-wide using differential equations.
        """)
        
        use_custom_sd = st.checkbox(
            "Customize SD Parameters",
            value=False,
            help="Use custom parameters instead of defaults",
            key="use_custom_sd"
        )
        
        if not use_custom_sd:
            st.info("💡 Using default parameters (Baseline scenario)")
            return None
        
        st.markdown("---")
        
        # Preset scenarios
        st.markdown("**Quick Presets:**")
        preset_choice = st.radio(
            "Scenario",
            options=["Baseline", "Aggressive Policy", "Conservative Policy", "Custom"],
            key="sd_preset",
            horizontal=True
        )
        
        # Get preset config
        if preset_choice == "Aggressive Policy":
            config = SystemDynamicsConfig.aggressive_policy()
        elif preset_choice == "Conservative Policy":
            config = SystemDynamicsConfig.conservative_policy()
        else:
            config = SystemDynamicsConfig.default()
        
        st.markdown("---")
        
        # Only show sliders if Custom selected
        if preset_choice == "Custom":
            st.markdown("#### 📈 EV Adoption Dynamics")
            
            config.ev_growth_rate_r = st.slider(
                "Growth Rate (r)",
                min_value=0.01, max_value=0.20, value=0.05, step=0.01,
                help="Base adoption rate. Higher = faster growth.",
                key="sd_growth_rate"
            )
            
            config.ev_carrying_capacity_K = st.slider(
                "Carrying Capacity (K)",
                min_value=0.50, max_value=1.00, value=0.80, step=0.05,
                help="Maximum sustainable adoption (as fraction). 0.80 = 80% max.",
                key="sd_carrying_capacity"
            )
            
            st.markdown("#### 🔄 Feedback Loops")
            
            config.infrastructure_feedback_strength = st.slider(
                "Infrastructure Feedback",
                min_value=0.0, max_value=0.10, value=0.02, step=0.01,
                help="Boost from charger availability",
                key="sd_infra_feedback"
            )
            
            config.social_influence_strength = st.slider(
                "Social Influence",
                min_value=0.0, max_value=0.10, value=0.03, step=0.01,
                help="Peer effects and network influence",
                key="sd_social_influence"
            )
            
            st.markdown("#### ⚡ Grid Dynamics")
            
            config.grid_stress_threshold = st.slider(
                "Grid Stress Threshold",
                min_value=0.70, max_value=0.95, value=0.85, step=0.05,
                help="Utilization that triggers grid expansion",
                key="sd_grid_threshold"
            )
            
            config.policy_response_gain = st.slider(
                "Policy Response Gain",
                min_value=0.1, max_value=1.0, value=0.5, step=0.1,
                help="How aggressively policies respond. Higher = faster expansion.",
                key="sd_policy_gain"
            )
            
            st.markdown("#### 🌍 Emissions")
            
            config.emissions_target_kg_day = st.number_input(
                "Daily Emissions Target (kg CO2)",
                min_value=10000, max_value=100000, value=40000, step=5000,
                help="Target emissions per day",
                key="sd_emissions_target"
            )
            
            st.markdown("#### 🎯 Tipping Points")
            
            config.adoption_tipping_point = st.slider(
                "Adoption Tipping Point",
                min_value=0.20, max_value=0.40, value=0.30, step=0.05,
                help="Threshold where adoption accelerates",
                key="sd_tipping_point"
            )
        
        # Preview parameters
        with st.expander("📋 Preview Parameters", expanded=False):
            st.json({
                "ev_dynamics": {
                    "growth_rate_r": config.ev_growth_rate_r,
                    "carrying_capacity_K": config.ev_carrying_capacity_K,
                    "infrastructure_feedback": config.infrastructure_feedback_strength,
                    "social_influence": config.social_influence_strength,
                },
                "grid_dynamics": {
                    "stress_threshold": config.grid_stress_threshold,
                    "policy_response_gain": config.policy_response_gain,
                },
                "thresholds": {
                    "tipping_point": config.adoption_tipping_point,
                    "emissions_target": config.emissions_target_kg_day,
                }
            })
        
        st.success(f"✅ Using **{preset_choice}** SD parameters")
        
        return config


def render_sd_info_box():
    """
    Render information box about System Dynamics.
    Call this from main sidebar to educate users.
    """
    
    with st.expander("ℹ️ About System Dynamics", expanded=False):
        st.markdown("""
        **System Dynamics** tracks macro-level patterns using differential equations.
        
        **Key Concepts:**
        
        🔬 **Logistic Growth**  
        EV adoption follows: `dEV/dt = r·EV·(1-EV/K) + feedbacks`
        
        📈 **Growth Rate (r)**  
        How fast adoption spreads initially
        
        🎯 **Carrying Capacity (K)**  
        Maximum sustainable adoption level
        
        🔄 **Feedback Loops**  
        - Infrastructure: More chargers → easier adoption
        - Social: More EVs → stronger peer influence
        
        🌊 **Tipping Points**  
        Critical thresholds (typically 30%) where adoption accelerates
        
        **Why Use SD?**
        - Predict long-term trends
        - Identify leverage points
        - Validate agent behavior against theory
        - Test policy sensitivity
        """)
        
        st.info("💡 View the **System Dynamics** tab after running a simulation to see these dynamics in action!")