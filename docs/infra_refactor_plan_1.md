# Infrastructure Manager Refactoring Plan
## Breaking Down the Monolith

---

## 📊 Current State: 700+ Lines, Too Many Responsibilities

**Current `infrastructure_manager.py` handles:**
1. Charging station registry & availability
2. Depot management
3. Grid capacity tracking
4. Time-of-day pricing
5. Smart charging optimization
6. Agent charging state tracking
7. Infrastructure expansion algorithms
8. Cost recovery calculations
9. Metrics & analytics
10. **NEW**: EV range adjustments (weather)

**Problem**: Single Responsibility Principle violated 10 times!

---

## 🎯 Refactored Architecture

```
simulation/infrastructure/
├── __init__.py                          # Re-export main classes
├── infrastructure_manager.py            # THIN FACADE (150 lines)
├── charging/
│   ├── __init__.py
│   ├── station_registry.py             # Charging station tracking
│   ├── availability_tracker.py         # Real-time availability
│   └── charging_session_manager.py     # Agent charging state
├── grid/
│   ├── __init__.py
│   ├── grid_capacity.py                # Grid load tracking
│   └── load_balancer.py                # Smart load distribution
├── pricing/
│   ├── __init__.py
│   ├── time_of_day_pricing.py          # Already exists!
│   └── dynamic_pricing_engine.py       # Surge pricing, cost recovery
├── expansion/
│   ├── __init__.py
│   ├── demand_analyzer.py              # Hotspot detection
│   ├── placement_optimizer.py          # Charger placement strategies
│   └── cost_recovery_tracker.py        # ROI calculations
├── depots/
│   ├── __init__.py
│   └── depot_manager.py                # Depot tracking
└── weather/
    ├── __init__.py
    └── ev_range_adjuster.py            # Temperature-based range

# Total: 17 focused files instead of 1 monolith!
```

---

## 🔧 Refactored `infrastructure_manager.py` (Thin Facade)

**Size**: ~150 lines (down from 700!)

