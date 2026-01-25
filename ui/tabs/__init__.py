"""
ui/tabs/__init__.py

Export all tab rendering functions for easy import in streamlit_app.py

"""

from .map_tab import render_map_tab
from .mode_adoption_tab import render_mode_adoption_tab
from .impact_tab import render_impact_tab
from .network_tab import render_network_tab
from .infrastructure_tab import render_infrastructure_tab
from .scenario_report_tab import render_scenario_report_tab
from .combined_scenarios_tab import render_combined_scenarios_tab
from .environmental_tab import render_environmental_tab  # FIX: Added this!

__all__ = [
    'render_map_tab',
    'render_mode_adoption_tab',
    'render_impact_tab',
    'render_network_tab',
    'render_infrastructure_tab',
    'render_scenario_report_tab',
    'render_combined_scenarios_tab',
    'render_environmental_tab',  
]