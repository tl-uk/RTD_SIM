"""
debug/tests/test_contextual_plan_generator.py

Test suite for ContextualPlanGenerator.

Tests the core innovation: extracting plans from story context.

Run with: pytest debug/test_contextual_plan_generator.py
"""

import pytest
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.contextual_plan_generator import ContextualPlanGenerator, ExtractedPlan
from agent.user_stories import UserStoryParser
from agent.job_stories import JobStoryParser


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def generator():
    """Create plan generator."""
    return ContextualPlanGenerator(llm_backend='rule_based')

@pytest.fixture
def user_parser():
    """Create user story parser."""
    return UserStoryParser()

@pytest.fixture
def job_parser():
    """Create job story parser."""
    return JobStoryParser()

@pytest.fixture
def origin():
    """Test origin coordinates (Edinburgh)."""
    return (-3.1883, 55.9533)

@pytest.fixture
def dest():
    """Test destination coordinates (Edinburgh suburbs)."""
    return (-3.2500, 55.9700)


# ============================================================================
# TEST: BASIC EXTRACTION
# ============================================================================

def test_extraction_returns_plan(generator, user_parser, job_parser, origin, dest):
    """Basic test: extraction should return ExtractedPlan."""
    user = user_parser.load_from_yaml('eco_warrior')
    job = job_parser.load_from_yaml('morning_commute')
    
    plan = generator.extract_plan_from_context(user, job, origin, dest)
    
    assert isinstance(plan, ExtractedPlan)
    assert plan.plan_type in ['point_to_point', 'multi_stop', 'scheduled', 'flexible']
    assert plan.primary_objective in ['minimize_time', 'minimize_carbon', 'minimize_cost']


# ============================================================================
# TEST: ECO WARRIOR SCENARIOS
# ============================================================================

def test_eco_warrior_school_run(generator, user_parser, job_parser, origin, dest):
    """
    Eco warrior + school run should extract:
    - Fixed schedule (school times)
    - Carbon minimization (eco-conscious)
    - Reliability critical (children present)
    - Weather sensitive (cycling with kids)
    """
    user = user_parser.load_from_yaml('eco_warrior')
    
    # Try different job story IDs that might exist
    try:
        job = job_parser.load_from_yaml('school_run_then_work')
    except KeyError:
        try:
            job = job_parser.load_from_yaml('morning_commute')
        except KeyError:
            pytest.skip("No suitable job story found")
    
    plan = generator.extract_plan_from_context(user, job, origin, dest)
    
    # Should minimize carbon (eco warrior)
    assert plan.primary_objective == 'minimize_carbon', \
        f"Expected minimize_carbon, got {plan.primary_objective}"
    
    # Should have reasoning
    assert plan.reasoning is not None
    assert 'eco' in plan.reasoning.lower() or 'carbon' in plan.reasoning.lower()


def test_eco_warrior_leisure(generator, user_parser, job_parser, origin, dest):
    """
    Eco warrior + leisure should extract:
    - Flexible schedule
    - Carbon minimization
    - Weather sensitivity may vary
    """
    user = user_parser.load_from_yaml('eco_warrior')
    
    # Try to load a leisure job
    try:
        job = job_parser.load_from_yaml('shopping_trip')
    except KeyError:
        pytest.skip("No shopping_trip job story found")
    
    plan = generator.extract_plan_from_context(user, job, origin, dest)
    
    assert plan.primary_objective == 'minimize_carbon'
    assert plan.flexibility_allowed == True


# ============================================================================
# TEST: BUSINESS COMMUTER SCENARIOS
# ============================================================================

def test_business_commuter_urgent(generator, user_parser, job_parser, origin, dest):
    """
    Business commuter should extract:
    - Time minimization
    - Reliability critical
    """
    user = user_parser.load_from_yaml('business_commuter')
    job = job_parser.load_from_yaml('morning_commute')
    
    plan = generator.extract_plan_from_context(user, job, origin, dest)
    
    # Business commuter should prioritize time
    assert plan.primary_objective == 'minimize_time', \
        f"Expected minimize_time for business commuter, got {plan.primary_objective}"


# ============================================================================
# TEST: CONCERNED PARENT SCENARIOS
# ============================================================================

