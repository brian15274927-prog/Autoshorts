"""
Universal VideoSpec - единый формат для всех видео.
Любой источник (YouTube, Audio, Upload) → VideoSpec → Revideo
"""
from pathlib import Path
from typing import Optional, List, Dict, Any, Literal
from dataclasses import dataclass, field, asdict
from enum import Enum
import json
import uuid
from datetime import datetime


class AspectRatio(str, Enum):
    """Поддерживаемые форматы видео."""
    PORTRAIT = "9:16"      # Shorts, TikTok, Reels (1080x1920)
    LANDSCAPE = "16:9"     # YouTube, standard (1920x1080)
    SQUARE = "1:1"         # Instagram posts (1080x1080)


class LayerType(str, Enum):
    """Типы слоёв в видео."""
    VIDEO = "video"
    IMAGE = "image"
    TEXT = "text"
    SUBTITLE = "subtitle"
    SHAPE = "shape"
    AUDIO = "audio"


class TransitionType(str, Enum):
    """Типы переходов между сценами."""
    NONE = "none"
    FADE = "fade"
    SLIDE_LEFT = "slide_left"
    SLIDE_RIGHT = "slide_right"
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"


@dataclass
class Position:
    """Позиция элемента."""
    x: float = 0.5  # 0-1, относительно ширины
    y: float = 0.5  # 0-1, относительно высоты
    anchor: str = "center"  # center, top, bottom, left, right


@dataclass
class TextStyle:
    """Стиль текста."""
    font_family: str = "Inter"
    font_size: int = 70
    font_weight: int = 700
    color: str = "#FFFFFF"
    background_color: Optional[str] = None
    stroke_color: Optional[str] = "#000000"
    stroke_width: int = 2
    shadow: bool = True
    shadow_color: str = "#000000"
    shadow_blur: int = 4


@dataclass
class Animation:
    """Анимация элемента."""
    type: str = "none"  # none, fade_in, fade_out, slide, scale, bounce
    duration: float = 0.3
    delay: float = 0.0
    easing: str = "ease-out"


@dataclass
class Layer:
    """Слой в сцене."""
    id: str = field(default_factory=lambda: f"layer_{uuid.uuid4().hex[:8]}")
    type: LayerType = LayerType.TEXT
    content: str = ""  # Текст, путь к файлу, URL
    start: float = 0.0
    end: Optional[float] = None  # None = до конца сцены
    position: Position = field(default_factory=Position)
    style: Optional[TextStyle] = None
    animation_in: Optional[Animation] = None
    animation_out: Optional[Animation] = None
    opacity: float = 1.0
    z_index: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['type'] = self.type.value if isinstance(self.type, LayerType) else self.type
        return d


@dataclass
class Subtitle:
    """Субтитр."""
    id: str = field(default_factory=lambda: f"sub_{uuid.uuid4().hex[:8]}")
    text: str = ""
    start: float = 0.0
    end: float = 1.0
    style: Optional[TextStyle] = None
    position: Position = field(default_factory=lambda: Position(x=0.5, y=0.85))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Scene:
    """Сцена в видео."""
    id: str = field(default_factory=lambda: f"scene_{uuid.uuid4().hex[:8]}")
    name: str = "Scene"
    duration: float = 5.0
    background_color: str = "#000000"
    background_media: Optional[str] = None  # Путь к видео/изображению
    layers: List[Layer] = field(default_factory=list)
    transition_in: TransitionType = TransitionType.NONE
    transition_out: TransitionType = TransitionType.NONE
    transition_duration: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        d = {
            'id': self.id,
            'name': self.name,
            'duration': self.duration,
            'background_color': self.background_color,
            'background_media': self.background_media,
            'layers': [l.to_dict() for l in self.layers],
            'transition_in': self.transition_in.value if isinstance(self.transition_in, TransitionType) else self.transition_in,
            'transition_out': self.transition_out.value if isinstance(self.transition_out, TransitionType) else self.transition_out,
            'transition_duration': self.transition_duration,
        }
        return d


