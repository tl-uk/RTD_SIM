"""
ui/tabs/environmental_tab.py

Environmental impact visualization: weather, emissions, air quality.
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px

def render_environmental_tab(results, anim, current_data):
    """Render environmental impact tab."""
    
    st.header("🌍 Environmental Impact Analysis")
    
    # Weather Conditions
    if results.weather_manager:
        st.subheader("🌤️ Weather Conditions")
        
        conditions = results.weather_manager.current_conditions
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                "Temperature",
                f"{conditions['temperature']:.1f}°C",
                delta=None
            )
        
        with col2:
            st.metric(
                "Precipitation",
                f"{conditions['precipitation']:.1f} mm/h",
                delta=None
            )
        
        with col3:
            st.metric(
                "Wind Speed",
                f"{conditions['wind_speed']:.1f} km/h",
                delta=None
            )
        
        with col4:
            if conditions['ice_warning']:
                st.warning("⚠️ Ice Warning")
            else:
                st.success("✅ No Ice")
    
    # Lifecycle Emissions
    if hasattr(results, 'lifecycle_emissions_total'):
        st.subheader("📊 Lifecycle Emissions by Mode")
        
        emissions = results.lifecycle_emissions_total
        
        if emissions:
            # Create bar chart
            modes = list(emissions.keys())
            co2e = [emissions[m]['co2e_kg'] for m in modes]
            
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=modes,
                y=co2e,
                name='CO2e (kg)',
                marker_color='darkred'
            ))
            
            fig.update_layout(
                title="Total CO2e Emissions by Mode",
                xaxis_title="Mode",
                yaxis_title="CO2e (kg)",
                height=400
            )
            
            st.plotly_chart(fig, use_container_width=True)
            
            # Mode comparison table
            st.dataframe({
                'Mode': modes,
                'CO2e (kg)': [f"{emissions[m]['co2e_kg']:.2f}" for m in modes],
                'PM2.5 (g)': [f"{emissions[m]['pm25_g']:.2f}" for m in modes],
                'NOx (g)': [f"{emissions[m]['nox_g']:.2f}" for m in modes],
            })
    
    # Air Quality Heatmap
    if results.air_quality_tracker:
        st.subheader("🌫️ Air Quality Hotspots")
        
        aq = results.air_quality_tracker
        
        # Pollutant selector
        pollutant = st.selectbox(
            "Select Pollutant",
            ['pm25', 'nox', 'co'],
            format_func=lambda x: {
                'pm25': 'PM2.5 (Fine Particles)',
                'nox': 'NOx (Nitrogen Oxides)',
                'co': 'CO (Carbon Monoxide)'
            }[x]
        )
        
        # Get hotspots
        hotspots = aq.get_hotspots(pollutant=pollutant, threshold_multiplier=2.0)
        
        if hotspots:
            st.warning(f"⚠️ {len(hotspots)} pollution hotspots detected")
            
            # Show top 5
            for i, hotspot in enumerate(hotspots[:5]):
                st.write(f"{i+1}. Grid {hotspot['grid_cell']}: "
                        f"{hotspot['concentration']:.1f} µg/m³ "
                        f"({hotspot['exceedance_factor']:.1f}x WHO limit)")
        else:
            st.success("✅ No hotspots detected")
        
        # Summary statistics
        stats = aq.get_summary_statistics()
        
        st.write("**Air Quality Summary**")
        for poll, data in stats.items():
            st.write(f"**{poll.upper()}**: Mean {data['mean']:.2f} µg/m³ "
                    f"(WHO limit: {data['who_limit']:.1f})")