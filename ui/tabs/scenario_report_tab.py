"""
ui/tabs/scenario_report_tab.py

Scenario report visualization tab - extracted from main_tabs.py

"""

import streamlit as st
import sys
from pathlib import Path

parent_dir = Path(__file__).resolve().parent.parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from visualiser.visualization import render_scenario_report_tab

def render_scenario_report_tab(results):
    """
    Render scenario report visualization tab.
    
    Args:
        results: SimulationResults object
    """
    st.subheader("📋 Applied Scenario Report")
    
    report = results.scenario_report
    
    # Scenario overview
    st.markdown(f"### {report['name']}")
    st.write(report['description'])
    
    st.markdown("---")
    
    # Applied policies
    st.markdown("### 🔧 Applied Policies")
    
    for policy in report['policies']:
        with st.expander(f"{policy['parameter']} ({policy['target']})", expanded=True):
            col1, col2 = st.columns([1, 2])
            
            with col1:
                st.write(f"**Value:** {policy['value']}")
                if policy.get('mode'):
                    st.write(f"**Mode:** {policy['mode']}")
            
            with col2:
                # Describe what this policy does
                description = _get_policy_description(policy)
                st.info(description)
    
    st.markdown("---")
    
    # Expected outcomes
    st.markdown("### 🎯 Expected Outcomes")
    
    for outcome, value in report['expected_outcomes'].items():
        col1, col2 = st.columns([2, 1])
        with col1:
            st.write(outcome.replace('_', ' ').title())
        with col2:
            st.metric("", f"{value:+.1%}")


def _get_policy_description(policy):
    """Get human-readable description of policy."""
    param = policy['parameter']
    value = policy['value']
    mode = policy.get('mode', 'all modes')
    
    descriptions = {
        'cost_reduction': f"Reduces cost for {mode} by {value}%",
        'cost_multiplier': f"Multiplies cost for {mode} by {value}x",
        'speed_multiplier': f"Multiplies speed for {mode} by {value}x",
        'add_chargers': f"Adds {value} charging stations",
        'charging_cost_multiplier': f"Multiplies charging costs by {value}x",
        'increase_capacity': f"Increases grid capacity by {value}x",
    }
    
    return descriptions.get(param, f"Modifies {param} to {value}") 