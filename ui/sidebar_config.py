"""
ui/sidebar_config.py

Sidebar configuration with Phase 5.1 combined scenarios.

"""

import streamlit as st
from pathlib import Path
import sys
import yaml

parent_dir = Path(__file__).resolve().parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from simulation.config.simulation_config import SimulationConfig

# Check if story modules are available
try:
    from agent.user_stories import UserStoryParser
    from agent.job_stories import JobStoryParser
    STORIES_AVAILABLE = True
except ImportError:
    STORIES_AVAILABLE = False


def render_sidebar_config():
    """
    Render sidebar configuration panel.
    
    Returns:
        tuple: (SimulationConfig, run_button_clicked)
    """
    st.header("⚙️ Simulation Configuration")
    
    # ============================================================================
    # FIX: Combined scenario selection OUTSIDE form (so it updates immediately)
    # ============================================================================
    st.markdown("---")
    combined_config = _render_combined_scenario_selection()
    st.markdown("---")
    
    with st.form("config_form"):
        # Basic settings
        st.markdown("### 📊 Basic Settings")
        steps = st.number_input("Simulation Steps", 20, 200, 100, 20)
        num_agents = st.number_input("Number of Agents", 10, 200, 50, 10)
        
        st.markdown("---")
        
        # Location settings
        region_info = _render_location_settings()
        place, extended_bbox = region_info['place'], region_info['bbox']
        use_osm = region_info['use_osm']
        region_name = region_info['region_name']
        
        st.markdown("---")
        
        # Story selection
        user_stories, job_stories = _render_story_selection()
        
        st.markdown("---")
        
        # Advanced features
        advanced_config = _render_advanced_features()
        
        st.markdown("---")
        
        # Scenario selection (Phase 5.1) - only show if not using combined
        if not combined_config['use_combined']:
            scenario_config = _render_scenario_selection()
        else:
            # Skip simple scenarios if combined is active
            scenarios_dir = Path(__file__).resolve().parent.parent / 'scenarios' / 'configs'
            scenario_config = {'scenario_name': None, 'scenarios_dir': scenarios_dir}
            st.info("ℹ️ Simple scenarios disabled (using combined scenario)")
        
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
        region_name=region_name,
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
        scenario_name=scenario_config['scenario_name'] if not combined_config['use_combined'] else None,
        scenarios_dir=scenario_config['scenarios_dir'],
        combined_scenario_data=combined_config['combined_scenario_data'] if combined_config['use_combined'] else None,
        # Weather parameters (Phase 5.2)
        weather_enabled=advanced_config['enable_weather'],
        weather_source=advanced_config['weather_source'],
        weather_temp_adjustment=advanced_config['weather_temp_adjustment'],
        weather_precip_multiplier=advanced_config['weather_precip_multiplier'],
        weather_wind_multiplier=advanced_config['weather_wind_multiplier'],
    )
    
    return config, run_btn


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
            options=[
                'Edinburgh City',
                'Central Scotland (Edinburgh-Glasgow)',
                'Scotland 3-City Corridor (Aberdeen-Edinburgh-Glasgow)',
                'Custom Place'
            ],
            index=0,
            help="Select spatial extent for simulation"
        )
        
        if region_choice == 'Edinburgh City':
            place = "Edinburgh, UK"
            extended_bbox = None
            region_name = "Edinburgh City" 
            st.info("🏙️ City scale: ~30km radius, good for walk/bike/car/EV")
        
        elif region_choice == 'Central Scotland (Edinburgh-Glasgow)':
            place = None
            extended_bbox = (-4.30, 55.80, -3.10, 56.00)
            region_name = "Central Scotland (Edinburgh-Glasgow)" 
            st.success("📦 2-City: Edinburgh-Glasgow corridor (~80km, 60k nodes)")
        
        elif region_choice == 'Scotland 3-City Corridor (Aberdeen-Edinburgh-Glasgow)':
            place = None
            extended_bbox = (-4.30, 55.85, -2.05, 57.20)
            region_name = "Scotland 3-City Corridor (Aberdeen-Edinburgh-Glasgow)"
            st.success("🚛 3-City: Aberdeen-Edinburgh-Glasgow (~240km, 120-150k nodes)")
        
        else:  # Custom Place
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
            region_name = place
            st.info(f"🗺️ Will load: {place}")
    else:
        place = "Edinburgh, UK"
        extended_bbox = None
        region_name = "Synthetic Network"
    
    return {
        'use_osm': use_osm,
        'place': place,
        'bbox': extended_bbox,
        'region_name': region_name
    }


