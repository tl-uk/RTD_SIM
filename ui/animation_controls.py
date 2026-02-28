"""
ui/animation_controls.py

Animation playback controls and display options.
SIMPLIFIED: Auto-play removed, manual refresh button for display options
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
    
    # Display options - Simple checkboxes with manual refresh
    st.markdown("**Display Options**")
    
    show_agents_before = st.session_state.get('show_agents', True)
    show_routes_before = st.session_state.get('show_routes', True)
    show_infra_before = st.session_state.get('show_infrastructure', True)
    
    st.checkbox(
        "Show Agents", 
        value=show_agents_before,
        key='show_agents',
        help="Toggle agent markers on/off"
    )
    
    st.checkbox(
        "Show Routes", 
        value=show_routes_before,
        key='show_routes',
        help="Toggle route lines on/off"
    )
    
    st.checkbox(
        "Show Infrastructure", 
        value=show_infra_before,
        key='show_infrastructure',
        help="Toggle charging stations on/off"
    )
    
    # Check if anything changed
    something_changed = (
        st.session_state.show_agents != show_agents_before or
        st.session_state.show_routes != show_routes_before or
        st.session_state.show_infrastructure != show_infra_before
    )
    
    # Manual refresh button - only enabled if something changed
    if something_changed:
        if st.button("🔄 Apply Changes", use_container_width=True, help="Update map with new settings", type="primary"):
            # Position already saved, just trigger rerun
            st.rerun()
    
    st.caption("💡 Toggle options above, then click **Apply Changes**")