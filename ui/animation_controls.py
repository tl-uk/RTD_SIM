"""
ui/animation_controls.py

Animation playback controls and display options.
PROPER FIX: Simple checkboxes, no apply button needed
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
    
    # Display options - Simple checkboxes, map tab uses @st.fragment
    st.markdown("**Display Options**")
    
    st.checkbox(
        "Show Agents", 
        value=st.session_state.get('show_agents', True),
        key='show_agents',
        help="Toggle agent markers"
    )
    
    st.checkbox(
        "Show Routes", 
        value=st.session_state.get('show_routes', True),
        key='show_routes',
        help="Toggle route lines"
    )
    
    st.checkbox(
        "Show Infrastructure", 
        value=st.session_state.get('show_infrastructure', True),
        key='show_infrastructure',
        help="Toggle charging stations"
    )