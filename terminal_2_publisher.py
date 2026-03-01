#!/usr/bin/env python3
"""
terminal_2_publisher.py

Run this in Terminal 2 to act as a publisher.
Sends events that Terminal 1 will receive.
"""

import time
import logging
from events.event_bus import EventBus
from events.event_types import (
    InfrastructureFailureEvent,
    PolicyChangeEvent,
    WeatherEvent,
    GridStressEvent
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

print("="*70)
print("📢 TERMINAL 2: PUBLISHER / EVENT GENERATOR")
print("="*70)
print()

# Create event bus
bus = EventBus()

print("✅ Connected to event bus")
print()
print("="*70)
print("📢 INTERACTIVE EVENT PUBLISHER")
print("="*70)
print()
print("Choose an event to publish:")
print()
print("1. Infrastructure failure in Edinburgh (agent_edinburgh should see)")
print("2. Infrastructure failure in Glasgow (agent_glasgow should see)")
print("3. Infrastructure failure in Aberdeen (agent_aberdeen should see)")
print("4. Policy change (carbon tax) - all agents should see")
print("5. Policy change (EV subsidy) - all agents should see")
print("6. Weather event in Edinburgh")
print("7. Grid stress event (wide radius)")
print("8. Rapid fire test (10 events)")
print("9. Show statistics")
print("0. Exit")
print()

def publish_edinburgh_failure():
    """Publish infrastructure failure in Edinburgh."""
    event = InfrastructureFailureEvent(
        infrastructure_type='charging_station',
        infrastructure_id='CS_Edinburgh_Central',
        failure_reason='power_outage',
        lat=55.9533,
        lon=-3.1883,
        radius_km=5.0,
        estimated_duration_min=60
    )
    bus.publish(event)
    print(f"📢 Published: Infrastructure failure in Edinburgh")
    print(f"   Location: ({event.spatial.latitude}, {event.spatial.longitude})")
    print(f"   Expected to reach: agent_edinburgh (within 10km)")

def publish_glasgow_failure():
    """Publish infrastructure failure in Glasgow."""
    event = InfrastructureFailureEvent(
        infrastructure_type='charging_station',
        infrastructure_id='CS_Glasgow_Central',
        failure_reason='maintenance',
        lat=55.8642,
        lon=-4.2518,
        radius_km=5.0,
        estimated_duration_min=120
    )
    bus.publish(event)
    print(f"📢 Published: Infrastructure failure in Glasgow")
    print(f"   Location: ({event.spatial.latitude}, {event.spatial.longitude})")
    print(f"   Expected to reach: agent_glasgow (within 10km)")

def publish_aberdeen_failure():
    """Publish infrastructure failure in Aberdeen."""
    event = InfrastructureFailureEvent(
        infrastructure_type='charging_station',
        infrastructure_id='CS_Aberdeen_Port',
        failure_reason='hardware_fault',
        lat=57.1499,
        lon=-2.0938,
        radius_km=5.0,
        estimated_duration_min=30
    )
    bus.publish(event)
    print(f"📢 Published: Infrastructure failure in Aberdeen")
    print(f"   Location: ({event.spatial.latitude}, {event.spatial.longitude})")
    print(f"   Expected to reach: agent_aberdeen (within 10km)")

def publish_carbon_tax_change():
    """Publish carbon tax policy change."""
    event = PolicyChangeEvent(
        parameter='carbon_tax',
        old_value=50.0,
        new_value=100.0,
        lat=56.0,  # Central Scotland
        lon=-3.5,
        radius_km=200.0  # Wide radius - reaches all agents
    )
    bus.publish(event)
    print(f"📢 Published: Carbon tax increase £50 → £100/tonne")
    print(f"   Radius: {event.spatial.radius_km} km")
    print(f"   Expected to reach: ALL agents (nationwide policy)")

def publish_ev_subsidy_change():
    """Publish EV subsidy policy change."""
    event = PolicyChangeEvent(
        parameter='ev_subsidy',
        old_value=5000.0,
        new_value=7000.0,
        lat=56.0,
        lon=-3.5,
        radius_km=200.0
    )
    bus.publish(event)
    print(f"📢 Published: EV subsidy increase £5000 → £7000")
    print(f"   Radius: {event.spatial.radius_km} km")
    print(f"   Expected to reach: ALL agents (nationwide policy)")

def publish_edinburgh_weather():
    """Publish weather event in Edinburgh."""
    event = WeatherEvent(
        weather_type='storm',
        severity=8,
        lat=55.9533,
        lon=-3.1883,
        radius_km=20.0,
        duration_min=180,
        impacts=['heavy_rain', 'reduced_visibility']
    )
    bus.publish(event)
    print(f"📢 Published: Severe storm in Edinburgh")
    print(f"   Severity: {event.payload['severity']}/10")
    print(f"   Expected to reach: agent_edinburgh")

def publish_grid_stress():
    """Publish grid stress event."""
    event = GridStressEvent(
        grid_utilization=0.87,
        threshold=0.85,
        load_mw=270.0,
        capacity_mw=310.0,
        crossed_direction='up',
        lat=56.0,
        lon=-3.5,
        radius_km=150.0
    )
    bus.publish(event)
    print(f"📢 Published: Grid stress event")
    print(f"   Utilization: {event.payload['grid_utilization']:.1%}")
    print(f"   Emergency mode: {event.payload['emergency_mode']}")
    print(f"   Expected to reach: ALL agents (wide grid event)")

def rapid_fire_test():
    """Publish 10 events rapidly to test throughput."""
    print("🚀 Rapid fire test: Publishing 10 events...")
    
    events_sent = 0
    start_time = time.time()
    
    for i in range(10):
        event = PolicyChangeEvent(
            parameter=f'test_param_{i}',
            old_value=float(i),
            new_value=float(i+1),
            lat=56.0,
            lon=-3.5,
            radius_km=200.0
        )
        bus.publish(event)
        events_sent += 1
        time.sleep(0.05)  # 50ms between events
    
    elapsed = time.time() - start_time
    print(f"✅ Sent {events_sent} events in {elapsed:.2f} seconds")
    print(f"   Throughput: {events_sent/elapsed:.1f} events/sec")

def show_statistics():
    """Show current statistics."""
    stats = bus.get_statistics()
    print("\n" + "="*70)
    print("📊 PUBLISHER STATISTICS")
    print("="*70)
    print(f"Events published: {stats['events_published']}")
    print(f"Events received: {stats['events_received']} (from others)")
    print(f"Connected: {stats['connected']}")
    print("="*70 + "\n")

# Main loop
try:
    while True:
        choice = input("\nEnter choice (0-9): ").strip()
        
        if choice == '1':
            publish_edinburgh_failure()
        elif choice == '2':
            publish_glasgow_failure()
        elif choice == '3':
            publish_aberdeen_failure()
        elif choice == '4':
            publish_carbon_tax_change()
        elif choice == '5':
            publish_ev_subsidy_change()
        elif choice == '6':
            publish_edinburgh_weather()
        elif choice == '7':
            publish_grid_stress()
        elif choice == '8':
            rapid_fire_test()
        elif choice == '9':
            show_statistics()
        elif choice == '0':
            break
        else:
            print("❌ Invalid choice. Enter 0-9.")
        
        # Small delay for visual separation
        time.sleep(0.1)

except KeyboardInterrupt:
    print("\n\n🛑 Shutting down publisher...")

finally:
    print("\n" + "="*70)
    print("📊 FINAL STATISTICS")
    print("="*70)
    
    stats = bus.get_statistics()
    print(f"Total events published: {stats['events_published']}")
    
    bus.close()
    print("\n✅ Publisher stopped cleanly")
