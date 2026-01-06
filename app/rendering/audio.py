"""
Audio Mixer for Video Rendering Engine.
Handles voice + BGM mixing with proper volume normalization.
"""
import math
import logging
from pathlib import Path
from typing import Optional, Union

from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    concatenate_audioclips,
)
from moviepy.audio.AudioClip import AudioClip

logger = logging.getLogger(__name__)


def db_to_amplitude(db: float) -> float:
    """
    Convert decibels to amplitude multiplier.
    -20 dB = 0.1 amplitude
    -6 dB = 0.5 amplitude
    0 dB = 1.0 amplitude
    """
    return math.pow(10, db / 20.0)


class AudioMixer:
    """
    Production audio mixer for combining voice narration with background music.

    Features:
    - Precise dB-based volume control
    - BGM looping to match video duration
    - Fade in/out for smooth transitions
    - Silence padding for voice gaps
    """

    def __init__(
        self,
        bgm_volume_db: float = -20.0,
        voice_volume_db: float = 0.0,
        default_sample_rate: int = 44100,
    ):
        self.bgm_amplitude = db_to_amplitude(bgm_volume_db)
        self.voice_amplitude = db_to_amplitude(voice_volume_db)
        self.sample_rate = default_sample_rate

        logger.info(
            f"AudioMixer initialized: BGM={bgm_volume_db}dB ({self.bgm_amplitude:.3f}), "
            f"Voice={voice_volume_db}dB ({self.voice_amplitude:.3f})"
        )

    def load_audio_file(self, path: Union[str, Path]) -> AudioFileClip:
        """
        Load audio file with validation.
        Supports WAV, MP3, M4A, OGG, FLAC.
        """
        path = Path(path)

        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {path}")

        supported_extensions = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac"}
        if path.suffix.lower() not in supported_extensions:
            raise ValueError(f"Unsupported audio format: {path.suffix}")

        clip = AudioFileClip(str(path))
        logger.debug(f"Loaded audio: {path.name}, duration={clip.duration:.2f}s, fps={clip.fps}")

        return clip

    def apply_volume(self, clip: AudioFileClip, amplitude: float) -> AudioFileClip:
        """Apply volume multiplier to audio clip."""
        if amplitude == 1.0:
            return clip
        return clip.volumex(amplitude)

    def loop_to_duration(
        self,
        clip: AudioFileClip,
        target_duration: float,
    ) -> AudioFileClip:
        """
        Loop audio clip to match target duration.
        If clip is longer, it gets trimmed.
        If clip is shorter, it loops with crossfade.
        """
        if clip.duration >= target_duration:
            return clip.subclip(0, target_duration)

        loops_needed = math.ceil(target_duration / clip.duration)

        clips_to_concat = []
        remaining_duration = target_duration

        for i in range(loops_needed):
            if remaining_duration <= 0:
                break

            if remaining_duration >= clip.duration:
                clips_to_concat.append(clip)
                remaining_duration -= clip.duration
            else:
                clips_to_concat.append(clip.subclip(0, remaining_duration))
                remaining_duration = 0

        if len(clips_to_concat) == 1:
            return clips_to_concat[0]

        looped = concatenate_audioclips(clips_to_concat)

        final_duration = min(looped.duration, target_duration)
        return looped.subclip(0, final_duration)

    def apply_fades(
        self,
        clip: AudioFileClip,
        fade_in_duration: float = 0.0,
        fade_out_duration: float = 0.0,
    ) -> AudioFileClip:
        """Apply fade in and fade out effects."""
        result = clip

        if fade_in_duration > 0 and fade_in_duration < clip.duration:
            result = result.audio_fadein(fade_in_duration)

        if fade_out_duration > 0 and fade_out_duration < clip.duration:
            result = result.audio_fadeout(fade_out_duration)

        return result

    def create_silence(self, duration: float, fps: int = 44100) -> AudioClip:
        """Create silent audio clip of specified duration."""
        def make_silence(t):
            import numpy as np
            if isinstance(t, (int, float)):
                return 0
            return np.zeros((len(t), 2))

        silence = AudioClip(make_silence, duration=duration, fps=fps)
        silence = silence.set_fps(fps)
        return silence

    def pad_audio_to_duration(
        self,
        clip: AudioFileClip,
        target_duration: float,
    ) -> AudioClip:
        """
        Pad audio with silence to match target duration.
        If audio is longer, trim it.
        """
        if clip.duration >= target_duration:
            return clip.subclip(0, target_duration)

        silence_duration = target_duration - clip.duration
        silence = self.create_silence(silence_duration, fps=clip.fps or self.sample_rate)

        padded = concatenate_audioclips([clip, silence])
        return padded

    def mix_audio(
        self,
        voice_path: Union[str, Path],
        bgm_path: Optional[Union[str, Path]],
        total_duration: float,
        bgm_fade_in: float = 1.0,
        bgm_fade_out: float = 2.0,
    ) -> CompositeAudioClip:
        """
        Mix voice narration with background music.

        Args:
            voice_path: Path to voice/narration audio file
            bgm_path: Optional path to background music
            total_duration: Target duration in seconds
            bgm_fade_in: BGM fade in duration (seconds)
            bgm_fade_out: BGM fade out duration (seconds)

        Returns:
            CompositeAudioClip with mixed audio
        """
        logger.info(f"Mixing audio: voice={voice_path}, bgm={bgm_path}, duration={total_duration}s")

        voice_clip = self.load_audio_file(voice_path)
        voice_clip = self.apply_volume(voice_clip, self.voice_amplitude)
        voice_clip = self.pad_audio_to_duration(voice_clip, total_duration)

        if bgm_path is None:
            logger.info("No BGM provided, returning voice only")
            return voice_clip

        bgm_clip = self.load_audio_file(bgm_path)
        bgm_clip = self.apply_volume(bgm_clip, self.bgm_amplitude)
        bgm_clip = self.loop_to_duration(bgm_clip, total_duration)
        bgm_clip = self.apply_fades(bgm_clip, bgm_fade_in, bgm_fade_out)

        mixed = CompositeAudioClip([voice_clip, bgm_clip])
        mixed = mixed.set_duration(total_duration)

        logger.info(f"Audio mixed successfully, final duration={mixed.duration:.2f}s")

        return mixed

    def extract_segment(
        self,
        audio_clip: AudioFileClip,
        start_time: float,
        end_time: float,
    ) -> AudioFileClip:
        """Extract audio segment between start and end times."""
        if start_time < 0:
            start_time = 0
        if end_time > audio_clip.duration:
            end_time = audio_clip.duration
        if start_time >= end_time:
            raise ValueError(f"Invalid segment: start={start_time}, end={end_time}")

        return audio_clip.subclip(start_time, end_time)

    def normalize_audio(
        self,
        clip: AudioFileClip,
        target_db: float = -3.0,
    ) -> AudioFileClip:
        """
        Normalize audio to target dB level.
        Useful for ensuring consistent volume levels.
        """
        import numpy as np

        audio_array = clip.to_soundarray()

        max_amplitude = np.max(np.abs(audio_array))
        if max_amplitude == 0:
            return clip

        current_db = 20 * np.log10(max_amplitude)

        adjustment_db = target_db - current_db
        adjustment_amplitude = db_to_amplitude(adjustment_db)

        return clip.volumex(adjustment_amplitude)

    def close_clips(self, *clips: AudioFileClip) -> None:
        """Safely close audio clips to free resources."""
        for clip in clips:
            if clip is not None:
                try:
                    clip.close()
                except Exception as e:
                    logger.warning(f"Error closing audio clip: {e}")