```python
"""
simulation/infrastructure/infrastructure_manager.py

REFACTORED: Thin facade delegating to specialized subsystems.
"""

from __future__ import annotations
from typing import Dict, List, Tuple, Optional
import logging

from .charging.station_registry import ChargingStationRegistry
from .charging.charging_session_manager import ChargingSessionManager
from .grid.grid_capacity import GridCapacityManager
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
    - Charging stations
    - Grid capacity
    - Pricing
    - Expansion
    - Depots
    - EV range (weather)
    """
    
    def __init__(self, grid_capacity_mw: float = 1000.0, 
                 enable_time_of_day_pricing: bool = False):
        """Initialize infrastructure subsystems."""
        
        # Core subsystems
        self.stations = ChargingStationRegistry()
        self.sessions = ChargingSessionManager(self.stations)
        self.grid = GridCapacityManager(grid_capacity_mw)
        self.pricing = DynamicPricingEngine(enable_time_of_day_pricing)
        self.optimizer = ChargingPlacementOptimizer(self.stations)
        self.cost_recovery = CostRecoveryTracker()
        self.depots = DepotManager()
        self.ev_range = EVRangeAdjuster()
        
        # Current simulation hour (for pricing)
        self.current_hour = 8
        
        # Backward compatibility - expose subsystem data
        self.charging_stations = self.stations.stations
        self.agent_charging_state = self.sessions.agent_states
        self.grid_regions = self.grid.regions
        
        logger.info(f"InfrastructureManager initialized (grid: {grid_capacity_mw} MW)")
    
    # ========================================================================
    # Charging Station API (Delegate to StationRegistry)
    # ========================================================================
    
    def add_charging_station(self, station_id: str, location: Tuple[float, float],
                            charger_type: str = 'level2', num_ports: int = 2,
                            power_kw: float = 7.0, cost_per_kwh: float = 0.15,
                            owner_type: str = 'public') -> None:
        """Add charging station."""
        self.stations.add_station(station_id, location, charger_type, 
                                 num_ports, power_kw, cost_per_kwh, owner_type)
    
    def find_nearest_charger(self, location: Tuple[float, float],
                            charger_type: str = 'any',
                            max_distance_km: float = 5.0,
                            require_available: bool = False) -> Optional[Tuple[str, float]]:
        """Find nearest charging station."""
        return self.stations.find_nearest(location, charger_type, 
                                         max_distance_km, require_available)
    
    def get_charger_availability(self, station_id: str) -> Dict:
        """Get availability info for station."""
        return self.stations.get_availability(station_id)
    
    # ========================================================================
    # Charging Session API (Delegate to SessionManager)
    # ========================================================================
    
    def reserve_charger(self, agent_id: str, station_id: str, 
                       duration_min: float) -> bool:
        """Reserve charger for agent."""
        success = self.sessions.reserve(agent_id, station_id, duration_min)
        
        # Track revenue
        if success and station_id in self.stations.stations:
            station = self.stations.stations[station_id]
            revenue = duration_min * (station.power_kw / 60) * station.cost_per_kwh
            self.cost_recovery.record_revenue(revenue)
        
        return success
    
    def release_charger(self, agent_id: str) -> None:
        """Release charger when agent finishes."""
        self.sessions.release(agent_id)
    
    # ========================================================================
    # Grid API (Delegate to GridCapacityManager)
    # ========================================================================
    
    def update_grid_load(self, step: int) -> None:
        """Update grid load from active charging."""
        active_charging = self.sessions.get_active_sessions()
        total_load_kw = sum(
            self.stations.stations[s['station_id']].power_kw 
            for s in active_charging 
            if s['station_id'] in self.stations.stations
        )
        
        self.grid.update_load(total_load_kw / 1000.0)  # Convert to MW
        
        if step % 20 == 0:
            logger.info(f"Step {step}: Grid {self.grid.get_load():.2f} MW "
                       f"({self.grid.get_utilization():.1%})")
    
    def get_grid_stress_factor(self) -> float:
        """Get grid stress multiplier."""
        return self.grid.get_stress_factor()
    
    # ========================================================================
    # Pricing API (Delegate to DynamicPricingEngine)
    # ========================================================================
    
    def update_time(self, step: int, steps_per_hour: int = 6) -> None:
        """Update simulation time."""
        self.current_hour = (8 + (step // steps_per_hour)) % 24
        self.pricing.update_hour(self.current_hour)
    
    def get_current_charging_cost(self, station_id: str) -> float:
        """Get current cost per kWh at station."""
        return self.pricing.get_price(station_id, self.stations.stations)
    
    # ========================================================================
    # Expansion API (Delegate to PlacementOptimizer)
    # ========================================================================
    
    def add_chargers_by_demand(self, num_chargers: int, 
                               charger_type: str = 'level2',
                               strategy: str = 'demand_heatmap') -> List[str]:
        """Add chargers using placement strategy."""
        new_stations = self.optimizer.place_chargers(
            num_chargers, charger_type, strategy
        )
        
        # Track cost
        cost_per_charger = 5000
        total_cost = len(new_stations) * cost_per_charger
        self.cost_recovery.record_investment(total_cost)
        
        return new_stations
    
    def relocate_underutilized_chargers(self, num_to_relocate: int,
                                       utilization_threshold: float = 0.2) -> List[str]:
        """Relocate underutilized chargers."""
        return self.optimizer.relocate_underutilized(
            num_to_relocate, utilization_threshold
        )
    
    # ========================================================================
    # EV Range API (Delegate to EVRangeAdjuster)
    # ========================================================================
    
    def get_base_ev_range(self, mode: str) -> float:
        """Get rated EV range."""
        return self.ev_range.get_base_range(mode)
    
    def set_adjusted_ev_range(self, mode: str, range_km: float):
        """Set weather-adjusted range."""
        self.ev_range.set_adjusted_range(mode, range_km)
    
    def get_adjusted_ev_range(self, mode: str) -> float:
        """Get current adjusted range."""
        return self.ev_range.get_adjusted_range(mode)
    
    # ========================================================================
    # Depot API (Delegate to DepotManager)
    # ========================================================================
    
    def add_depot(self, depot_id: str, location: Tuple[float, float],
                 depot_type: str, num_chargers: int = 10,
                 charger_power_kw: float = 50.0) -> None:
        """Add depot."""
        self.depots.add_depot(depot_id, location, depot_type, 
                             num_chargers, charger_power_kw)
    
    def find_nearest_depot(self, location: Tuple[float, float],
                          depot_type: str = 'any') -> Optional[Tuple[str, float]]:
        """Find nearest depot."""
        return self.depots.find_nearest(location, depot_type)
    
    # ========================================================================
    # Metrics API (Aggregates from subsystems)
    # ========================================================================
    
    def get_infrastructure_metrics(self) -> Dict:
        """Get comprehensive metrics."""
        return {
            **self.stations.get_metrics(),
            **self.grid.get_metrics(),
            **self.sessions.get_metrics(),
            **self.cost_recovery.get_metrics(),
        }
    
    # ========================================================================
    # Convenience Methods (Backward Compatibility)
    # ========================================================================
    
    def populate_edinburgh_chargers(self, num_public: int = 50, 
                                    num_depot: int = 5) -> None:
        """Quick setup for Edinburgh."""
        self.stations.populate_edinburgh(num_public)
        self.depots.populate_edinburgh(num_depot)
```

