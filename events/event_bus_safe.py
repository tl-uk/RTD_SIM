"""
events/event_bus_safe.py

Safe event bus wrapper with automatic fallback.
Ensures RTD_SIM works with or without Redis.

Fallback hierarchy:
1. Redis-based event bus (multi-process, full features)
2. In-memory event bus (single-process, spatial index if available)
3. Null event bus (no-op, zero impact)
"""

import logging
from typing import Optional, Callable, Any, Dict, List
from .event_types import BaseEvent, EventType, EventPriority

logger = logging.getLogger(__name__)


class SafeEventBus:
    """
    Event bus wrapper with automatic fallback.
    
    Usage:
        bus = SafeEventBus()  # Automatically chooses best available backend
        
        if bus.is_available():
            bus.publish(event)
            bus.subscribe(EventType.POLICY_CHANGE, callback)
    
    Modes:
    - 'redis': Full features (multi-process, spatial index)
    - 'memory': In-process only (still has spatial index if rtree available)
    - 'null': Disabled (all operations are no-ops)
    """
    
    def __init__(
        self,
        enable_redis: bool = True,
        redis_host: str = 'localhost',
        redis_port: int = 6379,
        redis_db: int = 0
    ):
        """
        Initialize safe event bus with automatic fallback.
        
        Args:
            enable_redis: Try to use Redis (default True)
            redis_host: Redis host if enabled
            redis_port: Redis port if enabled
            redis_db: Redis database number if enabled
        """
        self.backend = None
        self.mode = 'none'
        
        # Try backends in order
        if enable_redis:
            self._try_redis_backend(redis_host, redis_port, redis_db)
        
        if self.backend is None:
            self._try_memory_backend()
        
        if self.backend is None:
            self._use_null_backend()
    
    def _try_redis_backend(self, host: str, port: int, db: int):
        """Attempt to initialize Redis-based event bus."""
        try:
            from .event_bus import SpatialEventBus
            
            self.backend = SpatialEventBus(host=host, port=port, db=db)
            
            # Verify Redis is actually working
            if self.backend.redis_client is not None:
                self.mode = 'redis'
                logger.info("✅ Event bus: Using Redis (full features)")
                logger.info(f"   - Multi-process pub/sub: enabled")
                logger.info(f"   - Spatial filtering: enabled")
                logger.info(f"   - Priority channels: enabled")
            else:
                # Redis connection failed in event_bus.__init__
                self.backend = None
                logger.warning("⚠️ Redis connection failed, trying fallback...")
                
        except ImportError as e:
            logger.debug(f"Redis event bus module not available: {e}")
            self.backend = None
        except Exception as e:
            logger.warning(f"Redis event bus initialization failed: {e}")
            self.backend = None
    
    def _try_memory_backend(self):
        """Attempt to initialize in-memory event bus."""
        try:
            self.backend = InMemoryEventBus()
            self.mode = 'memory'
            logger.info("✅ Event bus: Using in-memory (single-process)")
            logger.info(f"   - Spatial filtering: {self.backend.has_spatial}")
            logger.info(f"   - Real-time callbacks: enabled")
        except Exception as e:
            logger.warning(f"In-memory event bus initialization failed: {e}")
            self.backend = None
    
    def _use_null_backend(self):
        """Use null event bus (all operations are no-ops)."""
        self.backend = NullEventBus()
        self.mode = 'null'
        logger.info("⚠️ Event bus: Disabled (simulation will work normally)")
        logger.info("   Note: To enable events, ensure Redis is running")
    
    # ========================================
    # Public API (safe - never crashes)
    # ========================================
    
    def publish(self, event: BaseEvent) -> bool:
        """
        Publish event (safe - never fails).
        
        Args:
            event: Event to publish
        
        Returns:
            True if published successfully, False otherwise
        """
        try:
            return self.backend.publish(event)
        except Exception as e:
            logger.debug(f"Event publish failed (non-critical): {e}")
            return False
    
    def publish_synthetic_event(self, synthetic_event) -> bool:
        """
        Publish a synthetic generator event to the bus (safe - never fails).

        Maps synthetic EventType values to the correct BaseEvent subclass from
        events.event_types, then delegates to publish().

        Args:
            synthetic_event: SyntheticEvent from simulation.events.synthetic_generator
        Returns:
            True if published, False otherwise
        """
        try:
            from .event_types import (
                BaseEvent, EventType as BusEventType,
                SpatialMetadata, WeatherEvent,
                InfrastructureFailureEvent, TrafficEvent, GridStressEvent
            )

            event_type_value = getattr(synthetic_event.event_type, 'value',
                                       str(synthetic_event.event_type))
            raw = synthetic_event.to_dict() if hasattr(synthetic_event, 'to_dict') else {}
            impact = getattr(synthetic_event, 'impact_data', {})
            lat = raw.get('lat', 55.9533)
            lon = raw.get('lon', -3.1883)
            duration = getattr(synthetic_event, 'duration_steps', None)

            if event_type_value == 'weather_disruption':
                base_event = WeatherEvent(
                    weather_type=impact.get('weather_type', 'general'),
                    severity=int(impact.get('severity', 5)),
                    lat=lat, lon=lon, radius_km=10.0,
                    duration_min=duration,
                    impacts=impact.get('impacts', []),
                    source='synthetic_event_generator'
                )
            elif event_type_value == 'infrastructure_failure':
                base_event = InfrastructureFailureEvent(
                    infrastructure_type=impact.get('infrastructure_type', 'charging_station'),
                    infrastructure_id=impact.get('infrastructure_id', 'unknown'),
                    failure_reason=impact.get('failure_reason', 'synthetic_failure'),
                    lat=lat, lon=lon, radius_km=5.0,
                    estimated_duration_min=duration,
                    source='synthetic_event_generator'
                )
            elif event_type_value == 'grid_stress':
                base_event = GridStressEvent(
                    grid_utilization=impact.get('grid_utilization', 0.85),
                    threshold=impact.get('threshold', 0.8),
                    load_mw=impact.get('load_mw', 850.0),
                    capacity_mw=impact.get('capacity_mw', 1000.0),
                    crossed_direction=impact.get('direction', 'up'),
                    source='synthetic_event_generator'
                )
            else:
                # traffic_congestion and any unknown type -> generic TrafficEvent shell
                base_event = BaseEvent(
                    event_type=BusEventType.TRAFFIC_EVENT,
                    payload=raw,
                    source='synthetic_event_generator'
                )

            return self.publish(base_event)

        except Exception as e:
            logger.debug(f"publish_synthetic_event failed (non-critical): {e}")
            return False

    def subscribe(
        self,
        event_type: EventType,
        callback: Callable[[BaseEvent], None],
        priority: Optional[EventPriority] = None
    ):
        """
        Subscribe to event type (safe).
        
        Args:
            event_type: Type of events to receive
            callback: Function to call when event received
            priority: Optional priority filter
        """
        try:
            return self.backend.subscribe(event_type, callback, priority)
        except Exception as e:
            logger.debug(f"Event subscribe failed (non-critical): {e}")
    
    def subscribe_spatial(
        self,
        agent_id: str,
        event_type: EventType,
        callback: Callable[[BaseEvent], None]
    ):
        """
        Subscribe with spatial filtering (safe).
        
        Args:
            agent_id: Agent identifier
            event_type: Type of events to receive
            callback: Function to call when relevant event received
        """
        try:
            return self.backend.subscribe_spatial(agent_id, event_type, callback)
        except Exception as e:
            logger.debug(f"Spatial subscribe failed (non-critical): {e}")
    
    def register_agent(
        self,
        agent_id: str,
        lat: float,
        lon: float,
        perception_radius_km: float = 5.0,
        **metadata
    ):
        """
        Register agent location for spatial filtering (safe).
        
        Args:
            agent_id: Unique agent identifier
            lat: Latitude
            lon: Longitude
            perception_radius_km: How far agent can perceive events
            **metadata: Additional agent metadata
        """
        try:
            return self.backend.register_agent(
                agent_id, lat, lon,
                perception_radius_km=perception_radius_km,
                **metadata
            )
        except Exception as e:
            logger.debug(f"Agent registration failed (non-critical): {e}")
    
    def update_agent_location(self, agent_id: str, lat: float, lon: float):
        """
        Update agent location (safe).
        
        Args:
            agent_id: Agent to update
            lat: New latitude
            lon: New longitude
        """
        try:
            return self.backend.update_agent_location(agent_id, lat, lon)
        except Exception as e:
            logger.debug(f"Location update failed (non-critical): {e}")
    
    def unregister_agent(self, agent_id: str):
        """
        Remove agent from spatial index (safe).
        
        Args:
            agent_id: Agent to remove
        """
        try:
            return self.backend.unregister_agent(agent_id)
        except Exception as e:
            logger.debug(f"Agent unregister failed (non-critical): {e}")
    
    def start_listening(self):
        """Start event listener (safe)."""
        try:
            return self.backend.start_listening()
        except Exception as e:
            logger.debug(f"Start listening failed (non-critical): {e}")
    
    def stop_listening(self):
        """Stop event listener (safe)."""
        try:
            return self.backend.stop_listening()
        except Exception as e:
            logger.debug(f"Stop listening failed (non-critical): {e}")
    
    def close(self):
        """Close event bus and cleanup (safe)."""
        try:
            return self.backend.close()
        except Exception as e:
            logger.debug(f"Close failed (non-critical): {e}")
    
    def is_available(self) -> bool:
        """
        Check if event bus is available and working.
        
        Returns:
            True if events can be published/received, False if disabled
        """
        return self.mode in ['redis', 'memory']
    
    def get_mode(self) -> str:
        """
        Get current backend mode.
        
        Returns:
            'redis', 'memory', or 'null'
        """
        return self.mode
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get event bus statistics (safe).
        
        Returns:
            Dictionary with stats (published, received, mode, etc.)
        """
        try:
            stats = self.backend.get_statistics()
            stats['mode'] = self.mode
            return stats
        except Exception as e:
            logger.debug(f"Get statistics failed: {e}")
            return {'mode': self.mode, 'available': False}


# ========================================
# In-Memory Event Bus (Tier 2 Fallback)
# ========================================

class InMemoryEventBus:
    """
    In-memory event bus (no Redis, same process only).
    Still uses spatial index if rtree is available.
    """
    
    def __init__(self):
        """Initialize in-memory event bus."""
        self.callbacks: Dict[EventType, List[Callable]] = {}
        self.spatial_callbacks: Dict[EventType, Dict[str, Callable]] = {}
        self.events_published = 0
        self.events_received = 0
        
        # Try to use spatial index for O(log N) queries
        self.spatial_index = None
        self.has_spatial = False
        
        try:
            from .spatial_index import SpatialIndex
            self.spatial_index = SpatialIndex()
            self.has_spatial = True
            logger.debug("In-memory bus: Using spatial index (O(log N) queries)")
        except Exception as e:
            logger.debug(f"Spatial index unavailable (using O(N) brute force): {e}")
    
    def publish(self, event: BaseEvent) -> bool:
        """Publish to in-memory subscribers."""
        event_type = event.event_type
        
        # Call regular subscribers
        if event_type in self.callbacks:
            for callback in self.callbacks[event_type]:
                try:
                    callback(event)
                    self.events_received += 1
                except Exception as e:
                    logger.error(f"Callback error: {e}")
        
        # Call spatial subscribers (with filtering)
        if event_type in self.spatial_callbacks and event.spatial:
            if self.has_spatial:
                # Use spatial index for efficient lookup
                nearby = self.spatial_index.query_radius(
                    event.spatial.latitude,
                    event.spatial.longitude,
                    event.spatial.radius_km
                )
                
                for obj in nearby:
                    agent_id = obj.object_id
                    if agent_id in self.spatial_callbacks[event_type]:
                        try:
                            self.spatial_callbacks[event_type][agent_id](event)
                            self.events_received += 1
                        except Exception as e:
                            logger.error(f"Spatial callback error: {e}")
            else:
                # Fallback: call all spatial subscribers (no filtering)
                for agent_id, callback in self.spatial_callbacks[event_type].items():
                    try:
                        callback(event)
                        self.events_received += 1
                    except Exception as e:
                        logger.error(f"Spatial callback error: {e}")
        
        self.events_published += 1
        return True
    
    def subscribe(
        self,
        event_type: EventType,
        callback: Callable,
        priority: Optional[EventPriority] = None
    ):
        """Subscribe to event type."""
        if event_type not in self.callbacks:
            self.callbacks[event_type] = []
        self.callbacks[event_type].append(callback)
    
    def subscribe_spatial(
        self,
        agent_id: str,
        event_type: EventType,
        callback: Callable
    ):
        """Subscribe with spatial filtering."""
        if event_type not in self.spatial_callbacks:
            self.spatial_callbacks[event_type] = {}
        self.spatial_callbacks[event_type][agent_id] = callback
    
    def register_agent(
        self,
        agent_id: str,
        lat: float,
        lon: float,
        **kwargs
    ):
        """Register agent in spatial index."""
        if self.has_spatial:
            self.spatial_index.insert(agent_id, lat, lon, **kwargs)
    
    def update_agent_location(self, agent_id: str, lat: float, lon: float):
        """Update agent location."""
        if self.has_spatial:
            self.spatial_index.update(agent_id, lat, lon)
    
    def unregister_agent(self, agent_id: str):
        """Remove agent from spatial index."""
        if self.has_spatial:
            self.spatial_index.remove(agent_id)
    
    def start_listening(self):
        """No-op for in-memory (callbacks are immediate)."""
        pass
    
    def stop_listening(self):
        """No-op for in-memory."""
        pass
    
    def close(self):
        """Cleanup."""
        self.callbacks.clear()
        self.spatial_callbacks.clear()
        if self.has_spatial:
            self.spatial_index.clear()
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics."""
        return {
            'events_published': self.events_published,
            'events_received': self.events_received,
            'has_spatial_index': self.has_spatial,
            'subscriptions': len(self.callbacks),
            'spatial_subscriptions': sum(len(v) for v in self.spatial_callbacks.values())
        }


