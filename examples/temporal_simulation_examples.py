"""
examples/temporal_simulation_examples.py

Example usage of the Temporal Engine for extended simulations.

Run this to see how temporal scaling works with different scenarios.
"""

from simulation.time.temporal_engine import TemporalEngine, TimeScale
from datetime import datetime


def example_1_one_week_commuter_study():
    """
    Example 1: One-week commuter behavior study at hourly resolution.
    
    Use case: Understand daily patterns, rush hour impact, weekday vs weekend.
    """
    print("="*70)
    print("EXAMPLE 1: One-Week Commuter Study (Hourly Resolution)")
    print("="*70)
    
    engine = TemporalEngine(
        time_scale=TimeScale.HOUR,
        start_datetime=datetime(2024, 1, 8, 0, 0),  # Monday
        steps=168  # 7 days × 24 hours
    )
    
    summary = engine.get_summary()
    print(f"\nSimulation Config:")
    print(f"  Duration: {summary['duration']}")
    print(f"  From: {summary['start_date']} to {summary['end_date']}")
    print(f"  Each step = {summary['step_duration']}")
    
    # Show some key timepoints
    print(f"\nKey Timepoints:")
    for step in [0, 8, 17, 24, 168]:
        if step >= 168:
            step = 167
        time_info = engine.get_time_info(step)
        rush_hour = "🚗 RUSH HOUR" if time_info['is_rush_hour'] else ""
        weekend = "📅 WEEKEND" if time_info['is_weekend'] else ""
        print(f"  Step {step:3d}: {time_info['date']} {time_info['time']} {rush_hour} {weekend}")
    
    print(f"\n💡 Use Case: Compare agent mode choices during rush hour vs off-peak")
    print()


def example_2_one_year_ev_adoption():
    """
    Example 2: One-year EV adoption study with policy intervention.
    
    Use case: Long-term policy impact, seasonal effects, adoption curves.
    """
    print("="*70)
    print("EXAMPLE 2: One-Year EV Adoption Study (Daily Resolution)")
    print("="*70)
    
    engine = TemporalEngine(
        time_scale=TimeScale.DAY,
        start_datetime=datetime(2024, 1, 1, 0, 0),
        steps=365
    )
    
    summary = engine.get_summary()
    print(f"\nSimulation Config:")
    print(f"  Duration: {summary['duration']}")
    print(f"  Total days: {summary['total_sim_days']:.0f}")
    
    # Policy timeline
    print(f"\nSample Policy Timeline:")
    
    policy_dates = [
        (datetime(2024, 1, 15), "Add 50 EV chargers"),
        (datetime(2024, 4, 1), "Grid expansion +20%"),
        (datetime(2024, 7, 1), "Add 100 more chargers"),
        (datetime(2024, 10, 1), "Pricing incentive launch"),
    ]
    
    for policy_date, description in policy_dates:
        step = engine.get_step_from_datetime(policy_date)
        if step is not None:
            time_info = engine.get_time_info(step)
            print(f"  Step {step:3d} ({time_info['date']}): {description}")
    
    # Seasonal checkpoints
    print(f"\nSeasonal Checkpoints:")
    for step in [0, 90, 180, 270, 364]:
        time_info = engine.get_time_info(step)
        print(f"  Step {step:3d}: {time_info['date']} - {time_info['season'].upper()}")
    
    print(f"\n💡 Use Case: Track EV adoption as it spreads over 12 months")
    print(f"             Observe seasonal effects (winter range reduction)")
    print()


def example_3_five_year_infrastructure():
    """
    Example 3: Five-year infrastructure rollout at weekly resolution.
    
    Use case: Strategic planning, multi-year trends, investment cycles.
    """
    print("="*70)
    print("EXAMPLE 3: Five-Year Infrastructure Plan (Weekly Resolution)")
    print("="*70)
    
    engine = TemporalEngine(
        time_scale=TimeScale.WEEK,
        start_datetime=datetime(2024, 1, 1, 0, 0),
        steps=260  # 5 years × 52 weeks
    )
    
    summary = engine.get_summary()
    print(f"\nSimulation Config:")
    print(f"  Duration: {summary['duration']}")
    print(f"  Total years: {summary['total_sim_days']/365:.1f}")
    
    # Multi-year checkpoints
    print(f"\nYearly Milestones:")
    for year in range(1, 6):
        step = year * 52  # Each year = 52 weeks
        if step >= 260:
            step = 259
        time_info = engine.get_time_info(step)
        print(f"  Year {year} ({time_info['date']}): Review infrastructure impact")
    
    # Monthly policy reviews
    print(f"\nMonthly Policy Reviews (first year):")
    for month in range(1, 13):
        step = month * 4  # Roughly 4 weeks per month
        time_info = engine.get_time_info(step)
        print(f"  Step {step:3d} ({time_info['date']}): Month {month} review")
    
    print(f"\n💡 Use Case: Long-term strategic planning")
    print(f"             Gradual infrastructure buildout")
    print(f"             Multi-year behavioral shifts")
    print()