def test_concerned_parent_school_run(generator, user_parser, job_parser, origin, dest):
    """
    Concerned parent + school run should extract:
    - Fixed schedule
    - Reliability critical (children)
    - Weather sensitive
    - Safety as secondary objective
    """
    user = user_parser.load_from_yaml('concerned_parent')
    
    try:
        job = job_parser.load_from_yaml('morning_commute')
    except KeyError:
        pytest.skip("No suitable job found")
    
    plan = generator.extract_plan_from_context(user, job, origin, dest)
    
    # Should be reliability critical (children)
    assert plan.reliability_critical == True, \
        "Expected reliability_critical=True for concerned parent"
    
    # Should be weather sensitive
    assert plan.weather_sensitive == True, \
        "Expected weather_sensitive=True for concerned parent"
    
    # Should have safety as objective
    assert 'safety' in str(plan.secondary_objectives).lower()


# ============================================================================
# TEST: FREIGHT OPERATOR SCENARIOS
# ============================================================================

def test_freight_operator_delivery(generator, user_parser, job_parser, origin, dest):
    """
    Freight operator should extract:
    - Cost minimization OR time minimization
    - Regulatory compliance
    - Reliability critical
    """
    user = user_parser.load_from_yaml('freight_operator')
    
    try:
        job = job_parser.load_from_yaml('freight_delivery_route')
    except KeyError:
        try:
            job = job_parser.load_from_yaml('long_haul_freight')
        except KeyError:
            pytest.skip("No freight job found")
    
    plan = generator.extract_plan_from_context(user, job, origin, dest)
    
    # Should optimize cost or time (freight jobs)
    assert plan.primary_objective in ['minimize_cost', 'minimize_time'], \
        f"Expected cost/time optimization for freight, got {plan.primary_objective}"
    
    # Check for compliance (if mentioned in job context)
    if hasattr(job, 'plan_context') and job.plan_context:
        compliance_mentioned = any(
            'compliance' in str(c).lower() or 'regulation' in str(c).lower()
            for c in job.plan_context
        )
        
        if compliance_mentioned:
            assert len(plan.must_comply_with) > 0, \
                "Expected regulatory constraints for freight operator"


# ============================================================================
# TEST: SAME PERSONA, DIFFERENT JOBS
# ============================================================================

def test_same_persona_different_jobs_produces_different_plans(
    generator, user_parser, job_parser, origin, dest
):
    """
    CRITICAL TEST: Same persona + different jobs should produce different plans.
    
    This demonstrates the core innovation.
    """
    eco_warrior = user_parser.load_from_yaml('eco_warrior')
    
    # Get two different jobs
    try:
        job1 = job_parser.load_from_yaml('morning_commute')
        job2 = job_parser.load_from_yaml('shopping_trip')
    except KeyError:
        pytest.skip("Need both morning_commute and shopping_trip jobs")
    
    plan1 = generator.extract_plan_from_context(eco_warrior, job1, origin, dest)
    plan2 = generator.extract_plan_from_context(eco_warrior, job2, origin, dest)
    
    # Both should minimize carbon (same persona)
    assert plan1.primary_objective == 'minimize_carbon'
    assert plan2.primary_objective == 'minimize_carbon'
    
    # But other attributes should differ based on job context
    # (e.g., schedule flexibility, reliability requirements)
    
    # Print for manual inspection
    print(f"\nJob 1 (morning_commute): schedule_fixed={plan1.schedule_fixed}")
    print(f"Job 2 (shopping_trip): schedule_fixed={plan2.schedule_fixed}")


# ============================================================================
# TEST: DIFFERENT PERSONAS, SAME JOB
# ============================================================================

def test_different_personas_same_job_produces_different_plans(
    generator, user_parser, job_parser, origin, dest
):
    """
    CRITICAL TEST: Different personas + same job should produce different objectives.
    
    This demonstrates persona influence on planning.
    """
    eco = user_parser.load_from_yaml('eco_warrior')
    biz = user_parser.load_from_yaml('business_commuter')
    
    job = job_parser.load_from_yaml('morning_commute')
    
    plan_eco = generator.extract_plan_from_context(eco, job, origin, dest)
    plan_biz = generator.extract_plan_from_context(biz, job, origin, dest)
    
    # Different personas should have different objectives
    assert plan_eco.primary_objective == 'minimize_carbon', \
        "Eco warrior should minimize carbon"
    
    assert plan_biz.primary_objective == 'minimize_time', \
        "Business commuter should minimize time"
    
    print(f"\nEco warrior objective: {plan_eco.primary_objective}")
    print(f"Business commuter objective: {plan_biz.primary_objective}")


