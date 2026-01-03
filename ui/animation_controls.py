"""
ui/animation_controls.py

Animation playback controls, timeline, and display options.
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
        if st.button("⏮️", help="Reset", use_container_width=True, key='reset_btn'):
            anim.stop()
            st.rerun()
    with col2:
        if st.button("◀️", help="Step Back", use_container_width=True, key='back_btn'):
            if anim.current_step > 0:
                anim.current_step -= 1
                st.rerun()
    with col3:
        if st.button("▶️", help="Step Forward", use_container_width=True, key='fwd_btn'):
            if anim.current_step < anim.total_steps - 1:
                anim.current_step += 1
                st.rerun()
    with col4:
        if st.button("⏭️", help="End", use_container_width=True, key='end_btn'):
            anim.seek(anim.total_steps - 1)
            st.rerun()
    
    st.markdown("---")
    
    # Auto-play toggle
    auto_play = st.checkbox("▶️ Auto-Play", value=anim.is_playing, key='auto_play')
    if auto_play != anim.is_playing:
        if auto_play:
            anim.play()
        else:
            anim.pause()
        st.rerun()
    
    # Timeline slider
    current_step = st.slider(
        "Timeline",
        0, anim.total_steps - 1,
        anim.current_step,
        key='time_slider'
    )
    
    if current_step != anim.current_step:
        anim.seek(current_step)
        st.rerun()
    
    # Progress indicator
    st.progress(
        anim.get_progress(), 
        text=f"Step {anim.current_step + 1}/{anim.total_steps}"
    )
    
    st.markdown("---")
    
    # Display options
    st.markdown("**Display Options**")
    st.session_state.show_agents = st.checkbox(
        "Show Agents", 
        value=st.session_state.show_agents
    )
    st.session_state.show_routes = st.checkbox(
        "Show Routes", 
        value=st.session_state.show_routes
    )
    st.session_state.show_infrastructure = st.checkbox(
        "Show Infrastructure", 
        value=st.session_state.show_infrastructure
    )