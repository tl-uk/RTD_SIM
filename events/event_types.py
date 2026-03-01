"""
events/event_types.py

Core event type definitions for RTD_SIM real-time digital twin.
All events include spatial metadata for radius-based perception.

Event Types:
- PolicyChange: Policy parameter updates
- InfrastructureFailure: Charging station or grid failures
- WeatherEvent: Weather perturbations affecting travel
- AgentModeSwitch: Agent changes transportation mode
- GridStressEvent: Grid utilization threshold crossed
- TrafficEvent: Congestion or road closures
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum
import uuid


class EventType(Enum):
    """Event type enumeration."""
    POLICY_CHANGE = "policy_change"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    WEATHER_EVENT = "weather_event"
    AGENT_MODE_SWITCH = "agent_mode_switch"
    GRID_STRESS = "grid_stress"
    TRAFFIC_EVENT = "traffic_event"
    THRESHOLD_CROSSED = "threshold_crossed"


class EventPriority(Enum):
    """Event priority for processing order."""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class SpatialMetadata:
    """
    Spatial information for event perception.
    Events affect agents within perception radius.
    """
    latitude: float
    longitude: float
    radius_km: float = 5.0  # Default perception radius
    affected_region: Optional[str] = None  # e.g., "Edinburgh City"
    
    def __post_init__(self):
        """Validate spatial data."""
        if not -90 <= self.latitude <= 90:
            raise ValueError(f"Invalid latitude: {self.latitude}")
        if not -180 <= self.longitude <= 180:
            raise ValueError(f"Invalid longitude: {self.longitude}")
        if self.radius_km < 0:
            raise ValueError(f"Invalid radius: {self.radius_km}")


@dataclass
class BaseEvent:
    """
    Base class for all events in RTD_SIM.
    
    All events include:
    - Unique ID for tracking
    - Timestamp for ordering
    - Spatial metadata for perception
    - Priority for processing order
    - Custom payload for event-specific data
    """
    event_type: EventType
    timestamp: datetime = field(default_factory=datetime.now)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    spatial: Optional[SpatialMetadata] = None
    priority: EventPriority = EventPriority.NORMAL
    payload: Dict[str, Any] = field(default_factory=dict)
    source: Optional[str] = None  # Source of event (e.g., "mqtt_sensor", "policy_engine")
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize event to dictionary for pub/sub."""
        return {
            'event_id': self.event_id,
            'event_type': self.event_type.value,
            'timestamp': self.timestamp.isoformat(),
            'spatial': {
                'lat': self.spatial.latitude,
                'lon': self.spatial.longitude,
                'radius_km': self.spatial.radius_km,
                'region': self.spatial.affected_region
            } if self.spatial else None,
            'priority': self.priority.value,
            'payload': self.payload,
            'source': self.source
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BaseEvent':
        """Deserialize event from dictionary."""
        spatial = None
        if data.get('spatial'):
            spatial = SpatialMetadata(
                latitude=data['spatial']['lat'],
                longitude=data['spatial']['lon'],
                radius_km=data['spatial'].get('radius_km', 5.0),
                affected_region=data['spatial'].get('region')
            )
        
        return cls(
            event_type=EventType(data['event_type']),
            timestamp=datetime.fromisoformat(data['timestamp']),
            event_id=data['event_id'],
            spatial=spatial,
            priority=EventPriority(data['priority']),
            payload=data['payload'],
            source=data.get('source')
        )


# ==================================================================
# SPECIFIC EVENT TYPES
# ==================================================================

@dataclass
class PolicyChangeEvent(BaseEvent):
    """
    Policy parameter change event.
    
    Examples:
    - Carbon tax increase: £50 → £100/tonne
    - EV subsidy change: £5000 → £7000
    - Congestion charge: £12 → £15/day
    """
    
    def __init__(
        self,
        parameter: str,
        old_value: float,
        new_value: float,
        lat: float = 0.0,
        lon: float = 0.0,
        radius_km: float = 100.0,  # Policies often have wide reach
        **kwargs
    ):
        super().__init__(
            event_type=EventType.POLICY_CHANGE,
            spatial=SpatialMetadata(lat, lon, radius_km),
            payload={
                'parameter': parameter,
                'old_value': old_value,
                'new_value': new_value,
                'delta': new_value - old_value,
                'delta_pct': ((new_value - old_value) / old_value * 100) if old_value != 0 else 0
            },
            **kwargs
        )


@dataclass
class InfrastructureFailureEvent(BaseEvent):
    """
    Infrastructure component failure.
    
    Examples:
    - Charging station offline
    - Grid substation failure
    - Road closure
    """
    
    def __init__(
        self,
        infrastructure_type: str,  # 'charging_station', 'grid', 'road'
        infrastructure_id: str,
        failure_reason: str,
        lat: float,
        lon: float,
        radius_km: float = 5.0,
        estimated_duration_min: Optional[int] = None,
        **kwargs
    ):
        super().__init__(
            event_type=EventType.INFRASTRUCTURE_FAILURE,
            spatial=SpatialMetadata(lat, lon, radius_km),
            priority=EventPriority.HIGH,
            payload={
                'infrastructure_type': infrastructure_type,
                'infrastructure_id': infrastructure_id,
                'failure_reason': failure_reason,
                'estimated_duration_min': estimated_duration_min,
                'severity': 'critical' if estimated_duration_min and estimated_duration_min > 60 else 'moderate'
            },
            **kwargs
        )


@dataclass
class WeatherEvent(BaseEvent):
    """
    Weather perturbation affecting travel.
    
    Examples:
    - Heavy rain (reduce speeds, increase energy consumption)
    - Snow (road closures, mode unavailability)
    - Heat wave (A/C energy increase)
    """
    
    def __init__(
        self,
        weather_type: str,  # 'rain', 'snow', 'storm', 'heat', 'fog'
        severity: int,  # 0-10 scale
        lat: float,
        lon: float,
        radius_km: float = 10.0,
        duration_min: Optional[int] = None,
        impacts: Optional[List[str]] = None,
        **kwargs
    ):
        super().__init__(
            event_type=EventType.WEATHER_EVENT,
            spatial=SpatialMetadata(lat, lon, radius_km),
            priority=EventPriority.HIGH if severity >= 7 else EventPriority.NORMAL,
            payload={
                'weather_type': weather_type,
                'severity': severity,
                'duration_min': duration_min,
                'impacts': impacts or [],
                'speed_reduction_factor': 1.0 - (severity * 0.05),  # 5% per severity level
                'energy_increase_factor': 1.0 + (severity * 0.03)   # 3% per severity level
            },
            **kwargs
        )


@dataclass
class AgentModeSwitchEvent(BaseEvent):
    """
    Agent switches transportation mode.
    Aggregated for System Dynamics updates.
    """
    
    def __init__(
        self,
        agent_id: str,
        old_mode: str,
        new_mode: str,
        reason: str,
        lat: float,
        lon: float,
        **kwargs
    ):
        super().__init__(
            event_type=EventType.AGENT_MODE_SWITCH,
            spatial=SpatialMetadata(lat, lon, radius_km=0.1),  # Small radius
            priority=EventPriority.LOW,
            payload={
                'agent_id': agent_id,
                'old_mode': old_mode,
                'new_mode': new_mode,
                'reason': reason,
                'is_ev_switch': ('electric' in new_mode.lower() or 'ev' in new_mode.lower())
            },
            **kwargs
        )


@dataclass
class GridStressEvent(BaseEvent):
    """
    Grid utilization crosses threshold.
    Triggers emergency mode or load shedding.
    """
    
    def __init__(
        self,
        grid_utilization: float,
        threshold: float,
        load_mw: float,
        capacity_mw: float,
        crossed_direction: str,  # 'up' or 'down'
        lat: float = 0.0,
        lon: float = 0.0,
        radius_km: float = 50.0,  # Grid events have wide impact
        **kwargs
    ):
        super().__init__(
            event_type=EventType.GRID_STRESS,
            spatial=SpatialMetadata(lat, lon, radius_km),
            priority=EventPriority.CRITICAL if grid_utilization > 0.95 else EventPriority.HIGH,
            payload={
                'grid_utilization': grid_utilization,
                'threshold': threshold,
                'load_mw': load_mw,
                'capacity_mw': capacity_mw,
                'headroom_mw': capacity_mw - load_mw,
                'crossed_direction': crossed_direction,
                'emergency_mode': grid_utilization > 0.90
            },
            **kwargs
        )


@dataclass
class TrafficEvent(BaseEvent):
    """
    Traffic congestion or road closure.
    """
    
    def __init__(
        self,
        traffic_type: str,  # 'congestion', 'accident', 'closure'
        affected_roads: List[str],
        lat: float,
        lon: float,
        radius_km: float = 3.0,
        delay_factor: float = 1.5,  # Travel time multiplier
        **kwargs
    ):
        super().__init__(
            event_type=EventType.TRAFFIC_EVENT,
            spatial=SpatialMetadata(lat, lon, radius_km),
            priority=EventPriority.HIGH if traffic_type == 'closure' else EventPriority.NORMAL,
            payload={
                'traffic_type': traffic_type,
                'affected_roads': affected_roads,
                'delay_factor': delay_factor,
                'severity': 'high' if delay_factor > 2.0 else 'moderate' if delay_factor > 1.3 else 'low'
            },
            **kwargs
        )


# ==================================================================
# EVENT FACTORY
# ==================================================================

class EventFactory:
    """Factory for creating events from various sources."""
    
    @staticmethod
    def create_from_slider(
        slider_name: str,
        old_value: float,
        new_value: float,
        lat: float = 0.0,
        lon: float = 0.0
    ) -> BaseEvent:
        """
        Create event from UI slider change.
        Maps slider names to appropriate event types.
        """
        
        # Policy sliders
        if slider_name in ['carbon_tax', 'ev_subsidy', 'congestion_charge']:
            return PolicyChangeEvent(
                parameter=slider_name,
                old_value=old_value,
                new_value=new_value,
                lat=lat,
                lon=lon,
                source='control_panel_slider'
            )
        
        # Environmental sliders
        elif slider_name == 'weather_severity':
            return WeatherEvent(
                weather_type='general',
                severity=int(new_value),
                lat=lat,
                lon=lon,
                source='control_panel_slider'
            )
        
        # Grid sliders
        elif slider_name == 'grid_capacity':
            # Note: This would typically trigger through SD monitoring
            # But can be injected directly for testing
            return BaseEvent(
                event_type=EventType.POLICY_CHANGE,
                spatial=SpatialMetadata(lat, lon, radius_km=100.0),
                payload={
                    'parameter': 'grid_capacity_mw',
                    'old_value': old_value,
                    'new_value': new_value
                },
                source='control_panel_slider'
            )
        
        else:
            # Generic event for unknown sliders
            return BaseEvent(
                event_type=EventType.POLICY_CHANGE,
                spatial=SpatialMetadata(lat, lon, radius_km=10.0),
                payload={
                    'parameter': slider_name,
                    'old_value': old_value,
                    'new_value': new_value
                },
                source='control_panel_slider'
            )
    
    @staticmethod
    def create_from_mqtt(
        topic: str,
        payload: Dict[str, Any]
    ) -> Optional[BaseEvent]:
        """
        Create event from MQTT message.
        To be implemented in Phase 8.
        """
        # Placeholder for future MQTT integration
        pass


# ==================================================================
# EXAMPLE USAGE
# ==================================================================

if __name__ == "__main__":
    # Example 1: Policy change
    policy_event = PolicyChangeEvent(
        parameter='carbon_tax',
        old_value=50.0,
        new_value=100.0,
        lat=55.9533,  # Edinburgh
        lon=-3.1883,
        radius_km=50.0
    )
    print("Policy Event:", policy_event.to_dict())
    
    # Example 2: Infrastructure failure
    failure_event = InfrastructureFailureEvent(
        infrastructure_type='charging_station',
        infrastructure_id='CS_123',
        failure_reason='power_outage',
        lat=55.9533,
        lon=-3.1883,
        radius_km=5.0,
        estimated_duration_min=120
    )
    print("\nFailure Event:", failure_event.to_dict())
    
    # Example 3: Weather event
    weather_event = WeatherEvent(
        weather_type='storm',
        severity=8,
        lat=55.9533,
        lon=-3.1883,
        radius_km=20.0,
        duration_min=180,
        impacts=['reduced_visibility', 'road_flooding']
    )
    print("\nWeather Event:", weather_event.to_dict())