#!/usr/bin/env python3
"""
test_simulation_event_system.py

Standalone test to diagnose event system integration issues.
Runs a mini-simulation without Streamlit to capture all logs.
"""

import sys
import os
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)s:%(name)s:%(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('event_system_test.log', mode='w')
    ]
)

logger = logging.getLogger(__name__)

print("="*80)
print("🧪 EVENT SYSTEM INTEGRATION TEST")
print("="*80)
print()

# ============================================================================
# TEST SETUP
# ============================================================================

print("📦 Phase 1: Imports")
print("-" * 80)

try:
    from events.event_bus_safe import SafeEventBus
    from events.event_types import PolicyChangeEvent, EventType
    from agent.story_driven_agent import StoryDrivenAgent
    from scenarios.dynamic_policy_engine import DynamicPolicyEngine
    from scenarios.scenario_manager import ScenarioManager
    from simulation.config.simulation_config import SimulationConfig
    
    print("✅ All imports successful")
except Exception as e:
    print(f"❌ Import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()

# ============================================================================
# CREATE EVENT BUS
# ============================================================================

print("📦 Phase 2: Event Bus Initialization")
print("-" * 80)

try:
    # Create event bus (force in-memory for testing)
    event_bus = SafeEventBus(enable_redis=False)
    event_bus.start_listening()
    
    mode = event_bus.get_mode()
    print(f"✅ Event bus created: mode={mode}")
    print(f"✅ Event bus available: {event_bus.is_available()}")
except Exception as e:
    print(f"❌ Event bus creation failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()

# ============================================================================
# CREATE AGENTS AND REGISTER
# ============================================================================

print("📦 Phase 3: Agent Creation & Registration")
print("-" * 80)

agents = []
agent_locations = [
    (55.9533, -3.1883),  # Edinburgh center
    (55.9500, -3.1800),  # Edinburgh nearby
    (55.9600, -3.2000),  # Edinburgh outskirts
]

try:
    for i, (lat, lon) in enumerate(agent_locations):
        agent_id = f"test_agent_{i+1}"
        
        # Create agent
        agent = StoryDrivenAgent(
            user_story_id='business_commuter',
            job_story_id='commute_flexible',
            origin=(lon, lat),
            dest=(lon + 0.01, lat + 0.01),
            agent_id=agent_id
        )
        
        print(f"✅ Created agent: {agent.state.agent_id}")
        print(f"   Location: {agent.state.location}")
        
        # CRITICAL: Register with event bus BEFORE subscribing
        success = event_bus.register_agent(
            agent.state.agent_id,
            lat=lat,
            lon=lon,
            perception_radius_km=10.0
        )
        
        if success:
            print(f"✅ Registered {agent.state.agent_id} with event bus")
        else:
            print(f"❌ Failed to register {agent.state.agent_id}")
        
        # Subscribe to events
        agent.subscribe_to_events(event_bus)
        
        if hasattr(agent, 'event_perception_enabled') and agent.event_perception_enabled:
            print(f"✅ {agent.state.agent_id} subscribed to events")
        else:
            print(f"⚠️ {agent.state.agent_id} NOT subscribed")
        
        agents.append(agent)
        print()
    
    print(f"✅ Created and registered {len(agents)} agents")
    
except Exception as e:
    print(f"❌ Agent creation failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()

# ============================================================================
# CREATE POLICY ENGINE (OPTIONAL)
# ============================================================================

print("📦 Phase 4: Policy Engine Setup")
print("-" * 80)

try:
    config = SimulationConfig()
    scenario_mgr = ScenarioManager()
    policy_engine = DynamicPolicyEngine(config, scenario_mgr)
    policy_engine.set_event_bus(event_bus)
    
    print("✅ Policy engine created and connected")
except Exception as e:
    print(f"⚠️ Policy engine setup failed: {e}")
    policy_engine = None

print()

# ============================================================================
# PUBLISH TEST EVENT
# ============================================================================

print("📦 Phase 5: Publishing Test Event")
print("-" * 80)

try:
    # Create policy change event at Edinburgh center
    event = PolicyChangeEvent(
        parameter='carbon_tax',
        old_value=50.0,
        new_value=100.0,
        lat=55.9533,   # Edinburgh center
        lon=-3.1883,
        radius_km=20.0,  # 20km radius
        source='test_script'
    )
    
    print(f"📢 Publishing event: {event.type}")
    print(f"   Parameter: {event.payload['parameter']}")
    print(f"   Location: ({event.spatial.latitude}, {event.spatial.longitude})")
    print(f"   Radius: {event.spatial.radius_km} km")
    
    success = event_bus.publish(event)
    
    if success:
        print(f"✅ Event published successfully")
    else:
        print(f"❌ Event publish failed")
    
except Exception as e:
    print(f"❌ Event publishing failed: {e}")
    import traceback
    traceback.print_exc()

print()

# ============================================================================
# WAIT FOR EVENT PROCESSING
# ============================================================================

print("📦 Phase 6: Waiting for Event Processing")
print("-" * 80)

import time
print("⏳ Waiting 1 second for callbacks...")
time.sleep(1)

print()

# ============================================================================
# CHECK AGENT PERCEPTION
# ============================================================================

print("📦 Phase 7: Checking Agent Perception")
print("-" * 80)

total_perceived = 0
for agent in agents:
    perceived = agent.get_perceived_policies()
    
    if perceived:
        print(f"✅ {agent.state.agent_id}: Perceived {len(perceived)} policies")
        for param, value in perceived.items():
            print(f"   - {param}: {value}")
        total_perceived += len(perceived)
    else:
        print(f"❌ {agent.state.agent_id}: No policies perceived")

print()
print(f"📊 Total policies perceived across all agents: {total_perceived}")

print()

# ============================================================================
# CHECK EVENT BUS STATISTICS
# ============================================================================

print("📦 Phase 8: Event Bus Statistics")
print("-" * 80)

try:
    stats = event_bus.get_statistics()
    print(f"Mode: {stats['mode']}")
    print(f"Events published: {stats['events_published']}")
    print(f"Events received: {stats['events_received']}")
    print(f"Active subscriptions: {stats['active_subscriptions']}")
    
    if stats['events_published'] > 0 and stats['events_received'] == 0:
        print()
        print("⚠️ WARNING: Events published but none received!")
        print("   This indicates a spatial filtering or callback issue.")
    elif stats['events_received'] > 0:
        print()
        print(f"✅ SUCCESS: {stats['events_received']} events delivered!")
    
except Exception as e:
    print(f"❌ Could not get statistics: {e}")

print()

# ============================================================================
# CLEANUP
# ============================================================================

print("📦 Phase 9: Cleanup")
print("-" * 80)

try:
    event_bus.close()
    print("✅ Event bus closed")
except Exception as e:
    print(f"⚠️ Cleanup error: {e}")

print()

# ============================================================================
# FINAL SUMMARY
# ============================================================================

print("="*80)
print("📊 TEST SUMMARY")
print("="*80)
print()

if total_perceived > 0:
    print("🎉 SUCCESS! Event system is working correctly!")
    print(f"   - {len(agents)} agents created")
    print(f"   - {total_perceived} policy changes perceived")
    print()
    print("✅ Phase 6.2b integration is COMPLETE!")
else:
    print("❌ ISSUE: Agents not perceiving events")
    print()
    print("Possible causes:")
    print("  1. Spatial filtering too strict (check distances)")
    print("  2. Callbacks not being triggered")
    print("  3. Agent registration issues")
    print()
    print("Check event_system_test.log for detailed logs")

print()
print("="*80)
print()
print(f"📄 Detailed logs saved to: event_system_test.log")
print()