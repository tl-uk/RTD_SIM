"""
ui/tabs/policy_diagnostics_tab.py

NEW Phase 5.2: Policy diagnostics and "why no triggers?" explanation.
Helps users understand policy behavior and configure scenarios effectively.
"""

import streamlit as st
from typing import Dict, Any


def render_policy_diagnostics_tab(results, config):
    """
    Render policy diagnostics tab explaining why policies did/didn't trigger.
    
    Args:
        results: SimulationResults with policy_status
        config: SimulationConfig used for the simulation
    """
    
    st.header("🔍 Policy Diagnostics")
    
    # Check if combined scenario was used
    if not hasattr(results, 'policy_status') or results.policy_status is None:
        st.info("💡 No combined scenario was active for this simulation.")
        
        st.markdown("""
        ### How to Use Policy Scenarios
        
        1. Go to **Sidebar → Advanced: Combined Scenarios**
        2. Enable "Use Combined Scenario"
        3. Select a scenario (e.g., "Aggressive Electrification Push")
        4. Run simulation
        
        **Or use Configuration Presets:**
        1. Go to **Sidebar → Configuration Presets**
        2. Select a preset like "High EV Demand" or "Grid Stress Test"
        3. These are pre-configured to trigger policy actions
        """)
        return
    
    # Policy scenario was active
    policy_status = results.policy_status
    scenario_name = policy_status.get('scenario_name', 'Unknown')
    rules_triggered = policy_status.get('rules_triggered', 0)
    total_rules = policy_status.get('total_interaction_rules', 0)
    sim_state = policy_status.get('simulation_state', {})
    
    # Overview
    st.markdown(f"### 📋 Scenario: {scenario_name}")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Rules Triggered", f"{rules_triggered} / {total_rules}")
    
    with col2:
        ev_adoption = sim_state.get('ev_adoption', 0)
        st.metric("Final EV Adoption", f"{ev_adoption*100:.1f}%")
    
    with col3:
        grid_util = sim_state.get('grid_utilization', 0)
        st.metric("Final Grid Utilization", f"{grid_util*100:.1f}%")
    
    with col4:
        charger_util = sim_state.get('charger_utilization', 0)
        st.metric("Charger Utilization", f"{charger_util*100:.1f}%")
    
    st.markdown("---")
    
    # Policy Actions Analysis
    if rules_triggered > 0:
        st.success(f"✅ {rules_triggered} policy rule(s) triggered successfully!")
        
        if hasattr(results, 'policy_actions') and results.policy_actions:
            st.markdown("### ⚙️ Policy Actions Taken")
            
            for i, action in enumerate(results.policy_actions, 1):
                with st.expander(f"Action {i}: {action['action']} (Step {action['step']})", expanded=i<=3):
                    st.markdown(f"**Trigger Condition:** `{action['condition']}`")
                    st.markdown(f"**Action:** {action['action']}")
                    
                    if 'result' in action:
                        st.markdown("**Result:**")
                        st.json(action['result'])
    else:
        # NO TRIGGERS - Main diagnostic section
        st.warning("⚠️ No Policy Actions Were Triggered")
        
        _render_why_no_triggers_diagnostic(sim_state, config, policy_status)
    
    st.markdown("---")
    
    # Configuration Recommendations
    _render_configuration_recommendations(sim_state, config, rules_triggered)


