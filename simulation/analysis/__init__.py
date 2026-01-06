"""
simulation/analysis/__init__.py

Analysis module for scenario comparison and evaluation.
"""

from simulation.analysis.scenario_comparison import (
    list_available_scenarios,
    get_scenario_info,
    compare_scenarios,
    format_comparison_report
)

__all__ = [
    'list_available_scenarios',
    'get_scenario_info',
    'compare_scenarios',
    'format_comparison_report'
]