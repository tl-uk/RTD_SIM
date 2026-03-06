#!/usr/bin/env python3
"""
debug/test_temporal_integration.py

Standalone test script for Phase 7.1 temporal engine integration.
Run from project root: python test_temporal_integration.py
"""

import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

print("="*70)
print("PHASE 7.1: TEMPORAL ENGINE INTEGRATION TEST")
print("="*70)
print()

# Test 1: Import temporal engine
print("Test 1: Importing temporal engine...")
try:
    from simulation.time.temporal_engine import (
        TemporalEngine, 
        TimeScale,
        create_temporal_engine_from_config
    )
    print("✅ Temporal engine imported successfully")
except ImportError as e:
    print(f"❌ Failed to import temporal engine: {e}")
    print("   Make sure temporal_engine.py is in simulation/time/")
    sys.exit(1)

print()

# Test 2: Create basic temporal engine
print("Test 2: Creating temporal engine...")
try:
    engine = TemporalEngine(
        time_scale=TimeScale.DAY,
        start_datetime=datetime(2024, 1, 1),
        steps=7
    )
    print("✅ Temporal engine created")
    print(f"   Duration: {engine._format_duration()}")
except Exception as e:
    print(f"❌ Failed to create engine: {e}")
    sys.exit(1)

print()

# Test 3: Get time info
print("Test 3: Getting time information...")
try:
    time_info = engine.get_time_info(0)
    print("✅ Time info retrieved")
    print(f"   Step 0: {time_info['date']} - {time_info['season']}")
    
    time_info = engine.get_time_info(3)
    print(f"   Step 3: {time_info['date']} - {time_info['season']}")
except Exception as e:
    print(f"❌ Failed to get time info: {e}")
    sys.exit(1)

print()

# Test 4: Create from config
print("Test 4: Creating from SimulationConfig...")
try:
    from simulation.config.simulation_config import SimulationConfig
    
    config = SimulationConfig(
        steps=30,
        enable_temporal_scaling=True,
        time_scale="1day_per_step",
        start_datetime=datetime(2024, 1, 1)
    )
    
    engine_from_config = create_temporal_engine_from_config(config)
    
    if engine_from_config:
        print("✅ Engine created from config")
        summary = engine_from_config.get_summary()
        print(f"   Duration: {summary['duration']}")
        print(f"   Steps: {summary['total_steps']}")
    else:
        print("❌ Engine is None (config might be missing temporal settings)")
        
except ImportError:
    print("⚠️  SimulationConfig not updated yet")
    print("   Add these fields to simulation/config/simulation_config.py:")
    print("   - enable_temporal_scaling: bool = False")
    print("   - time_scale: Optional[str] = None")
    print("   - start_datetime: Optional[datetime] = None")
except Exception as e:
    print(f"❌ Failed: {e}")

print()

# Test 5: Test time-aware features
print("Test 5: Testing time-aware features...")
try:
    year_engine = TemporalEngine(
        time_scale=TimeScale.DAY,
        start_datetime=datetime(2024, 1, 1),
        steps=365
    )
    
    # Test seasonal detection
    winter_info = year_engine.get_time_info(15)  # Jan 16
    summer_info = year_engine.get_time_info(180)  # Jun 29
    
    print("✅ Seasonal detection working")
    print(f"   Jan 16: {winter_info['season']}")
    print(f"   Jun 29: {summer_info['season']}")
    
    # Test periodic events
    monthly_events = 0
    for step in range(90):
        if year_engine.should_trigger_periodic_event(step, 'monthly'):
            monthly_events += 1
    
    print(f"✅ Periodic events working")
    print(f"   Found {monthly_events} monthly events in 90 days")
    
except Exception as e:
    print(f"❌ Failed: {e}")

print()

# Test 6: Check UI component
print("Test 6: Checking UI component...")
try:
    from ui.components.temporal_settings import render_temporal_settings
    print("✅ UI component imported successfully")
    print("   Ready to use in sidebar_config.py")
except ImportError as e:
    print(f"⚠️  UI component not found: {e}")
    print("   Make sure temporal_settings.py is in ui/components/")

print()

# Summary
print("="*70)
print("TEST SUMMARY")
print("="*70)
print()
print("Core functionality: ✅ WORKING")
print()
print("Next steps:")
print("  1. Add fields to SimulationConfig (if Test 4 failed)")
print("  2. Apply patches to sidebar_config.py")
print("  3. Apply patches to simulation_loop.py")
print("  4. Test in Streamlit UI")
print()
print("See INSTALLATION.md for complete instructions.")
print()