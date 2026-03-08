"""
ui/tabs/environmental_tab.py

Environmental impact analysis tab with weather and air quality data.
"""

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def render_environmental_tab(results, anim, current_data):
    """
    Render environmental impact analysis tab.
    
    Shows:
    - Weather conditions over time
    - EV range adjustments
    - Air quality metrics
    - Lifecycle emissions
    """
    
    st.subheader("🌍 Environmental Impact Analysis")
    
    # Check if weather was enabled
    weather_enabled = hasattr(results, 'weather_manager') and results.weather_manager is not None
    has_weather_history = hasattr(results, 'weather_history') and len(results.weather_history) > 0
    
    # Check if air quality tracking enabled
    has_air_quality = hasattr(results, 'air_quality_tracker') and results.air_quality_tracker is not None
    
    # Check if lifecycle emissions enabled
    has_lifecycle = hasattr(results, 'lifecycle_emissions_total') and results.lifecycle_emissions_total
    
    # If nothing available, show info
    if not weather_enabled and not has_air_quality and not has_lifecycle:
        st.info("💡 No environmental data available for this simulation.")
        st.markdown("""
        **To enable environmental tracking:**
        1. Go to Sidebar → Advanced Features
        2. ☑️ Enable Weather System
        3. Run simulation
        
        **Available environmental features:**
        - 🌤️ Weather conditions (temp, precipitation, wind)
        - ❄️ EV range adjustments based on temperature
        - 🏭 Air quality tracking (if enabled)
        - ♻️ Lifecycle emissions analysis
        """)
        return
    
    # ========================================================================
    # WEATHER DATA
    # ========================================================================
    
    if weather_enabled or has_weather_history:
        st.markdown("### 🌤️ Weather Conditions")
        
        if has_weather_history:
            # Plot weather over time
            steps = [h['step'] for h in results.weather_history]
            temps = [h.get('temperature', 0) for h in results.weather_history]
            precip = [h.get('precipitation', 0) for h in results.weather_history]
            wind = [h.get('wind_speed', 0) for h in results.weather_history]
            
            # Create subplots
            fig = make_subplots(
                rows=3, cols=1,
                subplot_titles=('Temperature (°C)', 'Precipitation (mm/h)', 'Wind Speed (km/h)'),
                vertical_spacing=0.12
            )
            
            # Temperature
            fig.add_trace(
                go.Scatter(x=steps, y=temps, name='Temperature', line=dict(color='red', width=2)),
                row=1, col=1
            )
            
            # Precipitation
            fig.add_trace(
                go.Scatter(x=steps, y=precip, name='Precipitation', 
                          fill='tozeroy', line=dict(color='blue', width=2)),
                row=2, col=1
            )
            
            # Wind
            fig.add_trace(
                go.Scatter(x=steps, y=wind, name='Wind Speed', line=dict(color='green', width=2)),
                row=3, col=1
            )
            
            # === PHASE 7.2: OVERLAY SYNTHETIC WEATHER EVENTS ===
            if hasattr(results, 'event_generator') and results.event_generator:
                try:
                    from simulation.events.synthetic_generator import EventType
                    
                    # Get all active and completed events
                    all_events = []
                    
                    # Try to get event history
                    if hasattr(results.event_generator, '_event_history'):
                        all_events = results.event_generator._event_history
                    elif hasattr(results.event_generator, 'active_events'):
                        all_events = results.event_generator.active_events
                    
                    # Add shaded regions for weather events
                    for event in all_events:
                        if event.event_type == EventType.WEATHER_DISRUPTION:
                            weather_type = event.impact_data.get('weather_type', 'unknown')
                            
                            # Determine color based on severity
                            if event.severity == 'Severe':
                                color = 'rgba(255, 0, 0, 0.15)'  # Red
                            elif event.severity == 'Moderate':
                                color = 'rgba(255, 165, 0, 0.15)'  # Orange
                            else:
                                color = 'rgba(255, 255, 0, 0.15)'  # Yellow
                            
                            # Get event step range
                            event_start = getattr(event, 'start_step', 0)
                            event_end = event_start + event.duration_steps
                            
                            # Only add if within the visible range
                            if event_start < len(steps):
                                # Add shaded region to all 3 subplots
                                for row_num in [1, 2, 3]:
                                    fig.add_vrect(
                                        x0=event_start,
                                        x1=min(event_end, len(steps)),
                                        fillcolor=color,
                                        layer="below",
                                        line_width=0,
                                        row=row_num,
                                        col=1
                                    )
                except Exception as e:
                    # Silently fail if event overlay doesn't work
                    pass
            
            fig.update_xaxes(title_text="Simulation Step", row=3, col=1)
            fig.update_layout(height=700, showlegend=False, hovermode='x unified')
            
            st.plotly_chart(fig, use_container_width=True)
            
            # Show legend for synthetic events if present
            if hasattr(results, 'event_generator') and results.event_generator:
                st.caption("**Synthetic Events:** 🟥 Severe | 🟧 Moderate | 🟨 Minor (shaded regions show active events)")
                
                # Show events summary
                try:
                    summary = results.event_generator.get_summary()
                    if summary.get('total_events', 0) > 0:
                        with st.expander("📋 Synthetic Events Summary"):
                            st.write(f"**Total Events Generated:** {summary['total_events']}")
                            if 'by_type' in summary:
                                st.write(f"**By Type:**")
                                for event_type, count in summary['by_type'].items():
                                    st.write(f"  - {event_type}: {count}")
                except:
                    pass
            
            # Summary statistics
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("Avg Temperature", f"{sum(temps)/len(temps):.1f}°C")
            with col2:
                st.metric("Total Precipitation", f"{sum(precip):.1f} mm")
            with col3:
                st.metric("Max Wind", f"{max(wind):.1f} km/h")
            with col4:
                ice_warnings = sum(1 for h in results.weather_history if h.get('ice_warning', False))
                st.metric("Ice Warnings", ice_warnings)
        
        else:
            # Show current weather only
            st.info("Weather system enabled but no historical data recorded.")
            if weather_enabled:
                try:
                    conditions = results.weather_manager.current_conditions
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Temperature", f"{conditions.get('temperature', 0):.1f}°C")
                    with col2:
                        st.metric("Precipitation", f"{conditions.get('precipitation', 0):.1f} mm/h")
                    with col3:
                        st.metric("Wind Speed", f"{conditions.get('wind_speed', 0):.1f} km/h")
                except Exception as e:
                    st.warning(f"Could not retrieve current weather: {e}")
        
        st.markdown("---")
    
    # ========================================================================
    # EV RANGE ADJUSTMENTS
    # ========================================================================
    
    if has_weather_history:
        st.markdown("### ❄️ EV Range Adjustments")
        
        st.caption("How cold temperature affects electric vehicle range")
        
        # Calculate average temp
        avg_temp = sum(h.get('temperature', 10) for h in results.weather_history) / len(results.weather_history)
        
        # Calculate range penalty
        if avg_temp < -10:
            penalty = 0.60  # 40% reduction
        elif avg_temp < 0:
            penalty = 0.75  # 25% reduction
        elif avg_temp < 10:
            penalty = 0.85  # 15% reduction
        elif avg_temp < 20:
            penalty = 0.95  # 5% reduction
        else:
            penalty = 1.0  # No reduction
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.metric("Average Temperature", f"{avg_temp:.1f}°C")
            st.metric("Range Multiplier", f"{penalty:.0%}")
        
        with col2:
            # Example ranges
            base_range = 300  # km
            adjusted_range = base_range * penalty
            
            st.markdown("**Example: 300 km rated range**")
            st.progress(penalty)
            st.caption(f"Actual range: ~{adjusted_range:.0f} km")
        
        st.markdown("---")
    
    # ========================================================================
    # LIFECYCLE EMISSIONS
    # ========================================================================
    
    if has_lifecycle:
        st.markdown("### ♻️ Lifecycle Emissions by Mode")
        
        emissions = results.lifecycle_emissions_total
        
        if emissions:
            # ✅ FIX: Extract totals from dicts if needed
            mode_totals = {}
            for mode, value in emissions.items():
                if isinstance(value, dict):
                    mode_totals[mode] = sum(value.values())
                else:
                    mode_totals[mode] = value
            
            # Sort by total emissions
            sorted_modes = sorted(mode_totals.items(), key=lambda x: x[1], reverse=True)
            
            modes = [m for m, _ in sorted_modes]
            values = [v for _, v in sorted_modes]
            
            # Create bar chart
            fig = go.Figure(data=[
                go.Bar(x=modes, y=values, marker_color='lightcoral')
            ])
            
            fig.update_layout(
                title="Total Lifecycle Emissions by Transport Mode",
                xaxis_title="Transport Mode",
                yaxis_title="CO₂ Emissions (g)",
                height=400
            )
            
            st.plotly_chart(fig, use_container_width=True)
            
            # Summary table
            st.markdown("**Emissions Summary**")
            
            # ✅ FIX: Handle both dict and number formats
            total_emissions = sum(
                sum(v.values()) if isinstance(v, dict) else v 
                for v in values
            )
            
            for mode, value in sorted_modes[:10]:  # Top 10
                # ✅ FIX: Extract total if value is a dict
                emission_total = sum(value.values()) if isinstance(value, dict) else value
                
                percentage = (emission_total / total_emissions) * 100 if total_emissions > 0 else 0
                col1, col2, col3 = st.columns([3, 2, 2])
                with col1:
                    st.write(f"**{mode}**")
                with col2:
                    st.write(f"{emission_total:,.0f} g CO₂")
                with col3:
                    st.write(f"{percentage:.1f}%")
        else:
            st.info("No lifecycle emissions data recorded.")
        
        st.markdown("---")
    
    # ========================================================================
    # AIR QUALITY
    # ========================================================================
    
    if has_air_quality:
        st.markdown("### 🏭 Air Quality Tracking")
        
        try:
            metrics = results.air_quality_metrics
            
            if metrics:
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric("PM2.5", f"{metrics.get('pm25_avg', 0):.1f} µg/m³")
                with col2:
                    st.metric("NOx", f"{metrics.get('nox_avg', 0):.1f} µg/m³")
                with col3:
                    st.metric("Hotspots", metrics.get('num_hotspots', 0))
                with col4:
                    aqi = metrics.get('aqi', 0)
                    if aqi < 50:
                        st.metric("AQI", aqi, delta="Good", delta_color="normal")
                    elif aqi < 100:
                        st.metric("AQI", aqi, delta="Moderate", delta_color="off")
                    else:
                        st.metric("AQI", aqi, delta="Unhealthy", delta_color="inverse")
            else:
                st.info("Air quality tracking enabled but no data available.")
        
        except Exception as e:
            st.warning(f"Could not load air quality data: {e}")
    
    # ========================================================================
    # ENVIRONMENTAL SUMMARY
    # ========================================================================
    
    st.markdown("---")
    st.markdown("### 📊 Environmental Summary")
    
    summary_cols = st.columns(3)
    
    with summary_cols[0]:
        if weather_enabled:
            st.success("✅ Weather tracking active")
        else:
            st.info("➖ Weather not enabled")
    
    with summary_cols[1]:
        if has_lifecycle:
            st.success("✅ Lifecycle emissions tracked")
        else:
            st.info("➖ Basic emissions only")
    
    with summary_cols[2]:
        if has_air_quality:
            st.success("✅ Air quality monitored")
        else:
            st.info("➖ Air quality not enabled")