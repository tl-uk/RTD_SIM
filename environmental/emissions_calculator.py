"""
environmental/emissions_calculator.py

Lifecycle emissions calculator for transport modes.
Based on COPERT methodology (EU) and UK NAEI data.
"""

from typing import Dict, Tuple
import math


class LifecycleEmissions:
    """Calculate full lifecycle emissions for transport modes."""
    
    # Vehicle manufacturing emissions (kg CO2e)
    MANUFACTURING_EMISSIONS = {
        'car': 10000,           # ICE car
        'ev': 15000,            # EV (includes battery)
        'van_diesel': 15000,
        'van_electric': 22000,
        'truck_diesel': 50000,
        'truck_electric': 75000,
        'hgv_diesel': 120000,
        'hgv_electric': 180000,
        'hgv_hydrogen': 150000,
        'bike': 100,
        'ebike': 200,
        'cargo_bike': 300,
        'bus': 80000,
    }
    
    # Battery production emissions (kg CO2e per kWh)
    BATTERY_EMISSIONS_PER_KWH = 75.0
    
    # Battery capacities (kWh)
    BATTERY_CAPACITIES = {
        'ev': 60.0,
        'van_electric': 75.0,
        'truck_electric': 300.0,
        'hgv_electric': 500.0,
        'ebike': 0.5,
        'cargo_bike': 1.0,
    }
    
    # Vehicle lifetimes (km)
    VEHICLE_LIFETIMES = {
        'car': 250000,
        'ev': 250000,
        'van_diesel': 300000,
        'van_electric': 300000,
        'truck_diesel': 500000,
        'truck_electric': 500000,
        'hgv_diesel': 800000,
        'hgv_electric': 800000,
        'hgv_hydrogen': 800000,
        'bike': 20000,
        'ebike': 20000,
        'cargo_bike': 30000,
        'bus': 600000,
    }
    
    # Fuel/energy emissions
    DIESEL_EMISSIONS_PER_L = 2.68      # kg CO2e per liter
    DIESEL_PRODUCTION_PER_L = 0.5      # kg CO2e per liter (upstream)
    
    # UK grid electricity (2024 estimate - decreasing)
    GRID_EMISSIONS_PER_KWH = 0.233     # kg CO2e per kWh
    
    # Hydrogen production (grey hydrogen for now)
    HYDROGEN_EMISSIONS_PER_KG = 10.0   # kg CO2e per kg H2
    
    # Fuel efficiency (liters per 100km for diesel, kWh per 100km for electric)
    FUEL_EFFICIENCY = {
        'car': 7.0,              # L/100km
        'van_diesel': 10.0,
        'truck_diesel': 25.0,
        'hgv_diesel': 35.0,
        'ev': 18.0,              # kWh/100km
        'van_electric': 25.0,
        'truck_electric': 80.0,
        'hgv_electric': 120.0,
        'hgv_hydrogen': 8.0,     # kg H2/100km
        'bus': 30.0,             # L/100km
        'ebike': 1.0,            # kWh/100km
        'cargo_bike': 1.5,
    }
    
    # Air quality emissions (grams per km)
    # Format: (PM2.5, NOx, CO)
    AIR_QUALITY_EMISSIONS = {
        'car': (0.005, 0.06, 0.5),
        'van_diesel': (0.01, 0.15, 0.8),
        'truck_diesel': (0.03, 0.5, 2.0),
        'hgv_diesel': (0.05, 0.8, 3.0),
        'bus': (0.02, 0.4, 1.5),
        # Electric vehicles (upstream only, from power generation)
        'ev': (0.001, 0.005, 0.01),
        'van_electric': (0.001, 0.005, 0.01),
        'truck_electric': (0.002, 0.01, 0.02),
        'hgv_electric': (0.003, 0.015, 0.03),
        # Zero emissions
        'walk': (0.0, 0.0, 0.0),
        'bike': (0.0, 0.0, 0.0),
        'ebike': (0.0, 0.0, 0.0),
        'cargo_bike': (0.0, 0.0, 0.0),
    }
    
    def __init__(self, grid_carbon_intensity: float = 0.233):
        """
        Initialize emissions calculator.
        
        Args:
            grid_carbon_intensity: kg CO2e per kWh (default: UK 2024)
        """
        self.grid_intensity = grid_carbon_intensity
    
    def calculate_trip_emissions(
        self,
        mode: str,
        distance_km: float,
        vehicle_age_km: float = 50000
    ) -> Dict[str, float]:
        """
        Calculate full lifecycle emissions for a trip.
        
        Args:
            mode: Transport mode
            distance_km: Trip distance in km
            vehicle_age_km: How much the vehicle has been used
        
        Returns:
            Dict with emissions breakdown
        """
        # Manufacturing emissions (amortized)
        manufacturing = self._calculate_manufacturing_emissions(
            mode, distance_km, vehicle_age_km
        )
        
        # Fuel/energy emissions
        energy = self._calculate_energy_emissions(mode, distance_km)
        
        # Air quality impacts
        pm25, nox, co = self._calculate_air_quality_emissions(mode, distance_km)
        
        # Total CO2e
        total_co2e = manufacturing + energy['total']
        
        return {
            'co2e_kg': total_co2e,
            'manufacturing_co2e_kg': manufacturing,
            'energy_co2e_kg': energy['combustion'],
            'upstream_co2e_kg': energy['upstream'],
            'pm25_g': pm25,
            'nox_g': nox,
            'co_g': co,
        }
    
    def _calculate_manufacturing_emissions(
        self,
        mode: str,
        distance_km: float,
        vehicle_age_km: float
    ) -> float:
        """Calculate amortized manufacturing emissions."""
        if mode in ['walk', 'bus', 'tram', 'local_train', 'intercity_train']:
            # Negligible per-trip manufacturing for active travel and public transport
            return 0.0
        
        base_manufacturing = self.MANUFACTURING_EMISSIONS.get(mode, 10000)
        
        # Add battery manufacturing for EVs
        if mode in self.BATTERY_CAPACITIES:
            battery_kwh = self.BATTERY_CAPACITIES[mode]
            battery_emissions = battery_kwh * self.BATTERY_EMISSIONS_PER_KWH
            base_manufacturing += battery_emissions
        
        # Amortize over vehicle lifetime
        lifetime_km = self.VEHICLE_LIFETIMES.get(mode, 250000)
        emissions_per_km = base_manufacturing / lifetime_km
        
        return emissions_per_km * distance_km
    
    def _calculate_energy_emissions(
        self,
        mode: str,
        distance_km: float
    ) -> Dict[str, float]:
        """Calculate fuel/energy emissions."""
        if mode in ['walk', 'bike']:
            return {'combustion': 0.0, 'upstream': 0.0, 'total': 0.0}
        
        efficiency = self.FUEL_EFFICIENCY.get(mode, 7.0)
        
        # Diesel modes
        if mode in ['car', 'van_diesel', 'truck_diesel', 'hgv_diesel', 'bus']:
            liters_used = (distance_km / 100.0) * efficiency
            combustion = liters_used * self.DIESEL_EMISSIONS_PER_L
            upstream = liters_used * self.DIESEL_PRODUCTION_PER_L
            return {
                'combustion': combustion,
                'upstream': upstream,
                'total': combustion + upstream
            }
        
        # Electric modes
        elif mode in ['ev', 'van_electric', 'truck_electric', 'hgv_electric', 
                      'ebike', 'cargo_bike']:
            kwh_used = (distance_km / 100.0) * efficiency
            emissions = kwh_used * self.grid_intensity
            return {
                'combustion': 0.0,
                'upstream': emissions,  # Grid emissions counted as upstream
                'total': emissions
            }
        
        # Hydrogen modes
        elif mode in ['hgv_hydrogen']:
            kg_h2_used = (distance_km / 100.0) * efficiency
            emissions = kg_h2_used * self.HYDROGEN_EMISSIONS_PER_KG
            return {
                'combustion': 0.0,
                'upstream': emissions,
                'total': emissions
            }
        
        # Public transport (estimated per passenger-km)
        elif mode in ['bus', 'tram']:
            # Assume 50% occupancy for buses
            emissions_per_km = 0.05  # kg CO2e per passenger-km
            return {
                'combustion': emissions_per_km * distance_km,
                'upstream': 0.0,
                'total': emissions_per_km * distance_km
            }
        
        elif mode in ['local_train', 'intercity_train']:
            # Trains vary by electrification
            emissions_per_km = 0.035  # kg CO2e per passenger-km (UK average)
            return {
                'combustion': emissions_per_km * distance_km,
                'upstream': 0.0,
                'total': emissions_per_km * distance_km
            }
        
        else:
            # Unknown mode - use car as proxy
            return self._calculate_energy_emissions('car', distance_km)
    
    def _calculate_air_quality_emissions(
        self,
        mode: str,
        distance_km: float
    ) -> Tuple[float, float, float]:
        """
        Calculate air quality pollutants (PM2.5, NOx, CO).
        
        Returns:
            Tuple of (PM2.5_g, NOx_g, CO_g)
        """
        if mode not in self.AIR_QUALITY_EMISSIONS:
            # Unknown mode - assume zero
            return (0.0, 0.0, 0.0)
        
        pm25_per_km, nox_per_km, co_per_km = self.AIR_QUALITY_EMISSIONS[mode]
        
        return (
            pm25_per_km * distance_km,
            nox_per_km * distance_km,
            co_per_km * distance_km
        )
    
    def compare_modes(
        self,
        distance_km: float,
        modes: list = None
    ) -> Dict[str, Dict[str, float]]:
        """
        Compare lifecycle emissions across modes for a given trip.
        
        Args:
            distance_km: Trip distance
            modes: List of modes to compare (default: common modes)
        
        Returns:
            Dict mapping mode to emissions breakdown
        """
        if modes is None:
            modes = ['walk', 'bike', 'ebike', 'bus', 'car', 'ev', 
                    'van_diesel', 'van_electric']
        
        comparison = {}
        
        for mode in modes:
            comparison[mode] = self.calculate_trip_emissions(mode, distance_km)
        
        return comparison
    
    def get_mode_carbon_intensity(self, mode: str) -> float:
        """
        Get average carbon intensity (g CO2e per km).
        
        Useful for quick comparisons.
        """
        # Calculate for a representative 10km trip
        emissions = self.calculate_trip_emissions(mode, 10.0)
        return (emissions['co2e_kg'] * 1000) / 10.0  # g per km


