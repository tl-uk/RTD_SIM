"""
simulation/execution/system_dynamics_integration.py

Phase 5.3: Integration helpers for System Dynamics in simulation loop

Provides clean interface for:
- Initializing SD from config
- Updating SD each step
- Accessing SD state for UI/analytics
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Optional, List, Dict, Any
import logging

if TYPE_CHECKING:
    from agent.system_dynamics import StreamingSystemDynamics, DiscreteEvent
    from simulation.config.simulation_config import SimulationConfig

logger = logging.getLogger(__name__)


def initialize_system_dynamics(config: 'SimulationConfig') -> Optional['StreamingSystemDynamics']:
    """
    Initialize System Dynamics engine from simulation config.
    
    Args:
        config: SimulationConfig with system_dynamics sub-config
    
    Returns:
        StreamingSystemDynamics instance or None if disabled
    """
    try:
        from agent.system_dynamics import StreamingSystemDynamics
        
        # Use config default as a fallback only — the SD update() method
        # overwrites ev_adoption_stock with actual agent data on the first
        # call, so this value is only used for logging and history[0].
        # Keeping it at 0.05 while actual agents start at 35%+ causes the
        # first history entry to be wrong and confuses the chart.
        #
        # The correct approach: pass 0.0 and let the first update() set it.
        # The update() will immediately replace it with actual agent data.
        initial_adoption = 0.0   # SD stocks are always agent-reality driven
 
        sd = StreamingSystemDynamics(
            initial_adoption=initial_adoption,
            config=config
        )
        
        logger.info(f"✅ System Dynamics initialized: EV={initial_adoption:.1%}, "
                   f"r={sd.state.ev_growth_rate_r:.3f}, K={sd.state.ev_carrying_capacity_K:.1%}")
        
        return sd
        
    except ImportError as e:
        logger.warning(f"System Dynamics module not found: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to initialize System Dynamics: {e}")
        import traceback
        traceback.print_exc()
        return None


def update_system_dynamics(
    system_dynamics: 'StreamingSystemDynamics',
    step: int,
    agents: List,
    infrastructure: Any,
    dt: float = 1.0
) -> List['DiscreteEvent']:
    """
    Update System Dynamics state for current simulation step.
    
    Args:
        system_dynamics: StreamingSystemDynamics instance
        step: Current simulation step number
        agents: List of agents
        infrastructure: InfrastructureManager instance
        dt: Time delta (usually 1.0 for step-based simulation)
    
    Returns:
        List of discrete events triggered by threshold crossings
    """
    if system_dynamics is None:
        return []
    
    try:
        # Count EVs among agents
        EV_MODES = {'ev', 'van_electric', 'truck_electric', 'hgv_electric', 'hgv_hydrogen'}
        ev_count = sum(1 for agent in agents if agent.state.mode in EV_MODES)
        total_agents = len(agents)
        
        # Get grid state
        grid_load = 0.0
        if infrastructure and hasattr(infrastructure, 'grid'):
            try:
                grid_load = infrastructure.grid.current_load_mw
            except:
                pass
        
        # Get emissions (if tracked)
        emissions = sum(getattr(agent.state, 'emissions_g', 0) for agent in agents) / 1000.0  # g → kg
        
        # Get infrastructure capacity (charger count as proxy)
        infrastructure_capacity = 100.0
        if infrastructure:
            try:
                infrastructure_capacity = len(infrastructure.charging_stations)
            except:
                pass
        
        # Update SD
        events = system_dynamics.update(
            ev_count=ev_count,
            total_agents=total_agents,
            grid_load=grid_load,
            emissions=emissions,
            infrastructure_capacity=infrastructure_capacity,
            dt=dt
        )
        
        # Log significant events
        for event in events:
            if event.severity in ['high', 'critical']:
                logger.info(f"🎯 SD Event: {event.event_type} - {event.data.get('description', '')}")
        
        return events
        
    except Exception as e:
        logger.error(f"Failed to update System Dynamics at step {step}: {e}")
        return []


def get_system_dynamics_state(system_dynamics: 'StreamingSystemDynamics') -> Dict[str, Any]:
    """
    Extract current SD state for logging/UI.
    
    Args:
        system_dynamics: StreamingSystemDynamics instance
    
    Returns:
        Dict with current state snapshot
    """
    if system_dynamics is None:
        return {}
    
    try:
        return system_dynamics.get_state_summary()
    except Exception as e:
        logger.error(f"Failed to get SD state: {e}")
        return {}


def get_system_dynamics_history(system_dynamics: 'StreamingSystemDynamics') -> List[Dict]:
    """
    Get complete SD history for analysis/plotting.
    
    Args:
        system_dynamics: StreamingSystemDynamics instance
    
    Returns:
        List of state snapshots over time
    """
    if system_dynamics is None:
        return []
    
    try:
        return system_dynamics.history
    except Exception as e:
        logger.error(f"Failed to get SD history: {e}")
        return []