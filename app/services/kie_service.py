"""
Kie Image Generation Service - Uses Kie.ai API for Nano Banana (Gemini 2.5 Flash) image generation.

API: https://api.kie.ai
Model: google/nano-banana
"""
import os
import asyncio
import logging
import httpx
import uuid
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from app.config import config

logger = logging.getLogger(__name__)

# Output directory for generated images
KIE_OUTPUT_DIR = config.paths.temp_images_dir


class KieError(Exception):
    """Base exception for Kie service errors."""
    pass


class KieBillingError(KieError):
    """Raised when Kie API returns a billing-related error."""
    pass


class KieContentPolicyError(KieError):
    """Raised when Kie rejects a prompt due to content policy."""
    pass


class KieAuthError(KieError):
    """Raised when Kie API key is invalid."""
    pass


class KieTimeoutError(KieError):
    """Raised when Kie task times out."""
    pass


@dataclass
class GeneratedImage:
    """Generated image metadata - compatible with DalleService and NanoBananaService."""
    image_path: str
    prompt: str
    revised_prompt: str
    width: int
    height: int
    segment_index: int


class KieService:
    """
    Kie.ai Image Generation Service using Nano Banana model.

    Uses async task-based API:
    1. Create task -> get taskId
    2. Poll for completion
    3. Download image
    """

    BASE_URL = "https://api.kie.ai"
    MODEL = "google/nano-banana"

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Kie service.

        Args:
            api_key: Kie API key (falls back to config)
        """
        from app.config import config
        self.api_key = api_key or config.ai.kie_api_key or ""
        self.client = httpx.AsyncClient(timeout=60.0)

        if not self.api_key:
            logger.warning("[KIE] No API key configured - image generation disabled")
        else:
            logger.info(f"[KIE] Initialized with Nano Banana model")

    def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers."""
        return {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

    async def generate_image(
        self,
        prompt: str,
        output_path: Optional[str] = None,
        size: str = "9:16",
        quality: str = "standard",
        style: str = "vivid"
    ) -> Optional[GeneratedImage]:
        """
        Generate a single image using Kie.ai Nano Banana.

        Args:
            prompt: The image generation prompt
            output_path: Optional path to save the image
            size: Image aspect ratio (9:16, 16:9, 1:1)
            quality: Quality setting (ignored, for compatibility)
            style: Style setting (incorporated into prompt)

        Returns:
            GeneratedImage with path and metadata, or None on failure
        """
        if not self.api_key:
            logger.warning("[KIE] No API key - skipping generation")
            return None

        if output_path is None:
            output_path = str(KIE_OUTPUT_DIR / f"{uuid.uuid4()}.png")

        try:
            logger.info(f"[KIE] Generating image: {prompt[:100]}...")

            # Enhance prompt
            enhanced_prompt = prompt
            if style == "vivid":
                enhanced_prompt += ", cinematic composition, high quality, vibrant colors"

            # Create task
            create_url = f"{self.BASE_URL}/api/v1/playground/createTask"

            data = {
                "model": self.MODEL,
                "input": {
                    "prompt": enhanced_prompt,
                    "output_format": "png",
                    "image_size": size
                }
            }

            response = await self.client.post(
                create_url,
                headers=self._get_headers(),
                json=data
            )

            # Handle auth errors
            if response.status_code == 401 or response.status_code == 403:
                raise KieAuthError("Invalid API key")

            response.raise_for_status()
            result = response.json()

            if result.get('code') != 200:
                error_msg = result.get('msg', 'Unknown error')
                if 'billing' in error_msg.lower() or 'quota' in error_msg.lower() or 'balance' in error_msg.lower():
                    raise KieBillingError(f"Billing error: {error_msg}")
                elif 'safety' in error_msg.lower() or 'blocked' in error_msg.lower() or 'content' in error_msg.lower():
                    raise KieContentPolicyError(f"Content blocked: {error_msg}")
                else:
                    logger.error(f"[KIE] API error: {error_msg}")
                    return None

            task_id = result.get('data', {}).get('taskId')
            if not task_id:
                logger.error(f"[KIE] No task ID in response: {result}")
                return None

            logger.info(f"[KIE] Task created: {task_id}")

            # Poll for completion
            image_url = await self._poll_for_completion(task_id)

            # Download image
            await self._download_image(image_url, output_path)

            # Parse dimensions from size
            width, height = self._parse_size(size)

            logger.info(f"[KIE] Image saved: {output_path}")

            return GeneratedImage(
                image_path=output_path,
                prompt=prompt,
                revised_prompt=enhanced_prompt,
                width=width,
                height=height,
                segment_index=0
            )

        except KieAuthError:
            raise
        except KieBillingError:
            raise
        except KieContentPolicyError:
            raise
        except KieTimeoutError:
            raise
        except Exception as e:
            logger.error(f"[KIE] Generation failed: {e}")
            return None

    async def _poll_for_completion(self, task_id: str, max_wait: int = 120) -> str:
        """Poll for task completion and return image URL."""
        url = f"{self.BASE_URL}/api/v1/playground/recordInfo"
        headers = {'Authorization': f'Bearer {self.api_key}'}

        for i in range(max_wait // 3):
            response = await self.client.get(
                url,
                headers=headers,
                params={'taskId': task_id}
            )
            response.raise_for_status()
            result = response.json()

            if result.get('code') != 200:
                raise KieError(f"Query error: {result.get('msg')}")

            data = result.get('data', {})
            state = data.get('state', '').lower()

            if state in ['completed', 'success']:
                image_url = None

                # Parse resultJson field
                result_json_str = data.get('resultJson')
                if result_json_str:
                    try:
                        result_json = json.loads(result_json_str)
                        result_urls = result_json.get('resultUrls', [])
                        if result_urls and len(result_urls) > 0:
                            image_url = result_urls[0]
                    except (json.JSONDecodeError, TypeError):
                        pass

                # Fallback: try other fields
                if not image_url:
                    image_url = (
                        data.get('imageUrl') or
                        data.get('image_url') or
                        data.get('output', {}).get('imageUrl') or
                        data.get('output', {}).get('image_url')
                    )

                # Check if output is a list
                if not image_url:
                    output = data.get('output')
                    if isinstance(output, list) and len(output) > 0:
                        image_url = output[0].get('url') or output[0].get('imageUrl')

                if image_url:
                    logger.info(f"[KIE] Image ready: {image_url[:60]}...")
                    return image_url

                raise KieError(f"Completed but no image URL found in: {data}")

            if state == 'failed':
                error = data.get('failMsg') or data.get('error') or 'Unknown error'
                if 'content' in error.lower() or 'safety' in error.lower():
                    raise KieContentPolicyError(f"Content blocked: {error}")
                raise KieError(f"Image generation failed: {error}")

            logger.debug(f"[KIE] Polling task {task_id}: {state} (attempt {i+1})")
            await asyncio.sleep(3)

        raise KieTimeoutError(f"Task {task_id} timed out after {max_wait}s")

    async def _download_image(self, url: str, output_path: str):
        """Download image from URL."""
        response = await self.client.get(url)
        response.raise_for_status()

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'wb') as f:
            f.write(response.content)

        logger.info(f"[KIE] Image downloaded: {output_path}")

    def _parse_size(self, size: str) -> tuple:
        """Parse size string to width/height."""
        if size == "9:16":
            return 1080, 1920
        elif size == "16:9":
            return 1920, 1080
        elif size == "1:1":
            return 1024, 1024
        elif "1024x1792" in size or "1792" in size:
            return 1024, 1792
        elif "1792x1024" in size:
            return 1792, 1024
        else:
            return 1024, 1024

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
            output_dir = str(KIE_OUTPUT_DIR / str(uuid.uuid4()))

        os.makedirs(output_dir, exist_ok=True)

        images = []
        api_calls = 0

        # Map video format to Kie size
        size_map = {
            "9:16": "9:16",
            "16:9": "16:9",
            "1:1": "1:1"
        }
        size = size_map.get(video_format, "9:16")

        logger.info(f"[KIE] Generating {len(visual_prompts)} images...")

        for idx, prompt in enumerate(visual_prompts):
            output_path = os.path.join(output_dir, f"segment_{idx:03d}.png")

            try:
                image = await self.generate_image(
                    prompt=prompt,
                    output_path=output_path,
                    size=size
                )

                if image:
                    image.segment_index = idx
                    images.append(image)
                    api_calls += 1
                else:
                    fallback = self._create_fallback_image(output_path, idx, topic)
                    images.append(fallback)

            except KieBillingError as e:
                logger.critical(f"[KIE] Billing error - stopping: {e}")
                for remaining_idx in range(idx, len(visual_prompts)):
                    fallback_path = os.path.join(output_dir, f"segment_{remaining_idx:03d}.png")
                    fallback = self._create_fallback_image(fallback_path, remaining_idx, topic)
                    images.append(fallback)
                break

            except KieContentPolicyError as e:
                logger.warning(f"[KIE] Content blocked for segment {idx}: {e}")
                fallback = self._create_fallback_image(output_path, idx, topic)
                images.append(fallback)

            except KieAuthError as e:
                logger.error(f"[KIE] Auth failed: {e}")
                for remaining_idx in range(idx, len(visual_prompts)):
                    fallback_path = os.path.join(output_dir, f"segment_{remaining_idx:03d}.png")
                    fallback = self._create_fallback_image(fallback_path, remaining_idx, topic)
                    images.append(fallback)
                break

            except KieTimeoutError as e:
                logger.warning(f"[KIE] Timeout for segment {idx}: {e}")
                fallback = self._create_fallback_image(output_path, idx, topic)
                images.append(fallback)

        logger.info(f"[KIE] Generated {api_calls} images via Kie.ai")

        return images

    def _create_fallback_image(
        self,
        output_path: str,
        segment_index: int,
        topic: str
    ) -> GeneratedImage:
        """Create a fallback placeholder image."""
        self._create_solid_color_png(output_path, 1080, 1920)

        return GeneratedImage(
            image_path=output_path,
            prompt=f"Fallback for: {topic}",
            revised_prompt="Fallback image",
            width=1080,
            height=1920,
            segment_index=segment_index
        )

    def _create_solid_color_png(self, output_path: str, width: int, height: int):
        """Create a minimal solid color PNG image."""
        import struct
        import zlib

        r, g, b = 25, 35, 60

        def create_png(w, h, r, g, b):
            def chunk(chunk_type, data):
                c = chunk_type + data
                return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)

            sig = b'\x89PNG\r\n\x1a\n'
            ihdr_data = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
            ihdr = chunk(b'IHDR', ihdr_data)

            raw_data = b''
            for _ in range(h):
                raw_data += b'\x00'
                raw_data += bytes([r, g, b]) * w
            compressed = zlib.compress(raw_data, 9)
            idat = chunk(b'IDAT', compressed)
            iend = chunk(b'IEND', b'')

            return sig + ihdr + idat + iend

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        png_data = create_png(width, height, r, g, b)
        with open(output_path, 'wb') as f:
            f.write(png_data)

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
        logger.info("[KIE] Service closed")
