"""
rtd_sim/test_event_system.py

Test script for Phase 6.1 event system.
Validates pub/sub, spatial filtering, and event types.
"""

import time
import logging
from events.event_bus import EventBus, SpatialEventBus
from events.event_types import (
    PolicyChangeEvent,
    InfrastructureFailureEvent,
    WeatherEvent,
    EventType
)

logging.basicConfig(level=logging.INFO)


def test_basic_pubsub():
    """Test basic publish-subscribe."""
    print("\n" + "="*60)
    print("TEST 1: Basic Pub/Sub")
    print("="*60)
    
    bus = EventBus()
    received_events = []
    
    def callback(event):
        received_events.append(event)
        print(f"✅ Received: {event.event_type.value}")
    
    bus.subscribe(EventType.POLICY_CHANGE, callback)
    bus.start_listening()
    
    # Publish multiple events
    events = [
        PolicyChangeEvent('carbon_tax', 50, 100, 55.9533, -3.1883),
        PolicyChangeEvent('ev_subsidy', 5000, 7000, 55.9533, -3.1883),
    ]
    
    for event in events:
        bus.publish(event)
    
    time.sleep(0.5)
    
    assert len(received_events) == 2, f"Expected 2 events, got {len(received_events)}"
    print(f"✅ Test passed: {len(received_events)} events received")
    
    bus.close()


def test_spatial_filtering():
    """Test spatial perception filtering."""
    print("\n" + "="*60)
    print("TEST 2: Spatial Filtering")
    print("="*60)
    
    bus = SpatialEventBus()
    
    # Register agents
    bus.register_agent('agent_1', lat=55.9533, lon=-3.1883, perception_radius_km=5.0)
    bus.register_agent('agent_2', lat=55.9700, lon=-3.2000, perception_radius_km=5.0)  # ~2km away
    bus.register_agent('agent_3', lat=56.0000, lon=-3.3000, perception_radius_km=5.0)  # ~15km away
    
    perceived_by = {
        'agent_1': [],
        'agent_2': [],
        'agent_3': []
    }
    
    def make_callback(agent_id):
        def callback(event):
            perceived_by[agent_id].append(event)
            print(f"📍 {agent_id} perceived event")
        return callback
    
    for agent_id in ['agent_1', 'agent_2', 'agent_3']:
        bus.subscribe_spatial(agent_id, EventType.INFRASTRUCTURE_FAILURE, make_callback(agent_id))
    
    bus.start_listening()
    
    # Publish event near agent_1
    event = InfrastructureFailureEvent(
        infrastructure_type='charging_station',
        infrastructure_id='CS_1',
        failure_reason='maintenance',
        lat=55.9540,  # ~0.7km from agent_1
        lon=-3.1890,
        radius_km=3.0  # 3km radius
    )
    
    bus.publish(event)
    time.sleep(0.5)
    
    # Verify
    assert len(perceived_by['agent_1']) == 1, "agent_1 should perceive (within 5km)"
    assert len(perceived_by['agent_2']) == 1, "agent_2 should perceive (within 5km)"
    assert len(perceived_by['agent_3']) == 0, "agent_3 should NOT perceive (too far)"
    
    print(f"✅ Spatial filtering works correctly")
    print(f"   - agent_1: {len(perceived_by['agent_1'])} events")
    print(f"   - agent_2: {len(perceived_by['agent_2'])} events")
    print(f"   - agent_3: {len(perceived_by['agent_3'])} events")
    
    bus.close()


def test_priority_events():
    """Test priority event handling."""
    print("\n" + "="*60)
    print("TEST 3: Priority Events")
    print("="*60)
    
    bus = EventBus()
    received = {'normal': [], 'high': []}
    
    def callback(event):
        if event.priority.name in ['HIGH', 'CRITICAL']:
            received['high'].append(event)
        else:
            received['normal'].append(event)
        print(f"📥 Received {event.priority.name} priority event")
    
    # Subscribe to both normal and high priority channels
    bus.subscribe(EventType.WEATHER_EVENT, callback)
    bus.subscribe(EventType.WEATHER_EVENT, callback, priority=EventPriority.HIGH)
    
    bus.start_listening()
    
    # Publish events with different priorities
    normal_weather = WeatherEvent('rain', severity=3, lat=55.9533, lon=-3.1883)
    severe_weather = WeatherEvent('storm', severity=9, lat=55.9533, lon=-3.1883)
    
    bus.publish(normal_weather)
    bus.publish(severe_weather)
    
    time.sleep(0.5)
    
    print(f"✅ Priority events work correctly")
    print(f"   - Normal: {len(received['normal'])} events")
    print(f"   - High: {len(received['high'])} events")
    
    bus.close()


def test_statistics():
    """Test statistics tracking."""
    print("\n" + "="*60)
    print("TEST 4: Statistics")
    print("="*60)
    
    bus = EventBus()
    
    def callback(event):
        pass
    
    bus.subscribe(EventType.POLICY_CHANGE, callback)
    bus.start_listening()
    
    # Publish several events
    for i in range(5):
        event = PolicyChangeEvent(f'param_{i}', 0, 100, 55.9533, -3.1883)
        bus.publish(event)
    
    time.sleep(0.5)
    
    stats = bus.get_statistics()
    print(f"📊 Statistics:")
    print(f"   - Published: {stats['events_published']}")
    print(f"   - Received: {stats['events_received']}")
    print(f"   - Subscriptions: {stats['subscriptions']}")
    print(f"   - Listening: {stats['listening']}")
    
    assert stats['events_published'] == 5
    assert stats['events_received'] == 5
    
    print(f"✅ Statistics tracking works correctly")
    
    bus.close()


def run_all_tests():
    """Run all integration tests."""
    print("\n" + "="*70)
    print("🧪 PHASE 6.1 EVENT SYSTEM INTEGRATION TESTS")
    print("="*70)
    
    try:
        test_basic_pubsub()
        test_spatial_filtering()
        test_priority_events()
        test_statistics()
        
        print("\n" + "="*70)
        print("✅ ALL TESTS PASSED!")
        print("="*70)
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_all_tests()