# ========================================
# Null Event Bus (Tier 3 Fallback)
# ========================================

class NullEventBus:
    """
    Null event bus - all operations are no-ops.
    Used when both Redis and in-memory fail.
    """
    
    def publish(self, event: BaseEvent) -> bool:
        return False
    
    def subscribe(self, *args, **kwargs):
        pass
    
    def subscribe_spatial(self, *args, **kwargs):
        pass
    
    def register_agent(self, *args, **kwargs):
        pass
    
    def update_agent_location(self, *args, **kwargs):
        pass
    
    def unregister_agent(self, *args, **kwargs):
        pass
    
    def start_listening(self):
        pass
    
    def stop_listening(self):
        pass
    
    def close(self):
        pass
    
    def get_statistics(self) -> Dict[str, Any]:
        return {
            'mode': 'null',
            'events_published': 0,
            'events_received': 0,
            'available': False
        }


# ========================================
# DEBUG: Usage and Testing
# ========================================

if __name__ == "__main__":
    import time
    
    logging.basicConfig(level=logging.INFO)
    
    print("="*70)
    print("🧪 SAFE EVENT BUS DEMO")
    print("="*70)
    print()
    
    # Test 1: With Redis (if available)
    print("Test 1: Attempting to use Redis...")
    bus = SafeEventBus(enable_redis=True)
    print(f"Mode: {bus.get_mode()}")
    print(f"Available: {bus.is_available()}")
    print()
    
    # Test 2: Without Redis (force fallback)
    print("Test 2: Forcing in-memory fallback...")
    bus = SafeEventBus(enable_redis=False)
    print(f"Mode: {bus.get_mode()}")
    print(f"Available: {bus.is_available()}")
    print()
    
    # Test 3: Publishing events
    if bus.is_available():
        print("Test 3: Publishing test event...")
        
        from .event_types import PolicyChangeEvent
        
        def handle_event(event):
            print(f"✅ Received event: {event.payload}")
        
        from .event_types import EventType
        bus.subscribe(EventType.POLICY_CHANGE, handle_event)
        bus.start_listening()
        
        event = PolicyChangeEvent(
            parameter='test_param',
            old_value=10.0,
            new_value=20.0,
            lat=55.9533,
            lon=-3.1883
        )
        
        success = bus.publish(event)
        print(f"Published: {success}")
        
        time.sleep(0.5)  # Wait for callback
        
        stats = bus.get_statistics()
        print(f"\nStatistics: {stats}")
        
        bus.close()
    else:
        print("⚠️ Event bus not available (expected if Redis not running)")
    
    print("\n✅ Demo complete!")