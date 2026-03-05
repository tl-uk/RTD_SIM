"""
simulation/time/temporal_engine.py

Temporal Engine for Extended Simulations

Manages simulation time scaling, allowing simulations to span days, weeks, months, or years.
Converts simulation steps to real-world datetime and enables time-aware event triggering.

Phase 7.1: Extended Temporal Simulation
"""

from __future__ import annotations
from datetime import datetime, timedelta
from typing import Literal, Optional, Dict, Any
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class TimeScale(Enum):
    """Available time scales for simulation."""
    MINUTE = "1min_per_step"      # 100 steps = 100 minutes (1.67 hours)
    FIVE_MINUTES = "5min_per_step"  # 100 steps = 500 minutes (8.33 hours)
    FIFTEEN_MINUTES = "15min_per_step"  # 100 steps = 25 hours
    HOUR = "1hour_per_step"       # 100 steps = 100 hours (4.17 days)
    DAY = "1day_per_step"         # 100 steps = 100 days (3.3 months)
    WEEK = "1week_per_step"       # 100 steps = 700 days (1.92 years)
    MONTH = "1month_per_step"     # 100 steps = 100 months (8.33 years)


class TemporalEngine:
    """
    Manages simulation temporal scaling and datetime conversions.
    
    Allows RTD_SIM to simulate extended periods while maintaining
    reasonable step counts for visualization and computation.
    
    Examples:
        # 1-day simulation at 1-minute resolution
        engine = TemporalEngine(TimeScale.MINUTE, steps=1440)
        
        # 1-year simulation at 1-day resolution
        engine = TemporalEngine(TimeScale.DAY, steps=365)
        
        # 5-year policy study at 1-week resolution
        engine = TemporalEngine(TimeScale.WEEK, steps=260)
    """
    
    def __init__(
        self,
        time_scale: TimeScale | str = TimeScale.MINUTE,
        start_datetime: Optional[datetime] = None,
        steps: int = 100
    ):
        """
        Initialize temporal engine.
        
        Args:
            time_scale: How much real time each step represents
            start_datetime: Simulation start date/time (default: now)
            steps: Total number of simulation steps
        """
        # Convert string to enum if needed
        if isinstance(time_scale, str):
            time_scale = TimeScale(time_scale)
        
        self.time_scale = time_scale
        self.start_datetime = start_datetime or datetime(2024, 1, 1, 0, 0, 0)
        self.total_steps = steps
        
        # Calculate step duration in minutes
        self.minutes_per_step = self._calculate_minutes_per_step()
        
        # Calculate simulation duration
        self.total_minutes = self.minutes_per_step * steps
        self.end_datetime = self.start_datetime + timedelta(minutes=self.total_minutes)
        
        logger.info(f"⏰ Temporal Engine initialized:")
        logger.info(f"   Time scale: {time_scale.value}")
        logger.info(f"   Start: {self.start_datetime.strftime('%Y-%m-%d %H:%M')}")
        logger.info(f"   End: {self.end_datetime.strftime('%Y-%m-%d %H:%M')}")
        logger.info(f"   Duration: {self._format_duration()}")
        logger.info(f"   Steps: {steps} (each step = {self._format_step_duration()})")
    
    def _calculate_minutes_per_step(self) -> int:
        """Calculate how many real-world minutes each step represents."""
        scale_map = {
            TimeScale.MINUTE: 1,
            TimeScale.FIVE_MINUTES: 5,
            TimeScale.FIFTEEN_MINUTES: 15,
            TimeScale.HOUR: 60,
            TimeScale.DAY: 1440,           # 24 * 60
            TimeScale.WEEK: 10080,         # 7 * 24 * 60
            TimeScale.MONTH: 43200,        # 30 * 24 * 60 (approximation)
        }
        return scale_map[self.time_scale]
    
    def get_datetime(self, step: int) -> datetime:
        """
        Get real-world datetime for given simulation step.
        
        Args:
            step: Simulation step number (0-indexed)
            
        Returns:
            datetime object representing that point in simulation time
        """
        minutes_elapsed = step * self.minutes_per_step
        return self.start_datetime + timedelta(minutes=minutes_elapsed)
    
    def get_time_info(self, step: int) -> Dict[str, Any]:
        """
        Get comprehensive time information for given step.
        
        Returns dict with:
            - datetime: Full datetime object
            - date: Date string (YYYY-MM-DD)
            - time: Time string (HH:MM:SS)
            - hour: Hour of day (0-23)
            - day_of_week: 0=Monday, 6=Sunday
            - day_of_month: 1-31
            - day_of_year: 1-365
            - month: 1-12
            - year: YYYY
            - is_weekday: True/False
            - is_weekend: True/False
            - is_rush_hour: True/False (7-9am or 5-7pm)
            - season: 'winter'/'spring'/'summer'/'fall'
        """
        dt = self.get_datetime(step)
        
        hour = dt.hour
        day_of_week = dt.weekday()  # 0=Monday, 6=Sunday
        month = dt.month
        
        # Determine season (Northern Hemisphere)
        if month in [12, 1, 2]:
            season = 'winter'
        elif month in [3, 4, 5]:
            season = 'spring'
        elif month in [6, 7, 8]:
            season = 'summer'
        else:
            season = 'fall'
        
        # Rush hour detection
        is_rush_hour = (7 <= hour <= 9) or (17 <= hour <= 19)
        
        return {
            'datetime': dt,
            'date': dt.strftime('%Y-%m-%d'),
            'time': dt.strftime('%H:%M:%S'),
            'hour': hour,
            'day_of_week': day_of_week,
            'day_of_month': dt.day,
            'day_of_year': dt.timetuple().tm_yday,
            'month': month,
            'year': dt.year,
            'is_weekday': day_of_week < 5,
            'is_weekend': day_of_week >= 5,
            'is_rush_hour': is_rush_hour,
            'season': season,
            'step': step,
            'elapsed_days': (dt - self.start_datetime).days,
        }
    
    def should_trigger_periodic_event(
        self, 
        step: int, 
        frequency: Literal['hourly', 'daily', 'weekly', 'monthly', 'yearly']
    ) -> bool:
        """
        Check if a periodic event should trigger at this step.
        
        Args:
            step: Current simulation step
            frequency: How often event should trigger
            
        Returns:
            True if event should trigger at this step
        """
        time_info = self.get_time_info(step)
        dt = time_info['datetime']
        
        if frequency == 'hourly':
            # Trigger at the start of each hour (minute 0)
            return dt.minute == 0 and dt.second == 0
        
        elif frequency == 'daily':
            # Trigger at midnight
            return dt.hour == 0 and dt.minute == 0 and dt.second == 0
        
        elif frequency == 'weekly':
            # Trigger at midnight on Monday
            return time_info['day_of_week'] == 0 and dt.hour == 0 and dt.minute == 0
        
        elif frequency == 'monthly':
            # Trigger at midnight on the 1st
            return dt.day == 1 and dt.hour == 0 and dt.minute == 0
        
        elif frequency == 'yearly':
            # Trigger at midnight on January 1st
            return dt.month == 1 and dt.day == 1 and dt.hour == 0 and dt.minute == 0
        
        return False
    
    def get_step_from_datetime(self, target_datetime: datetime) -> Optional[int]:
        """
        Find which step corresponds to a given datetime.
        
        Args:
            target_datetime: The datetime to find
            
        Returns:
            Step number, or None if datetime is outside simulation range
        """
        if target_datetime < self.start_datetime or target_datetime > self.end_datetime:
            return None
        
        minutes_elapsed = (target_datetime - self.start_datetime).total_seconds() / 60
        step = int(minutes_elapsed / self.minutes_per_step)
        
        return min(step, self.total_steps - 1)
    
    def _format_duration(self) -> str:
        """Format total simulation duration as human-readable string."""
        total_days = self.total_minutes / 1440
        
        if total_days < 1:
            hours = self.total_minutes / 60
            return f"{hours:.1f} hours"
        elif total_days < 7:
            return f"{total_days:.1f} days"
        elif total_days < 30:
            weeks = total_days / 7
            return f"{weeks:.1f} weeks"
        elif total_days < 365:
            months = total_days / 30
            return f"{months:.1f} months"
        else:
            years = total_days / 365
            return f"{years:.1f} years"
    
    def _format_step_duration(self) -> str:
        """Format single step duration as human-readable string."""
        minutes = self.minutes_per_step
        
        if minutes < 60:
            return f"{minutes} min"
        elif minutes < 1440:
            hours = minutes / 60
            return f"{hours:.0f} hour{'s' if hours > 1 else ''}"
        elif minutes < 10080:
            days = minutes / 1440
            return f"{days:.0f} day{'s' if days > 1 else ''}"
        else:
            weeks = minutes / 10080
            return f"{weeks:.0f} week{'s' if weeks > 1 else ''}"
    
    def get_progress_string(self, current_step: int) -> str:
        """
        Get human-readable progress string.
        
        Example: "Day 45 of 365 (12.3%)"
        """
        time_info = self.get_time_info(current_step)
        progress_pct = (current_step / self.total_steps) * 100
        
        if self.time_scale in [TimeScale.MINUTE, TimeScale.FIVE_MINUTES, TimeScale.FIFTEEN_MINUTES]:
            return f"Hour {time_info['hour']}:{time_info['datetime'].minute:02d} ({progress_pct:.1f}%)"
        elif self.time_scale == TimeScale.HOUR:
            return f"Day {time_info['elapsed_days']}, Hour {time_info['hour']} ({progress_pct:.1f}%)"
        elif self.time_scale == TimeScale.DAY:
            return f"Day {current_step + 1} of {self.total_steps} ({progress_pct:.1f}%)"
        elif self.time_scale == TimeScale.WEEK:
            week_num = current_step + 1
            return f"Week {week_num} of {self.total_steps} ({progress_pct:.1f}%)"
        else:  # MONTH
            return f"Month {current_step + 1} of {self.total_steps} ({progress_pct:.1f}%)"
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of temporal configuration."""
        return {
            'time_scale': self.time_scale.value,
            'start_date': self.start_datetime.strftime('%Y-%m-%d %H:%M'),
            'end_date': self.end_datetime.strftime('%Y-%m-%d %H:%M'),
            'total_steps': self.total_steps,
            'duration': self._format_duration(),
            'step_duration': self._format_step_duration(),
            'total_sim_days': self.total_minutes / 1440,
        }


# Helper function for quick engine creation from config
def create_temporal_engine_from_config(config) -> Optional[TemporalEngine]:
    """
    Create TemporalEngine from SimulationConfig.
    
    Args:
        config: SimulationConfig object with temporal settings
        
    Returns:
        TemporalEngine instance, or None if temporal features disabled
    """
    # Check if temporal scaling is enabled
    if not hasattr(config, 'time_scale') or not config.time_scale:
        return None
    
    # Get start datetime if specified
    start_dt = None
    if hasattr(config, 'start_datetime') and config.start_datetime:
        start_dt = config.start_datetime
    
    # Create engine
    engine = TemporalEngine(
        time_scale=config.time_scale,
        start_datetime=start_dt,
        steps=config.steps
    )
    
    return engine


if __name__ == "__main__":
    # Example usage and testing
    print("=== Temporal Engine Examples ===\n")
    
    # Example 1: One day simulation at 1-minute resolution
    print("Example 1: One day at 1-minute resolution")
    engine1 = TemporalEngine(TimeScale.MINUTE, steps=1440)
    print(f"Step 0: {engine1.get_datetime(0)}")
    print(f"Step 720: {engine1.get_datetime(720)}")  # Noon
    print(f"Step 1439: {engine1.get_datetime(1439)}")  # End of day
    print()
    
    # Example 2: One year simulation at 1-day resolution
    print("Example 2: One year at 1-day resolution")
    engine2 = TemporalEngine(TimeScale.DAY, steps=365)
    print(f"Step 0: {engine2.get_datetime(0)}")
    print(f"Step 180: {engine2.get_datetime(180)}")  # Mid-year
    print(f"Step 364: {engine2.get_datetime(364)}")  # End of year
    
    # Show time info
    time_info = engine2.get_time_info(180)
    print(f"\nStep 180 details:")
    print(f"  Date: {time_info['date']}")
    print(f"  Season: {time_info['season']}")
    print(f"  Day of year: {time_info['day_of_year']}")
    print()
    
    # Example 3: 5-year policy study at 1-week resolution
    print("Example 3: Five years at 1-week resolution")
    engine3 = TemporalEngine(TimeScale.WEEK, steps=260)
    print(f"Duration: {engine3._format_duration()}")
    print(f"Step 52: {engine3.get_datetime(52)}")  # One year in
    print(f"Step 260: {engine3.get_datetime(259)}")  # End