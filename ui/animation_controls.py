"""
ui/animation_controls.py

Animation playback controls and display options.
FINAL FIX: Remove slider key to prevent state conflicts
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
    
    # Initialize if needed
    if 'current_animation_step' not in st.session_state:
        st.session_state.current_animation_step = anim.current_step
    
    # Phase 7.1: Safety check - clamp step to valid range
    # This prevents errors when switching between simulations with different step counts
    if st.session_state.current_animation_step >= anim.total_steps:
        st.session_state.current_animation_step = anim.total_steps - 1
    if st.session_state.current_animation_step < 0:
        st.session_state.current_animation_step = 0
    
    # Sync anim with session state at start of render
    anim.current_step = st.session_state.current_animation_step
    
    # Playback buttons
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("⏮️", help="Reset to Start", use_container_width=True, key='reset_btn'):
            st.session_state.current_animation_step = 0
            st.rerun()
    with col2:
        if st.button("◀️", help="Step Back", use_container_width=True, key='back_btn'):
            if st.session_state.current_animation_step > 0:
                st.session_state.current_animation_step -= 1
                st.rerun()
    with col3:
        if st.button("▶️", help="Step Forward", use_container_width=True, key='fwd_btn'):
            if st.session_state.current_animation_step < anim.total_steps - 1:
                st.session_state.current_animation_step += 1
                st.rerun()
    with col4:
        if st.button("⏭️", help="Jump to End", use_container_width=True, key='end_btn'):
            st.session_state.current_animation_step = anim.total_steps - 1
            st.rerun()
    
    st.markdown("---")
    
    # Timeline slider - NO KEY PARAMETER to avoid conflicts
    current_step_slider = st.slider(
        "Timeline",
        min_value=0,
        max_value=anim.total_steps - 1,
        value=st.session_state.current_animation_step
    )
    
    # Only update if slider actually changed
    if current_step_slider != st.session_state.current_animation_step:
        st.session_state.current_animation_step = current_step_slider
        st.rerun()
    
    # Progress indicator  
    progress = st.session_state.current_animation_step / (anim.total_steps - 1) if anim.total_steps > 1 else 0
    st.progress(
        progress,
        text=f"Step {st.session_state.current_animation_step + 1}/{anim.total_steps}"
    )
    
    st.markdown("---")
    
    # Display options - Simple checkboxes, NO KEY PARAMETER
    st.markdown("**Display Options**")
    
    # Read current values
    show_agents_current = st.session_state.get('show_agents', True)
    show_routes_current = st.session_state.get('show_routes', True)
    show_infra_current = st.session_state.get('show_infrastructure', True)
    
    # Render checkboxes WITHOUT keys
    show_agents_new = st.checkbox(
        "Show Agents",
        value=show_agents_current
    )
    
    show_routes_new = st.checkbox(
        "Show Routes",
        value=show_routes_current
    )
    
    show_infra_new = st.checkbox(
        "Show Infrastructure",
        value=show_infra_current
    )
    
    # Update session state if changed (this happens automatically on next rerun)
    if show_agents_new != show_agents_current:
        st.session_state.show_agents = show_agents_new
    if show_routes_new != show_routes_current:
        st.session_state.show_routes = show_routes_new
    if show_infra_new != show_infra_current:
        st.session_state.show_infrastructure = show_infra_new