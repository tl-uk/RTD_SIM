"""
examples/synthetic_events_demo.py

Demonstration of Phase 7.2 Synthetic Event Generator.

Shows how events are generated over time and their impacts.
"""

import sys
from pathlib import Path

# Add project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from simulation.events.synthetic_generator import (
    SyntheticEventGenerator,
    EventType,
    EventSeverity
)
from datetime import datetime, timedelta


def demo_1_basic_generation():
    """Demo 1: Basic event generation over time."""
    print("=" * 70)
    print("DEMO 1: Basic Event Generation")
    print("=" * 70)
    print()
    
    generator = SyntheticEventGenerator(
        traffic_enabled=True,
        weather_enabled=True,
        infrastructure_enabled=True,
        random_seed=42
    )
    
    # Simulate one day at hourly resolution
    start_time = datetime(2024, 1, 15, 0, 0)  # Winter Monday
    
    print("Simulating 24 hours (hourly resolution)...")
    print()
    
    event_count = 0
    for hour in range(24):
        current_time = start_time + timedelta(hours=hour)
        
        time_info = {
            'datetime': current_time,
            'hour': current_time.hour,
            'is_rush_hour': 7 <= current_time.hour <= 9 or 17 <= current_time.hour <= 19,
            'is_weekday': True,
            'season': 'winter',
            'day_of_week': 0,  # Monday
        }
        
        events = generator.generate_events_for_step(hour, time_info)
        
        if events:
            for event in events:
                event_count += 1
                rush_marker = " 🚗" if time_info['is_rush_hour'] else ""
                print(f"Hour {hour:02d}:00{rush_marker} - {event.description}")
                print(f"   Impact: {event.impact_data}")
                print()
    
    print(f"Total events: {event_count}")
    print(f"Active events at end: {len(generator.get_active_events())}")
    print()


def demo_2_seasonal_comparison():
    """Demo 2: Compare event generation across seasons."""
    print("=" * 70)
    print("DEMO 2: Seasonal Event Comparison")
    print("=" * 70)
    print()
    
    seasons = ['winter', 'spring', 'summer', 'fall']
    
    for season in seasons:
        print(f"\n=== {season.upper()} ===")
        
        generator = SyntheticEventGenerator(
            weather_enabled=True,
            traffic_enabled=False,
            infrastructure_enabled=False,
            random_seed=42
        )
        
        time_info = {
            'datetime': datetime(2024, 1, 1, 12, 0),
            'hour': 12,
            'is_rush_hour': False,
            'is_weekday': True,
            'season': season,
        }
        
        # Generate for 30 days
        weather_events = 0
        event_types = {}
        
        for day in range(30):
            events = generator.generate_events_for_step(day, time_info)
            for event in events:
                weather_events += 1
                weather_type = event.impact_data.get('weather_type', 'unknown')
                event_types[weather_type] = event_types.get(weather_type, 0) + 1
        
        print(f"Weather events in 30 days: {weather_events}")
        print(f"Event types: {event_types}")
    
    print()


def demo_3_event_frequency():
    """Demo 3: Show different frequency settings."""
    print("=" * 70)
    print("DEMO 3: Event Frequency Comparison")
    print("=" * 70)
    print()
    
    frequencies = {
        'rare': 0.25,
        'occasional': 0.5,
        'normal': 1.0,
        'frequent': 2.0,
        'very_frequent': 4.0,
    }
    
    for freq_name, multiplier in frequencies.items():
        generator = SyntheticEventGenerator(
            traffic_enabled=True,
            weather_enabled=True,
            infrastructure_enabled=True,
            traffic_base_probability=0.05 * multiplier,
            weather_base_probability=0.03 * multiplier,
            infrastructure_failure_probability=0.01 * multiplier,
            random_seed=42
        )
        
        time_info = {
            'datetime': datetime(2024, 1, 15, 12, 0),
            'hour': 12,
            'is_rush_hour': False,
            'is_weekday': True,
            'season': 'winter',
        }
        
        # Simulate 30 days
        total_events = 0
        for day in range(30):
            events = generator.generate_events_for_step(day, time_info)
            total_events += len(events)
        
        print(f"{freq_name.upper():15s}: {total_events:3d} events in 30 days")
    
    print()


