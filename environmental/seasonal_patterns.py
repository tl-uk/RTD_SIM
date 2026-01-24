"""
environmental/seasonal_patterns.py

Seasonal patterns for environmental factors.
Provides functions to model seasonal variations in weather and environmental conditions.

"""
# environmental/seasonal_patterns.py
def get_seasonal_multipliers(month, day_of_year):
    if month in [12, 1, 2]:  # Winter
        return {
            'tourism_demand': 0.6,
            'freight_demand': 1.2,  # Holiday surge
            'ev_range': 0.75,  # Cold weather
            'bike_adoption': 0.4  # Weather deterrent
        }
    # ... summer, spring, autumn