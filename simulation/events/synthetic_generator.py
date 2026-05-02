"""
simulation/events/synthetic_generator.py

Phase 7.2: Synthetic Event Generator

Generates realistic random events during extended simulations to add
unpredictability and test agent adaptation to real-world conditions.

Events include:
- Traffic congestion (time-of-day dependent)
- Weather disruptions (seasonal patterns)
- Infrastructure failures (random)
- Policy announcements (scheduled or random)
"""

from __future__ import annotations
import random
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from enum import Enum

try:
    from utils.secure_rng import AgentRandom
    _SECURE_RNG_AVAILABLE = True
except Exception:  # pragma: no cover
    AgentRandom = None  # type: ignore
    _SECURE_RNG_AVAILABLE = False

logger = logging.getLogger(__name__)

class EventType(Enum):
    """Types of synthetic events."""
    TRAFFIC_CONGESTION = "traffic_congestion"
    WEATHER_DISRUPTION = "weather_disruption"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    POLICY_ANNOUNCEMENT = "policy_announcement"
    GRID_STRESS = "grid_stress"
    DEMAND_SURGE = "demand_surge"


class EventSeverity(Enum):
    """Severity levels for events."""
    MINOR = "minor"
    MODERATE = "moderate"
    SEVERE = "severe"
    CRITICAL = "critical"


