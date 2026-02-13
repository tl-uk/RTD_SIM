"""
simulation/infrastructure/infrastructure_manager.py

REFACTORED: Thin facade orchestrating infrastructure subsystems.

This file is now ~250 lines instead of 700+.
All complex logic delegated to specialized subsystems.

COMPLETE VERSION: Includes load balancing support
"""

from __future__ import annotations
from typing import Dict, List, Tuple, Optional
import logging

from .charging.station_registry import ChargingStationRegistry
from .charging.availability_tracker import AvailabilityTracker
from .charging.charging_session_manager import ChargingSessionManager
from .grid.grid_capacity import GridCapacityManager
from .grid.load_balancer import LoadBalancer, create_default_zones  # ADDED
from .pricing.dynamic_pricing_engine import DynamicPricingEngine
from .expansion.placement_optimizer import ChargingPlacementOptimizer
from .expansion.cost_recovery_tracker import CostRecoveryTracker
from .depots.depot_manager import DepotManager
from .weather.ev_range_adjuster import EVRangeAdjuster

logger = logging.getLogger(__name__)


class InfrastructureManager:
    """
    Thin facade orchestrating infrastructure subsystems.
    
    Delegates to specialized managers for:
    - Charging stations (registry, availability, sessions)
    - Grid capacity
    - Load balancing (optional)
    - Pricing (time-of-day, surge)
    - Expansion (placement, cost recovery)
    - Depots
    - EV range (weather adjustments)
    
    Provides backward-compatible API for existing code.
    """
    
    def __init__(
        self,
        grid_capacity_mw: float = 1000.0,
        enable_time_of_day_pricing: bool = False,
        enable_load_balancing: bool = False  # ADDED
    ):
        """
        Initialize infrastructure subsystems.
        
        Args:
            grid_capacity_mw: Total grid capacity
            enable_time_of_day_pricing: Enable ToD pricing
            enable_load_balancing: Enable smart load balancing across zones
        """
        # Initialize subsystems
        self.stations = ChargingStationRegistry()
        self.availability = AvailabilityTracker(self.stations)
        self.sessions = ChargingSessionManager(self.stations)
        self.grid = GridCapacityManager(grid_capacity_mw)
        self.pricing = DynamicPricingEngine(enable_time_of_day_pricing)
        self.optimizer = ChargingPlacementOptimizer(self.stations)
        self.cost_recovery = CostRecoveryTracker()
        self.depots = DepotManager()
        self.ev_range = EVRangeAdjuster()
        
        # ADDED: Load balancer (optional)
        self.load_balancer = None
        if enable_load_balancing:
            self.load_balancer = LoadBalancer(self.grid)
            create_default_zones(self.load_balancer, grid_capacity_mw, num_zones=4)
            logger.info("Load balancing enabled with 4 zones")
        
        # Current simulation hour (for pricing)
        self.current_hour = 8
        
        # Backward compatibility - expose subsystem data
        self.charging_stations = self.stations.stations
        self.agent_charging_state = self.sessions.agent_states
        self.grid_regions = self.grid.regions
        
        # Historical tracking for visualization
        self.historical_utilization = []
        self.historical_load = []
        self.historical_occupancy = []
        
        # Time-of-day pricing flag
        self.enable_tod_pricing = enable_time_of_day_pricing
        
        logger.info(f"InfrastructureManager initialized (grid: {grid_capacity_mw} MW)")
    
    # ========================================================================
    # Charging Station API (Delegate to StationRegistry)
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
        """Add charging station to registry."""
        self.stations.add_station(
            station_id, location, charger_type,
            num_ports, power_kw, cost_per_kwh, owner_type
        )
    
    def find_nearest_charger(
        self,
        location: Tuple[float, float],
        charger_type: str = 'any',
        max_distance_km: float = 5.0,
        require_available: bool = False
    ) -> Optional[Tuple[str, float]]:
        """Find nearest charging station."""
        return self.stations.find_nearest(
            location, charger_type, max_distance_km, require_available
        )
    
    def get_charger_availability(self, station_id: str) -> Dict:
        """Get availability info for station."""
        return self.stations.get_availability(station_id)
    
    # ========================================================================
    # Charging Session API (Delegate to SessionManager)
    # ========================================================================
    
    def reserve_charger(
        self,
        agent_id: str,
        station_id: str,
        duration_min: float
    ) -> bool:
        """Reserve charger for agent."""
        success = self.sessions.reserve(agent_id, station_id, duration_min)
        
        # Track revenue estimate
        if success and station_id in self.stations.stations:
            station = self.stations.stations[station_id]
            revenue_estimate = duration_min * (station.power_kw / 60) * station.cost_per_kwh
            self.cost_recovery.record_revenue(revenue_estimate)
        
        return success
    
    def release_charger(self, agent_id: str) -> None:
        """Release charger when agent finishes."""
        self.sessions.release(agent_id)
    
    # ========================================================================
    # Grid API (Delegate to GridCapacityManager)
    # ========================================================================
    
    def update_grid_load(self, step: int) -> None:
        """Update grid load from active charging sessions."""
        active_charging = self.sessions.get_charging_agents()
        
        total_load_kw = 0.0
        for agent_id in active_charging:
            state = self.sessions.agent_states.get(agent_id)
            if state and state['station_id'] in self.stations.stations:
                station = self.stations.stations[state['station_id']]
                total_load_kw += station.power_kw
        
        depot_load_kw = sum(d.num_chargers * d.charger_power_kw * 0.3 
                    for d in self.depots.depots.values())
        total_with_depot = (total_load_kw + depot_load_kw) / 1000.0
        self.grid.update_load(total_with_depot)
        
        # Track historical data for visualization
        utilization = self.grid.get_utilization()
        self.historical_utilization.append(utilization)
        self.historical_load.append(self.grid.get_load())
        
        # Calculate occupancy rate
        total_ports = sum(s.num_ports for s in self.stations.stations.values())
        occupied = sum(s.currently_occupied for s in self.stations.stations.values())
        occupancy = occupied / max(1, total_ports)
        self.historical_occupancy.append(occupancy)
        
        # Log periodically
        if step % 20 == 0 and total_load_kw > 0:
            logger.info(f"Step {step}: Grid {self.grid.get_load():.2f} MW ({utilization:.1%})")
    
    def get_grid_stress_factor(self) -> float:
        """Get grid stress multiplier for cost calculations."""
        return self.grid.get_stress_factor()
    
    def get_base_grid_load(self) -> float:
        """Get base grid load (for seasonal adjustments)."""
        return self.grid.get_load()
    
    def set_grid_load(self, load_mw: float) -> None:
        """Set grid load directly (for seasonal adjustments)."""
        self.grid.update_load(load_mw)
    
    # ========================================================================
    # Load Balancing API (Delegate to LoadBalancer) - ADDED
    # ========================================================================
    
    def request_balanced_charging(
        self,
        agent_id: str,
        station_id: str,
        power_kw: float,
        duration_min: float,
        priority: int = 0,
        flexible: bool = True
    ) -> Optional[str]:
        """
        Request charging with load balancing.
        
        Args:
            agent_id: Agent identifier
            station_id: Desired charging station
            power_kw: Power requirement
            duration_min: Expected duration
            priority: 0=normal, 1=high, 2=critical
            flexible: Can be delayed/rescheduled?
        
        Returns:
            Approved zone_id or None if queued
        """
        if not self.load_balancer:
            # Fall back to direct charging if load balancing disabled
            return 'default'
        
        return self.load_balancer.request_charging(
            agent_id, station_id, power_kw, duration_min, priority, flexible
        )
    
    def complete_balanced_charging(self, agent_id: str) -> None:
        """Complete load-balanced charging session and free capacity."""
        if self.load_balancer:
            self.load_balancer.complete_charging(agent_id)
    
    def process_pending_charging_requests(self) -> List[Tuple[str, str]]:
        """
        Process pending flexible charging requests.
        
        Returns:
            List of (agent_id, zone_id) for newly approved requests
        """
        if self.load_balancer:
            return self.load_balancer.process_pending_requests()
        return []
    
    def rebalance_grid_load(self) -> int:
        """
        Actively rebalance load across zones.
        
        Moves flexible sessions from overloaded to underloaded zones.
        
        Returns:
            Number of sessions rebalanced
        """
        if self.load_balancer:
            return self.load_balancer.rebalance_load()
        return 0
    
    def get_load_balancing_metrics(self) -> Dict:
        """Get load balancing metrics."""
        if self.load_balancer:
            return self.load_balancer.get_balancing_metrics()
        return {'load_balancing_enabled': False}
    
    def get_zone_status(self) -> List[Dict]:
        """Get status of all load balancing zones."""
        if self.load_balancer:
            return self.load_balancer.get_zone_status()
        return []
    
    # ========================================================================
    # Pricing API (Delegate to DynamicPricingEngine)
    # ========================================================================
    
    def update_time(self, step: int, steps_per_hour: int = 60) -> None:
        """Update simulation time for ToD pricing."""
        self.current_hour = (8 + (step // steps_per_hour)) % 24
        self.pricing.update_hour(self.current_hour)
    
    def get_current_charging_cost(self, station_id: str) -> float:
        """Get current cost per kWh at station."""
        return self.pricing.get_price(station_id, self.stations.stations)
    
    # ========================================================================
    # Expansion API (Delegate to PlacementOptimizer)
    # ========================================================================
    
    def add_chargers_by_demand(
        self,
        num_chargers: int,
        charger_type: str = 'level2',
        strategy: str = 'demand_heatmap'
    ) -> List[str]:
        """Add chargers using placement strategy."""
        new_stations = self.optimizer.place_chargers(
            num_chargers, charger_type, strategy
        )
        
        # Track investment cost
        cost_per_charger = 5000 if charger_type == 'level2' else 50000
        total_cost = len(new_stations) * cost_per_charger
        self.cost_recovery.record_investment(total_cost)
        
        return new_stations
    
    def relocate_underutilized_chargers(
        self,
        num_to_relocate: int,
        utilization_threshold: float = 0.2
    ) -> List[str]:
        """Relocate underutilized chargers to high-demand areas."""
        return self.optimizer.relocate_underutilized(
            num_to_relocate, utilization_threshold
        )
    
    # ========================================================================
    # EV Range API (Delegate to EVRangeAdjuster)
    # ========================================================================
    
    def get_base_ev_range(self, mode: str) -> float:
        """Get rated EV range at optimal temperature."""
        return self.ev_range.get_base_range(mode)
    
    def set_adjusted_ev_range(self, mode: str, range_km: float) -> None:
        """Set weather-adjusted range."""
        self.ev_range.set_adjusted_range(mode, range_km)
    
    def get_adjusted_ev_range(self, mode: str) -> float:
        """Get current adjusted range."""
        return self.ev_range.get_adjusted_range(mode)
    
    # ========================================================================
    # Depot API (Delegate to DepotManager)
    # ========================================================================
    
    def add_depot(
        self,
        depot_id: str,
        location: Tuple[float, float],
        depot_type: str,
        num_chargers: int = 10,
        charger_power_kw: float = 50.0
    ) -> None:
        """Add commercial/freight depot."""
        self.depots.add_depot(
            depot_id, location, depot_type,
            num_chargers, charger_power_kw
        )
    
    def find_nearest_depot(
        self,
        location: Tuple[float, float],
        depot_type: str = 'any'
    ) -> Optional[Tuple[str, float]]:
        """Find nearest depot to location."""
        return self.depots.find_nearest(location, depot_type)
    
    # ========================================================================
    # Metrics API (Aggregates from subsystems)
    # ========================================================================
    
    def get_infrastructure_metrics(self) -> Dict:
        """Get comprehensive infrastructure metrics."""
        metrics = {}
        
        # Charging station metrics
        metrics.update(self.stations.get_metrics())
        
        # Grid metrics
        metrics.update(self.grid.get_metrics())
        
        # Session metrics
        metrics.update(self.sessions.get_metrics())
        
        # Load balancing metrics (if enabled)
        if self.load_balancer:
            lb_metrics = self.load_balancer.get_balancing_metrics()
            metrics['load_balancing_enabled'] = True
            metrics['grid_well_balanced'] = lb_metrics.get('well_balanced', False)
            metrics['pending_charging_requests'] = lb_metrics.get('pending_requests', 0)
        else:
            metrics['load_balancing_enabled'] = False
        
        # Cost recovery
        cost_metrics = self.cost_recovery.get_metrics()
        metrics['infrastructure_investment'] = cost_metrics['total_investment']
        metrics['infrastructure_revenue'] = cost_metrics['total_revenue']
        metrics['infrastructure_roi'] = cost_metrics['roi_percentage']
        
        # Depot count
        metrics['depots'] = len(self.depots.depots)
        
        return metrics
    
    def get_hotspots(self, threshold: float = 0.8) -> List[str]:
        """Identify overutilized charging stations."""
        return self.stations.get_hotspots(threshold)
    
    # ========================================================================
    # Convenience Methods (Backward Compatibility)
    # ========================================================================
    
    def populate_edinburgh_chargers(
        self,
        num_public: int = 50,
        num_depot: int = 5
    ) -> None:
        """Quick setup for Edinburgh testing."""
        self.stations.populate_edinburgh(num_public)
        self.depots.populate_edinburgh(num_depot)
        
        logger.info(f"Populated Edinburgh: {num_public} chargers, {num_depot} depots")
        