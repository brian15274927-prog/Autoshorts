"""
Nano Banana Service - Google Gemini Image Generation for Faceless Videos.
Generates cinematic visuals using Google's Gemini image models.

Models:
- gemini-2.0-flash-exp: Fast, cheap (~$0.039/image)
- imagen-3.0-generate-002: Higher quality

Pricing: ~$0.039 per image (1290 output tokens * $30/1M)
"""
import sys
import asyncio

# CRITICAL: Windows asyncio fix
if sys.platform == 'win32':
    try:
        from asyncio import WindowsProactorEventLoopPolicy
        asyncio.set_event_loop_policy(WindowsProactorEventLoopPolicy())
    except (ImportError, AttributeError):
        pass

import os
import logging
import httpx
import uuid
import base64
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Output directory for generated images
NANOBANANA_OUTPUT_DIR = Path(r"C:\dake\data\temp_images")
NANOBANANA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


class NanoBananaError(Exception):
    """Base exception for Nano Banana service errors."""
    pass


class NanoBananaBillingError(NanoBananaError):
    """Raised when Google API returns a billing-related error."""
    pass


class NanoBananaContentPolicyError(NanoBananaError):
    """Raised when Gemini rejects a prompt due to content policy."""
    pass


@dataclass
class GeneratedImage:
    """Generated image metadata - same structure as DalleService for compatibility."""
    image_path: str
    prompt: str
    revised_prompt: str
    width: int
    height: int
    segment_index: int


