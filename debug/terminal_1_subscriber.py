#!/usr/bin/env python3
"""
terminal_1_subscriber.py

Run this in Terminal 1 to act as a subscriber/listener.
Receives events published from Terminal 2.
"""

import time
import logging
from events.event_bus import SpatialEventBus
from events.event_types import EventType, InfrastructureFailureEvent, PolicyChangeEvent

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

print("="*70)
print("🎧 TERMINAL 1: SUBSCRIBER / LISTENER")
print("="*70)
print()

# Create event bus
bus = SpatialEventBus()

# Register some agents at different locations
print("📍 Registering agents...")
agents = {
    'agent_edinburgh': {'lat': 55.9533, 'lon': -3.1883, 'radius': 10.0},
    'agent_glasgow': {'lat': 55.8642, 'lon': -4.2518, 'radius': 10.0},
    'agent_aberdeen': {'lat': 57.1499, 'lon': -2.0938, 'radius': 10.0},
}

for agent_id, loc in agents.items():
    bus.register_agent(agent_id, lat=loc['lat'], lon=loc['lon'], 
                      perception_radius_km=loc['radius'])
    print(f"  ✅ {agent_id}: ({loc['lat']:.4f}, {loc['lon']:.4f}) radius={loc['radius']}km")

print()

# Event counters
event_counts = {agent_id: 0 for agent_id in agents.keys()}

# Callback for infrastructure failures
def handle_infrastructure_failure(agent_id):
    def callback(event):
        event_counts[agent_id] += 1
        print(f"\n🚨 [{agent_id}] INFRASTRUCTURE FAILURE DETECTED!")
        print(f"   Type: {event.payload['infrastructure_type']}")
        print(f"   ID: {event.payload['infrastructure_id']}")
        print(f"   Reason: {event.payload['failure_reason']}")
        print(f"   Location: ({event.spatial.latitude}, {event.spatial.longitude})")
        print(f"   Radius: {event.spatial.radius_km} km")
        print(f"   Total events for {agent_id}: {event_counts[agent_id]}")
    return callback

# Callback for policy changes
def handle_policy_change(agent_id):
    def callback(event):
        event_counts[agent_id] += 1
        print(f"\n📢 [{agent_id}] POLICY CHANGE!")
        print(f"   Parameter: {event.payload['parameter']}")
        print(f"   Old: {event.payload['old_value']}")
        print(f"   New: {event.payload['new_value']}")
        print(f"   Delta: {event.payload['delta']:+.2f} ({event.payload['delta_pct']:+.1f}%)")
        print(f"   Total events for {agent_id}: {event_counts[agent_id]}")
    return callback

# Subscribe all agents to infrastructure failures and policy changes
print("🎧 Subscribing agents to events...")
for agent_id in agents.keys():
    bus.subscribe_spatial(agent_id, EventType.INFRASTRUCTURE_FAILURE, 
                         handle_infrastructure_failure(agent_id))
    bus.subscribe_spatial(agent_id, EventType.POLICY_CHANGE,
                         handle_policy_change(agent_id))
    print(f"  ✅ {agent_id} subscribed")

print()

# Start listening
print("="*70)
print("🎧 LISTENING FOR EVENTS...")
print("="*70)
print()
print("💡 Now run 'python terminal_2_publisher.py' in another terminal")
print("   to publish events and see them received here!")
print()
print("📊 Statistics will be shown every 10 seconds")
print("Press Ctrl+C to stop")
print()

bus.start_listening()

try:
    # Keep running and show stats periodically
    last_stats_time = time.time()
    
    while True:
        time.sleep(1)
        
        # Show stats every 10 seconds
        if time.time() - last_stats_time > 10:
            print("\n" + "="*70)
            print("📊 STATISTICS UPDATE")
            print("="*70)
            
            stats = bus.get_statistics()
            print(f"Events published: {stats['events_published']}")
            print(f"Events received: {stats['events_received']}")
            print(f"Active subscriptions: {stats['subscriptions']}")
            print(f"Listening: {stats['listening']}")
            
            print("\nPer-agent event counts:")
            for agent_id, count in event_counts.items():
                print(f"  {agent_id}: {count} events")
            
            print("="*70 + "\n")
            
            last_stats_time = time.time()

except KeyboardInterrupt:
    print("\n\n🛑 Shutting down subscriber...")
    bus.close()
    
    print("\n" + "="*70)
    print("📊 FINAL STATISTICS")
    print("="*70)
    
    stats = bus.get_statistics()
    print(f"Total events published (by me): {stats['events_published']}")
    print(f"Total events received: {stats['events_received']}")
    
    print("\nFinal per-agent event counts:")
    for agent_id, count in event_counts.items():
        print(f"  {agent_id}: {count} events")
    
    print("\n✅ Subscriber stopped cleanly")
