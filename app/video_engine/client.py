"""
Revideo Client - Python HTTP client for Revideo Node.js API
"""
import httpx
import asyncio
import subprocess
import os
import time
import signal
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum


class TemplateType(str, Enum):
    SHORTS_VERTICAL = "shorts-vertical"
    TIKTOK = "tiktok"
    YOUTUBE_LANDSCAPE = "youtube-landscape"
    INSTAGRAM_SQUARE = "instagram-square"
    CUSTOM = "custom"


class AnimationType(str, Enum):
    NONE = "none"
    FADE = "fade"
    POP = "pop"
    SLIDE = "slide"
    TYPEWRITER = "typewriter"
    HIGHLIGHT = "highlight"


class QualityLevel(str, Enum):
    DRAFT = "draft"
    PREVIEW = "preview"
    PRODUCTION = "production"


@dataclass
class WordSpec:
    word: str
    start: float
    end: float


@dataclass
class SubtitleStyle:
    font_family: str = "Arial Black"
    font_size: int = 72
    font_weight: int = 900
    color: str = "#FFFFFF"
    background_color: Optional[str] = "#000000CC"
    background_padding: int = 16
    border_radius: int = 8
    text_align: str = "center"
    position: str = "center"
    offset_y: int = 0
    highlight_color: Optional[str] = "#FFFF00"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fontFamily": self.font_family,
            "fontSize": self.font_size,
            "fontWeight": self.font_weight,
            "color": self.color,
            "backgroundColor": self.background_color,
            "backgroundPadding": self.background_padding,
            "borderRadius": self.border_radius,
            "textAlign": self.text_align,
            "position": self.position,
            "offsetY": self.offset_y,
            "highlightColor": self.highlight_color,
        }


@dataclass
class SubtitleAnimation:
    type: AnimationType = AnimationType.POP
    duration: float = 0.3

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "duration": self.duration,
        }


@dataclass
class SubtitleSpec:
    id: str
    text: str
    start: float
    end: float
    style: Optional[SubtitleStyle] = None
    animation: Optional[SubtitleAnimation] = None
    words: Optional[List[WordSpec]] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "id": self.id,
            "text": self.text,
            "start": self.start,
            "end": self.end,
        }
        if self.style:
            result["style"] = self.style.to_dict()
        if self.animation:
            result["animation"] = self.animation.to_dict()
        if self.words:
            result["words"] = [{"word": w.word, "start": w.start, "end": w.end} for w in self.words]
        return result


@dataclass
class ClipSpec:
    id: str
    type: str  # 'video', 'image', 'color'
    start: float
    end: float
    src: Optional[str] = None
    color: Optional[str] = None
    position: Optional[Dict[str, int]] = None
    size: Optional[Dict[str, Any]] = None
    opacity: float = 1.0
    rotation: float = 0.0
    z_index: int = 0

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "id": self.id,
            "type": self.type,
            "start": self.start,
            "end": self.end,
            "opacity": self.opacity,
            "rotation": self.rotation,
            "zIndex": self.z_index,
        }
        if self.src:
            result["src"] = self.src
        if self.color:
            result["color"] = self.color
        if self.position:
            result["position"] = self.position
        if self.size:
            result["size"] = self.size
        return result


@dataclass
class AudioSpec:
    src: str
    volume: float = 1.0
    fade_in: float = 0.0
    fade_out: float = 0.0
    loop: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "src": self.src,
            "volume": self.volume,
            "fadeIn": self.fade_in,
            "fadeOut": self.fade_out,
            "loop": self.loop,
        }


@dataclass
class VideoSpec:
    id: str
    width: int = 1080
    height: int = 1920
    fps: int = 30
    duration: float = 10.0
    background: str = "#000000"
    clips: List[ClipSpec] = field(default_factory=list)
    subtitles: List[SubtitleSpec] = field(default_factory=list)
    audio: Optional[AudioSpec] = None
    template: Optional[TemplateType] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "id": self.id,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "duration": self.duration,
            "background": self.background,
            "clips": [c.to_dict() for c in self.clips],
            "subtitles": [s.to_dict() for s in self.subtitles],
        }
        if self.audio:
            result["audio"] = self.audio.to_dict()
        if self.template:
            result["template"] = self.template.value
        return result


@dataclass
class RenderOptions:
    quality: QualityLevel = QualityLevel.PRODUCTION
    format: str = "mp4"
    output_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "quality": self.quality.value,
            "format": self.format,
        }
        if self.output_path:
            result["outputPath"] = self.output_path
        return result


@dataclass
class RenderResult:
    success: bool
    output_path: Optional[str] = None
    duration: Optional[float] = None
    frames: Optional[int] = None
    render_time: Optional[float] = None
    error: Optional[str] = None
    job_id: Optional[str] = None