def calculate_urban_air_quality_impact(
    emissions_by_mode: Dict[str, Dict[str, float]],
    population_density: float = 3000.0  # people per km²
) -> Dict[str, float]:
    """
    Estimate health impact of air quality emissions.
    
    Uses simplified WHO health impact factors.
    
    Args:
        emissions_by_mode: Dict of mode → emissions dict
        population_density: People per km² in area
    
    Returns:
        Dict with health metrics
    """
    total_pm25 = sum(e.get('pm25_g', 0) for e in emissions_by_mode.values())
    total_nox = sum(e.get('nox_g', 0) for e in emissions_by_mode.values())
    
    # Simplified health impact (years of life lost per ton of pollutant)
    # WHO estimates: PM2.5 causes ~100 YLL per ton in urban areas
    pm25_tons = total_pm25 / 1_000_000
    nox_tons = total_nox / 1_000_000
    
    yll_pm25 = pm25_tons * 100.0
    yll_nox = nox_tons * 20.0
    
    # Economic cost (£ per ton, UK DEFRA values)
    cost_pm25 = pm25_tons * 70000  # £70k per ton
    cost_nox = nox_tons * 15000    # £15k per ton
    
    return {
        'total_pm25_g': total_pm25,
        'total_nox_g': total_nox,
        'years_life_lost': yll_pm25 + yll_nox,
        'health_cost_gbp': cost_pm25 + cost_nox,
        'affected_population': population_density * 10,  # 10km² area assumption
    }


