"""
events/event_bus.py

Redis-based event bus for RTD_SIM real-time digital twin.
Implements pub/sub pattern for event distribution.

Features:
- Topic-based subscriptions
- Spatial filtering (agents subscribe by location)
- Priority queues for event ordering
- Event persistence (optional)
- Multi-process safe

Usage:
    # Publisher
    bus = EventBus()
    bus.publish(policy_event)
    
    # Subscriber
    bus = EventBus()
    bus.subscribe('policy_change', callback=handle_policy_change)
    bus.start_listening()
"""

import redis
import json
import logging
from typing import Callable, Dict, List, Optional, Any
from threading import Thread
import time

from .event_types import BaseEvent, EventType, EventPriority

logger = logging.getLogger(__name__)


class EventBus:
    """
    Redis-based pub/sub event bus.
    
    Architecture:
    - Each event type has its own channel (e.g., 'rtd:events:policy_change')
    - Subscribers filter events by spatial proximity
    - Priority events use separate channels for fast-tracking
    """
    
    def __init__(
        self,
        host: str = 'localhost',
        port: int = 6379,
        db: int = 0,
        channel_prefix: str = 'rtd:events'
    ):
        """
        Initialize event bus.
        
        Args:
            host: Redis host
            port: Redis port
            db: Redis database number
            channel_prefix: Prefix for all event channels
        """
        self.host = host
        self.port = port
        self.db = db
        self.channel_prefix = channel_prefix
        
        # Redis connections (separate for pub and sub)
        self.redis_client = None
        self.pubsub = None
        
        # Subscriptions
        self.callbacks: Dict[str, List[Callable]] = {}
        self.listening = False
        self.listener_thread = None
        
        # Statistics
        self.events_published = 0
        self.events_received = 0
        
        # Connect
        self._connect()
    
    def _connect(self):
        """Establish Redis connection."""
        try:
            self.redis_client = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                decode_responses=True
            )
            
            # Test connection
            self.redis_client.ping()
            logger.info(f"✅ Connected to Redis at {self.host}:{self.port}")
            
        except redis.ConnectionError as e:
            logger.error(f"❌ Failed to connect to Redis: {e}")
            logger.warning("⚠️ Event bus running in OFFLINE mode (no pub/sub)")
            self.redis_client = None
    
    def _get_channel_name(self, event_type: EventType, priority: EventPriority = EventPriority.NORMAL) -> str:
        """
        Generate channel name for event type and priority.
        
        Examples:
        - rtd:events:policy_change
        - rtd:events:infrastructure_failure:high
        """
        if priority == EventPriority.CRITICAL or priority == EventPriority.HIGH:
            return f"{self.channel_prefix}:{event_type.value}:{priority.name.lower()}"
        else:
            return f"{self.channel_prefix}:{event_type.value}"
    
    def publish(self, event: BaseEvent) -> bool:
        """
        Publish event to appropriate channel.
        
        Args:
            event: Event to publish
        
        Returns:
            True if published successfully, False otherwise
        """
        if not self.redis_client:
            logger.warning("Event bus offline, cannot publish")
            return False
        
        try:
            # Serialize event
            event_json = json.dumps(event.to_dict())
            
            # Determine channel
            channel = self._get_channel_name(event.event_type, event.priority)
            
            # Publish
            num_subscribers = self.redis_client.publish(channel, event_json)
            
            self.events_published += 1
            
            logger.debug(
                f"📢 Published {event.event_type.value} to {channel} "
                f"({num_subscribers} subscribers)"
            )
            
            # Also publish to 'all' channel for monitoring
            self.redis_client.publish(f"{self.channel_prefix}:all", event_json)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to publish event: {e}")
            return False
    
    def subscribe(
        self,
        event_type: EventType,
        callback: Callable[[BaseEvent], None],
        priority: Optional[EventPriority] = None
    ):
        """
        Subscribe to event type with callback.
        
        Args:
            event_type: Type of events to receive
            callback: Function to call when event received
            priority: Optional priority filter (only receive high/critical)
        """
        if priority:
            channel = self._get_channel_name(event_type, priority)
        else:
            channel = self._get_channel_name(event_type)
        
        # Check if this is a new channel
        is_new_channel = channel not in self.callbacks
        
        if is_new_channel:
            self.callbacks[channel] = []
        
        self.callbacks[channel].append(callback)
        logger.info(f"✅ Subscribed to {channel}")
        
        # Phase 6.2b FIX: If already listening, dynamically subscribe to new channel
        if is_new_channel and self.listening and self.pubsub:
            try:
                self.pubsub.subscribe(channel)
                logger.info(f"🎧 Dynamically subscribed Redis to {channel}")
            except Exception as e:
                logger.error(f"Failed to dynamically subscribe to {channel}: {e}")
    
    def subscribe_all(self, callback: Callable[[BaseEvent], None]):
        """
        Subscribe to ALL events (monitoring/logging).
        
        Args:
            callback: Function to call for any event
        """
        channel = f"{self.channel_prefix}:all"
        
        # Check if this is a new channel
        is_new_channel = channel not in self.callbacks
        
        if is_new_channel:
            self.callbacks[channel] = []
        
        self.callbacks[channel].append(callback)
        logger.info(f"✅ Subscribed to ALL events")
        
        # Phase 6.2b FIX: If already listening, dynamically subscribe to new channel
        if is_new_channel and self.listening and self.pubsub:
            try:
                self.pubsub.subscribe(channel)
                logger.info(f"🎧 Dynamically subscribed Redis to {channel}")
            except Exception as e:
                logger.error(f"Failed to dynamically subscribe to {channel}: {e}")
    
    def start_listening(self):
        """
        Start listening for events in background thread.
        Non-blocking.
        """
        if not self.redis_client:
            logger.warning("Event bus offline, cannot listen")
            return
        
        if self.listening:
            logger.warning("Already listening")
            return
        
        # Create pubsub object
        self.pubsub = self.redis_client.pubsub()
        
        # Subscribe to all registered channels
        for channel in self.callbacks.keys():
            self.pubsub.subscribe(channel)
            logger.info(f"🎧 Listening on {channel}")
        
        # Start listener thread
        self.listening = True
        self.listener_thread = Thread(target=self._listen_loop, daemon=True)
        self.listener_thread.start()
        
        logger.info("🎧 Event bus listening started")
    
    def stop_listening(self):
        """Stop listening for events."""
        self.listening = False
        
        if self.pubsub:
            self.pubsub.close()
            self.pubsub = None
        
        if self.listener_thread:
            self.listener_thread.join(timeout=2.0)
            self.listener_thread = None
        
        logger.info("🛑 Event bus listening stopped")
    
    # DEBUGGING PATCH for event_bus.py
    def _listen_loop(self):
        """
        Main listening loop (runs in background thread).
        Receives events and dispatches to callbacks.
        """
        logger.info("🎧 Listener thread started")
        
        # DEBUG: Show registered callbacks
        logger.info(f"🔍 DEBUG: Registered callbacks: {list(self.callbacks.keys())}")
        logger.info(f"🔍 DEBUG: Total callback channels: {len(self.callbacks)}")
        
        while self.listening:
            try:
                # Check if pubsub is still open
                if not self.pubsub:
                    break
                
                # Get message (blocking with timeout)
                message = self.pubsub.get_message(timeout=0.1)
                
                # DEBUG: Log every message received
                if message:
                    logger.debug(f"🔍 DEBUG: Raw message type: {message.get('type')}")
                    if message['type'] == 'message':
                        channel = message['channel']
                        data = message['data']
                        
                        # DEBUG: Log channel and data
                        logger.info(f"🔍 DEBUG: Message on channel: '{channel}' (type: {type(channel)})")
                        logger.info(f"🔍 DEBUG: Channel in callbacks? {channel in self.callbacks}")
                        logger.info(f"🔍 DEBUG: Available channels: {list(self.callbacks.keys())}")
                        
                        # Deserialize event
                        event_dict = json.loads(data)
                        event = BaseEvent.from_dict(event_dict)
                        
                        logger.info(f"🔍 DEBUG: Deserialized event type: {event.event_type}")
                        
                        # Dispatch to callbacks
                        if channel in self.callbacks:
                            logger.info(f"✅ Channel matched! Calling {len(self.callbacks[channel])} callbacks")
                            for callback in self.callbacks[channel]:
                                try:
                                    callback(event)
                                    self.events_received += 1
                                    logger.info(f"✅ Callback executed! Total received: {self.events_received}")
                                except Exception as e:
                                    logger.error(f"Callback failed for {channel}: {e}")
                        else:
                            logger.warning(f"❌ Channel '{channel}' NOT in callbacks dict!")
                            logger.warning(f"   Callback keys: {list(self.callbacks.keys())}")
                
            except (ValueError, OSError) as e:
                if self.listening:
                    logger.error(f"Listen loop error: {e}")
            except Exception as e:
                logger.error(f"Unexpected error in listen loop: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        logger.info("🛑 Listener thread stopped")
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get event bus statistics.
        
        Returns:
            Dictionary with stats (published, received, channels, etc.)
        """
        return {
            'events_published': self.events_published,
            'events_received': self.events_received,
            'subscriptions': len(self.callbacks),
            'listening': self.listening,
            'connected': self.redis_client is not None
        }
    
    def clear_statistics(self):
        """Reset statistics counters."""
        self.events_published = 0
        self.events_received = 0
    
    def close(self):
        """Close all connections."""
        self.stop_listening()
        
        if self.redis_client:
            self.redis_client.close()
            self.redis_client = None
        
        logger.info("🔌 Event bus closed")


# ==================================================================
# SPATIAL EVENT BUS (extends EventBus with spatial filtering)
# ==================================================================

class SpatialEventBus(EventBus):
    """
    Event bus with spatial filtering.
    Agents subscribe with their location and perception radius.
    Only receive events within perception range.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Agent locations for spatial filtering
        # {agent_id: {'lat': float, 'lon': float, 'radius_km': float}}
        self.agent_locations: Dict[str, Dict[str, float]] = {}
    
    def register_agent(
        self,
        agent_id: str,
        lat: float,
        lon: float,
        perception_radius_km: float = 5.0
    ):
        """
        Register agent location for spatial filtering.
        
        Args:
            agent_id: Unique agent identifier
            lat: Agent latitude
            lon: Agent longitude
            perception_radius_km: How far agent can perceive events
        """
        self.agent_locations[agent_id] = {
            'lat': lat,
            'lon': lon,
            'radius_km': perception_radius_km
        }
        logger.debug(f"📍 Registered agent {agent_id} at ({lat:.4f}, {lon:.4f})")
    
    def update_agent_location(self, agent_id: str, lat: float, lon: float):
        """Update agent location (called when agent moves)."""
        if agent_id in self.agent_locations:
            self.agent_locations[agent_id]['lat'] = lat
            self.agent_locations[agent_id]['lon'] = lon
    
    def unregister_agent(self, agent_id: str):
        """Remove agent from spatial index."""
        if agent_id in self.agent_locations:
            del self.agent_locations[agent_id]
    
    def subscribe_spatial(
        self,
        agent_id: str,
        event_type: EventType,
        callback: Callable[[BaseEvent], None]
    ):
        """
        Subscribe with spatial filtering.
        Callback only invoked if event within agent's perception radius.
        
        Args:
            agent_id: Agent identifier
            event_type: Type of events to receive
            callback: Function to call when relevant event received
        """
        
        # Wrap callback with spatial filter
        def spatial_callback(event: BaseEvent):
            perceivable = self._is_event_perceivable(agent_id, event)
            logger.debug(f"Spatial filter for {agent_id}: perceivable={perceivable}")
            if perceivable:
                callback(event)
            else:
                logger.debug(f"  Event at ({event.spatial.latitude if event.spatial else 'N/A'}, "
                           f"{event.spatial.longitude if event.spatial else 'N/A'}) not within range")
        
        # Subscribe to ALL priority channels to ensure delivery
        # This fixes the channel mismatch where high-priority events weren't received
        self.subscribe(event_type, spatial_callback)  # Normal priority
        self.subscribe(event_type, spatial_callback, priority=EventPriority.HIGH)  # High priority  
        self.subscribe(event_type, spatial_callback, priority=EventPriority.CRITICAL)  # Critical priority
    
    def _is_event_perceivable(self, agent_id: str, event: BaseEvent) -> bool:
        """
        Check if event is within agent's perception radius.
        
        Args:
            agent_id: Agent identifier
            event: Event to check
        
        Returns:
            True if agent should perceive event, False otherwise
        """
        if agent_id not in self.agent_locations:
            return False
        
        if not event.spatial:
            # Non-spatial events perceivable by all
            return True
        
        agent_loc = self.agent_locations[agent_id]
        
        # Haversine distance (simplified for small distances)
        distance_km = self._haversine_distance(
            agent_loc['lat'], agent_loc['lon'],
            event.spatial.latitude, event.spatial.longitude
        )
        
        # Agent perceives if within EITHER:
        # - Agent's perception radius, OR
        # - Event's effect radius
        max_radius = max(agent_loc['radius_km'], event.spatial.radius_km)
        
        return distance_km <= max_radius
    
    @staticmethod
    def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Calculate distance between two points using Haversine formula.
        
        Args:
            lat1, lon1: First point
            lat2, lon2: Second point
        
        Returns:
            Distance in kilometers
        """
        from math import radians, sin, cos, sqrt, atan2
        
        R = 6371  # Earth radius in km
        
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))
        
        return R * c


# ==================================================================
# EXAMPLE USAGE
# ==================================================================

if __name__ == "__main__":
    from event_types import PolicyChangeEvent, InfrastructureFailureEvent
    
    # Setup logging
    logging.basicConfig(level=logging.INFO)
    
    # Example 1: Basic pub/sub
    print("=" * 60)
    print("EXAMPLE 1: Basic Pub/Sub")
    print("=" * 60)
    
    bus = EventBus()
    
    def handle_policy(event: BaseEvent):
        print(f"📩 Received policy change: {event.payload}")
    
    bus.subscribe(EventType.POLICY_CHANGE, handle_policy)
    bus.start_listening()
    
    # Publish event
    event = PolicyChangeEvent(
        parameter='carbon_tax',
        old_value=50.0,
        new_value=100.0,
        lat=55.9533,
        lon=-3.1883
    )
    bus.publish(event)
    
    time.sleep(0.5)  # Wait for processing
    
    print(f"\nStatistics: {bus.get_statistics()}")
    
    bus.close()
    
    # Example 2: Spatial filtering
    print("\n" + "=" * 60)
    print("EXAMPLE 2: Spatial Filtering")
    print("=" * 60)
    
    spatial_bus = SpatialEventBus()
    
    # Register agents at different locations
    spatial_bus.register_agent('agent_1', lat=55.9533, lon=-3.1883, perception_radius_km=5.0)
    spatial_bus.register_agent('agent_2', lat=55.9633, lon=-3.1983, perception_radius_km=5.0)
    
    def agent_callback(event: BaseEvent):
        print(f"📍 Agent perceived event at ({event.spatial.latitude}, {event.spatial.longitude})")
    
    spatial_bus.subscribe_spatial('agent_1', EventType.INFRASTRUCTURE_FAILURE, agent_callback)
    spatial_bus.start_listening()
    
    # Publish event near agent_1
    near_event = InfrastructureFailureEvent(
        infrastructure_type='charging_station',
        infrastructure_id='CS_1',
        failure_reason='maintenance',
        lat=55.9540,  # ~0.7km from agent_1
        lon=-3.1890,
        radius_km=2.0
    )
    spatial_bus.publish(near_event)
    
    time.sleep(0.5)
    
    spatial_bus.close()
    
    print("\n✅ Examples complete!")