class NanoBananaService:
    """
    Nano Banana (Google Gemini) Image Generation Service.

    Uses Gemini's image generation capabilities as an alternative to DALL-E.
    Compatible interface with DalleService for easy switching.
    """

    # Google AI API endpoint for Gemini
    GOOGLE_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    # Available models
    MODELS = {
        "flash": "gemini-2.0-flash-exp",  # Fast, supports image generation
        "imagen": "imagen-3.0-generate-002",  # High quality image generation
    }

    def __init__(self, api_key: Optional[str] = None, model: str = "flash"):
        """
        Initialize Nano Banana service.

        Args:
            api_key: Google API key
            model: Model to use - "flash" or "imagen"
        """
        from app.config import config
        self.api_key = api_key or config.ai.google_api_key or ""
        self.model_name = self.MODELS.get(model, self.MODELS["flash"])
        self.client = httpx.AsyncClient(timeout=120.0)

        if not self.api_key:
            logger.warning("[NANOBANANA] No Google API key - image generation disabled")
        else:
            logger.info(f"[NANOBANANA] Initialized with model: {self.model_name}")

    async def generate_image(
        self,
        prompt: str,
        output_path: Optional[str] = None,
        size: str = "1024x1024",
        quality: str = "standard",
        style: str = "vivid"
    ) -> Optional[GeneratedImage]:
        """
        Generate a single image using Google Gemini.

        Args:
            prompt: The image generation prompt
            output_path: Optional path to save the image
            size: Image size (ignored for Gemini, uses default)
            quality: Quality setting (ignored for Gemini)
            style: Style setting (incorporated into prompt)

        Returns:
            GeneratedImage with path and metadata, or None on failure
        """
        if not self.api_key:
            logger.warning("[NANOBANANA] No API key - skipping generation")
            return None

        if output_path is None:
            output_path = str(NANOBANANA_OUTPUT_DIR / f"{uuid.uuid4()}.png")

        try:
            logger.info(f"[NANOBANANA] Generating image: {prompt[:100]}...")

            # Use Gemini API for image generation
            url = f"{self.GOOGLE_API_URL}/{self.model_name}:generateContent?key={self.api_key}"

            # Parse size for aspect ratio hint and resolution
            aspect_hint = ""
            width_hint = 1024
            height_hint = 1024
            
            if "1792" in size or "9:16" in size or "x1920" in size:
                aspect_hint = "VERTICAL portrait orientation (9:16 aspect ratio), 1080x1920 resolution, "
                width_hint = 1080
                height_hint = 1920
            elif "1024x1792" in size:
                aspect_hint = "VERTICAL portrait orientation (9:16 aspect ratio), 1024x1792 resolution, "
                width_hint = 1024
                height_hint = 1792
            elif "1792x1024" in size or "16:9" in size:
                aspect_hint = "horizontal landscape orientation (16:9 aspect ratio), "
                width_hint = 1792
                height_hint = 1024

            # Enhanced prompt for better image generation with STRICT formatting
            enhanced_prompt = f"{aspect_hint}Generate a high-quality cinematic image: {prompt}"
            if style == "vivid":
                enhanced_prompt += " Make it vibrant and visually striking."
            
            logger.info(f"[NANOBANANA] Target resolution: {width_hint}x{height_hint}")

            # Gemini 2.0 Flash requires specific format for image generation
            payload = {
                "contents": [{
                    "parts": [{
                        "text": f"Generate an image: {enhanced_prompt}"
                    }]
                }],
                "generationConfig": {
                    "responseModalities": ["image", "text"]
                }
            }

            response = await self.client.post(url, json=payload)

            if response.status_code == 400:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", "Unknown error")

                if "billing" in error_msg.lower() or "quota" in error_msg.lower():
                    raise NanoBananaBillingError(f"Billing error: {error_msg}")
                elif "safety" in error_msg.lower() or "blocked" in error_msg.lower():
                    raise NanoBananaContentPolicyError(f"Content blocked: {error_msg}")
                else:
                    logger.error(f"[NANOBANANA] API error 400: {error_msg}")
                    return None

            if response.status_code != 200:
                logger.error(f"[NANOBANANA] API error {response.status_code}: {response.text[:500]}")
                return None

            data = response.json()

            # Extract image from response
            candidates = data.get("candidates", [])
            if not candidates:
                logger.error("[NANOBANANA] No candidates in response")
                return None

            parts = candidates[0].get("content", {}).get("parts", [])

            image_data = None
            for part in parts:
                if "inlineData" in part:
                    image_data = part["inlineData"].get("data")
                    break

            if not image_data:
                # Try alternative response format
                logger.warning("[NANOBANANA] No image data in response, trying text-to-image fallback")
                return None

            # Decode and save image
            image_bytes = base64.b64decode(image_data)

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(image_bytes)

            logger.info(f"[NANOBANANA] Image saved: {output_path}")

            return GeneratedImage(
                image_path=output_path,
                prompt=prompt,
                revised_prompt=enhanced_prompt,
                width=width_hint,
                height=height_hint,
                segment_index=0
            )

        except NanoBananaBillingError:
            raise
        except NanoBananaContentPolicyError:
            raise
        except Exception as e:
            logger.error(f"[NANOBANANA] Generation failed: {e}")
            return None

    async def generate_images_for_segments(
        self,
        segments: List[Dict[str, Any]],
        visual_prompts: List[str],
        output_dir: Optional[str] = None,
        video_format: str = "9:16",
        topic: str = ""
    ) -> List[GeneratedImage]:
        """
        Generate images for multiple script segments.

        Args:
            segments: List of script segments
            visual_prompts: List of prompts for each segment
            output_dir: Output directory for images
            video_format: Video aspect ratio
            topic: Video topic (used for fallback)

        Returns:
            List of GeneratedImage objects
        """
        if output_dir is None:
            output_dir = str(NANOBANANA_OUTPUT_DIR / str(uuid.uuid4()))

        os.makedirs(output_dir, exist_ok=True)

        images = []
        api_calls = 0

        logger.info(f"[NANOBANANA] Generating {len(visual_prompts)} images...")

        for idx, prompt in enumerate(visual_prompts):
            output_path = os.path.join(output_dir, f"segment_{idx:03d}.png")

            try:
                image = await self.generate_image(
                    prompt=prompt,
                    output_path=output_path
                )

                if image:
                    image.segment_index = idx
                    images.append(image)
                    api_calls += 1
                else:
                    # Use fallback
                    fallback = self._create_fallback_image(output_path, idx, topic)
                    images.append(fallback)

            except NanoBananaBillingError as e:
                logger.critical(f"[NANOBANANA] Billing error - stopping: {e}")
                # Fill remaining with fallbacks
                for remaining_idx in range(idx, len(visual_prompts)):
                    fallback_path = os.path.join(output_dir, f"segment_{remaining_idx:03d}.png")
                    fallback = self._create_fallback_image(fallback_path, remaining_idx, topic)
                    images.append(fallback)
                break

            except NanoBananaContentPolicyError as e:
                logger.warning(f"[NANOBANANA] Content blocked for segment {idx}: {e}")
                fallback = self._create_fallback_image(output_path, idx, topic)
                images.append(fallback)

        # Cost estimate
        estimated_cost = api_calls * 0.039  # ~$0.039 per image
        logger.info(f"[NANOBANANA] Generated {api_calls} images, estimated cost: ${estimated_cost:.3f}")

        return images

    def _create_fallback_image(
        self,
        output_path: str,
        segment_index: int,
        topic: str
    ) -> GeneratedImage:
        """Create a fallback placeholder image."""
        # Create a simple solid color PNG fallback
        self._create_solid_color_png(output_path, 1024, 1024)

        return GeneratedImage(
            image_path=output_path,
            prompt=f"Fallback for: {topic}",
            revised_prompt="Fallback image",
            width=1024,
            height=1024,
            segment_index=segment_index
        )

    def _create_solid_color_png(self, output_path: str, width: int, height: int):
        """Create a minimal solid color PNG image."""
        import struct
        import zlib

        # Dark purple/blue gradient color
        r, g, b = 30, 20, 50

        def create_png(w, h, r, g, b):
            def chunk(chunk_type, data):
                c = chunk_type + data
                return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)

            # PNG signature
            sig = b'\x89PNG\r\n\x1a\n'

            # IHDR chunk
            ihdr_data = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
            ihdr = chunk(b'IHDR', ihdr_data)

            # IDAT chunk (image data)
            raw_data = b''
            for _ in range(h):
                raw_data += b'\x00'  # filter byte
                raw_data += bytes([r, g, b]) * w
            compressed = zlib.compress(raw_data, 9)
            idat = chunk(b'IDAT', compressed)

            # IEND chunk
            iend = chunk(b'IEND', b'')

            return sig + ihdr + idat + iend

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        png_data = create_png(width, height, r, g, b)
        with open(output_path, 'wb') as f:
            f.write(png_data)

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
        logger.info("[NANOBANANA] Service closed")


# ═══════════════════════════════════════════════════════════════════════════════
# Factory function for creating image generation service
# ═══════════════════════════════════════════════════════════════════════════════

def get_image_service(provider: str = "dalle"):
    """
    Factory function to get the appropriate image generation service.

    Args:
        provider: "dalle" or "nanobanana"

    Returns:
        DalleService or NanoBananaService instance
    """
    if provider == "nanobanana":
        return NanoBananaService()
    else:
        from .dalle_service import DalleService
        return DalleService()
