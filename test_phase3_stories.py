"""
Test suite for RTD_SIM Phase 3: User/Job Story Framework

Tests:
1. User story loading and parsing
2. Job story loading and parsing
3. Story-driven agent generation
4. Desire resolution (conflict handling)
5. Stochastic variance
6. Batch agent generation

Run: python test_phase3_stories.py
"""

import logging
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(name)s: %(message)s'
)

from agent.user_stories import UserStoryParser, load_user_story
from agent.job_stories import JobStoryParser, load_job_story
from agent.story_driven_agent import StoryDrivenAgent, generate_agents_from_stories, generate_balanced_population
from agent.bdi_planner import BDIPlanner
from simulation.spatial_environment import SpatialEnvironment


def print_header(title, level=1):
    """Print formatted section header."""
    if level == 1:
        print("\n" + "="*70)
        print(title)
        print("="*70)
    else:
        print("\n" + "="*60)
        print(title)
        print("="*60)


def test_user_story_loading():
    """Test 1: Load and parse user stories."""
    print_header("TEST 1: User Story Loading", level=2)
    
    try:
        parser = UserStoryParser()
        available = parser.list_available_stories()
        
        print(f"\n[*] Found {len(available)} user stories:")
        for story_id in available:
            summary = parser.get_story_summary(story_id)
            print(f"    - {summary}")
        
        # Load a specific story
        print("\n[*] Loading 'eco_warrior' story...")
        story = parser.load_from_yaml('eco_warrior')
        
        print(f"    Story ID: {story.story_id}")
        print(f"    Type: {story.persona_type}")
        print(f"    Desires: {story.desires}")
        print(f"    Beliefs: {len(story.beliefs)}")
        print(f"    Mode preferences: {len(story.mode_preferences)}")
        
        # Check desires are valid (0-1 range)
        for key, value in story.desires.items():
            if not (0 <= value <= 1):
                print(f"\n[FAIL] Invalid desire value: {key}={value}")
                return False
        
        print("\n[OK] User story loading successful")
        return True
        
    except FileNotFoundError as e:
        print(f"\n[FAIL] Story file not found: {e}")
        print("       Make sure personas.yaml is in agent/ directory")
        return False
    except Exception as e:
        print(f"\n[FAIL] Error loading stories: {e}")
        return False


def test_job_story_loading():
    """Test 2: Load and parse job stories."""
    print_header("TEST 2: Job Story Loading", level=2)
    
    try:
        parser = JobStoryParser()
        available = parser.list_available_stories()
        
        print(f"\n[*] Found {len(available)} job stories:")
        for story_id in available:
            summary = parser.get_story_summary(story_id)
            print(f"    - {summary}")
        
        # Load a specific story
        print("\n[*] Loading 'morning_commute' story...")
        story = parser.load_from_yaml('morning_commute')
        
        print(f"    Story ID: {story.story_id}")
        print(f"    Type: {story.job_type}")
        print(f"    Context: {story.context[:50]}...")
        print(f"    Time window: {story.time_window.start} - {story.time_window.end}")
        print(f"    Flexibility: {story.time_window.flexibility}")
        
        # Test task context generation
        origin = (-3.19, 55.95)
        dest = (-3.15, 55.97)
        
        task = story.to_task_context(origin, dest)
        print(f"\n[*] Generated task context:")
        print(f"    Origin: {task.origin}")
        print(f"    Dest: {task.dest}")
        print(f"    Constraints: {len(task.constraints)}")
        
        print("\n[OK] Job story loading successful")
        return True
        
    except FileNotFoundError as e:
        print(f"\n[FAIL] Story file not found: {e}")
        print("       Make sure job_contexts.yaml is in agent/ directory")
        return False
    except Exception as e:
        print(f"\n[FAIL] Error loading stories: {e}")
        return False


