"""
ui/widgets/policy_status_widget.py

Live policy status widget for map tab.
Shows real-time policy metrics and alerts.
"""

import streamlit as st
from typing import Dict, Any, List, Optional


def render_policy_status_widget(results, current_step: int, config):
    """
    Render live policy status widget on map tab.
    
    Shows:
    - Current EV adoption %
    - Grid load and utilization
    - Active policies count
    - Recent policy triggers
    
    Args:
        results: SimulationResults with policy data
        current_step: Current simulation step
        config: SimulationConfig
    """
    
    # Only show if combined scenario is active
    if not hasattr(results, 'policy_status') or not results.policy_status:
        return
    
    # Container for widget
    with st.container():
        st.markdown("### 🎛️ Live Policy Status")
        
        # Get current timestep data
        if isinstance(results.time_series, list):
            current_data = results.time_series[current_step] if current_step < len(results.time_series) else None
        else:
            current_data = results.time_series.get_timestep(current_step)
        
        if not current_data:
            st.warning("No data for current step")
            return
        
        # Calculate current metrics
        agent_states = current_data.get('agent_states', [])
        
        # EV adoption
        ev_modes = ['ev', 'van_electric', 'truck_electric', 'hgv_electric']
        ev_count = sum(1 for agent in agent_states if agent.get('mode') in ev_modes)
        total_agents = len(agent_states)
        ev_adoption = ev_count / total_agents if total_agents > 0 else 0.0
        
        # Grid metrics (from infrastructure if available)
        grid_load_mw = 0.0
        grid_util = 0.0
        charger_util = 0.0
        
        if results.infrastructure:
            try:
                grid_util = results.infrastructure.grid.get_utilization()
                grid_load_mw = results.infrastructure.grid.current_load_mw
                metrics = results.infrastructure.get_infrastructure_metrics()
                charger_util = metrics.get('charger_utilization', 0.0)
            except:
                pass
        
        # Display metrics in columns
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            delta = "📈" if ev_adoption > 0.15 else None
            st.metric(
                "EV Adoption",
                f"{ev_adoption*100:.1f}%",
                delta=delta,
                help="Current percentage of agents using electric vehicles"
            )
        
        with col2:
            delta_color = "normal" if grid_util < 0.7 else "inverse"
            st.metric(
                "Grid Load",
                f"{grid_load_mw:.1f} MW",
                delta=f"{grid_util*100:.0f}%",
                delta_color=delta_color,
                help="Current grid utilization"
            )
        
        with col3:
            active_policies = results.policy_status.get('active_feedback_loops', 0)
            rules_triggered = results.policy_status.get('rules_triggered', 0)
            st.metric(
                "Active Policies",
                active_policies,
                delta=f"{rules_triggered} triggered",
                help="Number of active feedback loops and triggered rules"
            )
        
        with col4:
            delta_color = "normal" if charger_util < 0.8 else "inverse"
            st.metric(
                "Charger Load",
                f"{charger_util*100:.0f}%",
                delta_color=delta_color,
                help="Charging station utilization"
            )
        
        # Alerts and status messages
        _render_policy_alerts(ev_adoption, grid_util, charger_util, results.policy_status, config)
        
        # Recent policy actions (last 3)
        if hasattr(results, 'policy_actions') and results.policy_actions:
            recent_actions = [a for a in results.policy_actions if a['step'] <= current_step]
            if recent_actions:
                _render_recent_actions(recent_actions[-3:])


