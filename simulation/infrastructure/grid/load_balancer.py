"""
simulation/infrastructure/grid/load_balancer.py

Smart load distribution and balancing across the grid.
Prevents grid overload through intelligent charging scheduling.
This module implements a load balancer that distributes charging load across different grid zones,
schedules flexible charging sessions, and prioritizes critical loads to maintain grid stability.

"""

from __future__ import annotations
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class LoadBalancingZone:
    """Grid zone for load balancing."""
    zone_id: str
    capacity_mw: float
    current_load_mw: float = 0.0
    priority: int = 1  # Higher = more critical
    
    def available_capacity(self) -> float:
        """Get remaining capacity."""
        return max(0, self.capacity_mw - self.current_load_mw)
    
    def utilization(self) -> float:
        """Get utilization (0-1)."""
        return self.current_load_mw / max(0.001, self.capacity_mw)


@dataclass
class ChargingRequest:
    """Request for charging session."""
    agent_id: str
    station_id: str
    required_power_kw: float
    duration_min: float
    priority: int = 0  # 0=normal, 1=high, 2=critical
    flexible: bool = True  # Can be delayed?


class LoadBalancer:
    """
    Smart load balancing for grid management.
    
    Responsibilities:
    - Distribute charging load across zones
    - Prevent grid overload
    - Schedule flexible charging
    - Prioritize critical loads
    """
    
    def __init__(self, grid_capacity_manager):
        """
        Initialize load balancer.
        
        Args:
            grid_capacity_manager: GridCapacityManager instance
        """
        self.grid = grid_capacity_manager
        
        # Load balancing zones (can be geographic or logical)
        self.zones: Dict[str, LoadBalancingZone] = {}
        
        # Pending charging requests
        self.pending_requests: List[ChargingRequest] = []
        
        # Scheduled charging sessions
        self.scheduled_sessions: List[Dict] = []
        
        # Load balancing history
        self.balance_history: List[Dict] = []
        
        logger.info("LoadBalancer initialized")
    
    def add_zone(self, zone_id: str, capacity_mw: float, priority: int = 1) -> None:
        """Add a load balancing zone."""
        zone = LoadBalancingZone(
            zone_id=zone_id,
            capacity_mw=capacity_mw,
            priority=priority
        )
        
        self.zones[zone_id] = zone
        logger.info(f"Added load balancing zone: {zone_id} ({capacity_mw} MW)")
    
    def request_charging(
        self,
        agent_id: str,
        station_id: str,
        required_power_kw: float,
        duration_min: float,
        priority: int = 0,
        flexible: bool = True
    ) -> Optional[str]:
        """
        Request charging session with load balancing.
        
        Args:
            agent_id: Agent identifier
            station_id: Desired charging station
            required_power_kw: Power requirement
            duration_min: Expected duration
            priority: 0=normal, 1=high, 2=critical
            flexible: Can be delayed/rescheduled?
        
        Returns:
            Approved zone_id or None if rejected
        """
        request = ChargingRequest(
            agent_id=agent_id,
            station_id=station_id,
            required_power_kw=required_power_kw,
            duration_min=duration_min,
            priority=priority,
            flexible=flexible
        )
        
        # Try immediate approval
        zone = self._find_available_zone(required_power_kw, priority)
        
        if zone:
            # Approve immediately
            self._approve_charging(request, zone)
            return zone
        
        elif flexible:
            # Queue for later
            self.pending_requests.append(request)
            logger.debug(f"Queued flexible charging request for {agent_id}")
            return None
        
        else:
            # Reject (critical but no capacity)
            logger.warning(f"Rejected charging request for {agent_id} (no capacity)")
            return None
    
    def _find_available_zone(
        self,
        required_power_kw: float,
        priority: int
    ) -> Optional[str]:
        """Find zone with available capacity."""
        required_mw = required_power_kw / 1000.0
        
        # Sort zones by priority (high priority first)
        sorted_zones = sorted(
            self.zones.items(),
            key=lambda x: (-x[1].priority, x[1].utilization())
        )
        
        for zone_id, zone in sorted_zones:
            available = zone.available_capacity()
            
            # Check if zone has capacity
            if available >= required_mw:
                # For high-priority requests, allow up to 95% utilization
                # For normal requests, stop at 80%
                threshold = 0.95 if priority >= 1 else 0.80
                
                if zone.utilization() < threshold:
                    return zone_id
        
        return None
    
    def _approve_charging(self, request: ChargingRequest, zone_id: str) -> None:
        """Approve and schedule charging request."""
        zone = self.zones[zone_id]
        
        # Update zone load
        required_mw = request.required_power_kw / 1000.0
        zone.current_load_mw += required_mw
        
        # Schedule session
        self.scheduled_sessions.append({
            'agent_id': request.agent_id,
            'station_id': request.station_id,
            'zone_id': zone_id,
            'power_kw': request.required_power_kw,
            'duration_min': request.duration_min,
        })
        
        logger.debug(f"Approved charging for {request.agent_id} in zone {zone_id}")
    
    def complete_charging(self, agent_id: str) -> None:
        """Mark charging session as complete and free capacity."""
        # Find session
        session = next(
            (s for s in self.scheduled_sessions if s['agent_id'] == agent_id),
            None
        )
        
        if not session:
            logger.warning(f"No session found for {agent_id}")
            return
        
        # Free capacity
        zone_id = session['zone_id']
        if zone_id in self.zones:
            zone = self.zones[zone_id]
            power_mw = session['power_kw'] / 1000.0
            zone.current_load_mw = max(0, zone.current_load_mw - power_mw)
        
        # Remove session
        self.scheduled_sessions = [
            s for s in self.scheduled_sessions
            if s['agent_id'] != agent_id
        ]
        
        logger.debug(f"Completed charging for {agent_id}")
    
    def process_pending_requests(self) -> List[Tuple[str, str]]:
        """
        Process pending flexible requests.
        
        Returns:
            List of (agent_id, zone_id) for approved requests
        """
        approved = []
        remaining = []
        
        # Sort by priority
        self.pending_requests.sort(key=lambda r: -r.priority)
        
        for request in self.pending_requests:
            zone_id = self._find_available_zone(
                request.required_power_kw,
                request.priority
            )
            
            if zone_id:
                self._approve_charging(request, zone_id)
                approved.append((request.agent_id, zone_id))
            else:
                remaining.append(request)
        
        self.pending_requests = remaining
        
        if approved:
            logger.info(f"Processed {len(approved)} pending charging requests")
        
        return approved
    
    def rebalance_load(self) -> int:
        """
        Actively rebalance load across zones.
        
        Moves flexible sessions from overloaded to underloaded zones.
        
        Returns:
            Number of sessions rebalanced
        """
        # Find overloaded and underloaded zones
        overloaded = []
        underloaded = []
        
        for zone_id, zone in self.zones.items():
            util = zone.utilization()
            
            if util > 0.85:
                overloaded.append((zone_id, zone))
            elif util < 0.50:
                underloaded.append((zone_id, zone))
        
        if not overloaded or not underloaded:
            return 0
        
        # Move sessions from overloaded to underloaded zones
        rebalanced = 0
        
        for zone_id, zone in overloaded:
            # Find sessions in this zone
            zone_sessions = [
                s for s in self.scheduled_sessions
                if s['zone_id'] == zone_id
            ]
            
            # Try to move some sessions
            for session in zone_sessions[:3]:  # Max 3 per rebalance
                # Find underloaded zone with capacity
                power_mw = session['power_kw'] / 1000.0
                
                for target_zone_id, target_zone in underloaded:
                    if target_zone.available_capacity() >= power_mw:
                        # Move session
                        zone.current_load_mw -= power_mw
                        target_zone.current_load_mw += power_mw
                        
                        session['zone_id'] = target_zone_id
                        
                        rebalanced += 1
                        logger.info(f"Rebalanced session {session['agent_id']}: {zone_id} → {target_zone_id}")
                        break
        
        return rebalanced
    
    def get_balancing_metrics(self) -> Dict:
        """Get load balancing metrics."""
        if not self.zones:
            return {'status': 'no_zones'}
        
        total_capacity = sum(z.capacity_mw for z in self.zones.values())
        total_load = sum(z.current_load_mw for z in self.zones.values())
        
        # Zone utilization variance (measure of imbalance)
        utilizations = [z.utilization() for z in self.zones.values()]
        avg_util = sum(utilizations) / len(utilizations)
        variance = sum((u - avg_util) ** 2 for u in utilizations) / len(utilizations)
        
        return {
            'total_capacity_mw': total_capacity,
            'total_load_mw': total_load,
            'overall_utilization': total_load / max(0.001, total_capacity),
            'num_zones': len(self.zones),
            'pending_requests': len(self.pending_requests),
            'active_sessions': len(self.scheduled_sessions),
            'utilization_variance': variance,
            'well_balanced': variance < 0.05,  # Low variance = balanced
        }
    
    def get_zone_status(self) -> List[Dict]:
        """Get status of all zones."""
        return [
            {
                'zone_id': zone_id,
                'capacity_mw': zone.capacity_mw,
                'current_load_mw': zone.current_load_mw,
                'utilization': zone.utilization(),
                'available_capacity_mw': zone.available_capacity(),
                'priority': zone.priority,
            }
            for zone_id, zone in self.zones.items()
        ]


def create_default_zones(
    load_balancer: LoadBalancer,
    grid_capacity_mw: float,
    num_zones: int = 4
) -> None:
    """
    Create default geographic zones for load balancing.
    
    Args:
        load_balancer: LoadBalancer instance
        grid_capacity_mw: Total grid capacity
        num_zones: Number of zones to create
    """
    capacity_per_zone = grid_capacity_mw / num_zones
    
    zone_names = ['north', 'south', 'east', 'west', 'central', 'suburban']
    
    for i in range(num_zones):
        zone_name = zone_names[i] if i < len(zone_names) else f'zone_{i+1}'
        
        load_balancer.add_zone(
            zone_id=zone_name,
            capacity_mw=capacity_per_zone,
            priority=1
        )
    
    logger.info(f"Created {num_zones} default load balancing zones")