"""
ui/report_generator.py

On-demand report generation from simulation results
Generates text and CSV reports summarizing key metrics, SD results, and configuration
Phase 5.3: Report Generator for SD insights

"""

import streamlit as st
from pathlib import Path
from datetime import datetime
from typing import Dict, Any
import csv


def generate_text_report(results, config) -> str:
    """
    Generate text report from simulation results.
    
    Args:
        results: SimulationResults object
        config: SimulationConfig object
    
    Returns:
        Report as formatted string
    """
    
    report = []
    report.append("=" * 80)
    report.append("SIMULATION REPORT")
    report.append("=" * 80)
    report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("")
    
    # Configuration
    report.append("CONFIGURATION")
    report.append("-" * 80)
    report.append(f"Steps:             {config.steps}")
    report.append(f"Agents:            {config.num_agents}")
    report.append(f"Location:          {config.place if config.place else 'Custom'}")
    
    if results.infrastructure:
        try:
            infra_metrics = results.infrastructure.get_infrastructure_metrics()
            report.append(f"Grid Capacity:     {infra_metrics.get('grid_capacity_mw', 0):.1f} MW")
            report.append(f"Chargers:          {infra_metrics.get('total_chargers', 0)}")
        except:
            pass
    
    report.append("")
    
    # System Dynamics Parameters
    if hasattr(config, 'system_dynamics') and config.system_dynamics:
        sd = config.system_dynamics
        report.append("SYSTEM DYNAMICS PARAMETERS")
        report.append("-" * 80)
        report.append(f"Growth Rate (r):         {getattr(sd, 'ev_growth_rate_r', 0.05):.5f}")
        report.append(f"Carrying Capacity (K):   {getattr(sd, 'ev_carrying_capacity_K', 0.80):.1%}")
        report.append(f"Infrastructure Feedback: {getattr(sd, 'infrastructure_feedback_strength', 0.02):.5f}")
        report.append(f"Social Influence:        {getattr(sd, 'social_influence_strength', 0.03):.5f}")
        report.append("")
    
    # General Results
    report.append("GENERAL RESULTS")
    report.append("-" * 80)
    report.append(f"Success:           {'✅ Yes' if results.success else '❌ No'}")
    
    # Count agents from final timestep
    if hasattr(results, 'time_series') and results.time_series:
        if isinstance(results.time_series, list):
            final_data = results.time_series[-1] if results.time_series else None
        else:
            final_data = results.time_series.get_timestep(config.steps - 1)
        
        if final_data and 'agent_states' in final_data:
            total_agents = len(final_data['agent_states'])
            report.append(f"Total Agents:      {total_agents}")
            
            # Count EV adoption
            ev_modes = {'ev', 'van_electric', 'truck_electric', 'hgv_electric'}
            ev_count = sum(1 for agent in final_data['agent_states'] 
                          if agent.get('mode') in ev_modes)
            ev_pct = (ev_count / total_agents * 100) if total_agents > 0 else 0
            report.append(f"EV Adoption (Agents): {ev_pct:.1f}%")
    
    if hasattr(results, 'cascade_events'):
        report.append(f"Cascades Detected: {len(results.cascade_events)}")
    
    report.append("")
    
    # System Dynamics Results
    if hasattr(results, 'system_dynamics_history') and results.system_dynamics_history:
        sd_history = results.system_dynamics_history
        
        report.append("SYSTEM DYNAMICS RESULTS")
        report.append("-" * 80)
        
        initial = sd_history[0]
        final = sd_history[-1]
        
        report.append(f"Initial Adoption:  {initial['ev_adoption']:.1%}")
        report.append(f"Final Adoption:    {final['ev_adoption']:.1%}")
        
        # Find peak
        peak_adoption = max(h['ev_adoption'] for h in sd_history)
        peak_step = next(i for i, h in enumerate(sd_history) if h['ev_adoption'] == peak_adoption)
        report.append(f"Peak Adoption:     {peak_adoption:.1%} (step {peak_step})")
        
        growth = final['ev_adoption'] - initial['ev_adoption']
        report.append(f"Growth:            {growth:+.1%}")
        report.append("")
        
        # Flow statistics
        flows = [h['ev_adoption_flow'] for h in sd_history]
        avg_flow = sum(flows) / len(flows) if flows else 0
        max_flow = max(flows) if flows else 0
        final_flow = final['ev_adoption_flow']
        
        report.append(f"Average Flow:      {avg_flow:.5f}")
        report.append(f"Max Flow:          {max_flow:.5f}")
        report.append(f"Final Flow:        {final_flow:.5f}")
        report.append("")
        
        # Flow decomposition (if available)
        if 'ev_growth_rate_r' in final and 'ev_carrying_capacity_K' in final:
            r = final['ev_growth_rate_r']
            K = final['ev_carrying_capacity_K']
            EV = final['ev_adoption']
            
            logistic = r * EV * (1 - EV / K) if K > 0 else 0
            infrastructure = 0.02 * EV * 1.0  # Default feedback
            social = 0.03 * EV * (1 - EV)
            
            report.append("FLOW DECOMPOSITION (Final Step)")
            report.append(f"  Logistic:        {logistic:.5f}")
            report.append(f"  Infrastructure:  {infrastructure:.5f}")
            report.append(f"  Social:          {social:.5f}")
            report.append("")
        
        # Tipping point
        tipping_crossed = any(
            h.get('thresholds_crossed', {}).get('adoption_tipping_point', False)
            for h in sd_history
        )
        
        if tipping_crossed:
            # Find when it crossed
            for i, h in enumerate(sd_history):
                if h.get('thresholds_crossed', {}).get('adoption_tipping_point', False):
                    report.append(f"🎯 Tipping Point:  CROSSED at step {i}")
                    break
        else:
            report.append("🎯 Tipping Point:  NOT REACHED")
        
        report.append("")
    
    # Grid metrics
    if results.infrastructure:
        try:
            grid_metrics = results.infrastructure.get_infrastructure_metrics()
            report.append(f"Grid Load:         {grid_metrics.get('grid_load_mw', 0):.1f} MW")
            report.append(f"Grid Utilization:  {grid_metrics.get('grid_utilization', 0):.1%}")
        except:
            pass
        
        report.append("")
    
    # Mode distribution
    if hasattr(results, 'time_series') and results.time_series:
        if isinstance(results.time_series, list):
            final_data = results.time_series[-1] if results.time_series else None
        else:
            final_data = results.time_series.get_timestep(config.steps - 1)
        
        if final_data and 'agent_states' in final_data:
            report.append("MODE DISTRIBUTION (Final Step)")
            report.append("-" * 80)
            
            mode_counts = {}
            for agent in final_data['agent_states']:
                mode = agent.get('mode', 'unknown')
                mode_counts[mode] = mode_counts.get(mode, 0) + 1
            
            total = sum(mode_counts.values())
            
            # Sort by count descending
            for mode, count in sorted(mode_counts.items(), key=lambda x: x[1], reverse=True):
                pct = (count / total * 100) if total > 0 else 0
                report.append(f"  {mode:20} {count:3} ({pct:5.1f}%)")
            
            report.append("")
    
    report.append("=" * 80)
    
    return "\n".join(report)