@dataclass
class VideoSpec:
    """
    Универсальная спецификация видео.
    Единый формат для любого источника.
    """
    id: str = field(default_factory=lambda: f"video_{uuid.uuid4().hex[:12]}")
    name: str = "Untitled Video"

    # Формат
    aspect_ratio: AspectRatio = AspectRatio.PORTRAIT
    width: int = 1080
    height: int = 1920
    fps: int = 30

    # Контент
    scenes: List[Scene] = field(default_factory=list)
    subtitles: List[Subtitle] = field(default_factory=list)

    # Аудио
    audio_track: Optional[str] = None  # Путь к аудио
    audio_volume: float = 1.0
    background_music: Optional[str] = None
    background_music_volume: float = 0.3

    # Стили по умолчанию
    default_text_style: TextStyle = field(default_factory=TextStyle)
    default_subtitle_style: TextStyle = field(default_factory=lambda: TextStyle(
        font_size=60,
        font_weight=700,
        color="#FFFFFF",
        stroke_color="#000000",
        stroke_width=3,
    ))

    # Метаданные
    source_type: str = "manual"  # manual, youtube, audio, upload
    source_url: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def total_duration(self) -> float:
        """Общая длительность видео."""
        return sum(scene.duration for scene in self.scenes)

    def add_scene(self, scene: Scene) -> None:
        """Добавить сцену."""
        self.scenes.append(scene)

    def add_subtitle(self, subtitle: Subtitle) -> None:
        """Добавить субтитр."""
        self.subtitles.append(subtitle)

    def set_aspect_ratio(self, ratio: AspectRatio) -> None:
        """Установить формат видео."""
        self.aspect_ratio = ratio
        if ratio == AspectRatio.PORTRAIT:
            self.width, self.height = 1080, 1920
        elif ratio == AspectRatio.LANDSCAPE:
            self.width, self.height = 1920, 1080
        elif ratio == AspectRatio.SQUARE:
            self.width, self.height = 1080, 1080

    def to_dict(self) -> Dict[str, Any]:
        """Конвертировать в словарь для JSON."""
        return {
            'id': self.id,
            'name': self.name,
            'aspect_ratio': self.aspect_ratio.value if isinstance(self.aspect_ratio, AspectRatio) else self.aspect_ratio,
            'width': self.width,
            'height': self.height,
            'fps': self.fps,
            'scenes': [s.to_dict() for s in self.scenes],
            'subtitles': [s.to_dict() for s in self.subtitles],
            'audio_track': self.audio_track,
            'audio_volume': self.audio_volume,
            'background_music': self.background_music,
            'background_music_volume': self.background_music_volume,
            'default_text_style': asdict(self.default_text_style),
            'default_subtitle_style': asdict(self.default_subtitle_style),
            'source_type': self.source_type,
            'source_url': self.source_url,
            'created_at': self.created_at,
            'total_duration': self.total_duration,
        }

    def to_json(self, indent: int = 2) -> str:
        """Конвертировать в JSON строку."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoSpec':
        """Создать из словаря."""
        spec = cls(
            id=data.get('id', f"video_{uuid.uuid4().hex[:12]}"),
            name=data.get('name', 'Untitled'),
            width=data.get('width', 1080),
            height=data.get('height', 1920),
            fps=data.get('fps', 30),
            audio_track=data.get('audio_track'),
            audio_volume=data.get('audio_volume', 1.0),
            background_music=data.get('background_music'),
            background_music_volume=data.get('background_music_volume', 0.3),
            source_type=data.get('source_type', 'manual'),
            source_url=data.get('source_url'),
        )

        # Aspect ratio
        ar = data.get('aspect_ratio', '9:16')
        if ar == '9:16':
            spec.aspect_ratio = AspectRatio.PORTRAIT
        elif ar == '16:9':
            spec.aspect_ratio = AspectRatio.LANDSCAPE
        elif ar == '1:1':
            spec.aspect_ratio = AspectRatio.SQUARE

        # Scenes
        for scene_data in data.get('scenes', []):
            layers = []
            for layer_data in scene_data.get('layers', []):
                layer = Layer(
                    id=layer_data.get('id', f"layer_{uuid.uuid4().hex[:8]}"),
                    type=LayerType(layer_data.get('type', 'text')),
                    content=layer_data.get('content', ''),
                    start=layer_data.get('start', 0.0),
                    end=layer_data.get('end'),
                    opacity=layer_data.get('opacity', 1.0),
                    z_index=layer_data.get('z_index', 0),
                )
                layers.append(layer)

            scene = Scene(
                id=scene_data.get('id', f"scene_{uuid.uuid4().hex[:8]}"),
                name=scene_data.get('name', 'Scene'),
                duration=scene_data.get('duration', 5.0),
                background_color=scene_data.get('background_color', '#000000'),
                background_media=scene_data.get('background_media'),
                layers=layers,
            )
            spec.scenes.append(scene)

        # Subtitles
        for sub_data in data.get('subtitles', []):
            sub = Subtitle(
                id=sub_data.get('id', f"sub_{uuid.uuid4().hex[:8]}"),
                text=sub_data.get('text', ''),
                start=sub_data.get('start', 0.0),
                end=sub_data.get('end', 1.0),
            )
            spec.subtitles.append(sub)

        return spec

    @classmethod
    def from_json(cls, json_str: str) -> 'VideoSpec':
        """Создать из JSON строки."""
        return cls.from_dict(json.loads(json_str))


def create_simple_video(
    text: str,
    duration: float = 5.0,
    aspect_ratio: AspectRatio = AspectRatio.PORTRAIT,
    background_color: str = "#1a1a2e",
) -> VideoSpec:
    """Быстрое создание простого видео с текстом."""
    spec = VideoSpec(name=text[:30])
    spec.set_aspect_ratio(aspect_ratio)

    scene = Scene(
        name="Main",
        duration=duration,
        background_color=background_color,
        layers=[
            Layer(
                type=LayerType.TEXT,
                content=text,
                position=Position(x=0.5, y=0.5),
            )
        ]
    )
    spec.add_scene(scene)

    return spec


def create_video_from_subtitles(
    subtitles: List[Dict[str, Any]],
    background_media: Optional[str] = None,
    aspect_ratio: AspectRatio = AspectRatio.PORTRAIT,
) -> VideoSpec:
    """Создать видео из списка субтитров."""
    spec = VideoSpec(name="Subtitled Video")
    spec.set_aspect_ratio(aspect_ratio)

    if not subtitles:
        return spec

    # Вычисляем общую длительность
    total_duration = max(s.get('end', 0) for s in subtitles)

    # Одна сцена на всё видео
    scene = Scene(
        name="Main",
        duration=total_duration,
        background_media=background_media,
    )
    spec.add_scene(scene)

    # Добавляем субтитры
    for sub in subtitles:
        spec.add_subtitle(Subtitle(
            id=sub.get('id', f"sub_{uuid.uuid4().hex[:8]}"),
            text=sub.get('text', ''),
            start=sub.get('start', 0.0),
            end=sub.get('end', 1.0),
        ))

    return spec