def _render_story_selection():
    """Render story selection section."""
    st.markdown("### 📖 Story Selection")
    
    user_stories = []
    job_stories = []
    
    if STORIES_AVAILABLE:
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
    
    # Infrastructure (Phase 5.1)
    st.markdown("**🔌 Infrastructure**")
    enable_infrastructure = st.checkbox(
        "Enable Infrastructure Awareness", 
        value=True,
        help="EV range constraints, charging stations, grid capacity"
    )
    
    if enable_infrastructure:
        with st.expander("⚙️ Infrastructure Parameters"):
            num_chargers = st.slider("Public Chargers", 10, 200, 50, 10)
            num_depots = st.slider("Commercial Depots", 1, 20, 5, 1)
            grid_capacity_mw = st.slider(
                "Grid Capacity (MW)", 
                1, 2000, 100, 1,
                help="💡 Stress test: 1-10 MW | Normal: 50-200 MW | Large scale: 500+ MW"
            )
            
            # Show contextual guidance
            if grid_capacity_mw < 10:
                st.success("🔥 Stress test mode: High utilization expected!")
            elif grid_capacity_mw > 500:
                st.warning("⚠️ Grid >500 MW may show 0.0% utilization. Try 1-100 MW for better visibility.")
    else:
        num_chargers = 0
        num_depots = 0
        grid_capacity_mw = 100
    
    # Weather System (Phase 5.2)
    st.markdown("**🌤️ Weather System**")
    enable_weather = st.checkbox(
        "Enable Weather System",
        value=False,
        help="Temperature, precipitation, wind affect EV range and mode choice"
    )
    
    # Initialize defaults
    weather_source = 'live'
    weather_temp_adjustment = 0.0
    weather_precip_multiplier = 1.0
    weather_wind_multiplier = 1.0
    
    if enable_weather:
        # Weather source OUTSIDE expander so it shows immediately
        weather_source = st.selectbox(
            "Weather Source",
            options=['live', 'historical', 'synthetic'],
            index=2,  # Default to synthetic for testing
            help="Live: Current forecast | Historical: Jan 2024 | Synthetic: Patterns"
        )
        
        # Perturbations inside expander
        with st.expander("⚙️ Weather Perturbations (Optional)"):
            st.caption("Modify weather conditions for scenario testing")
            
            weather_temp_adjustment = st.slider(
                "Temperature Adjustment (°C)",
                min_value=-10.0,
                max_value=+10.0,
                value=0.0,
                step=0.5,
                help="Add/subtract from actual temperature. Negative = colder (winter stress test)"
            )
            
            weather_precip_multiplier = st.slider(
                "Precipitation Multiplier",
                min_value=0.0,
                max_value=3.0,
                value=1.0,
                step=0.1,
                help="1.0 = normal, 2.0 = double rainfall, 0.0 = no rain"
            )
            
            weather_wind_multiplier = st.slider(
                "Wind Speed Multiplier",
                min_value=0.5,
                max_value=2.0,
                value=1.0,
                step=0.1,
                help="1.5 = 50% stronger winds"
            )
        
        # Show impact preview (outside expander for visibility)
        if weather_temp_adjustment != 0 or weather_precip_multiplier != 1.0 or weather_wind_multiplier != 1.0:
            st.info("📊 Weather perturbations active - simulating extreme conditions")
    
    # Social networks
    enable_social = False
    use_realistic = False
    decay_rate = 0.0
    habit_weight = 0.0
    
    if STORIES_AVAILABLE:
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
        'habit_weight': habit_weight,
        # Weather parameters
        'enable_weather': enable_weather,
        'weather_source': weather_source,
        'weather_temp_adjustment': weather_temp_adjustment,
        'weather_precip_multiplier': weather_precip_multiplier,
        'weather_wind_multiplier': weather_wind_multiplier,
    }


def _render_scenario_selection():
    """
    Render simple scenario selection section (Phase 5.1).
    
    Returns:
        dict: Scenario configuration
    """
    st.markdown("### 📋 Simple Policy Scenarios")
    
    scenarios_dir = Path(__file__).resolve().parent.parent / 'scenarios' / 'configs'
    available_scenarios = list_available_scenarios(scenarios_dir)
    
    if not available_scenarios:
        st.warning("⚠️ No scenarios found in scenarios/configs/")
        return {'scenario_name': None, 'scenarios_dir': scenarios_dir}
    
    scenario_options = ['None (Baseline)'] + available_scenarios
    
    selected = st.selectbox(
        "Select Simple Scenario",
        options=scenario_options,
        index=0,
        help="Choose a single policy scenario, or None for baseline"
    )
    
    scenario_name = None if selected == 'None (Baseline)' else selected
    
    if scenario_name:
        scenario_info = get_scenario_info(scenario_name, scenarios_dir)
        if scenario_info:
            with st.expander("📝 Scenario Details", expanded=False):
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


