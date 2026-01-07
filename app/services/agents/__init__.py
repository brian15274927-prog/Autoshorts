"""
Multi-Agent Orchestration System for Faceless Video Generation.

Architecture:
- Agent 1: Master Storyteller (Scriptwriter) - Generates 150-word narrative
- Agent 1.5: Story Analyzer - Creates Visual Bible for consistency
- Agent 2: Visual Director (Prompt Engineer) - Slices into 12 segments with consistent visuals
- Agent 3: Technical Director (Orchestrator) - Manages flow, validates, handles errors
"""

from .storyteller import MasterStoryteller, ScriptStyle
from .story_analyzer import StoryAnalyzer, VisualBible
from .visual_director import VisualDirector
from .orchestrator import TechnicalDirector

__all__ = [
    "MasterStoryteller",
    "StoryAnalyzer",
    "VisualBible",
    "VisualDirector",
    "TechnicalDirector",
    "ScriptStyle",
]