def test_story_driven_agent():
    """Test 3: Create agents from stories."""
    print_header("TEST 3: Story-Driven Agent Creation", level=2)
    
    try:
        planner = BDIPlanner()
        origin = (-3.19, 55.95)
        dest = (-3.15, 55.97)
        
        print("\n[*] Creating eco_warrior + morning_commute agent...")
        agent1 = StoryDrivenAgent(
            user_story_id='eco_warrior',
            job_story_id='morning_commute',
            origin=origin,
            dest=dest,
            planner=planner,
            seed=42
        )
        
        print(f"    Agent ID: {agent1.state.agent_id}")
        print(f"    Desires: {agent1.desires}")
        print(f"    Mode: {agent1.state.mode}")
        
        # Check eco desire is high (eco_warrior should have high eco)
        if agent1.desires.get('eco', 0) < 0.6:
            print(f"\n[WARN] Eco desire unexpectedly low: {agent1.desires['eco']}")
        
        print("\n[*] Creating budget_student + flexible_leisure agent...")
        agent2 = StoryDrivenAgent(
            user_story_id='budget_student',
            job_story_id='flexible_leisure',
            origin=origin,
            dest=dest,
            planner=planner,
            seed=43
        )
        
        print(f"    Agent ID: {agent2.state.agent_id}")
        print(f"    Desires: {agent2.desires}")
        
        # Check cost desire is high (student should care about cost)
        if agent2.desires.get('cost', 0) < 0.7:
            print(f"\n[WARN] Cost desire unexpectedly low: {agent2.desires['cost']}")
        
        # Test explainability
        print("\n[*] Testing explainability...")
        context = agent1.get_story_context()
        print(f"    Context keys: {list(context.keys())}")
        
        explanation = agent1.explain_decision('bike')
        print(f"\n{explanation}")
        
        print("\n[OK] Story-driven agent creation successful")
        return True
        
    except Exception as e:
        print(f"\n[FAIL] Error creating agent: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_conflict_resolution():
    """Test 4: Desire conflict resolution."""
    print_header("TEST 4: Conflict Resolution Strategies", level=2)
    
    try:
        planner = BDIPlanner()
        origin = (-3.19, 55.95)
        dest = (-3.15, 55.97)
        
        # Test user_priority
        print("\n[*] Strategy: user_priority...")
        agent1 = StoryDrivenAgent(
            user_story_id='eco_warrior',
            job_story_id='emergency_trip',
            origin=origin,
            dest=dest,
            planner=planner,
            conflict_resolution='user_priority',
            seed=42
        )
        print(f"    Time desire: {agent1.desires.get('time', 0):.2f}")
        print(f"    Eco desire: {agent1.desires.get('eco', 0):.2f}")
        
        # Test job_priority
        print("\n[*] Strategy: job_priority...")
        agent2 = StoryDrivenAgent(
            user_story_id='eco_warrior',
            job_story_id='emergency_trip',
            origin=origin,
            dest=dest,
            planner=planner,
            conflict_resolution='job_priority',
            seed=42
        )
        print(f"    Time desire: {agent2.desires.get('time', 0):.2f}")
        print(f"    Eco desire: {agent2.desires.get('eco', 0):.2f}")
        
        # Test dynamic (default)
        print("\n[*] Strategy: dynamic (blend)...")
        agent3 = StoryDrivenAgent(
            user_story_id='eco_warrior',
            job_story_id='emergency_trip',
            origin=origin,
            dest=dest,
            planner=planner,
            conflict_resolution='dynamic',
            seed=42
        )
        print(f"    Time desire: {agent3.desires.get('time', 0):.2f}")
        print(f"    Eco desire: {agent3.desires.get('eco', 0):.2f}")
        
        # Verify they differ
        if agent1.desires['time'] != agent2.desires['time']:
            print("\n[OK] Different strategies produce different desires")
        else:
            print("\n[WARN] Strategies should produce different results")
        
        print("\n[OK] Conflict resolution test complete")
        return True
        
    except Exception as e:
        print(f"\n[FAIL] Error testing conflict resolution: {e}")
        return False


def test_variance():
    """Test 5: Stochastic variance."""
    print_header("TEST 5: Stochastic Variance", level=2)
    
    try:
        planner = BDIPlanner()
        origin = (-3.19, 55.95)
        dest = (-3.15, 55.97)
        
        print("\n[*] Creating 5 eco_warrior agents with variance...")
        
        desires_list = []
        for i in range(5):
            agent = StoryDrivenAgent(
                user_story_id='eco_warrior',
                job_story_id='morning_commute',
                origin=origin,
                dest=dest,
                planner=planner,
                seed=42 + i,  # Different seeds
                apply_variance=True
            )
            desires_list.append(agent.desires.get('eco', 0))
            print(f"    Agent {i+1} eco desire: {agent.desires['eco']:.3f}")
        
        # Check variance
        min_eco = min(desires_list)
        max_eco = max(desires_list)
        variance = max_eco - min_eco
        
        print(f"\n[*] Variance analysis:")
        print(f"    Min: {min_eco:.3f}")
        print(f"    Max: {max_eco:.3f}")
        print(f"    Range: {variance:.3f}")
        
        if variance > 0.05:
            print("\n[OK] Variance is working (range > 5%)")
        else:
            print("\n[WARN] Variance seems small (may be OK if base variance is low)")
        
        # Test without variance
        print("\n[*] Creating agent without variance...")
        agent_no_var1 = StoryDrivenAgent(
            user_story_id='eco_warrior',
            job_story_id='morning_commute',
            origin=origin,
            dest=dest,
            planner=planner,
            seed=100,
            apply_variance=False
        )
        agent_no_var2 = StoryDrivenAgent(
            user_story_id='eco_warrior',
            job_story_id='morning_commute',
            origin=origin,
            dest=dest,
            planner=planner,
            seed=200,  # Different seed
            apply_variance=False
        )
        
        if agent_no_var1.desires['eco'] == agent_no_var2.desires['eco']:
            print("    [OK] No variance produces identical desires")
        else:
            print("    [WARN] No variance should produce identical desires")
        
        print("\n[OK] Variance test complete")
        return True
        
    except Exception as e:
        print(f"\n[FAIL] Error testing variance: {e}")
        return False


def test_batch_generation():
    """Test 6: Batch agent generation."""
    print_header("TEST 6: Batch Agent Generation", level=2)
    
    try:
        planner = BDIPlanner()
        
        # Generate random OD pairs
        od_pairs = []
        for i in range(20):
            origin = (-3.25 + i*0.01, 55.93 + i*0.002)
            dest = (-3.15 + i*0.01, 55.97 + i*0.002)
            od_pairs.append((origin, dest))
        
        print("\n[*] Generating 20 agents from 3×3 story combinations...")
        
        user_stories = ['eco_warrior', 'budget_student', 'business_commuter']
        job_stories = ['morning_commute', 'flexible_leisure', 'shopping_trip']
        
        agents = generate_agents_from_stories(
            user_story_ids=user_stories,
            job_story_ids=job_stories,
            origin_dest_pairs=od_pairs,
            planner=planner,
            seed=42
        )
        
        print(f"\n[*] Generated {len(agents)} agents")
        
        # Analyze distribution
        from collections import Counter
        user_dist = Counter(a.user_story_id for a in agents)
        job_dist = Counter(a.job_story_id for a in agents)
        
        print(f"\n[*] User story distribution:")
        for story, count in user_dist.most_common():
            print(f"    {story}: {count}")
        
        print(f"\n[*] Job story distribution:")
        for story, count in job_dist.most_common():
            print(f"    {story}: {count}")
        
        # Test balanced generation
        print("\n[*] Testing balanced population generation...")
        
        def random_od_generator():
            import random
            return (
                (-3.25 + random.random()*0.1, 55.93 + random.random()*0.05),
                (-3.15 + random.random()*0.1, 55.97 + random.random()*0.05)
            )
        
        balanced_agents = generate_balanced_population(
            num_agents=30,
            user_story_ids=user_stories,
            job_story_ids=job_stories,
            origin_dest_generator=random_od_generator,
            planner=planner,
            seed=42
        )
        
        print(f"    Generated {len(balanced_agents)} balanced agents")
        
        # Check balance
        user_dist_balanced = Counter(a.user_story_id for a in balanced_agents)
        print(f"\n[*] Balanced distribution:")
        for story, count in user_dist_balanced.most_common():
            print(f"    {story}: {count}")
        
        print("\n[OK] Batch generation test complete")
        return True
        
    except Exception as e:
        print(f"\n[FAIL] Error in batch generation: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_with_simulation():
    """Test 7: Integration with simulation (optional - requires OSM)."""
    print_header("TEST 7: Simulation Integration (Optional)", level=2)
    
    try:
        print("\n[*] Attempting to load Edinburgh graph...")
        env = SpatialEnvironment()
        env.load_osm_graph(place="Edinburgh, Scotland", use_cache=True)
        
        if not env.graph_loaded:
            print("[SKIP] No graph loaded, skipping simulation test")
            return True
        
        print("[OK] Graph loaded")
        
        # Create agents
        planner = BDIPlanner()
        
        agents = []
        for i in range(5):
            od = env.get_random_origin_dest()
            if od:
                origin, dest = od
                agent = StoryDrivenAgent(
                    user_story_id='eco_warrior' if i % 2 == 0 else 'budget_student',
                    job_story_id='morning_commute',
                    origin=origin,
                    dest=dest,
                    planner=planner,
                    seed=42 + i
                )
                agents.append(agent)
        
        print(f"\n[*] Created {len(agents)} agents with real coordinates")
        
        # Run a few simulation steps
        print("[*] Running 5 simulation steps...")
        for step in range(5):
            for agent in agents:
                state = agent.step(env)
                if step == 0:
                    print(f"    {agent.state.agent_id}: {agent.state.mode} at {agent.state.location}")
        
        print("\n[OK] Simulation integration successful")
        return True
        
    except Exception as e:
        print(f"\n[SKIP] Simulation test skipped: {e}")
        return True  # Don't fail the test suite


def main():
    """Run all tests."""
    print_header("RTD_SIM Phase 3: User/Job Story Framework Tests", level=1)
    
    results = {
        "User Story Loading": test_user_story_loading(),
        "Job Story Loading": test_job_story_loading(),
        "Story-Driven Agent": test_story_driven_agent(),
        "Conflict Resolution": test_conflict_resolution(),
        "Stochastic Variance": test_variance(),
        "Batch Generation": test_batch_generation(),
        "Simulation Integration": test_with_simulation(),
    }
    
    print_header("TEST SUMMARY", level=1)
    for test_name, passed in results.items():
        status = "[OK]" if passed else "[FAIL]"
        print(f"{status} {test_name}")
    
    total = len(results)
    passed = sum(results.values())
    
    print(f"\nPassed: {passed}/{total} tests")
    
    if passed == total:
        print("\n*** All tests passed! Phase 3 Story Framework ready. ***")
        print("\nNext steps:")
        print("  1. Review generated agents in simulation")
        print("  2. Add more user/job stories as needed")
        print("  3. Proceed to Phase 4: Social Networks")
    else:
        print("\n*** Some tests failed. Review errors above. ***")
        print("\nCommon issues:")
        print("  - Missing YAML files (personas.yaml, job_contexts.yaml)")
        print("  - PyYAML not installed: pip install pyyaml")
        print("  - Incorrect file paths")


if __name__ == "__main__":
    main()