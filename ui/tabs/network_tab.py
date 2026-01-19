"""
ui/tabs/network_tab.py

Network visualization tab - extracted from main_tabs.py

"""
import streamlit as st
import sys
from pathlib import Path

parent_dir = Path(__file__).resolve().parent.parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from visualiser.visualization import render_cascade_chart

def render_network_tab(results, anim, agent_states):
    """
    Render network visualization tab.
    
    Args:
        results: SimulationResults object
        anim: AnimationController
        agent_states: Current agent states
    """
    # st.subheader("🌐 Network Overview")
    
    # # Render network graph
    # graph = render_network_graph(
    #     agent_states=agent_states,
    #     infrastructure_manager=results.infrastructure,
    #     current_step=anim.current_step,
    #     total_steps=anim.total_steps,
    # )
    
    # st.altair_chart(graph, use_container_width=True)

    st.subheader("🌐 Social Network Analysis")
    
    if results.network:
        net_metrics = results.network.get_network_metrics()
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Connections", net_metrics.total_ties)
        col2.metric("Avg Degree", f"{net_metrics.avg_degree:.1f}")
        col3.metric("Clustering", f"{net_metrics.clustering_coefficient:.2f}")
        
        if results.cascade_events:
            st.markdown("### 🌊 Cascade Events")
            fig = render_cascade_chart(results.cascade_events)
            if fig:
                st.plotly_chart(fig, width='stretch')
    else:
        st.info("Social network not enabled")