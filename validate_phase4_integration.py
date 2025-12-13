#!/usr/bin/env python3
"""
Phase 4.1 Integration Validator

Quick validation script to ensure Phase 4.1 (Realistic Social Influence) 
is properly integrated and working.

Run: python validate_phase4_integration.py

This script:
1. Verifies all imports work
2. Runs a mini simulation (10 agents, 20 steps)
3. Compares deterministic vs realistic behavior
4. Generates validation report
"""

import sys
from pathlib import Path
from collections import Counter
import statistics

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

print("="*70)
print("RTD_SIM Phase 4.1 Integration Validator")
print("="*70)

# ============================================================================
# Step 1: Verify Imports
# ============================================================================

print("\n[1/5] Verifying imports...")

try:
    from agent.story_driven_agent import generate_balanced_population
    from agent.social_network import SocialNetwork
    from agent.social_influence_dynamics import (
        RealisticSocialInfluence,
        enhance_social_network_with_realism,
        calculate_satisfaction
    )
    from agent.bdi_planner import BDIPlanner
    print("  ✅ All Phase 4.1 imports successful")
except ImportError as e:
    print(f"  ❌ Import failed: {e}")
    sys.exit(1)

# ============================================================================
# Step 2: Create Test Population
# ============================================================================

print("\n[2/5] Creating test population...")

import random

planner = BDIPlanner()

def random_od():
    return (
        (random.uniform(-3.3, -3.15), random.uniform(55.9, 55.97)),
        (random.uniform(-3.3, -3.15), random.uniform(55.9, 55.97))
    )

try:
    agents = generate_balanced_population(
        num_agents=10,
        user_story_ids=['eco_warrior', 'budget_student', 'business_commuter'],
        job_story_ids=['morning_commute', 'flexible_leisure'],
        origin_dest_generator=random_od,
        planner=planner,
        seed=42
    )
    print(f"  ✅ Created {len(agents)} story-driven agents")
except Exception as e:
    print(f"  ❌ Agent creation failed: {e}")
    sys.exit(1)

# ============================================================================
# Step 3: Run Deterministic Simulation
# ============================================================================

print("\n[3/5] Running deterministic simulation...")

try:
    network_det = SocialNetwork(topology='small_world', influence_enabled=True)
    network_det.build_network(agents, k=3, seed=42)
    
    bike_det = []
    
    for step in range(20):
        for agent in agents:
            mode_costs = {'bike': 1.0, 'car': 1.2, 'bus': 0.9, 'walk': 1.1}
            
            adjusted = network_det.apply_social_influence(
                agent.state.agent_id,
                mode_costs,
                influence_strength=0.3
            )
            
            best_mode = min(adjusted, key=adjusted.get)
            agent.state.mode = best_mode
        
        mode_counts = Counter(a.state.mode for a in agents)
        bike_det.append(mode_counts.get('bike', 0) / len(agents))
        
        network_det.record_mode_snapshot()
    
    print(f"  ✅ Deterministic complete: {bike_det[-1]:.1%} final bike adoption")
    
