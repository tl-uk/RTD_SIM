"""
SD History Diagnostic Tool

Run this to check what's actually in your SD history and why thresholds aren't detected.
"""

import streamlit as st

def diagnose_sd_history(sd_history):
    """
    Diagnostic function to check SD history contents.
    Call this from your SD tab to debug.
    """
    
    st.markdown("### 🔍 SD History Diagnostic")
    
    if not sd_history or len(sd_history) == 0:
        st.error("❌ No SD history available!")
        return
    
    st.success(f"✅ SD history has {len(sd_history)} timesteps")
    
    # Check first entry
    st.markdown("#### First Timestep (step 0):")
    first = sd_history[0]
    st.json(first)
    
    # Check last entry
    st.markdown("#### Last Timestep (step -1):")
    last = sd_history[-1]
    st.json(last)
    
    # Check for threshold data
    st.markdown("#### Threshold Detection:")
    
    has_threshold_field = 'thresholds_crossed' in first
    st.write(f"Has 'thresholds_crossed' field: {has_threshold_field}")
    
    if has_threshold_field:
        st.write("First step thresholds:", first.get('thresholds_crossed'))
        st.write("Last step thresholds:", last.get('thresholds_crossed'))
        
        # Check when tipping point was crossed
        tipping_steps = []
        for i, h in enumerate(sd_history):
            if h.get('thresholds_crossed', {}).get('adoption_tipping_point', False):
                tipping_steps.append(i)
        
        if tipping_steps:
            st.success(f"✅ Tipping point crossed at steps: {tipping_steps}")
        else:
            st.warning("⚠️ Tipping point never crossed in history")
            
            # Check adoption values
            adoptions = [h['ev_adoption'] for h in sd_history]
            max_adoption = max(adoptions)
            st.write(f"Max adoption reached: {max_adoption:.1%}")
            
            if max_adoption >= 0.30:
                st.error("❌ BUG: Adoption reached 30%+ but threshold not marked!")
                st.write("This means system_dynamics.py is not detecting the threshold.")
            else:
                st.info("ℹ️ Adoption never reached 30%, so no tipping point expected.")
    else:
        st.error("❌ 'thresholds_crossed' field missing from SD history!")
        st.write("Available fields:", list(first.keys()))
        st.write("""
        **Problem:** The system_dynamics.py module is not populating threshold data.
        
        **Check:**
        1. Does system_dynamics.py call `detect_thresholds()` each step?
        2. Does it add `thresholds_crossed` to the history dict?
        3. Is the history being saved correctly?
        """)


# To use this in your SD tab, add this at the top of the tab:
"""
if st.checkbox("🔍 Show SD Diagnostic Info", value=False):
    from ui.tabs.sd_diagnostic import diagnose_sd_history
    diagnose_sd_history(results.system_dynamics_history)
"""