"""
Agent 3: Technical Director (The Orchestrator)

Task: Manage the flow between agents, validate outputs, handle errors,
and ensure all data is saved to SQLite.

Responsibilities:
- Coordinate Agent 1 (Storyteller) and Agent 2 (Visual Director)
- Validate outputs from each agent
- Handle billing errors (STOP if 400)
- Save VideoJob and VideoSegments to SQLite
- Ensure 100% data retention
"""

import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from pathlib import Path

from .storyteller import MasterStoryteller, ScriptStyle, StoryResult
from .visual_director import VisualDirector, VisualSegment, SegmentationResult
from .story_analyzer import StoryAnalyzer, VisualBible

logger = logging.getLogger(__name__)


@dataclass
class OrchestratedScript:
    """Complete orchestrated script ready for video generation."""
    topic: str
    style: ScriptStyle
    language: str

    # From Storyteller
    narrative: str
    hook: str
    word_count: int

    # From Visual Director
    segments: List[VisualSegment]
    style_consistency_string: str
    total_duration: float

    # Metadata
    title: str
    cta: str
    visual_keywords: List[str]
    background_music_mood: str

    # Art Style for DALL-E
    art_style: str = "photorealism"

    # Visual Bible for consistency
    visual_bible: Optional[VisualBible] = None

    # Status
    used_fallback_story: bool = False
    used_fallback_segments: bool = False
    used_visual_bible: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "topic": self.topic,
            "style": self.style.value,
            "language": self.language,
            "narrative": self.narrative,
            "hook": self.hook,
            "word_count": self.word_count,
            "title": self.title,
            "cta": self.cta,
            "segments": [seg.to_dict() for seg in self.segments],
            "style_consistency_string": self.style_consistency_string,
            "total_duration": self.total_duration,
            "visual_keywords": self.visual_keywords,
            "background_music_mood": self.background_music_mood,
            "art_style": self.art_style,
            "visual_bible": self.visual_bible.to_dict() if self.visual_bible else None,
            "used_fallback_story": self.used_fallback_story,
            "used_fallback_segments": self.used_fallback_segments,
            "used_visual_bible": self.used_visual_bible,
        }


