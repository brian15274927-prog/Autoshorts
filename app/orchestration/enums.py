"""
Orchestration mode enumerations.

Defines the supported video generation modes for the platform.
"""
from enum import Enum


class OrchestrationMode(str, Enum):
    """
    Video generation modes supported by the orchestration system.

    Each mode represents a different input-to-video workflow:
    - TEXT: Generate video from text script (TTS + visuals)
    - MUSIC: Generate music video/clip from audio track
    - AUDIO: Generate video from existing audio/voiceover
    - LONG: Convert long video to multiple short clips
    """
    TEXT = "text"
    MUSIC = "music"
    AUDIO = "audio"
    LONG = "long"

    @classmethod
    def from_string(cls, value: str) -> "OrchestrationMode":
        """Get mode from string value."""
        value_lower = value.lower()
        for mode in cls:
            if mode.value == value_lower:
                return mode
        raise ValueError(f"Unknown orchestration mode: {value}")

    @property
    def display_name(self) -> str:
        """Human-readable display name."""
        names = {
            self.TEXT: "Text to Video",
            self.MUSIC: "Music to Clip",
            self.AUDIO: "Audio to Video",
            self.LONG: "Long to Shorts",
        }
        return names.get(self, self.value)

    @property
    def description(self) -> str:
        """Mode description for documentation."""
        descriptions = {
            self.TEXT: "Generate video with AI voiceover from text script",
            self.MUSIC: "Generate music video/clip synchronized to audio track",
            self.AUDIO: "Generate video from existing audio/voiceover file",
            self.LONG: "Convert long video to multiple short vertical clips",
        }
        return descriptions.get(self, "")
