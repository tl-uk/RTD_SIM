"""
Debug test for spatial filtering issue.
"""

import time
import logging
from events.event_bus import SpatialEventBus
from events.event_types import InfrastructureFailureEvent, EventType

# Enable DEBUG logging
logging.basicConfig(level=logging.DEBUG)

print("\n" + "="*60)
print("DEBUG: Spatial Filtering Test")
print("="*60)

bus = SpatialEventBus()

# Register agents
print("\n📍 Registering agents...")
bus.register_agent('agent_1', lat=55.9533, lon=-3.1883, perception_radius_km=5.0)
print(f"   agent_1 location: {bus.agent_locations['agent_1']}")

perceived_events = []

def callback(event):
    print(f"\n✅ CALLBACK TRIGGERED!")
    print(f"   Event type: {event.event_type.value}")
    print(f"   Event location: ({event.spatial.latitude}, {event.spatial.longitude})")
    print(f"   Event radius: {event.spatial.radius_km} km")
    perceived_events.append(event)

# Subscribe
print("\n🔃 Subscribing agent_1...")
bus.subscribe_spatial('agent_1', EventType.INFRASTRUCTURE_FAILURE, callback)

print("\n🎧 Starting listener...")
bus.start_listening()

# Give listener time to start
time.sleep(0.5)

# Create and publish event
print("\n📢 Creating event...")
event = InfrastructureFailureEvent(
    infrastructure_type='charging_station',
    infrastructure_id='CS_1',
    failure_reason='maintenance',
    lat=55.9540,  # ~0.7km from agent_1
    lon=-3.1890,
    radius_km=3.0
)

print(f"   Event location: ({event.spatial.latitude}, {event.spatial.longitude})")
print(f"   Event radius: {event.spatial.radius_km} km")

# Calculate distance manually
import math
def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

distance = haversine(55.9533, -3.1883, 55.9540, -3.1890)
print(f"   Distance to agent_1: {distance:.2f} km")

agent_radius = bus.agent_locations['agent_1']['radius_km']
event_radius = event.spatial.radius_km
max_radius = max(agent_radius, event_radius)
print(f"   Agent perception radius: {agent_radius} km")
print(f"   Max effective radius: {max_radius} km")
print(f"   Should perceive: {distance <= max_radius}")

print("\n📢 Publishing event...")
success = bus.publish(event)
print(f"   Published successfully: {success}")

# Wait for processing
print("\n⏳ Waiting for event processing...")
time.sleep(2.0)

print(f"\n📊 Results:")
print(f"   Events perceived: {len(perceived_events)}")

if len(perceived_events) == 0:
    print("\n❌ FAILED: Event not perceived!")
    print("\n🔍 Debugging info:")
    print(f"   Bus statistics: {bus.get_statistics()}")
    print(f"   Listening: {bus.listening}")
    print(f"   Pubsub: {bus.pubsub}")
    print(f"   Callbacks registered: {list(bus.callbacks.keys())}")
else:
    print("\n✅ SUCCESS: Event perceived!")

bus.close()