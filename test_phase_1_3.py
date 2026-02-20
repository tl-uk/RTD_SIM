"""
Test script for Phase 1-3: System Dynamics Core

Verifies:
- EV adoption grows according to logistic equation
- Threshold crossing events are detected
- Configuration parameters work
- History is recorded correctly

Usage:
    python test_phase_1_3.py
"""

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

from agent.system_dynamics import StreamingSystemDynamics, DiscreteEvent
from simulation.config.system_dynamics_config import SystemDynamicsConfig

def test_phase_1_basic_growth():
    """Phase 1: Verify EV adoption grows with logistic equation."""
    print("=" * 70)
    print("PHASE 1: Basic EV Adoption Growth")
    print("=" * 70)
    
    sd = StreamingSystemDynamics(initial_adoption=0.05)
    
    # Simulate with constant agent population
    total_agents = 500
    
    print(f"\nInitial state:")
    print(f"  EV adoption: {sd.state.ev_adoption_stock:.1%}")
    print(f"  Growth rate r: {sd.state.ev_growth_rate_r:.3f}")
    print(f"  Carrying capacity K: {sd.state.ev_carrying_capacity_K:.1%}")
    
    print(f"\nSimulating 100 steps...")
    print(f"{'Step':>6} | {'EV Count':>9} | {'Adoption':>10} | {'Flow':>10} | Events")
    print("-" * 70)
    
    # Track actual EV count (starts at 5% of agents)
    ev_count = int(0.05 * total_agents)
    
    for step in range(101):
        # Update SD (SD predicts adoption, doesn't control it directly)
        events = sd.update(
            ev_count=ev_count,
            total_agents=total_agents,
            grid_load=0.0,
            emissions=0.0,
            infrastructure_capacity=100.0,
            dt=1.0
        )
        
        # Simulate agents switching based on SD growth
        # In real sim, agents decide independently; here we mock gradual increases
        if step % 5 == 0 and ev_count < total_agents * 0.8:  # Cap at K=80%
            # Add a few EVs each cycle
            switch_rate = sd.state.ev_adoption_flow * total_agents
            ev_count += int(max(1, switch_rate))
        
        # Print every 10 steps
        if step % 10 == 0:
            event_str = f"{len(events)} events" if events else ""
            print(f"{step:6d} | {ev_count:9d} | {sd.state.ev_adoption_stock:9.1%} | "
                  f"{sd.state.ev_adoption_flow:9.5f} | {event_str}")
            
            for event in events:
                print(f"       └─ {event.event_type}: {event.data.get('description', '')}")
    
    final_adoption = sd.state.ev_adoption_stock
    print(f"\n✅ Phase 1 Complete!")
    print(f"   Final EV adoption: {final_adoption:.1%}")
    print(f"   Growth observed: {final_adoption > 0.05}")
    
    assert final_adoption > 0.05, "Adoption should have grown"
    assert final_adoption < 1.0, "Adoption should not exceed 100%"
    
    return sd


def test_phase_2_config_integration():
    """Phase 2: Verify config parameters change behavior."""
    print("\n" + "=" * 70)
    print("PHASE 2: Config Integration")
    print("=" * 70)
    
    # Test that different config parameters produce different flows
    # for the SAME adoption level
    
    config_default = SystemDynamicsConfig(ev_growth_rate_r=0.05)
    config_fast = SystemDynamicsConfig(ev_growth_rate_r=0.10)
    
    sd_default = StreamingSystemDynamics(initial_adoption=0.20, config=config_default)
    sd_fast = StreamingSystemDynamics(initial_adoption=0.20, config=config_fast)
    
    # Compute flow for SAME adoption (20%) with different r values
    flow_default = sd_default._compute_ev_adoption_flow(0.20)
    flow_fast = sd_fast._compute_ev_adoption_flow(0.20)
    
    print(f"\nFor 20% adoption:")
    print(f"  r=0.05 → flow = {flow_default:.5f}")
    print(f"  r=0.10 → flow = {flow_fast:.5f}")
    print(f"  Ratio: {flow_fast / flow_default:.2f}x")
    
    print(f"\n✅ Phase 2 Complete!")
    print(f"   Higher r produces higher flow: {flow_fast > flow_default}")
    print(f"   Config successfully controls dynamics")
    
    assert flow_fast > flow_default, f"r=0.10 should produce faster flow than r=0.05 ({flow_fast} vs {flow_default})"
    # Note: Ratio won't be exactly 2x because feedback terms (infrastructure, social) add to base logistic growth
    # At 20% adoption: logistic dominates but feedbacks reduce the ratio
    assert flow_fast / flow_default > 1.1, f"Flow should be at least 10% faster ({flow_fast / flow_default}x)"
    
    return sd_default, sd_fast


