"""
Agent 2: Visual Director (Prompt Engineer)

Task: Take the story from Agent 1 and slice it into visual segments.

Key Features:
- Visual Consistency: Uses Visual Bible for character/location consistency
- All DALL-E prompts include consistent descriptions
- Segment structure: Hook → Content → Climax → CTA
- Cinematic prompts for DALL-E 3 / Nano Banana

Updated: Now supports Visual Bible from StoryAnalyzer for full story coherence.
"""

import json
import logging
import httpx
import re
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from dataclasses import dataclass, field, asdict

from .storyteller import ScriptStyle

if TYPE_CHECKING:
    from .story_analyzer import VisualBible

logger = logging.getLogger(__name__)


@dataclass
class VisualSegment:
    """A single segment with text and visual prompt."""
    index: int
    text: str
    duration: float
    visual_prompt: str
    visual_keywords: List[str] = field(default_factory=list)
    emotion: str = "neutral"
    segment_type: str = "content"  # hook, content, climax, cta
    camera_direction: str = "static"
    lighting_mood: str = "cinematic"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SegmentationResult:
    """Result from the Visual Director agent."""
    segments: List[VisualSegment]
    style_consistency_string: str
    total_duration: float
    success: bool
    error: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════════
# ART STYLE PROMPTS FOR DALL-E (User-selectable visual styles)
# ═══════════════════════════════════════════════════════════════════════════════

ART_STYLE_PROMPTS = {
    # Photo Realistic (default)
    "photorealism": "hyper-realistic photograph, intricate details, natural lighting, documentary style, 8K resolution, photojournalistic quality",

    # Anime
    "anime": "Japanese anime style, large expressive eyes, detailed hair, vibrant colors, dynamic action pose, clean line art, anime aesthetic, Studio anime quality",

    # Studio Ghibli
    "ghibli": "hand-drawn anime style, Hayao Miyazaki aesthetic, ethereal landscapes, soft watercolor textures, whimsical fantasy world, detailed backgrounds, warm nostalgic atmosphere",

    # Disney Toon
    "disney": "traditional animated film style, expressive cartoon characters, soft cel shading, classic animation look, warm color palette, family-friendly aesthetic, storybook illustration quality",

    # Comic Book
    "comic": "classic comic book style, bold ink outlines, halftone dot pattern, vibrant flat colors, dynamic superhero poses, action panels aesthetic, graphic novel illustration",

    # Minecraft
    "minecraft": "blocky voxel art style, cubic pixel aesthetic, 3D block-based world, vibrant primary colors, procedural terrain look, sandbox game visual style, low-poly cubic characters",

    # LEGO
    "lego": "plastic toy brick aesthetic, brick-built characters and environments, vivid primary colors, 3D rendered toy style, glossy plastic surfaces, miniature diorama look",

    # GTA V
    "gtav": "gritty open-world video game art, realistic urban setting, strong dramatic shadows, cinematic quality, neon city lights, crime drama aesthetic, Los Santos visual style",

    # Watercolor
    "watercolor": "traditional watercolor painting, soft color bleeds and washes, paper texture visible, artistic brush strokes, impressionistic lighting, fine art illustration style",

    # Expressionism
    "expressionism": "bold expressionist painting style, Van Gogh inspired brush strokes, swirling dynamic compositions, emotional color palette, dramatic distorted perspectives, artistic impasto texture",

    # Charcoal
    "charcoal": "black and white charcoal drawing, dramatic high contrast, textured paper grain, fine art sketch aesthetic, realistic shading, classical drawing technique",

    # Pixel Art
    "pixel": "retro pixel art style, 16-bit video game aesthetic, limited color palette, crisp pixel edges, nostalgic gaming visuals, sprite-based characters",

    # Creepy Toon
    "creepy": "dark unsettling cartoon style, Tim Burton inspired aesthetic, exaggerated gothic characters, eerie shadows and lighting, horror animation look, creepy whimsical atmosphere",

    # Children's Book
    "childrens": "whimsical children's book illustration, soft pastel colors, friendly rounded characters, storybook aesthetic, warm inviting atmosphere, gentle watercolor look",
}

# Default art style if none specified
DEFAULT_ART_STYLE = "photorealism"


# ═══════════════════════════════════════════════════════════════════════════════
# VISUAL CONSISTENCY TEMPLATES BY SCRIPT STYLE
# ═══════════════════════════════════════════════════════════════════════════════

