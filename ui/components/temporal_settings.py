"""
ui/components/temporal_settings.py

UI component for temporal scaling settings.
Allows users to configure extended time simulations.

Phase 7.1: Extended Temporal Simulation
"""

import streamlit as st
from datetime import datetime
from typing import Dict, Any


def render_temporal_settings() -> Dict[str, Any]:
    """
    Render temporal scaling settings in sidebar.
    
    Returns:
        Dict with temporal configuration:
        - enable_temporal_scaling: bool
        - time_scale: str or None
        - start_datetime: datetime or None
        - suggested_steps: int
    """
    
    with st.expander("⏰ Extended Time Simulation", expanded=False):
        st.markdown("**Simulate Days, Weeks, Months, or Years**")
        st.caption("Enable realistic policy impact analysis over extended periods")
        
        enable_temporal = st.checkbox(
            "Enable Temporal Scaling",
            value=False,
            help="Simulate extended time periods beyond single-day scenarios",
            key="enable_temporal_scaling"
        )
        
        if not enable_temporal:
            return {
                'enable_temporal_scaling': False,
                'time_scale': None,
                'start_datetime': None,
                'suggested_steps': None,
            }
        
        # Time scale selection
        st.markdown("---")
        st.markdown("### Time Scale")
        
        time_scale_options = {
            "1 minute per step": "1min_per_step",
            "5 minutes per step": "5min_per_step",
            "15 minutes per step": "15min_per_step",
            "1 hour per step": "1hour_per_step",
            "1 day per step": "1day_per_step",
            "1 week per step": "1week_per_step",
            "1 month per step": "1month_per_step",
        }
        
        time_scale_display = st.selectbox(
            "How much real time does each simulation step represent?",
            options=list(time_scale_options.keys()),
            index=4,  # Default: "1 day per step"
            help="Choose based on your analysis timeframe",
            key="time_scale_select"
        )
        
        time_scale = time_scale_options[time_scale_display]
        
        # Duration presets
        st.markdown("---")
        st.markdown("### Simulation Duration")
        
        # Smart duration suggestions based on time scale
        if "day" in time_scale:
            duration_presets = {
                "1 week": 7,
                "2 weeks": 14,
                "1 month": 30,
                "3 months": 90,
                "6 months": 180,
                "1 year": 365,
                "2 years": 730,
            }
            default_preset = "1 year"
        elif "week" in time_scale:
            duration_presets = {
                "3 months": 13,
                "6 months": 26,
                "1 year": 52,
                "2 years": 104,
                "5 years": 260,
            }
            default_preset = "1 year"
        elif "month" in time_scale:
            duration_presets = {
                "6 months": 6,
                "1 year": 12,
                "2 years": 24,
                "5 years": 60,
                "10 years": 120,
            }
            default_preset = "5 years"
        elif "hour" in time_scale:
            duration_presets = {
                "1 day": 24,
                "3 days": 72,
                "1 week": 168,
                "2 weeks": 336,
                "1 month": 720,
            }
            default_preset = "1 week"
        else:  # minute scales
            duration_presets = {
                "2 hours": 120,
                "6 hours": 360,
                "12 hours": 720,
                "1 day": 1440,
                "2 days": 2880,
            }
            default_preset = "1 day"
        
        # Duration selector
        col1, col2 = st.columns([2, 1])
        
        with col1:
            duration_choice = st.selectbox(
                "Select duration",
                options=list(duration_presets.keys()),
                index=list(duration_presets.keys()).index(default_preset),
                help="Choose a preset or use custom",
                key="duration_preset"
            )
        
        with col2:
            use_custom = st.checkbox(
                "Custom",
                value=False,
                help="Enter custom number of steps",
                key="use_custom_steps"
            )
        
        if use_custom:
            suggested_steps = st.number_input(
                "Number of steps",
                min_value=10,
                max_value=10000,
                value=duration_presets[duration_choice],
                step=1,
                help="Total simulation steps",
                key="custom_steps_input"
            )
        else:
            suggested_steps = duration_presets[duration_choice]
        
        # Show calculated duration
        try:
            from simulation.time.temporal_engine import TemporalEngine, TimeScale
            
            temp_engine = TemporalEngine(
                TimeScale(time_scale),
                steps=suggested_steps
            )
            summary = temp_engine.get_summary()
            
            # Display summary
            st.success(f"📅 **Simulation will span:** {summary['duration']}")
            
            col_a, col_b = st.columns(2)
            with col_a:
                st.caption(f"**Steps:** {suggested_steps}")
                st.caption(f"**Each step:** {summary['step_duration']}")
            with col_b:
                st.caption(f"**Start:** {summary['start_date']}")
                st.caption(f"**End:** {summary['end_date']}")
        
        except Exception as e:
            st.warning(f"Could not calculate duration: {e}")
        
        # Start date/time
        st.markdown("---")
        st.markdown("### Start Date & Time")
        
        col_date, col_time = st.columns(2)
        
        with col_date:
            start_date = st.date_input(
                "Start date",
                value=datetime(2024, 1, 1).date(),
                help="When does the simulation begin?",
                key="start_date_input"
            )
        
        with col_time:
            start_time = st.time_input(
                "Start time",
                value=datetime(2024, 1, 1, 0, 0).time(),
                help="Time of day to start",
                key="start_time_input"
            )
        
        start_datetime = datetime.combine(start_date, start_time)
        
        # Tips
        st.markdown("---")
        st.markdown("### 💡 Tips")
        
        if "day" in time_scale:
            st.info(
                "**Daily resolution** is ideal for:\n"
                "- Long-term policy impact analysis\n"
                "- Seasonal behavior patterns\n"
                "- Infrastructure buildout over months/years"
            )
        elif "week" in time_scale:
            st.info(
                "**Weekly resolution** is ideal for:\n"
                "- Multi-year trend analysis\n"
                "- Strategic planning scenarios\n"
                "- Long-term adoption curves"
            )
        elif "hour" in time_scale:
            st.info(
                "**Hourly resolution** is ideal for:\n"
                "- Detailed daily pattern analysis\n"
                "- Rush hour vs off-peak studies\n"
                "- Time-of-day pricing impact"
            )
        
        return {
            'enable_temporal_scaling': True,
            'time_scale': time_scale,
            'start_datetime': start_datetime,
            'suggested_steps': suggested_steps,
        }


