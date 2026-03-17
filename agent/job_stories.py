"""
agent/job_stories.py

Job story parser - converts task contexts to agent constraints and parameters.
Defines WHAT the agent needs to accomplish.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
from datetime import time as datetime_time
import logging

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

logger = logging.getLogger(__name__)


# ============================================================================
# Helpers
# ============================================================================

def _coerce_time_str(value: Any) -> str:
    """Coerce a YAML-parsed time value to a HH:MM string.

    PyYAML (pre-6.0) treats unquoted sexagesimal values such as ``07:00``
    as integers (7*60 = 420).  This helper normalises both the legacy int
    form and the modern string form to a consistent ``"HH:MM"`` string, so
    callers never need to special-case the type.

    Examples
    --------
    >>> _coerce_time_str(420)
    '07:00'
    >>> _coerce_time_str('08:45')
    '08:45'
    >>> _coerce_time_str(7)       # bare integer hour
    '00:07'
    """
    if isinstance(value, int):
        h, m = divmod(value, 60)
        return f"{h:02d}:{m:02d}"
    if isinstance(value, float):
        h, m = divmod(int(round(value)), 60)
        return f"{h:02d}:{m:02d}"
    return str(value)


# The use of dataclasses simplifies the definition and management of 
# complex data structures.
# ============================================================================

@dataclass # Dataclass decorator for JobStory and related classes
class TimeWindow:
    """Represents a time constraint."""
    start: str  # HH:MM format
    end: str    # HH:MM format
    flexibility: str  # 'none', 'very_low', 'low', 'medium', 'high', 'very_high'
    preferred_arrival: Optional[str] = None  # HH:MM format
    
    def to_minutes(self) -> Tuple[int, int]:
        """Convert to minutes since midnight."""
        start_h, start_m = map(int, self.start.split(':'))
        end_h, end_m = map(int, self.end.split(':'))
        return (start_h * 60 + start_m, end_h * 60 + end_m)


@dataclass # Dataclass for multi-stage trip stages, allowing for complex trips with multiple legs and constraints.
class StageDefinition:
    """Multi-stage trip stage definition."""
    stage_id: int
    destination_type: str
    time_window: TimeWindow
    constraints: List[str] = field(default_factory=list)
    typical_distance_km: Optional[List[float]] = None

# Main dataclass for job stories, representing the parsed information from YAML files 
# and templates. Contains all the necessary information to define a task for the agent, 
# including spatial and temporal constraints, parameters, and multi-stage trip details. 
# The to_task_context method allows for easy conversion to a TaskContext object that can 
# be used for planning and execution. This structure supports a wide variety of tasks and
# can be easily extended with additional fields as needed for different types of jobs 
# (commute, delivery, leisure, etc.).
@dataclass 
class TaskContext:
    """
    Parsed task context from job story.
    
    Contains spatial, temporal, and operational constraints.
    """
    origin: Optional[Tuple[float, float]] = None
    dest: Optional[Tuple[float, float]] = None
    time_window: Optional[TimeWindow] = None
    stages: List[StageDefinition] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)

# The JobStory dataclass represents a complete job story with all the relevant information 
# parsed from YAML files or generated templates. It includes methods to convert the job story 
# into a TaskContext that can be used for planning and execution. The JobStoryParser class is 
# responsible for loading job stories from YAML files and providing access to them. 
# Convenience functions are provided for easy loading and listing of job stories. 
# This structure allows for a flexible and extensible way to define a wide variety of 
# tasks for the agent, and can be easily integrated with the rest of the system for planning 
# and execution. 
@dataclass
class JobStory:
    """
    Parsed job story containing task requirements.
    
    Represents WHAT task the agent is performing.
    """
    story_id: str
    context: str  # "When..." statement
    goal: str     # "I want..." statement
    outcome: str  # "So that..." statement
    
    job_type: str  # 'commute', 'delivery', 'leisure', etc.
    
    # Temporal constraints
    time_window: Optional[TimeWindow] = None
    
    # Spatial constraints
    destination_type: str = 'general'
    typical_distance_km: Optional[List[float]] = None  # [min, max] range
    
    # Task parameters
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    # Multi-stage support
    stages: List[StageDefinition] = field(default_factory=list)
    
    # Vehicle constraints (for freight)
    vehicle_constraints: Optional[Dict[str, Any]] = None
    
    # Delivery-specific
    delivery_params: Optional[Dict[str, Any]] = None
    
    # Plan inference context
    plan_context: List[str] = field(default_factory=list)
    
    # CSV integration
    csv_columns: Dict[str, List[str]] = field(default_factory=dict)
    
    # Desire overrides (for emergency, etc.)
    desire_overrides: Optional[Dict[str, float]] = None
    
    def to_task_context(
        self, 
        origin: Optional[Tuple[float, float]] = None,
        dest: Optional[Tuple[float, float]] = None,
        csv_data: Optional[Dict[str, Any]] = None
    ) -> TaskContext:
        """
        Convert job story to task context.
        
        Args:
            origin: Origin coordinates (lon, lat)
            dest: Destination coordinates (lon, lat)
            csv_data: Optional CSV row data to override/augment
        
        Returns:
            TaskContext with all parameters
        """
        context = TaskContext()
        
        # Spatial parameters
        context.origin = origin
        context.dest = dest
        
        # Temporal parameters
        context.time_window = self.time_window
        
        # Multi-stage
        context.stages = self.stages.copy()
        
        # Task parameters
        context.parameters = self.parameters.copy()
        
        # Extract constraints from context
        context.constraints = self._extract_constraints()
        
        # Apply CSV overrides if provided
        if csv_data:
            context = self._apply_csv_overrides(context, csv_data)
        
        return context
    
    def _extract_constraints(self) -> List[str]:
        """Extract constraints from job story."""
        constraints = []
        
        # Add from parameters
        if self.parameters.get('recurring'):
            constraints.append('recurring_trip')
        
        if self.parameters.get('vehicle_required'):
            constraints.append('vehicle_required')
        
        if self.parameters.get('luggage_present'):
            constraints.append('luggage_present')
        
        # Add from time window
        if self.time_window and self.time_window.flexibility in ['none', 'very_low']:
            constraints.append('time_critical')
        
        return constraints
    
    # Apply CSV data to override/augment task context. This allows for dynamic updates 
    # to the task context based on external data sources, which can be useful for testing 
    # or for real-time updates in a simulation. The CSV data can include overrides for 
    # origin/destination coordinates, time windows, and any additional parameters that 
    # may be relevant for the task. This function ensures that the task context can be 
    # easily modified without changing the underlying job story definition, allowing for 
    # greater flexibility in how tasks are defined and executed.
    def _apply_csv_overrides(
        self, 
        context: TaskContext, 
        csv_data: Dict[str, Any]
    ) -> TaskContext:
        """Apply CSV data to override/augment task context."""
        
        # Override origin/dest if in CSV
        if 'origin_lat' in csv_data and 'origin_lon' in csv_data:
            context.origin = (
                float(csv_data['origin_lon']),
                float(csv_data['origin_lat'])
            )
        
        if 'dest_lat' in csv_data and 'dest_lon' in csv_data:
            context.dest = (
                float(csv_data['dest_lon']),
                float(csv_data['dest_lat'])
            )
        
        # Override time window
        if 'preferred_arrival' in csv_data:
            if context.time_window:
                context.time_window.preferred_arrival = csv_data['preferred_arrival']
        
        # Add any extra parameters
        for key, value in csv_data.items():
            if key not in ['origin_lat', 'origin_lon', 'dest_lat', 'dest_lon']:
                context.parameters[key] = value
        
        return context
    
    def is_multi_stage(self) -> bool:
        """Check if this is a multi-stage job."""
        return len(self.stages) > 1
    
    def __repr__(self) -> str:
        return f"JobStory(id={self.story_id}, type={self.job_type})"

# ============================================================================
# Job Story Parser
# ============================================================================

# Main class for parsing job stories from YAML files and templates.
# Supports loading from a single YAML file or a directory of YAML files, as well as
# programmatically generated job templates. Caches loaded stories for efficient access.
class JobStoryParser: 
    """
    Parser for job context YAML files.
    """
    
    def __init__(self, stories_path: Optional[Path] = None):
        """
        Initialize parser.
        
        Args:
            stories_path: Path to job_contexts.yaml OR directory containing YAML files
        """
        if not YAML_AVAILABLE:
            raise ImportError("PyYAML required: pip install pyyaml")
        
        if stories_path is None:
            module_dir = Path(__file__).parent
            stories_path = module_dir / "job_contexts"  # ✅ Changed to directory
        
        self.stories_path = Path(stories_path)
        self._stories_cache: Optional[Dict[str, Any]] = None
        
        logger.info(f"JobStoryParser initialized: {self.stories_path}")
    
    def load_from_yaml(self, story_id: str) -> JobStory:
        """
        Load job story from YAML file.
        
        Args:
            story_id: Story identifier (e.g., 'morning_commute')
        
        Returns:
            Parsed JobStory object
        """
        if self._stories_cache is None:
            self._load_stories()
        
        if story_id not in self._stories_cache:
            available = list(self._stories_cache.keys())
            raise KeyError(
                f"Job story '{story_id}' not found. "
                f"Available: {available}"
            )
        
        story_data = self._stories_cache[story_id]
        
        # Parse time window
        # This helper converts both the legacy int form and the modern string form to a consistent "HH:MM" string.
        # Applied at both the job-level and stage-level TimeWindow construction sites, including preferred_arrival.
        time_window = None
        if 'time_window' in story_data:
            tw_data = story_data['time_window']
            time_window = TimeWindow(
                start=_coerce_time_str(tw_data.get('start', '00:00')),
                end=_coerce_time_str(tw_data.get('end', '23:59')),
                flexibility=tw_data.get('flexibility', 'medium'),
                preferred_arrival=(
                    _coerce_time_str(tw_data['preferred_arrival'])
                    if tw_data.get('preferred_arrival') is not None else None
                )
            )
        
        # Parse stages (for multi-stage trips)
        stages = []
        if 'stages' in story_data:
            for stage_data in story_data['stages']:
                # ✅ FIX: Make destination_type optional with default
                destination_type = stage_data.get('destination_type', 'general')
                
                # ✅ FIX: Make time_window optional
                if 'time_window' in stage_data:
                    tw_data = stage_data['time_window']
                    stage_tw = TimeWindow(
                        start=_coerce_time_str(tw_data.get('start', '00:00')),
                        end=_coerce_time_str(tw_data.get('end', '23:59')),
                        flexibility=tw_data.get('flexibility', 'medium'),
                        preferred_arrival=(
                            _coerce_time_str(tw_data['preferred_arrival'])
                            if tw_data.get('preferred_arrival') is not None else None
                        )
                    )
                else:
                    # Default time window if not specified
                    stage_tw = TimeWindow(
                        start='00:00',
                        end='23:59',
                        flexibility='medium'
                    )
                
                stage = StageDefinition(
                    stage_id=stage_data['stage_id'],
                    destination_type=destination_type,
                    time_window=stage_tw,
                    constraints=stage_data.get('constraints', []),
                    typical_distance_km=stage_data.get('typical_distance_km')
                )
                stages.append(stage)
        
        # Create JobStory object
        story = JobStory(
            story_id=story_id,
            context=story_data.get('context', ''),
            goal=story_data.get('goal', ''),
            outcome=story_data.get('outcome', ''),
            job_type=story_data.get('job_type', 'general'),
            time_window=time_window,
            destination_type=story_data.get('destination_type', 'general'),
            typical_distance_km=story_data.get('typical_distance_km'),
            parameters=story_data.get('parameters', {}),
            stages=stages,
            vehicle_constraints=story_data.get('vehicle_constraints'),
            delivery_params=story_data.get('delivery_params'),
            plan_context=story_data.get('plan_context', []),
            csv_columns=story_data.get('csv_columns', {}),
            desire_overrides=story_data.get('desire_overrides')
        )
        
        return story
    
    def _load_stories(self):
        """Load all stories from YAML + generated templates."""
        self._stories_cache = {}
        
        # Load YAML files (Strategy 1)
        if self.stories_path.is_file():
            with open(self.stories_path, 'r') as f:
                self._stories_cache = yaml.safe_load(f)
            logger.info(f"Loaded {len(self._stories_cache)} stories from file")
        
        elif self.stories_path.is_dir():
            yaml_files = sorted(self.stories_path.glob('*.yaml'))
            
            for yaml_file in yaml_files:
                with open(yaml_file, 'r') as f:
                    stories = yaml.safe_load(f)
                    if stories:
                        self._stories_cache.update(stories)
            
            logger.info(f"Loaded {len(self._stories_cache)} stories from {len(yaml_files)} YAML files")
        
        # Load programmatically generated jobs (Strategy 3)
        try:
            from agent.job_templates import generate_all_job_templates
            generated = generate_all_job_templates()
            
            # Add generated jobs (with prefix to distinguish)
            for job_id, job_def in generated.items():
                if job_id not in self._stories_cache:  # Don't override manual jobs
                    self._stories_cache[job_id] = job_def
            
            logger.info(f"Added {len(generated)} generated job templates")
        except ImportError:
            logger.debug("job_templates.py not found, skipping generated jobs")
    
    def list_available_stories(self) -> List[str]:
        """Get list of all available job story IDs."""
        if self._stories_cache is None:
            self._load_stories()
        return list(self._stories_cache.keys())
    
    def get_story_summary(self, story_id: str) -> str:
        """Get one-line summary of a job story."""
        story = self.load_from_yaml(story_id)
        return f"{story_id} ({story.job_type}): {story.context[:50]}..."


# ============================================================================
# Convenience Functions
# ============================================================================

def load_job_story(story_id: str, stories_path: Optional[Path] = None) -> JobStory:
    """
    Quick function to load a job story.
    
    Args:
        story_id: Story identifier
        stories_path: Optional path to job_contexts.yaml
    
    Returns:
        JobStory object
    """
    parser = JobStoryParser(stories_path)
    return parser.load_from_yaml(story_id)


def list_job_stories(stories_path: Optional[Path] = None) -> List[str]:
    """
    List all available job stories.
    
    Args:
        stories_path: Optional path to job_contexts.yaml
    
    Returns:
        List of story IDs
    """
    parser = JobStoryParser(stories_path)
    return parser.list_available_stories()