def demo_4_event_types_and_impacts():
    """Demo 4: Show different event types and their impacts."""
    print("=" * 70)
    print("DEMO 4: Event Types and Impacts")
    print("=" * 70)
    print()
    
    generator = SyntheticEventGenerator(
        traffic_enabled=True,
        weather_enabled=True,
        infrastructure_enabled=True,
        grid_enabled=True,
        random_seed=123  # Different seed for variety
    )
    
    time_info = {
        'datetime': datetime(2024, 2, 1, 8, 0),
        'hour': 8,
        'is_rush_hour': True,
        'is_weekday': True,
        'season': 'winter',
    }
    
    # Generate events until we have examples of each type
    event_examples = {}
    max_steps = 100
    
    for step in range(max_steps):
        events = generator.generate_events_for_step(step, time_info)
        
        for event in events:
            event_type = event.event_type.value
            if event_type not in event_examples:
                event_examples[event_type] = event
        
        if len(event_examples) >= 4:  # Got all types
            break
    
    # Display examples
    for event_type, event in event_examples.items():
        print(f"\n🎲 {event_type.upper().replace('_', ' ')}")
        print(f"   Description: {event.description}")
        print(f"   Severity: {event.severity.value}")
        print(f"   Duration: {event.duration_steps} steps")
        print(f"   Impact: {event.impact_data}")
        print(f"   Multiplier: {event.get_impact_multiplier()}x")
    
    print()


def demo_5_one_year_simulation():
    """Demo 5: Full year simulation with all events."""
    print("=" * 70)
    print("DEMO 5: One-Year Simulation (365 days)")
    print("=" * 70)
    print()
    
    generator = SyntheticEventGenerator(
        traffic_enabled=True,
        weather_enabled=True,
        infrastructure_enabled=True,
        grid_enabled=True,
        random_seed=42
    )
    
    # Track statistics
    events_by_type = {}
    events_by_severity = {}
    events_by_month = [0] * 12
    
    start_date = datetime(2024, 1, 1)
    
    print("Generating events for 365 days...")
    print()
    
    for day in range(365):
        current_date = start_date + timedelta(days=day)
        
        # Determine season
        month = current_date.month
        if month in [12, 1, 2]:
            season = 'winter'
        elif month in [3, 4, 5]:
            season = 'spring'
        elif month in [6, 7, 8]:
            season = 'summer'
        else:
            season = 'fall'
        
        time_info = {
            'datetime': current_date,
            'hour': 12,
            'is_rush_hour': False,
            'is_weekday': current_date.weekday() < 5,
            'season': season,
            'month': month,
        }
        
        events = generator.generate_events_for_step(day, time_info)
        
        for event in events:
            # Track by type
            event_type = event.event_type.value
            events_by_type[event_type] = events_by_type.get(event_type, 0) + 1
            
            # Track by severity
            severity = event.severity.value
            events_by_severity[severity] = events_by_severity.get(severity, 0) + 1
            
            # Track by month
            events_by_month[month - 1] += 1
    
    # Display statistics
    print("📊 ANNUAL STATISTICS")
    print()
    
    total_events = sum(events_by_type.values())
    print(f"Total events: {total_events}")
    print()
    
    print("By Type:")
    for event_type, count in sorted(events_by_type.items()):
        pct = (count / total_events) * 100
        print(f"  {event_type:25s}: {count:3d} ({pct:5.1f}%)")
    print()
    
    print("By Severity:")
    for severity, count in sorted(events_by_severity.items()):
        pct = (count / total_events) * 100
        print(f"  {severity:10s}: {count:3d} ({pct:5.1f}%)")
    print()
    
    print("By Month:")
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
              'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    for i, (month, count) in enumerate(zip(months, events_by_month)):
        season_marker = ""
        if i in [0, 1, 11]:
            season_marker = " ❄️"
        elif i in [5, 6, 7]:
            season_marker = " ☀️"
        print(f"  {month}: {count:3d}{season_marker}")
    
    print()


if __name__ == "__main__":
    print("\n" + "="*70)
    print("PHASE 7.2: SYNTHETIC EVENT GENERATOR - DEMONSTRATIONS")
    print("="*70 + "\n")
    
    demo_1_basic_generation()
    input("Press Enter for next demo...")
    
    demo_2_seasonal_comparison()
    input("Press Enter for next demo...")
    
    demo_3_event_frequency()
    input("Press Enter for next demo...")
    
    demo_4_event_types_and_impacts()
    input("Press Enter for next demo...")
    
    demo_5_one_year_simulation()
    
    print("="*70)
    print("END OF DEMONSTRATIONS")
    print("="*70)
    print("\n💡 Next steps:")
    print("  1. Install synthetic event generator in RTD_SIM")
    print("  2. Enable in UI sidebar")
    print("  3. Run extended simulations with events!")
    print("  4. Watch agents adapt to unpredictable conditions")
    print("\nSee PHASE_72_INTEGRATION_GUIDE.md for installation.\n")