def get_net_zero_progress(
    current_emissions_kg_co2e: float,
    baseline_emissions_kg_co2e: float,
    target_year: int = 2045,
    current_year: int = 2024
) -> Dict[str, float]:
    """
    Calculate progress toward net zero target (Scotland: 2045).
    
    Args:
        current_emissions_kg_co2e: Current emissions
        baseline_emissions_kg_co2e: Baseline year emissions
        target_year: Net zero target year
        current_year: Current year
    
    Returns:
        Dict with progress metrics
    """
    years_remaining = target_year - current_year
    total_years = target_year - 2020  # Baseline year
    elapsed_years = current_year - 2020
    
    # Linear reduction target
    target_reduction_pct = (elapsed_years / total_years) * 100
    
    # Actual reduction
    actual_reduction = baseline_emissions_kg_co2e - current_emissions_kg_co2e
    actual_reduction_pct = (actual_reduction / baseline_emissions_kg_co2e) * 100
    
    # Required annual reduction rate
    required_annual_rate = (current_emissions_kg_co2e / years_remaining) if years_remaining > 0 else 0
    
    return {
        'current_emissions_kg': current_emissions_kg_co2e,
        'baseline_emissions_kg': baseline_emissions_kg_co2e,
        'reduction_kg': actual_reduction,
        'reduction_pct': actual_reduction_pct,
        'target_reduction_pct': target_reduction_pct,
        'on_track': actual_reduction_pct >= target_reduction_pct,
        'years_remaining': years_remaining,
        'required_annual_reduction_kg': required_annual_rate,
    }