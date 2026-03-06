"""
ui/sidebar_config.py

Sidebar configuration with Phase 5.1 combined scenarios.

"""

import streamlit as st
from pathlib import Path
from typing import Any, Dict, Optional, List
import sys
import yaml

parent_dir = Path(__file__).resolve().parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from simulation.config.simulation_config import SimulationConfig
from ui.sidebar_system_dynamics import render_sd_parameters_section, render_sd_info_box

# Check if story modules are available
try:
    from agent.user_stories import UserStoryParser
    from agent.job_stories import JobStoryParser
    STORIES_AVAILABLE = True
except ImportError:
    STORIES_AVAILABLE = False

# Import policy parameter controls
from ui.widgets.policy_parameter_controls import (
    render_policy_parameter_controls,
    apply_parameter_overrides
)

# Phase 7.1 - Extended Temporal Simulation testing
from ui.components.temporal_settings import render_temporal_settings

def render_sidebar_config():
    """
    Render sidebar configuration panel.
    
    Returns:
        tuple: (SimulationConfig, run_button_clicked)
    """
    st.header("⚙️ Simulation Configuration")
    
    # ============================================================================
    # Combined scenario selection OUTSIDE form (so it updates immediately)
    # ============================================================================
    st.markdown("---")
    st.markdown("### 🔗 Policy Configuration")

    # Policy mode selection
    policy_mode = st.radio(
        "Policy Mode",
        options=["Default Policies", "Combined Scenario", "None (Baseline)"],
        index=0,
        help="Choose how infrastructure policies are managed"
    )

    combined_scenario_data = None
    use_default_policies = False
    use_combined = False
    policy_thresholds = None

    if policy_mode == "Combined Scenario":
        # Advanced combined scenarios
        combined_scenario_data = _render_combined_scenario_selector()
        use_combined = True
        
    elif policy_mode == "Default Policies":
        # Use default policies
        use_default_policies = True
        
        st.info(
            "💡 **Default Policies Active**\n\n"
            "Basic infrastructure management:\n"
            "- Grid expansion at 85% utilization\n"
            "- Depot chargers at 50% EV adoption\n"
            "- Public chargers at 80% utilization\n"
            "- Night-time pricing discounts"
        )
        
        # Option to customize default policy thresholds
        if st.checkbox("⚙️ Customize Default Policy Thresholds", value=False):
            with st.expander("Default Policy Settings"):
                grid_threshold = st.slider(
                    "Grid Expansion Trigger (%)",
                    min_value=70,
                    max_value=95,
                    value=85,
                    step=5,
                    help="Expand grid when utilization exceeds this %"
                )
                
                ev_threshold = st.slider(
                    "Depot Addition Trigger (% EV Adoption)",
                    min_value=30,
                    max_value=70,
                    value=50,
                    step=5,
                    help="Add depot chargers when EV adoption exceeds this %"
                )
                
                charger_threshold = st.slider(
                    "Public Charger Addition Trigger (%)",
                    min_value=70,
                    max_value=95,
                    value=80,
                    step=5,
                    help="Add public chargers when utilization exceeds this %"
                )
                
                # Store custom thresholds
                policy_thresholds = {
                    'grid_expansion': grid_threshold / 100,
                    'depot_addition': ev_threshold / 100,
                    'charger_addition': charger_threshold / 100
                }
    else:
        # No policies - baseline simulation
        st.warning(
            "⚠️ **No Policies Active**\n\n"
            "Running baseline simulation without dynamic infrastructure management."
        )

    st.markdown("---")

    # Advanced parameter controls
    with st.expander("🎛️ Advanced Parameter Tuning", expanded=False):
        param_overrides = render_policy_parameter_controls()

    st.markdown("---")

    # ========================================================================
    # Weather configuration OUTSIDE form (so it updates immediately)
    # ========================================================================
    weather_config = _render_weather_configuration()

    st.markdown("---")

    # ========================================================================
    # Location configuration OUTSIDE form (so geocoding works)
    # ========================================================================
    region_info = _render_location_settings()
    place, extended_bbox = region_info['place'], region_info['bbox']
    use_osm = region_info['use_osm']
    region_name = region_info['region_name']

    st.markdown("---")

    # ========================================================================
    # System Dynamics Configuration (OUTSIDE form for immediate UI update)
    # ========================================================================
    st.markdown("### 🔬 System Dynamics")
    
    use_custom_sd = st.checkbox(
        "Customize SD Parameters",
        value=False,
        help="Adjust macro-level dynamics parameters",
        key="use_custom_sd_params"
    )
    
    sd_params = None
    if use_custom_sd:
        with st.expander("⚙️ SD Parameter Controls", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                sd_growth_rate = st.slider(
                    "Growth Rate (r)",
                    min_value=0.01, max_value=0.20, value=0.05, step=0.01,
                    help="Base adoption rate",
                    key="sd_r"
                )
                sd_infrastructure_feedback = st.slider(
                    "Infrastructure Feedback",
                    min_value=0.0, max_value=0.200, value=0.02, step=0.001,
                    help="Charger availability boost",
                    key="sd_infra"
                )
            with col2:
                sd_carrying_capacity = st.slider(
                    "Carrying Capacity (K)",
                    min_value=0.50, max_value=1.00, value=0.80, step=0.05,
                    help="Maximum sustainable adoption",
                    key="sd_K"
                )
                sd_social_influence = st.slider(
                    "Social Influence",
                    min_value=0.0, max_value=0.200, value=0.03, step=0.001,
                    help="Peer effects strength",
                    key="sd_social"
                )
            
            # Store parameters
            sd_params = {
                'growth_rate': sd_growth_rate,
                'carrying_capacity': sd_carrying_capacity,
                'infrastructure_feedback': sd_infrastructure_feedback,
                'social_influence': sd_social_influence,
            }
            
            st.caption("💡 These parameters control logistic growth dynamics at the system level")
    
    st.sidebar.markdown("---")
    
    with st.form("config_form"):
        # Basic settings
        st.markdown("### 📊 Basic Settings")
        steps = st.number_input("Simulation Steps", 20, 500, 100, 20)
        num_agents = st.number_input("Number of Agents", 10, 1500, 50, 10)
        
        st.markdown("---")
        
        # Story selection
        user_stories, job_stories = _render_story_selection()
        
        st.markdown("---")
        
        # Advanced features
        advanced_config = _render_advanced_features()
        
        st.markdown("---")
        
        # Scenario selection - only show if not using combined or default policies
        if not use_combined:
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

    # =======================================================================
    # Build config
    # =======================================================================
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
        
        # Scenario configuration
        scenario_name=scenario_config['scenario_name'] if not use_combined else None,
        scenarios_dir=scenario_config['scenarios_dir'],
        
        # Policy configuration
        combined_scenario_data=combined_scenario_data,
        use_default_policies=use_default_policies,
        policy_thresholds=policy_thresholds,
        
        # Weather parameters
        weather_enabled=weather_config['enable_weather'],
        weather_source=weather_config['weather_source'],
        weather_temp_adjustment=weather_config['weather_temp_adjustment'],
        weather_precip_multiplier=weather_config['weather_precip_multiplier'],
        weather_wind_multiplier=weather_config['weather_wind_multiplier'],
    )
    
    # Apply System Dynamics config (ALWAYS - use defaults if not customized)
    from simulation.config.system_dynamics_config import SystemDynamicsConfig
    
    if sd_params:
        # Use custom parameters
        config.system_dynamics = SystemDynamicsConfig(
            ev_growth_rate_r=sd_params['growth_rate'],
            ev_carrying_capacity_K=sd_params['carrying_capacity'],
            infrastructure_feedback_strength=sd_params['infrastructure_feedback'],
            social_influence_strength=sd_params['social_influence'],
        )
        st.sidebar.success("✅ Custom System Dynamics parameters applied")
    else:
        # Use default parameters (Always create this for baseline!)
        config.system_dynamics = SystemDynamicsConfig()
        # SD will run with defaults: r=0.05, K=0.80, feedback=0.02, social=0.03
    
    # Apply parameter overrides if enabled
    if param_overrides:
        config = apply_parameter_overrides(config, param_overrides)

        st.sidebar.subheader("🎯 Real-Time Events")
    
        enable_events = st.sidebar.checkbox(
            "Enable Event Bus (Experimental)",
            value=config.enable_event_bus,
            help="Enable real-time event system. Auto-falls back to in-memory if Redis unavailable."
        )
        config.enable_event_bus = enable_events

        if enable_events:
            subscribe_agents = st.sidebar.checkbox(
                "📢 Subscribe Agents to Events",
                value=config.enable_agent_event_subscription,
                help="Agents perceive policy changes in real-time"
            )
            config.enable_agent_event_subscription = subscribe_agents
            
            # Event settings expander
            with st.sidebar.expander("⚙️ Event Settings", expanded=False):
                # Redis configuration
                col1, col2 = st.columns(2)
                with col1:
                    config.redis_host = st.text_input(
                        "Redis Host",
                        value=config.redis_host,
                        help="Redis server host"
                    )
                with col2:
                    config.redis_port = st.number_input(
                        "Redis Port",
                        value=config.redis_port,
                        min_value=1,
                        max_value=65535
                    )
                
                # Agent perception
                config.agent_perception_radius_km = st.slider(
                    "Agent Perception Radius (km)",
                    min_value=1.0,
                    max_value=50.0,
                    value=config.agent_perception_radius_km,
                    step=1.0,
                    help="How far agents can perceive events"
                )
                
                # Status check
                st.markdown("**Status:**")
                try:
                    import redis
                    client = redis.Redis(
                        host=config.redis_host,
                        port=config.redis_port,
                        socket_connect_timeout=1
                    )
                    client.ping()
                    st.success("✅ Redis available")
                except Exception:
                    st.warning("⚠️ Redis unavailable (will use in-memory fallback)")

        st.markdown("---")

        st.sidebar.success("✅ Advanced parameters applied")
        
        # DEBUG: Show applied values
        with st.sidebar.expander("🔍 Applied Values (Debug)", expanded=False):
            st.write(f"Grid Capacity: {config.grid_capacity_mw:.1f} MW")
            st.write(f"Num Chargers: {config.num_chargers}")
            st.write(f"Eco Desire: {config.agents.behavior.eco_desire_mean:.2f}")
    
    # Phase 5.3: System Dynamics info box (OUTSIDE form, at bottom of sidebar)
    st.markdown("---")
    render_sd_info_box()
    
    return config, run_btn


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _geocode_place(query: str) -> Optional[dict]:
    """
    Geocode a place name using Nominatim (OpenStreetMap).

    Returns dict with keys: lat, lon, display_name, bbox
    or None if geocoding fails.
    """
    try:
        import requests
        url = "https://nominatim.openstreetmap.org/search"
        resp = requests.get(
            url,
            params={"q": query.strip(), "format": "json", "limit": 1},
            headers={"User-Agent": "RTD-SIM/1.0 (freight-decarbonisation-simulator)"},
            timeout=8,
        )
        results = resp.json()
        if results:
            r = results[0]
            return {
                "lat":          float(r["lat"]),
                "lon":          float(r["lon"]),
                "display_name": r["display_name"],
                "bbox":         r.get("boundingbox"),  # [min_lat, max_lat, min_lon, max_lon]
            }
    except Exception:
        pass
    return None


