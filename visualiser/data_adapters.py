# visualiser/data_adapters.py
"""
Data adapters for converting simulation data to visualization format.

Transforms:
- Agent states -> pydeck ScatterplotLayer data
- Routes -> pydeck PathLayer data
- Congestion -> pydeck PathLayer with colors
- Time series storage and retrieval
"""

from typing import List, Dict, Tuple, Optional
import pandas as pd
import numpy as np

# Import style configuration
try:
    from visualiser.style_config import (
        MODE_COLORS, get_congestion_color, get_congestion_width
    )
except ImportError:
    # Fallback if style_config not available
    MODE_COLORS = {
        'walk': [34, 197, 94],
        'bike': [59, 130, 246],
        'bus': [245, 158, 11],
        'car': [239, 68, 68],
        'ev': [168, 85, 245],
    }
    
    def get_congestion_color(factor: float) -> List[int]:
        """Simple congestion color fallback."""
        normalized = min(1.0, max(0.0, (factor - 1.0) / 2.0))
        if normalized < 0.5:
            r = int(255 * (normalized * 2))
            g = 255
            b = 0
        else:
            r = 255
            g = int(255 * (1 - (normalized - 0.5) * 2))
            b = 0
        return [r, g, b]
    
    def get_congestion_width(factor: float) -> float:
        """Simple congestion width fallback."""
        normalized = min(1.0, (factor - 1.0) / 2.0)
        return 2 + (10 - 2) * normalized


class AgentDataAdapter:
    """Convert agent states to pydeck-compatible format."""
    
    @staticmethod
    def agents_to_dataframe(
        agent_states: List[Dict],
        timestep: int
    ) -> pd.DataFrame:
        """
        Convert list of agent states to DataFrame for ScatterplotLayer.
        
        Args:
            agent_states: List of dicts with keys:
                - agent_id: Unique identifier
                - location: (lon, lat) tuple
                - mode: Transport mode
                - arrived: Boolean
                - distance_km: Distance traveled (optional)
                - emissions_g: Emissions (optional)
            timestep: Current simulation timestep
        
        Returns:
            DataFrame with columns: lon, lat, color, agent_id, mode, arrived, timestep
        """
        if not agent_states:
            return pd.DataFrame(columns=[
                'lon', 'lat', 'color', 'agent_id', 'mode', 'arrived', 'timestep'
            ])
        
        data = []
        for state in agent_states:
            loc = state.get('location')
            
            # Validate location
            if not loc or not isinstance(loc, (list, tuple)) or len(loc) != 2:
                continue
            
            try:
                lon, lat = float(loc[0]), float(loc[1])
            except (ValueError, TypeError):
                continue
            
            # Get mode and color
            mode = state.get('mode', 'walk')
            color = MODE_COLORS.get(mode, [128, 128, 128])
            
            data.append({
                'lon': lon,
                'lat': lat,
                'color': color,
                'agent_id': state.get('agent_id', ''),
                'mode': mode,
                'arrived': bool(state.get('arrived', False)),
                'timestep': timestep,
            })
        
        return pd.DataFrame(data)
    
    @staticmethod
    def get_agent_summary_stats(agent_states: List[Dict]) -> Dict:
        """
        Calculate summary statistics for current agent states.
        
        Args:
            agent_states: List of agent state dictionaries
        
        Returns:
            Dictionary with summary statistics
        """
        if not agent_states:
            return {
                'total_agents': 0,
                'arrived': 0,
                'moving': 0,
                'total_distance': 0.0,
                'total_emissions': 0.0,
                'modes': {}
            }
        
        from collections import Counter
        
        modes = Counter(state.get('mode', 'walk') for state in agent_states)
        arrived = sum(1 for state in agent_states if state.get('arrived', False))
        total_distance = sum(state.get('distance_km', 0.0) for state in agent_states)
        total_emissions = sum(state.get('emissions_g', 0.0) for state in agent_states)
        
        return {
            'total_agents': len(agent_states),
            'arrived': arrived,
            'moving': len(agent_states) - arrived,
            'total_distance': round(total_distance, 3),
            'total_emissions': round(total_emissions, 2),
            'modes': dict(modes)
        }


