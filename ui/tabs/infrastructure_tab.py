# ============================================================================
# ui/tabs/infrastructure_tab.py
# ============================================================================

"""
ui/tabs/infrastructure_tab.py

Infrastructure visualization tab - extracted from main_tabs.py

"""

import streamlit as st
import sys
from pathlib import Path

parent_dir = Path(__file__).resolve().parent.parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from visualiser.visualization import render_infrastructure_metrics

def render_infrastructure_tab(results, anim, current_data):  # FIXED: Added anim, current_data
    """
    Render infrastructure metrics tab.
    
    Args:
        results: SimulationResults object
        anim: AnimationController (not used but kept for consistency)
        current_data: Current timestep data (not used but kept for consistency)
    """
    st.subheader("🔌 Infrastructure Metrics")
    
    infra_data = render_infrastructure_metrics(results.infrastructure)
    metrics = infra_data['metrics']
    
    # Current metrics
    col1, col2, col3, col4 = st.columns(4)
    
    col1.metric(
        "Charger Utilization",
        f"{metrics['utilization']:.1%}",
        delta="High" if metrics['utilization'] > 0.7 else "Normal"
    )
    
    col2.metric(
        "Grid Load",
        f"{metrics['grid_load_mw']:.1f} MW",
        delta=f"{metrics['grid_utilization']:.0%}"
    )
    
    col3.metric(
        "Queued Agents",
        metrics['queued_agents'],
        delta="⚠️" if metrics['queued_agents'] > 10 else "✅"
    )
    
    col4.metric(
        "Hotspots",
        len(infra_data['hotspots']),
        delta="Critical" if len(infra_data['hotspots']) > 5 else "OK"
    )
    
    st.markdown("---")
    
    # Grid utilization over time
    if infra_data['grid_figure']:
        st.markdown("### ⚡ Grid Utilization Over Time")
        st.plotly_chart(infra_data['grid_figure'], use_container_width=True)
        
        # Add capacity info
        st.info(f"📊 **Grid Capacity**: {metrics['grid_capacity_mw']:.0f} MW | "
                f"**Peak Load**: {max(results.infrastructure.historical_utilization) * 100:.1f}% | "
                f"**Average Load**: {sum(results.infrastructure.historical_utilization) / len(results.infrastructure.historical_utilization) * 100:.1f}%")
    
    # Charging station map
    st.markdown("---")
    st.markdown("### 🗺️ Charging Station Coverage")
    st.info("💡 Charger locations shown on main map when 'Show Infrastructure' is enabled")
