"""
Base orchestrator abstract class.

Defines the interface that all mode-specific orchestrators must implement.
The orchestrator is responsible for transforming mode-specific input
into a standardized render job that can be processed by the rendering pipeline.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict
from dataclasses import dataclass

from .enums import OrchestrationMode


@dataclass
class OrchestrationResult:
    """
    Result of orchestration process.

    Contains all data needed to submit a render job,
    plus metadata about the orchestration.
    """
    mode: OrchestrationMode
    render_job: Dict[str, Any]
    metadata: Dict[str, Any]

    # Computed properties from orchestration
    estimated_duration_seconds: float = 0.0
    estimated_cost_credits: int = 1

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "mode": self.mode.value,
            "render_job": self.render_job,
            "metadata": self.metadata,
            "estimated_duration_seconds": self.estimated_duration_seconds,
            "estimated_cost_credits": self.estimated_cost_credits,
        }


class BaseOrchestrator(ABC):
    """
    Abstract base class for video generation orchestrators.

    Each orchestrator handles a specific mode of video generation:
    - TextModeOrchestrator: text -> TTS -> video
    - MusicModeOrchestrator: music track -> video
    - AudioModeOrchestrator: audio file -> video

    The orchestrator's responsibility is to:
    1. Validate mode-specific input
    2. Prepare all required assets (audio, backgrounds, etc.)
    3. Build a render job configuration compatible with the rendering pipeline
    4. Return structured result for job submission

    Orchestrators must NOT:
    - Know about HTTP/FastAPI specifics
    - Interact directly with Celery
    - Handle authentication or credits
    """

    def __init__(self):
        """Initialize orchestrator."""
        self._mode: OrchestrationMode = self._get_mode()

    @property
    def mode(self) -> OrchestrationMode:
        """Get the orchestration mode this orchestrator handles."""
        return self._mode

    @abstractmethod
    def _get_mode(self) -> OrchestrationMode:
        """
        Return the mode this orchestrator handles.
        Must be implemented by subclasses.
        """
        pass

    @abstractmethod
    def validate_request(self, request: Dict[str, Any]) -> None:
        """
        Validate the incoming request data.

        Args:
            request: Raw request data from the API

        Raises:
            ValueError: If request is invalid
        """
        pass

    @abstractmethod
    def build_render_job(self, request: Dict[str, Any]) -> OrchestrationResult:
        """
        Transform mode-specific request into a render job.

        This is the main entry point for orchestration. It should:
        1. Validate the request
        2. Prepare/fetch required assets
        3. Build script, scenes, timestamps
        4. Return a complete OrchestrationResult

        Args:
            request: Validated request data

        Returns:
            OrchestrationResult containing the render job and metadata

        Raises:
            ValueError: If request cannot be processed
            RuntimeError: If asset preparation fails
        """
        pass

    def get_mode_info(self) -> Dict[str, Any]:
        """
        Get information about this orchestration mode.

        Returns:
            Dictionary with mode metadata
        """
        return {
            "mode": self.mode.value,
            "display_name": self.mode.display_name,
            "description": self.mode.description,
        }