class RouteDataAdapter:
    """Convert routes to pydeck-compatible format."""
    
    @staticmethod
    def routes_to_dataframe(agent_states: List[Dict]) -> pd.DataFrame:
        """
        Convert agent routes to DataFrame for PathLayer.
        
        Args:
            agent_states: List of dicts with keys:
                - agent_id: Unique identifier
                - route: List of (lon, lat) tuples
                - mode: Transport mode
        
        Returns:
            DataFrame with columns: path, color, agent_id, mode
        """
        if not agent_states:
            return pd.DataFrame(columns=['path', 'color', 'agent_id', 'mode'])
        
        data = []
        for state in agent_states:
            route = state.get('route')
            
            # Validate route
            if not route or not isinstance(route, list) or len(route) < 2:
                continue
            
            # Convert to [[lon, lat], [lon, lat], ...] format for pydeck
            try:
                path = [
                    [float(pt[0]), float(pt[1])] 
                    for pt in route 
                    if isinstance(pt, (list, tuple)) and len(pt) == 2
                ]
            except (ValueError, TypeError, IndexError):
                continue
            
            if len(path) < 2:
                continue
            
            # Get mode and color
            mode = state.get('mode', 'walk')
            color = MODE_COLORS.get(mode, [128, 128, 128])
            
            data.append({
                'path': path,
                'color': color,
                'agent_id': state.get('agent_id', ''),
                'mode': mode,
            })
        
        return pd.DataFrame(data)


class CongestionDataAdapter:
    """Convert congestion data to pydeck-compatible format."""
    
    @staticmethod
    def congestion_to_dataframe(
        congestion_heatmap: Dict[Tuple[int, int, int], float],
        graph: Optional[object]
    ) -> pd.DataFrame:
        """
        Convert congestion heatmap to DataFrame for PathLayer.
        
        Args:
            congestion_heatmap: Dict mapping (u, v, key) -> congestion_factor
            graph: NetworkX graph with node coordinates
        
        Returns:
            DataFrame with columns: path, color, width, congestion_factor, edge_id
        """
        if not congestion_heatmap or graph is None:
            return pd.DataFrame(columns=[
                'path', 'color', 'width', 'congestion_factor', 'edge_id'
            ])
        
        data = []
        for (u, v, key), factor in congestion_heatmap.items():
            try:
                # Get node coordinates
                u_lon = float(graph.nodes[u]['x'])
                u_lat = float(graph.nodes[u]['y'])
                v_lon = float(graph.nodes[v]['x'])
                v_lat = float(graph.nodes[v]['y'])
                
                # Create path
                path = [[u_lon, u_lat], [v_lon, v_lat]]
                
                # Get color and width based on congestion
                color = get_congestion_color(factor)
                width = get_congestion_width(factor)
                
                data.append({
                    'path': path,
                    'color': color,
                    'width': width,
                    'congestion_factor': float(factor),
                    'edge_id': f"{u}_{v}_{key}",
                })
            except (KeyError, TypeError, ValueError):
                # Skip edges with missing data
                continue
        
        return pd.DataFrame(data)


