"""
Fast Script Generator - Single GPT request for complete script generation.
Replaces the slow multi-agent system with a single optimized prompt.

Performance: ~5-10 seconds vs ~80 seconds (8x faster!)
"""
import json
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from openai import AsyncOpenAI

from app.config import config

logger = logging.getLogger(__name__)


# Art style descriptions for visual prompts
ART_STYLE_PROMPTS = {
    "photorealism": "hyper-realistic 8K photograph, natural lighting, cinematic composition, professional photography",
    "anime": "anime style, vibrant colors, detailed eyes, Japanese animation aesthetic, Studio Ghibli inspired",
    "ghibli": "Studio Ghibli style, magical atmosphere, soft colors, whimsical, hand-painted aesthetic",
    "disney": "Disney Pixar 3D animation style, expressive characters, vibrant colors, family-friendly",
    "comic": "comic book style, bold outlines, dynamic composition, halftone dots, vibrant panels",
    "watercolor": "soft watercolor painting, flowing colors, artistic brushstrokes, dreamy atmosphere",
    "pixel": "pixel art, retro gaming aesthetic, 8-bit style, nostalgic, clean pixels",
    "creepy": "dark and moody, gothic atmosphere, mysterious shadows, dramatic horror lighting",
    "minecraft": "Minecraft voxel style, blocky 3D world, colorful blocks, game aesthetic",
    "expressionism": "abstract expressionism, bold colors, emotional intensity, artistic brushwork",
}

# Style descriptions for script tone
STYLE_DESCRIPTIONS = {
    "viral": "engaging, hook-driven, surprising facts, emotional triggers, shareable content",
    "documentary": "informative, factual, educational, professional narration, NatGeo style",
    "storytelling": "narrative arc, characters, conflict, resolution, emotional journey",
    "motivational": "inspiring, uplifting, call to action, personal growth, empowering",
    "educational": "clear explanations, step-by-step, informative, teaching style",
}


FAST_SCRIPT_PROMPT = '''You are an expert video scriptwriter for short vertical videos (TikTok/Reels/Shorts).

Create a complete video script on topic: "{topic}"

REQUIREMENTS:
- Total duration: {duration} seconds
- Language: {language_name}
- Style: {style_desc}
- Visual style: {art_style_desc}

CRITICAL TEXT LENGTH REQUIREMENTS:
- Total word count: approximately {word_count} words (2.5 words per second × {duration} seconds)
- Each segment MUST have enough text for its duration
- 5-second segment = ~12-15 words of narration
- 10-second segment = ~25-30 words of narration
- DO NOT make short 1-2 sentence segments - expand with details, examples, facts!

RESPONSE FORMAT (strict JSON):
{{
    "title": "Catchy video title in {language_name}",
    "hook": "First sentence that hooks viewers (must grab attention!)",
    "cta": "Call to action at the end",
    "background_music_mood": "energetic/calm/dramatic/inspirational/mysterious",
    "visual_keywords": ["keyword1", "keyword2", "keyword3"],
    "segments": [
        {{
            "text": "Narration text for this segment in {language_name} (MUST be 12-30 words!)",
            "duration": 5,
            "visual_prompt": "Detailed visual description in ENGLISH for image generation",
            "emotion": "neutral/excited/serious/mysterious/happy",
            "camera_direction": "static/zoom_in/zoom_out/pan_left/pan_right"
        }}
    ]
}}

RULES:
1. Create {segment_count} segments for {duration} seconds video
2. Each segment text MUST be 12-30 words - NO SHORT SENTENCES!
3. Sum of all segment durations MUST equal {duration} seconds
4. visual_prompt MUST be in ENGLISH, describe concrete photographable scene
5. visual_prompt MUST include: "{art_style_desc}"
6. NO abstract concepts in visual_prompt - only concrete objects/scenes
7. Narration in {language_name}, visual_prompt in English

VISUAL PROMPT EXAMPLES:
BAD: "Symbol of success and growth"
GOOD: "{art_style_desc}, businessman in suit standing on mountain peak, golden sunset, dramatic clouds, wide shot"

BAD: "Visualization of technology"
GOOD: "{art_style_desc}, close-up of hands typing on glowing keyboard, blue neon lights, dark room, shallow depth of field"

{custom_idea_section}
'''