STYLE_VISUAL_CONSISTENCY = {
    ScriptStyle.VIRAL: "ultra-sharp 4K social media aesthetic, vibrant saturated colors, high contrast, trending visual style, attention-grabbing composition",

    ScriptStyle.DOCUMENTARY: "National Geographic documentary style, photorealistic, cinematic 8K, natural earth tones, museum-quality fine art photography, David Attenborough nature documentary aesthetic",

    ScriptStyle.MOTIVATIONAL: "warm inspirational tones, golden hour lighting throughout, hope and triumph visual language, cinematic motivational poster aesthetic, soft lens flare",

    ScriptStyle.STORYTELLING: "epic fantasy/historical drama cinematography, consistent character design, Game of Thrones visual style, rich detailed production design, cinematic color grading",

    ScriptStyle.EDUCATIONAL: "clean professional infographic style, clear visual hierarchy, scientific visualization aesthetic, TED talk presentation quality, modern minimal design",

    ScriptStyle.MYSTERY: "noir cinematography, deep shadows and moody lighting, mystery thriller visual style, Fincher-esque desaturated palette, atmospheric fog and mist",

    ScriptStyle.HISTORICAL: "period-accurate historical recreation, museum exhibition quality, sepia-tinted documentary style, History Channel epic visualization, authentic costume and setting detail"
}


# Segment count based on duration
DURATION_TO_SEGMENTS = {
    30: 6,   # 30 seconds = 6 segments (5 sec each)
    45: 9,   # 45 seconds = 9 segments (5 sec each)
    60: 12,  # 60 seconds = 12 segments (5 sec each)
    90: 18,  # 90 seconds = 18 segments (5 sec each)
}

def get_segment_count(duration_seconds: int) -> int:
    """Get target segment count for a given duration."""
    if duration_seconds in DURATION_TO_SEGMENTS:
        return DURATION_TO_SEGMENTS[duration_seconds]
    # Default: ~5 seconds per segment
    return max(4, int(duration_seconds / 5))


# System prompt template for segmentation (segment count filled in dynamically)
SEGMENTATION_SYSTEM_PROMPT_TEMPLATE = """You are a VISUAL DIRECTOR for short-form documentary videos.

Your task: Divide a narrative story into EXACTLY {segment_count} visual segments for a {duration}-second video.

═══════════════════════════════════════════════════════════════
SEGMENT STRUCTURE ({segment_count} segments):
═══════════════════════════════════════════════════════════════

SEGMENT 1 (HOOK):
- Purpose: Stop the scroll, grab attention
- Can use attention-grabbing language
- Visual: Most striking, curiosity-inducing image

SEGMENTS 2-{content_end} (CONTENT):
- Purpose: Tell the story with pure facts
- NO meta-phrases ("did you know", "here's what's crazy")
- Just events, details, descriptions
- Visuals progress the narrative

SEGMENT {climax_num} (CLIMAX):
- Purpose: The "WOW" moment
- Most shocking revelation or peak emotion
- Visual: Most dramatic, impactful image

SEGMENT {cta_num} (CTA):
- Purpose: Call to action
- Encourage subscribe/follow
- Visual: Clean, professional, inviting

═══════════════════════════════════════════════════════════════
VISUAL PROMPT FORMAT:
═══════════════════════════════════════════════════════════════

Each visual_prompt MUST follow this structure:
"[SHOT TYPE] of [SUBJECT], [SPECIFIC DETAILS], [LIGHTING], [STYLE CONSISTENCY STRING], no text, no words, no watermarks"

SHOT TYPES (use variety):
- Extreme wide shot (landscapes, scale)
- Wide shot (context, environment)
- Medium shot (subject in environment)
- Close-up (details, emotion)
- Low angle (power, grandeur)
- High angle (vulnerability)
- Bird's eye view (aerial perspective)
- Dutch angle (tension, unease)

LIGHTING OPTIONS:
- Golden hour sunlight streaming
- Dramatic rim lighting with shadows
- Soft diffused light
- Blue hour twilight
- Volumetric god rays through mist
- Backlit silhouettes
- Moody atmospheric lighting
- High contrast chiaroscuro

═══════════════════════════════════════════════════════════════
OUTPUT FORMAT (JSON):
═══════════════════════════════════════════════════════════════

{
  "segments": [
    {
      "index": 0,
      "text": "The hook sentence",
      "duration": 5.0,
      "visual_prompt": "Extreme wide shot of...",
      "emotion": "mysterious",
      "segment_type": "hook",
      "camera_direction": "zoom_in",
      "lighting_mood": "golden_hour"
    },
    ... (12 total)
  ]
}

IMPORTANT:
- Each segment: 15-25 words of text (4-6 seconds speech)
- Duration: 5.0 seconds each
- Visual prompts: 40-60 words, highly detailed
- NO text/words/watermarks in images
"""