**Result**: Main file reduced from 700 lines to 150 lines!

---

## 📝 Example Subsystem: `charging/station_registry.py`

```python
"""
simulation/infrastructure/charging/station_registry.py

Manages charging station registry and spatial queries.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
import logging
import math

logger = logging.getLogger(__name__)


@dataclass
class ChargingStation:
    """Individual charging station."""
    station_id: str
    location: Tuple[float, float]
    charger_type: str
    num_ports: int
    power_kw: float
    cost_per_kwh: float
    
    # State
    currently_occupied: int = 0
    queue: List[str] = field(default_factory=list)
    operational: bool = True
    owner_type: str = 'public'
    
    # History
    utilization_history: List[float] = field(default_factory=list)
    
    def is_available(self) -> bool:
        """Check if ports available."""
        return self.operational and self.currently_occupied < self.num_ports
    
    def occupancy_rate(self) -> float:
        """Current occupancy."""
        return self.currently_occupied / max(1, self.num_ports)


class ChargingStationRegistry:
    """Registry of all charging stations."""
    
    def __init__(self):
        self.stations: Dict[str, ChargingStation] = {}
    
    def add_station(self, station_id: str, location: Tuple[float, float],
                   charger_type: str = 'level2', num_ports: int = 2,
                   power_kw: float = 7.0, cost_per_kwh: float = 0.15,
                   owner_type: str = 'public') -> None:
        """Add station to registry."""
        station = ChargingStation(
            station_id=station_id,
            location=location,
            charger_type=charger_type,
            num_ports=num_ports,
            power_kw=power_kw,
            cost_per_kwh=cost_per_kwh,
            owner_type=owner_type
        )
        self.stations[station_id] = station
    
    def find_nearest(self, location: Tuple[float, float],
                    charger_type: str = 'any',
                    max_distance_km: float = 5.0,
                    require_available: bool = False) -> Optional[Tuple[str, float]]:
        """Find nearest station."""
        # Implementation here...
        pass
    
    def get_metrics(self) -> Dict:
        """Get registry metrics."""
        total_ports = sum(s.num_ports for s in self.stations.values())
        occupied = sum(s.currently_occupied for s in self.stations.values())
        
        return {
            'charging_stations': len(self.stations),
            'total_ports': total_ports,
            'occupied_ports': occupied,
            'utilization': occupied / max(1, total_ports),
        }
```

---

## ✅ Benefits of Refactoring

1. **Single Responsibility**: Each file has ONE clear purpose
2. **Testability**: Can unit test each subsystem independently
3. **Maintainability**: 150-line files easier than 700-line monolith
4. **Extensibility**: Add new pricing strategies without touching grid code
5. **Team Development**: Multiple devs can work on different subsystems
6. **Performance**: Can optimize hot paths in isolation

---

## 🚀 Migration Path (2-3 hours)

**Step 1**: Create directory structure (5 min)
**Step 2**: Extract `ChargingStation` → `station_registry.py` (20 min)
**Step 3**: Extract grid logic → `grid_capacity.py` (20 min)
**Step 4**: Extract session tracking → `charging_session_manager.py` (30 min)
**Step 5**: Extract expansion → `placement_optimizer.py` (30 min)
**Step 6**: Refactor main file as thin facade (30 min)
**Step 7**: Test backward compatibility (30 min)

---

## 📌 Recommendation

**Do this refactoring BEFORE adding more features!**

Current infrastructure manager is at the **700-line danger zone**. Adding weather integration would push it to 800+, making it unmaintainable.

Refactor now while you remember the code structure, then Phase 5.2 integration will be much cleaner.
