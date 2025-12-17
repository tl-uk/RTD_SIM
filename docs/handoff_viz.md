# RTD_SIM Visualization Handoff - URGENT FIXES NEEDED

# RTD_SIM Visualization Handoff - URGENT FIXES NEEDED

## Current Status: ISSUES REMAINING

**Date:** December 2024  
**Phase:** 4.1 Integration Complete (Backend), Visualization Broken (Frontend)  
**Timeline:** 18-month research project, currently Month 5-6  
**Priority:** HIGH - User cannot differentiate agents

---

## 📋 Project Roadmap & Status

### ✅ COMPLETED (Phases 1-4.1)

#### Phase 1: BDI Architecture (Months 1-2) ✅ DONE
- ✅ Cognitive agent framework (`cognitive_abm.py`)
- ✅ BDI planner with desires, beliefs, intentions (`bdi_planner.py`)
- ✅ Mode choice decision-making
- ✅ Basic movement and routing
- **Status:** Working, all tests passing

#### Phase 2: OSM Integration + Routing (Months 2-3) ✅ DONE
- ✅ OSMnx integration for real street networks
- ✅ Multi-modal routing (walk, bike, bus, car, EV)
- ✅ Route planning with environmental costs
- ✅ Congestion tracking (optional)
- ✅ Emissions calculations
- **Status:** Working, validated with Edinburgh network

#### Phase 3: Story-Driven Agents (Months 3-4) ✅ DONE
- ✅ User story framework (10 personas in `personas.yaml`)
- ✅ Job story framework (10 contexts in `job_contexts.yaml`)
- ✅ Story parser and agent generator
- ✅ Personality-based desire calibration
- ✅ Explainable decision-making
- **Status:** Working, 7/7 tests passing (`test_phase3_stories.py`)

#### Phase 4: Social Networks (Months 4-5) ✅ DONE
- ✅ Social network topologies (homophily, small-world, scale-free)
- ✅ Peer influence on mode choice
- ✅ Cascade detection
- ✅ Tipping point analysis
- ✅ Strong vs weak ties
- **Status:** Working, 7/7 tests passing (`test_phase4_social.py`)

#### Phase 4.1: Realistic Social Influence (Month 5-6) ✅ BACKEND DONE, ❌ VIZ BROKEN
- ✅ Temporal decay (influences fade 10-20% per step)
- ✅ Habit formation (repeated use builds inertia)
- ✅ Experience weighting (satisfaction overrides peers)
- ✅ Saturation limits (only recent influences count)
- ✅ Fashion cycles (popular modes lose appeal)
- ✅ Backend integration complete
- ✅ Test passing (`test_realistic_influence.py`)
- ❌ **Visualization broken** (colors not working, auto-play broken)
- **Status:** BLOCKED - Cannot validate without working visualization

**Key Achievement:** Prevents over-deterministic cascades (30-50% peaks vs 80-100%)

---

### 🚧 CURRENT BLOCKERS (Must Fix Before Phase 5)

#### CRITICAL Issue 1: Agent Colors Not Working ❌
- **Problem:** All agents appear orange/gold on map
- **Expected:** Walk=green, bike=blue, bus=orange, car=red, EV=purple
- **Impact:** Cannot visually distinguish agent modes
- **Attempts:** Tried 3 different approaches, all failed
- **Status:** BLOCKING research validation

#### HIGH Issue 2: Auto-Play Not Working ❌
- **Problem:** Animation doesn't advance when Play clicked
- **Expected:** Automatic frame advancement every 0.2-0.5s
- **Impact:** Must manually click through each timestep
- **Fallback:** Manual stepping should work (needs verification)
- **Status:** BLOCKING user experience

#### File: `streamlit_app_unified.py`
- Purpose: Unified visualization for all phases
- Status: Created but broken (colors + auto-play)
- Dependencies: `visualiser/` modules
- Tests: None (visual verification only)

**MUST FIX THESE BEFORE PROCEEDING TO PHASE 5**

---

### 📅 UPCOMING (Not Yet Started)

#### Phase 5: System Dynamics + Real-Time (Months 7-10) ⏸️ ON HOLD
**Prerequisites:** Phase 4.1 visualization MUST be fixed first

**Planned Features:**
1. **Streaming System Dynamics**
   - Continuous feedback loops (not batch ODE)
   - Carbon budget tracking with constraints
   - Dynamic parameter updates based on system state
   
