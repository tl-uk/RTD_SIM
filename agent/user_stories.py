"""
agent/user_stories.py

This module implements the UserStory class and UserStoryParser for converting persona 
definitions into BDI parameters. The parser supports direct mapping from YAML, inference 
from narrative text, and a hybrid approach. User stories represent the WHO of the agent, 
including personality, beliefs, constraints, and mode preferences. This allows us to 
create diverse agent personas that can be used in the simulation, and to test how 
different types of agents interact with various job stories and system dynamics. 

The parser also includes convenience functions for loading stories and listing available 
story IDs, making it easy to integrate into the agent generation process. 

This is a critical component for creating a realistic and coherent population of agents 
with diverse motivations and behaviors, which is essential for testing the impacts of 
policies and system changes in the real-time digital twin simulation.

"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from pathlib import Path
import logging
import re

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    logging.warning("PyYAML not available - install with: pip install pyyaml")

logger = logging.getLogger(__name__)

# ===============================================================================
# Data classes for User Stories
# ===============================================================================

# Belief class to represent agent beliefs with strength and updateability, allowing for
# dynamic belief updates based on experiences and interactions in the simulation.
@dataclass
class Belief:
    """Represents an agent belief."""
    text: str
    strength: float = 0.5  # 0-1
    updateable: bool = True

# UserStory class to represent the parsed user story, including persona type, desires, 
# beliefs, constraints, mode preferences, and planning hints. This structured 
# representation allows for easy integration into the agent generation process and supports 
# dynamic behavior based on the agent's narrative and characteristics.
@dataclass
class UserStory:
    """
    Parsed user story containing persona characteristics.
    
    Represents WHO the agent is (personality, beliefs, constraints).
    """
    story_id: str
    narrative: str
    persona_type: str  # 'passenger' or 'freight'
    
    # BDI desires (0-1 scale)
    desires: Dict[str, float] = field(default_factory=dict)
    desire_variance: float = 0.10
    
    # Beliefs
    beliefs: List[Belief] = field(default_factory=list)
    
    # Hard constraints
    constraints: List[str] = field(default_factory=list)
    
    # Mode preferences
    mode_preferences: Dict[str, float] = field(default_factory=dict)
    
    # Planning hints
    plan_hints: List[str] = field(default_factory=list)
    
    # Social network parameters
    social_profile: Dict[str, Any] = field(default_factory=dict)
    
    # Freight-specific parameters
    freight_params: Optional[Dict[str, Any]] = None
    
    def to_bdi_desires(self) -> Dict[str, float]:
        """
        Extract BDI desire parameters.
        
        Returns:
            Dictionary of desire weights (0-1 scale)
        """
        return self.desires.copy()
    
    def get_mode_preference(self, mode: str) -> float:
        """Get preference for a specific mode (0-1, higher = more preferred)."""
        return self.mode_preferences.get(mode, 0.5)
    
    def __repr__(self) -> str:
        return f"UserStory(id={self.story_id}, type={self.persona_type})"

# ===============================================================================
# User Story Parser
# ===============================================================================

# UserStoryParser class to load and parse user stories from a YAML file, supporting 
# direct mapping, inference from narrative text, and a hybrid approach. This allows for
# flexible story definitions and the ability to create rich agent personas based on 
# narrative descriptions, which can be particularly useful for testing how different 
# types of agents interact with the system and respond to policies in the simulation.
class UserStoryParser:
    """
    Parser for user story YAML files.
    
    Supports:
    - Direct mapping (explicit values in YAML)
    - Inference (derive from narrative text)
    - Hybrid (combine explicit + inferred)
    """
    
    def __init__(self, stories_path: Optional[Path] = None):
        """
        Initialize parser.
        
        Args:
            stories_path: Path to personas.yaml file
                         (default: agent/personas.yaml)
        """
        if not YAML_AVAILABLE:
            raise ImportError("PyYAML required: pip install pyyaml")
        
        if stories_path is None:
            # Try to find personas.yaml relative to this file
            module_dir = Path(__file__).parent
            stories_path = module_dir / "personas" / "personas.yaml"
        
        self.stories_path = Path(stories_path)
        self._stories_cache: Optional[Dict[str, Any]] = None
        
        logger.info(f"UserStoryParser initialized: {self.stories_path}")
    
    def load_from_yaml(self, story_id: str) -> UserStory:
        """
        Load user story from YAML file.
        
        Args:
            story_id: Story identifier (e.g., 'eco_warrior')
        
        Returns:
            Parsed UserStory object
        
        Raises:
            FileNotFoundError: If personas.yaml not found
            KeyError: If story_id not in file
        """
        if self._stories_cache is None:
            self._load_stories()
        
        if story_id not in self._stories_cache:
            available = list(self._stories_cache.keys())
            raise KeyError(
                f"Story '{story_id}' not found. "
                f"Available: {available}"
            )
        
        story_data = self._stories_cache[story_id]
        
        # Parse beliefs
        beliefs = []
        for b in story_data.get('beliefs', []):
            if isinstance(b, dict):
                beliefs.append(Belief(
                    text=b['text'],
                    strength=b.get('strength', 0.5),
                    updateable=b.get('updateable', True)
                ))
            elif isinstance(b, str):
                # Simple string belief, infer defaults
                beliefs.append(Belief(text=b, strength=0.7, updateable=True))
        
        # Create UserStory object
        story = UserStory(
            story_id=story_id,
            narrative=story_data.get('narrative', ''),
            persona_type=story_data.get('persona_type', 'passenger'),
            desires=story_data.get('desires', {}),
            desire_variance=story_data.get('desire_variance', 0.10),
            beliefs=beliefs,
            constraints=story_data.get('constraints', []),
            mode_preferences=story_data.get('mode_preferences', {}),
            plan_hints=story_data.get('plan_hints', []),
            social_profile=story_data.get('social_profile', {}),
            freight_params=story_data.get('freight_params'),
        )
        
        # If desires missing, try to infer from narrative
        if not story.desires:
            story.desires = self._infer_desires(story.narrative, story.persona_type)
        
        # If mode preferences missing, infer from desires
        if not story.mode_preferences:
            story.mode_preferences = self._infer_mode_preferences(story.desires)
        
        return story
    
    # Class-level dict so every UserStoryParser instance sharing the same
    # resolved path reads the YAML file only once per process lifetime.
    # Call UserStoryParser._class_cache.clear() if the YAML is hot-reloaded
    # at runtime (e.g. after Phase 9 story ingestion publishes new personas).
    _class_cache: dict = {}

    def _load_stories(self) -> None:
        """Load all stories from YAML file, using a class-level cache.

        Also merges operator_personas.yaml (sibling file in the same
        directory) so that fleet_manager_*, port_terminal_operator,
        rail_freight_operator, and air_freight_operator are available
        without callers needing to pass an explicit path.
        """
        resolved = self.stories_path.resolve()

        if resolved in UserStoryParser._class_cache:
            self._stories_cache = UserStoryParser._class_cache[resolved]
            logger.debug(
                "UserStoryParser: cache hit — %d stories (%s)",
                len(self._stories_cache), self.stories_path.name,
            )
            return

        if not self.stories_path.exists():
            raise FileNotFoundError(
                f"personas.yaml not found at: {self.stories_path}\n"
                f"Expected location: agent/personas/personas.yaml\n"
                f"Please ensure the file exists at the correct path."
            )

        with open(self.stories_path, 'r') as f:
            self._stories_cache = yaml.safe_load(f) or {}

        # Merge operator_personas.yaml from the same directory, if present.
        # Operator personas (fleet_manager_*, port_terminal_operator, etc.)
        # are defined there and must be reachable via the same parser.
        operator_path = self.stories_path.parent / "operator_personas.yaml"
        if operator_path.exists():
            with open(operator_path, 'r') as f:
                operator_data = yaml.safe_load(f) or {}
            overlap = set(self._stories_cache) & set(operator_data)
            if overlap:
                logger.warning(
                    "UserStoryParser: operator_personas.yaml has key(s) "
                    "that clash with personas.yaml: %s — operator values used",
                    overlap,
                )
            self._stories_cache.update(operator_data)
            logger.info(
                "UserStoryParser: merged %d operator personas from %s",
                len(operator_data), operator_path.name,
            )
        else:
            logger.debug(
                "UserStoryParser: operator_personas.yaml not found at %s "
                "(operator personas unavailable)",
                operator_path,
            )

        UserStoryParser._class_cache[resolved] = self._stories_cache
        logger.info(
            "UserStoryParser: loaded %d stories total (%s)",
            len(self._stories_cache), self.stories_path.name,
        )
   
    # Infer desires from narrative text using keyword matching and context clues. 
    # This allows for creating user stories with minimal explicit parameters, relying on 
    # the narrative to convey the agent's motivations and preferences, which can be 
    # particularly useful for testing how well the agent generation process can capture 
    # the essence of a persona  based on its story, and how those inferred desires 
    # influence behavior in the simulation.
    def _infer_desires(self, narrative: str, persona_type: str) -> Dict[str, float]:
        """
        Infer BDI desires from narrative text.
        
        Uses keyword matching and context clues.
        """
        desires = {
            'eco': 0.5,
            'time': 0.5,
            'cost': 0.5,
            'comfort': 0.5,
            'safety': 0.5,
            'reliability': 0.5,
            'flexibility': 0.5,
        }
        
        if not narrative:
            return desires
        
        text_lower = narrative.lower()
        
        # Environmental keywords
        eco_keywords = ['carbon', 'emission', 'environment', 'sustainable', 
                       'green', 'eco', 'climate', 'decarboni']
        if any(kw in text_lower for kw in eco_keywords):
            desires['eco'] = 0.8
        
        # Time keywords
        time_keywords = ['time', 'quick', 'fast', 'urgent', 'schedule', 'deadline']
        if any(kw in text_lower for kw in time_keywords):
            desires['time'] = 0.7
        
        # Cost keywords
        cost_keywords = ['cost', 'budget', 'afford', 'cheap', 'expensive', 'money']
        if any(kw in text_lower for kw in cost_keywords):
            desires['cost'] = 0.7
        
        # Comfort keywords
        comfort_keywords = ['comfort', 'convenient', 'easy', 'stress-free']
        if any(kw in text_lower for kw in comfort_keywords):
            desires['comfort'] = 0.7
        
        # Safety keywords
        safety_keywords = ['safe', 'secure', 'risk', 'danger', 'children']
        if any(kw in text_lower for kw in safety_keywords):
            desires['safety'] = 0.8
        
        # Reliability keywords
        reliability_keywords = ['reliable', 'dependable', 'consistent', 'on time']
        if any(kw in text_lower for kw in reliability_keywords):
            desires['reliability'] = 0.8
        
        # Freight-specific adjustments
        if persona_type == 'freight':
            desires['reliability'] = max(desires['reliability'], 0.8)
            desires['cost'] = max(desires['cost'], 0.7)
            if 'compliance' in text_lower or 'regulation' in text_lower:
                desires['compliance'] = 0.9
        
        return desires
    
    # Infer mode preferences from desires. This creates a mapping from the agent's 
    # underlying motivations (desires) to specific transportation mode preferences, 
    # which can then be used to influence the agent's mode choice behavior in the 
    # simulation. This allows us to test how well the inferred desires translate into 
    # realistic mode preferences, and how those preferences affect the agent's 
    # interactions with the system and response to policies.
    def _infer_mode_preferences(self, desires: Dict[str, float]) -> Dict[str, float]:
        """
        Infer mode preferences from desires.
        
        High eco desire → prefer active/public transport
        High time desire → prefer car/taxi
        High cost desire → prefer walk/bike
        """
        prefs = {
            'walk': 0.5,
            'bike': 0.5,
            'ebike': 0.5,
            'bus': 0.5,
            'train': 0.5,
            'car_petrol': 0.5,
            'car_diesel': 0.5,
            'ev': 0.5,
            'taxi': 0.5,
        }
        
        eco = desires.get('eco', 0.5)
        time = desires.get('time', 0.5)
        cost = desires.get('cost', 0.5)
        
        # High eco → prefer active + public transport
        if eco > 0.7:
            prefs['walk'] = 0.8
            prefs['bike'] = 0.9
            prefs['bus'] = 0.7
            prefs['train'] = 0.7
            prefs['car_petrol'] = 0.2
            prefs['car_diesel'] = 0.1
        
        # High time → prefer fast modes
        if time > 0.7:
            prefs['car_petrol'] = 0.7
            prefs['ev'] = 0.8
            prefs['taxi'] = 0.9
            prefs['walk'] = 0.3
        
        # High cost sensitivity → prefer free/cheap modes
        if cost > 0.7:
            prefs['walk'] = 0.9
            prefs['bike'] = 0.8
            prefs['bus'] = 0.6
            prefs['car_petrol'] = 0.2
            prefs['taxi'] = 0.1
        
        return prefs
    
    def list_available_stories(self) -> List[str]:
        """Get list of all available story IDs."""
        if self._stories_cache is None:
            self._load_stories()
        return list(self._stories_cache.keys())
    
    def get_story_summary(self, story_id: str) -> str:
        """Get one-line summary of a story."""
        story = self.load_from_yaml(story_id)
        narrative_preview = story.narrative[:60] + "..." if len(story.narrative) > 60 else story.narrative
        return f"{story_id} ({story.persona_type}): {narrative_preview}"


# ============================================================================
# Convenience Functions
# ============================================================================

def load_user_story(story_id: str, stories_path: Optional[Path] = None) -> UserStory:
    """
    Quick function to load a user story.
    
    Args:
        story_id: Story identifier
        stories_path: Optional path to personas.yaml
    
    Returns:
        UserStory object
    """
    parser = UserStoryParser(stories_path)
    return parser.load_from_yaml(story_id)


def list_user_stories(stories_path: Optional[Path] = None) -> List[str]:
    """
    List all available user stories.
    
    Args:
        stories_path: Optional path to personas.yaml
    
    Returns:
        List of story IDs
    """
    parser = UserStoryParser(stories_path)
    return parser.list_available_stories()