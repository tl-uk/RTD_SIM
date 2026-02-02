"""
analytics/network_efficiency.py

Phase 5.3: Infrastructure and system performance metrics.
Tracks network utilization, bottlenecks, and efficiency indicators.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import logging
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Bottleneck:
    """Identified network bottleneck."""
    location: Tuple[float, float]  # lat, lon
    bottleneck_type: str  # 'charger', 'grid', 'route'
    severity: float  # 0-1
    affected_agents: int
    congestion_factor: float  # How much slower than normal
    recommendation: str


@dataclass
class InfrastructureUtilization:
    """Infrastructure usage statistics."""
    resource_type: str  # 'charger', 'grid', 'depot'
    resource_id: str
    location: Optional[Tuple[float, float]]
    
    # Utilization
    capacity: float
    peak_load: float
    avg_load: float
    utilization_rate: float  # 0-1
    
    # Performance
    queue_length_avg: float
    queue_length_max: int
    service_time_avg: float
    
    # Efficiency
    wasted_capacity: float  # Underutilized
    excess_demand: float  # Overutilized
    efficiency_score: float  # 0-1


class NetworkEfficiencyTracker:
    """
    Track infrastructure and system performance.
    
    Enables:
    - VKT (Vehicle Kilometers Traveled) analysis
    - Infrastructure utilization tracking
    - Bottleneck identification
    - Congestion measurement
    """
    
    def __init__(self):
        """Initialize network efficiency tracker."""
        # VKT tracking
        self.vkt_by_mode: Dict[str, float] = defaultdict(float)
        self.vkt_by_vehicle_type: Dict[str, float] = defaultdict(float)
        self.vkt_history: List[Dict] = []
        
        # Infrastructure tracking
        self.charger_utilization_history: List[Dict] = []
        self.grid_load_history: List[Dict] = []
        
        # Congestion tracking
        self.congestion_events: List[Dict] = []
        self.route_delays: Dict[str, List[float]] = defaultdict(list)
        
        # Bottlenecks
        self.bottlenecks: List[Bottleneck] = []
        
        logger.info("✅ NetworkEfficiencyTracker initialized")
    
    # =========================================================================
    # VKT Tracking
    # =========================================================================
    
    def record_vehicle_travel(
        self,
        agent_id: str,
        mode: str,
        distance_km: float,
        vehicle_type: str = "personal",
        step: int = 0
    ):
        """
        Record vehicle kilometers traveled.
        
        Args:
            agent_id: Agent ID (use agent.agent_id)
            mode: Transport mode
            distance_km: Distance traveled
            vehicle_type: Type of vehicle (personal, freight_light, freight_heavy)
            step: Current step
        """
        self.vkt_by_mode[mode] += distance_km
        self.vkt_by_vehicle_type[vehicle_type] += distance_km
    
    def get_vkt_summary(self) -> Dict:
        """
        Get VKT summary statistics.
        
        Returns:
            Dict with total VKT, per mode, per vehicle type
        """
        total_vkt = sum(self.vkt_by_mode.values())
        
        return {
            'total_vkt_km': total_vkt,
            'by_mode': dict(self.vkt_by_mode),
            'by_vehicle_type': dict(self.vkt_by_vehicle_type),
            'avg_trip_distance': self._calculate_avg_trip_distance(),
        }
    
    def _calculate_avg_trip_distance(self) -> Dict[str, float]:
        """Calculate average trip distance by mode."""
        # This would require trip count tracking
        # Simplified version
        avg_distances = {}
        for mode, total_vkt in self.vkt_by_mode.items():
            # Estimate based on mode characteristics
            if mode in ['walk', 'bike']:
                avg_distances[mode] = min(5.0, total_vkt)
            elif mode in ['bus', 'tram']:
                avg_distances[mode] = min(15.0, total_vkt)
            else:
                avg_distances[mode] = total_vkt
        
        return avg_distances
    
    # =========================================================================
    # Infrastructure Utilization
    # =========================================================================
    
    def record_infrastructure_state(
        self,
        step: int,
        infrastructure
    ):
        """
        Record infrastructure state at current step.
        
        Args:
            step: Current simulation step
            infrastructure: InfrastructureManager instance
        """
        if not infrastructure:
            return
        
        metrics = infrastructure.get_infrastructure_metrics()
        
        # Charger utilization
        charger_data = {
            'step': step,
            'occupied_ports': metrics.get('occupied_ports', 0),
            'total_ports': metrics.get('total_ports', 0),
            'utilization': metrics.get('utilization', 0.0),
            'queued_agents': metrics.get('queued_agents', 0),
        }
        self.charger_utilization_history.append(charger_data)
        
        # Grid load
        grid_data = {
            'step': step,
            'load_mw': metrics.get('grid_load_mw', 0.0),
            'capacity_mw': metrics.get('grid_capacity_mw', 1.0),
            'utilization': metrics.get('grid_utilization', 0.0),
        }
        self.grid_load_history.append(grid_data)
    
    def analyze_infrastructure_efficiency(
        self,
        infrastructure
    ) -> Dict[str, InfrastructureUtilization]:
        """
        Analyze efficiency of all infrastructure resources.
        
        Args:
            infrastructure: InfrastructureManager instance
        
        Returns:
            Dict mapping resource_id -> InfrastructureUtilization
        """
        utilization_reports = {}
        
        if not infrastructure:
            return utilization_reports
        
        # Charger analysis
        if hasattr(infrastructure, 'charging_stations'):
            for station_id, station in infrastructure.charging_stations.items():
                util = self._analyze_charger_utilization(station_id, station)
                utilization_reports[f"charger_{station_id}"] = util
        
        # Grid analysis
        grid_util = self._analyze_grid_utilization(infrastructure)
        utilization_reports['grid'] = grid_util
        
        return utilization_reports
    
    def _analyze_charger_utilization(
        self,
        station_id: str,
        station
    ) -> InfrastructureUtilization:
        """Analyze individual charger station."""
        # Get historical data for this station
        station_history = [
            h for h in self.charger_utilization_history
            # Would need per-station tracking in practice
        ]
        
        if not station_history:
            capacity = getattr(station, 'num_ports', 4)
            return InfrastructureUtilization(
                resource_type='charger',
                resource_id=station_id,
                location=getattr(station, 'location', None),
                capacity=capacity,
                peak_load=0.0,
                avg_load=0.0,
                utilization_rate=0.0,
                queue_length_avg=0.0,
                queue_length_max=0,
                service_time_avg=0.0,
                wasted_capacity=capacity,
                excess_demand=0.0,
                efficiency_score=0.0
            )
        
        # Calculate metrics from history
        capacity = getattr(station, 'num_ports', 4)
        utilizations = [h['utilization'] for h in station_history]
        queues = [h.get('queued_agents', 0) for h in station_history]
        
        avg_util = np.mean(utilizations)
        peak_util = np.max(utilizations)
        
        avg_load = avg_util * capacity
        peak_load = peak_util * capacity
        
        wasted = capacity * (1 - avg_util) if avg_util < 0.8 else 0.0
        excess = np.mean([q for q in queues if q > 0]) if any(queues) else 0.0
        
        # Efficiency score (0-1)
        # Optimal is 70-80% utilization (high use but no queuing)
        if 0.7 <= avg_util <= 0.8:
            efficiency = 1.0
        elif avg_util < 0.7:
            efficiency = avg_util / 0.7
        else:
            efficiency = max(0.0, 1.0 - (avg_util - 0.8) * 2)
        
        return InfrastructureUtilization(
            resource_type='charger',
            resource_id=station_id,
            location=getattr(station, 'location', None),
            capacity=capacity,
            peak_load=peak_load,
            avg_load=avg_load,
            utilization_rate=avg_util,
            queue_length_avg=np.mean(queues),
            queue_length_max=int(np.max(queues)) if queues else 0,
            service_time_avg=45.0,  # Typical charging time
            wasted_capacity=wasted,
            excess_demand=excess,
            efficiency_score=efficiency
        )
    
    def _analyze_grid_utilization(self, infrastructure) -> InfrastructureUtilization:
        """Analyze grid performance."""
        if not self.grid_load_history:
            metrics = infrastructure.get_infrastructure_metrics()
            capacity = metrics.get('grid_capacity_mw', 1.0)
            
            return InfrastructureUtilization(
                resource_type='grid',
                resource_id='main',
                location=None,
                capacity=capacity,
                peak_load=0.0,
                avg_load=0.0,
                utilization_rate=0.0,
                queue_length_avg=0.0,
                queue_length_max=0,
                service_time_avg=0.0,
                wasted_capacity=capacity,
                excess_demand=0.0,
                efficiency_score=0.0
            )
        
        # Calculate from history
        loads = [h['load_mw'] for h in self.grid_load_history]
        utilizations = [h['utilization'] for h in self.grid_load_history]
        capacity = self.grid_load_history[0]['capacity_mw']
        
        avg_load = np.mean(loads)
        peak_load = np.max(loads)
        avg_util = np.mean(utilizations)
        
        wasted = capacity * (1 - avg_util) if avg_util < 0.7 else 0.0
        excess = max(0.0, peak_load - capacity)
        
        # Efficiency: aim for 60-80% average utilization
        if 0.6 <= avg_util <= 0.8:
            efficiency = 1.0
        elif avg_util < 0.6:
            efficiency = avg_util / 0.6
        else:
            efficiency = max(0.0, 1.0 - (avg_util - 0.8))
        
        return InfrastructureUtilization(
            resource_type='grid',
            resource_id='main',
            location=None,
            capacity=capacity,
            peak_load=peak_load,
            avg_load=avg_load,
            utilization_rate=avg_util,
            queue_length_avg=0.0,
            queue_length_max=0,
            service_time_avg=0.0,
            wasted_capacity=wasted,
            excess_demand=excess,
            efficiency_score=efficiency
        )
    
    # =========================================================================
    # Bottleneck Detection
    # =========================================================================
    
    def identify_bottlenecks(
        self,
        infrastructure,
        severity_threshold: float = 0.6
    ) -> List[Bottleneck]:
        """
        Identify infrastructure bottlenecks.
        
        Args:
            infrastructure: InfrastructureManager instance
            severity_threshold: Minimum severity to report (0-1)
        
        Returns:
            List of bottlenecks
        """
        bottlenecks = []
        
        # Analyze all infrastructure
        utilization_reports = self.analyze_infrastructure_efficiency(infrastructure)
        
        for resource_id, util in utilization_reports.items():
            # Check for overutilization
            if util.utilization_rate > 0.9:
                severity = min(1.0, (util.utilization_rate - 0.9) / 0.1)
                
                if severity >= severity_threshold:
                    bottleneck = Bottleneck(
                        location=util.location or (0.0, 0.0),
                        bottleneck_type=util.resource_type,
                        severity=severity,
                        affected_agents=int(util.queue_length_avg * 10),
                        congestion_factor=1.0 + severity,
                        recommendation=self._generate_recommendation(util)
                    )
                    bottlenecks.append(bottleneck)
            
            # Check for underutilization (wasted capacity)
            elif util.utilization_rate < 0.3 and util.capacity > 0:
                severity = (0.3 - util.utilization_rate) / 0.3
                
                if severity >= severity_threshold:
                    bottleneck = Bottleneck(
                        location=util.location or (0.0, 0.0),
                        bottleneck_type=f"{util.resource_type}_underused",
                        severity=severity,
                        affected_agents=0,
                        congestion_factor=0.0,
                        recommendation=f"Consider relocating or reducing {util.resource_type} capacity"
                    )
                    bottlenecks.append(bottleneck)
        
        self.bottlenecks = bottlenecks
        return bottlenecks
    
    def _generate_recommendation(self, util: InfrastructureUtilization) -> str:
        """Generate recommendation for bottleneck resolution."""
        if util.resource_type == 'charger':
            if util.queue_length_max > 5:
                return f"Add {int(util.queue_length_max / 2)} chargers at this location"
            else:
                return "Increase charger capacity or speed"
        
        elif util.resource_type == 'grid':
            if util.excess_demand > 0:
                return f"Increase grid capacity by {util.excess_demand:.1f} MW"
            else:
                return "Implement load balancing or time-of-use pricing"
        
        return "Review infrastructure allocation"
    
    # =========================================================================
    # Congestion Metrics
    # =========================================================================
    
    def record_congestion_event(
        self,
        step: int,
        location: Tuple[float, float],
        congestion_type: str,
        delay_minutes: float,
        affected_agents: int
    ):
        """Record a congestion event."""
        event = {
            'step': step,
            'location': location,
            'type': congestion_type,
            'delay': delay_minutes,
            'affected': affected_agents,
        }
        self.congestion_events.append(event)
    
    def calculate_congestion_metrics(self) -> Dict:
        """Calculate overall congestion statistics."""
        if not self.congestion_events:
            return {
                'total_events': 0,
                'avg_delay': 0.0,
                'peak_delay': 0.0,
                'total_affected': 0,
            }
        
        delays = [e['delay'] for e in self.congestion_events]
        affected = [e['affected'] for e in self.congestion_events]
        
        return {
            'total_events': len(self.congestion_events),
            'avg_delay': np.mean(delays),
            'median_delay': np.median(delays),
            'peak_delay': np.max(delays),
            'total_affected': sum(affected),
            'avg_affected_per_event': np.mean(affected),
        }
    
    # =========================================================================
    # Summary Reports
    # =========================================================================
    
    def generate_summary_report(self) -> Dict:
        """Generate comprehensive efficiency report."""
        return {
            'vkt': self.get_vkt_summary(),
            'infrastructure': {
                'chargers': len([h for h in self.charger_utilization_history if h.get('step', 0) == max([x.get('step', 0) for x in self.charger_utilization_history], default=0)]),
                'avg_charger_utilization': np.mean([h['utilization'] for h in self.charger_utilization_history]) if self.charger_utilization_history else 0.0,
                'peak_grid_load': np.max([h['load_mw'] for h in self.grid_load_history]) if self.grid_load_history else 0.0,
                'avg_grid_utilization': np.mean([h['utilization'] for h in self.grid_load_history]) if self.grid_load_history else 0.0,
            },
            'bottlenecks': len(self.bottlenecks),
            'congestion': self.calculate_congestion_metrics(),
        }