2. **Policy Injection System**
   - Test interventions during simulation
   - "What if we add bike lane at step 50?"
   - Measure policy effectiveness in real-time
   
3. **MQTT/IoT Integration**
   - Real-time data streams from sensors
   - Live traffic data integration
   - Weather data integration
   
4. **Kalman-like Data Assimilation**
   - Blend simulation with real-world observations
   - Correct predictions with actual data
   - Uncertainty quantification
   
5. **Carbon Budget Feedback**
   - Track cumulative emissions vs budget
   - Trigger policy responses when budget exceeded
   - Multi-objective optimization

**Why Prerequisites Matter:**
- ✅ Realistic influence prevents policy over-response
- ✅ Habit formation shows policy persistence
- ✅ Experience weighting enables policy feedback loops

**Status:** NOT STARTED - Waiting for Phase 4.1 validation

**Timeline:** 
- Originally planned: Months 7-10
- Currently: Month 5-6 (ahead of schedule if Phase 5 hasn't started)
- New timeline: Start Phase 5 after visualization fixed

---

### 📊 Research Deliverables Status

#### Paper 1: Methodology (Transportation Science)
**Target:** Submit Month 9-10
**Status:** ⚠️ At Risk

**Sections:**
- ✅ Phase 1-2: BDI + Routing methodology (ready)
- ✅ Phase 3: Story-driven generation (ready)
- ✅ Phase 4: Social networks (ready)
- ✅ Phase 4.1: Realistic influence theory (ready)
- ❌ **Phase 4.1 validation** (BLOCKED - needs visualization)
- 🔲 Phase 5: System dynamics methodology (not started)

**Required Figures:**
- ❌ Realistic vs deterministic comparison plot (need viz)
- ❌ Adoption curves showing decay (need viz)
- ❌ Habit formation visualization (need viz)
- ❌ Network cascade detection (need viz)

**Risk:** Cannot generate figures without working visualization

#### Paper 2: Application (Transportation Research Part D)
**Target:** Submit Month 12-14
**Status:** ⏸️ On Hold

**Requirements:**
- Phase 4.1 validated with Edinburgh data ✅ (backend ready)
- Phase 5 system dynamics complete 🔲 (not started)
- Real-world calibration ⏸️ (waiting for viz)
- Policy scenarios ⏸️ (waiting for Phase 5)

**Dependencies:** Phase 4.1 viz → Phase 5 → Paper 2

---

### 🎯 Immediate Action Items (Priority Order)

#### Week 1: Fix Visualization (URGENT)
1. ❗ **Fix agent colors** - Try 5 approaches in handoff
2. ❗ **Fix auto-play** - Or implement robust manual stepping
3. ❗ **Validate** - Run realistic vs deterministic comparison
4. ❗ **Generate figures** - Comparison plots for Paper 1

#### Week 2: Phase 4.1 Validation
1. Run full simulation (100+ agents, 200+ steps)
2. Compare realistic vs deterministic
3. Validate adoption curves (30-50% vs 80-100%)
4. Measure volatility (should be ~0.15)
5. Detect cascades (should be temporary)
6. Document for Paper 1

#### Week 3-4: Prepare for Phase 5
1. Review Phase 5 requirements
2. Research streaming system dynamics approaches
3. Design MQTT integration architecture
4. Plan Kalman filter implementation
5. Define carbon budget constraints

#### Month 7+: Phase 5 Implementation
*Only start after Phase 4.1 fully validated*

---

### 📈 Testing Status

#### Automated Tests: 15/15 Passing ✅
- `test_phase3_stories.py`: 7/7 ✅
- `test_phase4_social.py`: 7/7 ✅
- `test_realistic_influence.py`: 1/1 ✅

#### Visual Validation: 0/5 Passing ❌
- Color differentiation: ❌ FAIL
- Auto-play animation: ❌ FAIL
- Manual stepping: ⚠️ Untested
- Adoption curve plots: ⚠️ Untested (backend ready)
- Network visualizations: ⚠️ Untested (backend ready)

**Overall Testing Status:** Backend solid, Frontend broken

---

### 💾 Data & Configuration Status

#### Agent Stories: ✅ Complete
- `agent/personas.yaml`: 10 user stories defined
- `agent/job_contexts.yaml`: 10 job contexts defined
- Total combinations: 100 unique agent types
- All parsers working correctly

#### Network Configurations: ✅ Complete
- Homophily network: Implemented, tested
- Small-world network: Implemented, tested
- Scale-free network: Implemented, tested
- Random network: Implemented, tested

#### Influence Configurations: ✅ Complete
- Default config: decay=0.15, habit=0.4, exp=0.4, peer=0.2
- Personality-based configs: 6 variants defined
- Edinburgh calibration: Parameters estimated
- All working in backend

#### Visualization Configurations: ❌ Broken
- Color scheme defined correctly in `style_config.py`
- But not rendering correctly in Pydeck
- Animation controller defined, but not advancing

---

### 🔍 Known Issues Summary

| Issue | Priority | Status | Blocker For |
|-------|----------|--------|-------------|
| Agent colors all orange | CRITICAL | Open | Research validation, Paper 1 |
| Auto-play not working | HIGH | Open | User experience |
| Phase 4.1 visualization | CRITICAL | Open | Phase 5, Paper 1 |
| Phase 5 not started | LOW | Expected | Paper 2 |

---

### 🎓 Research Context

**Project:** Real-Time Decarbonization Simulation (RTD_SIM)  
**Duration:** 18 months (currently Month 5-6)  
**Institution:** Unknown (user in Belfast, Northern Ireland)  
**Papers:** 2 planned (Transportation Science + Transportation Research Part D)

**Why This Matters:**
- Novel methodology contribution (Phase 4.1 realistic influence)
- First ABM with decay + habit + experience weighting
- Addresses over-deterministic cascade problem in literature
- Enables realistic policy scenario testing
- Foundation for real-time transport management (Phase 5)

**Current Risk:**
Cannot validate Phase 4.1 without working visualization. This blocks:
- Paper 1 figure generation
- Phase 5 development
- Real-world calibration
- Stakeholder demonstrations

**Timeline Impact:**
- If fixed this week: On track for Month 9 Paper 1 submission ✅
- If delayed 2+ weeks: Risk missing Paper 1 deadline ⚠️
- Phase 5 can absorb some delay (Months 7-10 window) ✅

---

## 🚨 CRITICAL ISSUES

### Issue 1: All Agents/Routes Appear Orange/Gold
**Expected:** Agents colored by mode (walk=green, bike=blue, bus=orange, car=red, EV=purple)  
**Actual:** All agents and routes appear as same orange/gold color  
**Impact:** Cannot visually distinguish which agents are using which transport mode  
**Status:** NOT FIXED despite multiple attempts

### Issue 2: Auto-Play Not Working
**Expected:** When "▶️ Play" button clicked, animation advances automatically  
**Actual:** Animation does not advance, stays on same frame  
**Impact:** User must manually click through each timestep  
**Status:** NOT FIXED

---

## Project Context

### What RTD_SIM Is
Agent-based transport decarbonization simulator with:
- **Phase 1:** BDI cognitive agents
- **Phase 2:** OSM routing integration
- **Phase 3:** Story-driven agent generation (10 user stories × 10 job contexts)
- **Phase 4:** Social network influence
- **Phase 4.1:** Realistic social influence (decay, habits, experience weighting)

### Current State
- ✅ Backend simulation working (all 14+ tests passing)
- ✅ Phase 4.1 realistic influence integrated
- ❌ Visualization broken (colors not working)
- ❌ Animation not working

### Technology Stack
- Python 3.10+
- Streamlit (web UI)
- Pydeck (map visualization with deck.gl)
- NetworkX (social networks)
- OSMnx (street networks)
- Plotly (charts)

---

## File Structure

```
RTD_SIM/
├── agent/
│   ├── __init__.py (v4.1.0)
│   ├── cognitive_abm.py          ✅ Working
│   ├── bdi_planner.py             ✅ Working
│   ├── story_driven_agent.py      ✅ Working
│   ├── social_network.py          ✅ Working
│   ├── social_influence_dynamics.py  ✅ Working (Phase 4.1)
│   ├── agent_satisfaction.py      ✅ Working (Phase 4.1)
│   ├── user_stories.py            ✅ Working
│   ├── job_stories.py             ✅ Working
│   ├── personas.yaml              ✅ 10 user stories
│   └── job_contexts.yaml          ✅ 10 job contexts
├── simulation/
│   ├── spatial_environment.py     ✅ Working
│   ├── controller.py              ✅ Working
│   └── event_bus.py               ✅ Working
├── visualiser/
│   ├── data_adapters.py           ✅ Working
│   ├── animation_controller.py    ⚠️ Used but not advancing
│   └── style_config.py            ✅ Defines colors correctly
├── ui/ (or root)
│   ├── streamlit_app_unified.py   ❌ BROKEN (colors + autoplay)
│   └── [multiple old streamlit files - ignore these]
└── test_*.py                      ✅ All passing
```

---

## The Color Problem - Technical Details

### Desired Behavior
```python
MODE_COLORS_RGB = {
    'walk': [34, 197, 94],    # Green
    'bike': [59, 130, 246],   # Blue
    'bus': [245, 158, 11],    # Orange
    'car': [239, 68, 68],     # Red
    'ev': [168, 85, 245],     # Purple
}
```

Each agent should be colored based on their `agent.state.mode` value.

### What We've Tried (All Failed)

**Attempt 1: Direct color array**
```python
agent_data.append({
    'color': MODE_COLORS_RGB[mode],  # e.g., [34, 197, 94]
})
agent_layer = pdk.Layer(
    'ScatterplotLayer',
    get_color='color',  # ❌ Doesn't work
)
```
**Result:** All agents gold/orange

**Attempt 2: Split RGB into columns**
```python
agent_data.append({
    'r': color_rgb[0],
    'g': color_rgb[1], 
    'b': color_rgb[2],
})
agent_layer = pdk.Layer(
    'ScatterplotLayer',
    get_fill_color='[r, g, b]',  # ❌ Still doesn't work
)
```
**Result:** All agents gold/orange

**Attempt 3: Verified data pipeline**
- Added debug panel to show agent modes
- Confirmed agents DO have different modes (walk, bike, bus, car)
- Confirmed color values ARE being set correctly in DataFrame
- Problem is in Pydeck rendering, not data preparation

### Current Code (Not Working)

```python
# In streamlit_app_unified.py, Map tab
agent_data = []
for state in agent_states:
    mode = state.get('mode', 'walk')
    color_rgb = MODE_COLORS_RGB.get(mode, [128, 128, 128])
    agent_data.append({
        'lon': float(loc[0]),
        'lat': float(loc[1]),
        'r': color_rgb[0],
        'g': color_rgb[1],
        'b': color_rgb[2],
        'mode': mode,
    })

agent_df = pd.DataFrame(agent_data)
agent_layer = pdk.Layer(
    'ScatterplotLayer',
    data=agent_df,
    get_position='[lon, lat]',
    get_fill_color='[r, g, b]',  # ❌ Not working
    ...
)
```

### Hypothesis
Pydeck's `get_fill_color` expression might not be evaluating correctly. Possibilities:
1. DataFrame column types wrong (need int, not float?)
2. Pydeck version issue
3. Need to use accessor functions differently
4. Alpha channel required? (RGBA instead of RGB)

---

## The Auto-Play Problem - Technical Details

### Desired Behavior
1. User clicks "▶️ Play" button in sidebar
2. `animation_controller.is_playing` becomes `True`
3. Bottom of script checks `if anim.is_playing:`
4. Sleeps briefly, increments step, calls `st.rerun()`
5. Loop continues until end or user clicks pause

### Current Code (Not Working)

```python
# In sidebar
with col2:
    if st.button("⏸️" if anim.is_playing else "▶️", 
                use_container_width=True, key='play'):
        anim.toggle_play_pause()
        st.rerun()

# At bottom of script
if anim.is_playing:
    delay = 0.15
    time.sleep(delay)
    
    if anim.current_step < anim.total_steps - 1:
        anim.current_step += 1
        st.rerun()
    else:
        if anim.loop:
            anim.current_step = 0
            st.rerun()
        else:
            anim.pause()
            st.rerun()
```

### What Happens
- Button click DOES toggle `anim.is_playing` to `True` (verified)
- Script reaches bottom `if anim.is_playing:` block (verified)
- `st.rerun()` is called
- BUT: Animation stays frozen on same frame

### Hypothesis
1. `st.rerun()` might be resetting `anim.is_playing` state
2. Session state not persisting correctly
3. Need to use `st.experimental_rerun()` instead?
4. Streamlit's rerun behavior changed in recent versions?

### Alternative: Manual Stepping
User requested fallback: If auto-play can't be fixed, at least make manual stepping work well:
- ◀️ Previous frame
- ▶️ Next frame  
- Slider to jump to any frame
- All of these SHOULD already work (they just call `anim.seek()` + `st.rerun()`)

---

## Debug Information Added

Added debug panel in Map tab (expand "🎨 Debug: Agent Colors"):

```python
with st.expander("🎨 Debug: Agent Colors"):
    st.markdown("**Agents by mode (should be different colors):**")
    for mode, count in mode_counts.most_common():
        color_hex = MODE_COLORS_HEX.get(mode, '#808080')
        color_rgb = MODE_COLORS_RGB.get(mode, [128, 128, 128])
        st.markdown(
            f"<span style='color:{color_hex};font-size:24px'>●</span> "
            f"{mode.capitalize()}: {count} agents (RGB: {color_rgb})",
            unsafe_allow_html=True
        )
```

**What this shows:**
- Confirms agents have different modes ✅
- Shows what color each mode SHOULD be ✅
- Proves data preparation is correct ✅
- But map still shows all gold ❌

---

## What Works

These features ARE working correctly:

✅ **Simulation execution** - Agents move, make decisions, influence each other  
✅ **Data collection** - All metrics tracked correctly  
✅ **Mode adoption charts** - Show different modes over time  
✅ **Impact calculations** - Emissions, distance computed correctly  
✅ **Network analysis** - Social cascades detected  
✅ **Manual timeline slider** - Can jump to any timestep  
✅ **Tab navigation** - All 4 tabs display  

---

## User Environment

- **OS:** Unknown (assume Windows/Mac/Linux compatible)
- **Location:** Belfast, Northern Ireland, GB
- **Python:** 3.10+
- **Streamlit version:** Unknown (need to check)
- **Pydeck version:** Unknown (need to check)

**IMPORTANT:** Check versions with:
```bash
pip show streamlit pydeck
```

---

## Reproduction Steps

1. **Setup:**
```bash
cd RTD_SIM
pip install streamlit pydeck pandas plotly networkx
```

2. **Run visualization:**
```bash
streamlit run streamlit_app_unified.py
```

3. **Configure simulation:**
   - Keep defaults (50 agents, 100 steps, Edinburgh)
   - Click "🚀 Run Simulation"
   - Wait ~30 seconds

4. **Observe issues:**
   - **Color issue:** All agents appear gold/orange (should be green/blue/red/purple mix)
   - **Auto-play issue:** Click "▶️ Play" button → animation doesn't advance

5. **Debug panel:**
   - Expand "🎨 Debug: Agent Colors" in Map tab
   - Shows agents DO have different modes
   - Shows correct RGB values
   - But map doesn't reflect this

---

## Requested Solution

### Priority 1: Fix Colors (CRITICAL)
Need agents and routes to display in different colors by mode. User cannot use simulator without this.

**Acceptance criteria:**
- Walk agents appear GREEN
- Bike agents appear BLUE
- Bus agents appear ORANGE
- Car agents appear RED
- EV agents appear PURPLE

### Priority 2: Fix Auto-Play (HIGH)
Need animation to advance automatically when Play is clicked.

**Acceptance criteria:**
- Click "▶️ Play" → animation advances every 0.2-0.5 seconds
- Can pause with "⏸️ Pause"
- Loops if loop enabled

**Fallback if auto-play can't be fixed:**
- Ensure manual stepping works flawlessly
- Add keyboard shortcuts (arrow keys?)
- Make slider more prominent

---

## Potential Solutions to Investigate

### For Color Issue

**Option 1: Try RGBA instead of RGB**
```python
'r': color_rgb[0],
'g': color_rgb[1],
'b': color_rgb[2],
'a': 255,  # Add alpha
get_fill_color='[r, g, b, a]'
```

**Option 2: Try integer type enforcement**
```python
'r': int(color_rgb[0]),
'g': int(color_rgb[1]),
'b': int(color_rgb[2]),
```

**Option 3: Use accessor function syntax**
```python
get_fill_color='@@=[properties.r, properties.g, properties.b]'
```

**Option 4: Pre-calculate color per row**
```python
agent_df['color'] = agent_df.apply(
    lambda row: [int(row['r']), int(row['g']), int(row['b'])],
    axis=1
)
get_fill_color='color'
```

**Option 5: Switch to different visualization library**
- Try Plotly mapbox instead of Pydeck?
- Try Folium with colored markers?

### For Auto-Play Issue

**Option 1: Use st.empty() placeholder pattern**
```python
placeholder = st.empty()
while anim.is_playing:
    with placeholder.container():
        # Render frame
        pass
    time.sleep(0.2)
    anim.step_forward()
```

**Option 2: Use st.session_state callback**
```python
def advance_animation():
    st.session_state.current_step += 1
    
if st.button("▶️", on_click=advance_animation):
    pass
```

**Option 3: JavaScript auto-refresh**
```python
if anim.is_playing:
    st.markdown(
        '<meta http-equiv="refresh" content="0.5">',
        unsafe_allow_html=True
    )
```

**Option 4: Give up on auto-play, optimize manual stepping**
- Make ◀️▶️ buttons larger
- Add keyboard shortcuts
- Add "Play 10 frames" button
- Improve slider UX

---

## Files Provided to Next Session

You should have:
1. ✅ `streamlit_app_unified.py` - The broken visualization file
2. ✅ `visualiser/animation_controller.py` - Animation state manager
3. ✅ `visualiser/data_adapters.py` - Data preparation
4. ✅ `visualiser/style_config.py` - Color definitions
5. ✅ This handoff document

**If you need more files, ask for:**
- `agent/*.py` files (for understanding agent state structure)
- `simulation/*.py` files (for understanding simulation loop)
- Test files (to verify backend working)

---

## Questions for Debugging

When continuing, ask user:

1. **"What Streamlit version are you running?"**
   ```bash
   streamlit --version
   ```

2. **"What does the debug panel show?"**
   - Expand "🎨 Debug: Agent Colors" in Map tab
   - Screenshot or copy the output

3. **"What's in the browser console?"**
   - Press F12 in browser
   - Look for JavaScript errors
   - Check Network tab for failed requests

4. **"Can you try a minimal Pydeck example?"**
   ```python
   import streamlit as st
   import pydeck as pdk
   import pandas as pd
   
   df = pd.DataFrame({
       'lat': [55.95, 55.96],
       'lon': [-3.19, -3.18],
       'r': [255, 0],
       'g': [0, 255],
       'b': [0, 0],
   })
   
   layer = pdk.Layer(
       'ScatterplotLayer',
       data=df,
       get_position='[lon, lat]',
       get_fill_color='[r, g, b]',
       get_radius=100
   )
   
   st.pydeck_chart(pdk.Deck(layers=[layer]))
   ```
   
   **Expected:** One red dot, one green dot  
   **If both gold:** Pydeck installation issue

---

## Success Criteria

✅ **Visualization working when:**
1. Run simulation
2. See agents in different colors (green, blue, red, purple)
3. Click Play → animation advances automatically
4. OR manual stepping works smoothly
5. Can identify which agents use which modes by color

---

## Notes from Previous Attempts

- Tried splitting RGB into columns → didn't work
- Tried direct color array → didn't work  
- Verified data is correct → problem is in Pydeck rendering
- Checked animation_controller state → correctly toggling is_playing
- Added debug panel → confirms modes are different
- User is in Belfast, Northern Ireland (for context/timezone)
- This is a research project (18-month timeline, currently month 5-6)
- Papers depend on this working (need visualizations for validation)

---

## Related Documents

- `phase4_handoff_integration.md` - Phase 4.1 integration (✅ complete)
- `REALISTIC_INFLUENCE.md` - Theory behind Phase 4.1
- `test_realistic_influence.py` - Validation test (✅ passing)
- `STREAMLIT_MIGRATION_GUIDE.md` - Migration to unified file

---

## Contact Points

**If you get stuck:**
1. Check Pydeck documentation: https://deckgl.readthedocs.io/
2. Check Streamlit forum: https://discuss.streamlit.io/
3. Try minimal reproduction case (included above)
4. Consider alternative visualization libraries

---

## URGENT ACTION ITEMS

1. ❗ Fix agent colors - this is blocking ALL visualization work
2. ❗ Fix or replace auto-play - affects usability
3. Get working visualization for research validation
4. Prepare figures for Paper 1 (methodology)

**Timeline:** User needs this working ASAP for research progress.

---

**END OF HANDOFF**

Good luck! The backend is solid - just need to fix the frontend rendering.
