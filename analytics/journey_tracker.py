"""
analytics/journey_tracker.py

This module provides journey-level metrics and analysis. 

The JourneyTracker class captures detailed data for each agent's journey, including 
decisions made, performance outcomes, and influencing factors such as weather and social 
influence. It also provides methods to analyze this data, generate statistics, and produce 
summary reports. This allows us to understand not just what decisions agents are making, 
but why they are making them and how those decisions play out in terms of costs, emissions, 
and overall journey success.

Key features:
- Comprehensive data capture for each journey, including decision context and performance metrics.
- Analysis of decision factors to understand what influences mode choice.
- Assessment of weather impact on journey outcomes.
- Measurement of social influence patterns.
- Generation of summary reports for overall insights into agent behavior and system performance.

Bottom line: Tracks individual agent decisions, journey performance, and influencing factors.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict
import logging
import numpy as np

logger = logging.getLogger(__name__)

# ==============================================================================
# Data Classes for Journey Metrics
# ==============================================================================

# JourneyMetrics class to represent the complete data for a single agent's journey, including
# decision context, performance outcomes, costs, emissions, weather influence, and social
# influence. This structured representation allows for detailed analysis of each journey and
# the factors that influenced it, which can be used to understand agent behavior and the
# effectiveness of policies in the simulation.
@dataclass
class JourneyMetrics:
    """Complete journey data for a single agent at a single step."""
    
    # Identity
    agent_id: str
    step: int
    timestamp: float  # Simulation time
    
    # Decision context
    mode_chosen: str
    alternatives_available: List[str]
    decision_factors: Dict[str, float] = field(default_factory=dict)  # cost, time, comfort, emissions
    
    # Journey performance
    origin: Optional[Tuple[float, float]] = None
    destination: Optional[Tuple[float, float]] = None
    planned_distance_km: float = 0.0
    actual_distance_km: float = 0.0
    planned_time_min: float = 0.0
    actual_time_min: float = 0.0
    delay_min: float = 0.0
    arrived: bool = False
    
    # Costs
    financial_cost: float = 0.0
    time_cost: float = 0.0
    comfort_cost: float = 0.0
    
    # Environmental impact
    co2e_kg: float = 0.0
    pm25_g: float = 0.0
    nox_g: float = 0.0
    air_quality_exposure: float = 0.0  # μg/m³·hour
    
    # Weather influence
    temperature: float = 10.0
    precipitation: float = 0.0
    ice_warning: bool = False
    weather_speed_penalty: float = 0.0  # 0.0 = no penalty, 0.5 = 50% slower
    
    # Social influence
    influenced_by: List[str] = field(default_factory=list)  # Agent IDs
    influence_strength: float = 0.0
    habit_strength: float = 0.0
    
    # Agent characteristics
    persona: str = "unknown"
    job: str = "unknown"
    vehicle_required: bool = False
    cargo_capacity: bool = False

# =============================================================================
# Journey Tracker Class
# =============================================================================

# JourneyTracker class to capture and analyze journey-level data for all agents in the simulation,
# allowing for detailed insights into decision factors, performance outcomes, weather impact, and
# social influence patterns. This class provides methods to record journeys, query data, and generate
# statistics and summary reports, enabling a comprehensive understanding of agent behavior and system
# performance at the journey level.
class JourneyTracker:
    """
    Comprehensive journey-level data collection and analysis.
    
    Captures detailed metrics for every agent movement, enabling:
    - Decision factor analysis
    - Performance tracking
    - Weather impact assessment
    - Social influence measurement
    """
    
    def __init__(self):
        """Initialize journey tracker."""
        self.journeys: List[JourneyMetrics] = []
        self._journey_count = 0
        
        # Quick lookup caches
        self._journeys_by_agent: Dict[str, List[JourneyMetrics]] = defaultdict(list)
        self._journeys_by_mode: Dict[str, List[JourneyMetrics]] = defaultdict(list)
        self._journeys_by_step: Dict[int, List[JourneyMetrics]] = defaultdict(list)
        
        logger.info("✅ JourneyTracker initialized")
    
    def record_journey(
        self,
        agent,
        step: int,
        decision_factors: Optional[Dict[str, float]] = None,
        weather_conditions: Optional[Dict] = None,
        social_influence: Optional[Dict] = None,
        emissions: Optional[Dict] = None
    ) -> JourneyMetrics:
        """
        Record a journey for an agent at current step.
        
        Args:
            agent: Agent instance
            step: Current simulation step
            decision_factors: Cost, time, comfort, emissions weights
            weather_conditions: Current weather state
            social_influence: Who influenced this agent
            emissions: Journey emissions data
        
        Returns:
            JourneyMetrics instance
        """
        # Extract agent state
        state = agent.state
        
        # Create journey record
        journey = JourneyMetrics(
            agent_id=agent.state.agent_id,
            step=step,
            timestamp=step / 60.0,  # Convert to hours
            mode_chosen=state.mode,
            alternatives_available=getattr(agent, 'available_modes', []),
            decision_factors=decision_factors or {},
        )
        
        # Journey performance
        journey.origin = getattr(state, 'origin', None)
        journey.destination = state.destination
        journey.actual_distance_km = state.distance_km
        journey.arrived = state.arrived
        
        # Costs (if agent has these attributes)
        if hasattr(state, 'last_trip_cost'):
            journey.financial_cost = state.last_trip_cost
        if hasattr(state, 'last_trip_time'):
            journey.actual_time_min = state.last_trip_time
        
        # Environmental impact
        if emissions:
            journey.co2e_kg = emissions.get('co2e_kg', 0.0)
            journey.pm25_g = emissions.get('pm25_g', 0.0)
            journey.nox_g = emissions.get('nox_g', 0.0)
        
        # Weather influence
        if weather_conditions:
            journey.temperature = weather_conditions.get('temperature', 10.0)
            journey.precipitation = weather_conditions.get('precipitation', 0.0)
            journey.ice_warning = weather_conditions.get('ice_warning', False)
            journey.weather_speed_penalty = 1.0 - weather_conditions.get('speed_multiplier', 1.0)
        
        # Social influence
        if social_influence:
            journey.influenced_by = social_influence.get('influenced_by', [])
            journey.influence_strength = social_influence.get('strength', 0.0)
        
        if hasattr(agent, 'habit_strength'):
            journey.habit_strength = agent.habit_strength.get(state.mode, 0.0)
        
        # Agent characteristics
        if hasattr(agent, 'persona'):
            journey.persona = agent.persona
        if hasattr(agent, 'job'):
            journey.job = agent.job
        
        context = getattr(agent, 'agent_context', {})
        journey.vehicle_required = context.get('vehicle_required', False)
        journey.cargo_capacity = context.get('cargo_capacity', False)
        
        # Store journey
        self.journeys.append(journey)
        self._journeys_by_agent[agent.state.agent_id].append(journey)
        self._journeys_by_mode[state.mode].append(journey)
        self._journeys_by_step[step].append(journey)
        self._journey_count += 1
        
        return journey
    
    # =========================================================================
    # Query Methods
    # =========================================================================
    
    def get_journeys_by_agent(self, agent_id: str) -> List[JourneyMetrics]:
        """Get all journeys for a specific agent."""
        return self._journeys_by_agent.get(agent_id, [])
    
    def get_journeys_by_mode(self, mode: str) -> List[JourneyMetrics]:
        """Get all journeys using a specific mode."""
        return self._journeys_by_mode.get(mode, [])
    
    def get_journeys_by_step(self, step: int) -> List[JourneyMetrics]:
        """Get all journeys at a specific step."""
        return self._journeys_by_step.get(step, [])
    
    def get_journeys_in_range(self, start_step: int, end_step: int) -> List[JourneyMetrics]:
        """Get journeys within a step range."""
        journeys = []
        for step in range(start_step, end_step + 1):
            journeys.extend(self._journeys_by_step.get(step, []))
        return journeys
    
    # =========================================================================
    # Statistical Analysis
    # =========================================================================
    
    def get_journey_statistics(self, mode: Optional[str] = None) -> Dict:
        """
        Calculate statistical distributions for journey metrics.
        
        Args:
            mode: Filter by mode (None = all modes)
        
        Returns:
            Dict with mean, std, min, max, percentiles
        """
        journeys = self._journeys_by_mode[mode] if mode else self.journeys
        
        if not journeys:
            return {}
        
        # Extract metrics
        distances = [j.actual_distance_km for j in journeys if j.actual_distance_km > 0]
        times = [j.actual_time_min for j in journeys if j.actual_time_min > 0]
        costs = [j.financial_cost for j in journeys if j.financial_cost > 0]
        emissions = [j.co2e_kg for j in journeys if j.co2e_kg > 0]
        delays = [j.delay_min for j in journeys if j.delay_min != 0]
        
        stats = {
            'total_journeys': len(journeys),
            'completed_journeys': sum(1 for j in journeys if j.arrived),
            'completion_rate': sum(1 for j in journeys if j.arrived) / len(journeys) if journeys else 0,
        }
        
        # Distance statistics
        if distances:
            stats['distance'] = {
                'mean': np.mean(distances),
                'std': np.std(distances),
                'min': np.min(distances),
                'max': np.max(distances),
                'median': np.median(distances),
                'p25': np.percentile(distances, 25),
                'p75': np.percentile(distances, 75),
            }
        
        # Time statistics
        if times:
            stats['time'] = {
                'mean': np.mean(times),
                'std': np.std(times),
                'min': np.min(times),
                'max': np.max(times),
                'median': np.median(times),
            }
        
        # Cost statistics
        if costs:
            stats['cost'] = {
                'mean': np.mean(costs),
                'std': np.std(costs),
                'total': np.sum(costs),
            }
        
        # Emissions statistics
        if emissions:
            stats['emissions'] = {
                'mean': np.mean(emissions),
                'total': np.sum(emissions),
                'per_km': np.sum(emissions) / np.sum(distances) if distances else 0,
            }
        
        # Delay statistics
        if delays:
            stats['delay'] = {
                'mean': np.mean(delays),
                'median': np.median(delays),
                'max': np.max(delays),
            }
        
        return stats
    
    def analyze_decision_factors(self, mode: Optional[str] = None) -> Dict[str, float]:
        """
        Analyze which factors influence mode choice decisions.
        
        Returns importance scores for each decision factor.
        """
        journeys = self._journeys_by_mode[mode] if mode else self.journeys
        
        if not journeys:
            return {}
        
        # Aggregate factor weights across all decisions
        factor_totals = defaultdict(float)
        factor_counts = defaultdict(int)
        
        for journey in journeys:
            for factor, weight in journey.decision_factors.items():
                factor_totals[factor] += abs(weight)
                factor_counts[factor] += 1
        
        # Calculate average importance
        factor_importance = {}
        for factor in factor_totals:
            factor_importance[factor] = factor_totals[factor] / factor_counts[factor]
        
        # Normalize to percentages
        total = sum(factor_importance.values())
        if total > 0:
            factor_importance = {
                factor: (weight / total) * 100
                for factor, weight in factor_importance.items()
            }
        
        return dict(sorted(factor_importance.items(), key=lambda x: x[1], reverse=True))
    
    def analyze_weather_impact(self) -> Dict:
        """
        Analyze how weather affects journey performance.
        
        Returns:
            Dict with weather impact metrics
        """
        # Group by weather conditions
        clear_weather = [j for j in self.journeys if j.precipitation == 0 and j.temperature > 5]
        cold_weather = [j for j in self.journeys if j.temperature < 0]
        rain = [j for j in self.journeys if j.precipitation > 0]
        ice = [j for j in self.journeys if j.ice_warning]
        
        def avg_delay(journeys):
            delays = [j.delay_min for j in journeys if j.delay_min > 0]
            return np.mean(delays) if delays else 0.0
        
        def avg_speed_penalty(journeys):
            penalties = [j.weather_speed_penalty for j in journeys]
            return np.mean(penalties) if penalties else 0.0
        
        return {
            'clear_weather': {
                'journeys': len(clear_weather),
                'avg_delay': avg_delay(clear_weather),
                'avg_speed_penalty': avg_speed_penalty(clear_weather),
            },
            'cold_weather': {
                'journeys': len(cold_weather),
                'avg_delay': avg_delay(cold_weather),
                'avg_speed_penalty': avg_speed_penalty(cold_weather),
            },
            'rain': {
                'journeys': len(rain),
                'avg_delay': avg_delay(rain),
                'avg_speed_penalty': avg_speed_penalty(rain),
            },
            'ice': {
                'journeys': len(ice),
                'avg_delay': avg_delay(ice),
                'avg_speed_penalty': avg_speed_penalty(ice),
            },
        }
    
    def analyze_social_influence(self) -> Dict:
        """
        Analyze social influence patterns on mode choice.
        
        Returns:
            Dict with influence metrics
        """
        influenced = [j for j in self.journeys if j.influenced_by]
        not_influenced = [j for j in self.journeys if not j.influenced_by]
        
        return {
            'total_journeys': len(self.journeys),
            'influenced_journeys': len(influenced),
            'influence_rate': len(influenced) / len(self.journeys) if self.journeys else 0,
            'avg_influence_strength': np.mean([j.influence_strength for j in influenced]) if influenced else 0,
            'influenced_by_mode': self._group_by_mode(influenced),
            'not_influenced_by_mode': self._group_by_mode(not_influenced),
        }
    
    def _group_by_mode(self, journeys: List[JourneyMetrics]) -> Dict[str, int]:
        """Group journeys by mode and count."""
        mode_counts = defaultdict(int)
        for journey in journeys:
            mode_counts[journey.mode_chosen] += 1
        return dict(mode_counts)
    
    # =========================================================================
    # Summary Reports
    # =========================================================================
    
    def generate_summary_report(self) -> Dict:
        """
        Generate comprehensive summary of all journey data.
        
        Returns:
            Dict with all key metrics and insights
        """
        report = {
            'overview': {
                'total_journeys': len(self.journeys),
                'unique_agents': len(self._journeys_by_agent),
                'modes_used': list(self._journeys_by_mode.keys()),
                'simulation_steps': len(self._journeys_by_step),
            },
            'statistics_by_mode': {},
            'decision_factors': self.analyze_decision_factors(),
            'weather_impact': self.analyze_weather_impact(),
            'social_influence': self.analyze_social_influence(),
        }
        
        # Add per-mode statistics
        for mode in self._journeys_by_mode.keys():
            report['statistics_by_mode'][mode] = self.get_journey_statistics(mode)
        
        return report
    
    def get_weather_impact_stats(self) -> Dict[str, Any]:
        """
        Get statistics on weather impact on journeys.
        
        Returns breakdown by weather condition:
        - Clear (temp > 5, no precip, no ice)
        - Cold (temp <= 0)
        - Rain (precip > 0)
        - Ice (ice_warning = True)
        """
        stats = {
            'clear': 0,
            'cold': 0,
            'rain': 0,
            'ice': 0,
            'total': len(self.journeys)
        }
        
        for journey in self.journeys:
            # Categorize weather
            if journey.ice_warning:
                stats['ice'] += 1
            elif journey.precipitation > 0:
                stats['rain'] += 1
            elif journey.temperature <= 0:
                stats['cold'] += 1
            else:
                stats['clear'] += 1
        
        return stats
    
    def get_summary_statistics(self) -> Dict:
        """Quick summary statistics for display."""
        if not self.journeys:
            return {'total_journeys': 0}
        
        return {
            'total_journeys': len(self.journeys),
            'completed': sum(1 for j in self.journeys if j.arrived),
            'completion_rate': sum(1 for j in self.journeys if j.arrived) / len(self.journeys),
            'total_distance_km': sum(j.actual_distance_km for j in self.journeys),
            'total_emissions_kg': sum(j.co2e_kg for j in self.journeys),
            'avg_delay_min': np.mean([j.delay_min for j in self.journeys if j.delay_min > 0]) if any(j.delay_min > 0 for j in self.journeys) else 0,
            'influenced_rate': len([j for j in self.journeys if j.influenced_by]) / len(self.journeys),
        }