def _locations_to_bbox(locations: list, padding: float = 0.3) -> tuple:
    """
    Convert a list of {lat, lon} dicts into an (west, south, east, north)
    bounding box with padding to give OSMnx a usable area.
    """
    lats = [loc["lat"] for loc in locations]
    lons = [loc["lon"] for loc in locations]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)

    # If all points are the same place, spread the box by padding alone
    lat_span = max_lat - min_lat
    lon_span = max_lon - min_lon
    pad_lat  = max(padding, lat_span * 0.2)
    pad_lon  = max(padding, lon_span * 0.2)

    return (
        round(min_lon - pad_lon, 6),  # west
        round(min_lat - pad_lat, 6),  # south
        round(max_lon + pad_lon, 6),  # east
        round(max_lat + pad_lat, 6),  # north
    )


def _render_location_map_picker() -> list:
    """
    Render an interactive Leaflet map inside a Streamlit HTML component.

    Users click to place/remove pins. Returns list of {lat, lon} dicts
    stored in st.session_state['map_pins'].
    The component communicates pin changes back via a hidden text input
    that the user manually updates — because st.components.v1.html is
    one-way (no callback). We store pins in session_state and let the
    user confirm via the 'Use these pins' button.
    """
    import streamlit.components.v1 as components

    # Initialise session state
    if "map_pins" not in st.session_state:
        st.session_state.map_pins = []

    # Serialise existing pins for the map to pre-draw
    import json
    existing_pins_json = json.dumps(st.session_state.map_pins)

    leaflet_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8"/>
      <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
      <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
      <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
      <style>
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ font-family: sans-serif; }}
        #map {{ height: 380px; width: 100%; }}
        #info {{
          background: #1e2130; color: #e0e0e0;
          padding: 8px 12px; font-size: 13px;
          border-top: 1px solid #333;
        }}
        #pinlist {{ margin-top:4px; }}
        .pin-entry {{ display:flex; justify-content:space-between; align-items:center;
                      padding: 2px 0; border-bottom: 1px solid #333; }}
        .pin-entry span {{ font-size: 12px; flex:1; margin-right:8px; overflow:hidden;
                           text-overflow:ellipsis; white-space:nowrap; }}
        .rm-btn {{ background:#c0392b; color:white; border:none; border-radius:3px;
                   padding:2px 6px; cursor:pointer; font-size:11px; flex-shrink:0; }}
        #copybox {{ width:100%; margin-top:6px; background:#111; color:#7ec8e3;
                    border:1px solid #444; padding:4px; font-size:11px;
                    font-family:monospace; resize:none; height:36px; }}
        #copybtn {{ margin-top:4px; padding:4px 10px; background:#2a9d8f; color:white;
                    border:none; border-radius:3px; cursor:pointer; font-size:12px; }}
        h4 {{ margin-bottom:4px; font-size:13px; color:#7ec8e3; }}
      </style>
    </head>
    <body>
      <div id="map"></div>
      <div id="info">
        <h4>📍 Click map to place pins &nbsp;|&nbsp; Click pin to remove</h4>
        <div id="pinlist"></div>
        <textarea id="copybox" readonly placeholder="Pins will appear here as lat,lon pairs..."></textarea>
        <button id="copybtn" onclick="copyPins()">📋 Copy pin coords</button>
      </div>
      <script>
        var map = L.map('map').setView([54.5, -3.5], 6);
        L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
          attribution: '© OpenStreetMap contributors', maxZoom: 18
        }}).addTo(map);

        var pins = {existing_pins_json};
        var markers = [];

        function renderPins() {{
          // Clear existing markers
          markers.forEach(function(m) {{ map.removeLayer(m); }});
          markers = [];

          var pinlist = document.getElementById('pinlist');
          pinlist.innerHTML = '';
          var coords = [];

          pins.forEach(function(p, i) {{
            var m = L.marker([p.lat, p.lon], {{
              title: p.label || ('Pin ' + (i+1))
            }}).addTo(map);
            m.bindPopup('<b>' + (p.label || 'Pin ' + (i+1)) + '</b><br>'
              + p.lat.toFixed(5) + ', ' + p.lon.toFixed(5)
              + '<br><button onclick="removePin(' + i + ')" style="margin-top:4px;background:#c0392b;color:white;border:none;border-radius:3px;padding:2px 6px;cursor:pointer">Remove</button>');
            markers.push(m);
            coords.push(p.lat.toFixed(5) + ',' + p.lon.toFixed(5));

            var row = document.createElement('div');
            row.className = 'pin-entry';
            row.innerHTML = '<span>📍 ' + (p.label || 'Pin ' + (i+1))
              + ' (' + p.lat.toFixed(3) + ', ' + p.lon.toFixed(3) + ')</span>'
              + '<button class="rm-btn" onclick="removePin(' + i + ')">✕</button>';
            pinlist.appendChild(row);
          }});

          document.getElementById('copybox').value = coords.join('; ');
        }}

        function removePin(i) {{
          pins.splice(i, 1);
          renderPins();
        }}

        map.on('click', function(e) {{
          var lat = e.latlng.lat;
          var lon = e.latlng.lng;
          pins.push({{ lat: lat, lon: lon, label: 'Pin ' + (pins.length + 1) }});
          renderPins();
          // Auto-open popup on last marker
          markers[markers.length-1].openPopup();
        }});

        function copyPins() {{
          var box = document.getElementById('copybox');
          box.select();
          document.execCommand('copy');
        }}

        renderPins();
      </script>
    </body>
    </html>
    """

    components.html(leaflet_html, height=500, scrolling=False)

    st.caption(
        "👆 Click the map to place pins. Copy the coords from the box, "
        "then paste them into the **Coordinates** input below."
    )

    # Coordinate paste input — user pastes "lat,lon; lat,lon" pairs
    coord_input = st.text_input(
        "Paste pin coordinates (lat,lon; lat,lon ...)",
        value="",
        key="map_pin_coords",
        placeholder="e.g. 51.127, 1.3092; 55.9533, -3.1883",
        help="Copy coords from the map box above and paste here, separated by semicolons",
    )

    pins = []
    if coord_input.strip():
        for part in coord_input.split(";"):
            part = part.strip()
            if not part:
                continue
            try:
                lat_s, lon_s = part.split(",", 1)
                pins.append({"lat": float(lat_s.strip()), "lon": float(lon_s.strip())})
            except ValueError:
                st.warning(f"⚠️ Could not parse coordinates: `{part}` — use format `lat, lon`")

    return pins


def _render_location_settings():
    """Render location configuration section."""
    st.markdown("### 🗺️ Location")
    use_osm = st.checkbox("Use Real Street Network", value=True)

    place = None
    extended_bbox = None
    region_name = "Synthetic Network"

    if use_osm:
        region_choice = st.selectbox(
            "Region",
            options=[
                'Edinburgh City',
                'Central Scotland (Edinburgh-Glasgow)',
                'Scotland 3-City Corridor (Aberdeen-Edinburgh-Glasgow)',
                'Custom Place',
            ],
            index=0,
            help="Select spatial extent for simulation",
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
            # ----------------------------------------------------------------
            # Input method toggle
            # ----------------------------------------------------------------
            input_method = st.radio(
                "Input method",
                options=["📝 Type locations", "🗺️ Click map"],
                index=0,
                horizontal=True,
                key="custom_location_method",
                help="Type place names separated by ; or click the map to drop pins",
            )

            locations_resolved = []   # list of {lat, lon, display_name}
            raw_names = []            # list of human-readable names for region_name

            # ----------------------------------------------------------------
            # Mode A: text input
            # ----------------------------------------------------------------
            if input_method == "📝 Type locations":
                if "custom_text_locations" not in st.session_state:
                    st.session_state.custom_text_locations = "Edinburgh, UK"

                text_input = st.text_input(
                    "Place names (separate multiple with `;`)",
                    value=st.session_state.custom_text_locations,
                    key="custom_text_input",
                    placeholder="e.g. Port of Dover; Edinburgh",
                    help="Type one or more place names. Multiple locations create a bounding box spanning all of them.",
                )

                if text_input:
                    st.session_state.custom_text_locations = text_input

                if text_input and st.button("🔍 Geocode locations", key="geocode_btn"):
                    names = [n.strip() for n in text_input.split(";") if n.strip()]
                    geocoded = []
                    failed = []
                    with st.spinner("Geocoding…"):
                        for name in names:
                            result = _geocode_place(name)
                            if result:
                                geocoded.append(result)
                                raw_names.append(result["display_name"].split(",")[0])
                            else:
                                failed.append(name)

                    if failed:
                        st.warning(f"⚠️ Could not geocode: {', '.join(failed)}")
                    if geocoded:
                        st.session_state.geocoded_locations = geocoded
                        st.session_state.geocoded_names = raw_names

                # Display resolved locations from session state
                if "geocoded_locations" in st.session_state and st.session_state.geocoded_locations:
                    locations_resolved = st.session_state.geocoded_locations
                    raw_names = st.session_state.get("geocoded_names", [])
                    for loc in locations_resolved:
                        st.success(f"📍 {loc['display_name'].split(',')[0]} → {loc['lat']:.4f}, {loc['lon']:.4f}")
                elif text_input and "geocoded_locations" not in st.session_state:
                    # First run — show hint
                    st.info("💡 Press **Geocode locations** to resolve place names to coordinates.")

            # ----------------------------------------------------------------
            # Mode B: map picker
            # ----------------------------------------------------------------
            else:
                st.caption("Click anywhere on the map to place pins. Two or more pins define the simulation corridor.")
                pin_locations = _render_location_map_picker()

                if pin_locations:
                    locations_resolved = pin_locations
                    raw_names = [f"Pin {i+1}" for i in range(len(pin_locations))]
                    for i, loc in enumerate(pin_locations):
                        st.success(f"📍 Pin {i+1}: {loc['lat']:.4f}, {loc['lon']:.4f}")
                else:
                    st.info("👆 Click the map to place at least one pin, then paste the coordinates above.")

            # ----------------------------------------------------------------
            # Convert resolved locations → place / extended_bbox
            # ----------------------------------------------------------------
            if len(locations_resolved) == 0:
                # Nothing resolved yet — fall back to Edinburgh to avoid crash
                place = "Edinburgh, UK"
                extended_bbox = None
                region_name = "Custom (not yet resolved)"
                st.warning("⚠️ No locations resolved — defaulting to Edinburgh.")

            elif len(locations_resolved) == 1:
                # Single location: use as place name if we have a display name,
                # else fall back to a tight bbox
                loc = locations_resolved[0]
                display = loc.get("display_name", "")
                if display:
                    # Extract the primary name (first comma-separated token)
                    place = display.split(",")[0].strip() + ", " + display.split(",")[-1].strip()
                    extended_bbox = None
                    region_name = display.split(",")[0].strip()
                else:
                    # Coordinate-only pin — build a small bbox around it
                    extended_bbox = _locations_to_bbox([loc], padding=0.15)
                    place = None
                    region_name = f"{loc['lat']:.3f}, {loc['lon']:.3f}"
                st.info(f"🗺️ Single location: {region_name}")

            else:
                # Multiple locations: compute spanning bounding box
                extended_bbox = _locations_to_bbox(locations_resolved, padding=0.15)
                place = None
                region_name = " → ".join(raw_names) if raw_names else "Custom multi-location"
                west, south, east, north = extended_bbox
                approx_km = int(((east - west) ** 2 + (north - south) ** 2) ** 0.5 * 111)
                st.success(
                    f"📦 Bounding box covers {len(locations_resolved)} locations "
                    f"(~{approx_km} km diagonal)\n\n"
                    f"`{west:.4f}, {south:.4f} → {east:.4f}, {north:.4f}`"
                )

    else:
        place = "Edinburgh, UK"
        extended_bbox = None
        region_name = "Synthetic Network"

    return {
        'use_osm': use_osm,
        'place': place,
        'bbox': extended_bbox,
        'region_name': region_name,
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




def _render_weather_configuration():
    """
    Render weather configuration section OUTSIDE form.
    This ensures the weather dropdown shows immediately when checkbox is clicked.
    """
    st.markdown("### 🌤️ Weather System")
    
    enable_weather = st.checkbox(
        "Enable Weather System",
        value=False,
        key="weather_enabled_checkbox",
        help="Temperature, precipitation, wind affect EV range and mode choice"
    )
    
    # Initialize defaults
    weather_source = 'synthetic'
    weather_temp_adjustment = 0.0
    weather_precip_multiplier = 1.0
    weather_wind_multiplier = 1.0
    
    if enable_weather:
        # Weather source - OUTSIDE expander with key for persistence
        weather_source = st.selectbox(
            "Weather Source",
            options=['live', 'historical', 'synthetic'],
            index=2,  # Default to synthetic
            key="weather_source_select",
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
                key="weather_temp_adjust",
                help="Add/subtract from actual temperature. Negative = colder (winter stress test)"
            )
            
            weather_precip_multiplier = st.slider(
                "Precipitation Multiplier",
                min_value=0.0,
                max_value=3.0,
                value=1.0,
                step=0.1,
                key="weather_precip_mult",
                help="1.0 = normal, 2.0 = double rainfall, 0.0 = no rain"
            )
            
            weather_wind_multiplier = st.slider(
                "Wind Speed Multiplier",
                min_value=0.5,
                max_value=2.0,
                value=1.0,
                step=0.1,
                key="weather_wind_mult",
                help="1.5 = 50% stronger winds"
            )
        
        # Show impact preview (outside expander for visibility)
        if weather_temp_adjustment != 0 or weather_precip_multiplier != 1.0 or weather_wind_multiplier != 1.0:
            st.info("📊 Weather perturbations active - simulating extreme conditions")
    
    return {
        'enable_weather': enable_weather,
        'weather_source': weather_source,
        'weather_temp_adjustment': weather_temp_adjustment,
        'weather_precip_multiplier': weather_precip_multiplier,
        'weather_wind_multiplier': weather_wind_multiplier,
    }


def _render_advanced_features():
    """Render advanced features section."""
    st.markdown("### 🔬 Advanced Features")
    
    use_congestion = st.checkbox("Enable Congestion", value=False)
    
    # Infrastructure controlled by Advanced Parameters
    enable_infrastructure = True  # Always enabled
    num_chargers = 50  # Default - will be overridden by advanced params
    num_depots = 5
    grid_capacity_mw = 50.0
    
    # Check if advanced params are active
    use_advanced = st.session_state.get('use_advanced_params', False)
    if not use_advanced:
        st.info("💡 Enable 'Advanced Parameter Tuning' above to customize infrastructure settings")
    
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
        'enable_social': enable_social,
        'use_realistic': use_realistic,
        'decay_rate': decay_rate,
        'habit_weight': habit_weight,
        'enable_infrastructure': enable_infrastructure,
        'num_chargers': num_chargers,
        'num_depots': num_depots,
        'grid_capacity_mw': grid_capacity_mw,
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


def _render_combined_scenario_selector() -> Optional[Dict]:
    """
    Render combined scenario selection dropdown.
    
    Returns:
        Combined scenario data dict or None
    """
    scenarios_dir = Path(__file__).parent.parent / 'scenarios' / 'combined_configs'
    
    if not scenarios_dir.exists():
        st.error(f"Scenarios directory not found: {scenarios_dir}")
        return None
    
    # Find all YAML files except default_policies.yaml
    scenario_files = [
        f for f in scenarios_dir.glob('*.yaml') 
        if f.name != 'default_policies.yaml'
    ]
    
    if not scenario_files:
        st.warning("No combined scenarios found")
        return None
    
    # Create scenario options
    scenario_names = [f.stem.replace('_', ' ').title() for f in scenario_files]
    
    selected_scenario = st.selectbox(
        "Select Combined Scenario",
        options=scenario_names,
        help="Advanced policy scenarios with complex interactions"
    )
    
    if selected_scenario:
        # Find the corresponding file
        selected_file = None
        for f in scenario_files:
            if f.stem.replace('_', ' ').title() == selected_scenario:
                selected_file = f
                break
        
        if selected_file:
            try:
                import yaml
                with open(selected_file, 'r') as f:
                    documents = list(yaml.safe_load_all(f))
                
                # Get first document
                if not documents:
                    st.error("Scenario file is empty")
                    return None
                
                data = documents[0]
                
                # Validate
                if not isinstance(data, dict):
                    st.error("Invalid scenario file format")
                    return None
                
                # Display preview
                with st.expander("📝 Scenario Preview", expanded=False):
                    st.markdown(f"**Name:** {data.get('name', 'Unknown')}")
                    st.markdown(f"**Description:**")
                    st.markdown(data.get('description', 'No description'))
                    
                    rules = data.get('interaction_rules', [])
                    st.markdown(f"**Policy Rules:** {len(rules)}")
                    
                    constraints = data.get('constraints', [])
                    if constraints:
                        st.markdown(f"**Constraints:** {len(constraints)}")
                
                return data
                
            except yaml.YAMLError as e:
                st.error(f"YAML parsing error: {e}")
                return None
            except Exception as e:
                st.error(f"Failed to load scenario: {e}")
                return None
    
    return None


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

# =======================================================================
# NEW: Combined scenario parameters renderer (Phase 5.1)
# ======================================================================= 
def _render_combined_scenario_parameters(scenario_data):
    """
    NEW: Allow users to configure policy parameters before simulation.
    Shows contextual controls based on selected scenario.
    """
    
    st.markdown("#### ⚙️ Scenario Parameters")
    
    params = {}
    
    # Grid Configuration
    with st.expander("🔌 Grid & Infrastructure", expanded=True):
        params['grid_capacity_mw'] = st.slider(
            "Grid Capacity (MW)",
            min_value=10, max_value=200, value=100,
            help="Electrical grid capacity. Lower = more likely to trigger grid interventions"
        )
        
        params['charger_density'] = st.slider(
            "Charging Station Density",
            min_value=0.5, max_value=3.0, value=1.0, step=0.1,
            help="Multiplier for charging stations. 1.0 = default density"
        )
    
    # Policy Thresholds  
    with st.expander("📊 Policy Triggers", expanded=True):
        params['grid_intervention_threshold'] = st.slider(
            "Grid Intervention Threshold (%)",
            min_value=50, max_value=95, value=70,
            help="Grid utilization % that triggers capacity expansion"
        )
        
        params['ev_adoption_target'] = st.slider(
            "EV Adoption Target (%)",
            min_value=10, max_value=100, value=50,
            help="Target EV adoption for policy success metrics"
        )
        
        params['initial_ev_adoption'] = st.slider(
            "Initial EV Adoption (%)",
            min_value=0, max_value=30, value=5,
            help="Starting % of agents using electric vehicles"
        )
    
    # Agent Behavior
    with st.expander("🧠 Agent Preferences", expanded=False):
        params['eco_desire_mean'] = st.slider(
            "Eco Consciousness (mean)",
            min_value=0.0, max_value=1.0, value=0.5, step=0.05,
            help="Average environmental concern. Higher = more EV adoption"
        )
        
        params['cost_sensitivity_mean'] = st.slider(
            "Cost Sensitivity (mean)",
            min_value=0.0, max_value=1.0, value=0.5, step=0.05,
            help="How much agents care about costs. Higher = prefer cheaper options"
        )
    
    # Budget Constraints
    if 'constraints' in scenario_data:
        with st.expander("💰 Budget Constraints", expanded=False):
            default_budget = scenario_data.get('constraints', {}).get('budget', 1000000)
            
            params['budget_limit'] = st.number_input(
                "Policy Budget (£)",
                min_value=100000, max_value=10000000, 
                value=default_budget, step=100000,
                help="Total budget for infrastructure investments"
            )
    
    return params

def render_policy_trigger_analysis(results):
    """
    NEW: Explain why policies didn't trigger and suggest fixes.
    Add to combined_scenarios_tab.py
    """
    
    if results.policy_status.get('rules_triggered', 0) == 0:
        st.warning("⚠️ No Policy Actions Were Triggered")
        
        with st.expander("💡 Why didn't policies trigger?", expanded=True):
            sim_state = results.policy_status.get('simulation_state', {})
            
            # Diagnose specific issues
            issues = []
            suggestions = []
            
            # Check grid utilization
            grid_util = sim_state.get('grid_utilization', 0)
            if grid_util < 0.5:
                issues.append(f"Grid utilization very low ({grid_util*100:.1f}%)")
                suggestions.append("• Reduce grid capacity to 20-50 MW")
                suggestions.append("• Increase initial EV adoption to 20%+")
            
            # Check EV adoption
            ev_adoption = sim_state.get('ev_adoption', 0)
            if ev_adoption < 0.1:
                issues.append(f"EV adoption low ({ev_adoption*100:.1f}%)")
                suggestions.append("• Increase agent eco desire to 0.7-0.9")
                suggestions.append("• Lower EV costs in scenario config")
            
            # Check charging usage
            charger_util = sim_state.get('charger_utilization', 0)
            if charger_util < 0.1:
                issues.append(f"Chargers barely used ({charger_util*100:.1f}%)")
                suggestions.append("• Ensure agents are selecting EV modes")
                suggestions.append("• Check if charging infrastructure is accessible")
            
            # Display diagnosis
            st.markdown("**Likely Reasons:**")
            for issue in issues:
                st.markdown(f"- {issue}")
            
            st.markdown("**Suggestions to See Policy Actions:**")
            for suggestion in suggestions:
                st.markdown(suggestion)
            
            # Quick fix buttons
            st.markdown("**Quick Configurations:**")
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if st.button("🔥 High EV Demand"):
                    st.info("Set: Grid=30MW, EV Adoption=25%, Eco Desire=0.8")
            
            with col2:
                if st.button("⚡ Grid Stress"):
                    st.info("Set: Grid=20MW, Chargers=0.5x, EV Adoption=20%")
            
            with col3:
                if st.button("💰 Budget Constrained"):
                    st.info("Set: Budget=£500k, Grid=100MW, Aggressive expansion")

def render_scenario_presets():
    """
    NEW: Quick parameter configurations that guarantee policy triggers.
    Add to sidebar before scenario selection.
    """
    
    st.markdown("#### 🎯 Quick Configurations")
    
    preset = st.selectbox(
        "Load Preset",
        [
            "Default",
            "High EV Demand (Guaranteed Triggers)",
            "Grid Stress Test",
            "Budget Constrained",
            "Rapid Adoption Scenario",
            "Custom"
        ]
    )
    
    presets = {
        "High EV Demand (Guaranteed Triggers)": {
            'grid_capacity_mw': 30,
            'initial_ev_adoption': 25,
            'eco_desire_mean': 0.8,
            'charger_density': 1.5,
            'grid_intervention_threshold': 60
        },
        "Grid Stress Test": {
            'grid_capacity_mw': 20,
            'initial_ev_adoption': 20,
            'charger_density': 0.5,
            'grid_intervention_threshold': 50
        },
        "Budget Constrained": {
            'grid_capacity_mw': 100,
            'budget_limit': 500000,
            'initial_ev_adoption': 15,
            'charger_density': 0.8
        },
        # ... etc
    }
    
    if preset != "Default" and preset != "Custom":
        st.success(f"✅ Loaded: {preset}")
        return presets[preset]
    
    return None  # Use manual configuration