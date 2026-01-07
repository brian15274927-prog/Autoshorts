"""
LLM Service - Documentary Storyteller AI Engine.
Generates cinematic, engaging scripts for faceless video content.

Features:
- Documentary-style narration (no repetitive topic mentions)
- Emotional arc with proper transitions
- Cinematic visual prompts for DALL-E 3
- Professional narrator voice style
"""
import os
import logging
import json
import re
import httpx
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class ScriptStyle(str, Enum):
    """Available script styles for video generation."""
    VIRAL = "viral"
    EDUCATIONAL = "educational"
    STORYTELLING = "storytelling"
    DOCUMENTARY = "documentary"
    MOTIVATIONAL = "motivational"
    MYSTERY = "mystery"
    HISTORICAL = "historical"


@dataclass
class ScriptSegment:
    """A single segment of the generated script with cinematic metadata."""
    text: str
    duration: float
    visual_prompt: str = ""  # Cinematic DALL-E prompt
    visual_keywords: List[str] = field(default_factory=list)
    emotion: str = "neutral"
    segment_type: str = "content"  # hook, content, climax, cta
    camera_direction: str = "static"  # zoom_in, zoom_out, pan_left, pan_right
    lighting_mood: str = "natural"  # dramatic, soft, golden_hour, moody


@dataclass
class GeneratedScript:
    """Complete generated script with all segments."""
    title: str
    hook: str
    segments: List[ScriptSegment]
    cta: str
    total_duration: float
    visual_keywords: List[str]
    background_music_mood: str
    target_audience: str
    topic: str = ""
    style: ScriptStyle = ScriptStyle.DOCUMENTARY
    language: str = "ru"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "hook": self.hook,
            "topic": self.topic,
            "segments": [asdict(s) for s in self.segments],
            "cta": self.cta,
            "total_duration": self.total_duration,
            "visual_keywords": self.visual_keywords,
            "background_music_mood": self.background_music_mood,
            "target_audience": self.target_audience,
            "style": self.style.value if isinstance(self.style, ScriptStyle) else self.style,
            "language": self.language
        }


# ============================================================
# TWO-STEP DOCUMENTARY GENERATION SYSTEM
# ============================================================

# STEP 1: Generate complete narrative story (no segments)
STEP1_STORY_PROMPT = """You are a MASTER DOCUMENTARY STORYTELLER for viral short-form content.

YOUR TASK: Write a COMPLETE 150-word narrative story about the given topic.

═══════════════════════════════════════════════════════════════
CHAIN OF THOUGHT - Follow these steps:
═══════════════════════════════════════════════════════════════

THINK STEP 1: What is the most SHOCKING or UNEXPECTED fact about this topic?
THINK STEP 2: What EMOTIONAL journey should the viewer experience?
THINK STEP 3: What is the CLIMAX - the most mind-blowing revelation?
THINK STEP 4: How do I make viewers NEED to watch until the end?

═══════════════════════════════════════════════════════════════
WRITING RULES:
═══════════════════════════════════════════════════════════════

1. Write ONE continuous narrative - NO segments, NO bullet points
2. Start with ONE hook sentence (curiosity gap or shocking statement)
3. Then ONLY facts, descriptions, and story progression
4. Build to a climax with the most shocking revelation
5. End with a thought that makes viewers want more

═══════════════════════════════════════════════════════════════
FORBIDDEN PHRASES (will cause rejection):
═══════════════════════════════════════════════════════════════
❌ "Did you know..." (only allowed ONCE at the very beginning)
❌ "I will tell you..."
❌ "Now let me explain..."
❌ "Stay tuned..."
❌ "In this video..."
❌ "Let's find out..."
❌ "You won't believe..."
❌ "Wait for it..."
❌ Any meta-commentary about the story itself

═══════════════════════════════════════════════════════════════
GOOD EXAMPLE (Topic: Genghis Khan):
═══════════════════════════════════════════════════════════════

"One man conquered more land than the Roman Empire, Alexander the Great, and Napoleon combined. Born as Temüjin in the harsh Mongolian steppe, he was abandoned by his tribe at age nine. His father poisoned, his family left to starve. But this rejection forged an unbreakable will. By thirty, he united the warring Mongol tribes through a revolutionary idea: loyalty over bloodline. His army of 100,000 horsemen swept across Asia like a storm. Cities that surrendered were spared. Those that resisted were erased from history. His empire stretched from Korea to Poland - 24 million square kilometers. The Silk Road flourished under his protection. Paper money, religious freedom, meritocracy - innovations centuries ahead of Europe. When he died in 1227, his burial site was hidden so completely that it remains lost to this day. 40 million people carry his DNA. His legacy shaped the modern world."

OUTPUT: Return ONLY the story text (150 words). No JSON, no formatting."""


