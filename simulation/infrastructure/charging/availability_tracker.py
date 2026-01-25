"""
simulation.infrastructure.charging.availability_tracker

Charging station availability tracking. 

Real-time availability of charging stations
is monitored and updated to reflect usage patterns, maintenance schedules, and
unexpected outages. This module provides interfaces to query current availability
and historical usage statistics.

"""

"""
simulation/infrastructure/charging/availability_tracker.py

Real-time tracking of charging port availability.
Manages port occupation and queue dynamics.
"""

from __future__ import annotations
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class AvailabilityTracker:
    """
    Tracks real-time charging port availability.
    
    Responsibilities:
    - Monitor port occupation
    - Manage charging queues
    - Predict wait times
    - Generate availability reports
    """
    
    def __init__(self, station_registry):
        """
        Initialize availability tracker.
        
        Args:
            station_registry: ChargingStationRegistry instance
        """
        self.registry = station_registry
        
        # Historical snapshots for trend analysis
        self.availability_snapshots: List[Dict] = []
        
    def occupy_port(self, station_id: str) -> bool:
        """
        Occupy a charging port.
        
        Args:
            station_id: Station identifier
        
        Returns:
            True if port occupied successfully
        """
        if station_id not in self.registry.stations:
            logger.warning(f"Station {station_id} not found")
            return False
        
        station = self.registry.stations[station_id]
        
        if not station.is_available():
            logger.debug(f"No ports available at {station_id}")
            return False
        
        station.currently_occupied += 1
        logger.debug(f"Port occupied at {station_id} ({station.currently_occupied}/{station.num_ports})")
        
        return True
    
    def release_port(self, station_id: str) -> bool:
        """
        Release a charging port.
        
        Args:
            station_id: Station identifier
        
        Returns:
            True if port released successfully
        """
        if station_id not in self.registry.stations:
            logger.warning(f"Station {station_id} not found")
            return False
        
        station = self.registry.stations[station_id]
        
        if station.currently_occupied > 0:
            station.currently_occupied -= 1
            logger.debug(f"Port released at {station_id} ({station.currently_occupied}/{station.num_ports})")
            return True
        
        logger.warning(f"No occupied ports to release at {station_id}")
        return False
    
    def add_to_queue(self, station_id: str, agent_id: str) -> bool:
        """Add agent to station queue."""
        if station_id not in self.registry.stations:
            return False
        
        station = self.registry.stations[station_id]
        
        if agent_id not in station.queue:
            station.queue.append(agent_id)
            logger.debug(f"Agent {agent_id} queued at {station_id} (position {len(station.queue)})")
            return True
        
        return False
    
    def remove_from_queue(self, station_id: str, agent_id: str) -> bool:
        """Remove agent from station queue."""
        if station_id not in self.registry.stations:
            return False
        
        station = self.registry.stations[station_id]
        
        if agent_id in station.queue:
            station.queue.remove(agent_id)
            logger.debug(f"Agent {agent_id} removed from queue at {station_id}")
            return True
        
        return False
    
    def process_queue(self, station_id: str) -> Optional[str]:
        """
        Process queue when port becomes available.
        
        Returns:
            Next agent_id from queue or None
        """
        if station_id not in self.registry.stations:
            return None
        
        station = self.registry.stations[station_id]
        
        if station.queue and station.is_available():
            next_agent = station.queue.pop(0)
            logger.debug(f"Processing queue at {station_id}: {next_agent} moved to charging")
            return next_agent
        
        return None
    
    def take_snapshot(self) -> None:
        """Record current availability snapshot for trend analysis."""
        snapshot = {
            'total_stations': len(self.registry.stations),
            'total_ports': sum(s.num_ports for s in self.registry.stations.values()),
            'occupied_ports': sum(s.currently_occupied for s in self.registry.stations.values()),
            'queued_agents': sum(len(s.queue) for s in self.registry.stations.values()),
            'available_stations': sum(1 for s in self.registry.stations.values() if s.is_available()),
        }
        
        self.availability_snapshots.append(snapshot)
        
        # Keep only last 1000 snapshots
        if len(self.availability_snapshots) > 1000:
            self.availability_snapshots.pop(0)
    
    def get_availability_trend(self) -> Dict:
        """Get availability trends over time."""
        if not self.availability_snapshots:
            return {'trend': 'no_data'}
        
        recent_snapshots = self.availability_snapshots[-100:]  # Last 100 snapshots
        
        avg_utilization = sum(
            s['occupied_ports'] / max(1, s['total_ports'])
            for s in recent_snapshots
        ) / len(recent_snapshots)
        
        avg_queue_length = sum(
            s['queued_agents']
            for s in recent_snapshots
        ) / len(recent_snapshots)
        
        return {
            'trend': 'increasing' if avg_utilization > 0.7 else 'stable',
            'avg_utilization': avg_utilization,
            'avg_queue_length': avg_queue_length,
            'snapshots_analyzed': len(recent_snapshots),
        }
    
    def predict_wait_time(self, station_id: str, avg_charge_time_min: float = 30.0) -> float:
        """
        Predict wait time at a station.
        
        Args:
            station_id: Station identifier
            avg_charge_time_min: Average charging duration
        
        Returns:
            Estimated wait time in minutes
        """
        if station_id not in self.registry.stations:
            return 0.0
        
        station = self.registry.stations[station_id]
        
        return station.get_queue_wait_time_min(avg_charge_time_min)
    
    def get_availability_report(self) -> Dict:
        """Generate comprehensive availability report."""
        total_stations = len(self.registry.stations)
        
        if total_stations == 0:
            return {'status': 'no_stations'}
        
        available_count = sum(1 for s in self.registry.stations.values() if s.is_available())
        fully_occupied = sum(1 for s in self.registry.stations.values() if s.occupancy_rate() == 1.0)
        with_queues = sum(1 for s in self.registry.stations.values() if len(s.queue) > 0)
        
        total_ports = sum(s.num_ports for s in self.registry.stations.values())
        occupied_ports = sum(s.currently_occupied for s in self.registry.stations.values())
        
        return {
            'total_stations': total_stations,
            'available_stations': available_count,
            'fully_occupied_stations': fully_occupied,
            'stations_with_queues': with_queues,
            'total_ports': total_ports,
            'occupied_ports': occupied_ports,
            'free_ports': total_ports - occupied_ports,
            'overall_utilization': occupied_ports / max(1, total_ports),
            'availability_rate': available_count / total_stations,
        }