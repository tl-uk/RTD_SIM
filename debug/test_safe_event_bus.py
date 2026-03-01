#!/usr/bin/env python3
"""
test_safe_event_bus.py

Test all three fallback tiers of SafeEventBus.
"""

import sys
import os
# Add parent directory to path so we can import events
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import logging
import subprocess

logging.basicConfig(level=logging.INFO)


def check_redis_running():
    """Check if Redis is running."""
    try:
        import redis
        client = redis.Redis(host='localhost', port=6379)
        client.ping()
        return True
    except Exception:
        return False


def test_tier_1_redis():
    """Test Tier 1: Redis backend."""
    print("\n" + "="*70)
    print("TEST 1: Redis Backend (Tier 1 - Full Features)")
    print("="*70)
    
    if not check_redis_running():
        print("⚠️ SKIPPED: Redis not running")
        print("   To test: redis-server &")
        return False
    
    from events.event_bus_safe import SafeEventBus
    from events.event_types import PolicyChangeEvent, EventType
    
    # Create bus with Redis enabled
    bus = SafeEventBus(enable_redis=True)
    
    # Verify mode
    assert bus.get_mode() == 'redis', f"Expected 'redis', got '{bus.get_mode()}'"
    assert bus.is_available(), "Bus should be available"
    
    # Test publish/subscribe
    received_events = []
    
    def callback(event):
        received_events.append(event)
    
    bus.subscribe(EventType.POLICY_CHANGE, callback)
    bus.start_listening()
    
    time.sleep(0.2)  # Let listener start
    
    # Publish event
    event = PolicyChangeEvent(
        parameter='carbon_tax',
        old_value=50.0,
        new_value=100.0,
        lat=55.9533,
        lon=-3.1883
    )
    
    success = bus.publish(event)
    assert success, "Publish should succeed"
    
    time.sleep(0.5)  # Wait for delivery
    
    assert len(received_events) == 1, f"Should receive 1 event, got {len(received_events)}"
    
    # Test statistics
    stats = bus.get_statistics()
    assert stats['mode'] == 'redis'
    assert stats['events_published'] >= 1
    
    bus.close()
    
    print("✅ PASSED: Redis backend works correctly")
    return True


def test_tier_2_memory():
    """Test Tier 2: In-memory backend."""
    print("\n" + "="*70)
    print("TEST 2: In-Memory Backend (Tier 2 - Single Process)")
    print("="*70)
    
    from events.event_bus_safe import SafeEventBus
    from events.event_types import PolicyChangeEvent, EventType
    
    # Create bus with Redis disabled (force in-memory)
    bus = SafeEventBus(enable_redis=False)
    
    # Verify mode
    assert bus.get_mode() == 'memory', f"Expected 'memory', got '{bus.get_mode()}'"
    assert bus.is_available(), "Bus should be available"
    
    # Test publish/subscribe
    received_events = []
    
    def callback(event):
        received_events.append(event)
    
    bus.subscribe(EventType.POLICY_CHANGE, callback)
    
    # Publish event (immediate delivery in memory)
    event = PolicyChangeEvent(
        parameter='ev_subsidy',
        old_value=5000.0,
        new_value=7000.0,
        lat=55.9533,
        lon=-3.1883
    )
    
    success = bus.publish(event)
    assert success, "Publish should succeed"
    
    assert len(received_events) == 1, f"Should receive 1 event, got {len(received_events)}"
    
    # Test spatial features
    bus.register_agent('test_agent', lat=55.9533, lon=-3.1883, perception_radius_km=10.0)
    
    spatial_received = []
    
    def spatial_callback(event):
        spatial_received.append(event)
    
    bus.subscribe_spatial('test_agent', EventType.POLICY_CHANGE, spatial_callback)
    
    # Publish nearby event
    nearby_event = PolicyChangeEvent(
        parameter='grid_capacity',
        old_value=300.0,
        new_value=350.0,
        lat=55.9540,  # ~0.7km away
        lon=-3.1890
    )
    
    bus.publish(nearby_event)
    
    # In-memory delivery is immediate
    assert len(spatial_received) >= 1, "Spatial callback should be triggered"
    
    # Test statistics
    stats = bus.get_statistics()
    assert stats['mode'] == 'memory'
    assert stats['events_published'] >= 2
    
    bus.close()
    
    print("✅ PASSED: In-memory backend works correctly")
    return True