class VisualDirector:
    """
    Agent 2: Visual Director

    Takes a narrative story and slices it into 12 visual segments
    with consistent DALL-E prompts for visual coherence.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        """
        Initialize Visual Director agent.

        Default model: gpt-4o-mini (15x cheaper, sufficient for segmentation tasks)
        """
        from app.config import config
        self.api_key = api_key or config.ai.openai_api_key or ""
        self.model = model
        self.client = httpx.AsyncClient(timeout=120.0)

        if not self.api_key or self.api_key.startswith("PASTE_"):
            logger.warning("[VISUAL_DIRECTOR] No API key - will use fallback segmentation")
            self.api_key = ""
        else:
            logger.info(f"[VISUAL_DIRECTOR] Agent initialized with {model} (cost-optimized)")

    async def segment_story(
        self,
        narrative: str,
        topic: str,
        style: ScriptStyle = ScriptStyle.DOCUMENTARY,
        language: str = "ru",
        duration_seconds: int = 60,
        art_style: str = "photorealism"
    ) -> SegmentationResult:
        """
        Segment a narrative into visual segments with consistent prompts.

        Args:
            narrative: The story from Master Storyteller
            topic: The main topic/subject
            style: The style for visual consistency
            language: Language of the narrative
            duration_seconds: Target video duration (30 or 60 seconds)
            art_style: User-selected art style for DALL-E (minecraft, anime, etc.)

        Returns:
            SegmentationResult with segments
        """
        segment_count = get_segment_count(duration_seconds)
        logger.info(f"[VISUAL_DIRECTOR] Segmenting story into {segment_count} parts ({style.value} style, {duration_seconds}s)")
        logger.info(f"[VISUAL_DIRECTOR] Art Style: {art_style}")
        self._current_segment_count = segment_count
        self._current_duration = duration_seconds
        self._current_art_style = art_style

        # Get style consistency string (based on script style)
        style_consistency = STYLE_VISUAL_CONSISTENCY.get(
            style,
            STYLE_VISUAL_CONSISTENCY[ScriptStyle.DOCUMENTARY]
        )

        # Get art style modifier for DALL-E prompts
        art_style_modifier = ART_STYLE_PROMPTS.get(art_style, ART_STYLE_PROMPTS[DEFAULT_ART_STYLE])
        logger.info(f"[VISUAL_DIRECTOR] Art Style Modifier: {art_style_modifier[:50]}...")

        if not self.api_key:
            return self._generate_fallback_segments(narrative, topic, style, style_consistency, language, segment_count, duration_seconds, art_style)

        try:
            language_name = {"ru": "Russian", "en": "English", "kk": "Kazakh"}.get(language, language)

            # Calculate segment structure based on count
            content_end = segment_count - 2
            climax_num = segment_count - 1
            cta_num = segment_count

            # Build dynamic system prompt
            system_prompt = SEGMENTATION_SYSTEM_PROMPT_TEMPLATE.format(
                segment_count=segment_count,
                duration=duration_seconds,
                content_end=content_end,
                climax_num=climax_num,
                cta_num=cta_num
            )

            user_prompt = f"""Divide this narrative into EXACTLY {segment_count} segments for a {duration_seconds}-second video:

═══════════════════════════════════════════════════════════════
NARRATIVE:
═══════════════════════════════════════════════════════════════
{narrative}

═══════════════════════════════════════════════════════════════
PARAMETERS:
═══════════════════════════════════════════════════════════════
TOPIC: {topic}
LANGUAGE: Keep all text in {language_name}
STYLE: {style.value.upper()}
DURATION: {duration_seconds} seconds ({segment_count} segments)

═══════════════════════════════════════════════════════════════
CRITICAL: ART STYLE (MUST BE IN EVERY PROMPT)
═══════════════════════════════════════════════════════════════
User selected ART STYLE: {art_style.upper()}
EVERY visual_prompt MUST include this EXACT art style modifier:
"{art_style_modifier}"

═══════════════════════════════════════════════════════════════
CRITICAL: VISUAL CONSISTENCY STRING
═══════════════════════════════════════════════════════════════
EVERY visual_prompt MUST ALSO include this consistency string:
"{style_consistency}"

This ensures all {segment_count} images share the same visual style and characters look consistent.

FINAL PROMPT FORMAT: {art_style_modifier}, [SHOT] of [SUBJECT], [DETAILS], {style_consistency}, no text, no words

CRITICAL: The art style modifier MUST be at the START of every visual_prompt!

═══════════════════════════════════════════════════════════════
SEGMENTATION RULES:
═══════════════════════════════════════════════════════════════
- Segment 1: HOOK (attention-grabbing opener)
- Segments 2-{content_end}: Pure story content (NO meta-phrases!)
- Segment {climax_num}: CLIMAX (most powerful moment)
- Segment {cta_num}: CTA (call to action)