def example_4_periodic_events():
    """
    Example 4: Demonstrate periodic event triggering.
    
    Shows how to schedule events at different frequencies.
    """
    print("="*70)
    print("EXAMPLE 4: Periodic Event Triggering")
    print("="*70)
    
    engine = TemporalEngine(
        time_scale=TimeScale.DAY,
        start_datetime=datetime(2024, 1, 1, 0, 0),
        steps=90  # 3 months
    )
    
    print(f"\nScanning for periodic events in 90-day simulation...\n")
    
    weekly_events = []
    monthly_events = []
    
    for step in range(90):
        if engine.should_trigger_periodic_event(step, 'weekly'):
            time_info = engine.get_time_info(step)
            weekly_events.append(f"  Step {step:3d} ({time_info['date']}): Weekly policy review")
        
        if engine.should_trigger_periodic_event(step, 'monthly'):
            time_info = engine.get_time_info(step)
            monthly_events.append(f"  Step {step:3d} ({time_info['date']}): Monthly infrastructure update")
    
    print("Weekly Events (every Monday):")
    for event in weekly_events[:5]:  # Show first 5
        print(event)
    print(f"  ... ({len(weekly_events)} total weekly events)\n")
    
    print("Monthly Events (1st of each month):")
    for event in monthly_events:
        print(event)
    
    print(f"\n💡 Use Case: Schedule regular policy reviews, budget cycles, maintenance")
    print()


def example_5_time_aware_decisions():
    """
    Example 5: Show how to use time info for agent decisions.
    
    Demonstrates conditional logic based on time of day, season, etc.
    """
    print("="*70)
    print("EXAMPLE 5: Time-Aware Agent Decisions")
    print("="*70)
    
    engine = TemporalEngine(
        time_scale=TimeScale.HOUR,
        start_datetime=datetime(2024, 7, 15, 0, 0),  # Summer
        steps=24  # One day
    )
    
    print(f"\nAgent Decision Logic Based on Time:\n")
    
    for step in [7, 8, 12, 17, 22]:
        time_info = engine.get_time_info(step)
        
        print(f"Step {step:2d} ({time_info['time']} on {time_info['date']}):")
        
        # Rush hour logic
        if time_info['is_rush_hour']:
            print(f"  🚗 Rush hour detected → Expect congestion, consider alternatives")
        
        # Time-of-day pricing
        if 22 <= time_info['hour'] or time_info['hour'] < 7:
            print(f"  🔌 Off-peak hours → Charge EV at reduced rate")
        
        # Seasonal effects
        if time_info['season'] == 'summer':
            print(f"  ☀️  Summer → EV range +15%, bike mode attractive")
        elif time_info['season'] == 'winter':
            print(f"  ❄️  Winter → EV range -25%, heating demand up")
        
        # Weekend behavior
        if time_info['is_weekend']:
            print(f"  📅 Weekend → Leisure travel patterns, lower commute traffic")
        
        print()
    
    print(f"💡 Use Case: Agents make realistic time-dependent decisions")
    print()


if __name__ == "__main__":
    print("\n" + "="*70)
    print("RTD_SIM TEMPORAL ENGINE - USAGE EXAMPLES")
    print("="*70 + "\n")
    
    example_1_one_week_commuter_study()
    input("Press Enter for next example...")
    
    example_2_one_year_ev_adoption()
    input("Press Enter for next example...")
    
    example_3_five_year_infrastructure()
    input("Press Enter for next example...")
    
    example_4_periodic_events()
    input("Press Enter for next example...")
    
    example_5_time_aware_decisions()
    
    print("="*70)
    print("END OF EXAMPLES")
    print("="*70)
    print("\n💡 Next steps:")
    print("  1. Install temporal engine in your RTD_SIM project")
    print("  2. Enable temporal scaling in UI sidebar")
    print("  3. Run extended simulations!")
    print("  4. Integrate time-aware logic in your agents")
    print("\nSee INSTALLATION.md for setup instructions.\n")