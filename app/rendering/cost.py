"""
Cost & Usage Tracking Module.
Calculates render costs based on resource consumption.
"""
import os
import logging
from typing import Optional
from dataclasses import dataclass

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class CostConfig:
    """
    Cost configuration loaded from environment variables.
    All costs in USD.
    """

    def __init__(self):
        self.cpu_cost_per_second: float = float(
            os.getenv("CPU_COST_PER_SECOND", "0.0005")
        )
        self.storage_cost_per_mb: float = float(
            os.getenv("STORAGE_COST_PER_MB", "0.00002")
        )
        self.gpu_cost_per_second: float = float(
            os.getenv("GPU_COST_PER_SECOND", "0.002")
        )
        self.bandwidth_cost_per_mb: float = float(
            os.getenv("BANDWIDTH_COST_PER_MB", "0.00001")
        )

        logger.info(
            f"CostConfig loaded: CPU=${self.cpu_cost_per_second}/s, "
            f"Storage=${self.storage_cost_per_mb}/MB, "
            f"GPU=${self.gpu_cost_per_second}/s"
        )

    def reload(self) -> None:
        """Reload configuration from environment."""
        self.__init__()


class UsageMetrics(BaseModel):
    """
    Resource usage metrics for a render job.
    """
    render_time_seconds: float = Field(..., ge=0, description="Actual render time")
    video_duration_seconds: float = Field(..., ge=0, description="Output video duration")
    scenes_count: int = Field(..., ge=0, description="Number of scenes rendered")
    resolution: str = Field(..., description="Video resolution (WxH)")
    width: int = Field(..., ge=1, description="Video width in pixels")
    height: int = Field(..., ge=1, description="Video height in pixels")
    fps: int = Field(..., ge=1, description="Frames per second")
    output_size_mb: Optional[float] = Field(default=None, ge=0, description="Output file size in MB")
    total_frames: int = Field(default=0, ge=0, description="Total frames rendered")

    @classmethod
    def create(
        cls,
        render_time_seconds: float,
        video_duration_seconds: float,
        scenes_count: int,
        width: int,
        height: int,
        fps: int,
        output_size_mb: Optional[float] = None,
    ) -> "UsageMetrics":
        total_frames = int(video_duration_seconds * fps)

        return cls(
            render_time_seconds=render_time_seconds,
            video_duration_seconds=video_duration_seconds,
            scenes_count=scenes_count,
            resolution=f"{width}x{height}",
            width=width,
            height=height,
            fps=fps,
            output_size_mb=output_size_mb,
            total_frames=total_frames,
        )


class RenderCostBreakdown(BaseModel):
    """
    Detailed cost breakdown for a render job.
    All values in USD.
    """
    cpu_cost_usd: float = Field(..., ge=0, description="CPU compute cost")
    storage_cost_usd: float = Field(..., ge=0, description="Storage cost for output file")
    gpu_cost_usd: float = Field(default=0.0, ge=0, description="GPU compute cost (if applicable)")
    bandwidth_cost_usd: float = Field(default=0.0, ge=0, description="Bandwidth cost (if applicable)")
    total_cost_usd: float = Field(..., ge=0, description="Total cost")

    cost_per_second_video: float = Field(default=0.0, ge=0, description="Cost per second of output video")
    cost_per_frame: float = Field(default=0.0, ge=0, description="Cost per rendered frame")

    currency: str = Field(default="USD", description="Currency code")

    @classmethod
    def create(
        cls,
        cpu_cost_usd: float,
        storage_cost_usd: float,
        gpu_cost_usd: float = 0.0,
        bandwidth_cost_usd: float = 0.0,
        video_duration_seconds: float = 0.0,
        total_frames: int = 0,
    ) -> "RenderCostBreakdown":
        total_cost = cpu_cost_usd + storage_cost_usd + gpu_cost_usd + bandwidth_cost_usd

        cost_per_second = total_cost / video_duration_seconds if video_duration_seconds > 0 else 0.0
        cost_per_frame = total_cost / total_frames if total_frames > 0 else 0.0

        return cls(
            cpu_cost_usd=round(cpu_cost_usd, 6),
            storage_cost_usd=round(storage_cost_usd, 6),
            gpu_cost_usd=round(gpu_cost_usd, 6),
            bandwidth_cost_usd=round(bandwidth_cost_usd, 6),
            total_cost_usd=round(total_cost, 6),
            cost_per_second_video=round(cost_per_second, 6),
            cost_per_frame=round(cost_per_frame, 8),
        )