# STEP 2: Divide story into 12 segments
STEP2_SEGMENT_PROMPT = """You are a VIDEO EDITOR dividing a documentary script into 12 segments.

═══════════════════════════════════════════════════════════════
STRICT SEGMENT RULES:
═══════════════════════════════════════════════════════════════

SEGMENT 1 (HOOK):
- The ONLY segment allowed to have attention-grabbing phrases
- Can use: "Did you know", "One man...", shocking statement
- Purpose: Stop the scroll, create curiosity gap

SEGMENTS 2-10 (CONTENT):
- ONLY facts, descriptions, story development
- NO meta-phrases like "now I will tell you", "here's what's crazy"
- NO "stay tuned", "wait for it", "you won't believe"
- Just pure storytelling - events, details, consequences

SEGMENT 11 (CLIMAX):
- The most SHOCKING revelation
- The "wow" moment of the story
- Peak emotional impact

SEGMENT 12 (CTA):
- Call to action (subscribe, follow, like)
- Can tease "Part 2" or continuation
- Leave viewer wanting more

═══════════════════════════════════════════════════════════════
SEGMENT FORMAT:
═══════════════════════════════════════════════════════════════

Each segment needs:
- text: 15-25 words (4-6 seconds of speech)
- duration: 5.0 seconds
- visual_prompt: "[SHOT TYPE] of [SUBJECT], [DETAILS], [LIGHTING], cinematic 8K, National Geographic style, photorealistic"
- emotion: mysterious/intriguing/tense/powerful/shocking/reflective
- segment_type: hook/content/climax/cta
- camera_direction: zoom_in/zoom_out/pan_left/pan_right/static
- lighting_mood: golden_hour/dramatic/moody/soft/backlit

SHOT TYPES: Extreme wide shot, Wide shot, Medium shot, Close-up, Aerial view
LIGHTING: Golden hour, Blue hour, Dramatic rim lighting, Soft diffused

═══════════════════════════════════════════════════════════════

OUTPUT: Return valid JSON object with "segments" array containing exactly 12 segments."""