class TimeSeriesStorage:
    """
    Store and retrieve simulation state at each timestep.
    
    Enables:
    - Replay functionality
    - Forward/backward scrubbing
    - Agent trail tracking
    - Metrics time series
    """
    
    def __init__(self):
        """Initialize empty storage."""
        self.timesteps: List[Dict] = []
        self.agent_history: Dict[str, List[Dict]] = {}
    
    def store_timestep(
        self,
        step: int,
        agent_states: List[Dict],
        congestion_heatmap: Optional[Dict] = None,
        metrics: Optional[Dict] = None
    ):
        """
        Store complete state for one timestep.
        
        Args:
            step: Timestep number
            agent_states: List of agent state dictionaries
            congestion_heatmap: Optional congestion data
            metrics: Optional simulation metrics
        """
        self.timesteps.append({
            'step': step,
            'agent_states': agent_states,
            'congestion_heatmap': congestion_heatmap,
            'metrics': metrics,
        })
        
        # Track individual agent history
        for state in agent_states:
            agent_id = state.get('agent_id')
            if agent_id:
                if agent_id not in self.agent_history:
                    self.agent_history[agent_id] = []
                
                self.agent_history[agent_id].append({
                    'step': step,
                    **state
                })
    
    def get_timestep(self, step: int) -> Optional[Dict]:
        """
        Retrieve state at specific timestep.
        
        Args:
            step: Timestep number
        
        Returns:
            Dictionary with keys: step, agent_states, congestion_heatmap, metrics
            or None if step is out of range
        """
        if 0 <= step < len(self.timesteps):
            return self.timesteps[step]
        return None
    
    def get_agent_trail(
        self,
        agent_id: str,
        start_step: int = 0,
        end_step: Optional[int] = None
    ) -> List[Tuple[float, float]]:
        """
        Get agent's position trail over time.
        
        Args:
            agent_id: Agent identifier
            start_step: Starting timestep (inclusive)
            end_step: Ending timestep (exclusive), None = all remaining
        
        Returns:
            List of (lon, lat) coordinates representing the agent's path
        """
        if agent_id not in self.agent_history:
            return []
        
        history = self.agent_history[agent_id]
        if end_step is None:
            end_step = len(history)
        
        trail = []
        for state in history[start_step:end_step]:
            loc = state.get('location')
            if loc and isinstance(loc, (list, tuple)) and len(loc) == 2:
                try:
                    trail.append((float(loc[0]), float(loc[1])))
                except (ValueError, TypeError):
                    continue
        
        return trail
    
    def get_agent_trail_dataframe(
        self,
        agent_id: str,
        start_step: int = 0,
        end_step: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Get agent trail as DataFrame suitable for PathLayer.
        
        Args:
            agent_id: Agent identifier
            start_step: Starting timestep
            end_step: Ending timestep
        
        Returns:
            DataFrame with columns: path, color, agent_id
        """
        trail = self.get_agent_trail(agent_id, start_step, end_step)
        
        if len(trail) < 2:
            return pd.DataFrame(columns=['path', 'color', 'agent_id'])
        
        # Convert to pydeck format
        path = [[lon, lat] for lon, lat in trail]
        
        # Get agent's mode from most recent state
        if agent_id in self.agent_history and self.agent_history[agent_id]:
            mode = self.agent_history[agent_id][-1].get('mode', 'walk')
            color = MODE_COLORS.get(mode, [128, 128, 128])
        else:
            color = [128, 128, 128]
        
        return pd.DataFrame([{
            'path': path,
            'color': color,
            'agent_id': agent_id,
        }])
    
    def get_num_timesteps(self) -> int:
        """Get total number of stored timesteps."""
        return len(self.timesteps)
    
    def get_metrics_series(self) -> pd.DataFrame:
        """
        Get time series of metrics.
        
        Returns:
            DataFrame with columns: step, arrivals, total_emissions, total_distance, etc.
        """
        data = []
        for ts in self.timesteps:
            metrics = ts.get('metrics', {})
            if metrics:
                data.append({
                    'step': ts['step'],
                    **metrics
                })
        
        if not data:
            return pd.DataFrame(columns=['step'])
        
        return pd.DataFrame(data)
    
    def get_modal_split_series(self) -> pd.DataFrame:
        """
        Get modal split over time.
        
        Returns:
            DataFrame with columns: step, walk, bike, bus, car, ev
        """
        from collections import Counter
        
        data = []
        for ts in self.timesteps:
            agent_states = ts.get('agent_states', [])
            
            # Count modes
            modes = Counter(state.get('mode', 'walk') for state in agent_states)
            
            row = {'step': ts['step']}
            for mode in ['walk', 'bike', 'bus', 'car', 'ev']:
                row[mode] = modes.get(mode, 0)
            
            data.append(row)
        
        return pd.DataFrame(data)
    
    def clear(self):
        """Clear all stored data."""
        self.timesteps.clear()
        self.agent_history.clear()
    
    def __len__(self) -> int:
        """Return number of timesteps stored."""
        return len(self.timesteps)
    
    def __repr__(self) -> str:
        """String representation."""
        return f"TimeSeriesStorage({len(self)} timesteps, {len(self.agent_history)} agents)"


# Convenience function for quick data extraction
def extract_visualization_data(
    timestep_data: Dict,
    graph: Optional[object] = None
) -> Dict[str, pd.DataFrame]:
    """
    Extract all visualization data from a timestep.
    
    Args:
        timestep_data: Dictionary from TimeSeriesStorage.get_timestep()
        graph: NetworkX graph for congestion visualization
    
    Returns:
        Dictionary with keys: 'agents', 'routes', 'congestion'
    """
    agent_states = timestep_data.get('agent_states', [])
    congestion_heatmap = timestep_data.get('congestion_heatmap', {})
    step = timestep_data.get('step', 0)
    
    return {
        'agents': AgentDataAdapter.agents_to_dataframe(agent_states, step),
        'routes': RouteDataAdapter.routes_to_dataframe(agent_states),
        'congestion': CongestionDataAdapter.congestion_to_dataframe(
            congestion_heatmap, graph
        ) if graph else pd.DataFrame(),
    }