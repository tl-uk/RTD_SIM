"""
ui/diagnostics_panel.py

Phase 4.5F+G: Comprehensive freight + multi-modal diagnostics
"""

import streamlit as st
import pandas as pd


def render_diagnostics_panel(results):
    """
    Render diagnostics panel in sidebar with ALL modes (4.5F+G).
    
    Args:
        results: SimulationResults object
    """
    if not results:
        return
    
    with st.expander("🔍 Infrastructure Diagnostics", expanded=False):
        # Mode distribution - includes Phase 4.5G multi-modal
        _render_mode_distribution(results)
        
        st.markdown("---")
        
        # Freight analysis (Phase 4.5F)
        _render_freight_analysis(results)
        
        st.markdown("---")
        
        # Grid & charging
        if results.infrastructure:
            _render_grid_analysis(results)
        
        st.markdown("---")
        
        # Sample agents
        _render_sample_agents(results)


def _render_mode_distribution(results):
    """Render mode distribution table with ALL modes (4.5F+G)."""
    st.markdown("### 📊 Mode Distribution Analysis")
    
    mode_counts = {}
    for agent in results.agents:
        mode = agent.state.mode
        mode_counts[mode] = mode_counts.get(mode, 0) + 1
    
    # ALL MODES including Phase 4.5G multi-modal
    all_modes = [
        'walk', 'bike', 'cargo_bike', 'e_scooter',
        'bus', 'car', 'ev',
        'tram', 'local_train', 'intercity_train',
        'ferry_diesel', 'ferry_electric',
        'flight_domestic', 'flight_electric',
        'van_electric', 'van_diesel',
        'truck_electric', 'truck_diesel',
        'hgv_electric', 'hgv_diesel', 'hgv_hydrogen'
    ]
    
    mode_data = []
    for mode in all_modes:
        count = mode_counts.get(mode, 0)
        pct = (count / len(results.agents) * 100) if results.agents else 0
        
        # Show all non-zero modes + core modes
        if count > 0 or mode in ['walk', 'bike', 'bus', 'car', 'ev']:
            mode_data.append({
                'Mode': mode.replace('_', ' ').title(),
                'Count': count,
                'Percentage': f"{pct:.1f}%"
            })
    
    df = pd.DataFrame(mode_data)
    st.dataframe(df, use_container_width=True, hide_index=True)
    
    # Freight highlight (Phase 4.5F)
    freight_modes = ['van_electric', 'van_diesel', 'truck_electric', 'truck_diesel', 
                    'hgv_electric', 'hgv_diesel', 'hgv_hydrogen', 'cargo_bike']
    freight_count = sum(mode_counts.get(m, 0) for m in freight_modes)
    
    if freight_count > 0:
        freight_pct = freight_count / len(results.agents) * 100
        st.success(f"✅ Freight active: {freight_count}/{len(results.agents)} ({freight_pct:.1f}%)")
        
        # Breakdown by freight type
        with st.expander("🚛 Freight Mode Breakdown"):
            for mode in freight_modes:
                count = mode_counts.get(mode, 0)
                if count > 0:
                    pct = count / freight_count * 100
                    st.write(f"**{mode.replace('_', ' ').title()}**: {count} ({pct:.1f}% of freight)")
    
    # Multi-modal highlight (Phase 4.5G)
    multimodal_modes = ['tram', 'local_train', 'intercity_train', 'ferry_diesel', 
                        'ferry_electric', 'flight_domestic', 'e_scooter']
    multimodal_count = sum(mode_counts.get(m, 0) for m in multimodal_modes)
    
    if multimodal_count > 0:
        multimodal_pct = multimodal_count / len(results.agents) * 100
        st.info(f"🚆 Multi-modal active: {multimodal_count}/{len(results.agents)} ({multimodal_pct:.1f}%)")


def _render_freight_analysis(results):
    """Render freight agent analysis (Phase 4.5F)."""
    st.markdown("### 🚚 Freight Analysis")
    
    # Count vehicle_required agents
    vehicle_required_count = sum(
        1 for a in results.agents 
        if hasattr(a, 'agent_context') 
        and a.agent_context.get('vehicle_required', False)
    )
    
    st.write(f"**Agents with vehicle_required:** {vehicle_required_count}/{len(results.agents)}")
    
    if vehicle_required_count == 0:
        st.warning("⚠️ No freight agents found - check job_contexts.yaml")
        return
    
    # Vehicle type distribution
    vehicle_types = {}
    for agent in results.agents:
        if hasattr(agent, 'agent_context') and agent.agent_context.get('vehicle_required'):
            vtype = agent.agent_context.get('vehicle_type', 'unknown')
            vehicle_types[vtype] = vehicle_types.get(vtype, 0) + 1
    
    if vehicle_types:
        st.write("**Vehicle Type Distribution:**")
        for vtype, count in sorted(vehicle_types.items(), key=lambda x: x[1], reverse=True):
            pct = count / vehicle_required_count * 100
            st.write(f"- {vtype}: {count} ({pct:.1f}%)")
    
    # Job distribution (top 10)
    job_types = {}
    for agent in results.agents:
        job_id = getattr(agent, 'job_story_id', 'unknown')
        job_types[job_id] = job_types.get(job_id, 0) + 1
    
    with st.expander("📦 Job Distribution"):
        for job_id, count in sorted(job_types.items(), key=lambda x: x[1], reverse=True)[:10]:
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
    port_pct = (occupied / total_ports * 100) if total_ports > 0 else 0
    st.write(f"**Ports:** {occupied}/{total_ports} ({port_pct:.1f}%)")


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

    # Freight agent debug
    st.markdown("### 🔎 Freight Agent Debug")
    freight_agents = [
        a for a in results.agents 
        if hasattr(a, 'agent_context') and a.agent_context.get('vehicle_required')
    ]
    
    if freight_agents:
        fa = freight_agents[0]
        st.code(f"""
Freight Agent: {fa.state.agent_id}
Job: {fa.job_story_id}
Mode: {fa.state.mode}
Distance: {fa.state.distance_km:.1f} km
agent_context: {fa.agent_context}
vehicle_type: {fa.agent_context.get('vehicle_type')}
        """)
    else:
        st.write("No freight agents found")