def generate_csv_summary(results, config) -> str:
    """
    Generate CSV summary of key metrics.
    
    Args:
        results: SimulationResults object
        config: SimulationConfig object
    
    Returns:
        CSV content as string
    """
    
    rows = []
    
    # Header
    rows.append([
        "metric_name",
        "value",
        "unit",
        "description"
    ])
    
    # Configuration
    rows.append(["steps", config.steps, "steps", "Total simulation steps"])
    rows.append(["agents", config.num_agents, "agents", "Number of agents"])
    rows.append(["location", config.place if config.place else "Custom", "", "Simulation location"])
    
    # Infrastructure
    if results.infrastructure:
        try:
            infra_metrics = results.infrastructure.get_infrastructure_metrics()
            rows.append(["grid_capacity", infra_metrics.get('grid_capacity_mw', 0), "MW", "Grid capacity"])
            rows.append(["chargers", infra_metrics.get('total_chargers', 0), "units", "Number of chargers"])
            rows.append(["grid_load", infra_metrics.get('grid_load_mw', 0), "MW", "Final grid load"])
            rows.append(["grid_utilization", infra_metrics.get('grid_utilization', 0), "fraction", "Grid utilization"])
        except:
            pass
    
    # System Dynamics
    if hasattr(results, 'system_dynamics_history') and results.system_dynamics_history:
        sd_history = results.system_dynamics_history
        initial = sd_history[0]
        final = sd_history[-1]
        
        rows.append(["initial_adoption", initial['ev_adoption'], "fraction", "Initial EV adoption"])
        rows.append(["final_adoption", final['ev_adoption'], "fraction", "Final EV adoption"])
        rows.append(["adoption_growth", final['ev_adoption'] - initial['ev_adoption'], "fraction", "Adoption growth"])
        
        peak_adoption = max(h['ev_adoption'] for h in sd_history)
        rows.append(["peak_adoption", peak_adoption, "fraction", "Peak adoption reached"])
        
        # Tipping point
        tipping_crossed = any(
            h.get('thresholds_crossed', {}).get('adoption_tipping_point', False)
            for h in sd_history
        )
        rows.append(["tipping_point_crossed", "Yes" if tipping_crossed else "No", "", "Whether 30% threshold was crossed"])
        
        # Flow metrics
        final_flow = final['ev_adoption_flow']
        rows.append(["final_flow", final_flow, "per_step", "Final adoption flow rate"])
    
    # Cascades
    if hasattr(results, 'cascade_events'):
        rows.append(["cascades", len(results.cascade_events), "events", "Cascade events detected"])
    
    # Convert to CSV string
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(rows)
    return output.getvalue()


def render_report_generator_button(results, config):
    """
    Render report generator button in sidebar.
    
    Args:
        results: SimulationResults object  
        config: SimulationConfig object
    """
    
    st.markdown("---")
    st.markdown("### 📊 Report Generator")
    
    if st.button("🎯 Generate Reports", help="Create text and CSV reports from current simulation"):
        with st.spinner("Generating reports..."):
            # Generate reports
            text_report = generate_text_report(results, config)
            csv_report = generate_csv_summary(results, config)
            
            # Create timestamp for filenames
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Display success
            st.success("✅ Reports generated!")
            
            # Download buttons in columns
            col1, col2 = st.columns(2)
            
            with col1:
                st.download_button(
                    label="📄 Text Report",
                    data=text_report,
                    file_name=f"simulation_report_{timestamp}.txt",
                    mime="text/plain",
                    help="Download detailed text report"
                )
            
            with col2:
                st.download_button(
                    label="📊 CSV Summary",
                    data=csv_report,
                    file_name=f"simulation_summary_{timestamp}.csv",
                    mime="text/csv",
                    help="Download CSV with key metrics"
                )
            
            # Preview section
            with st.expander("📋 Preview Text Report", expanded=False):
                st.text(text_report)
            
            with st.expander("📊 Preview CSV Summary", expanded=False):
                st.code(csv_report, language="csv")