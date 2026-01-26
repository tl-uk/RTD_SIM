"""
simulation/infrastructure/pricing/__init__.py

Pricing subsystem exports.

Re-export pricing-related classes for easy access.

"""

from .dynamic_pricing_engine import DynamicPricingEngine

# Import it here for consistency
try:
    from .time_of_day_pricing import (
        TimeOfDayPricingManager,
        SmartChargingOptimizer,
    )
    TIME_OF_DAY_AVAILABLE = True
except ImportError:
    TIME_OF_DAY_AVAILABLE = False

__all__ = [
    'DynamicPricingEngine',
]

if TIME_OF_DAY_AVAILABLE:
    __all__.extend([
        'TimeOfDayPricingManager',
        'SmartChargingOptimizer',
    ])