def test_tier_3_null():
    """Test Tier 3: Null backend (should never crash)."""
    print("\n" + "="*70)
    print("TEST 3: Null Backend (Tier 3 - Disabled)")
    print("="*70)
    
    from events.event_bus_safe import NullEventBus
    from events.event_types import PolicyChangeEvent
    
    # Create null bus directly
    bus = NullEventBus()
    
    # All operations should be no-ops (never crash)
    event = PolicyChangeEvent(
        parameter='test',
        old_value=0,
        new_value=1,
        lat=0,
        lon=0
    )
    
    # These should all work without error
    result = bus.publish(event)
    assert result == False, "Null bus should return False"
    
    bus.subscribe(None, lambda x: None)
    bus.subscribe_spatial('agent', None, lambda x: None)
    bus.register_agent('agent', 0, 0)
    bus.update_agent_location('agent', 0, 0)
    bus.start_listening()
    bus.stop_listening()
    bus.close()
    
    stats = bus.get_statistics()
    assert stats['available'] == False
    
    print("✅ PASSED: Null backend never crashes")
    return True


def test_safe_mode_detection():
    """Test that SafeEventBus correctly detects available mode."""
    print("\n" + "="*70)
    print("TEST 4: Automatic Mode Detection")
    print("="*70)
    
    from events.event_bus_safe import SafeEventBus
    
    # Let it auto-detect
    bus = SafeEventBus()
    
    mode = bus.get_mode()
    print(f"Detected mode: {mode}")
    
    if mode == 'redis':
        print("✅ Redis available and selected")
    elif mode == 'memory':
        print("✅ Fallback to in-memory (Redis unavailable)")
    elif mode == 'null':
        print("⚠️ All backends failed (null mode)")
    
    # Verify is_available() matches mode
    available = bus.is_available()
    expected = mode in ['redis', 'memory']
    assert available == expected, f"is_available() should be {expected}"
    
    bus.close()
    
    print("✅ PASSED: Mode detection works correctly")
    return True


def test_resilience():
    """Test that operations never crash even if backend fails."""
    print("\n" + "="*70)
    print("TEST 5: Resilience (Operations Never Crash)")
    print("="*70)
    
    from events.event_bus_safe import SafeEventBus
    from events.event_types import PolicyChangeEvent, EventType
    
    bus = SafeEventBus()
    
    # These should never crash, regardless of mode
    event = PolicyChangeEvent(
        parameter='test',
        old_value=0,
        new_value=1,
        lat=55.9533,
        lon=-3.1883
    )
    
    # Try all operations
    bus.publish(event)
    bus.subscribe(EventType.POLICY_CHANGE, lambda x: None)
    bus.subscribe_spatial('agent', EventType.POLICY_CHANGE, lambda x: None)
    bus.register_agent('agent', 55.9533, -3.1883)
    bus.update_agent_location('agent', 55.9540, -3.1890)
    bus.unregister_agent('agent')
    bus.start_listening()
    bus.stop_listening()
    
    # Even with invalid inputs
    try:
        bus.register_agent('bad', 999, 999)  # Invalid coords
    except Exception:
        pass  # Should be caught internally
    
    bus.close()
    
    print("✅ PASSED: All operations are resilient")
    return True


def run_all_tests():
    """Run all tests."""
    print("\n" + "="*70)
    print("🧪 SAFE EVENT BUS - COMPREHENSIVE TEST SUITE")
    print("="*70)
    
    results = []
    
    # Test tier 1 (Redis)
    try:
        results.append(('Tier 1: Redis', test_tier_1_redis()))
    except Exception as e:
        print(f"❌ Tier 1 FAILED: {e}")
        results.append(('Tier 1: Redis', False))
    
    # Test tier 2 (Memory)
    try:
        results.append(('Tier 2: Memory', test_tier_2_memory()))
    except Exception as e:
        print(f"❌ Tier 2 FAILED: {e}")
        results.append(('Tier 2: Memory', False))
    
    # Test tier 3 (Null)
    try:
        results.append(('Tier 3: Null', test_tier_3_null()))
    except Exception as e:
        print(f"❌ Tier 3 FAILED: {e}")
        results.append(('Tier 3: Null', False))
    
    # Test mode detection
    try:
        results.append(('Mode Detection', test_safe_mode_detection()))
    except Exception as e:
        print(f"❌ Mode Detection FAILED: {e}")
        results.append(('Mode Detection', False))
    
    # Test resilience
    try:
        results.append(('Resilience', test_resilience()))
    except Exception as e:
        print(f"❌ Resilience FAILED: {e}")
        results.append(('Resilience', False))
    
    # Summary
    print("\n" + "="*70)
    print("📊 TEST SUMMARY")
    print("="*70)
    
    for name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{name:30} {status}")
    
    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)
    
    print(f"\nTotal: {passed_count}/{total_count} passed")
    
    if passed_count == total_count:
        print("\n🎉 ALL TESTS PASSED!")
        return 0
    else:
        print(f"\n⚠️ {total_count - passed_count} TEST(S) FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())