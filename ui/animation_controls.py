"""
ui/animation_controls.py

Animation playback controls and display options.
FINAL FIX: Use temporary state variables to prevent checkbox reruns
"""

import streamlit as st


def render_animation_controls(anim):
    """
    Render animation control panel in sidebar.
    
    Args:
        anim: AnimationController instance
    """
    if not anim:
        return
    
    st.markdown("---")
    st.header("🎬 Animation Controls")
    
    # Playback buttons
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("⏮️", help="Reset to Start", use_container_width=True, key='reset_btn'):
            anim.stop()
            st.session_state.current_animation_step = anim.current_step
            st.rerun()
    with col2:
        if st.button("◀️", help="Step Back", use_container_width=True, key='back_btn'):
            if anim.current_step > 0:
                anim.current_step -= 1
                st.session_state.current_animation_step = anim.current_step
                st.rerun()
    with col3:
        if st.button("▶️", help="Step Forward", use_container_width=True, key='fwd_btn'):
            if anim.current_step < anim.total_steps - 1:
                anim.current_step += 1
                st.session_state.current_animation_step = anim.current_step
                st.rerun()
    with col4:
        if st.button("⏭️", help="Jump to End", use_container_width=True, key='end_btn'):
            anim.seek(anim.total_steps - 1)
            st.session_state.current_animation_step = anim.current_step
            st.rerun()
    
    st.markdown("---")
    
    # Timeline slider
    current_step = st.slider(
        "Timeline",
        0, anim.total_steps - 1,
        anim.current_step,
        key='time_slider'
    )
    
    if current_step != anim.current_step:
        anim.seek(current_step)
        st.session_state.current_animation_step = anim.current_step
        st.rerun()
    
    # Progress indicator
    st.progress(
        anim.get_progress(), 
        text=f"Step {anim.current_step + 1}/{anim.total_steps}"
    )
    
    st.markdown("---")
    
    # Display options - Use DIFFERENT keys to avoid triggering the actual state
    st.markdown("**Display Options**")
    
    # Initialize temp state if not exists
    if 'temp_show_agents' not in st.session_state:
        st.session_state.temp_show_agents = st.session_state.get('show_agents', True)
    if 'temp_show_routes' not in st.session_state:
        st.session_state.temp_show_routes = st.session_state.get('show_routes', True)
    if 'temp_show_infrastructure' not in st.session_state:
        st.session_state.temp_show_infrastructure = st.session_state.get('show_infrastructure', True)
    
    # Use temp keys so they don't immediately update the real session state
    temp_agents = st.checkbox(
        "Show Agents", 
        value=st.session_state.temp_show_agents,
        key='temp_agents_checkbox',
        help="Toggle agent markers on/off"
    )
    
    temp_routes = st.checkbox(
        "Show Routes", 
        value=st.session_state.temp_show_routes,
        key='temp_routes_checkbox',
        help="Toggle route lines on/off"
    )
    
    temp_infrastructure = st.checkbox(
        "Show Infrastructure", 
        value=st.session_state.temp_show_infrastructure,
        key='temp_infra_checkbox',
        help="Toggle charging stations on/off"
    )
    
    # Update temp state
    st.session_state.temp_show_agents = temp_agents
    st.session_state.temp_show_routes = temp_routes
    st.session_state.temp_show_infrastructure = temp_infrastructure
    
    # Check if anything changed from actual state
    changes_pending = (
        st.session_state.temp_show_agents != st.session_state.get('show_agents', True) or
        st.session_state.temp_show_routes != st.session_state.get('show_routes', True) or
        st.session_state.temp_show_infrastructure != st.session_state.get('show_infrastructure', True)
    )
    
    # Apply button - only update real state when clicked
    if changes_pending:
        if st.button("✅ Apply Changes", use_container_width=True, type="primary", help="Update map with new display settings"):
            # Copy temp state to real state
            st.session_state.show_agents = st.session_state.temp_show_agents
            st.session_state.show_routes = st.session_state.temp_show_routes
            st.session_state.show_infrastructure = st.session_state.temp_show_infrastructure
            # Don't need to save animation position - it's already preserved
            st.rerun()
        
        st.caption("⚠️ Click **Apply Changes** to update the map")
    else:
        st.caption("💡 Toggle options above to change display")