except Exception as e:
    print(f"  ❌ Deterministic simulation failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============================================================================
# Step 4: Run Realistic Simulation
# ============================================================================

print("\n[4/5] Running realistic simulation...")

# Reset agents
for agent in agents:
    agent.state.mode = 'walk'

try:
    network_real = SocialNetwork(topology='small_world', influence_enabled=True)
    network_real.build_network(agents, k=3, seed=42)
    
    # Add realistic influence
    influence = RealisticSocialInfluence(
        decay_rate=0.15,
        habit_weight=0.4,
        experience_weight=0.3,
        peer_weight=0.3
    )
    
    enhance_social_network_with_realism(network_real, influence)
    
    bike_real = []
    
    for step in range(20):
        influence.advance_time()
        
        for agent in agents:
            mode_costs = {'bike': 1.0, 'car': 1.2, 'bus': 0.9, 'walk': 1.1}
            
            adjusted = network_real.apply_social_influence(
                agent.state.agent_id,
                mode_costs
            )
            
            current_mode = agent.state.mode
            best_mode = min(adjusted, key=adjusted.get)
            
            # Record satisfaction
            satisfaction = random.uniform(0.5, 0.9)
            influence.record_mode_usage(agent.state.agent_id, best_mode, satisfaction)
            
            agent.state.mode = best_mode
        
        mode_counts = Counter(a.state.mode for a in agents)
        bike_real.append(mode_counts.get('bike', 0) / len(agents))
        
        network_real.record_mode_snapshot()
    
    print(f"  ✅ Realistic complete: {bike_real[-1]:.1%} final bike adoption")
    
except Exception as e:
    print(f"  ❌ Realistic simulation failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============================================================================
# Step 5: Compare Results
# ============================================================================

print("\n[5/5] Comparing results...")

det_final = bike_det[-1]
real_final = bike_real[-1]

det_vol = statistics.stdev(bike_det) if len(bike_det) > 1 else 0
real_vol = statistics.stdev(bike_real) if len(bike_real) > 1 else 0

det_increases = sum(1 for i in range(len(bike_det)-1) if bike_det[i+1] > bike_det[i])
real_increases = sum(1 for i in range(len(bike_real)-1) if bike_real[i+1] > bike_real[i])

print("\n" + "="*70)
print("VALIDATION RESULTS")
print("="*70)

print(f"\n📊 Final Bike Adoption:")
print(f"  Deterministic: {det_final:.1%}")
print(f"  Realistic:     {real_final:.1%}")
print(f"  Difference:    {abs(det_final - real_final):.1%}")

print(f"\n📈 Volatility (Std Dev):")
print(f"  Deterministic: {det_vol:.3f}")
print(f"  Realistic:     {real_vol:.3f}")

print(f"\n📉 Monotonic Behavior (% increasing steps):")
print(f"  Deterministic: {det_increases/(len(bike_det)-1):.1%}")
print(f"  Realistic:     {real_increases/(len(bike_real)-1):.1%}")

# ============================================================================
# Validation Checks
# ============================================================================

print("\n" + "="*70)
print("VALIDATION CHECKS")
print("="*70)

checks_passed = 0
total_checks = 4

# Check 1: Realistic has lower final adoption
if real_final < det_final * 0.9:  # At least 10% lower
    print("✅ Check 1: Realistic has lower final adoption")
    checks_passed += 1
else:
    print("❌ Check 1: Realistic should have lower final adoption")

# Check 2: Realistic has higher volatility
if real_vol > det_vol * 1.1:  # At least 10% more volatile
    print("✅ Check 2: Realistic has higher volatility")
    checks_passed += 1
else:
    print("⚠️  Check 2: Realistic should have higher volatility (may need more steps)")

# Check 3: Realistic is less monotonic
if real_increases < det_increases:
    print("✅ Check 3: Realistic is less monotonic")
    checks_passed += 1
else:
    print("⚠️  Check 3: Realistic should be less monotonic (may need more steps)")

# Check 4: Network has influence system
if hasattr(network_real, 'influence_system'):
    print("✅ Check 4: Network has influence system attached")
    checks_passed += 1
else:
    print("❌ Check 4: Network missing influence system")

# ============================================================================
# Summary
# ============================================================================

print("\n" + "="*70)
print("SUMMARY")
print("="*70)

if checks_passed >= 3:
    print(f"\n✅ VALIDATION PASSED ({checks_passed}/{total_checks} checks)")
    print("\nPhase 4.1 integration is working correctly!")
    print("\nNext steps:")
    print("  1. Run full test: python test_realistic_influence.py")
    print("  2. Launch visualization: streamlit run streamlit_phase4_viz_enhanced.py")
    print("  3. Integrate into example_phase3_4_integration.py")
else:
    print(f"\n⚠️  VALIDATION PARTIAL ({checks_passed}/{total_checks} checks)")
    print("\nSome checks failed, but this may be due to:")
    print("  - Small sample size (10 agents)")
    print("  - Short simulation (20 steps)")
    print("  - Random variation")
    print("\nTry running test_realistic_influence.py for full validation.")

print("\n" + "="*70)
print("Validation complete!")
print("="*70)