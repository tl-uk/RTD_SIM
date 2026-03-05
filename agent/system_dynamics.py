"""
agent/system_dynamics.py

This module implements Streaming System Dynamics for Real-Time Digital Twin.
It models continuous variables like EV adoption, grid load, and emissions, while also 
monitoring thresholds to trigger discrete events. The SD state is updated incrementally 
based on actual agent behavior and external data, rather than solving ODEs. This allows 
for real-time feedback loops between agent actions and system-level dynamics.

Implements hybrid continuous-discrete dynamics:
- Continuous: dEV_adoption/dt, dGrid_load/dt, dEmissions/dt
- Discrete: Threshold crossings → Events
- Data assimilation: Kalman-like sensor fusion (future)

NOTE: This is a first implementation and may not perfectly capture all dynamics or be 
fully calibrated.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import time
import logging

logger = logging.getLogger(__name__)

# ================================================================================
# DATA CLASSES
# ================================================================================
# Discrete event class for threshold crossings and other system-level events that agents 
# can perceive and react to.
@dataclass
class DiscreteEvent:
    """
    Discrete event triggered by continuous state threshold crossing.
    
    Attributes:
        event_type: Type identifier (e.g., 'adoption_tipping_point', 'grid_stress')
        timestamp: Unix timestamp when event occurred
        data: Event-specific data payload
        location: Optional (lon, lat) for spatial events
        radius_km: Affected area radius (for agent perception)
        severity: 'low', 'medium', 'high', 'critical'
    """
    event_type: str
    timestamp: float
    data: Dict[str, Any]
    location: Optional[tuple] = None
    radius_km: float = 10.0
    severity: str = 'medium'

# System Dynamics state class to hold continuous variables, flows, parameters, and 
# # threshold states. This is updated incrementally based on agent behavior and external 
# data, rather than solving ODEs, allowing for real-time feedback loops.
@dataclass
class StreamingSDState:
    """
    System Dynamics state (continuous variables).
    
    Updated incrementally on events, not via ODE solving.
    Aligns with RTD-AMB.docx: "Streaming SD: Event-driven stock updates"
    """
    
    # ========================================================================
    # STOCKS (State Variables)
    # ========================================================================
    ev_adoption_stock: float = 0.05        # Current EV adoption rate (0-1)
    grid_load_stock: float = 0.0           # Current grid load (MW)
    emissions_stock: float = 0.0           # Cumulative emissions (kg CO2/day)
    infrastructure_capacity_stock: float = 100.0  # Baseline charger density
    
    # ========================================================================
    # FLOWS (Rates of Change)
    # ========================================================================
    ev_adoption_flow: float = 0.0          # dEV/dt (computed each step)
    grid_load_flow: float = 0.0            # dGrid/dt
    emissions_flow: float = 0.0            # dEmissions/dt
    
    # ========================================================================
    # PARAMETERS (User-Configurable via Config)
    # ========================================================================
    # EV adoption dynamics (Logistic growth)
    ev_growth_rate_r: float = 0.05         # Base growth rate
    ev_carrying_capacity_K: float = 0.80   # Max adoption ceiling
    infrastructure_feedback_strength: float = 0.02  # Charger → adoption boost
    social_influence_strength: float = 0.03         # Peer → adoption boost
    
    # Grid dynamics
    grid_capacity: float = 100.0           # Total grid capacity (MW)
    grid_stress_threshold: float = 0.85    # Utilization % trigger
    
    # Emissions dynamics
    emissions_target_kg_day: float = 40000.0
    
    # ========================================================================
    # THRESHOLD MONITORS (For Discrete Events)
    # ========================================================================
    thresholds: Dict[str, Dict] = field(default_factory=lambda: {
        'adoption_tipping': {
            'value': 0.30,
            'crossed': False,
            'description': 'EV adoption crosses critical mass'
        },
        'grid_stress': {
            'value': 0.85,
            'crossed': False,
            'description': 'Grid utilization exceeds safe threshold'
        },
        'emissions_target': {
            'value': 40000.0,
            'crossed': False,
            'description': 'Daily emissions exceed target'
        }
    })
    
    # ========================================================================
    # METADATA
    # ========================================================================
    last_update_time: float = field(default_factory=time.time)
    total_updates: int = 0
    
    # Confidence tracking (for data assimilation - future)
    state_confidence: Dict[str, float] = field(default_factory=lambda: {
        'ev_adoption': 1.0,
        'grid_load': 0.8,
        'emissions': 0.9
    })

# ============================================================================
# STREAMING SYSTEM DYNAMICS ENGINE
# ============================================================================
# Master function to generate freight delivery job variations based on time windows and 
# urgency levels. This creates multiple job templates programmatically, which can be used
# for testing or to populate the simulation with realistic job diversity.
class StreamingSystemDynamics:
    """
    Real-time System Dynamics engine.
    
    Key differences from traditional SD:
    - No ODE solver (scipy.integrate.odeint)
    - Event-triggered flow computation
    - Incremental Euler steps with dt from wall-clock time
    - Threshold monitoring for discrete transitions
    
    Usage:
        sd = StreamingSystemDynamics(initial_adoption=0.05)
        
        for step in simulation:
            # Aggregate agent state
            ev_count = sum(1 for a in agents if a.mode in EV_MODES)
            
            # Update continuous dynamics
            events = sd.update(
                ev_count=ev_count,
                total_agents=len(agents),
                grid_load=current_grid_load,
                dt=1.0  # 1 simulation step
            )
            
            # Handle discrete events
            for event in events:
                event_bus.publish(event)
    """
    
    def __init__(
        self,
        config: Optional[Any] = None,
        initial_adoption: float = 0.05
    ):
        """
        Initialize streaming SD state.
        
        Args:
            config: Optional SystemDynamicsConfig object (FIRST parameter for new API)
            initial_adoption: Starting EV adoption rate (0-1) - default 5%
        
        Note: Parameter order changed! Now: StreamingSystemDynamics(config)
              Old API (config, initial_adoption) still works via type detection
        """
        # Handle backward compatibility: if first arg is a float, it's the old API
        if config is not None and isinstance(config, (int, float)):
            # Old API: StreamingSystemDynamics(0.05, config)
            initial_adoption = float(config)
            config = None
        
        self.state = StreamingSDState(ev_adoption_stock=initial_adoption)
        
        # Apply config overrides if provided
        if config:
            self._apply_config(config)
        
        # History for analysis
        self.history: List[Dict[str, float]] = []
        
        logger.info(f"System Dynamics initialized: EV={initial_adoption:.1%}, "
                   f"r={self.state.ev_growth_rate_r:.3f}, K={self.state.ev_carrying_capacity_K:.1%}")
    # Apply configuration parameters to SD state, allowing for dynamic adjustment of growth rates, 
    # thresholds, and feedback strengths without needing to modify the core logic. 
    # This supports experimentation and calibration.
    def _apply_config(self, config):
        """Apply configuration parameters to SD state."""
        # Config can be either SystemDynamicsConfig directly or a SimulationConfig with .system_dynamics attr
        if hasattr(config, 'system_dynamics'):
            sd_config = config.system_dynamics
        else:
            # Assume it's already a SystemDynamicsConfig
            sd_config = config
        
        if not sd_config:
            return
        
        # EV adoption parameters
        if hasattr(sd_config, 'ev_growth_rate_r'):
            self.state.ev_growth_rate_r = sd_config.ev_growth_rate_r
        if hasattr(sd_config, 'ev_carrying_capacity_K'):
            self.state.ev_carrying_capacity_K = sd_config.ev_carrying_capacity_K
        if hasattr(sd_config, 'infrastructure_feedback_strength'):
            self.state.infrastructure_feedback_strength = sd_config.infrastructure_feedback_strength
        if hasattr(sd_config, 'social_influence_strength'):
            self.state.social_influence_strength = sd_config.social_influence_strength
        
        # Grid parameters
        if hasattr(sd_config, 'grid_stress_threshold'):
            self.state.grid_stress_threshold = sd_config.grid_stress_threshold
            self.state.thresholds['grid_stress']['value'] = sd_config.grid_stress_threshold
        
        # Emissions parameters
        if hasattr(sd_config, 'emissions_target_kg_day'):
            self.state.emissions_target_kg_day = sd_config.emissions_target_kg_day
            self.state.thresholds['emissions_target']['value'] = sd_config.emissions_target_kg_day
        
        logger.info(f"Applied config: r={self.state.ev_growth_rate_r:.3f}, "
                   f"K={self.state.ev_carrying_capacity_K:.1%}")
    
    def update(
        self,
        ev_count: int,
        total_agents: int,
        grid_load: float = 0.0,
        emissions: float = 0.0,
        infrastructure_capacity: float = 100.0,
        dt: float = 1.0
    ) -> List[DiscreteEvent]:
        """
        Update continuous dynamics and check for discrete transitions.
        
        Args:
            ev_count: Number of agents currently using EV modes
            total_agents: Total agent population
            grid_load: Current grid load in MW
            emissions: Current daily emissions in kg CO2
            infrastructure_capacity: Charging infrastructure index
            dt: Time step (simulation steps, not wall-clock)
        
        Returns:
            List of discrete events triggered by threshold crossings
        """
        # Update infrastructure capacity (for feedback)
        self.state.infrastructure_capacity_stock = infrastructure_capacity
        
        # ====================================================================
        # STEP 1: Compute Flows (Differential Equations)
        # ====================================================================
        
        # EV Adoption Flow: Logistic growth with feedbacks
        current_adoption = ev_count / total_agents if total_agents > 0 else self.state.ev_adoption_stock
        self.state.ev_adoption_flow = self._compute_ev_adoption_flow(current_adoption)
        
        # Grid Load Flow: Direct from charging demand
        self.state.grid_load_flow = (grid_load - self.state.grid_load_stock) / max(dt, 1.0)
        
        # Emissions Flow: Direct from current emissions
        self.state.emissions_flow = (emissions - self.state.emissions_stock) / max(dt, 1.0)
        
        # ====================================================================
        # STEP 2: Update Stocks (Incremental from Agent Reality)
        # ====================================================================
        
        # EV adoption: Track ACTUAL adoption from agents (not predicted)
        # The flow is a prediction; the stock is reality
        actual_adoption = ev_count / total_agents if total_agents > 0 else 0.0
        self.state.ev_adoption_stock = actual_adoption
        
        # Grid load updates from actual charging
        self.state.grid_load_stock = grid_load
        
        # Emissions accumulate from actual transport
        self.state.emissions_stock = emissions
        
        # ====================================================================
        # STEP 3: Check Thresholds → Generate Discrete Events
        # ====================================================================
        
        discrete_events = self._check_threshold_crossings()
        
        # ====================================================================
        # STEP 4: Record History
        # ====================================================================
        
        self.history.append({
            'step': self.state.total_updates,
            'ev_adoption': self.state.ev_adoption_stock,
            'ev_adoption_flow': self.state.ev_adoption_flow,
            'grid_load': self.state.grid_load_stock,
            'grid_utilization': self.state.grid_load_stock / self.state.grid_capacity if self.state.grid_capacity > 0 else 0,
            'emissions': self.state.emissions_stock,
            'timestamp': time.time(),
            # Add threshold states to history for UI display and analysis.
            # Map internal keys to UI-expected keys
            'thresholds_crossed': {
                'adoption_tipping_point': self.state.thresholds['adoption_tipping']['crossed'],
                'grid_threshold_exceeded': self.state.thresholds['grid_stress']['crossed'],
                'emissions_target_exceeded': self.state.thresholds['emissions_target']['crossed'],
            },
            # Add SD parameters for UI display  
            'ev_growth_rate_r': self.state.ev_growth_rate_r,
            'ev_carrying_capacity_K': self.state.ev_carrying_capacity_K,
        })
        
        self.state.total_updates += 1
        self.state.last_update_time = time.time()
        
        return discrete_events
    
    # =============================================================================
    # INTERNAL METHODS
    # =============================================================================

    # Helper function to compute EV adoption flow based on logistic growth and feedbacks.
    # This is the core of the continuous dynamics, and it incorporates both the natural 
    # growth of adoption and the influence of infrastructure and social factors.
    # The flow is a prediction of how adoption would change based on current conditions, 
    # but the actual stock is updated from agent reality, allowing for feedback loops.
    # This separation of flow (theoretical change) and stock (actual state) is key to the 
    # streaming SD approach, where we want to model the dynamics but also ground them in 
    # the reality of agent behavior and external data. This allows for more realistic and 
    # responsive system dynamics that can adapt to the complexity of a real-time 
    # digital twin environment.
    def _compute_ev_adoption_flow(self, current_adoption: float) -> float:
        """
        Compute dEV_adoption/dt using logistic growth with feedbacks.
        
        Equation:
            dEV/dt = r * EV * (1 - EV/K) + infrastructure_feedback + social_feedback
        
        Where:
            r = Base growth rate
            K = Carrying capacity (max adoption ceiling)
            EV = Current adoption rate
        
        Args:
            current_adoption: Current EV adoption rate (0-1)
        
        Returns:
            Flow value (change per time step)
        """
        # Base logistic growth
        r = self.state.ev_growth_rate_r
        K = self.state.ev_carrying_capacity_K
        
        # Logistic term: r * N * (1 - N/K)
        logistic_growth = r * current_adoption * (1.0 - current_adoption / K)
        
        # Infrastructure feedback: More chargers → faster adoption
        infrastructure_boost = (
            self.state.infrastructure_capacity_stock / 100.0 
            * self.state.infrastructure_feedback_strength
        )
        
        # Social influence feedback: Higher adoption → stronger network effects
        social_boost = (
            current_adoption 
            * self.state.social_influence_strength
        )
        
        # Total flow
        total_flow = logistic_growth + infrastructure_boost + social_boost
        
        return total_flow
    
    def _check_threshold_crossings(self) -> List[DiscreteEvent]:
        """
        Monitor continuous state for discrete transitions.
        
        When thresholds are crossed, generate discrete events for:
        - Agent perception (agents need to know something changed)
        - Policy engine triggers (infrastructure expansion, etc.)
        - UI notifications (alert user to phase transitions)
        
        Returns:
            List of discrete events (empty if no crossings)
        """
        events = []
        
        # ====================================================================
        # Threshold 1: EV Adoption Tipping Point (30%)
        # ====================================================================
        adoption_threshold = self.state.thresholds['adoption_tipping']['value']
        
        if self.state.ev_adoption_stock > adoption_threshold:
            if not self.state.thresholds['adoption_tipping']['crossed']:
                logger.info(f"🎯 TIPPING POINT: EV adoption crossed {adoption_threshold:.0%}")
                
                events.append(DiscreteEvent(
                    event_type='adoption_tipping_point',
                    timestamp=time.time(),
                    data={
                        'adoption_rate': self.state.ev_adoption_stock,
                        'threshold': adoption_threshold,
                        'description': 'Critical mass reached - expect accelerated adoption'
                    },
                    location=None,  # System-wide event
                    radius_km=float('inf'),  # All agents should perceive
                    severity='high'
                ))
                
                self.state.thresholds['adoption_tipping']['crossed'] = True
        else:
            # Reset if dropped back below (hysteresis)
            self.state.thresholds['adoption_tipping']['crossed'] = False
        
        # ====================================================================
        # Threshold 2: Grid Stress (85% utilization)
        # ====================================================================
        if self.state.grid_capacity > 0:
            grid_utilization = self.state.grid_load_stock / self.state.grid_capacity
            grid_threshold = self.state.thresholds['grid_stress']['value']
            
            if grid_utilization > grid_threshold:
                if not self.state.thresholds['grid_stress']['crossed']:
                    logger.warning(f"🚨 GRID STRESS: Utilization {grid_utilization:.1%} > {grid_threshold:.1%}")
                    
                    events.append(DiscreteEvent(
                        event_type='grid_threshold_exceeded',
                        timestamp=time.time(),
                        data={
                            'utilization': grid_utilization,
                            'threshold': grid_threshold,
                            'load_mw': self.state.grid_load_stock,
                            'capacity_mw': self.state.grid_capacity,
                            'description': 'Grid capacity stressed - expansion recommended'
                        },
                        location=None,
                        radius_km=float('inf'),
                        severity='critical'
                    ))
                    
                    self.state.thresholds['grid_stress']['crossed'] = True
            else:
                self.state.thresholds['grid_stress']['crossed'] = False
        
        # ====================================================================
        # Threshold 3: Emissions Target Exceeded
        # ====================================================================
        emissions_threshold = self.state.thresholds['emissions_target']['value']
        
        if self.state.emissions_stock > emissions_threshold:
            if not self.state.thresholds['emissions_target']['crossed']:
                logger.warning(f"🌍 EMISSIONS: {self.state.emissions_stock:.0f} kg > target {emissions_threshold:.0f} kg")
                
                events.append(DiscreteEvent(
                    event_type='emissions_target_exceeded',
                    timestamp=time.time(),
                    data={
                        'emissions': self.state.emissions_stock,
                        'target': emissions_threshold,
                        'overshoot': self.state.emissions_stock - emissions_threshold,
                        'description': 'Daily emissions exceed carbon budget'
                    },
                    location=None,
                    radius_km=float('inf'),
                    severity='medium'
                ))
                
                self.state.thresholds['emissions_target']['crossed'] = True
        else:
            self.state.thresholds['emissions_target']['crossed'] = False
        
        return events
    
    def get_state_summary(self) -> Dict[str, Any]:
        """Get current state as dict (for UI/logging)."""
        return {
            'ev_adoption': self.state.ev_adoption_stock,
            'ev_adoption_flow': self.state.ev_adoption_flow,
            'grid_load_mw': self.state.grid_load_stock,
            'grid_utilization': self.state.grid_load_stock / self.state.grid_capacity if self.state.grid_capacity > 0 else 0,
            'emissions_kg': self.state.emissions_stock,
            'total_updates': self.state.total_updates,
            'thresholds_crossed': {
                k: v['crossed'] for k, v in self.state.thresholds.items()
            }
        }
    
    def reset(self):
        """Reset state to initial conditions."""
        initial_adoption = self.state.ev_adoption_stock
        self.state = StreamingSDState(ev_adoption_stock=initial_adoption)
        self.history.clear()
        logger.info("System Dynamics state reset")