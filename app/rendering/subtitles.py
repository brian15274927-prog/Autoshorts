"""
Subtitle Engine with word-level highlighting.
Generates dynamic karaoke-style subtitles where active word changes color.
"""
import logging
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from moviepy.editor import ImageClip, CompositeVideoClip, ColorClip
from moviepy.video.VideoClip import VideoClip

from .models import WordTimestamp, AudioTimestamps

logger = logging.getLogger(__name__)


@dataclass
class SubtitleStyle:
    font_path: Optional[str] = None
    font_size: int = 70
    color: str = "white"
    active_color: str = "#FFD700"
    stroke_color: str = "black"
    stroke_width: int = 3
    line_spacing: int = 10
    max_chars_per_line: int = 35
    max_words_per_group: int = 6
    padding_x: int = 40
    padding_y: int = 20


@dataclass
class WordGroup:
    words: list[WordTimestamp] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0

    @property
    def text(self) -> str:
        return " ".join(w.word for w in self.words)

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    def get_active_word_index(self, time: float) -> Optional[int]:
        for i, word in enumerate(self.words):
            if word.start <= time < word.end:
                return i
        return None


class SubtitleEngine:
    """
    Engine for generating dynamic subtitles with word-level highlighting.
    Uses PIL for high-quality text rendering with precise positioning.
    """

    def __init__(
        self,
        video_width: int = 1080,
        video_height: int = 1920,
        style: Optional[SubtitleStyle] = None,
    ):
        self.video_width = video_width
        self.video_height = video_height
        self.style = style or SubtitleStyle()
        self.subtitle_y_position = int(video_height * 0.72)

        self._font = self._load_font()
        self._font_metrics = self._calculate_font_metrics()

    def _load_font(self) -> ImageFont.FreeTypeFont:
        if self.style.font_path:
            try:
                return ImageFont.truetype(self.style.font_path, self.style.font_size)
            except Exception as e:
                logger.warning(f"Failed to load font {self.style.font_path}: {e}")

        try:
            return ImageFont.truetype("Arial Bold", self.style.font_size)
        except Exception:
            pass

        try:
            return ImageFont.truetype("DejaVuSans-Bold", self.style.font_size)
        except Exception:
            pass

        try:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", self.style.font_size)
        except Exception:
            pass

        logger.warning("Using default PIL font, text quality may be reduced")
        return ImageFont.load_default()

    def _calculate_font_metrics(self) -> dict:
        test_img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        draw = ImageDraw.Draw(test_img)

        bbox = draw.textbbox((0, 0), "Ayg", font=self._font)
        line_height = bbox[3] - bbox[1]

        space_bbox = draw.textbbox((0, 0), " ", font=self._font)
        space_width = space_bbox[2] - space_bbox[0]

        return {
            "line_height": line_height,
            "space_width": space_width,
        }

    def _get_text_size(self, text: str) -> tuple[int, int]:
        test_img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        draw = ImageDraw.Draw(test_img)
        bbox = draw.textbbox((0, 0), text, font=self._font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def _parse_color(self, color: str) -> tuple[int, int, int, int]:
        if color.startswith("#"):
            color = color[1:]
            if len(color) == 6:
                r = int(color[0:2], 16)
                g = int(color[2:4], 16)
                b = int(color[4:6], 16)
                return (r, g, b, 255)
            elif len(color) == 8:
                r = int(color[0:2], 16)
                g = int(color[2:4], 16)
                b = int(color[4:6], 16)
                a = int(color[6:8], 16)
                return (r, g, b, a)

        color_map = {
            "white": (255, 255, 255, 255),
            "black": (0, 0, 0, 255),
            "red": (255, 0, 0, 255),
            "green": (0, 255, 0, 255),
            "blue": (0, 0, 255, 255),
            "yellow": (255, 255, 0, 255),
            "gold": (255, 215, 0, 255),
        }

        return color_map.get(color.lower(), (255, 255, 255, 255))

    def group_words(self, timestamps: AudioTimestamps) -> list[WordGroup]:
        groups = []
        current_words = []

        for word in timestamps.words:
            current_words.append(word)

            current_text = " ".join(w.word for w in current_words)
            should_break = (
                len(current_words) >= self.style.max_words_per_group or
                len(current_text) > self.style.max_chars_per_line or
                word.word.rstrip().endswith((".", "!", "?"))
            )

            if should_break and current_words:
                group = WordGroup(
                    words=current_words.copy(),
                    start_time=current_words[0].start,
                    end_time=current_words[-1].end,
                )
                groups.append(group)
                current_words = []

        if current_words:
            group = WordGroup(
                words=current_words,
                start_time=current_words[0].start,
                end_time=current_words[-1].end,
            )
            groups.append(group)

        return groups

    def _render_subtitle_frame(
        self,
        group: WordGroup,
        active_word_index: Optional[int],
    ) -> np.ndarray:
        normal_color = self._parse_color(self.style.color)
        active_color = self._parse_color(self.style.active_color)
        stroke_color = self._parse_color(self.style.stroke_color)

        word_sizes = []
        for word in group.words:
            w, h = self._get_text_size(word.word)
            word_sizes.append((w, h))

        space_width = self._font_metrics["space_width"]
        total_width = sum(ws[0] for ws in word_sizes) + space_width * (len(group.words) - 1)
        max_height = max(ws[1] for ws in word_sizes) if word_sizes else self.style.font_size

        img_width = total_width + self.style.padding_x * 2
        img_height = max_height + self.style.padding_y * 2

        img = Image.new("RGBA", (img_width, img_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        x_offset = self.style.padding_x
        y_offset = self.style.padding_y

        for i, (word, (w, h)) in enumerate(zip(group.words, word_sizes)):
            color = active_color if i == active_word_index else normal_color

            if self.style.stroke_width > 0:
                for dx in range(-self.style.stroke_width, self.style.stroke_width + 1):
                    for dy in range(-self.style.stroke_width, self.style.stroke_width + 1):
                        if dx != 0 or dy != 0:
                            draw.text(
                                (x_offset + dx, y_offset + dy),
                                word.word,
                                font=self._font,
                                fill=stroke_color,
                            )

            draw.text(
                (x_offset, y_offset),
                word.word,
                font=self._font,
                fill=color,
            )

            x_offset += w + space_width

        return np.array(img)

    def create_subtitle_clip_for_group(
        self,
        group: WordGroup,
        fps: int = 30,
    ) -> VideoClip:
        frame_cache = {}

        def make_frame(t):
            global_time = group.start_time + t
            active_index = group.get_active_word_index(global_time)

            cache_key = active_index

            if cache_key not in frame_cache:
                frame_cache[cache_key] = self._render_subtitle_frame(group, active_index)

            return frame_cache[cache_key]

        clip = VideoClip(make_frame, duration=group.duration)
        clip = clip.set_fps(fps)

        frame_sample = make_frame(0)
        clip_height, clip_width = frame_sample.shape[:2]

        x_pos = (self.video_width - clip_width) // 2
        y_pos = self.subtitle_y_position

        clip = clip.set_position((x_pos, y_pos))
        clip = clip.set_start(group.start_time)

        return clip

    def create_all_subtitle_clips(
        self,
        timestamps: AudioTimestamps,
        fps: int = 30,
    ) -> list[VideoClip]:
        groups = self.group_words(timestamps)

        logger.info(f"Creating subtitle clips for {len(groups)} word groups")

        clips = []
        for i, group in enumerate(groups):
            clip = self.create_subtitle_clip_for_group(group, fps)
            clips.append(clip)
            logger.debug(f"Created subtitle clip {i+1}/{len(groups)}: '{group.text}' ({group.start_time:.2f}-{group.end_time:.2f}s)")

        return clips


class SRTGenerator:
    """
    Generate SRT subtitle files from word timestamps.
    """

    @staticmethod
    def format_timestamp(seconds: float) -> str:
        if seconds < 0:
            seconds = 0

        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)

        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    @classmethod
    def generate(
        cls,
        timestamps: AudioTimestamps,
        output_path: Path,
        max_words_per_line: int = 6,
        max_chars_per_line: int = 35,
    ) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        segments = []
        current_words = []

        for word in timestamps.words:
            current_words.append(word)

            current_text = " ".join(w.word for w in current_words)
            should_break = (
                len(current_words) >= max_words_per_line or
                len(current_text) > max_chars_per_line or
                word.word.rstrip().endswith((".", "!", "?"))
            )

            if should_break and current_words:
                segments.append({
                    "text": " ".join(w.word for w in current_words),
                    "start": current_words[0].start,
                    "end": current_words[-1].end,
                })
                current_words = []

        if current_words:
            segments.append({
                "text": " ".join(w.word for w in current_words),
                "start": current_words[0].start,
                "end": current_words[-1].end,
            })

        with open(output_path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments, 1):
                start_ts = cls.format_timestamp(seg["start"])
                end_ts = cls.format_timestamp(seg["end"])

                wrapped_text = textwrap.fill(seg["text"], width=max_chars_per_line)

                f.write(f"{i}\n")
                f.write(f"{start_ts} --> {end_ts}\n")
                f.write(f"{wrapped_text}\n")
                f.write("\n")

        logger.info(f"Generated SRT file: {output_path} ({len(segments)} segments)")

        return output_path

    @classmethod
    def generate_with_word_highlighting(
        cls,
        timestamps: AudioTimestamps,
        output_path: Path,
        max_words_per_line: int = 6,
    ) -> Path:
        """
        Generate SRT with <font> tags for word highlighting.
        Useful for players that support styled subtitles.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        subtitle_index = 1

        with open(output_path, "w", encoding="utf-8") as f:
            groups = []
            current_words = []

            for word in timestamps.words:
                current_words.append(word)

                if len(current_words) >= max_words_per_line or word.word.rstrip().endswith((".", "!", "?")):
                    groups.append(current_words.copy())
                    current_words = []

            if current_words:
                groups.append(current_words)

            for group in groups:
                for active_idx, active_word in enumerate(group):
                    words_text = []
                    for i, w in enumerate(group):
                        if i == active_idx:
                            words_text.append(f'<font color="#FFD700">{w.word}</font>')
                        else:
                            words_text.append(w.word)

                    start_ts = cls.format_timestamp(active_word.start)
                    end_ts = cls.format_timestamp(active_word.end)

                    f.write(f"{subtitle_index}\n")
                    f.write(f"{start_ts} --> {end_ts}\n")
                    f.write(" ".join(words_text) + "\n")
                    f.write("\n")

                    subtitle_index += 1

        logger.info(f"Generated highlighted SRT file: {output_path}")

        return output_path