def _render_combined_scenario_selection():
    """
    Phase 5.1: Combined scenario selector.
    MOVED OUTSIDE FORM so dropdown appears immediately when checkbox is checked.
    """
    st.markdown("### 🔗 Combined Scenarios (Advanced)")
    
    # Checkbox OUTSIDE form
    use_combined = st.checkbox(
        "Use Combined Scenario", 
        value=False,
        help="Combine multiple policies with interaction rules and constraints",
        key="use_combined_checkbox"
    )
    
    if not use_combined:
        return {'use_combined': False, 'combined_scenario_data': None}
    
    # Load combined scenarios
    combined_dir = Path(__file__).parent.parent / 'scenarios' / 'combined_configs'
    
    if not combined_dir.exists():
        st.warning("⚠️ Create folder: scenarios/combined_configs/")
        st.info("💡 Add YAML files like aggressive_electrification.yaml")
        return {'use_combined': False, 'combined_scenario_data': None}
    
    # Load scenarios
    scenarios = {}
    yaml_files = list(combined_dir.glob('*.yaml'))
    
    for yaml_file in yaml_files:
        try:
            with open(yaml_file, 'r') as f:
                for doc in yaml.safe_load_all(f):
                    if doc and 'name' in doc:
                        scenarios[doc['name']] = doc
        except Exception as e:
            st.error(f"Error loading {yaml_file.name}: {e}")
    
    if not scenarios:
        st.info("💡 Add YAML files to scenarios/combined_configs/")
        with st.expander("📝 Example YAML", expanded=False):
            st.code("""# aggressive_electrification.yaml
name: Aggressive Electrification Push
description: Comprehensive EV transition strategy

base_scenarios:
  - complete_supply_chain_electrification
  - depot_based_electrification
  - economy_7_style_tariff

interaction_rules:
  - condition: "step > 20"
    action: reduce_charging_costs
    parameters:
      multiplier: 0.8
    priority: 100

constraints:
  - type: budget
    limit: 50000000
    warning_threshold: 0.8
""", language="yaml")
        return {'use_combined': False, 'combined_scenario_data': None}
    
    # Selectbox OUTSIDE form (updates immediately)
    selected_name = st.selectbox(
        "Select Combined Scenario", 
        list(scenarios.keys()),
        key="combined_scenario_selector"
    )
    
    # Show scenario preview
    if selected_name:
        scenario_data = scenarios[selected_name]
        with st.expander("📝 Scenario Preview", expanded=False):
            st.write(f"**Description:** {scenario_data.get('description', 'No description')}")
            
            base_scenarios = scenario_data.get('base_scenarios', [])
            st.write(f"**Base Scenarios ({len(base_scenarios)}):**")
            for bs in base_scenarios[:5]:  # Show first 5
                st.write(f"  • {bs}")
            if len(base_scenarios) > 5:
                st.write(f"  ... and {len(base_scenarios) - 5} more")
            
            st.write(f"**Interaction Rules:** {len(scenario_data.get('interaction_rules', []))}")
            st.write(f"**Constraints:** {len(scenario_data.get('constraints', []))}")
            
            # Show expected outcomes if available
            if 'expected_outcomes' in scenario_data:
                st.markdown("**Expected Outcomes:**")
                for outcome, value in scenario_data['expected_outcomes'].items():
                    if isinstance(value, (int, float)):
                        st.write(f"  • {outcome}: {value:+.1%}")
                    else:
                        st.write(f"  • {outcome}: {value}")
    
    return {
        'use_combined': True,
        'combined_scenario_data': scenarios[selected_name]
    }


def list_available_scenarios(scenarios_dir: Path) -> list:
    """List all available scenario YAML files."""
    if not scenarios_dir.exists():
        return []
    
    yaml_files = list(scenarios_dir.glob('*.yaml'))
    scenario_names = [f.stem for f in yaml_files]
    
    return sorted(scenario_names)


def get_scenario_info(scenario_name: str, scenarios_dir: Path) -> dict:
    """Load scenario metadata from YAML file (supports multi-document)."""
    scenario_path = scenarios_dir / f"{scenario_name}.yaml"
    
    if not scenario_path.exists():
        return {}
    
    try:
        with open(scenario_path, 'r') as f:
            documents = list(yaml.safe_load_all(f))
        
        if not documents:
            return {'description': 'Empty scenario file', 'num_policies': 0, 'expected_outcomes': {}}
        
        first_doc = documents[0]
        metadata = first_doc.get('metadata', {})
        
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