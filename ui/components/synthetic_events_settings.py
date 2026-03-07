"""
ui/components/synthetic_events_settings.py

UI component for synthetic event generator settings.

Phase 7.2: Synthetic Event Generator
"""

import streamlit as st
from typing import Dict, Any


def render_synthetic_events_settings() -> Dict[str, Any]:
    """
    Render synthetic events settings in sidebar.
    
    Returns:
        Dict with synthetic events configuration
    """
    
    with st.expander("🎲 Synthetic Events", expanded=False):
        st.markdown("**Add Random Events to Simulation**")
        st.caption("Generates realistic random events (traffic, weather, failures)")
        
        enable_synthetic = st.checkbox(
            "Enable Synthetic Events",
            value=False,
            help="Generate random realistic events during simulation",
            key="enable_synthetic_events"
        )
        
        if not enable_synthetic:
            return {
                'enable_synthetic_events': False,
                'synthetic_traffic_events': False,
                'synthetic_weather_events': False,
                'synthetic_infrastructure_events': False,
                'synthetic_grid_events': False,
                'event_frequency': 'normal',
            }
        
        st.markdown("---")
        st.markdown("### Event Types")
        
        # Event type toggles
        traffic_events = st.checkbox(
            "🚗 Traffic Congestion",
            value=True,
            help="Random traffic jams (more frequent during rush hour)",
            key="synthetic_traffic"
        )
        
        weather_events = st.checkbox(
            "🌧️ Weather Disruptions",
            value=True,
            help="Seasonal weather events (snow in winter, rain in fall)",
            key="synthetic_weather"
        )
        
        infra_events = st.checkbox(
            "🔌 Infrastructure Failures",
            value=True,
            help="Random charger outages, grid issues, depot maintenance",
            key="synthetic_infrastructure"
        )
        
        grid_events = st.checkbox(
            "⚡ Grid Stress",
            value=True,
            help="High demand periods (peak hours, seasonal)",
            key="synthetic_grid"
        )
        
        st.markdown("---")
        st.markdown("### Event Frequency")
        
        frequency = st.select_slider(
            "How often should events occur?",
            options=["rare", "occasional", "normal", "frequent", "very_frequent"],
            value="normal",
            help="Adjust overall event frequency",
            key="event_frequency_slider"
        )
        
        # Show expected frequencies
        if frequency == "rare":
            st.caption("📊 ~1-2 events per month")
        elif frequency == "occasional":
            st.caption("📊 ~3-5 events per month")
        elif frequency == "normal":
            st.caption("📊 ~5-10 events per month")
        elif frequency == "frequent":
            st.caption("📊 ~10-20 events per month")
        else:  # very_frequent
            st.caption("📊 ~20-40 events per month")
        
        st.markdown("---")
        st.markdown("### 💡 Tips")
        
        tips_by_frequency = {
            "rare": "Good for testing policy impact without too much noise",
            "occasional": "Adds some unpredictability while keeping focus on policies",
            "normal": "⭐ Recommended: Realistic balance of events and stability",
            "frequent": "High-stress testing - how robust are your policies?",
            "very_frequent": "Extreme conditions - for resilience testing",
        }
        
        st.info(tips_by_frequency[frequency])
        
        # Event type info
        st.markdown("---")
        st.markdown("### Event Details")
        
        with st.expander("Traffic Congestion", expanded=False):
            st.markdown("""
            **When:** Rush hour (7-9am, 5-7pm) on weekdays  
            **Effect:** Increased travel times, delays  
            **Severity:** Minor (20%), Moderate (50%), Severe (100% delays)  
            **Duration:** 1-12 steps depending on severity  
            """)
        
        with st.expander("Weather Disruptions", expanded=False):
            st.markdown("""
            **When:** Seasonal (more in winter/fall)  
            **Types:** Snow, ice, rain, wind, fog  
            **Effect:** Reduced EV range, lower speeds  
            **Example:** Winter snow reduces EV range by 15-30%  
            **Duration:** 2-24 steps depending on severity  
            """)
        
        with st.expander("Infrastructure Failures", expanded=False):
            st.markdown("""
            **When:** Random throughout simulation  
            **Types:** Charger outages, grid issues, depot maintenance  
            **Effect:** Reduced charging capacity  
            **Example:** 5-25 chargers offline for repairs  
            **Duration:** 3-24 steps (repairs take time)  
            """)
        
        with st.expander("Grid Stress", expanded=False):
            st.markdown("""
            **When:** Peak hours (morning/evening), winter/summer  
            **Effect:** Reduced charging rates, peak pricing  
            **Severity:** 10-30% charging rate reduction  
            **Duration:** 1-4 steps (short peaks)  
            """)
        
        return {
            'enable_synthetic_events': True,
            'synthetic_traffic_events': traffic_events,
            'synthetic_weather_events': weather_events,
            'synthetic_infrastructure_events': infra_events,
            'synthetic_grid_events': grid_events,
            'event_frequency': frequency,
        }


def display_active_events(active_events, current_step: int):
    """
    Display currently active synthetic events in sidebar.
    
    Args:
        active_events: List of active SyntheticEvent objects
        current_step: Current simulation step
    """
    if not active_events:
        return
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🎲 Active Events")
    
    # Group by type
    event_icons = {
        'traffic_congestion': '🚗',
        'weather_disruption': '🌧️',
        'infrastructure_failure': '🔌',
        'grid_stress': '⚡',
        'policy_announcement': '📋',
    }
    
    for event in active_events:
        icon = event_icons.get(event.event_type.value, '⚠️')
        
        # Build status text
        status_text = f"{icon} **{event.description}**"
        
        # Show remaining duration
        if event.steps_remaining > 0:
            status_text += f" ({event.steps_remaining} steps left)"
        
        st.sidebar.caption(status_text)
        
        # Show impact
        if event.impact_data:
            impact_str = ", ".join([f"{k}: {v}" for k, v in event.impact_data.items()])
            st.sidebar.caption(f"   Impact: {impact_str}")
    
    st.sidebar.caption(f"📊 Total: {len(active_events)} active events")