Return valid JSON with "segments" array containing exactly {segment_count} segments."""

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.7,
                "max_tokens": 3000,
                "response_format": {"type": "json_object"}
            }

            response = await self.client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload
            )

            if response.status_code != 200:
                logger.error(f"[VISUAL_DIRECTOR] API error: {response.status_code}")
                return self._generate_fallback_segments(narrative, topic, style, style_consistency, language)

            data = response.json()
            content = data["choices"][0]["message"]["content"]

            # Parse JSON
            script_data = json.loads(content)
            raw_segments = script_data.get("segments", [])

            # Convert to VisualSegment objects
            segments = []
            for i, seg_data in enumerate(raw_segments[:12]):
                # Ensure art style modifier AND style consistency in visual prompt
                visual_prompt = seg_data.get("visual_prompt", "")

                # CRITICAL: PREPEND art style modifier for DALL-E priority
                # Art style MUST be at the START of the prompt for maximum effect
                if art_style_modifier not in visual_prompt:
                    visual_prompt = f"{art_style_modifier}, {visual_prompt}"

                # Ensure style consistency string is also present at the end
                if style_consistency not in visual_prompt:
                    visual_prompt = f"{visual_prompt}, {style_consistency}"

                # Clean up any double commas
                visual_prompt = visual_prompt.replace(",,", ",").strip(", ")

                segment = VisualSegment(
                    index=i,
                    text=seg_data.get("text", ""),
                    duration=float(seg_data.get("duration", 5.0)),
                    visual_prompt=visual_prompt,
                    visual_keywords=seg_data.get("visual_keywords", [topic]),
                    emotion=seg_data.get("emotion", "neutral"),
                    segment_type=self._get_segment_type(i),
                    camera_direction=seg_data.get("camera_direction", "static"),
                    lighting_mood=seg_data.get("lighting_mood", "cinematic")
                )
                segments.append(segment)

            # Ensure we have exactly 12 segments
            while len(segments) < 12:
                segments.append(self._create_padding_segment(len(segments), topic, style_consistency))

            # Clean repetitive phrases from content segments
            segments = self._clean_repetitive_phrases(segments)

            total_duration = sum(seg.duration for seg in segments)

            logger.info(f"[VISUAL_DIRECTOR] Created {len(segments)} segments, {total_duration:.1f}s total")

            return SegmentationResult(
                segments=segments,
                style_consistency_string=style_consistency,
                total_duration=total_duration,
                success=True
            )

        except json.JSONDecodeError as e:
            logger.error(f"[VISUAL_DIRECTOR] JSON parse failed: {e}")
            return self._generate_fallback_segments(narrative, topic, style, style_consistency, language, segment_count, duration_seconds, art_style)
        except Exception as e:
            logger.error(f"[VISUAL_DIRECTOR] Segmentation failed: {e}")
            return self._generate_fallback_segments(narrative, topic, style, style_consistency, language, segment_count, duration_seconds, art_style)

    def _get_segment_type(self, index: int, segment_count: int = 12) -> str:
        """Determine segment type based on position."""
        if index == 0:
            return "hook"
        elif index == segment_count - 2:
            return "climax"
        elif index == segment_count - 1:
            return "cta"
        else:
            return "content"

    def _clean_repetitive_phrases(self, segments: List[VisualSegment]) -> List[VisualSegment]:
        """Remove forbidden phrases from content segments (2-10)."""
        forbidden_patterns = [
            r"(?i)did you know",
            r"(?i)вы знали",
            r"(?i)знаете ли вы",
            r"(?i)i will tell you",
            r"(?i)я расскажу",
            r"(?i)сейчас расскажу",
            r"(?i)stay tuned",
            r"(?i)wait for it",
            r"(?i)here's what's crazy",
            r"(?i)вот что удивительно",
            r"(?i)but here's the thing",
            r"(?i)let me tell you",
            r"(?i)позвольте рассказать",
            r"(?i)in this video",
            r"(?i)в этом видео",
        ]

        for segment in segments:
            if 1 <= segment.index <= 9:  # Content segments only
                text = segment.text
                for pattern in forbidden_patterns:
                    text = re.sub(pattern + r"[,.]?\s*", "", text)
                text = re.sub(r"\s+", " ", text).strip()
                if text and text[0].islower():
                    text = text[0].upper() + text[1:]
                segment.text = text

        return segments

    def _create_padding_segment(
        self,
        index: int,
        topic: str,
        style_consistency: str
    ) -> VisualSegment:
        """Create a padding segment if we don't have 12."""
        return VisualSegment(
            index=index,
            text=f"Продолжение истории о {topic}." if index < 11 else "Подписывайтесь для продолжения.",
            duration=5.0,
            visual_prompt=f"Cinematic shot related to {topic}, atmospheric lighting, {style_consistency}, no text, no words",
            visual_keywords=[topic],
            emotion="neutral",
            segment_type=self._get_segment_type(index),
            camera_direction="static",
            lighting_mood="cinematic"
        )

    def _generate_fallback_segments(
        self,
        narrative: str,
        topic: str,
        style: ScriptStyle,
        style_consistency: str,
        language: str,
        segment_count: int = 12,
        duration_seconds: int = 60,
        art_style: str = "photorealism"
    ) -> SegmentationResult:
        """Generate fallback segments when API is unavailable."""
        logger.info(f"[VISUAL_DIRECTOR] Using fallback segmentation for: {topic} ({segment_count} segments, art_style={art_style})")

        # Get art style modifier
        art_style_modifier = ART_STYLE_PROMPTS.get(art_style, ART_STYLE_PROMPTS[DEFAULT_ART_STYLE])

        # Split narrative into sentences
        sentences = re.split(r'(?<=[.!?])\s+', narrative)

        # Distribute sentences across segments
        segments_per_sentence = max(1, len(sentences) // segment_count)
        current_sentence = 0

        segments = []
        shot_types = [
            "Extreme wide shot", "Wide shot", "Medium shot", "Close-up",
            "Low angle shot", "Bird's eye view", "High angle shot", "Dutch angle",
            "Wide establishing shot", "Tracking shot", "Close-up", "Clean modern shot"
        ]

        lighting_moods = [
            "golden_hour", "dramatic", "soft", "moody",
            "backlit", "blue_hour", "atmospheric", "cinematic",
            "natural", "rim_lighting", "dramatic", "warm"
        ]

        camera_directions = [
            "zoom_in", "static", "pan_left", "zoom_out",
            "pan_right", "zoom_in", "static", "pan_left",
            "zoom_out", "static", "zoom_in", "static"
        ]

        emotions = [
            "mysterious", "somber", "determined", "powerful",
            "intense", "amazed", "tense", "hopeful",
            "mysterious", "wonder", "shocking", "engaging"
        ]

        # Calculate segment duration
        segment_duration = duration_seconds / segment_count

        for i in range(segment_count):
            # Get text for this segment
            if current_sentence < len(sentences):
                text = " ".join(sentences[current_sentence:current_sentence + segments_per_sentence])
                current_sentence += segments_per_sentence
            else:
                text = f"Продолжение истории о {topic}." if language == "ru" else f"The story of {topic} continues."

            # Ensure text isn't too long
            words = text.split()
            if len(words) > 25:
                text = " ".join(words[:25]) + "."

            # Cycle through presets if we have more segments than presets
            shot_idx = i % len(shot_types)
            light_idx = i % len(lighting_moods)
            cam_idx = i % len(camera_directions)
            emo_idx = i % len(emotions)

            segment = VisualSegment(
                index=i,
                text=text,
                duration=segment_duration,
                visual_prompt=f"{art_style_modifier}, {shot_types[shot_idx]} of scene related to {topic}, dramatic composition, {lighting_moods[light_idx]} lighting, {style_consistency}, no text, no words, no watermarks",
                visual_keywords=[topic],
                emotion=emotions[emo_idx],
                segment_type=self._get_segment_type(i, segment_count),
                camera_direction=camera_directions[cam_idx],
                lighting_mood=lighting_moods[light_idx]
            )
            segments.append(segment)

        return SegmentationResult(
            segments=segments,
            style_consistency_string=style_consistency,
            total_duration=60.0,
            success=True,
            error="Used fallback segmentation (API unavailable)"
        )

    async def segment_story_with_visual_bible(
        self,
        narrative: str,
        topic: str,
        visual_bible: "VisualBible",
        style: ScriptStyle = ScriptStyle.DOCUMENTARY,
        language: str = "ru",
        duration_seconds: int = 60,
        art_style: str = "photorealism"
    ) -> SegmentationResult:
        """
        Segment story using Visual Bible for full visual consistency.

        This method uses the Visual Bible to ensure:
        - Characters look the same across all segments
        - Locations maintain consistent visual descriptions
        - Atmosphere and mood are unified

        Args:
            narrative: The story from Master Storyteller
            topic: The main topic/subject
            visual_bible: VisualBible with characters, locations, atmosphere
            style: The style for visual consistency
            language: Language of the narrative
            duration_seconds: Target video duration
            art_style: User-selected art style

        Returns:
            SegmentationResult with visually coherent segments
        """
        segment_count = get_segment_count(duration_seconds)
        logger.info(f"[VISUAL_DIRECTOR] Segmenting with Visual Bible ({segment_count} segments)")
        logger.info(f"[VISUAL_DIRECTOR] Visual Bible: {len(visual_bible.characters)} characters, {len(visual_bible.locations)} locations")

        # Get style consistency string
        style_consistency = STYLE_VISUAL_CONSISTENCY.get(
            style, STYLE_VISUAL_CONSISTENCY[ScriptStyle.DOCUMENTARY]
        )

        # Get art style modifier
        art_style_modifier = ART_STYLE_PROMPTS.get(art_style, ART_STYLE_PROMPTS[DEFAULT_ART_STYLE])

        if not self.api_key:
            return self._generate_fallback_with_bible(
                narrative, topic, visual_bible, style_consistency,
                language, segment_count, duration_seconds, art_style
            )

        try:
            language_name = {"ru": "Russian", "en": "English", "kk": "Kazakh"}.get(language, language)

            # Build character descriptions for prompt
            character_descriptions = []
            for char in visual_bible.characters:
                character_descriptions.append(f"- {char.name}: {char.description}")
            characters_text = "\n".join(character_descriptions) if character_descriptions else "No specific characters"

            # Build location descriptions
            location_descriptions = []
            for loc in visual_bible.locations:
                location_descriptions.append(f"- {loc.name}: {loc.description}")
            locations_text = "\n".join(location_descriptions) if location_descriptions else "Generic settings"

            # Build atmosphere description
            atm = visual_bible.atmosphere
            atmosphere_text = f"""
Mood: {atm.get('mood', 'cinematic')}
Lighting: {atm.get('lighting', 'natural')}
Color Palette: {', '.join(atm.get('color_palette', ['neutral']))}
Style: {atm.get('style', 'documentary')}"""

            # Build segment mapping hints
            segment_hints = []
            for mapping in visual_bible.segment_mapping[:segment_count]:
                idx = mapping.get("segment_index", 0)
                loc_id = mapping.get("location_id", "")
                char_ids = mapping.get("character_ids", [])
                visual_focus = mapping.get("visual_focus", "medium shot")
                mood_shift = mapping.get("mood_shift", "")

                hint = f"Segment {idx}: {visual_focus}"
                if loc_id:
                    hint += f", location: {loc_id}"
                if char_ids:
                    hint += f", characters: {', '.join(char_ids)}"
                if mood_shift:
                    hint += f", mood: {mood_shift}"
                segment_hints.append(hint)

            segment_hints_text = "\n".join(segment_hints)

            # Enhanced system prompt with Visual Bible
            system_prompt = f"""You are a VISUAL DIRECTOR creating {segment_count} segments for a {duration_seconds}-second video.

═══════════════════════════════════════════════════════════════
VISUAL BIBLE (USE THESE EXACT DESCRIPTIONS!)
═══════════════════════════════════════════════════════════════

CHARACTERS (use EXACT descriptions in prompts):
{characters_text}

LOCATIONS (use EXACT descriptions in prompts):
{locations_text}

ATMOSPHERE:
{atmosphere_text}

VISUAL THREAD: {visual_bible.visual_thread}

KEY OBJECTS: {', '.join(visual_bible.key_objects) if visual_bible.key_objects else 'None specified'}

SEGMENT MAPPING (which elements appear where):
{segment_hints_text}

═══════════════════════════════════════════════════════════════
CRITICAL RULES FOR VISUAL VARIETY & CONSISTENCY
═══════════════════════════════════════════════════════════════

1. When a character appears, use their EXACT description from Visual Bible
2. When a location appears, use its EXACT description from Visual Bible
3. Always include the atmosphere's mood and lighting style
4. Keep color palette consistent: {', '.join(atm.get('color_palette', ['neutral']))}
5. Each prompt must feel like it's from the SAME visual world

⚠️ IMPORTANT: VISUAL VARIETY (DO NOT show characters in every frame!)
- Characters should appear in only 30-40% of segments (3-5 out of 12)
- Mix different shot types:
  * LANDSCAPE/ENVIRONMENT shots (no people) - wide shots of locations
  * OBJECT/DETAIL shots - close-ups of key objects
  * ATMOSPHERIC shots - mood, lighting, weather
  * CHARACTER shots - only when directly relevant to narration
- Avoid repetitive "person standing" images
- Create visual storytelling through variety

═══════════════════════════════════════════════════════════════
OUTPUT FORMAT (JSON)
═══════════════════════════════════════════════════════════════

Return JSON with "segments" array. Each segment:
{{
  "index": 0,
  "text": "Narration text in {language_name}",
  "duration": 5.0,
  "visual_prompt": "[ART STYLE], [SHOT TYPE - vary between landscape/object/character], [SUBJECT - not always character!], [ATMOSPHERE], {style_consistency}, no text, no words",
  "emotion": "mood for this segment",
  "segment_type": "hook/content/climax/cta",
  "camera_direction": "zoom_in/pan/static",
  "lighting_mood": "from atmosphere"
}}

IMPORTANT:
- Segment 1 = HOOK (attention grabber)
- Segments 2-{segment_count-2} = CONTENT (story progression)
- Segment {segment_count-1} = CLIMAX (peak moment)
- Segment {segment_count} = CTA (call to action)
"""

            user_prompt = f"""Create {segment_count} visually consistent segments for this narrative:

NARRATIVE:
{narrative}

TOPIC: {topic}

ART STYLE (MUST be at START of every visual_prompt):
{art_style_modifier}

STYLE CONSISTENCY STRING (MUST be in every visual_prompt):
{style_consistency}

CRITICAL: Copy character/location descriptions EXACTLY from the Visual Bible above!
Every segment must feel like it's from the same visual world.

Return valid JSON with exactly {segment_count} segments."""

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.7,
                "max_tokens": 4000,
                "response_format": {"type": "json_object"}
            }

            response = await self.client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload
            )

            if response.status_code != 200:
                logger.error(f"[VISUAL_DIRECTOR] API error: {response.status_code}")
                return self._generate_fallback_with_bible(
                    narrative, topic, visual_bible, style_consistency,
                    language, segment_count, duration_seconds, art_style
                )

            data = response.json()
            content = data["choices"][0]["message"]["content"]
            script_data = json.loads(content)
            raw_segments = script_data.get("segments", [])

            # Convert to VisualSegment objects with Visual Bible context
            segments = []
            for i, seg_data in enumerate(raw_segments[:segment_count]):
                visual_prompt = seg_data.get("visual_prompt", "")

                # Ensure art style modifier at start
                if art_style_modifier not in visual_prompt:
                    visual_prompt = f"{art_style_modifier}, {visual_prompt}"

                # Ensure style consistency
                if style_consistency not in visual_prompt:
                    visual_prompt = f"{visual_prompt}, {style_consistency}"

                # Clean up
                visual_prompt = visual_prompt.replace(",,", ",").strip(", ")

                segment = VisualSegment(
                    index=i,
                    text=seg_data.get("text", ""),
                    duration=float(seg_data.get("duration", duration_seconds / segment_count)),
                    visual_prompt=visual_prompt,
                    visual_keywords=seg_data.get("visual_keywords", [topic]),
                    emotion=seg_data.get("emotion", "neutral"),
                    segment_type=self._get_segment_type(i, segment_count),
                    camera_direction=seg_data.get("camera_direction", "static"),
                    lighting_mood=seg_data.get("lighting_mood", atm.get("lighting", "cinematic"))
                )
                segments.append(segment)

            # Pad if needed
            while len(segments) < segment_count:
                segments.append(self._create_bible_padding_segment(
                    len(segments), topic, visual_bible, style_consistency,
                    art_style_modifier, segment_count
                ))

            # Clean repetitive phrases
            segments = self._clean_repetitive_phrases(segments)

            total_duration = sum(seg.duration for seg in segments)
            logger.info(f"[VISUAL_DIRECTOR] Created {len(segments)} visually consistent segments")

            return SegmentationResult(
                segments=segments,
                style_consistency_string=style_consistency,
                total_duration=total_duration,
                success=True
            )

        except Exception as e:
            logger.error(f"[VISUAL_DIRECTOR] Visual Bible segmentation failed: {e}")
            return self._generate_fallback_with_bible(
                narrative, topic, visual_bible, style_consistency,
                language, segment_count, duration_seconds, art_style
            )

    def _generate_fallback_with_bible(
        self,
        narrative: str,
        topic: str,
        visual_bible: "VisualBible",
        style_consistency: str,
        language: str,
        segment_count: int,
        duration_seconds: int,
        art_style: str
    ) -> SegmentationResult:
        """Generate fallback segments using Visual Bible context."""
        logger.info(f"[VISUAL_DIRECTOR] Fallback with Visual Bible for: {topic}")

        art_style_modifier = ART_STYLE_PROMPTS.get(art_style, ART_STYLE_PROMPTS[DEFAULT_ART_STYLE])
        atm = visual_bible.atmosphere

        # Split narrative
        sentences = re.split(r'(?<=[.!?])\s+', narrative)
        sentences_per_seg = max(1, len(sentences) // segment_count)

        segments = []

        # Different shot types for variety
        landscape_shots = ["Extreme wide shot", "Wide establishing shot", "Bird's eye view", "Panoramic shot"]
        object_shots = ["Close-up detail shot", "Macro shot", "Product shot style"]
        character_shots = ["Medium shot", "Portrait shot", "Low angle shot"]
        atmospheric_shots = ["Atmospheric wide shot", "Moody environmental shot", "Silhouette shot"]

        # Determine which segments get characters (only 30-40%)
        # Typically: hook (maybe), 2-3 content segments, climax
        character_segments = {0, segment_count // 3, segment_count // 2, segment_count - 2}  # ~4 out of 12

        for i in range(segment_count):
            # Get text
            start_idx = i * sentences_per_seg
            end_idx = min(start_idx + sentences_per_seg, len(sentences))
            text = " ".join(sentences[start_idx:end_idx]) if start_idx < len(sentences) else f"Продолжение о {topic}."

            # Limit text length
            words = text.split()
            if len(words) > 25:
                text = " ".join(words[:25]) + "."

            # Get Visual Bible context for this segment
            context = visual_bible.get_context_for_segment(i)
            mood = atm.get("mood", "cinematic")
            lighting = atm.get("lighting", "natural")

            # Decide shot type based on segment position
            include_character = i in character_segments and context["characters"]

            loc_desc = ""
            if context["location"]:
                loc = context["location"]
                loc_desc = f"{loc['name']}: {loc['description'][:80]}"

            if include_character:
                # Character shot (30-40% of segments)
                char = context["characters"][0]
                char_desc = f"{char['name']}: {char['description'][:80]}"
                shot = character_shots[i % len(character_shots)]
                if loc_desc:
                    visual_prompt = f"{art_style_modifier}, {shot} of {char_desc}, in {loc_desc}, {mood} mood, {lighting} lighting, {style_consistency}, no text, no words"
                else:
                    visual_prompt = f"{art_style_modifier}, {shot} of {char_desc}, {mood} mood, {lighting} lighting, {style_consistency}, no text, no words"
            elif i % 4 == 0:
                # Landscape/environment shot (no people)
                shot = landscape_shots[i % len(landscape_shots)]
                if loc_desc:
                    visual_prompt = f"{art_style_modifier}, {shot} of {loc_desc}, empty scene without people, {mood} mood, {lighting} lighting, {style_consistency}, no text, no words"
                else:
                    visual_prompt = f"{art_style_modifier}, {shot} of landscape related to {topic}, empty scene without people, {mood} mood, {lighting} lighting, {style_consistency}, no text, no words"
            elif i % 4 == 1:
                # Object/detail shot
                shot = object_shots[i % len(object_shots)]
                key_objects = context.get("key_objects", [])
                if key_objects:
                    visual_prompt = f"{art_style_modifier}, {shot} of {key_objects[0]}, {mood} mood, {lighting} lighting, {style_consistency}, no text, no words"
                else:
                    visual_prompt = f"{art_style_modifier}, {shot} of symbolic object related to {topic}, {mood} mood, {lighting} lighting, {style_consistency}, no text, no words"
            else:
                # Atmospheric shot
                shot = atmospheric_shots[i % len(atmospheric_shots)]
                if loc_desc:
                    visual_prompt = f"{art_style_modifier}, {shot} of {loc_desc}, dramatic atmosphere, {mood} mood, {lighting} lighting, {style_consistency}, no text, no words"
                else:
                    visual_prompt = f"{art_style_modifier}, {shot} capturing the essence of {topic}, dramatic atmosphere, {mood} mood, {lighting} lighting, {style_consistency}, no text, no words"

            segment = VisualSegment(
                index=i,
                text=text,
                duration=duration_seconds / segment_count,
                visual_prompt=visual_prompt,
                visual_keywords=[topic],
                emotion=atm.get("mood", "neutral"),
                segment_type=self._get_segment_type(i, segment_count),
                camera_direction="static",
                lighting_mood=lighting
            )
            segments.append(segment)

        return SegmentationResult(
            segments=segments,
            style_consistency_string=style_consistency,
            total_duration=duration_seconds,
            success=True,
            error="Used Visual Bible fallback"
        )

    def _create_bible_padding_segment(
        self,
        index: int,
        topic: str,
        visual_bible: "VisualBible",
        style_consistency: str,
        art_style_modifier: str,
        segment_count: int
    ) -> VisualSegment:
        """Create padding segment using Visual Bible context."""
        context = visual_bible.get_context_for_segment(index)
        atm = visual_bible.atmosphere

        char_desc = ""
        if context["characters"]:
            char_desc = context["characters"][0]["description"][:80]

        return VisualSegment(
            index=index,
            text=f"Продолжение истории о {topic}.",
            duration=5.0,
            visual_prompt=f"{art_style_modifier}, Cinematic shot of {char_desc or topic}, {atm.get('mood', 'dramatic')} atmosphere, {style_consistency}, no text",
            visual_keywords=[topic],
            emotion=atm.get("mood", "neutral"),
            segment_type=self._get_segment_type(index, segment_count),
            camera_direction="static",
            lighting_mood=atm.get("lighting", "cinematic")
        )

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