class LLMService:
    """
    LLM Service for generating documentary-style video scripts.

    Uses GPT-4o for intelligent, engaging content creation with
    proper storytelling structure and cinematic visual descriptions.
    """

    OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",  # Cost-optimized: 15x cheaper than gpt-4o
        base_url: str = "https://api.openai.com/v1"
    ):
        """
        Initialize LLM Service with API key.

        Default model: gpt-4o-mini (15x cheaper, sufficient for script generation)
        """
        from app.config import config
        self.api_key = api_key or config.ai.openai_api_key or ""
        self.model = model
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=120.0)

        if not self.api_key or self.api_key.startswith("PASTE_"):
            logger.warning("OpenAI API key not configured - using fallback scripts")
            self.api_key = ""
        else:
            logger.info(f"[LLM] Service initialized with {model} (cost-optimized)")

    async def generate_script(
        self,
        topic: str,
        style: ScriptStyle = ScriptStyle.DOCUMENTARY,
        duration_seconds: int = 60,
        language: str = "ru"
    ) -> GeneratedScript:
        """
        Generate a complete video script using TWO-STEP approach:

        Step 1: Generate a complete 150-word narrative story
        Step 2: Divide into 12 segments with strict rules

        This prevents repetitive phrases like "Did you know" appearing multiple times.

        Args:
            topic: The main topic/subject for the video
            style: Script style (documentary, viral, educational, etc.)
            duration_seconds: Target duration in seconds
            language: Output language code (ru, en, etc.)

        Returns:
            GeneratedScript with all segments and visual prompts
        """
        if not self.api_key:
            logger.warning("No API key - using fallback script generator")
            return self._generate_fallback_script(topic, duration_seconds, style, language)

        # Language instruction
        language_name = {"ru": "Russian", "en": "English", "kk": "Kazakh"}.get(language, language)

        try:
            logger.info(f"[STEP 1/2] Generating narrative story for: {topic}")

            # ═══════════════════════════════════════════════════════════
            # STEP 1: Generate complete narrative story (no segments)
            # ═══════════════════════════════════════════════════════════

            story_text = await self._generate_story_step1(topic, language_name)

            if not story_text or len(story_text) < 50:
                logger.warning("Step 1 failed - story too short, using fallback")
                return self._generate_fallback_script(topic, duration_seconds, style, language)

            logger.info(f"[STEP 1/2] Story generated: {len(story_text)} chars")
            logger.debug(f"Story preview: {story_text[:200]}...")

            # ═══════════════════════════════════════════════════════════
            # STEP 2: Divide story into 12 segments
            # ═══════════════════════════════════════════════════════════

            logger.info(f"[STEP 2/2] Dividing into 12 segments...")

            segments = await self._divide_into_segments_step2(story_text, topic, language_name)

            if not segments or len(segments) < 6:
                logger.warning("Step 2 failed - not enough segments, using fallback")
                return self._generate_fallback_script(topic, duration_seconds, style, language)

            # Calculate total duration
            total_duration = sum(seg.duration for seg in segments)

            script = GeneratedScript(
                title=f"История: {topic}" if language == "ru" else f"Story: {topic}",
                hook=segments[0].text if segments else "",
                segments=segments,
                cta=segments[-1].text if segments else "",
                total_duration=total_duration,
                visual_keywords=[topic],
                background_music_mood="epic",
                target_audience="general",
                topic=topic,
                style=style,
                language=language
            )

            logger.info(f"[SUCCESS] Two-step generation complete: {len(segments)} segments, {total_duration:.1f}s")
            return script

        except Exception as e:
            logger.error(f"Two-step script generation failed: {e}")
            return self._generate_fallback_script(topic, duration_seconds, style, language)

    async def _generate_story_step1(self, topic: str, language: str) -> Optional[str]:
        """
        STEP 1: Generate a complete 150-word narrative story.
        No segments, just continuous prose with facts and story arc.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        user_prompt = f"""Write a 150-word documentary story about: {topic}

LANGUAGE: Write in {language}. Make it eloquent and natural.

REMEMBER:
- ONE continuous narrative (no bullet points, no segments)
- Start with ONE attention-grabbing hook sentence
- Then ONLY facts, events, and story progression
- Build to a climax with the most shocking revelation
- End with a thought-provoking conclusion

