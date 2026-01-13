"""
ui/sidebar_config.py

Sidebar configuration with Phase 4.5G test mode (NON-DISRUPTIVE).
"""

import streamlit as st
from pathlib import Path
import sys

parent_dir = Path(__file__).resolve().parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from simulation.config.simulation_config import SimulationConfig

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
    
    # ✅ NEW: Test Mode Toggle (at the top, outside form)
    test_mode = st.checkbox(
        "🧪 Enable Test Mode (Phase 4.5G)",
        value=False,
        help="Single-agent testing for multi-modal validation"
    )
    
    if test_mode:
        return _render_test_mode()
    else:
        return _render_standard_mode()


def _render_standard_mode():
    """Render standard simulation configuration (your existing code)."""
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
        
        # Scenario selection
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


def _render_test_mode():
    """✅ NEW: Render Phase 4.5G test mode configuration."""
    st.subheader("🎯 Phase 4.5G Test Configuration")
    
    # Test case selection
    test_case = st.selectbox(
        "Select Test Case",
        [
            "Edinburgh-Glasgow Rail (80km)",
            "Island Ferry Route (50km)",
            "Last Mile Scooter (3km)",
            "Accessible Tram (10km)",
            "Gig Economy Delivery (15km)",  # ✅ ADDED for testing fix
        ]
    )
    
    # Get pre-configured test
    origin_name, dest_name, user_story, job_story, expected_modes = _get_test_case_config(test_case)
    
    st.info(f"📍 **Route**: {origin_name} → {dest_name}")
    st.info(f"👤 **Persona**: {user_story}")
    st.info(f"📋 **Job**: {job_story}")
    st.success(f"✅ **Expected Modes**: {', '.join(expected_modes)}")
    
    # Create single-agent test config
    config = SimulationConfig(
        steps=50,  # Short test
        num_agents=1,  # Single agent
        place="Edinburgh, UK",
        extended_bbox=None,
        use_osm=True,
        user_stories=[user_story],
        job_stories=[job_story],
        enable_infrastructure=True,
        enable_social=False,
        num_chargers=50,
        num_depots=5,
        grid_capacity_mw=1000
    )
    
    run_btn = st.button("🧪 Run Test", type="primary", key="test_run")
    
    # Store expected modes for validation (in session state)
    if run_btn:
        st.session_state.test_expected_modes = expected_modes
    
    return config, run_btn


def _get_test_case_config(test_case: str) -> tuple:
    """Get origin, destination, user, job, and expected modes for test case."""
    configs = {
        "Edinburgh-Glasgow Rail (80km)": (
            "Edinburgh", "Glasgow",
            "long_distance_commuter", "intercity_train_commute",
            ["local_train", "intercity_train"]
        ),
        "Island Ferry Route (50km)": (
            "Isle of Arran", "Glasgow",
            "island_resident", "island_ferry_trip",
            ["ferry_diesel", "ferry_electric"]
        ),
        "Last Mile Scooter (3km)": (
            "Edinburgh Waverley", "Edinburgh Castle",
            "long_distance_commuter", "last_mile_scooter",
            ["e_scooter", "bike", "walk"]
        ),
        "Accessible Tram (10km)": (
            "Edinburgh City Centre", "Edinburgh Airport",
            "disabled_commuter", "accessible_tram_journey",
            ["tram", "bus"]
        ),
        "Gig Economy Delivery (15km)": (  # ✅ NEW TEST CASE
            "Edinburgh", "Leith",
            "delivery_driver", "gig_economy_delivery",
            ["cargo_bike", "van_electric"]  # Should NOT get truck!
        ),
    }
    return configs.get(test_case, (
        "Edinburgh", "Glasgow", 
        "eco_warrior", "morning_commute",
        ["walk", "bike", "bus"]
    ))


# ============================================================================
# EXISTING HELPER FUNCTIONS (unchanged)
# ============================================================================

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
            job_stories = ['morning_commute', 'shopping_trip']
    
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
    """Render scenario selection section."""
    st.markdown("### 📋 Policy Scenarios")
    
    # Check if scenarios available
    scenarios_dir = Path(__file__).resolve().parent.parent / 'scenarios' / 'configs'
    
    # Simplified: just show None for now
    return {
        'scenario_name': None,
        'scenarios_dir': scenarios_dir
    }