CUSTOM_IDEA_SECTION = '''
USER'S CUSTOM IDEA (process according to mode):
Mode: {idea_mode}
- expand: Develop this idea into a full structured script
- polish: Keep the content, improve structure and flow
- strict: Keep as close as possible to original text

User's idea:
{custom_idea}
'''


@dataclass
class FastScript:
    """Generated script result."""
    title: str
    hook: str
    cta: str
    total_duration: float
    background_music_mood: str
    visual_keywords: List[str]
    segments: List[Dict[str, Any]]
    topic: str
    style: str
    art_style: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "hook": self.hook,
            "cta": self.cta,
            "total_duration": self.total_duration,
            "background_music_mood": self.background_music_mood,
            "visual_keywords": self.visual_keywords,
            "segments": self.segments,
            "topic": self.topic,
            "style": self.style,
            "art_style": self.art_style,
        }


class FastScriptGenerator:
    """
    Fast script generator using a single GPT request.

    Replaces the slow multi-agent system:
    - Old: 4 GPT requests, ~80 seconds
    - New: 1 GPT request, ~5-10 seconds
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or config.ai.openai_api_key or ""
        self.client = AsyncOpenAI(api_key=self.api_key) if self.api_key else None

        if not self.api_key:
            logger.warning("[FAST_SCRIPT] No OpenAI API key - script generation disabled")
        else:
            logger.info("[FAST_SCRIPT] Generator initialized (single-request mode)")

    async def generate_script(
        self,
        topic: str,
        style: str = "documentary",
        language: str = "ru",
        duration: int = 60,
        art_style: str = "photorealism",
        custom_idea: Optional[str] = None,
        idea_mode: str = "expand"
    ) -> FastScript:
        """
        Generate a complete video script in a single GPT request.

        Args:
            topic: Video topic
            style: Script style (viral, documentary, storytelling, motivational, educational)
            language: Language code (ru, en)
            duration: Target duration in seconds
            art_style: Visual style for image generation
            custom_idea: User's custom idea/draft
            idea_mode: How to process custom idea (expand, polish, strict)

        Returns:
            FastScript with all segments and visual prompts
        """
        if not self.client:
            logger.warning("[FAST_SCRIPT] No API key - using fallback")
            return self._create_fallback_script(topic, duration, art_style)

        logger.info(f"[FAST_SCRIPT] Generating script: {topic[:50]}...")

        # Prepare prompt
        language_names = {"ru": "Russian", "en": "English", "kk": "Kazakh"}
        language_name = language_names.get(language, "Russian")

        style_desc = STYLE_DESCRIPTIONS.get(style, STYLE_DESCRIPTIONS["documentary"])
        art_style_desc = ART_STYLE_PROMPTS.get(art_style, ART_STYLE_PROMPTS["photorealism"])

        # Custom idea section
        custom_section = ""
        if custom_idea:
            custom_section = CUSTOM_IDEA_SECTION.format(
                idea_mode=idea_mode,
                custom_idea=custom_idea
            )

        # Calculate word count and segment count based on duration
        word_count = int(duration * 2.5)  # ~2.5 words per second
        segment_count = max(6, min(12, duration // 5))  # 5 seconds per segment on average

        prompt = FAST_SCRIPT_PROMPT.format(
            topic=topic,
            duration=duration,
            language_name=language_name,
            style_desc=style_desc,
            art_style_desc=art_style_desc,
            word_count=word_count,
            segment_count=segment_count,
            custom_idea_section=custom_section
        )

        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": """You are a video scriptwriter. Respond ONLY with valid JSON.