def _render_why_no_triggers_diagnostic(sim_state: Dict, config: Any, policy_status: Dict):
    """Explain why policies didn't trigger and suggest fixes."""
    
    st.markdown("### 💡 Why Policies Didn't Trigger")
    
    # Analyze the situation
    issues = []
    suggestions = []
    
    ev_adoption = sim_state.get('ev_adoption', 0)
    grid_util = sim_state.get('grid_utilization', 0)
    charger_util = sim_state.get('charger_utilization', 0)
    
    # Issue 1: Low EV adoption
    if ev_adoption < 0.1:
        issues.append(f"🔴 **Very low EV adoption** ({ev_adoption*100:.1f}%)")
        suggestions.append({
            'title': 'Increase EV Adoption',
            'items': [
                'Raise agent eco desire to 0.7-0.9',
                'Start with higher initial EV adoption (15-25%)',
                'Reduce EV costs in scenario configuration'
            ]
        })
    
    # Issue 2: Low grid utilization
    if grid_util < 0.3:
        issues.append(f"🔴 **Grid barely used** ({grid_util*100:.1f}%)")
        suggestions.append({
            'title': 'Increase Grid Stress',
            'items': [
                'Reduce grid capacity to 20-50 MW (currently: {:.0f} MW)'.format(
                    config.grid_capacity_mw
                ),
                'Increase number of agents to 150-200',
                'Enable more EV charging events'
            ]
        })
    
    # Issue 3: Low charger utilization
    if charger_util < 0.1:
        issues.append(f"🔴 **Chargers barely used** ({charger_util*100:.1f}%)")
        suggestions.append({
            'title': 'Increase Charging Demand',
            'items': [
                'Ensure agents are choosing EV modes',
                'Check that charging stations are accessible',
                'Increase journey distances to require more charging'
            ]
        })
    
    # Issue 4: Grid capacity too high
    if grid_util < 0.5 and config.grid_capacity_mw > 100:
        issues.append(f"🔴 **Grid capacity too high** ({config.grid_capacity_mw:.0f} MW)")
        suggestions.append({
            'title': 'Right-Size Infrastructure',
            'items': [
                'Reduce grid capacity to match agent load',
                'Try preset: "Grid Stress Test" (20 MW grid)',
                'Use preset: "High EV Demand" (30 MW grid, 100 agents)'
            ]
        })
    
    # Issue 5: Policy thresholds too high
    # (We don't have direct access to thresholds in results, but can infer)
    if grid_util > 0 and grid_util < 0.6:
        issues.append("🟡 **Grid utilization below typical trigger threshold** (70%)")
        suggestions.append({
            'title': 'Adjust Policy Thresholds',
            'items': [
                'Lower grid intervention threshold to 50-60%',
                'Use scenario with more aggressive triggers',
                'Modify combined scenario YAML to use lower thresholds'
            ]
        })
    
    # Display issues
    if issues:
        st.markdown("#### 🔍 Identified Issues:")
        for issue in issues:
            st.markdown(f"- {issue}")
    else:
        st.info("No obvious issues detected. Policies may simply not have been needed.")
    
    st.markdown("---")
    
    # Display suggestions
    if suggestions:
        st.markdown("#### 🎯 Suggested Fixes:")
        
        tabs = st.tabs([s['title'] for s in suggestions])
        
        for tab, suggestion in zip(tabs, suggestions):
            with tab:
                for item in suggestion['items']:
                    st.markdown(f"✓ {item}")
    
    st.markdown("---")
    
    # Quick configuration buttons
    st.markdown("#### ⚡ Quick Configurations")
    
    st.markdown("""
    Try these preset configurations that are **guaranteed to trigger policies**:
    """)
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.info("""
        **🔥 High EV Demand**
        - Grid: 30 MW
        - Agents: 100
        - Initial EV: 25%
        - Eco Desire: 0.8
        
        *Triggers: Grid expansion, pricing*
        """)
    
    with col2:
        st.info("""
        **⚡ Grid Stress Test**
        - Grid: 20 MW
        - Agents: 150
        - Initial EV: 20%
        - Sparse chargers (0.5x)
        
        *Triggers: Critical alerts, load balancing*
        """)
    
    with col3:
        st.info("""
        **🚀 Rapid Adoption**
        - Grid: 150 MW
        - Agents: 200
        - Dense network
        - Strong social influence
        
        *Triggers: Tipping points, cascades*
        """)
    
    st.markdown("""
    **To use these:** Go to Sidebar → Configuration Presets → Select preset → Run simulation
    """)


def _render_configuration_recommendations(sim_state: Dict, config: Any, rules_triggered: int):
    """Provide specific configuration recommendations."""
    
    st.markdown("### 🎛️ Configuration Recommendations")
    
    ev_adoption = sim_state.get('ev_adoption', 0)
    grid_util = sim_state.get('grid_utilization', 0)
    
    # Create recommendation based on current state
    if rules_triggered == 0:
        st.markdown("""
        Based on your simulation results, here's a recommended configuration to see policy actions:
        """)
        
        # Calculate recommended values
        recommended_grid = max(20, config.grid_capacity_mw * 0.3)  # 30% of current or 20 MW
        recommended_agents = max(100, config.num_agents * 1.5)  # 1.5x agents or 100
        
        config_table = {
            'Parameter': [
                'Grid Capacity',
                'Number of Agents',
                'Initial EV Adoption',
                'Agent Eco Desire',
                'Grid Intervention Threshold'
            ],
            'Current': [
                f'{config.grid_capacity_mw:.0f} MW',
                f'{config.num_agents}',
                '5%',  # Default
                '0.5',  # Default
                '70%'  # Default
            ],
            'Recommended': [
                f'{recommended_grid:.0f} MW',
                f'{recommended_agents:.0f}',
                '20-25%',
                '0.7-0.9',
                '60%'
            ],
            'Why': [
                'Lower to create grid stress',
                'More agents = more load',
                'Higher starting adoption',
                'More eco-conscious agents',
                'Earlier intervention'
            ]
        }
        
        import pandas as pd
        df = pd.DataFrame(config_table)
        st.table(df)
        
    else:
        st.success("""
        ✅ Your configuration successfully triggered policy actions! 
        
        **Current settings are working well.**
        """)
        
        st.markdown(f"""
        - EV Adoption reached: **{ev_adoption*100:.1f}%**
        - Grid Utilization: **{grid_util*100:.1f}%**
        - Policy Rules Triggered: **{rules_triggered}**
        
        To experiment further, try:
        - Increasing agent count for more complex dynamics
        - Testing different combined scenarios
        - Adjusting social network parameters to see feedback effects
        """)