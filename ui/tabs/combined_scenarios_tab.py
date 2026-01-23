"""
ui/tabs/combined_scenarios_tab.py

NEW Phase 5.1: Combined policy scenarios tab with interaction rules and feedback loops.
Extracted as separate tab module for maintainability.
"""

import streamlit as st
from pathlib import Path
import yaml
from typing import Dict, List
import sys

parent_dir = Path(__file__).resolve().parent.parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))


def render_combined_scenarios_tab(results, anim, current_data):
    """
    Render combined scenarios analysis tab.
    
    Shows:
    - Active combined scenario details
    - Policy actions taken during simulation
    - Constraint status (budget, grid, deployment)
    - Cost recovery metrics
    - Feedback loop effects
    
    Args:
        results: SimulationResults object with policy_actions, cost_recovery, etc.
        anim: AnimationController
        current_data: Current timestep data
    """
    
    st.subheader("🔗 Combined Policy Scenarios Analysis")
    
    # Check if combined scenario was used
    if not hasattr(results, 'policy_status') or results.policy_status is None:
        st.info("💡 No combined scenario was active for this simulation.")
        st.markdown("""
        **To use combined scenarios:**
        1. Go to Sidebar → Advanced: Combined Scenarios
        2. Select a predefined combined scenario
        3. Run simulation
        
        Combined scenarios allow you to:
        - Combine multiple policies (e.g., electrification + time-of-day pricing)
        - Apply dynamic interaction rules (grid stress → surge pricing)
        - Enforce constraints (budget, grid capacity)
        - Model feedback loops (adoption → infrastructure → adoption)
        """)
        return
    
    # Combined scenario was active - show full analysis
    policy_status = results.policy_status
    
    # Scenario Overview
    st.markdown(f"### 📋 {policy_status['scenario_name']}")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Base Scenarios", len(policy_status['base_scenarios']))
        for base in policy_status['base_scenarios']:
            st.caption(f"• {base}")
    
    with col2:
        # FIX: Show total rules defined, not just triggered
        total_rules = policy_status.get('total_interaction_rules', 0)
        rules_triggered = policy_status['rules_triggered']
        
        st.metric(
            "Interaction Rules", 
            f"{rules_triggered} / {total_rules}",
            delta=f"{rules_triggered} triggered",
            help=f"{total_rules} rules defined, {rules_triggered} actually triggered during simulation"
        )
        
        st.metric("Feedback Loops", policy_status['active_feedback_loops'])
    
    with col3:
        if 'ev_adoption' in policy_status['simulation_state']:
            st.metric("EV Adoption", f"{policy_status['simulation_state']['ev_adoption']:.1%}")
        if 'grid_utilization' in policy_status['simulation_state']:
            st.metric("Grid Utilization", f"{policy_status['simulation_state']['grid_utilization']:.1%}")
    
    st.markdown("---")
    
    # Policy Actions Taken
    if hasattr(results, 'policy_actions') and results.policy_actions:
        st.markdown("### ⚙️ Policy Actions Taken")
        
        for action in results.policy_actions:
            with st.expander(f"Step {action['step']}: {action['action']}", expanded=False):
                st.markdown(f"**Condition:** `{action['condition']}`")
                st.json(action['result'])
    
    else:
        st.info("No dynamic policy actions were triggered during this simulation.")
    
    st.markdown("---")
    
    # Constraint Status
    st.markdown("### ⚖️ Constraint Status")
    
    if 'constraints' in policy_status:
        constraints = policy_status['constraints']
        
        for const_name, const_data in constraints.items():
            col1, col2 = st.columns([2, 1])
            
            with col1:
                st.markdown(f"**{const_name.replace('_', ' ').title()}**")
                
                # Progress bar
                utilization = const_data['utilization']
                status = const_data['status']
                
                if status == 'exceeded':
                    st.error(f"❌ Limit exceeded: {utilization:.0%}")
                elif status == 'warning':
                    st.warning(f"⚠️ Warning: {utilization:.0%}")
                else:
                    st.success(f"✅ OK: {utilization:.0%}")
                
                st.progress(min(1.0, utilization))
            
            with col2:
                if const_name == 'budget':
                    st.metric("Limit", f"£{const_data['limit']:,.0f}")
                    st.metric("Used", f"£{const_data['current']:,.0f}")
                    st.metric("Remaining", f"£{const_data['remaining']:,.0f}")
                else:
                    st.metric("Limit", f"{const_data['limit']:,.0f}")
                    st.metric("Current", f"{const_data['current']:,.0f}")
    
    else:
        st.info("No constraints were defined for this scenario.")
    
    st.markdown("---")
    
    # Cost Recovery Analysis
    if hasattr(results, 'final_cost_recovery') and results.final_cost_recovery:
        st.markdown("### 💰 Infrastructure Cost Recovery")
        
        recovery = results.final_cost_recovery
        
        col1, col2, col3, col4 = st.columns(4)
        
        col1.metric("Total Investment", f"£{recovery['total_investment']:,.0f}")
        col2.metric("Total Revenue", f"£{recovery['total_revenue']:,.0f}")
        col3.metric("Profit/Loss", f"£{recovery['profit']:,.0f}")
        col4.metric("ROI", f"{recovery['roi_percentage']:.1f}%")
        
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.metric("Payback Period", f"{recovery['payback_years']:.1f} years")
        
        with col2:
            if recovery['break_even']:
                st.success("✅ Break-even achieved")
            else:
                st.warning("⚠️ Not yet break-even")
        
        # Cost recovery over time
        if hasattr(results, 'cost_recovery_history') and results.cost_recovery_history:
            st.markdown("#### 📊 Cost Recovery Over Time")
            
            import plotly.graph_objects as go
            
            steps = [h['step'] for h in results.cost_recovery_history]
            revenue = [h['total_revenue'] for h in results.cost_recovery_history]
            costs = [h['total_investment'] + h['operating_costs'] for h in results.cost_recovery_history]
            
            fig = go.Figure()
            
            fig.add_trace(go.Scatter(
                x=steps,
                y=revenue,
                name='Revenue',
                line=dict(color='green', width=2)
            ))
            
            fig.add_trace(go.Scatter(
                x=steps,
                y=costs,
                name='Costs',
                line=dict(color='red', width=2)
            ))
            
            fig.update_layout(
                title="Infrastructure Cost Recovery",
                xaxis_title="Simulation Step",
                yaxis_title="Amount (£)",
                hovermode='x unified'
            )
            
            st.plotly_chart(fig, use_container_width=True)
    
    else:
        st.info("Cost recovery tracking not enabled for this scenario.")
    
    st.markdown("---")
    
    # Constraint Violations (if any)
    if hasattr(results, 'constraint_violations') and results.constraint_violations:
        st.markdown("### ⚠️ Constraint Violations")
        
        for violation in results.constraint_violations:
            if violation['type'] == 'violation':
                st.error(f"❌ {violation['constraint']}: {violation['utilization']:.0%} (Limit: {violation['limit']})")
            else:
                st.warning(f"⚠️ {violation['constraint']}: {violation['utilization']:.0%} (Limit: {violation['limit']})")
    
    st.markdown("---")
    
    # Simulation State Summary
    with st.expander("📊 Final Simulation State", expanded=False):
        st.json(policy_status['simulation_state'])


