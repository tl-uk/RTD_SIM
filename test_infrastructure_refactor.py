"""
test_infrastructure_refactor.py

Quick tests to verify refactored infrastructure works correctly.
Run with: pytest test_infrastructure_refactor.py -v
"""

import pytest
from simulation.infrastructure import InfrastructureManager


class TestBackwardCompatibility:
    """Verify all old API methods still work."""
    
    def test_initialization(self):
        """Test manager initializes correctly."""
        infra = InfrastructureManager(grid_capacity_mw=100.0)
        
        assert infra.grid.regions['default'].capacity_mw == 100.0
        assert len(infra.stations.stations) == 0
    
    def test_add_charging_station(self):
        """Test adding charging station (old API)."""
        infra = InfrastructureManager()
        
        infra.add_charging_station(
            station_id="test_station",
            location=(-3.19, 55.95),
            charger_type='level2',
            num_ports=4,
            power_kw=7.0
        )
        
        assert "test_station" in infra.charging_stations
        assert infra.charging_stations["test_station"].num_ports == 4
    
    def test_find_nearest_charger(self):
        """Test finding nearest charger."""
        infra = InfrastructureManager()
        
        infra.add_charging_station("s1", (-3.19, 55.95), num_ports=2)
        infra.add_charging_station("s2", (-3.20, 55.96), num_ports=4)
        
        nearest = infra.find_nearest_charger(
            location=(-3.195, 55.955),
            max_distance_km=10.0
        )
        
        assert nearest is not None
        station_id, distance = nearest
        assert station_id in ["s1", "s2"]
        assert distance < 10.0
    
    def test_reserve_and_release_charger(self):
        """Test charging session workflow."""
        infra = InfrastructureManager()
        
        infra.add_charging_station("s1", (-3.19, 55.95), num_ports=2)
        
        # Reserve charger
        success = infra.reserve_charger("agent_001", "s1", duration_min=60.0)
        assert success is True
        
        # Check state
        assert "agent_001" in infra.agent_charging_state
        assert infra.charging_stations["s1"].currently_occupied == 1
        
        # Release charger
        infra.release_charger("agent_001")
        assert "agent_001" not in infra.agent_charging_state
        assert infra.charging_stations["s1"].currently_occupied == 0
    
    def test_grid_load_update(self):
        """Test grid load tracking."""
        infra = InfrastructureManager(grid_capacity_mw=100.0)
        
        infra.add_charging_station("s1", (-3.19, 55.95), power_kw=50.0)
        infra.reserve_charger("agent_001", "s1", duration_min=60.0)
        infra.sessions.start_charging("agent_001", step=0)
        
        infra.update_grid_load(step=0)
        
        grid_load = infra.grid.get_load()
        assert grid_load == 0.05  # 50 kW = 0.05 MW
    
    def test_get_infrastructure_metrics(self):
        """Test metrics aggregation."""
        infra = InfrastructureManager()
        
        infra.add_charging_station("s1", (-3.19, 55.95), num_ports=4)
        infra.add_charging_station("s2", (-3.20, 55.96), num_ports=2)
        
        metrics = infra.get_infrastructure_metrics()
        
        assert metrics['charging_stations'] == 2
        assert metrics['total_ports'] == 6
        assert 'grid_utilization' in metrics