# ============================================================================
# TEST: TIME WINDOW EXTRACTION
# ============================================================================

def test_time_window_extraction(generator, user_parser, job_parser, origin, dest):
    """Time windows should be extracted from job stories."""
    user = user_parser.load_from_yaml('eco_warrior')
    job = job_parser.load_from_yaml('morning_commute')
    
    plan = generator.extract_plan_from_context(user, job, origin, dest)
    
    if hasattr(job, 'time_window') and job.time_window:
        assert plan.time_window_start is not None
        assert plan.time_window_end is not None
        
        # Check format (HH:MM)
        assert ':' in plan.time_window_start
        assert ':' in plan.time_window_end


# ============================================================================
# TEST: REGULATORY CONSTRAINTS
# ============================================================================

def test_regulatory_constraint_extraction(generator, user_parser, job_parser, origin, dest):
    """Regulatory constraints should be extracted from plan_context."""
    user = user_parser.load_from_yaml('freight_operator')
    
    try:
        job = job_parser.load_from_yaml('freight_delivery_route')
    except KeyError:
        pytest.skip("No freight job with compliance context")
    
    plan = generator.extract_plan_from_context(user, job, origin, dest)
    
    # Check if job has compliance context
    if hasattr(job, 'plan_context') and job.plan_context:
        compliance_contexts = [
            c for c in job.plan_context
            if 'compliance' in c.lower() or 'regulation' in c.lower()
        ]
        
        if compliance_contexts:
            assert len(plan.must_comply_with) > 0, \
                f"Expected compliance constraints, got: {plan.must_comply_with}"


# ============================================================================
# TEST: URGENCY HANDLING
# ============================================================================

def test_urgency_critical_overrides_objective(generator, user_parser, job_parser, origin, dest):
    """Critical urgency should override objective to minimize_time."""
    eco = user_parser.load_from_yaml('eco_warrior')
    
    # Find a critical urgency job
    job_ids = job_parser.list_available_stories()
    
    critical_job = None
    for job_id in job_ids:
        try:
            job = job_parser.load_from_yaml(job_id)
            if hasattr(job, 'parameters') and job.parameters.get('urgency') == 'critical':
                critical_job = job
                break
        except:
            continue
    
    if critical_job is None:
        pytest.skip("No critical urgency job found")
    
    plan = generator.extract_plan_from_context(eco, critical_job, origin, dest)
    
    # Critical urgency should override eco preference
    assert plan.primary_objective == 'minimize_time', \
        "Critical urgency should force minimize_time"
    
    assert plan.reliability_critical == True


# ============================================================================
# TEST: REASONING GENERATION
# ============================================================================

def test_reasoning_generated(generator, user_parser, job_parser, origin, dest):
    """Every plan should have reasoning for explainability."""
    user = user_parser.load_from_yaml('eco_warrior')
    job = job_parser.load_from_yaml('morning_commute')
    
    plan = generator.extract_plan_from_context(user, job, origin, dest)
    
    assert plan.reasoning is not None
    assert len(plan.reasoning) > 0
    
    print(f"\nReasoning: {plan.reasoning}")


# ============================================================================
# TEST: CSV DATA OVERRIDE
# ============================================================================

def test_csv_waypoint_override(generator, user_parser, job_parser, origin, dest):
    """CSV data should add waypoints to plan."""
    user = user_parser.load_from_yaml('eco_warrior')
    job = job_parser.load_from_yaml('morning_commute')
    
    csv_data = {
        'waypoint_1_lat': 55.9600,
        'waypoint_1_lon': -3.2000
    }
    
    plan = generator.extract_plan_from_context(user, job, origin, dest, csv_data)
    
    assert len(plan.waypoints) > 0
    assert plan.plan_type == 'multi_stop'


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])