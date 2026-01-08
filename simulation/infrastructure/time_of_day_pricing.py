"""
simulation/infrastructure/time_of_day_pricing.py

Phase 4.5C: Dynamic electricity pricing and smart charging optimization.

Features:
- Peak/off-peak electricity rates
- Time-dependent charging costs
- Smart charging scheduling
- Grid load balancing
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class TimeOfDay(Enum):
    """Time periods for pricing."""
    NIGHT = "night"          # 00:00-06:00 (super off-peak)
    MORNING = "morning"      # 06:00-09:00 (morning peak)
    MIDDAY = "midday"        # 09:00-17:00 (standard)
    EVENING = "evening"      # 17:00-20:00 (evening peak)
    LATE = "late"            # 20:00-00:00 (off-peak)


@dataclass
class PricingTier:
    """Electricity pricing tier."""
    name: str
    price_per_kwh: float  # GBP per kWh
    multiplier: float     # Relative to base rate
    time_ranges: List[Tuple[int, int]]  # [(start_hour, end_hour), ...]


class TimeOfDayPricingManager:
    """
    Manages dynamic electricity pricing based on time of day.
    
    Implements UK-style Economy 7/Octopus Agile style pricing:
    - Super off-peak (night): 0.08 GBP/kWh (0.5x base)
    - Off-peak (late evening): 0.12 GBP/kWh (0.75x base)
    - Standard (midday): 0.16 GBP/kWh (1.0x base)
    - Peak (morning/evening): 0.28 GBP/kWh (1.75x base)
    """
    
    def __init__(
        self,
        base_price_per_kwh: float = 0.16,
        enable_dynamic_pricing: bool = True
    ):
        """
        Initialize pricing manager.
        
        Args:
            base_price_per_kwh: Base electricity price (GBP/kWh)
            enable_dynamic_pricing: Enable time-of-day pricing
        """
        self.base_price = base_price_per_kwh
        self.enabled = enable_dynamic_pricing
        
        # Define pricing tiers
        self.tiers = {
            TimeOfDay.NIGHT: PricingTier(
                name="Super Off-Peak",
                price_per_kwh=base_price_per_kwh * 0.5,
                multiplier=0.5,
                time_ranges=[(0, 6)]
            ),
            TimeOfDay.MORNING: PricingTier(
                name="Morning Peak",
                price_per_kwh=base_price_per_kwh * 1.75,
                multiplier=1.75,
                time_ranges=[(6, 9)]
            ),
            TimeOfDay.MIDDAY: PricingTier(
                name="Standard",
                price_per_kwh=base_price_per_kwh * 1.0,
                multiplier=1.0,
                time_ranges=[(9, 17)]
            ),
            TimeOfDay.EVENING: PricingTier(
                name="Evening Peak",
                price_per_kwh=base_price_per_kwh * 1.75,
                multiplier=1.75,
                time_ranges=[(17, 20)]
            ),
            TimeOfDay.LATE: PricingTier(
                name="Off-Peak",
                price_per_kwh=base_price_per_kwh * 0.75,
                multiplier=0.75,
                time_ranges=[(20, 24)]
            ),
        }
        
        logger.info(f"Time-of-day pricing initialized: enabled={self.enabled}, base={self.base_price:.3f} GBP/kWh")
    
    def get_current_tier(self, current_hour: int) -> PricingTier:
        """
        Get current pricing tier based on hour of day.
        
        Args:
            current_hour: Hour of day (0-23)
        
        Returns:
            Current PricingTier
        """
        for time_of_day, tier in self.tiers.items():
            for start, end in tier.time_ranges:
                if start <= current_hour < end:
                    return tier
        
        # Fallback to standard
        return self.tiers[TimeOfDay.MIDDAY]
    
    def get_price_at_time(self, hour: int) -> float:
        """
        Get electricity price at specific hour.
        
        Args:
            hour: Hour of day (0-23)
        
        Returns:
            Price in GBP per kWh
        """
        if not self.enabled:
            return self.base_price
        
        tier = self.get_current_tier(hour)
        return tier.price_per_kwh
    
    def calculate_charging_cost(
        self,
        energy_kwh: float,
        start_hour: int,
        duration_hours: float
    ) -> float:
        """
        Calculate total charging cost over time period.
        
        Args:
            energy_kwh: Total energy to charge (kWh)
            start_hour: Starting hour (0-23)
            duration_hours: Charging duration in hours
        
        Returns:
            Total cost in GBP
        """
        if not self.enabled:
            return energy_kwh * self.base_price
        
        total_cost = 0.0
        hours_remaining = duration_hours
        current_hour = start_hour
        
        # Distribute energy across hours
        energy_per_hour = energy_kwh / duration_hours
        
        while hours_remaining > 0:
            hour_fraction = min(1.0, hours_remaining)
            hour_energy = energy_per_hour * hour_fraction
            hour_price = self.get_price_at_time(current_hour % 24)
            
            total_cost += hour_energy * hour_price
            
            hours_remaining -= hour_fraction
            current_hour += 1
        
        return total_cost
    
    def find_optimal_charging_window(
        self,
        energy_kwh: float,
        charging_rate_kw: float,
        earliest_hour: int,
        latest_hour: int,
        required_completion_hour: int
    ) -> Tuple[int, float]:
        """
        Find optimal charging start time to minimize cost.
        
        Args:
            energy_kwh: Total energy needed (kWh)
            charging_rate_kw: Charging power (kW)
            earliest_hour: Earliest possible start (0-23)
            latest_hour: Latest possible start (0-23)
            required_completion_hour: Must complete by this hour
        
        Returns:
            Tuple of (optimal_start_hour, estimated_cost)
        """
        duration_hours = energy_kwh / charging_rate_kw
        
        best_start = earliest_hour
        best_cost = float('inf')
        
        # Try each possible start time
        for start_hour in range(earliest_hour, latest_hour + 1):
            completion_hour = start_hour + duration_hours
            
            # Check if completes in time
            if completion_hour > required_completion_hour:
                continue
            
            cost = self.calculate_charging_cost(energy_kwh, start_hour, duration_hours)
            
            if cost < best_cost:
                best_cost = cost
                best_start = start_hour
        
        return best_start, best_cost
    
    def get_price_forecast(self, hours_ahead: int = 24) -> List[Dict]:
        """
        Get price forecast for next N hours.
        
        Args:
            hours_ahead: Number of hours to forecast
        
        Returns:
            List of dicts with hour, price, tier_name
        """
        forecast = []
        
        for hour_offset in range(hours_ahead):
            hour = hour_offset % 24
            tier = self.get_current_tier(hour)
            
            forecast.append({
                'hour': hour,
                'price_per_kwh': tier.price_per_kwh,
                'tier_name': tier.name,
                'multiplier': tier.multiplier,
            })
        
        return forecast
    
    def get_daily_summary(self) -> Dict:
        """Get summary of daily pricing structure."""
        return {
            'enabled': self.enabled,
            'base_price': self.base_price,
            'night_price': self.tiers[TimeOfDay.NIGHT].price_per_kwh,
            'peak_price': self.tiers[TimeOfDay.MORNING].price_per_kwh,
            'savings_potential': (
                self.tiers[TimeOfDay.MORNING].price_per_kwh - 
                self.tiers[TimeOfDay.NIGHT].price_per_kwh
            ),
            'tiers': {
                tod.value: {
                    'name': tier.name,
                    'price': tier.price_per_kwh,
                    'hours': tier.time_ranges,
                }
                for tod, tier in self.tiers.items()
            }
        }


@dataclass
class SmartChargingSession:
    """Represents a smart charging session."""
    agent_id: str
    vehicle_mode: str
    energy_needed_kwh: float
    charging_rate_kw: float
    earliest_start: int
    latest_completion: int
    scheduled_start: Optional[int] = None
    estimated_cost: Optional[float] = None
    actual_cost: Optional[float] = None


class SmartChargingOptimizer:
    """
    Optimizes EV charging schedules to minimize cost and grid impact.
    
    Features:
    - Cost minimization via off-peak charging
    - Grid load balancing
    - User preference consideration (urgency vs. cost)
    """
    
    def __init__(
        self,
        pricing_manager: TimeOfDayPricingManager,
        max_concurrent_sessions: int = 50
    ):
        """
        Initialize smart charging optimizer.
        
        Args:
            pricing_manager: TimeOfDayPricingManager instance
            max_concurrent_sessions: Max simultaneous charging sessions
        """
        self.pricing = pricing_manager
        self.max_concurrent = max_concurrent_sessions
        self.active_sessions: Dict[str, SmartChargingSession] = {}
        
        logger.info(f"Smart charging optimizer initialized: max_concurrent={max_concurrent_sessions}")
    
    def schedule_charging(
        self,
        agent_id: str,
        vehicle_mode: str,
        energy_needed_kwh: float,
        charging_rate_kw: float,
        urgency: str = 'normal',
        earliest_hour: int = 0,
        latest_hour: int = 23
    ) -> SmartChargingSession:
        """
        Schedule optimal charging session for agent.
        
        Args:
            agent_id: Agent identifier
            vehicle_mode: Vehicle type (ev, van_electric, etc.)
            energy_needed_kwh: Energy to charge (kWh)
            charging_rate_kw: Charging power (kW)
            urgency: 'immediate', 'normal', or 'flexible'
            earliest_hour: Earliest acceptable start
            latest_hour: Latest acceptable start
        
        Returns:
            SmartChargingSession with scheduled start time
        """
        # Determine completion deadline based on urgency
        if urgency == 'immediate':
            required_completion = earliest_hour + 2  # Within 2 hours
        elif urgency == 'normal':
            required_completion = earliest_hour + 8  # Within 8 hours
        else:  # flexible
            required_completion = latest_hour
        
        # Find optimal charging window
        optimal_start, estimated_cost = self.pricing.find_optimal_charging_window(
            energy_kwh=energy_needed_kwh,
            charging_rate_kw=charging_rate_kw,
            earliest_hour=earliest_hour,
            latest_hour=latest_hour,
            required_completion_hour=required_completion
        )
        
        session = SmartChargingSession(
            agent_id=agent_id,
            vehicle_mode=vehicle_mode,
            energy_needed_kwh=energy_needed_kwh,
            charging_rate_kw=charging_rate_kw,
            earliest_start=earliest_hour,
            latest_completion=required_completion,
            scheduled_start=optimal_start,
            estimated_cost=estimated_cost
        )
        
        self.active_sessions[agent_id] = session
        
        logger.debug(f"Scheduled charging for {agent_id}: start={optimal_start}h, cost=£{estimated_cost:.2f}")
        
        return session
    
    def complete_session(self, agent_id: str, actual_cost: float) -> None:
        """Mark charging session as complete."""
        if agent_id in self.active_sessions:
            self.active_sessions[agent_id].actual_cost = actual_cost
            del self.active_sessions[agent_id]
    
    def get_load_profile(self, hours_ahead: int = 24) -> Dict[int, float]:
        """
        Get predicted grid load from scheduled charging.
        
        Args:
            hours_ahead: Hours to forecast
        
        Returns:
            Dict mapping hour to total load (kW)
        """
        load_profile = {h: 0.0 for h in range(hours_ahead)}
        
        for session in self.active_sessions.values():
            if session.scheduled_start is not None:
                duration_hours = session.energy_needed_kwh / session.charging_rate_kw
                
                for hour_offset in range(int(duration_hours) + 1):
                    hour = (session.scheduled_start + hour_offset) % 24
                    if hour < hours_ahead:
                        load_profile[hour] += session.charging_rate_kw
        
        return load_profile
    
    def get_cost_savings_report(self) -> Dict:
        """Generate report on smart charging cost savings."""
        if not self.active_sessions:
            return {'total_sessions': 0}
        
        total_estimated = sum(
            s.estimated_cost for s in self.active_sessions.values()
            if s.estimated_cost is not None
        )
        
        # Calculate what immediate charging would have cost
        immediate_cost = sum(
            self.pricing.calculate_charging_cost(
                s.energy_needed_kwh,
                s.earliest_start,
                s.energy_needed_kwh / s.charging_rate_kw
            )
            for s in self.active_sessions.values()
        )
        
        savings = immediate_cost - total_estimated
        savings_pct = (savings / immediate_cost * 100) if immediate_cost > 0 else 0
        
        return {
            'total_sessions': len(self.active_sessions),
            'immediate_cost': immediate_cost,
            'optimized_cost': total_estimated,
            'savings': savings,
            'savings_percentage': savings_pct,
        }