class TestNewSubsystems:
    """Test new subsystem-specific functionality."""
    
    def test_station_registry_spatial_queries(self):
        """Test enhanced spatial queries."""
        infra = InfrastructureManager()
        
        infra.add_charging_station("s1", (-3.19, 55.95))
        infra.add_charging_station("s2", (-3.20, 55.96))
        infra.add_charging_station("s3", (-3.21, 55.97))
        
        # Find within radius
        nearby = infra.stations.find_within_radius(
            location=(-3.19, 55.95),
            radius_km=2.0
        )
        
        assert len(nearby) >= 1
        assert all(distance <= 2.0 for _, distance in nearby)
    
    def test_availability_tracking(self):
        """Test availability tracking subsystem."""
        infra = InfrastructureManager()
        
        infra.add_charging_station("s1", (-3.19, 55.95), num_ports=2)
        
        # Occupy port
        success = infra.availability.occupy_port("s1")
        assert success is True
        assert infra.charging_stations["s1"].currently_occupied == 1
        
        # Release port
        success = infra.availability.release_port("s1")
        assert success is True
        assert infra.charging_stations["s1"].currently_occupied == 0
    
    def test_grid_stress_factor(self):
        """Test grid stress calculation."""
        infra = InfrastructureManager(grid_capacity_mw=100.0)
        
        # Low load
        infra.grid.update_load(50.0)
        assert infra.get_grid_stress_factor() == 1.0
        
        # High load
        infra.grid.update_load(90.0)
        assert infra.get_grid_stress_factor() == 1.5
        
        # Critical load
        infra.grid.update_load(98.0)
        assert infra.get_grid_stress_factor() == 2.0
    
    def test_cost_recovery_tracking(self):
        """Test cost recovery calculations."""
        infra = InfrastructureManager()
        
        # Record investment
        infra.cost_recovery.record_investment(50000.0)
        
        # Record revenue
        infra.cost_recovery.record_revenue(5000.0)
        
        metrics = infra.cost_recovery.get_metrics()
        
        assert metrics['total_investment'] == 50000.0
        assert metrics['total_revenue'] == 5000.0
        assert metrics['roi_percentage'] == 10.0
    
    def test_ev_range_adjustment(self):
        """Test EV range weather adjustments."""
        infra = InfrastructureManager()
        
        # Base range
        base_range = infra.get_base_ev_range('ev')
        assert base_range == 350.0
        
        # Adjust for cold weather
        infra.set_adjusted_ev_range('ev', 262.5)  # 75% of base
        
        adjusted = infra.get_adjusted_ev_range('ev')
        assert adjusted == 262.5
    
    def test_charger_placement(self):
        """Test charger placement optimizer."""
        infra = InfrastructureManager()
        
        # Place chargers using demand heatmap strategy
        new_stations = infra.add_chargers_by_demand(
            num_chargers=5,
            charger_type='level2',
            strategy='demand_heatmap'
        )
        
        assert len(new_stations) == 5
        assert all(sid in infra.charging_stations for sid in new_stations)


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_reserve_nonexistent_station(self):
        """Test reserving non-existent station."""
        infra = InfrastructureManager()
        
        success = infra.reserve_charger("agent_001", "nonexistent", 60.0)
        assert success is False
    
    def test_release_nonexistent_agent(self):
        """Test releasing non-existent agent (should not crash)."""
        infra = InfrastructureManager()
        
        # Should not raise exception
        infra.release_charger("nonexistent_agent")
    
    def test_find_nearest_no_stations(self):
        """Test finding nearest when no stations exist."""
        infra = InfrastructureManager()
        
        nearest = infra.find_nearest_charger((-3.19, 55.95))
        assert nearest is None
    
    def test_full_station_queuing(self):
        """Test queue behavior when station is full."""
        infra = InfrastructureManager()
        
        infra.add_charging_station("s1", (-3.19, 55.95), num_ports=1)
        
        # First agent reserves
        assert infra.reserve_charger("agent_001", "s1", 60.0) is True
        
        # Second agent gets queued
        assert infra.reserve_charger("agent_002", "s1", 60.0) is False
        assert "agent_002" in infra.charging_stations["s1"].queue


def test_populate_edinburgh():
    """Test quick Edinburgh setup."""
    infra = InfrastructureManager()
    
    infra.populate_edinburgh_chargers(num_public=50, num_depot=5)
    
    # Should have ~60 stations (50 level2 + 10 dcfast)
    assert len(infra.charging_stations) >= 50
    
    # Should have 5 depots
    assert len(infra.depots.depots) == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])