class TechnicalDirector:
    """
    Agent 3: Technical Director (Orchestrator)

    Manages the multi-agent workflow:
    1. Calls Agent 1 (Storyteller) to generate narrative
    2. Validates story output
    3. Calls Agent 2 (Visual Director) to segment story
    4. Validates segments
    5. Saves everything to SQLite via the database repo
    6. Handles ALL errors gracefully (billing errors = STOP)
    """

    def __init__(self, api_key: Optional[str] = None):
        from app.config import config
        self.api_key = api_key or config.ai.openai_api_key or ""

        # Initialize sub-agents
        self.storyteller = MasterStoryteller(api_key=self.api_key)
        self.story_analyzer = StoryAnalyzer(api_key=self.api_key)
        self.visual_director = VisualDirector(api_key=self.api_key)

        logger.info("[ORCHESTRATOR] Technical Director initialized")
        logger.info("[ORCHESTRATOR] Agent 1 (Storyteller): Ready")
        logger.info("[ORCHESTRATOR] Agent 1.5 (StoryAnalyzer): Ready")
        logger.info("[ORCHESTRATOR] Agent 2 (Visual Director): Ready")

    async def orchestrate_script_generation(
        self,
        topic: str,
        style: ScriptStyle = ScriptStyle.DOCUMENTARY,
        language: str = "ru",
        duration_seconds: int = 60,
        art_style: str = "photorealism",
        custom_idea: Optional[str] = None,
        idea_mode: str = "expand"
    ) -> OrchestratedScript:
        """
        Orchestrate the full script generation workflow.

        Flow:
        1. Agent 1 generates/processes narrative (from topic or custom_idea)
        2. Validate narrative (length, quality)
        3. Agent 2 segments into visual parts
        4. Validate segments (count, structure)
        5. Return complete orchestrated script

        Args:
            topic: The main topic/subject for the video
            style: Script style (viral, documentary, motivational, storytelling)
            language: Output language code
            duration_seconds: Target duration (default 60s)
            art_style: Visual style for DALL-E
            custom_idea: User's own idea/draft to be processed
            idea_mode: How to process custom_idea:
                - 'expand': Develop into full structured script
                - 'polish': Improve structure, keep content closely
                - 'strict': Keep as close as possible to original

        Returns:
            OrchestratedScript ready for video generation
        """
        logger.info("=" * 70)
        logger.info("[ORCHESTRATOR] STARTING MULTI-AGENT SCRIPT GENERATION")
        logger.info("=" * 70)
        logger.info(f"  Topic: {topic}")
        logger.info(f"  Style: {style.value.upper()}")
        logger.info(f"  Art Style: {art_style.upper()}")
        logger.info(f"  Language: {language}")
        logger.info(f"  Target Duration: {duration_seconds}s")
        if custom_idea:
            logger.info(f"  Custom Idea: YES ({len(custom_idea)} chars)")
            logger.info(f"  Idea Mode: {idea_mode.upper()}")
        logger.info("=" * 70)

        used_fallback_story = False
        used_fallback_segments = False

        # ═══════════════════════════════════════════════════════════════════
        # PHASE 1: AGENT 1 - MASTER STORYTELLER
        # ═══════════════════════════════════════════════════════════════════
        if custom_idea:
            logger.info("[ORCHESTRATOR] PHASE 1: Processing Custom Idea with Agent 1...")
        else:
            logger.info("[ORCHESTRATOR] PHASE 1: Calling Agent 1 (Master Storyteller)...")

        story_result: StoryResult = await self.storyteller.generate_story(
            topic=topic,
            style=style,
            language=language,
            duration_seconds=duration_seconds,
            custom_idea=custom_idea,
            idea_mode=idea_mode
        )

        # Validate story output
        if not self._validate_story(story_result):
            logger.warning("[ORCHESTRATOR] Story validation failed - using fallback")
            story_result = self.storyteller._generate_fallback_story(topic, style, language)
            used_fallback_story = True

        if story_result.error:
            used_fallback_story = True

        logger.info(f"[ORCHESTRATOR] PHASE 1 COMPLETE: {story_result.word_count} words generated")
        logger.info(f"[ORCHESTRATOR] Hook: {story_result.hook[:80]}...")

        # ═══════════════════════════════════════════════════════════════════
        # PHASE 1.5: STORY ANALYZER - CREATE VISUAL BIBLE
        # ═══════════════════════════════════════════════════════════════════
        logger.info("[ORCHESTRATOR] PHASE 1.5: Analyzing story for Visual Bible...")

        visual_bible: Optional[VisualBible] = None
        used_visual_bible = False

        try:
            # Prepare segments for analysis (simple text split)
            from .visual_director import get_segment_count
            segment_count = get_segment_count(duration_seconds)
            narrative_sentences = story_result.narrative.replace('!', '.').replace('?', '.').split('.')
            sentences_per_segment = max(1, len(narrative_sentences) // segment_count)

            temp_segments = []
            for i in range(segment_count):
                start = i * sentences_per_segment
                end = start + sentences_per_segment
                text = '. '.join(narrative_sentences[start:end]).strip()
                if text:
                    temp_segments.append({"text": text, "index": i})

            visual_bible = await self.story_analyzer.analyze_story(
                full_script=story_result.narrative,
                segments=temp_segments,
                topic=topic,
                style=style.value
            )

            if visual_bible and len(visual_bible.characters) > 0:
                used_visual_bible = True
                logger.info(f"[ORCHESTRATOR] PHASE 1.5 COMPLETE: Visual Bible created")
                logger.info(f"  - Characters: {len(visual_bible.characters)}")
                logger.info(f"  - Locations: {len(visual_bible.locations)}")
                logger.info(f"  - Atmosphere: {visual_bible.atmosphere.get('mood', 'unknown')}")
            else:
                logger.warning("[ORCHESTRATOR] Visual Bible empty - will use standard segmentation")

        except Exception as e:
            logger.warning(f"[ORCHESTRATOR] Story analysis failed: {e} - continuing without Visual Bible")
            visual_bible = None

        # ═══════════════════════════════════════════════════════════════════
        # PHASE 2: AGENT 2 - VISUAL DIRECTOR
        # ═══════════════════════════════════════════════════════════════════
        logger.info("[ORCHESTRATOR] PHASE 2: Calling Agent 2 (Visual Director)...")

        segment_result: SegmentationResult
        if visual_bible and used_visual_bible:
            logger.info("[ORCHESTRATOR] Using Visual Bible for consistent segmentation...")
            segment_result = await self.visual_director.segment_story_with_visual_bible(
                narrative=story_result.narrative,
                topic=topic,
                visual_bible=visual_bible,
                style=style,
                language=language,
                duration_seconds=duration_seconds,
                art_style=art_style
            )
        else:
            logger.info("[ORCHESTRATOR] Using standard segmentation...")
            segment_result = await self.visual_director.segment_story(
                narrative=story_result.narrative,
                topic=topic,
                style=style,
                language=language,
                duration_seconds=duration_seconds,
                art_style=art_style
            )

        # Validate segments
        if not self._validate_segments(segment_result):
            logger.warning("[ORCHESTRATOR] Segment validation failed - using fallback")
            from .visual_director import get_segment_count
            segment_count = get_segment_count(duration_seconds)
            segment_result = self.visual_director._generate_fallback_segments(
                story_result.narrative, topic, style,
                segment_result.style_consistency_string, language,
                segment_count, duration_seconds, art_style
            )
            used_fallback_segments = True

        if segment_result.error:
            used_fallback_segments = True

        logger.info(f"[ORCHESTRATOR] PHASE 2 COMPLETE: {len(segment_result.segments)} segments created")

        # ═══════════════════════════════════════════════════════════════════
        # PHASE 3: ASSEMBLY
        # ═══════════════════════════════════════════════════════════════════
        logger.info("[ORCHESTRATOR] PHASE 3: Assembling final script...")

        # Determine background music mood based on style
        music_moods = {
            ScriptStyle.VIRAL: "energetic",
            ScriptStyle.DOCUMENTARY: "epic",
            ScriptStyle.MOTIVATIONAL: "inspiring",
            ScriptStyle.STORYTELLING: "cinematic",
            ScriptStyle.EDUCATIONAL: "calm",
            ScriptStyle.MYSTERY: "suspenseful",
            ScriptStyle.HISTORICAL: "orchestral"
        }

        orchestrated = OrchestratedScript(
            topic=topic,
            style=style,
            language=language,
            narrative=story_result.narrative,
            hook=story_result.hook,
            word_count=story_result.word_count,
            segments=segment_result.segments,
            style_consistency_string=segment_result.style_consistency_string,
            total_duration=segment_result.total_duration,
            title=self._generate_title(topic, style, language),
            cta=segment_result.segments[-1].text if segment_result.segments else "",
            visual_keywords=[topic],
            background_music_mood=music_moods.get(style, "epic"),
            art_style=art_style,
            visual_bible=visual_bible,
            used_fallback_story=used_fallback_story,
            used_fallback_segments=used_fallback_segments,
            used_visual_bible=used_visual_bible
        )

        logger.info("=" * 70)
        logger.info("[ORCHESTRATOR] MULTI-AGENT GENERATION COMPLETE")
        logger.info("=" * 70)
        logger.info(f"  Title: {orchestrated.title}")
        logger.info(f"  Segments: {len(orchestrated.segments)}")
        logger.info(f"  Duration: {orchestrated.total_duration:.1f}s")
        logger.info(f"  Visual Bible: {'YES' if used_visual_bible else 'NO'}")
        logger.info(f"  Fallback Story: {used_fallback_story}")
        logger.info(f"  Fallback Segments: {used_fallback_segments}")
        logger.info("=" * 70)

        return orchestrated

    def _validate_story(self, story: StoryResult) -> bool:
        """Validate story output from Agent 1."""
        if not story.success:
            return False

        if not story.narrative or len(story.narrative) < 100:
            logger.warning(f"[ORCHESTRATOR] Story too short: {len(story.narrative)} chars")
            return False

        if story.word_count < 50:
            logger.warning(f"[ORCHESTRATOR] Not enough words: {story.word_count}")
            return False

        return True

    def _validate_segments(self, result: SegmentationResult) -> bool:
        """Validate segments from Agent 2."""
        if not result.success:
            return False

        if not result.segments or len(result.segments) < 6:
            logger.warning(f"[ORCHESTRATOR] Not enough segments: {len(result.segments)}")
            return False

        # Check each segment has required fields
        for seg in result.segments:
            if not seg.text or len(seg.text) < 5:
                logger.warning(f"[ORCHESTRATOR] Segment {seg.index} has no/short text")
                return False
            if not seg.visual_prompt or len(seg.visual_prompt) < 20:
                logger.warning(f"[ORCHESTRATOR] Segment {seg.index} has no/short visual prompt")
                return False

        return True

    def _generate_title(self, topic: str, style: ScriptStyle, language: str) -> str:
        """Generate a title based on topic and style."""
        if language == "ru":
            titles = {
                ScriptStyle.VIRAL: f"🔥 ШОК! {topic}",
                ScriptStyle.DOCUMENTARY: f"История: {topic}",
                ScriptStyle.MOTIVATIONAL: f"💪 {topic}: Путь к успеху",
                ScriptStyle.STORYTELLING: f"📖 {topic}: История одного...",
                ScriptStyle.EDUCATIONAL: f"🎓 {topic}: Полный разбор",
                ScriptStyle.MYSTERY: f"🔍 Тайна {topic}",
                ScriptStyle.HISTORICAL: f"⏳ {topic}: Как это было"
            }
        else:
            titles = {
                ScriptStyle.VIRAL: f"🔥 SHOCKING! {topic}",
                ScriptStyle.DOCUMENTARY: f"Story: {topic}",
                ScriptStyle.MOTIVATIONAL: f"💪 {topic}: Path to Success",
                ScriptStyle.STORYTELLING: f"📖 {topic}: One Person's Journey",
                ScriptStyle.EDUCATIONAL: f"🎓 {topic}: Complete Breakdown",
                ScriptStyle.MYSTERY: f"🔍 The Mystery of {topic}",
                ScriptStyle.HISTORICAL: f"⏳ {topic}: How It Happened"
            }

        return titles.get(style, f"История: {topic}" if language == "ru" else f"Story: {topic}")

    def convert_to_legacy_format(self, orchestrated: OrchestratedScript) -> Dict[str, Any]:
        """
        Convert OrchestratedScript to the legacy format expected by faceless_engine.

        This ensures backward compatibility with existing code.
        """
        return {
            "title": orchestrated.title,
            "hook": orchestrated.hook,
            "topic": orchestrated.topic,
            "segments": [
                {
                    "text": seg.text,
                    "duration": seg.duration,
                    "visual_prompt": seg.visual_prompt,
                    "visual_keywords": seg.visual_keywords,
                    "emotion": seg.emotion,
                    "segment_type": seg.segment_type,
                    "camera_direction": seg.camera_direction,
                    "lighting_mood": seg.lighting_mood
                }
                for seg in orchestrated.segments
            ],
            "cta": orchestrated.cta,
            "total_duration": orchestrated.total_duration,
            "visual_keywords": orchestrated.visual_keywords,
            "background_music_mood": orchestrated.background_music_mood,
            "target_audience": "general",
            "style": orchestrated.style.value,
            "language": orchestrated.language,
            "narrative": orchestrated.narrative,
            "style_consistency_string": orchestrated.style_consistency_string,
            "art_style": orchestrated.art_style,
            "used_fallback_story": orchestrated.used_fallback_story,
            "used_fallback_segments": orchestrated.used_fallback_segments
        }

    async def close(self):
        """Close all agent connections."""
        await self.storyteller.close()
        await self.story_analyzer.close()
        await self.visual_director.close()
        logger.info("[ORCHESTRATOR] All agents closed")


# ═══════════════════════════════════════════════════════════════════════════════
# BILLING ERROR HANDLER
# ═══════════════════════════════════════════════════════════════════════════════

class BillingErrorHandler:
    """
    Handles billing errors from OpenAI API.
    When a 400 billing error is detected, STOPS the entire process.
    """

    BILLING_KEYWORDS = [
        "billing", "insufficient_quota", "exceeded", "quota",
        "payment", "credit", "balance", "limit reached",
        "rate_limit_exceeded", "insufficient_funds"
    ]

    @staticmethod
    def is_billing_error(status_code: int, error_text: str) -> bool:
        """Check if the error is a billing-related error."""
        if status_code != 400:
            return False

        error_lower = error_text.lower()
        return any(kw in error_lower for kw in BillingErrorHandler.BILLING_KEYWORDS)

    @staticmethod
    def handle_billing_error(error_text: str):
        """Handle a billing error by logging and raising an exception."""
        logger.critical("!" * 70)
        logger.critical("!   [BILLING ERROR] NO CREDITS / QUOTA EXCEEDED")
        logger.critical("!   Check your OpenAI billing at:")
        logger.critical("!   https://platform.openai.com/account/billing")
        logger.critical("!" * 70)
        logger.critical(f"Error details: {error_text[:200]}")

        raise BillingError(f"OpenAI Billing Error: {error_text[:200]}")


class BillingError(Exception):
    """Raised when a billing error is detected - STOPS the entire process."""
    pass