CRITICAL REQUIREMENTS:
- Sum of segment durations MUST equal requested total duration
- EACH segment text MUST be 12-30 words - SHORT SENTENCES ARE FORBIDDEN!
- Total text when spoken aloud must fill the entire duration (2.5 words = 1 second)
- visual_prompt must be in ENGLISH with concrete, photographable scenes
- Include the art style description in EVERY visual_prompt
- For 30 second video: minimum 75 words total
- For 60 second video: minimum 150 words total"""
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=4000,
                response_format={"type": "json_object"}
            )

            content = response.choices[0].message.content
            script_data = json.loads(content)

            # Process segments
            segments = []
            total_segment_duration = 0

            for i, seg in enumerate(script_data.get("segments", [])):
                seg_duration = float(seg.get("duration", 5))
                seg_duration = max(2, min(15, seg_duration))  # Clamp to valid range
                total_segment_duration += seg_duration

                segments.append({
                    "text": seg.get("text", ""),
                    "duration": seg_duration,
                    "visual_prompt": seg.get("visual_prompt", ""),
                    "visual_keywords": seg.get("visual_keywords", []),
                    "emotion": seg.get("emotion", "neutral"),
                    "segment_type": "content" if i > 0 else "hook",
                    "camera_direction": seg.get("camera_direction", "static"),
                    "lighting_mood": "cinematic"
                })

            # Calculate total word count for logging
            total_words = sum(len(seg["text"].split()) for seg in segments)
            expected_words = int(duration * 2.5)
            logger.info(f"[FAST_SCRIPT] Generated {total_words} words (expected ~{expected_words} for {duration}s)")

            if total_words < expected_words * 0.7:
                logger.warning(f"[FAST_SCRIPT] Text too short! Only {total_words} words for {duration}s video")

            # Scale durations if needed
            if segments and abs(total_segment_duration - duration) > 1:
                scale = duration / total_segment_duration
                for seg in segments:
                    seg["duration"] = round(seg["duration"] * scale, 1)
                logger.info(f"[FAST_SCRIPT] Scaled durations by {scale:.2f}")

            result = FastScript(
                title=script_data.get("title", topic),
                hook=script_data.get("hook", segments[0]["text"] if segments else ""),
                cta=script_data.get("cta", ""),
                total_duration=float(duration),
                background_music_mood=script_data.get("background_music_mood", "cinematic"),
                visual_keywords=script_data.get("visual_keywords", []),
                segments=segments,
                topic=topic,
                style=style,
                art_style=art_style
            )

            logger.info(f"[FAST_SCRIPT] Generated {len(segments)} segments in single request")
            return result

        except Exception as e:
            logger.error(f"[FAST_SCRIPT] Generation failed: {e}")
            return self._create_fallback_script(topic, duration, art_style)

    def _create_fallback_script(
        self,
        topic: str,
        duration: int,
        art_style: str
    ) -> FastScript:
        """Create fallback script when API is unavailable."""
        logger.info("[FAST_SCRIPT] Using fallback script")

        art_style_desc = ART_STYLE_PROMPTS.get(art_style, ART_STYLE_PROMPTS["photorealism"])
        segment_count = max(4, duration // 10)
        segment_duration = duration / segment_count

        segments = []
        for i in range(segment_count):
            segments.append({
                "text": f"Segment {i+1} about {topic}.",
                "duration": segment_duration,
                "visual_prompt": f"{art_style_desc}, scene related to {topic}, cinematic composition",
                "visual_keywords": [topic],
                "emotion": "neutral",
                "segment_type": "content",
                "camera_direction": "zoom_in" if i % 2 == 0 else "zoom_out",
                "lighting_mood": "cinematic"
            })

        return FastScript(
            title=topic,
            hook=f"Discover {topic}",
            cta="Follow for more!",
            total_duration=float(duration),
            background_music_mood="cinematic",
            visual_keywords=[topic],
            segments=segments,
            topic=topic,
            style="documentary",
            art_style=art_style
        )

    async def close(self):
        """Close the client."""
        if self.client:
            await self.client.close()
        logger.info("[FAST_SCRIPT] Generator closed")


# Singleton instance
_fast_generator: Optional[FastScriptGenerator] = None


def get_fast_script_generator() -> FastScriptGenerator:
    """Get singleton FastScriptGenerator instance."""
    global _fast_generator
    if _fast_generator is None:
        _fast_generator = FastScriptGenerator()
    return _fast_generator