def _render_policy_alerts(ev_adoption: float, grid_util: float, charger_util: float, 
                          policy_status: Dict, config):
    """Render alert messages based on current metrics."""
    
    alerts = []
    
    # EV adoption alerts
    ev_target = config.policy.thresholds.ev_adoption_target
    if ev_adoption >= ev_target:
        alerts.append(("success", f"✅ EV adoption target reached ({ev_adoption*100:.0f}% ≥ {ev_target*100:.0f}%)"))
    elif ev_adoption >= ev_target * 0.8:
        alerts.append(("info", f"📊 Approaching EV target ({ev_adoption*100:.0f}% / {ev_target*100:.0f}%)"))
    
    # Grid alerts
    grid_intervention = config.policy.thresholds.grid_intervention_threshold
    grid_critical = config.policy.thresholds.grid_critical_threshold
    
    if grid_util >= grid_critical:
        alerts.append(("error", f"🚨 CRITICAL: Grid at {grid_util*100:.0f}% capacity!"))
    elif grid_util >= grid_intervention:
        alerts.append(("warning", f"⚠️ Grid intervention threshold reached ({grid_util*100:.0f}%)"))
    
    # Charger alerts
    if charger_util >= 0.9:
        alerts.append(("warning", f"⚡ Chargers heavily loaded ({charger_util*100:.0f}%)"))
    
    # Policy trigger alerts
    rules_triggered = policy_status.get('rules_triggered', 0)
    if rules_triggered > 0:
        alerts.append(("info", f"🎯 {rules_triggered} policy rule(s) active"))
    
    # Display alerts
    if alerts:
        st.markdown("#### 🔔 Status Alerts")
        for alert_type, message in alerts:
            if alert_type == "success":
                st.success(message)
            elif alert_type == "warning":
                st.warning(message)
            elif alert_type == "error":
                st.error(message)
            else:
                st.info(message)


def _render_recent_actions(recent_actions: List[Dict]):
    """Render recent policy actions."""
    
    with st.expander(f"📋 Recent Policy Actions ({len(recent_actions)})", expanded=False):
        for action in reversed(recent_actions):  # Most recent first
            step = action.get('step', 0)
            action_name = action.get('action', 'Unknown')
            condition = action.get('condition', 'N/A')
            
            st.markdown(f"**Step {step}:** {action_name}")
            st.caption(f"Trigger: {condition}")
            st.markdown("---")


def render_compact_policy_status(results, current_step: int):
    """
    Render ultra-compact policy status (single line).
    
    For minimal space usage on map tab.
    """
    
    if not hasattr(results, 'policy_status') or not results.policy_status:
        return
    
    # Get current data
    if isinstance(results.time_series, list):
        current_data = results.time_series[current_step] if current_step < len(results.time_series) else None
    else:
        current_data = results.time_series.get_timestep(current_step)
    
    if not current_data:
        return
    
    agent_states = current_data.get('agent_states', [])
    ev_modes = ['ev', 'van_electric', 'truck_electric', 'hgv_electric']
    ev_count = sum(1 for agent in agent_states if agent.get('mode') in ev_modes)
    total_agents = len(agent_states)
    ev_adoption = ev_count / total_agents if total_agents > 0 else 0.0
    
    # Get grid utilization
    grid_util = 0.0
    if results.infrastructure:
        try:
            grid_util = results.infrastructure.grid.get_utilization()
        except:
            pass
    
    # Single line status
    rules_triggered = results.policy_status.get('rules_triggered', 0)
    scenario_name = results.policy_status.get('scenario_name', 'Unknown')
    
    status_icon = "🟢" if rules_triggered > 0 else "🟡"
    
    st.caption(
        f"{status_icon} **{scenario_name}** | "
        f"EV: {ev_adoption*100:.0f}% | "
        f"Grid: {grid_util*100:.0f}% | "
        f"Policies: {rules_triggered}"
    )


def render_policy_timeline(results, current_step: int):
    """
    Render policy timeline showing when actions occurred.
    
    Visual timeline of policy triggers throughout simulation.
    """
    
    if not hasattr(results, 'policy_actions') or not results.policy_actions:
        st.info("No policy actions triggered yet")
        return
    
    st.markdown("#### 📅 Policy Action Timeline")
    
    # Filter actions up to current step
    past_actions = [a for a in results.policy_actions if a['step'] <= current_step]
    
    if not past_actions:
        st.info(f"No policy actions before step {current_step}")
        return
    
    # Create timeline visualization
    total_steps = current_step + 1
    
    for action in past_actions:
        step = action['step']
        action_name = action['action']
        
        # Progress bar showing when action occurred
        progress = step / total_steps
        
        col1, col2 = st.columns([3, 1])
        
        with col1:
            st.progress(progress, text=f"Step {step}: {action_name}")
        
        with col2:
            st.caption(f"{progress*100:.0f}%")