class RevideoClient:
    """
    HTTP client for Revideo Node.js API server
    """

    def __init__(
        self,
        base_url: str = "http://localhost:3100",
        timeout: float = 300.0,
        auto_start_server: bool = True
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.auto_start_server = auto_start_server
        self._server_process: Optional[subprocess.Popen] = None
        self._client = httpx.AsyncClient(timeout=timeout)

        # Path to Revideo Node.js project
        self.revideo_path = Path(__file__).parent / "revideo"

    async def __aenter__(self):
        if self.auto_start_server:
            await self.ensure_server_running()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        """Close the client and stop server if we started it"""
        await self._client.aclose()
        if self._server_process:
            self._server_process.terminate()
            try:
                self._server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._server_process.kill()
            self._server_process = None

    async def is_server_running(self) -> bool:
        """Check if Revideo server is running"""
        try:
            response = await self._client.get(f"{self.base_url}/health", timeout=2.0)
            return response.status_code == 200
        except Exception:
            return False

    async def ensure_server_running(self) -> bool:
        """Start server if not running"""
        if await self.is_server_running():
            return True

        return await self.start_server()

    async def start_server(self) -> bool:
        """Start the Revideo Node.js server"""
        if self._server_process:
            return True

        # Build first if needed
        dist_path = self.revideo_path / "dist" / "server.js"
        if not dist_path.exists():
            print("Building Revideo server...")
            build_result = subprocess.run(
                ["npm", "run", "build"],
                cwd=str(self.revideo_path),
                capture_output=True,
                text=True,
                shell=True
            )
            if build_result.returncode != 0:
                print(f"Build failed: {build_result.stderr}")
                # Try dev mode instead
                print("Trying dev mode...")
                self._server_process = subprocess.Popen(
                    ["npm", "run", "dev"],
                    cwd=str(self.revideo_path),
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
                )
            else:
                # Start production server
                self._server_process = subprocess.Popen(
                    ["npm", "start"],
                    cwd=str(self.revideo_path),
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
                )
        else:
            self._server_process = subprocess.Popen(
                ["npm", "start"],
                cwd=str(self.revideo_path),
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
            )

        # Wait for server to be ready
        for _ in range(30):
            await asyncio.sleep(1)
            if await self.is_server_running():
                print("Revideo server started successfully")
                return True

        print("Failed to start Revideo server")
        return False

    async def health(self) -> Dict[str, Any]:
        """Check server health"""
        response = await self._client.get(f"{self.base_url}/health")
        response.raise_for_status()
        return response.json()

    async def get_templates(self) -> Dict[str, Any]:
        """Get available templates"""
        response = await self._client.get(f"{self.base_url}/templates")
        response.raise_for_status()
        return response.json()

    async def get_template(self, name: TemplateType) -> Dict[str, Any]:
        """Get specific template configuration"""
        response = await self._client.get(f"{self.base_url}/templates/{name.value}")
        response.raise_for_status()
        return response.json()

    async def render_async(
        self,
        spec: VideoSpec,
        options: Optional[RenderOptions] = None,
        template: Optional[TemplateType] = None
    ) -> str:
        """Start async render job, returns job ID"""
        payload = {
            "spec": spec.to_dict(),
        }
        if options:
            payload["options"] = options.to_dict()
        if template:
            payload["template"] = template.value

        response = await self._client.post(f"{self.base_url}/render", json=payload)
        response.raise_for_status()
        data = response.json()
        return data["jobId"]

    async def render_sync(
        self,
        spec: VideoSpec,
        options: Optional[RenderOptions] = None,
        template: Optional[TemplateType] = None
    ) -> RenderResult:
        """Render video synchronously (blocking)"""
        payload = {
            "spec": spec.to_dict(),
        }
        if options:
            payload["options"] = options.to_dict()
        if template:
            payload["template"] = template.value

        response = await self._client.post(
            f"{self.base_url}/render/sync",
            json=payload,
            timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()

        return RenderResult(
            success=data.get("success", False),
            output_path=data.get("outputPath"),
            duration=data.get("duration"),
            frames=data.get("frames"),
            render_time=data.get("renderTime"),
            error=data.get("error"),
        )

    async def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Get render job status"""
        response = await self._client.get(f"{self.base_url}/jobs/{job_id}")
        response.raise_for_status()
        return response.json()

    async def wait_for_job(
        self,
        job_id: str,
        poll_interval: float = 1.0,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> RenderResult:
        """Wait for async job to complete"""
        while True:
            status = await self.get_job_status(job_id)

            if progress_callback:
                progress_callback(status.get("progress", 0))

            if status["status"] == "completed":
                result = status.get("result", {})
                return RenderResult(
                    success=True,
                    output_path=result.get("outputPath"),
                    duration=result.get("duration"),
                    frames=result.get("frames"),
                    render_time=result.get("renderTime"),
                    job_id=job_id,
                )
            elif status["status"] == "failed":
                return RenderResult(
                    success=False,
                    error=status.get("error"),
                    job_id=job_id,
                )

            await asyncio.sleep(poll_interval)

    async def render_subtitles_video(
        self,
        video_src: str,
        subtitles: List[Dict[str, Any]],
        template: TemplateType = TemplateType.SHORTS_VERTICAL,
        output_path: Optional[str] = None
    ) -> RenderResult:
        """Quick render for subtitles overlay on video"""
        payload = {
            "videoSrc": video_src,
            "subtitles": subtitles,
            "template": template.value,
        }
        if output_path:
            payload["outputPath"] = output_path

        response = await self._client.post(
            f"{self.base_url}/render/subtitles",
            json=payload,
            timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()

        return RenderResult(
            success=data.get("success", False),
            output_path=data.get("outputPath"),
            duration=data.get("duration"),
            frames=data.get("frames"),
            render_time=data.get("renderTime"),
            error=data.get("error"),
        )

    async def generate_preview(
        self,
        spec: VideoSpec,
        time: float = 0.0,
        template: Optional[TemplateType] = None
    ) -> Dict[str, Any]:
        """Generate preview frame at specific time"""
        payload = {
            "spec": spec.to_dict(),
            "time": time,
        }
        if template:
            payload["template"] = template.value

        response = await self._client.post(f"{self.base_url}/preview", json=payload)
        response.raise_for_status()
        return response.json()

    async def compose_spec(
        self,
        video: Optional[str] = None,
        subtitles: Optional[List[Dict[str, Any]]] = None,
        template: TemplateType = TemplateType.SHORTS_VERTICAL,
        duration: float = 30.0
    ) -> VideoSpec:
        """Compose VideoSpec from simple inputs"""
        payload = {
            "video": video,
            "subtitles": subtitles or [],
            "template": template.value,
            "duration": duration,
        }

        response = await self._client.post(f"{self.base_url}/compose", json=payload)
        response.raise_for_status()
        data = response.json()

        # Convert response to VideoSpec
        clips = []
        for clip_data in data.get("clips", []):
            clips.append(ClipSpec(
                id=clip_data["id"],
                type=clip_data["type"],
                src=clip_data.get("src"),
                start=clip_data["start"],
                end=clip_data["end"],
            ))

        subs = []
        for sub_data in data.get("subtitles", []):
            style_data = sub_data.get("style", {})
            style = SubtitleStyle(
                font_family=style_data.get("fontFamily", "Arial Black"),
                font_size=style_data.get("fontSize", 72),
                font_weight=style_data.get("fontWeight", 900),
                color=style_data.get("color", "#FFFFFF"),
                background_color=style_data.get("backgroundColor"),
                background_padding=style_data.get("backgroundPadding", 16),
                border_radius=style_data.get("borderRadius", 8),
                text_align=style_data.get("textAlign", "center"),
                position=style_data.get("position", "center"),
            )

            anim_data = sub_data.get("animation", {})
            animation = SubtitleAnimation(
                type=AnimationType(anim_data.get("type", "pop")),
                duration=anim_data.get("duration", 0.3),
            )

            subs.append(SubtitleSpec(
                id=sub_data["id"],
                text=sub_data["text"],
                start=sub_data["start"],
                end=sub_data["end"],
                style=style,
                animation=animation,
            ))

        return VideoSpec(
            id=data["id"],
            width=data["width"],
            height=data["height"],
            fps=data["fps"],
            duration=data["duration"],
            background=data.get("background", "#000000"),
            clips=clips,
            subtitles=subs,
        )


# Convenience functions for synchronous usage
def render_video_sync(
    spec: VideoSpec,
    options: Optional[RenderOptions] = None,
    template: Optional[TemplateType] = None,
    base_url: str = "http://localhost:3100"
) -> RenderResult:
    """Synchronous wrapper for rendering video"""
    async def _render():
        async with RevideoClient(base_url=base_url) as client:
            return await client.render_sync(spec, options, template)

    return asyncio.run(_render())


def render_subtitles_sync(
    video_src: str,
    subtitles: List[Dict[str, Any]],
    template: TemplateType = TemplateType.SHORTS_VERTICAL,
    output_path: Optional[str] = None,
    base_url: str = "http://localhost:3100"
) -> RenderResult:
    """Synchronous wrapper for subtitle video rendering"""
    async def _render():
        async with RevideoClient(base_url=base_url) as client:
            return await client.render_subtitles_video(
                video_src, subtitles, template, output_path
            )

    return asyncio.run(_render())
