"""
Video Rendering Engine - Main orchestrator.
Assembles vertical 1080x1920 videos with subtitles, audio mixing.
"""
import logging
import time
import os
from pathlib import Path
from typing import Optional, Callable, Union

import numpy as np
from moviepy.editor import (
    VideoFileClip,
    ImageClip,
    CompositeVideoClip,
    concatenate_videoclips,
    ColorClip,
    AudioFileClip,
)
from moviepy.video.fx.all import resize, crop, fadein, fadeout
from moviepy.audio.fx.all import audio_fadein, audio_fadeout

from .models import (
    RenderJob,
    RenderResult,
    RenderProgress,
    SceneData,
    SceneType,
    AudioTimestamps,
    WordTimestamp,
)
from .subtitles import SubtitleEngine, SRTGenerator, SubtitleStyle
from .audio import AudioMixer
from .cost import CostCalculator, UsageMetrics

logger = logging.getLogger(__name__)


class VideoRenderEngine:
    """
    Production video rendering engine for vertical AI videos (1080x1920).

    Pipeline:
    1. Load and resize background clips per scene
    2. Generate dynamic subtitles with word highlighting
    3. Composite video with subtitles
    4. Mix audio (voice + BGM at -20dB)
    5. Export final MP4 + SRT
    """

    def __init__(
        self,
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
        video_codec: str = "libx264",
        audio_codec: str = "aac",
        video_bitrate: str = "8M",
        audio_bitrate: str = "192k",
        preset: str = "medium",
        threads: int = 4,
        bgm_volume_db: float = -20.0,
        subtitle_style: Optional[SubtitleStyle] = None,
        progress_callback: Optional[Callable[[RenderProgress], None]] = None,
    ):
        self.width = width
        self.height = height
        self.fps = fps
        self.video_codec = video_codec
        self.audio_codec = audio_codec
        self.video_bitrate = video_bitrate
        self.audio_bitrate = audio_bitrate
        self.preset = preset
        self.threads = threads

        self.subtitle_engine = SubtitleEngine(
            video_width=width,
            video_height=height,
            style=subtitle_style,
        )
        self.audio_mixer = AudioMixer(bgm_volume_db=bgm_volume_db)
        self.cost_calculator = CostCalculator()
        self.progress_callback = progress_callback

        logger.info(
            f"VideoRenderEngine initialized: {width}x{height}@{fps}fps, "
            f"codec={video_codec}, preset={preset}"
        )

    def _emit_progress(
        self,
        job_id: str,
        stage: str,
        progress: float,
        message: str = "",
        current_scene: Optional[int] = None,
        total_scenes: Optional[int] = None,
    ) -> None:
        progress_data = RenderProgress(
            job_id=job_id,
            stage=stage,
            progress=min(100.0, max(0.0, progress)),
            current_scene=current_scene,
            total_scenes=total_scenes,
            message=message,
        )

        logger.info(f"[{job_id}] {stage}: {progress:.1f}% - {message}")

        if self.progress_callback:
            try:
                self.progress_callback(progress_data)
            except Exception as e:
                logger.warning(f"Progress callback failed: {e}")

    def _validate_file_exists(self, path: Union[str, Path], file_type: str) -> Path:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"{file_type} not found: {path}")
        return path

    def _fit_to_vertical(
        self,
        clip: Union[VideoFileClip, ImageClip],
    ) -> Union[VideoFileClip, ImageClip]:
        """
        Resize and center-crop clip to fit 9:16 vertical aspect ratio.
        """
        target_aspect = self.width / self.height
        source_aspect = clip.w / clip.h

        if abs(source_aspect - target_aspect) < 0.01:
            if clip.w != self.width or clip.h != self.height:
                return resize(clip, (self.width, self.height))
            return clip

        if source_aspect > target_aspect:
            new_height = self.height
            scale_factor = new_height / clip.h
            new_width = int(clip.w * scale_factor)
            resized = resize(clip, (new_width, new_height))

            x_center = new_width // 2
            x1 = x_center - (self.width // 2)
            x2 = x1 + self.width

            return crop(resized, x1=x1, y1=0, x2=x2, y2=self.height)

        else:
            new_width = self.width
            scale_factor = new_width / clip.w
            new_height = int(clip.h * scale_factor)
            resized = resize(clip, (new_width, new_height))

            y_center = new_height // 2
            y1 = y_center - (self.height // 2)
            y2 = y1 + self.height

            return crop(resized, x1=0, y1=y1, x2=self.width, y2=y2)

    def _load_background_clip(
        self,
        scene: SceneData,
    ) -> Union[VideoFileClip, ImageClip]:
        """
        Load background for scene and fit to vertical format.
        Handles video looping if source is shorter than scene duration.
        """
        path = self._validate_file_exists(scene.background_path, "Background file")

        scene_duration = scene.duration

        if scene.scene_type == SceneType.IMAGE:
            clip = ImageClip(str(path))
            clip = clip.set_duration(scene_duration)
            clip = self._fit_to_vertical(clip)
            clip = clip.set_fps(self.fps)
            return clip

        source_clip = VideoFileClip(str(path))

        if source_clip.duration >= scene_duration:
            clip = source_clip.subclip(0, scene_duration)
        else:
            loops_needed = int(np.ceil(scene_duration / source_clip.duration))
            clips = [source_clip] * loops_needed
            looped = concatenate_videoclips(clips, method="compose")
            clip = looped.subclip(0, scene_duration)

        clip = self._fit_to_vertical(clip)
        clip = clip.set_fps(self.fps)

        return clip

    def _build_scene_clip(
        self,
        scene: SceneData,
        timestamps: AudioTimestamps,
        job_id: str,
        scene_index: int,
        total_scenes: int,
    ) -> CompositeVideoClip:
        """
        Build complete scene with background and subtitles.
        """
        self._emit_progress(
            job_id=job_id,
            stage="building_scene",
            progress=10 + (scene_index / total_scenes) * 40,
            message=f"Building scene {scene_index + 1}/{total_scenes}",
            current_scene=scene_index + 1,
            total_scenes=total_scenes,
        )

        background = self._load_background_clip(scene)

        scene_words = timestamps.get_words_in_range(scene.start_time, scene.end_time)

        if not scene_words:
            return background

        adjusted_words = []
        for word in scene_words:
            adjusted_start = max(0, word.start - scene.start_time)
            adjusted_end = min(scene.duration, word.end - scene.start_time)

            if adjusted_end > adjusted_start:
                adjusted_words.append(WordTimestamp(
                    word=word.word,
                    start=adjusted_start,
                    end=adjusted_end,
                ))

        if not adjusted_words:
            return background

        scene_timestamps = AudioTimestamps(
            words=adjusted_words,
            total_duration=scene.duration,
        )

        subtitle_clips = self.subtitle_engine.create_all_subtitle_clips(
            timestamps=scene_timestamps,
            fps=self.fps,
        )

        all_clips = [background] + subtitle_clips

        composite = CompositeVideoClip(
            all_clips,
            size=(self.width, self.height),
        )
        composite = composite.set_duration(scene.duration)
        composite = composite.set_fps(self.fps)

        return composite

    def _apply_scene_transitions(
        self,
        clips: list[CompositeVideoClip],
        scenes: list[SceneData],
    ) -> list[CompositeVideoClip]:
        """
        Apply transitions between scenes.
        Currently supports: crossfade
        """
        if len(clips) < 2:
            return clips

        processed = []

        for i, (clip, scene) in enumerate(zip(clips, scenes)):
            if i == 0:
                processed.append(clip)
                continue

            prev_scene = scenes[i - 1]
            transition_type = prev_scene.transition_in
            transition_duration = prev_scene.transition_duration

            if transition_type == "crossfade" and transition_duration > 0:
                prev_clip = processed[-1]

                prev_with_fade = fadeout(prev_clip, transition_duration)
                curr_with_fade = fadein(clip, transition_duration)

                processed[-1] = prev_with_fade
                processed.append(curr_with_fade)
            else:
                processed.append(clip)

        return processed

    def _concatenate_scenes(
        self,
        scene_clips: list[CompositeVideoClip],
        scenes: list[SceneData],
    ) -> CompositeVideoClip:
        """
        Concatenate all scene clips with transitions.
        """
        if len(scene_clips) == 1:
            return scene_clips[0]

        processed_clips = self._apply_scene_transitions(scene_clips, scenes)

        final = concatenate_videoclips(
            processed_clips,
            method="compose",
        )

        return final

    def _close_clips(self, *clips) -> None:
        """Safely close video/audio clips."""
        for clip in clips:
            if clip is not None:
                try:
                    clip.close()
                except Exception as e:
                    logger.warning(f"Error closing clip: {e}")

    def render(self, job: RenderJob) -> RenderResult:
        """
        Execute complete video rendering pipeline.

        Args:
            job: RenderJob with all input parameters

        Returns:
            RenderResult with output paths and metadata
        """
        start_time = time.time()
        job_id = job.job_id

        clips_to_close = []

        try:
            self._emit_progress(
                job_id=job_id,
                stage="initializing",
                progress=0,
                message="Validating inputs",
            )

            audio_path = self._validate_file_exists(job.audio_path, "Audio file")
            if job.bgm_path:
                bgm_path = self._validate_file_exists(job.bgm_path, "BGM file")
            else:
                bgm_path = None

            for scene in job.script.scenes:
                self._validate_file_exists(scene.background_path, f"Background for scene {scene.scene_id}")

            output_dir = Path(job.output_dir) / job_id
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / job.output_filename

            self._emit_progress(
                job_id=job_id,
                stage="building_scenes",
                progress=10,
                message=f"Building {len(job.script.scenes)} scenes",
            )

            scene_clips = []
            total_scenes = len(job.script.scenes)

            for i, scene in enumerate(job.script.scenes):
                scene_clip = self._build_scene_clip(
                    scene=scene,
                    timestamps=job.timestamps,
                    job_id=job_id,
                    scene_index=i,
                    total_scenes=total_scenes,
                )
                scene_clips.append(scene_clip)
                clips_to_close.append(scene_clip)

            self._emit_progress(
                job_id=job_id,
                stage="concatenating",
                progress=55,
                message="Assembling final video",
            )

            final_video = self._concatenate_scenes(scene_clips, job.script.scenes)
            clips_to_close.append(final_video)

            video_duration = final_video.duration
            logger.info(f"Video assembled: duration={video_duration:.2f}s")

            self._emit_progress(
                job_id=job_id,
                stage="mixing_audio",
                progress=65,
                message="Mixing audio tracks",
            )

            mixed_audio = self.audio_mixer.mix_audio(
                voice_path=audio_path,
                bgm_path=bgm_path,
                total_duration=video_duration,
                bgm_fade_in=1.0,
                bgm_fade_out=2.0,
            )
            clips_to_close.append(mixed_audio)

            final_video = final_video.set_audio(mixed_audio)

            self._emit_progress(
                job_id=job_id,
                stage="exporting",
                progress=70,
                message=f"Encoding video ({self.video_codec}, {self.preset})",
            )

            ffmpeg_params = [
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
            ]

            final_video.write_videofile(
                str(output_path),
                fps=self.fps,
                codec=self.video_codec,
                audio_codec=self.audio_codec,
                bitrate=self.video_bitrate,
                audio_bitrate=self.audio_bitrate,
                preset=self.preset,
                threads=self.threads,
                ffmpeg_params=ffmpeg_params,
                logger=None,
                verbose=False,
            )

            srt_path = None
            if job.generate_srt:
                self._emit_progress(
                    job_id=job_id,
                    stage="generating_srt",
                    progress=95,
                    message="Generating subtitle file",
                )

                srt_path = output_dir / job.output_filename.replace(".mp4", ".srt")
                SRTGenerator.generate(
                    timestamps=job.timestamps,
                    output_path=srt_path,
                )

            file_size_bytes = output_path.stat().st_size
            file_size_mb = round(file_size_bytes / (1024 * 1024), 2)

            render_duration = time.time() - start_time
            scenes_count = len(job.script.scenes)

            usage_metrics = UsageMetrics.create(
                render_time_seconds=render_duration,
                video_duration_seconds=video_duration,
                scenes_count=scenes_count,
                width=self.width,
                height=self.height,
                fps=self.fps,
                output_size_mb=file_size_mb,
            )

            cost_breakdown = self.cost_calculator.calculate(usage_metrics)

            self._emit_progress(
                job_id=job_id,
                stage="completed",
                progress=100,
                message=f"Render complete: {file_size_mb}MB in {render_duration:.1f}s, cost=${cost_breakdown.total_cost_usd:.6f}",
            )

            logger.info(
                f"Render complete: job={job_id}, output={output_path}, "
                f"size={file_size_mb}MB, duration={render_duration:.1f}s, "
                f"cost=${cost_breakdown.total_cost_usd:.6f}"
            )

            return RenderResult(
                job_id=job_id,
                success=True,
                output_path=str(output_path),
                srt_path=str(srt_path) if srt_path else None,
                duration_seconds=render_duration,
                file_size_mb=file_size_mb,
                video_duration_seconds=video_duration,
                scenes_count=scenes_count,
                resolution=f"{self.width}x{self.height}",
                fps=self.fps,
                cost_usd=cost_breakdown.total_cost_usd,
                cost_breakdown=cost_breakdown.model_dump(),
                usage_metrics=usage_metrics.model_dump(),
            )

        except FileNotFoundError as e:
            render_duration = time.time() - start_time
            partial_cost = self.cost_calculator.calculate_partial(render_duration)

            logger.error(f"File not found during render: {e}")
            return RenderResult(
                job_id=job_id,
                success=False,
                duration_seconds=render_duration,
                error=f"File not found: {e}",
                cost_usd=partial_cost.total_cost_usd,
                cost_breakdown=partial_cost.model_dump(),
            )

        except Exception as e:
            render_duration = time.time() - start_time
            partial_cost = self.cost_calculator.calculate_partial(render_duration)

            logger.exception(f"Render failed for job {job_id}")
            return RenderResult(
                job_id=job_id,
                success=False,
                duration_seconds=render_duration,
                error=str(e),
                cost_usd=partial_cost.total_cost_usd,
                cost_breakdown=partial_cost.model_dump(),
            )

        finally:
            for clip in clips_to_close:
                self._close_clips(clip)