Write the story now:"""

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": STEP1_STORY_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.9,
            "max_tokens": 500  # COST FIX: Reduced from 1000 (150 words ~= 200 tokens)
        }

        try:
            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload
            )

            if response.status_code != 200:
                logger.error(f"Step 1 API error: {response.status_code}")
                return None

            data = response.json()
            story = data["choices"][0]["message"]["content"].strip()

            # Clean up the story (remove quotes if wrapped)
            if story.startswith('"') and story.endswith('"'):
                story = story[1:-1]

            return story

        except Exception as e:
            logger.error(f"Step 1 failed: {e}")
            return None

    async def _divide_into_segments_step2(
        self,
        story: str,
        topic: str,
        language: str
    ) -> List[ScriptSegment]:
        """
        STEP 2: Divide the story into exactly 12 segments.
        Applies strict rules about which segments can have hooks.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        user_prompt = f"""Divide this story into EXACTLY 12 segments for a 60-second video:

STORY:
{story}

TOPIC: {topic}
LANGUAGE: Keep in {language}

CRITICAL RULES:
- Segment 1: HOOK (the only segment with attention-grabbing opener)
- Segments 2-10: Pure facts and story (NO "did you know", NO "here's what's crazy")
- Segment 11: CLIMAX (most shocking revelation)
- Segment 12: CTA (subscribe/follow call to action)

Return JSON with "segments" array. Each segment needs: text, duration (5.0), visual_prompt, emotion, segment_type, camera_direction, lighting_mood."""

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": STEP2_SEGMENT_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 2000,  # COST FIX: Reduced from 4000 (12 segments ~= 1500 tokens)
            "response_format": {"type": "json_object"}
        }

        try:
            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload
            )

            if response.status_code != 200:
                logger.error(f"Step 2 API error: {response.status_code}")
                return []

            data = response.json()
            content = data["choices"][0]["message"]["content"]

            # Parse JSON response
            script_data = json.loads(content)

            segments = []
            for i, seg_data in enumerate(script_data.get("segments", [])):
                # Determine segment type based on position
                if i == 0:
                    seg_type = "hook"
                elif i == 10:
                    seg_type = "climax"
                elif i == 11:
                    seg_type = "cta"
                else:
                    seg_type = "content"

                segment = ScriptSegment(
                    text=seg_data.get("text", ""),
                    duration=float(seg_data.get("duration", 5.0)),
                    visual_prompt=seg_data.get("visual_prompt", ""),
                    visual_keywords=seg_data.get("visual_keywords", [topic]),
                    emotion=seg_data.get("emotion", "neutral"),
                    segment_type=seg_data.get("segment_type", seg_type),
                    camera_direction=seg_data.get("camera_direction", "static"),
                    lighting_mood=seg_data.get("lighting_mood", "cinematic")
                )
                segments.append(segment)

            # Validate: remove repetitive phrases from segments 2-10
            segments = self._clean_repetitive_phrases(segments)

            return segments

        except json.JSONDecodeError as e:
            logger.error(f"Step 2 JSON parse failed: {e}")
            return []
        except Exception as e:
            logger.error(f"Step 2 failed: {e}")
            return []

    def _clean_repetitive_phrases(self, segments: List[ScriptSegment]) -> List[ScriptSegment]:
        """
        Post-process segments to remove forbidden phrases from content segments.
        Only Segment 1 (hook) is allowed to have attention-grabbing phrases.
        """
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

        for i, segment in enumerate(segments):
            # Only clean segments 2-10 (indices 1-9)
            if 1 <= i <= 9:
                text = segment.text
                for pattern in forbidden_patterns:
                    text = re.sub(pattern + r"[,.]?\s*", "", text)
                # Clean up double spaces
                text = re.sub(r"\s+", " ", text).strip()
                # Capitalize first letter if needed
                if text and text[0].islower():
                    text = text[0].upper() + text[1:]
                segment.text = text

        return segments

    def _generate_fallback_script(
        self,
        topic: str,
        duration: int,
        style: ScriptStyle = ScriptStyle.DOCUMENTARY,
        language: str = "ru"
    ) -> GeneratedScript:
        """
        Generate a professional fallback script when API is unavailable.

        Creates a proper documentary-style narrative with:
        - EXACTLY 12 segments for 60-second videos
        - Never starts with topic name
        - Smooth transitions between segments
        - Cinematic visual prompts for each segment
        """
        logger.info(f"Generating fallback script for: {topic} ({duration}s)")

        # ALWAYS generate exactly 12 segments for 60s
        num_segments = 12 if duration >= 60 else max(6, duration // 5)

        if language == "ru":
            segments_data = self._create_russian_documentary_segments(topic, num_segments)
        else:
            segments_data = self._create_english_documentary_segments(topic, num_segments)

        segments = []
        segment_duration = duration / len(segments_data)

        camera_directions = ["zoom_in", "zoom_out", "pan_left", "pan_right", "static", "zoom_in"]

        for i, seg_data in enumerate(segments_data):
            segment = ScriptSegment(
                text=seg_data["text"],
                duration=segment_duration,
                visual_prompt=seg_data["visual_prompt"],
                visual_keywords=seg_data.get("keywords", [topic]),
                emotion=seg_data.get("emotion", "neutral"),
                segment_type=seg_data.get("type", "content"),
                camera_direction=camera_directions[i % len(camera_directions)],
                lighting_mood=seg_data.get("lighting", "cinematic")
            )
            segments.append(segment)

        return GeneratedScript(
            title=f"Раскрывая тайны: {topic}" if language == "ru" else f"Unveiling: {topic}",
            hook=segments[0].text if segments else "",
            segments=segments,
            cta=segments[-1].text if segments else "",
            total_duration=float(duration),
            visual_keywords=[topic],
            background_music_mood="epic",
            target_audience="general",
            topic=topic,
            style=style,
            language=language
        )

    def _create_russian_documentary_segments(self, topic: str, num_segments: int) -> List[Dict]:
        """
        Create Russian documentary-style segments following NO-REPETITION policy:
        - Segment 1: ONLY segment with hook phrase
        - Segments 2-10: Pure facts and story (NO meta-phrases)
        - Segment 11: Climax
        - Segment 12: CTA
        """

        # Story-driven segments with NO repetitive phrases
        segments = [
            # Segment 1: HOOK - The ONLY segment with attention-grabbing opener
            {
                "text": f"Один человек изменил ход истории навсегда. Его имя — {topic}.",
                "visual_prompt": f"Extreme wide shot of dramatic landscape at golden hour, sun rays breaking through storm clouds, epic sense of mystery, National Geographic documentary style, cinematic 8K, photorealistic",
                "emotion": "mysterious",
                "type": "hook",
                "lighting": "golden_hour",
                "keywords": [topic, "mystery", "revelation"]
            },
            # Segment 2: FACT - Pure information, no meta-phrases
            {
                "text": "Рождённый в суровых степях, он с детства познал жестокость мира. Отец убит. Семья изгнана.",
                "visual_prompt": f"Wide establishing shot of endless steppe landscape, nomadic tents in distance, harsh beauty, dramatic side lighting, dust particles in air, National Geographic style, 8K photorealistic",
                "emotion": "somber",
                "type": "content",
                "lighting": "dramatic",
                "keywords": [topic, "childhood", "hardship"]
            },
            # Segment 3: FACT - Story progression
            {
                "text": "Годы скитаний закалили его характер. Из изгнанника он превратился в лидера.",
                "visual_prompt": f"Medium shot of lone figure against vast horizon, transformation implied, dramatic shadows, shallow depth of field, cinematic 8K, National Geographic documentary style",
                "emotion": "determined",
                "type": "content",
                "lighting": "moody",
                "keywords": ["transformation", "leader", "strength"]
            },
            # Segment 4: FACT - Building the story
            {
                "text": "Объединив разрозненные племена, он создал армию, равной которой мир не видел.",
                "visual_prompt": f"Aerial wide shot of vast army formation, thousands of warriors, epic scale, golden hour lighting, dust clouds rising, National Geographic documentary style, cinematic 8K",
                "emotion": "powerful",
                "type": "content",
                "lighting": "golden_hour",
                "keywords": ["army", "unity", "power"]
            },
            # Segment 5: FACT - Key detail
            {
                "text": "Его тактика была проста: лояльность важнее крови. Предательство каралось смертью.",
                "visual_prompt": f"Close-up of ancient weapons and armor, intricate details, dramatic rim lighting, sense of power and consequence, cinematic 8K, photorealistic",
                "emotion": "intense",
                "type": "content",
                "lighting": "dramatic",
                "keywords": ["loyalty", "tactics", "justice"]
            },
            # Segment 6: FACT - Expansion of story
            {
                "text": "За двадцать лет его войска прошли от Тихого океана до Восточной Европы.",
                "visual_prompt": f"Epic map visualization, vast territories highlighted, sense of incredible expansion, sweeping camera movement, National Geographic style, cinematic 8K",
                "emotion": "amazed",
                "type": "content",
                "lighting": "dramatic",
                "keywords": ["expansion", "conquest", "empire"]
            },
            # Segment 7: FACT - Surprising detail
            {
                "text": "Города, сдавшиеся без боя, процветали. Сопротивлявшиеся — стирались с лица земли.",
                "visual_prompt": f"Split composition showing contrasts, ancient city flourishing vs ruins, dramatic lighting, sense of choice and consequence, cinematic 8K, photorealistic",
                "emotion": "tense",
                "type": "content",
                "lighting": "moody",
                "keywords": ["mercy", "destruction", "choice"]
            },
            # Segment 8: FACT - Legacy building
            {
                "text": "Шёлковый путь расцвёл под его защитой. Торговля, наука, культура — всё это он принёс миру.",
                "visual_prompt": f"Wide shot of ancient Silk Road caravan, diverse traders and goods, golden sunset, sense of prosperity and exchange, National Geographic style, cinematic 8K",
                "emotion": "hopeful",
                "type": "content",
                "lighting": "golden_hour",
                "keywords": ["silk road", "trade", "culture"]
            },
            # Segment 9: FACT - Mystery element
            {
                "text": "Когда он умер в 1227 году, место его захоронения скрыли навсегда.",
                "visual_prompt": f"Mysterious burial scene, hidden valley in mountains, fog and mist, sense of eternal secret, dramatic shadows, cinematic 8K, photorealistic",
                "emotion": "mysterious",
                "type": "content",
                "lighting": "moody",
                "keywords": ["death", "mystery", "burial"]
            },
            # Segment 10: FACT - Modern connection
            {
                "text": "Сегодня 40 миллионов человек несут его ДНК. Его кровь течёт в жилах народов Азии.",
                "visual_prompt": f"Modern DNA visualization merged with ancient imagery, connection through time, scientific wonder, cinematic 8K, National Geographic documentary style",
                "emotion": "wonder",
                "type": "content",
                "lighting": "soft",
                "keywords": ["DNA", "legacy", "descendants"]
            },
            # Segment 11: CLIMAX - The big revelation
            {
                "text": "Его империя была больше, чем владения Рима, Александра и Наполеона вместе взятые.",
                "visual_prompt": f"Epic comparison visualization, vast empire overlaid on modern map, sense of incomprehensible scale, dramatic lighting, cinematic masterpiece composition, 8K photorealistic",
                "emotion": "shocking",
                "type": "climax",
                "lighting": "dramatic",
                "keywords": ["empire", "scale", "history"]
            },
            # Segment 12: CTA - Call to action
            {
                "text": "Подписывайтесь, чтобы узнать продолжение. Впереди — ещё более невероятные истории.",
                "visual_prompt": f"Clean modern composition, warm inviting colors, professional documentary end card atmosphere, sense of more to come, cinematic 8K, photorealistic",
                "emotion": "engaging",
                "type": "cta",
                "lighting": "soft",
                "keywords": ["subscribe", "continue", "story"]
            },
        ]

        # Return exactly the requested number of segments
        return segments[:num_segments]

    def _create_english_documentary_segments(self, topic: str, num_segments: int) -> List[Dict]:
        """
        Create English documentary-style segments following NO-REPETITION policy:
        - Segment 1: ONLY segment with hook phrase
        - Segments 2-10: Pure facts and story (NO meta-phrases)
        - Segment 11: Climax
        - Segment 12: CTA
        """

        # Story-driven segments with NO repetitive phrases
        segments = [
            # Segment 1: HOOK - The ONLY segment with attention-grabbing opener
            {
                "text": f"One man changed the course of history forever. His name was {topic}.",
                "visual_prompt": f"Extreme wide shot of dramatic landscape at golden hour, sun rays breaking through storm clouds, epic sense of mystery, National Geographic documentary style, cinematic 8K, photorealistic",
                "emotion": "mysterious",
                "type": "hook",
                "lighting": "golden_hour",
                "keywords": [topic, "mystery", "revelation"]
            },
            # Segment 2: FACT - Pure information, no meta-phrases
            {
                "text": "Born in the harsh steppes, he knew cruelty from childhood. His father murdered. His family exiled.",
                "visual_prompt": f"Wide establishing shot of endless steppe landscape, nomadic tents in distance, harsh beauty, dramatic side lighting, dust particles in air, National Geographic style, 8K photorealistic",
                "emotion": "somber",
                "type": "content",
                "lighting": "dramatic",
                "keywords": [topic, "childhood", "hardship"]
            },
            # Segment 3: FACT - Story progression
            {
                "text": "Years of wandering forged his character. From outcast, he transformed into a leader.",
                "visual_prompt": f"Medium shot of lone figure against vast horizon, transformation implied, dramatic shadows, shallow depth of field, cinematic 8K, National Geographic documentary style",
                "emotion": "determined",
                "type": "content",
                "lighting": "moody",
                "keywords": ["transformation", "leader", "strength"]
            },
            # Segment 4: FACT - Building the story
            {
                "text": "Uniting scattered tribes, he built an army the world had never seen before.",
                "visual_prompt": f"Aerial wide shot of vast army formation, thousands of warriors, epic scale, golden hour lighting, dust clouds rising, National Geographic documentary style, cinematic 8K",
                "emotion": "powerful",
                "type": "content",
                "lighting": "golden_hour",
                "keywords": ["army", "unity", "power"]
            },
            # Segment 5: FACT - Key detail
            {
                "text": "His strategy was simple: loyalty above blood. Betrayal meant death.",
                "visual_prompt": f"Close-up of ancient weapons and armor, intricate details, dramatic rim lighting, sense of power and consequence, cinematic 8K, photorealistic",
                "emotion": "intense",
                "type": "content",
                "lighting": "dramatic",
                "keywords": ["loyalty", "tactics", "justice"]
            },
            # Segment 6: FACT - Expansion of story
            {
                "text": "In twenty years, his forces swept from the Pacific Ocean to Eastern Europe.",
                "visual_prompt": f"Epic map visualization, vast territories highlighted, sense of incredible expansion, sweeping camera movement, National Geographic style, cinematic 8K",
                "emotion": "amazed",
                "type": "content",
                "lighting": "dramatic",
                "keywords": ["expansion", "conquest", "empire"]
            },
            # Segment 7: FACT - Surprising detail
            {
                "text": "Cities that surrendered flourished. Those that resisted were erased from the map.",
                "visual_prompt": f"Split composition showing contrasts, ancient city flourishing vs ruins, dramatic lighting, sense of choice and consequence, cinematic 8K, photorealistic",
                "emotion": "tense",
                "type": "content",
                "lighting": "moody",
                "keywords": ["mercy", "destruction", "choice"]
            },
            # Segment 8: FACT - Legacy building
            {
                "text": "The Silk Road thrived under his protection. Trade, science, culture — he brought all this to the world.",
                "visual_prompt": f"Wide shot of ancient Silk Road caravan, diverse traders and goods, golden sunset, sense of prosperity and exchange, National Geographic style, cinematic 8K",
                "emotion": "hopeful",
                "type": "content",
                "lighting": "golden_hour",
                "keywords": ["silk road", "trade", "culture"]
            },
            # Segment 9: FACT - Mystery element
            {
                "text": "When he died in 1227, his burial site was hidden forever.",
                "visual_prompt": f"Mysterious burial scene, hidden valley in mountains, fog and mist, sense of eternal secret, dramatic shadows, cinematic 8K, photorealistic",
                "emotion": "mysterious",
                "type": "content",
                "lighting": "moody",
                "keywords": ["death", "mystery", "burial"]
            },
            # Segment 10: FACT - Modern connection
            {
                "text": "Today, 40 million people carry his DNA. His blood flows through the peoples of Asia.",
                "visual_prompt": f"Modern DNA visualization merged with ancient imagery, connection through time, scientific wonder, cinematic 8K, National Geographic documentary style",
                "emotion": "wonder",
                "type": "content",
                "lighting": "soft",
                "keywords": ["DNA", "legacy", "descendants"]
            },
            # Segment 11: CLIMAX - The big revelation
            {
                "text": "His empire was larger than Rome, Alexander, and Napoleon combined.",
                "visual_prompt": f"Epic comparison visualization, vast empire overlaid on modern map, sense of incomprehensible scale, dramatic lighting, cinematic masterpiece composition, 8K photorealistic",
                "emotion": "shocking",
                "type": "climax",
                "lighting": "dramatic",
                "keywords": ["empire", "scale", "history"]
            },
            # Segment 12: CTA - Call to action
            {
                "text": "Subscribe to discover what happens next. More incredible stories are coming.",
                "visual_prompt": f"Clean modern composition, warm inviting colors, professional documentary end card atmosphere, sense of more to come, cinematic 8K, photorealistic",
                "emotion": "engaging",
                "type": "cta",
                "lighting": "soft",
                "keywords": ["subscribe", "continue", "story"]
            },
        ]

        # Return exactly the requested number of segments
        return segments[:num_segments]

    async def analyze_viral_potential(self, script: GeneratedScript) -> Dict[str, Any]:
        """Analyze the viral potential of a script."""
        analysis = {
            "hook_strength": self._analyze_hook(script.hook),
            "pacing_score": self._analyze_pacing(script.segments),
            "cta_effectiveness": self._analyze_cta(script.cta),
            "overall_score": 0,
            "suggestions": []
        }

        analysis["overall_score"] = (
            analysis["hook_strength"] * 0.4 +
            analysis["pacing_score"] * 0.3 +
            analysis["cta_effectiveness"] * 0.3
        )

        return analysis

    def _analyze_hook(self, hook: str) -> float:
        """Analyze hook strength (0-100)."""
        score = 50
        power_words = ["секрет", "шок", "никто", "всегда", "никогда", "топ", "история", "тайна"]
        for word in power_words:
            if word.lower() in hook.lower():
                score += 10
        if "?" in hook:
            score += 15
        if len(hook) < 100:
            score += 10
        return min(100, score)

    def _analyze_pacing(self, segments: List[ScriptSegment]) -> float:
        """Analyze pacing (0-100)."""
        if not segments:
            return 0
        avg_duration = sum(s.duration for s in segments) / len(segments)
        if 4 <= avg_duration <= 6:
            return 100
        elif 3 <= avg_duration <= 8:
            return 80
        return 60

    def _analyze_cta(self, cta: str) -> float:
        """Analyze CTA effectiveness (0-100)."""
        score = 50
        action_words = ["подпис", "лайк", "коммент", "сохран", "поделит", "subscribe", "follow"]
        for word in action_words:
            if word.lower() in cta.lower():
                score += 15
        return min(100, score)

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