def render_combined_scenario_builder():
    """
    Optional: Separate page for building custom combined scenarios.
    Can be called from sidebar or main menu.
    """
    
    st.header("🎨 Combined Scenario Builder")
    
    st.markdown("""
    Build custom policy combinations with dynamic interaction rules.
    """)
    
    # Load available base scenarios
    scenarios_dir = Path(__file__).parent.parent.parent / 'scenarios' / 'configs'
    available_scenarios = []
    
    if scenarios_dir.exists():
        for yaml_file in scenarios_dir.glob('*.yaml'):
            available_scenarios.append(yaml_file.stem)
    
    if not available_scenarios:
        st.warning("⚠️ No base scenarios found in scenarios/configs/")
        return
    
    # Scenario selection
    st.markdown("### 1️⃣ Select Base Scenarios")
    selected_scenarios = st.multiselect(
        "Choose 2-4 base scenarios to combine",
        options=sorted(available_scenarios),
        help="Select multiple scenarios that will be active simultaneously"
    )
    
    if len(selected_scenarios) < 2:
        st.info("💡 Select at least 2 scenarios to create a combination")
        return
    
    # Name and description
    st.markdown("### 2️⃣ Name Your Combined Scenario")
    custom_name = st.text_input("Scenario Name", "My Custom Scenario")
    custom_desc = st.text_area("Description", "Custom policy combination")
    
    # Add interaction rules
    st.markdown("### 3️⃣ Add Interaction Rules")
    
    num_rules = st.number_input("Number of interaction rules", 0, 10, 1, 1)
    
    rules = []
    for i in range(num_rules):
        with st.expander(f"Rule {i+1}"):
            condition = st.text_input(
                "Condition (Python expression)",
                "grid_utilization > 0.8",
                key=f"cond_{i}",
                help="Use: grid_utilization, ev_adoption, charger_utilization, step, time_of_day"
            )
            
            action = st.selectbox(
                "Action",
                [
                    "apply_surge_pricing",
                    "increase_charging_cost",
                    "add_emergency_chargers",
                    "reduce_ev_subsidy",
                    "enable_smart_charging"
                ],
                key=f"action_{i}"
            )
            
            priority = st.slider("Priority (higher = evaluated first)", 0, 100, 50, 10, key=f"priority_{i}")
            
            # Action parameters
            st.caption("Action Parameters")
            params = {}
            
            if action == "apply_surge_pricing":
                multiplier = st.slider("Price Multiplier", 1.0, 3.0, 2.0, 0.1, key=f"mult_{i}")
                params = {"multiplier": multiplier}
            
            elif action == "add_emergency_chargers":
                num_chargers = st.number_input("Number of Chargers", 5, 50, 10, 5, key=f"num_{i}")
                strategy = st.selectbox("Placement Strategy", 
                                      ["demand_heatmap", "coverage_gaps", "equitable"], 
                                      key=f"strat_{i}")
                params = {"num_chargers": num_chargers, "strategy": strategy}
            
            elif action == "increase_charging_cost":
                params = {"reason": "infrastructure_cost_recovery"}
            
            rules.append({
                "condition": condition,
                "action": action,
                "parameters": params,
                "priority": priority
            })
    
    # Add constraints
    st.markdown("### 4️⃣ Set Constraints")
    
    col1, col2, col3 = st.columns(3)
    
    constraints = []
    
    with col1:
        budget_enabled = st.checkbox("Budget Constraint")
        if budget_enabled:
            budget_limit = st.number_input(
                "Budget (£)", 
                1000000, 
                500000000, 
                50000000,
                1000000,
                key="budget"
            )
            constraints.append({
                "type": "budget",
                "limit": budget_limit,
                "warning_threshold": 0.8
            })
    
    with col2:
        grid_enabled = st.checkbox("Grid Capacity")
        if grid_enabled:
            grid_limit = st.number_input(
                "Grid Capacity (MW)",
                100,
                5000,
                1000,
                100,
                key="grid"
            )
            constraints.append({
                "type": "grid_capacity",
                "limit": grid_limit,
                "warning_threshold": 0.85
            })
    
    with col3:
        deploy_enabled = st.checkbox("Deployment Rate")
        if deploy_enabled:
            deploy_limit = st.number_input(
                "Max Chargers/Year",
                100,
                10000,
                5000,
                100,
                key="deploy"
            )
            constraints.append({
                "type": "deployment_rate",
                "limit": deploy_limit,
                "warning_threshold": 0.9
            })
    
    # Preview
    st.markdown("### 📄 Preview")
    
    custom_scenario = {
        "name": custom_name,
        "description": custom_desc,
        "base_scenarios": selected_scenarios,
        "interaction_rules": rules,
        "constraints": constraints,
        "feedback_loops": [],
        "expected_outcomes": {}
    }
    
    with st.expander("YAML Preview"):
        st.code(yaml.dump(custom_scenario, default_flow_style=False, sort_keys=False), language="yaml")
    
    # Save and use
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("💾 Save to File", use_container_width=True):
            save_path = Path(__file__).parent.parent.parent / 'scenarios' / 'combined_configs' / f"{custom_name.lower().replace(' ', '_')}.yaml"
            save_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(save_path, 'w') as f:
                yaml.dump(custom_scenario, f, default_flow_style=False, sort_keys=False)
            
            st.success(f"✅ Saved to {save_path.name}")
    
    with col2:
        if st.button("✅ Use This Scenario", type="primary", use_container_width=True):
            st.session_state.selected_combined_scenario = custom_name
            st.session_state.combined_scenario_data = custom_scenario
            st.success(f"✅ Selected: {custom_name}")
            st.info("Go to sidebar and run simulation with this scenario")