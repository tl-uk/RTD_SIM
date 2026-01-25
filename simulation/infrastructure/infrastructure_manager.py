"""
simulation/infrastructure_manager.py

Central infrastructure registry for Phase 4.5.
Manages charging stations, depots, grid capacity, and availability.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Set
from collections import defaultdict
import logging
import math

from simulation.infrastructure.time_of_day_pricing import (
    TimeOfDayPricingManager,
    SmartChargingOptimizer
)

logger = logging.getLogger(__name__)


@dataclass
class ChargingStation:
    """Individual charging station."""
    station_id: str
    location: Tuple[float, float]  # (lon, lat)
    charger_type: str  # 'level2', 'dcfast', 'home', 'depot'
    num_ports: int
    power_kw: float
    cost_per_kwh: float
    
    # Real-time state
    currently_occupied: int = 0
    queue: List[str] = field(default_factory=list)  # agent_ids waiting
    
    # Operational
    operational: bool = True
    owner_type: str = 'public'  # 'public', 'private', 'commercial'
    
    def is_available(self) -> bool:
        """Check if station has free ports."""
        return self.operational and self.currently_occupied < self.num_ports
    
    def get_queue_wait_time_min(self, avg_charge_time_min: float = 30.0) -> float:
        """Estimate wait time based on queue length."""
        if self.is_available():
            return 0.0
        
        # Queue position × average charge time / number of ports
        return (len(self.queue) * avg_charge_time_min) / max(1, self.num_ports)
    
    def occupancy_rate(self) -> float:
        """Get current occupancy (0-1)."""
        return self.currently_occupied / max(1, self.num_ports)


@dataclass
class Depot:
    """Freight/commercial depot with charging facilities."""
    depot_id: str
    location: Tuple[float, float]
    depot_type: str  # 'delivery', 'freight', 'bus', 'taxi'
    
    # Charging infrastructure
    num_chargers: int = 0
    charger_power_kw: float = 50.0
    
    # Operational hours
    operates_24_7: bool = False
    operating_hours: Optional[Tuple[int, int]] = None  # (start_hour, end_hour)


@dataclass
class GridCapacity:
    """Regional grid capacity tracking."""
    region_id: str
    capacity_mw: float
    current_load_mw: float = 0.0
    
    def utilization(self) -> float:
        """Get grid utilization (0-1)."""
        return self.current_load_mw / max(0.001, self.capacity_mw)
    
    def is_overloaded(self, threshold: float = 0.95) -> bool:
        """Check if grid is near capacity."""
        return self.utilization() >= threshold


class InfrastructureManager:
    """
    Central manager for transport infrastructure.
    
    Responsibilities:
    - Track charging station locations and availability
    - Manage depot infrastructure
    - Monitor grid capacity and load
    - Provide infrastructure queries for BDI planner
    """
    
    def __init__(self, grid_capacity_mw: float = 1000.0, enable_time_of_day_pricing: bool = False):
        """
        Initialize infrastructure manager.
        
        Args:
            grid_capacity_mw: Total grid capacity in megawatts
        """
        # Infrastructure registries
        self.charging_stations: Dict[str, ChargingStation] = {}
        self.depots: Dict[str, Depot] = {}
        self.grid_regions: Dict[str, GridCapacity] = {}
        
        # Initialize default grid region
        self.grid_regions['default'] = GridCapacity(
            region_id='default',
            capacity_mw=grid_capacity_mw
        )
        
        # Time-of-day pricing
        self.enable_tod_pricing = enable_time_of_day_pricing
        
        if enable_time_of_day_pricing:
            self.tod_pricing = TimeOfDayPricingManager(
                base_price_per_kwh=0.16,  # UK average
                enable_dynamic_pricing=True
            )
            self.smart_charging = SmartChargingOptimizer(
                pricing_manager=self.tod_pricing,
                max_concurrent_sessions=50
            )
            logger.info("Time-of-day pricing and smart charging enabled")
        else:
            self.tod_pricing = None
            self.smart_charging = None
        
        # Track current simulation hour (0-23)
        self.current_hour = 8  # Start at 8 AM by default
        
        # Usage tracking
        self.agent_charging_state: Dict[str, Dict] = {}  # agent_id -> state
        self.historical_utilization: List[float] = []
        
        logger.info(f"InfrastructureManager initialized (grid: {grid_capacity_mw} MW)")
    
        # NEW: EV range tracking
        self._base_ev_ranges = {
            'ev': 350.0,
            'van_electric': 200.0,
            'truck_electric': 250.0,
            'hgv_electric': 300.0,
        }
        self._adjusted_ev_ranges = self._base_ev_ranges.copy()

    # =======================================================================
    # EV Range Management
    # ======================================================================
    def get_base_ev_range(self, mode: str) -> float:
        """Get rated range at optimal temperature."""
        return self._base_ev_ranges.get(mode, 350.0)
    
    def set_adjusted_ev_range(self, mode: str, range_km: float):
        """Set weather-adjusted range."""
        self._adjusted_ev_ranges[mode] = range_km
    
    def get_adjusted_ev_range(self, mode: str) -> float:
        """Get current adjusted range."""
        return self._adjusted_ev_ranges.get(mode, self.get_base_ev_range(mode))

    # ========================================================================
    # Charging Station Management
    # ========================================================================
    
    def add_charging_station(
        self,
        station_id: str,
        location: Tuple[float, float],
        charger_type: str = 'level2',
        num_ports: int = 2,
        power_kw: float = 7.0,
        cost_per_kwh: float = 0.15,
        owner_type: str = 'public'
    ) -> None:
        """Add a charging station to the registry."""
        station = ChargingStation(
            station_id=station_id,
            location=location,
            charger_type=charger_type,
            num_ports=num_ports,
            power_kw=power_kw,
            cost_per_kwh=cost_per_kwh,
            owner_type=owner_type
        )
        
        self.charging_stations[station_id] = station
        logger.debug(f"Added charging station: {station_id} at {location}")
    
    def find_nearest_charger(
        self,
        location: Tuple[float, float],
        charger_type: str = 'any',
        max_distance_km: float = 5.0,
        require_available: bool = False
    ) -> Optional[Tuple[str, float]]:
        """
        Find nearest charging station to location.
        
        Args:
            location: Search origin (lon, lat)
            charger_type: Required type ('any', 'level2', 'dcfast', 'home')
            max_distance_km: Maximum search radius
            require_available: Only return if ports available
        
        Returns:
            Tuple of (station_id, distance_km) or None
        """
        nearest = None
        min_distance = float('inf')
        
        for station_id, station in self.charging_stations.items():
            # Filter by type
            if charger_type != 'any' and station.charger_type != charger_type:
                continue
            
            # Filter by availability
            if require_available and not station.is_available():
                continue
            
            # Calculate distance
            distance = self._haversine_km(location, station.location)
            
            if distance < min_distance and distance <= max_distance_km:
                min_distance = distance
                nearest = (station_id, distance)
        
        return nearest
    
    def get_charger_availability(self, station_id: str) -> Dict:
        """Get detailed availability info for a station."""
        if station_id not in self.charging_stations:
            return {'exists': False}
        
        station = self.charging_stations[station_id]
        
        return {
            'exists': True,
            'available': station.is_available(),
            'free_ports': max(0, station.num_ports - station.currently_occupied),
            'total_ports': station.num_ports,
            'queue_length': len(station.queue),
            'estimated_wait_min': station.get_queue_wait_time_min(),
            'occupancy_rate': station.occupancy_rate(),
            'cost_per_kwh': station.cost_per_kwh,
            'charger_type': station.charger_type,
        }
    
    def reserve_charger(
        self,
        agent_id: str,
        station_id: str,
        duration_min: float
    ) -> bool:
        """
        Reserve a charger for an agent.
        
        Args:
            agent_id: Agent identifier
            station_id: Charging station ID
            duration_min: Expected charging duration
        
        Returns:
            True if reserved successfully
        """
        if station_id not in self.charging_stations:
            logger.warning(f"Station {station_id} not found")
            return False
        
        station = self.charging_stations[station_id]
        
        if station.is_available():
            # Occupy a port
            station.currently_occupied += 1
            
            # Track agent state
            self.agent_charging_state[agent_id] = {
                'station_id': station_id,
                'start_time': None,  # Set when charging starts
                'duration_min': duration_min,
                'status': 'reserved'
            }
            
            logger.debug(f"Agent {agent_id} reserved {station_id}")
            return True
        else:
            # Add to queue
            if agent_id not in station.queue:
                station.queue.append(agent_id)
                logger.debug(f"Agent {agent_id} queued at {station_id} (pos {len(station.queue)})")
            return False
    
    def release_charger(self, agent_id: str) -> None:
        """Release a charger when agent finishes charging."""
        if agent_id not in self.agent_charging_state:
            return
        
        state = self.agent_charging_state[agent_id]
        station_id = state['station_id']
        
        if station_id in self.charging_stations:
            station = self.charging_stations[station_id]
            station.currently_occupied = max(0, station.currently_occupied - 1)
            
            # Process queue
            if station.queue and station.is_available():
                next_agent = station.queue.pop(0)
                logger.debug(f"Agent {next_agent} moved from queue to charging at {station_id}")
        
        del self.agent_charging_state[agent_id]
        logger.debug(f"Agent {agent_id} released charger at {station_id}")

    # ========================================================================
    # Time-of-Day Pricing & Smart Charging
    # ========================================================================

    def update_time(self, step: int, steps_per_hour: int = 6) -> None:
        """
        Update current simulation time.
        
        Args:
            step: Current simulation step
            steps_per_hour: How many steps equal one hour (default: 6 = 10 min/step)
        """
        if self.enable_tod_pricing:
            self.current_hour = (8 + (step // steps_per_hour)) % 24  # Start at 8 AM
            logger.debug(f"Simulation time: {self.current_hour:02d}:00")


    def get_current_charging_cost(self, station_id: str) -> float:
        """
        Get current charging cost per kWh at station.
        
        Args:
            station_id: Charging station identifier
        
        Returns:
            Cost in GBP per kWh
        """
        if not self.enable_tod_pricing or station_id not in self.charging_stations:
            return 0.15  # Default flat rate
        
        station = self.charging_stations[station_id]
        base_cost = station.get('cost_per_kwh', 0.15)
        
        # Apply time-of-day multiplier
        current_price = self.tod_pricing.get_price_at_time(self.current_hour)
        
        return current_price


    def schedule_smart_charging(
        self,
        agent_id: str,
        vehicle_mode: str,
        energy_needed_kwh: float,
        urgency: str = 'normal'
    ) -> Dict:
        """
        Schedule smart charging session for agent.
        
        Args:
            agent_id: Agent identifier
            vehicle_mode: Vehicle type
            energy_needed_kwh: Energy to charge
            urgency: 'immediate', 'normal', or 'flexible'
        
        Returns:
            Dict with scheduled_start, estimated_cost
        """
        if not self.enable_tod_pricing:
            # Fallback to immediate charging
            cost = energy_needed_kwh * 0.15
            return {
                'scheduled_start': self.current_hour,
                'estimated_cost': cost,
                'smart_charging_used': False
            }
        
        # Determine charging rate based on vehicle type
        charging_rate_map = {
            'ev': 7.0,              # 7 kW home charger
            'van_electric': 11.0,   # 11 kW depot charger
            'cargo_bike': 0.5,      # 500W charger
            'truck_electric': 50.0, # 50 kW depot charger
            'hgv_electric': 150.0,  # 150 kW megacharger
            'hgv_hydrogen': 0.0,    # N/A for hydrogen
        }
        
        charging_rate_kw = charging_rate_map.get(vehicle_mode, 7.0)
        
        # Schedule charging
        session = self.smart_charging.schedule_charging(
            agent_id=agent_id,
            vehicle_mode=vehicle_mode,
            energy_needed_kwh=energy_needed_kwh,
            charging_rate_kw=charging_rate_kw,
            urgency=urgency,
            earliest_hour=self.current_hour,
            latest_hour=(self.current_hour + 16) % 24
        )
        
        return {
            'scheduled_start': session.scheduled_start,
            'estimated_cost': session.estimated_cost,
            'smart_charging_used': True,
            'completion_hour': session.latest_completion,
        }


    def get_tod_pricing_metrics(self) -> Dict:
        """Get time-of-day pricing metrics and status."""
        if not self.enable_tod_pricing:
            return {'enabled': False}
        
        current_tier = self.tod_pricing.get_current_tier(self.current_hour)
        summary = self.tod_pricing.get_daily_summary()
        
        # Get smart charging metrics
        charging_metrics = self.smart_charging.get_cost_savings_report()
        load_profile = self.smart_charging.get_load_profile(hours_ahead=24)
        
        return {
            'enabled': True,
            'current_hour': self.current_hour,
            'current_tier': current_tier.name,
            'current_price': current_tier.price_per_kwh,
            'daily_summary': summary,
            'smart_charging': charging_metrics,
            'load_profile': load_profile,
        }


    def get_charging_recommendation(
        self,
        agent_id: str,
        energy_needed_kwh: float,
        urgency: str = 'normal'
    ) -> Dict:
        """
        Get charging recommendation with cost comparison.
        
        Args:
            agent_id: Agent identifier
            energy_needed_kwh: Energy needed
            urgency: Urgency level
        
        Returns:
            Dict with immediate_cost, optimal_cost, recommended_start, savings
        """
        if not self.enable_tod_pricing:
            cost = energy_needed_kwh * 0.15
            return {
                'immediate_cost': cost,
                'optimal_cost': cost,
                'recommended_start': self.current_hour,
                'savings': 0.0,
                'savings_percentage': 0.0,
            }
        
        # Cost if charging immediately
        immediate_cost = self.tod_pricing.calculate_charging_cost(
            energy_kwh=energy_needed_kwh,
            start_hour=self.current_hour,
            duration_hours=energy_needed_kwh / 7.0  # Assume 7kW charger
        )
        
        # Cost if charging optimally
        optimal_start, optimal_cost = self.tod_pricing.find_optimal_charging_window(
            energy_kwh=energy_needed_kwh,
            charging_rate_kw=7.0,
            earliest_hour=self.current_hour,
            latest_hour=(self.current_hour + 16) % 24,
            required_completion_hour=(self.current_hour + 12) % 24
        )
        
        savings = immediate_cost - optimal_cost
        savings_pct = (savings / immediate_cost * 100) if immediate_cost > 0 else 0
        
        return {
            'immediate_cost': immediate_cost,
            'optimal_cost': optimal_cost,
            'recommended_start': optimal_start,
            'savings': savings,
            'savings_percentage': savings_pct,
        }
    
    # =======================================================================
    # Chrarging Time Calculation
    # =======================================================================
    def calculate_freight_charging_time(
        vehicle_mode: str,
        cargo_weight_kg: float,
        distance_traveled_km: float
    ) -> float:
        """Heavier loads = faster battery drain = longer charging."""
        base_charging_min = {
            'van_electric': 60,
            'truck_electric': 120,
            'hgv_electric': 180,
        }
        
        base_time = base_charging_min.get(vehicle_mode, 60)
        
        # Weight multiplier
        weight_multiplier = 1 + (cargo_weight_kg / 10000)  # +10% per tonne
        
        # Distance multiplier
        distance_multiplier = 1 + (distance_traveled_km / 100)  # +10% per 100km
        
        return base_time * weight_multiplier * distance_multiplier
    
    # =======================================================================
    # Vehicle Charging Management
    # =======================================================================
    def charge_vehicle(
        self,
        agent_id: str,
        station_id: str,
        vehicle_mode: str,
        energy_kwh: float,
        use_smart_charging: bool = True
    ) -> Dict:
        """
        Charge vehicle with optional smart charging.
        
        Args:
            agent_id: Agent identifier
            station_id: Charging station ID
            vehicle_mode: Vehicle type
            energy_kwh: Energy to charge
            use_smart_charging: Use smart charging optimization
        
        Returns:
            Dict with cost, duration, scheduled_start
        """
        if station_id not in self.charging_stations:
            return {'success': False, 'reason': 'station_not_found'}
        
        station = self.charging_stations[station_id]
        
        # Check availability
        if not station.is_available():
            return {'success': False, 'reason': 'no_ports_available'}
        
        # Get charging cost (time-of-day aware)
        cost_per_kwh = self.get_current_charging_cost(station_id)
        
        # Smart charging optimization
        if use_smart_charging and self.enable_tod_pricing:
            schedule = self.schedule_smart_charging(
                agent_id=agent_id,
                vehicle_mode=vehicle_mode,
                energy_needed_kwh=energy_kwh,
                urgency='normal'
            )
            
            total_cost = schedule['estimated_cost']
            scheduled_start = schedule['scheduled_start']
        else:
            # Immediate charging
            total_cost = energy_kwh * cost_per_kwh
            scheduled_start = self.current_hour
        
        # Occupy port
        station.occupy_port()
        
        # Track charging session
        self.agent_charging_state[agent_id] = {
            'station_id': station_id,
            'start_hour': scheduled_start,
            'energy_kwh': energy_kwh,
            'cost': total_cost,
        }
        
        # Update grid load
        charging_power = energy_kwh / 2.0  # Assume 2-hour charging
        grid_region = 'default'
        self.add_grid_load(grid_region, charging_power)
        
        return {
            'success': True,
            'cost': total_cost,
            'cost_per_kwh': cost_per_kwh,
            'scheduled_start': scheduled_start,
            'smart_charging_used': use_smart_charging and self.enable_tod_pricing,
        }
    
    # ========================================================================
    # Grid Management
    # ========================================================================
    
    def update_grid_load(self, step: int) -> None:
        """
        Update grid load based on active charging.
        
        Call this each simulation step.
        
        FIX: Count ALL agents in agent_charging_state, not just status='charging'
        """
        grid = self.grid_regions['default']
        
        # Calculate total load from all active charging
        total_load_kw = 0.0
        
        # FIX: Just check if agent is in the dict, don't filter by status
        # Both 'reserved' and 'charging' should contribute to grid load
        for agent_id, state in self.agent_charging_state.items():
            station_id = state.get('station_id')
            if station_id in self.charging_stations:
                station = self.charging_stations[station_id]
                # Add the station's power to load
                total_load_kw += station.power_kw
        
        grid.current_load_mw = total_load_kw / 1000.0
        
        # Track history
        self.historical_utilization.append(grid.utilization())
        
        # Log every 20 steps for monitoring
        if step % 20 == 0 and total_load_kw > 0:
            logger.info(f"Step {step}: Grid load {grid.current_load_mw:.2f} MW "
                    f"({grid.utilization():.1%}), "
                    f"{len(self.agent_charging_state)} agents charging")
        
        if grid.is_overloaded():
            logger.warning(f"Step {step}: Grid overloaded! ({grid.utilization():.1%})")

    
    def get_grid_stress_factor(self) -> float:
        """
        Get grid stress multiplier for BDI cost calculation.
        
        Returns:
            1.0 = normal, >1.0 = stressed (increases charging cost/time)
        """
        grid = self.grid_regions['default']
        utilization = grid.utilization()
        
        if utilization < 0.7:
            return 1.0  # Normal
        elif utilization < 0.85:
            return 1.2  # Slightly stressed
        elif utilization < 0.95:
            return 1.5  # Stressed
        else:
            return 2.0  # Critical
    
    # ========================================================================
    # Depot Management
    # ========================================================================
    
    def add_depot(
        self,
        depot_id: str,
        location: Tuple[float, float],
        depot_type: str,
        num_chargers: int = 10,
        charger_power_kw: float = 50.0
    ) -> None:
        """Add a commercial/freight depot."""
        depot = Depot(
            depot_id=depot_id,
            location=location,
            depot_type=depot_type,
            num_chargers=num_chargers,
            charger_power_kw=charger_power_kw
        )
        
        self.depots[depot_id] = depot
        logger.info(f"Added depot: {depot_id} ({depot_type})")
    
    def find_nearest_depot(
        self,
        location: Tuple[float, float],
        depot_type: str = 'any'
    ) -> Optional[Tuple[str, float]]:
        """Find nearest depot to location."""
        nearest = None
        min_distance = float('inf')
        
        for depot_id, depot in self.depots.items():
            if depot_type != 'any' and depot.depot_type != depot_type:
                continue
            
            distance = self._haversine_km(location, depot.location)
            
            if distance < min_distance:
                min_distance = distance
                nearest = (depot_id, distance)
        
        return nearest
    
    # ========================================================================
    # Infrastructure Expansion & Optimization
    # ========================================================================
    def add_chargers_by_demand(
        self,
        num_chargers: int,
        charger_type: str = 'level2',
        strategy: str = 'demand_heatmap'
    ) -> List[str]:
        """
        Add chargers using simple heuristics.
        
        Strategies:
        - demand_heatmap: Place where agent density is highest
        - grid_capacity: Place where grid has spare capacity
        - coverage_gaps: Fill areas >5km from nearest charger
        - equitable: Spread evenly across region
        """
        new_station_ids = []
        
        if strategy == 'demand_heatmap':
            # Use agent destinations to build demand heatmap
            hotspots = self._calculate_demand_hotspots()
            for i, (lon, lat) in enumerate(hotspots[:num_chargers]):
                station_id = f"demand_{i:03d}"
                self.add_charging_station(
                    station_id=station_id,
                    location=(lon, lat),
                    charger_type=charger_type,
                    num_ports=4,
                    power_kw=50.0 if charger_type == 'dcfast' else 7.0
                )
                new_station_ids.append(station_id)
        
        elif strategy == 'coverage_gaps':
            # Find locations >5km from any charger
            gaps = self._find_coverage_gaps(min_distance_km=5.0)
            for i, (lon, lat) in enumerate(gaps[:num_chargers]):
                station_id = f"coverage_{i:03d}"
                self.add_charging_station(
                    station_id=station_id,
                    location=(lon, lat),
                    charger_type=charger_type,
                    num_ports=2,
                    power_kw=7.0
                )
                new_station_ids.append(station_id)
        
        elif strategy == 'grid_capacity':
            # Place where grid has spare capacity
            # (Simplified: random with grid utilization check)
            for i in range(num_chargers):
                location = self._sample_location_with_grid_capacity()
                station_id = f"grid_{i:03d}"
                self.add_charging_station(
                    station_id=station_id,
                    location=location,
                    charger_type=charger_type,
                    num_ports=6,
                    power_kw=50.0
                )
                new_station_ids.append(station_id)
        
        logger.info(f"Added {len(new_station_ids)} chargers using {strategy}")
        return new_station_ids
    
    def _calculate_demand_hotspots(self) -> List[Tuple[float, float]]:
        """Find top demand locations (simplified: agent destinations)."""
        # In real implementation, use agent destination history
        # For now, return random high-demand locations
        import random
        hotspots = []
        for _ in range(50):
            lon = random.uniform(-3.35, -3.05)
            lat = random.uniform(55.85, 56.00)
            hotspots.append((lon, lat))
        return hotspots
    
    def _find_coverage_gaps(self, min_distance_km: float) -> List[Tuple[float, float]]:
        """Find locations far from any charger."""
        gaps = []
        # Sample grid and check distance to nearest charger
        for lon in range(-335, -305, 5):  # Every 0.05 degrees
            for lat in range(5585, 5600, 5):
                loc = (lon/100, lat/100)
                nearest = self.find_nearest_charger(loc, max_distance_km=100)
                if nearest is None or nearest[1] > min_distance_km:
                    gaps.append(loc)
        return gaps
    
    def _sample_location_with_grid_capacity(self) -> Tuple[float, float]:
        """Sample location where grid has spare capacity."""
        # Simplified: random location (would use grid capacity map in Phase 5)
        import random
        lon = random.uniform(-3.35, -3.05)
        lat = random.uniform(55.85, 56.00)
        return (lon, lat)
    
    def relocate_underutilized_chargers(
        self,
        num_to_relocate: int,
        utilization_threshold: float = 0.2
    ) -> List[str]:
        """Relocate chargers with <20% utilization to high-demand areas."""
        # Find underutilized chargers
        underutilized = [
            sid for sid, station in self.charging_stations.items()
            if station.occupancy_rate() < utilization_threshold
        ]
        
        # Find high-demand locations
        hotspots = self._calculate_demand_hotspots()
        
        relocated = []
        for i, station_id in enumerate(underutilized[:num_to_relocate]):
            if i < len(hotspots):
                # Move charger to hotspot
                station = self.charging_stations[station_id]
                old_location = station.location
                new_location = hotspots[i]
                
                station.location = new_location
                relocated.append(station_id)
                
                logger.info(f"Relocated {station_id}: {old_location} → {new_location}")
        
        return relocated
    
    # ========================================================================
    # Metrics & Analytics
    # ========================================================================
    
    def get_infrastructure_metrics(self) -> Dict:
        """Get comprehensive infrastructure metrics."""
        total_chargers = sum(s.num_ports for s in self.charging_stations.values())
        occupied_chargers = sum(s.currently_occupied for s in self.charging_stations.values())
        total_queued = sum(len(s.queue) for s in self.charging_stations.values())
        
        grid = self.grid_regions['default']
        
        return {
            'charging_stations': len(self.charging_stations),
            'total_ports': total_chargers,
            'occupied_ports': occupied_chargers,
            'utilization': occupied_chargers / max(1, total_chargers),
            'queued_agents': total_queued,
            'depots': len(self.depots),
            'grid_load_mw': grid.current_load_mw,
            'grid_capacity_mw': grid.capacity_mw,
            'grid_utilization': grid.utilization(),
            'grid_stressed': grid.is_overloaded(),
            'active_charging': len([s for s in self.agent_charging_state.values() 
                                   if s['status'] == 'charging']),
        }
    
    def get_hotspots(self, threshold: float = 0.8) -> List[str]:
        """
        Identify overutilized charging stations.
        
        Args:
            threshold: Occupancy threshold (0-1)
        
        Returns:
            List of station IDs with high utilization
        """
        hotspots = []
        
        for station_id, station in self.charging_stations.items():
            if station.occupancy_rate() >= threshold:
                hotspots.append(station_id)
        
        return hotspots
    
    # ========================================================================
    # Utilities
    # ========================================================================
    
    @staticmethod
    def _haversine_km(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
        """Calculate haversine distance in kilometers."""
        from math import radians, sin, cos, sqrt, atan2
        
        lon1, lat1 = coord1
        lon2, lat2 = coord2
        
        R = 6371.0  # Earth radius in km
        
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        
        a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))
        
        return R * c
    
    def populate_edinburgh_chargers(self, num_public: int = 50, num_depot: int = 5) -> None:
        """
        Quick setup for Edinburgh testing.
        
        Args:
            num_public: Number of public chargers to create
            num_depot: Number of depot chargers
        """
        import random
        
        # Edinburgh bounding box
        lon_min, lon_max = -3.35, -3.05
        lat_min, lat_max = 55.85, 56.00
        
        # Public chargers (Level 2)
        for i in range(num_public):
            lon = random.uniform(lon_min, lon_max)
            lat = random.uniform(lat_min, lat_max)
            
            self.add_charging_station(
                station_id=f"public_{i:03d}",
                location=(lon, lat),
                charger_type='level2',
                num_ports=random.choice([2, 4, 6]),
                power_kw=7.0,
                cost_per_kwh=0.15,
                owner_type='public'
            )
        
        # Change 20% of chargers to DC Fast (50kW instead of 7kW)
        for i in range(num_public // 5):
            lon = random.uniform(lon_min, lon_max)
            lat = random.uniform(lat_min, lat_max)
            
            self.add_charging_station(
                station_id=f"dcfast_{i:02d}",
                location=(lon, lat),
                charger_type='dcfast',
                num_ports=random.choice([2, 4]),
                power_kw=50.0,  # ← Much higher!
                cost_per_kwh=0.25,
                owner_type='commercial'
            )
        
        # Depots
        for i in range(num_depot):
            lon = random.uniform(lon_min, lon_max)
            lat = random.uniform(lat_min, lat_max)
            
            self.add_depot(
                depot_id=f"depot_{i:02d}",
                location=(lon, lat),
                depot_type=random.choice(['delivery', 'bus', 'taxi']),
                num_chargers=random.choice([10, 20, 30]),
                charger_power_kw=50.0
            )
        
        logger.info(f"Populated Edinburgh with {num_public} public chargers, {num_depot} depots")