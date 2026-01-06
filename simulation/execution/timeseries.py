"""
simulation/execution/timeseries.py

TimeSeries wrapper for backward compatibility with Streamlit UI.
Provides .get_timestep() method while storing data as list internally.
"""

from typing import List, Dict, Any, Optional


class TimeSeries:
    """
    Wrapper for simulation time series data.
    
    Maintains backward compatibility with Streamlit UI expectations
    while using efficient list storage internally.
    """
    
    def __init__(self):
        """Initialize empty time series."""
        self._data: List[Dict[str, Any]] = []
    
    def append(self, timestep_data: Dict[str, Any]) -> None:
        """
        Add timestep data.
        
        Args:
            timestep_data: Dict with 'step' and 'agents' keys
        """
        self._data.append(timestep_data)
    
    def get_timestep(self, step: int) -> Optional[Dict[str, Any]]:
        """
        Get data for specific timestep (backward compatible).
        
        Args:
            step: Timestep index
        
        Returns:
            Dict with timestep data or None if out of range
        """
        if 0 <= step < len(self._data):
            return self._data[step]
        return None
    
    def __len__(self) -> int:
        """Return number of timesteps."""
        return len(self._data)
    
    def __getitem__(self, index: int) -> Dict[str, Any]:
        """Allow direct indexing."""
        return self._data[index]
    
    def __iter__(self):
        """Allow iteration."""
        return iter(self._data)
    
    def to_list(self) -> List[Dict[str, Any]]:
        """Export as list."""
        return self._data.copy()
    
    @classmethod
    def from_list(cls, data: List[Dict[str, Any]]) -> 'TimeSeries':
        """
        Create TimeSeries from list.
        
        Args:
            data: List of timestep dicts
        
        Returns:
            TimeSeries instance
        """
        ts = cls()
        ts._data = data.copy()
        return ts
    
    @property
    def num_steps(self) -> int:
        """Get number of timesteps."""
        return len(self._data)
    
    def get_all_agent_ids(self) -> List[str]:
        """Get list of all unique agent IDs across all timesteps."""
        agent_ids = set()
        for timestep in self._data:
            for agent in timestep.get('agents', []):
                agent_ids.add(agent['agent_id'])
        return sorted(list(agent_ids))
    
    def get_agent_trajectory(self, agent_id: str) -> List[Dict[str, Any]]:
        """
        Get complete trajectory for specific agent.
        
        Args:
            agent_id: Agent identifier
        
        Returns:
            List of agent states across all timesteps
        """
        trajectory = []
        for timestep in self._data:
            for agent in timestep.get('agents', []):
                if agent['agent_id'] == agent_id:
                    trajectory.append({
                        'step': timestep['step'],
                        **agent
                    })
                    break
        return trajectory
    
    def get_mode_counts(self, step: int) -> Dict[str, int]:
        """
        Get mode distribution at specific timestep.
        
        Args:
            step: Timestep index
        
        Returns:
            Dict mapping mode -> count
        """
        from collections import defaultdict
        
        timestep = self.get_timestep(step)
        if not timestep:
            return {}
        
        mode_counts = defaultdict(int)
        for agent in timestep.get('agents', []):
            mode = agent.get('mode', 'unknown')
            mode_counts[mode] += 1
        
        return dict(mode_counts)