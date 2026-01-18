"""
ui/sidebar_config.py

Sidebar configuration with Phase 4.5G test mode and FIXED policy scenario dropdown.
"""

import streamlit as st
from pathlib import Path
import sys
import yaml

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
    """Render standard simulation configuration."""
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
        
        # Scenario selection - ✅ FIXED
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
            "Gig Economy Delivery (15km)",
            "HGV Construction Delivery (67km)",  # ✅ ADDED for freight testing
            "Van Service Call (25km)",
            "Truck Regional Distribution (120km)",
        ]
    )
    
    # Get pre-configured test
    origin_name, dest_name, user_story, job_story, expected_modes = _get_test_case_config(test_case)
    
    st.info(f"🗺️ **Route**: {origin_name} → {dest_name}")
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
        "Gig Economy Delivery (15km)": (
            "Edinburgh", "Leith",
            "delivery_driver", "gig_economy_delivery",
            ["cargo_bike", "van_electric"]
        ),
        "HGV Construction Delivery (67km)": (  # ✅ NEW
            "Edinburgh", "Glasgow",
            "freight_driver", "hgv_construction_delivery_generated",
            ["hgv_diesel", "hgv_electric", "truck_diesel"]
        ),
        "Van Service Call (25km)": (  # ✅ NEW
            "Edinburgh", "Livingston",
            "service_engineer", "service_engineer_call",
            ["van_electric", "van_diesel"]
        ),
        "Truck Regional Distribution (120km)": (  # ✅ NEW
            "Edinburgh", "Stirling",
            "freight_driver", "truck_regional_distribution_generated",
            ["truck_diesel", "truck_electric"]
        ),
    }
    return configs.get(test_case, (
        "Edinburgh", "Glasgow", 
        "eco_warrior", "morning_commute",
        ["walk", "bike", "bus"]
    ))


# ============================================================================
# HELPER FUNCTIONS
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
            options=['Edinburgh City', 'Central Scotland (Aberdeen-Edinburgh-Glasgow)', 
                     'Scotland 3-City Corridor (Aberdeen-Edinburgh-Glasgow)', 'Custom Place'],
            index=0,
            help="Select spatial extent for simulation"
        )
        
        if region_choice == 'Edinburgh City':
            place = "Edinburgh, UK"
            extended_bbox = None
            st.info("🏙️ City scale: ~30km radius, good for walk/bike/car/EV")
        elif region_choice == 'Central Scotland (Aberdeen-Edinburgh-Glasgow)':
            place = None
            # OSMnx (min_lat, min_lon, max_lat, max_lon)
            extended_bbox = (-4.30, 55.80, -3.10, 56.00)
            st.success("📦 Regional scale: ~100km, enables freight between cities")
        elif region_choice == 'Scotland 3-City Corridor (Aberdeen-Edinburgh-Glasgow)':
            place = None
            extended_bbox = (-4.30, 55.85, -2.05, 57.20)
            st.success("🚛 3-City: Aberdeen-Edinburgh-Glasgow (~150km corridor, 120k nodes)")
        else:  # Custom Place
            # Session state handling
            if 'custom_place' not in st.session_state:
                st.session_state.custom_place = "Edinburgh, UK"
            
            custom_input = st.text_input(
                "City/Place Name",
                value=st.session_state.custom_place,
                key="custom_place_input_form",
                help="Enter any city or place name"
            )
            
            if custom_input and custom_input != st.session_state.custom_place:
                st.session_state.custom_place = custom_input
            
            place = st.session_state.custom_place
            extended_bbox = None
            st.info(f"Will load: {place}")
    
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
    """
    ✅ FIXED: Phase 4.5B: Render scenario selection section.
    
    Returns:
        dict: Scenario configuration
    """
    st.markdown("### 📋 Policy Scenarios (Phase 4.5B)")
    
    # Check if scenarios available
    scenarios_dir = Path(__file__).resolve().parent.parent / 'scenarios' / 'configs'
    available_scenarios = list_available_scenarios(scenarios_dir)
    
    if not available_scenarios:
        st.warning("⚠️ No scenarios found in scenarios/configs/")
        st.info("💡 Create YAML files in scenarios/configs/ to define policy scenarios")
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
                
                if scenario_info.get('expected_outcomes'):
                    st.markdown("**Expected Outcomes:**")
                    for outcome, value in scenario_info['expected_outcomes'].items():
                        st.write(f"- {outcome}: {value:+.1%}")
    
    return {
        'scenario_name': scenario_name,
        'scenarios_dir': scenarios_dir
    }


def list_available_scenarios(scenarios_dir: Path) -> list:
    """
    ✅ FIXED: List all available scenario YAML files.
    
    Args:
        scenarios_dir: Path to scenarios/configs directory
    
    Returns:
        List of scenario names (without .yaml extension)
    """
    if not scenarios_dir.exists():
        return []
    
    yaml_files = list(scenarios_dir.glob('*.yaml'))
    
    # Return filenames without extension
    scenario_names = [f.stem for f in yaml_files]
    
    return sorted(scenario_names)


def get_scenario_info(scenario_name: str, scenarios_dir: Path) -> dict:
    """
    ✅ FIXED: Load scenario metadata from YAML file (supports multi-document).
    
    Args:
        scenario_name: Scenario filename (without .yaml)
        scenarios_dir: Path to scenarios/configs directory
    
    Returns:
        Dict with scenario metadata
    """
    scenario_path = scenarios_dir / f"{scenario_name}.yaml"
    
    if not scenario_path.exists():
        return {}
    
    try:
        with open(scenario_path, 'r') as f:
            # ✅ FIXED: Use safe_load_all for multi-document YAML
            documents = list(yaml.safe_load_all(f))
        
        # First document should have metadata
        if not documents:
            return {'description': 'Empty scenario file', 'num_policies': 0, 'expected_outcomes': {}}
        
        first_doc = documents[0]
        
        # Extract metadata from first document
        metadata = first_doc.get('metadata', {})
        
        # Count policies across all documents
        total_policies = 0
        for doc in documents:
            if doc and 'policies' in doc:
                total_policies += len(doc.get('policies', []))
        
        return {
            'description': metadata.get('description', 'No description'),
            'num_policies': total_policies,
            'expected_outcomes': metadata.get('expected_outcomes', {}),
        }
    
    except Exception as e:
        st.error(f"Error loading scenario {scenario_name}: {e}")
        return {}