def display_temporal_progress(temporal_engine, current_step: int):
    """
    Display current simulation time and progress.
    
    Use in main UI to show where simulation is in time.
    
    Args:
        temporal_engine: TemporalEngine instance
        current_step: Current simulation step
    """
    if not temporal_engine:
        return
    
    time_info = temporal_engine.get_time_info(current_step)
    progress_str = temporal_engine.get_progress_string(current_step)
    
    # Display in sidebar or header
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ⏰ Simulation Time")
    
    st.sidebar.metric(
        "Current Date",
        time_info['date'],
        delta=None
    )
    
    st.sidebar.metric(
        "Current Time",
        time_info['time'],
        delta=None
    )
    
    # Additional context
    col1, col2 = st.sidebar.columns(2)
    with col1:
        st.caption(f"**Season:** {time_info['season'].capitalize()}")
        st.caption(f"**Day:** {time_info['day_of_week_name']}")
    with col2:
        if time_info['is_rush_hour']:
            st.caption("🚗 **Rush Hour**")
        if time_info['is_weekend']:
            st.caption("📅 **Weekend**")
    
    # Progress bar
    progress = current_step / temporal_engine.total_steps
    st.sidebar.progress(progress, text=progress_str)


# Helper to add day of week name
def _add_day_name(time_info: Dict[str, Any]) -> Dict[str, Any]:
    """Add day of week name to time_info dict."""
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    time_info['day_of_week_name'] = days[time_info['day_of_week']]
    return time_info