class SyntheticEvent:
    """
    Represents a single synthetic event.
    """
    
    def __init__(
        self,
        event_type: EventType,
        severity: EventSeverity,
        duration_steps: int,
        affected_area: Optional[str] = None,
        impact_data: Optional[Dict[str, Any]] = None,
        description: str = ""
    ):
        self.event_type = event_type
        self.severity = severity
        self.duration_steps = duration_steps
        self.affected_area = affected_area
        self.impact_data = impact_data or {}
        self.description = description
        self.steps_remaining = duration_steps
    
    def is_active(self) -> bool:
        """Check if event is still active."""
        return self.steps_remaining > 0
    
    def step(self):
        """Advance event by one timestep."""
        if self.steps_remaining > 0:
            self.steps_remaining -= 1
    
    def get_impact_multiplier(self) -> float:
        """Get impact multiplier based on severity."""
        multipliers = {
            EventSeverity.MINOR: 1.1,
            EventSeverity.MODERATE: 1.3,
            EventSeverity.SEVERE: 1.6,
            EventSeverity.CRITICAL: 2.0,
        }
        return multipliers.get(self.severity, 1.0)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/storage."""
        return {
            'type': self.event_type.value,
            'severity': self.severity.value,
            'duration': self.duration_steps,
            'remaining': self.steps_remaining,
            'area': self.affected_area,
            'impact': self.impact_data,
            'description': self.description,
        }


class SyntheticEventGenerator:
    """
    Generates realistic random events during simulation.
    
    Events are:
    - Time-aware (rush hour traffic, seasonal weather)
    - Location-specific (affected areas)
    - Duration-based (last multiple timesteps)
    - Severity-varied (minor to critical)
    
    Example:
        generator = SyntheticEventGenerator(
            traffic_enabled=True,
            weather_enabled=True
        )
        
        for step in range(365):
            time_info = temporal_engine.get_time_info(step)
            new_events = generator.generate_events_for_step(step, time_info)
            
            for event in new_events:
                event_bus.publish(event)
    """
    
    def __init__(
        self,
        # Enable/disable event types
        traffic_enabled: bool = True,
        weather_enabled: bool = True,
        infrastructure_enabled: bool = True,
        policy_enabled: bool = False,
        grid_enabled: bool = True,
        
        # Event probabilities (per step)
        traffic_base_probability: float = 0.05,  # 5% per step normally
        weather_base_probability: float = 0.03,  # 3% per step
        infrastructure_failure_probability: float = 0.01,  # 1% per step
        grid_stress_probability: float = 0.02,  # 2% per step
        
        # Time-of-day multipliers
        rush_hour_traffic_multiplier: float = 6.0,  # 30% during rush hour
        
        # Seasonal multipliers
        winter_weather_multiplier: float = 4.0,  # 12% in winter
        
        # Location configuration
        affected_areas: Optional[List[str]] = None,
        
        # Random seed for reproducibility
        random_seed: Optional[int] = None,
    ):
        """
        Initialize synthetic event generator.
        
        Args:
            *_enabled: Enable/disable each event type
            *_probability: Base probability per timestep
            *_multiplier: Multipliers for time/season
            affected_areas: List of area names for location-specific events
            random_seed: Seed for reproducibility
        """
        # Feature flags
        self.traffic_enabled = traffic_enabled
        self.weather_enabled = weather_enabled
        self.infrastructure_enabled = infrastructure_enabled
        self.policy_enabled = policy_enabled
        self.grid_enabled = grid_enabled
        
        # Base probabilities
        self.traffic_base_prob = traffic_base_probability
        self.weather_base_prob = weather_base_probability
        self.infra_fail_prob = infrastructure_failure_probability
        self.grid_stress_prob = grid_stress_probability
        
        # Multipliers
        self.rush_hour_multiplier = rush_hour_traffic_multiplier
        self.winter_multiplier = winter_weather_multiplier
        
        # Locations
        self.affected_areas = affected_areas or [
            "city_center",
            "north_edinburgh",
            "south_edinburgh",
            "west_edinburgh",
            "east_edinburgh",
            "leith",
            "portobello",
            "corstorphine",
        ]
        
        # Active events tracker
        self.active_events: List[SyntheticEvent] = []
        
        # Event history for visualization
        self._event_history: List[SyntheticEvent] = []
        
        # Per-generator RNG (do NOT seed global random)
        if _SECURE_RNG_AVAILABLE and AgentRandom is not None:
            self.rng = AgentRandom(random_seed)
        else:
            self.rng = random.Random(random_seed)
                
        logger.info("🎲 Synthetic Event Generator initialized")
        logger.info(f"   Traffic: {'enabled' if traffic_enabled else 'disabled'}")
        logger.info(f"   Weather: {'enabled' if weather_enabled else 'disabled'}")
        logger.info(f"   Infrastructure: {'enabled' if infrastructure_enabled else 'disabled'}")
    
    def generate_events_for_step(
        self,
        step: int,
        time_info: Dict[str, Any]
    ) -> List[SyntheticEvent]:
        """
        Generate events for current timestep.
        
        Args:
            step: Current simulation step
            time_info: Time information from temporal engine
            
        Returns:
            List of newly generated events
        """
        new_events = []
        
        # Update existing events
        for event in self.active_events:
            event.step()
        
        # Remove expired events
        self.active_events = [e for e in self.active_events if e.is_active()]
        
        # Generate new events based on conditions
        
        # 1. Traffic congestion (time-dependent)
        if self.traffic_enabled:
            traffic_event = self._maybe_generate_traffic(time_info)
            if traffic_event:
                new_events.append(traffic_event)
                self.active_events.append(traffic_event)
        
        # 2. Weather disruptions (season-dependent)
        if self.weather_enabled:
            weather_event = self._maybe_generate_weather(time_info)
            if weather_event:
                new_events.append(weather_event)
                self.active_events.append(weather_event)
        
        # 3. Infrastructure failures (random)
        if self.infrastructure_enabled:
            infra_event = self._maybe_generate_infrastructure_failure(time_info)
            if infra_event:
                new_events.append(infra_event)
                self.active_events.append(infra_event)
        
        # 4. Grid stress (load-dependent - simplified for now)
        if self.grid_enabled:
            grid_event = self._maybe_generate_grid_stress(time_info)
            if grid_event:
                new_events.append(grid_event)
                self.active_events.append(grid_event)
        
        # Store events in history with start_step for visualization (Phase 7.2)
        for event in new_events:
            event.start_step = step  # Add start_step attribute for UI overlay
            self._event_history.append(event)
        
        return new_events
    
    def _maybe_generate_traffic(self, time_info: Dict[str, Any]) -> Optional[SyntheticEvent]:
        """Generate traffic congestion event."""
        # Calculate probability based on time of day
        base_prob = self.traffic_base_prob
        
        # Much higher during rush hour
        if time_info.get('is_rush_hour', False):
            prob = base_prob * self.rush_hour_multiplier
        else:
            prob = base_prob
        
        # Also higher on weekdays
        if time_info.get('is_weekday', False):
            prob *= 1.5
        
        # Roll the dice
        if self.rng.random() < prob:
            severity = self.rng.choice([
                EventSeverity.MINOR,
                EventSeverity.MINOR,  # Weight toward minor
                EventSeverity.MODERATE,
                EventSeverity.MODERATE,
                EventSeverity.SEVERE,
            ])
            
            # Duration depends on severity (in steps)
            if severity == EventSeverity.MINOR:
                duration = self.rng.randint(1, 3)
            elif severity == EventSeverity.MODERATE:
                duration = self.rng.randint(2, 6)
            else:  # SEVERE
                duration = self.rng.randint(4, 12)
            
            affected_area = self.rng.choice(self.affected_areas)
            
            # Impact data
            if severity == EventSeverity.MINOR:
                delay_multiplier = 1.2  # 20% delays
            elif severity == EventSeverity.MODERATE:
                delay_multiplier = 1.5  # 50% delays
            else:
                delay_multiplier = 2.0  # 100% delays
            
            description = f"{severity.value.capitalize()} traffic congestion in {affected_area}"
            
            logger.info(f"🚗 Generated traffic event: {description} (duration: {duration} steps)")
            
            return SyntheticEvent(
                event_type=EventType.TRAFFIC_CONGESTION,
                severity=severity,
                duration_steps=duration,
                affected_area=affected_area,
                impact_data={
                    'delay_multiplier': delay_multiplier,
                    'affected_routes': self.rng.randint(3, 15),
                },
                description=description
            )
        
        return None
    
    def _maybe_generate_weather(self, time_info: Dict[str, Any]) -> Optional[SyntheticEvent]:
        """Generate weather disruption event."""
        base_prob = self.weather_base_prob
        
        # Much higher in winter
        season = time_info.get('season', 'spring')
        if season == 'winter':
            prob = base_prob * self.winter_multiplier
            weather_types = ['snow', 'ice', 'heavy_rain', 'wind']
            weights = [0.3, 0.2, 0.3, 0.2]
        elif season == 'fall':
            prob = base_prob * 2.0
            weather_types = ['heavy_rain', 'wind', 'fog']
            weights = [0.5, 0.3, 0.2]
        elif season == 'spring':
            prob = base_prob * 1.5
            weather_types = ['rain', 'wind']
            weights = [0.7, 0.3]
        else:  # summer
            prob = base_prob * 0.5
            weather_types = ['rain', 'wind']
            weights = [0.6, 0.4]
        
        if self.rng.random() < prob:
            weather_type = self.rng.choices(weather_types, weights=weights)[0]
            
            # Severity varies
            severity = self.rng.choice([
                EventSeverity.MINOR,
                EventSeverity.MODERATE,
                EventSeverity.MODERATE,
                EventSeverity.SEVERE,
            ])
            
            # Duration (weather lasts longer)
            if severity == EventSeverity.MINOR:
                duration = self.rng.randint(2, 6)
            elif severity == EventSeverity.MODERATE:
                duration = self.rng.randint(4, 12)
            else:
                duration = self.rng.randint(8, 24)
            
            # Impact varies by weather type and severity
            impact_data = {'weather_type': weather_type}
            
            if weather_type in ['snow', 'ice']:
                impact_data['ev_range_reduction'] = 0.15 if severity == EventSeverity.MINOR else 0.30
                impact_data['speed_reduction'] = 0.20 if severity == EventSeverity.MINOR else 0.40
            elif weather_type == 'heavy_rain':
                impact_data['ev_range_reduction'] = 0.05
                impact_data['speed_reduction'] = 0.10 if severity == EventSeverity.MINOR else 0.25
            elif weather_type == 'wind':
                impact_data['ev_range_reduction'] = 0.10
            
            description = f"{severity.value.capitalize()} {weather_type} affecting area"
            
            logger.info(f"🌧️ Generated weather event: {description} (duration: {duration} steps)")
            
            return SyntheticEvent(
                event_type=EventType.WEATHER_DISRUPTION,
                severity=severity,
                duration_steps=duration,
                affected_area="region_wide",
                impact_data=impact_data,
                description=description
            )
        
        return None
    
    def _maybe_generate_infrastructure_failure(self, time_info: Dict[str, Any]) -> Optional[SyntheticEvent]:
        """Generate infrastructure failure event."""
        if self.rng.random() < self.infra_fail_prob:
            severity = self.rng.choice([
                EventSeverity.MINOR,
                EventSeverity.MINOR,
                EventSeverity.MODERATE,
            ])
            
            # Duration (infrastructure repairs take time)
            if severity == EventSeverity.MINOR:
                duration = self.rng .randint(3, 8)
            else:
                duration = self.rng.randint(8, 24)
            
            affected_area = self.rng.choice(self.affected_areas)
            
            # What failed?
            failure_type = self.rng.choice([
                'charger_outage',
                'grid_section_down',
                'depot_maintenance',
            ])
            
            impact_data = {'failure_type': failure_type}
            
            if failure_type == 'charger_outage':
                num_chargers = self.rng.randint(1, 10) if severity == EventSeverity.MINOR else self.rng.randint(5, 25)
                impact_data['chargers_affected'] = num_chargers
                description = f"{num_chargers} chargers offline in {affected_area}"
            elif failure_type == 'grid_section_down':
                impact_data['capacity_reduction'] = 0.10 if severity == EventSeverity.MINOR else 0.25
                description = f"Grid section reduced capacity in {affected_area}"
            else:  # depot_maintenance
                impact_data['depot_unavailable'] = True
                description = f"Depot maintenance in {affected_area}"
            
            logger.info(f"🔌 Generated infrastructure event: {description} (duration: {duration} steps)")
            
            return SyntheticEvent(
                event_type=EventType.INFRASTRUCTURE_FAILURE,
                severity=severity,
                duration_steps=duration,
                affected_area=affected_area,
                impact_data=impact_data,
                description=description
            )
        
        return None
    
    def _maybe_generate_grid_stress(self, time_info: Dict[str, Any]) -> Optional[SyntheticEvent]:
        """Generate grid stress event (high demand)."""
        # Higher during peak hours
        hour = time_info.get('hour', 12)
        
        prob = self.grid_stress_prob
        if 17 <= hour <= 20:  # Evening peak
            prob *= 3.0
        elif 7 <= hour <= 9:  # Morning peak
            prob *= 2.0
        
        # Higher in winter (heating) and summer (cooling)
        season = time_info.get('season', 'spring')
        if season in ['winter', 'summer']:
            prob *= 1.5
        
        if self.rng.random() < prob:
            severity = self.rng .choice([
                EventSeverity.MINOR,
                EventSeverity.MODERATE,
                EventSeverity.SEVERE,
            ])
            
            duration = random.randint(1, 4)
            
            impact_data = {
                'charging_rate_reduction': 0.10 if severity == EventSeverity.MINOR else 0.30,
                'peak_pricing_active': True,
            }
            
            description = f"{severity.value.capitalize()} grid stress - reduce charging"
            
            logger.info(f"⚡ Generated grid stress event: {description} (duration: {duration} steps)")
            
            return SyntheticEvent(
                event_type=EventType.GRID_STRESS,
                severity=severity,
                duration_steps=duration,
                affected_area="region_wide",
                impact_data=impact_data,
                description=description
            )
        
        return None
    
    def get_active_events(self) -> List[SyntheticEvent]:
        """Get list of currently active events."""
        return list(self.active_events)
    
    def get_events_by_type(self, event_type: EventType) -> List[SyntheticEvent]:
        """Get active events of specific type."""
        return [e for e in self.active_events if e.event_type == event_type]
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of event generator state."""
        type_counts = {}
        for event in self.active_events:
            type_name = event.event_type.value
            type_counts[type_name] = type_counts.get(type_name, 0) + 1
        
        return {
            'active_events': len(self.active_events),
            'by_type': type_counts,
            'traffic_enabled': self.traffic_enabled,
            'weather_enabled': self.weather_enabled,
            'infrastructure_enabled': self.infrastructure_enabled,
        }


# Helper function for quick setup
def create_event_generator_from_config(config) -> Optional[SyntheticEventGenerator]:
    """
    Create SyntheticEventGenerator from SimulationConfig.
    
    Args:
        config: SimulationConfig instance
        
    Returns:
        SyntheticEventGenerator if enabled, None otherwise
    """
    # Check if synthetic events are enabled
    if not hasattr(config, 'enable_synthetic_events') or not config.enable_synthetic_events:
        return None
    
    # Get configuration
    traffic_enabled = getattr(config, 'synthetic_traffic_events', True)
    weather_enabled = getattr(config, 'synthetic_weather_events', True)
    infra_enabled = getattr(config, 'synthetic_infrastructure_events', True)
    
    generator = SyntheticEventGenerator(
        traffic_enabled=traffic_enabled,
        weather_enabled=weather_enabled,
        infrastructure_enabled=infra_enabled,
    )
    
    return generator