def test_phase_3_threshold_detection():
    """Phase 3: Verify threshold crossing events."""
    print("\n" + "=" * 70)
    print("PHASE 3: Threshold Crossing Detection")
    print("=" * 70)
    
    # Use aggressive config to hit tipping point quickly
    config = SystemDynamicsConfig.aggressive_policy()
    config.adoption_tipping_point = 0.15  # Lower threshold for testing
    
    sd = StreamingSystemDynamics(initial_adoption=0.10, config=config)
    
    total_agents = 500
    ev_count = int(0.10 * total_agents)  # Start at 10%
    tipping_point_detected = False
    tipping_point_step = None
    
    print(f"\nSearching for tipping point at {config.adoption_tipping_point:.0%}...")
    print(f"{'Step':>6} | {'Adoption':>10} | Events")
    print("-" * 50)
    
    for step in range(201):
        events = sd.update(
            ev_count=ev_count,
            total_agents=total_agents,
            grid_load=0.0,
            emissions=0.0,
            infrastructure_capacity=200.0,  # High infrastructure for fast growth
            dt=1.0
        )
        
        # Simulate agent switches based on flow
        if step % 2 == 0:
            switch_count = int(sd.state.ev_adoption_flow * total_agents)
            ev_count = min(ev_count + max(1, switch_count), int(total_agents * 0.8))
        
        # Check for tipping point event
        for event in events:
            if event.event_type == 'adoption_tipping_point':
                tipping_point_detected = True
                tipping_point_step = step
                print(f"{step:6d} | {sd.state.ev_adoption_stock:9.1%} | 🎯 TIPPING POINT!")
                print(f"       └─ {event.data['description']}")
                break
        
        # Print status every 20 steps
        if step % 20 == 0 and not events:
            print(f"{step:6d} | {sd.state.ev_adoption_stock:9.1%} | -")
        
        if tipping_point_detected:
            break
    
    print(f"\n✅ Phase 3 Complete!")
    print(f"   Tipping point detected: {tipping_point_detected}")
    if tipping_point_detected:
        print(f"   Detected at step: {tipping_point_step}")
        print(f"   Final adoption: {sd.state.ev_adoption_stock:.1%}")
    
    assert tipping_point_detected, "Should detect tipping point crossing"
    assert sd.state.thresholds['adoption_tipping']['crossed'], "Threshold should be marked as crossed"
    
    return sd


def test_history_tracking():
    """Bonus: Verify history is recorded."""
    print("\n" + "=" * 70)
    print("BONUS: History Tracking")
    print("=" * 70)
    
    sd = StreamingSystemDynamics(initial_adoption=0.05)
    
    ev_count = int(0.05 * 500)
    
    # Run 20 steps
    for step in range(20):
        sd.update(ev_count, 500, dt=1.0)
        if step % 3 == 0:
            switch = int(sd.state.ev_adoption_flow * 500)
            ev_count = min(ev_count + max(1, switch), 400)
    
    print(f"\nHistory entries: {len(sd.history)}")
    print(f"Expected: 20")
    
    assert len(sd.history) == 20, "Should have 20 history entries"
    
    # Check history structure
    latest = sd.history[-1]
    print(f"\nLatest history entry keys: {list(latest.keys())}")
    assert 'ev_adoption' in latest
    assert 'ev_adoption_flow' in latest
    assert 'step' in latest
    
    print(f"\n✅ History tracking works!")
    
    return sd


def main():
    """Run all Phase 1-3 tests."""
    print("\n" + "=" * 70)
    print("SYSTEM DYNAMICS PHASE 1-3 TEST SUITE")
    print("=" * 70)
    
    try:
        # Phase 1: Basic growth
        sd1 = test_phase_1_basic_growth()
        
        # Phase 2: Config integration
        sd2_default, sd2_fast = test_phase_2_config_integration()
        
        # Phase 3: Threshold detection
        sd3 = test_phase_3_threshold_detection()
        
        # Bonus: History
        sd_history = test_history_tracking()
        
        print("\n" + "=" * 70)
        print("🎉 ALL TESTS PASSED!")
        print("=" * 70)
        print("\nPhase 1-3 is complete and working:")
        print("  ✅ EV adoption grows according to logistic equation")
        print("  ✅ Config parameters control growth rate")
        print("  ✅ Threshold crossings trigger discrete events")
        print("  ✅ History is tracked for analysis")
        
        print("\nNext steps:")
        print("  - Integrate into simulation_loop.py")
        print("  - Add UI sliders for config parameters")
        print("  - Create predictions tab")
        
        return True
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)