"""
ui/sidebar_config.py

Sidebar configuration panel with Phase 4.5B scenario selection.
Handles all simulation parameters.
"""

import streamlit as st
from pathlib import Path
import sys

# Add parent directory to path for imports
parent_dir = Path(__file__).resolve().parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from simulation.simulation_runner import SimulationConfig, list_available_scenarios, get_scenario_info

# Phase 4 availability check
try:
    from agent.user_stories import UserStoryParser
    from agent.job_stories import JobStoryParser
    PHASE_4_AVAILABLE = True
except ImportError:
    PHASE_4_AVAILABLE = False


def render_sidebar_config():
    """
    Render sidebar configuration panel.
    
    Returns:
        tuple: (SimulationConfig, run_button_clicked)
    """
    st.header("⚙️ Simulation Configuration")
    
    with st.form("config_form"):
        # Basic settings
        st.markdown("### 📊 Basic Settings")
        steps = st.number_input("Simulation Steps", 20, 200, 100, 20)
        num_agents = st.number_input("Number of Agents", 10, 100, 50, 10)
        
        st.markdown("---")
        
        # Location settings
        region_info = _render_location_settings()
        place, extended_bbox = region_info['place'], region_info['bbox']
        use_osm = region_info['use_osm']
        
        st.markdown("---")
        
        # Story selection
        user_stories, job_stories = _render_story_selection()
        
        st.markdown("---")
        
        # Advanced features
        advanced_config = _render_advanced_features()
        
        st.markdown("---")
        
        # 🆕 Phase 4.5B: Scenario selection
        scenario_config = _render_scenario_selection()
        
        st.markdown("---")
        
        # Submit button
        run_btn = st.form_submit_button(
            "🚀 Run Simulation", 
            type="primary", 
            use_container_width=True
        )
    
    # Build configuration object
    config = SimulationConfig(
        steps=steps,
        num_agents=num_agents,
        place=place,
        extended_bbox=extended_bbox,
        use_osm=use_osm,
        user_stories=user_stories,
        job_stories=job_stories,
        use_congestion=advanced_config['use_congestion'],
        enable_social=advanced_config['enable_social'],
        use_realistic_influence=advanced_config['use_realistic'],
        decay_rate=advanced_config['decay_rate'],
        habit_weight=advanced_config['habit_weight'],
        enable_infrastructure=advanced_config['enable_infrastructure'],
        num_chargers=advanced_config['num_chargers'],
        num_depots=advanced_config['num_depots'],
        grid_capacity_mw=advanced_config['grid_capacity_mw'],
        scenario_name=scenario_config['scenario_name'],
        scenarios_dir=scenario_config['scenarios_dir']
    )
    
    return config, run_btn


def _render_location_settings():
    """Render location configuration section."""
    st.markdown("### 🗺️ Location")
    use_osm = st.checkbox("Use Real Street Network", value=True)
    
    place = None
    extended_bbox = None
    
    if use_osm:
        region_choice = st.selectbox(
            "Region",
            options=['Edinburgh City', 'Central Scotland (Edinburgh-Glasgow)', 'Custom Place'],
            index=0,
            help="Select spatial extent for simulation"
        )
        
        if region_choice == 'Edinburgh City':
            place = "Edinburgh, UK"
            extended_bbox = None
            st.info("🏙️ City scale: ~30km radius, good for walk/bike/car/EV")
        elif region_choice == 'Central Scotland (Edinburgh-Glasgow)':
            place = None
            extended_bbox = (-4.50, 55.70, -2.90, 56.10)
            st.success("📦 Regional scale: ~100km, enables freight between cities")
        else:
            place = st.text_input("City/Place Name", "Edinburgh, UK")
            extended_bbox = None
    
    return {
        'use_osm': use_osm,
        'place': place,
        'bbox': extended_bbox
    }


