# visualiser/animation_controller.py
"""
Animation and playback control for Phase 2.3

Manages:
- Playback state (play/pause/seek)
- Speed control
- Loop control
- Time synchronization
"""

from typing import Optional
import time


class AnimationController:
    """
    Controls animation playback state.
    
    State machine:
    - STOPPED: Not playing, at start
    - PLAYING: Actively playing
    - PAUSED: Paused at current frame
    - FINISHED: Reached end of simulation
    """
    
    def __init__(self, total_steps: int, fps: int = 10):
        """
        Initialize animation controller.
        
        Args:
            total_steps: Total number of simulation timesteps
            fps: Target frames per second for playback
        """
        self.total_steps = total_steps
        self.fps = fps
        self.frame_duration = 1.0 / fps if fps > 0 else 0.1
        
        # State
        self.current_step = 0
        self.is_playing = False
        self.speed_multiplier = 1.0
        self.loop = False
        
        # Internal timing
        self._last_update_time = 0.0
    
    def play(self):
        """Start playback."""
        if self.current_step >= self.total_steps - 1:
            self.current_step = 0  # Restart from beginning
        self.is_playing = True
        self._last_update_time = time.time()
    
    def pause(self):
        """Pause playback."""
        self.is_playing = False
    
    def stop(self):
        """Stop and reset to beginning."""
        self.is_playing = False
        self.current_step = 0
    
    def toggle_play_pause(self):
        """Toggle between play and pause."""
        if self.is_playing:
            self.pause()
        else:
            self.play()
    
    def step_forward(self):
        """Advance one step."""
        if self.current_step < self.total_steps - 1:
            self.current_step += 1
    
    def step_backward(self):
        """Go back one step."""
        if self.current_step > 0:
            self.current_step -= 1
    
    def seek(self, step: int):
        """Jump to specific step."""
        self.current_step = max(0, min(step, self.total_steps - 1))
    
    def seek_normalized(self, position: float):
        """
        Seek to normalized position (0.0 to 1.0).
        
        Args:
            position: Position as fraction of total length (0.0 = start, 1.0 = end)
        """
        step = int(position * (self.total_steps - 1))
        self.seek(step)
    
    def set_speed(self, multiplier: float):
        """
        Set playback speed multiplier.
        
        Args:
            multiplier: Speed multiplier (0.5 = half speed, 2.0 = double speed)
        """
        self.speed_multiplier = max(0.1, min(10.0, multiplier))
    
    def set_loop(self, enabled: bool):
        """Enable/disable loop playback."""
        self.loop = enabled
    
    def update(self) -> bool:
        """
        Update animation state (call every frame).
        
        Returns:
            True if step changed, False otherwise
        """
        if not self.is_playing:
            return False
        
        current_time = time.time()
        elapsed = current_time - self._last_update_time
        
        # Check if enough time has passed for next frame
        adjusted_duration = self.frame_duration / self.speed_multiplier
        if elapsed < adjusted_duration:
            return False
        
        self._last_update_time = current_time
        
        # Advance step
        if self.current_step < self.total_steps - 1:
            self.current_step += 1
            return True
        else:
            # Reached end
            if self.loop:
                self.current_step = 0
                return True
            else:
                self.pause()
                return False
    
    def get_progress(self) -> float:
        """Get playback progress as fraction (0.0 to 1.0)."""
        if self.total_steps <= 1:
            return 1.0
        return self.current_step / (self.total_steps - 1)
    
    def get_time_remaining(self) -> float:
        """Get estimated seconds remaining at current speed."""
        steps_left = self.total_steps - self.current_step - 1
        frames_left = steps_left / self.speed_multiplier
        return frames_left * self.frame_duration
    
    def get_state_dict(self) -> dict:
        """Get current state as dictionary."""
        return {
            'current_step': self.current_step,
            'total_steps': self.total_steps,
            'is_playing': self.is_playing,
            'speed_multiplier': self.speed_multiplier,
            'loop': self.loop,
            'progress': self.get_progress(),
            'time_remaining': self.get_time_remaining(),
        }


class LayerManager:
    """
    Manages visibility of different map layers.
    
    Layers:
    - agents: Agent markers
    - routes: Agent routes
    - congestion: Traffic heatmap
    - trails: Agent movement trails
    - labels: Text labels
    """
    
    def __init__(self):
        self.layers = {
            'agents': True,
            'routes': False,
            'congestion': False,
            'trails': False,
            'labels': True,
        }
    
    def toggle(self, layer_name: str):
        """Toggle layer visibility."""
        if layer_name in self.layers:
            self.layers[layer_name] = not self.layers[layer_name]
    
    def set_visible(self, layer_name: str, visible: bool):
        """Set layer visibility explicitly."""
        if layer_name in self.layers:
            self.layers[layer_name] = visible
    
    def is_visible(self, layer_name: str) -> bool:
        """Check if layer is visible."""
        return self.layers.get(layer_name, False)
    
    def get_visible_layers(self) -> list:
        """Get list of visible layer names."""
        return [name for name, visible in self.layers.items() if visible]
    
    def show_all(self):
        """Make all layers visible."""
        for layer_name in self.layers:
            self.layers[layer_name] = True
    
    def hide_all(self):
        """Hide all layers."""
        for layer_name in self.layers:
            self.layers[layer_name] = False