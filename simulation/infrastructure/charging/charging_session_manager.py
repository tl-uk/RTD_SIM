"""
simulation/infrastructure/charging/charging_session_manager.py

Charging session management. Agent charging states are tracked, including start and end times,
charging rates, and session durations. This module interfaces with the station registry and
availability tracker to ensure efficient allocation of charging resources.

"""

from __future__ import annotations
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class ChargingSessionManager:
    """
    Manages active charging sessions for all agents.
    
    Responsibilities:
    - Track which agents are charging where
    - Manage session lifecycle (reserve, start, complete)
    - Session duration tracking
    - Revenue recording per session
    """
    
    def __init__(self, station_registry):
        """
        Initialize session manager.
        
        Args:
            station_registry: ChargingStationRegistry instance
        """
        self.registry = station_registry
        
        # Agent charging state: agent_id -> session_data
        self.agent_states: Dict[str, Dict] = {}
        
        # Completed sessions for analysis
        self.completed_sessions: List[Dict] = []
        
    def reserve(self, agent_id: str, station_id: str, duration_min: float) -> bool:
        """
        Reserve a charger for an agent.
        
        Args:
            agent_id: Agent identifier
            station_id: Charging station ID
            duration_min: Expected charging duration
        
        Returns:
            True if reserved successfully
        """
        if station_id not in self.registry.stations:
            logger.warning(f"Station {station_id} not found")
            return False
        
        station = self.registry.stations[station_id]
        
        if station.is_available():
            # Occupy a port
            station.currently_occupied += 1
            
            # Track agent state
            self.agent_states[agent_id] = {
                'station_id': station_id,
                'start_time': None,  # Set when charging starts
                'duration_min': duration_min,
                'status': 'reserved'
            }
            
            logger.debug(f"Agent {agent_id} reserved {station_id}")
            return True
        else:
            # Add to queue
            if agent_id not in station.queue:
                station.queue.append(agent_id)
                logger.debug(f"Agent {agent_id} queued at {station_id} (pos {len(station.queue)})")
            return False
    
    def start_charging(self, agent_id: str, step: int) -> bool:
        """
        Start charging session for reserved agent.
        
        Args:
            agent_id: Agent identifier
            step: Current simulation step
        
        Returns:
            True if charging started
        """
        if agent_id not in self.agent_states:
            logger.warning(f"Agent {agent_id} has no reservation")
            return False
        
        state = self.agent_states[agent_id]
        
        if state['status'] == 'reserved':
            state['status'] = 'charging'
            state['start_time'] = step
            logger.debug(f"Agent {agent_id} started charging at {state['station_id']}")
            return True
        
        return False
    
    def release(self, agent_id: str) -> None:
        """Release charger when agent finishes charging."""
        if agent_id not in self.agent_states:
            return
        
        state = self.agent_states[agent_id]
        station_id = state['station_id']
        
        if station_id in self.registry.stations:
            station = self.registry.stations[station_id]
            station.currently_occupied = max(0, station.currently_occupied - 1)
            
            # Record completed session
            self.completed_sessions.append({
                'agent_id': agent_id,
                'station_id': station_id,
                'duration_min': state['duration_min'],
                'start_time': state.get('start_time'),
            })
            
            # Process queue if available
            if station.queue and station.is_available():
                next_agent = station.queue.pop(0)
                logger.debug(f"Agent {next_agent} moved from queue to charging at {station_id}")
        
        del self.agent_states[agent_id]
        logger.debug(f"Agent {agent_id} released charger at {station_id}")
    
    def check_completion(self, agent_id: str, current_step: int) -> bool:
        """
        Check if agent's charging session is complete.
        
        Args:
            agent_id: Agent identifier
            current_step: Current simulation step
        
        Returns:
            True if session complete
        """
        if agent_id not in self.agent_states:
            return False
        
        state = self.agent_states[agent_id]
        
        if state['status'] != 'charging':
            return False
        
        start_time = state.get('start_time')
        if start_time is None:
            return False
        
        elapsed_min = (current_step - start_time) * 1.0  # Assuming 1 step = 1 min
        duration = state['duration_min']
        
        return elapsed_min >= duration
    
    def get_active_sessions(self) -> List[Dict]:
        """Get all currently active charging sessions."""
        return [
            {
                'agent_id': agent_id,
                'station_id': state['station_id'],
                'status': state['status'],
                'duration_min': state['duration_min'],
            }
            for agent_id, state in self.agent_states.items()
        ]
    
    def get_charging_agents(self) -> List[str]:
        """Get list of agent IDs currently charging."""
        return [
            agent_id
            for agent_id, state in self.agent_states.items()
            if state['status'] == 'charging'
        ]
    
    def get_session_count_by_station(self) -> Dict[str, int]:
        """Get count of active sessions per station."""
        counts = {}
        
        for state in self.agent_states.values():
            station_id = state['station_id']
            counts[station_id] = counts.get(station_id, 0) + 1
        
        return counts
    
    def get_metrics(self) -> Dict:
        """Get session metrics."""
        active_sessions = len(self.agent_states)
        charging_sessions = sum(
            1 for state in self.agent_states.values()
            if state['status'] == 'charging'
        )
        reserved_sessions = active_sessions - charging_sessions
        
        return {
            'active_charging': charging_sessions,
            'reserved': reserved_sessions,
            'total_sessions': active_sessions,
            'completed_sessions': len(self.completed_sessions),
        }