def _render_story_selection():
    """Render story selection section."""
    st.markdown("### 📖 Story Selection")
    
    user_stories = []
    job_stories = []
    
    if PHASE_4_AVAILABLE:
        try:
            user_parser = UserStoryParser()
            job_parser = JobStoryParser()
            available_users = user_parser.list_available_stories()
            available_jobs = job_parser.list_available_stories()
            
            user_stories = st.multiselect(
                "User Stories",
                available_users,
                default=available_users[:min(5, len(available_users))],
                help="Select which personas to include"
            )
            
            job_stories = st.multiselect(
                "Job Stories", 
                available_jobs,
                default=available_jobs[:min(5, len(available_jobs))],
                help="Select which job contexts to include"
            )
        except Exception as e:
            st.warning(f"Stories not found: {e}")
            user_stories = ['eco_warrior', 'budget_student', 'business_commuter']
            job_stories = ['morning_commute', 'flexible_leisure']
    
    return user_stories, job_stories


def _render_advanced_features():
    """Render advanced features section."""
    st.markdown("### 🔬 Advanced Features")
    
    use_congestion = st.checkbox("Enable Congestion", value=False)
    
    # Infrastructure
    st.markdown("**🔌 Infrastructure (Phase 4.5)**")
    enable_infrastructure = st.checkbox(
        "Enable Infrastructure Awareness", 
        value=True,
        help="EV range constraints, charging stations, grid capacity"
    )
    
    if enable_infrastructure:
        with st.expander("⚙️ Infrastructure Parameters"):
            num_chargers = st.slider("Public Chargers", 10, 100, 50, 10)
            num_depots = st.slider("Commercial Depots", 1, 20, 5, 1)
            grid_capacity_mw = st.slider("Grid Capacity (MW)", 100, 2000, 1000, 100)
    else:
        num_chargers = 0
        num_depots = 0
        grid_capacity_mw = 1000
    
    # Social networks
    enable_social = False
    use_realistic = False
    decay_rate = 0.0
    habit_weight = 0.0
    
    if PHASE_4_AVAILABLE:
        enable_social = st.checkbox("Enable Social Networks", value=True)
        
        if enable_social:
            use_realistic = st.checkbox("Use Realistic Influence", value=True)
            
            if use_realistic:
                with st.expander("⚙️ Influence Parameters"):
                    decay_rate = st.slider("Decay Rate", 0.05, 0.30, 0.15, 0.05)
                    habit_weight = st.slider("Habit Weight", 0.0, 0.6, 0.4, 0.1)
    
    return {
        'use_congestion': use_congestion,
        'enable_infrastructure': enable_infrastructure,
        'num_chargers': num_chargers,
        'num_depots': num_depots,
        'grid_capacity_mw': grid_capacity_mw,
        'enable_social': enable_social,
        'use_realistic': use_realistic,
        'decay_rate': decay_rate,
        'habit_weight': habit_weight
    }


def _render_scenario_selection():
    """
    🆕 Phase 4.5B: Render scenario selection section.
    
    Returns:
        dict: Scenario configuration
    """
    st.markdown("### 📋 Policy Scenarios (Phase 4.5B)")
    
    # Check if scenarios available
    scenarios_dir = Path(__file__).resolve().parent.parent / 'scenarios' / 'configs'
    available_scenarios = list_available_scenarios(scenarios_dir)
    
    if not available_scenarios:
        st.warning("⚠️ No scenarios found. Run `setup_scenarios.py` to create examples.")
        return {'scenario_name': None, 'scenarios_dir': scenarios_dir}
    
    # Add "None (Baseline)" option
    scenario_options = ['None (Baseline)'] + available_scenarios
    
    selected = st.selectbox(
        "Select Policy Scenario",
        options=scenario_options,
        index=0,
        help="Choose a policy scenario to apply, or None for baseline"
    )
    
    scenario_name = None if selected == 'None (Baseline)' else selected
    
    # Show scenario details if selected
    if scenario_name:
        scenario_info = get_scenario_info(scenario_name, scenarios_dir)
        if scenario_info:
            with st.expander("📝 Scenario Details", expanded=True):
                st.write(f"**Description:** {scenario_info['description']}")
                st.write(f"**Policies:** {scenario_info['num_policies']}")
                
                st.markdown("**Expected Outcomes:**")
                for outcome, value in scenario_info['expected_outcomes'].items():
                    st.write(f"- {outcome}: {value:+.1%}")
    
    return {
        'scenario_name': scenario_name,
        'scenarios_dir': scenarios_dir
    }