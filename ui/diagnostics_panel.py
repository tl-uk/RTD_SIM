"""
ui/diagnostics_panel.py

Compact infrastructure diagnostics panel with expandable sections.
Shows mode distribution, freight analysis, grid status, and sample agents.
"""

import streamlit as st
import pandas as pd


def render_diagnostics_panel(results):
    """
    Render diagnostics panel in sidebar.
    
    Args:
        results: SimulationResults object
    """
    if not results:
        return
    
    with st.expander("🔍 Infrastructure Diagnostics", expanded=False):
        # Mode distribution
        _render_mode_distribution(results)
        
        st.markdown("---")
        
        # Freight analysis
        _render_freight_analysis(results)
        
        st.markdown("---")
        
        # Grid & charging
        if results.infrastructure:
            _render_grid_analysis(results)
        
        st.markdown("---")
        
        # Sample agents
        _render_sample_agents(results)


def _render_mode_distribution(results):
    """Render mode distribution table."""
    st.markdown("### 📊 Mode Distribution")
    
    mode_counts = {}
    for agent in results.agents:
        mode = agent.state.mode
        mode_counts[mode] = mode_counts.get(mode, 0) + 1
    
    mode_data = []
    for mode in ['walk', 'bike', 'bus', 'car', 'ev', 'van_electric', 'van_diesel']:
        count = mode_counts.get(mode, 0)
        pct = (count / len(results.agents) * 100) if results.agents else 0
        mode_data.append({
            'Mode': mode,
            'Count': count,
            'Percentage': f"{pct:.1f}%"
        })
    
    df = pd.DataFrame(mode_data)
    st.dataframe(df, use_container_width=True, hide_index=True)
    
    # Freight highlight
    freight_count = mode_counts.get('van_electric', 0) + mode_counts.get('van_diesel', 0)
    if freight_count == 0:
        st.error(f"❌ NO FREIGHT MODES ({freight_count}/{len(results.agents)})")
    else:
        st.success(f"✅ Freight active: {freight_count}/{len(results.agents)} ({freight_count/len(results.agents)*100:.1f}%)")


def _render_freight_analysis(results):
    """Render freight agent analysis."""
    st.markdown("### 🚚 Freight Analysis")
    
    # Count vehicle_required agents
    vehicle_required_count = sum(
        1 for a in results.agents 
        if hasattr(a, 'agent_context') 
        and a.agent_context.get('vehicle_required', False)
    )
    
    st.write(f"**Agents with vehicle_required:** {vehicle_required_count}/{len(results.agents)}")
    
    if vehicle_required_count == 0:
        st.error("❌ No freight agents found - check job_contexts.yaml")
    
    # Job distribution
    job_types = {}
    for agent in results.agents:
        job_id = getattr(agent, 'job_story_id', 'unknown')
        job_types[job_id] = job_types.get(job_id, 0) + 1
    
    with st.expander("Job Distribution"):
        for job_id, count in sorted(job_types.items(), key=lambda x: x[1], reverse=True)[:5]:
            st.write(f"- {job_id}: {count}")


def _render_grid_analysis(results):
    """Render grid and charging analysis."""
    st.markdown("### ⚡ Grid & Charging")
    
    current_charging = len(results.infrastructure.agent_charging_state)
    grid = results.infrastructure.grid_regions['default']
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.metric("Charging", current_charging)
        st.metric("Load", f"{grid.current_load_mw:.2f} MW")
    
    with col2:
        st.metric("Capacity", f"{grid.capacity_mw:.0f} MW")
        st.metric("Utilization", f"{grid.utilization():.1%}")
    
    # Occupied ports
    occupied = sum(s.currently_occupied for s in results.infrastructure.charging_stations.values())
    total_ports = sum(s.num_ports for s in results.infrastructure.charging_stations.values())
    st.write(f"**Ports:** {occupied}/{total_ports} ({occupied/total_ports*100:.1f}%)")


def _render_sample_agents(results):
    """Render sample agent details."""
    st.markdown("### 🎭 Sample Agents")
    
    for i, agent in enumerate(results.agents[:3]):
        with st.expander(f"Agent {i+1}: {agent.state.agent_id}", expanded=False):
            st.write(f"**Mode:** {agent.state.mode}")
            st.write(f"**Distance:** {agent.state.distance_km:.1f} km")
            st.write(f"**Arrived:** {agent.state.arrived}")
            
            context = getattr(agent, 'agent_context', {})
            if context:
                st.json(context)

    # Fright agent debug:
    st.markdown("### 🔍 Freight Agent Debug")
    freight_agents = [
        a for a in results.agents 
        if 'freight' in a.job_story_id or 'delivery' in a.job_story_id
    ]
    if freight_agents:
        fa = freight_agents[0]
        st.code(f"""
    Freight Agent: {fa.state.agent_id}
    Job: {fa.job_story_id}
    Mode: {fa.state.mode}
    agent_context: {fa.agent_context}
    task_context.parameters: {fa.task_context.parameters if hasattr(fa, 'task_context') else 'N/A'}
        """)
    else:
        st.write("No freight agents found")