class CostCalculator:
    """
    Calculates render costs based on usage metrics.
    Thread-safe, stateless calculator.
    """

    def __init__(self, config: Optional[CostConfig] = None):
        self.config = config or CostConfig()

    def calculate(
        self,
        usage_metrics: UsageMetrics,
        include_gpu: bool = False,
        include_bandwidth: bool = False,
    ) -> RenderCostBreakdown:
        """
        Calculate cost breakdown from usage metrics.

        Args:
            usage_metrics: Resource usage metrics
            include_gpu: Include GPU costs (for future GPU-accelerated rendering)
            include_bandwidth: Include bandwidth costs (for CDN delivery)

        Returns:
            RenderCostBreakdown with detailed costs
        """
        cpu_cost = usage_metrics.render_time_seconds * self.config.cpu_cost_per_second

        storage_cost = 0.0
        if usage_metrics.output_size_mb is not None:
            storage_cost = usage_metrics.output_size_mb * self.config.storage_cost_per_mb

        gpu_cost = 0.0
        if include_gpu:
            gpu_cost = usage_metrics.render_time_seconds * self.config.gpu_cost_per_second

        bandwidth_cost = 0.0
        if include_bandwidth and usage_metrics.output_size_mb is not None:
            bandwidth_cost = usage_metrics.output_size_mb * self.config.bandwidth_cost_per_mb

        breakdown = RenderCostBreakdown.create(
            cpu_cost_usd=cpu_cost,
            storage_cost_usd=storage_cost,
            gpu_cost_usd=gpu_cost,
            bandwidth_cost_usd=bandwidth_cost,
            video_duration_seconds=usage_metrics.video_duration_seconds,
            total_frames=usage_metrics.total_frames,
        )

        logger.info(
            f"Cost calculated: total=${breakdown.total_cost_usd:.6f} "
            f"(CPU=${breakdown.cpu_cost_usd:.6f}, Storage=${breakdown.storage_cost_usd:.6f})"
        )

        return breakdown

    def calculate_partial(
        self,
        render_time_seconds: float,
        output_size_mb: Optional[float] = None,
    ) -> RenderCostBreakdown:
        """
        Calculate partial cost for failed renders.
        Uses minimal metrics available.
        """
        cpu_cost = render_time_seconds * self.config.cpu_cost_per_second

        storage_cost = 0.0
        if output_size_mb is not None:
            storage_cost = output_size_mb * self.config.storage_cost_per_mb

        return RenderCostBreakdown.create(
            cpu_cost_usd=cpu_cost,
            storage_cost_usd=storage_cost,
        )

    def estimate(
        self,
        video_duration_seconds: float,
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
        complexity_factor: float = 1.0,
    ) -> RenderCostBreakdown:
        """
        Estimate cost before rendering.
        Useful for quotations.

        Args:
            video_duration_seconds: Expected video duration
            width: Video width
            height: Video height
            fps: Frames per second
            complexity_factor: Multiplier for complex renders (1.0 = normal)

        Returns:
            Estimated RenderCostBreakdown
        """
        pixels = width * height
        base_pixels = 1080 * 1920

        pixel_factor = pixels / base_pixels
        fps_factor = fps / 30.0

        estimated_render_time = (
            video_duration_seconds *
            pixel_factor *
            fps_factor *
            complexity_factor *
            2.0
        )

        estimated_size_mb = (
            video_duration_seconds *
            (8.0 / 8.0) *
            pixel_factor *
            fps_factor
        )

        cpu_cost = estimated_render_time * self.config.cpu_cost_per_second
        storage_cost = estimated_size_mb * self.config.storage_cost_per_mb

        return RenderCostBreakdown.create(
            cpu_cost_usd=cpu_cost,
            storage_cost_usd=storage_cost,
            video_duration_seconds=video_duration_seconds,
            total_frames=int(video_duration_seconds * fps),
        )


_default_calculator: Optional[CostCalculator] = None


def get_cost_calculator() -> CostCalculator:
    """Get or create default CostCalculator instance."""
    global _default_calculator
    if _default_calculator is None:
        _default_calculator = CostCalculator()
    return _default_calculator


def calculate_render_cost(
    render_time_seconds: float,
    video_duration_seconds: float,
    scenes_count: int,
    width: int,
    height: int,
    fps: int,
    output_size_mb: Optional[float] = None,
) -> tuple[UsageMetrics, RenderCostBreakdown]:
    """
    Convenience function to calculate cost from raw values.

    Returns:
        Tuple of (UsageMetrics, RenderCostBreakdown)
    """
    calculator = get_cost_calculator()

    usage = UsageMetrics.create(
        render_time_seconds=render_time_seconds,
        video_duration_seconds=video_duration_seconds,
        scenes_count=scenes_count,
        width=width,
        height=height,
        fps=fps,
        output_size_mb=output_size_mb,
    )

    breakdown = calculator.calculate(usage)

    return usage, breakdown
