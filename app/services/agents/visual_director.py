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
class GlobalSceneContext:
    """
    Global visual context for entire video.
    Ensures all frames share consistent visual language.
    
    This context is extracted from the FULL NARRATIVE (not just topic)
    to prevent mismatches like "Kazakhstan story → Egyptian pyramids".
    
    NEW: 30/70 Rule - Max 30-40% character shots, 60-70% environment/action/details
    NEW: Gender Detection - "ОН" → MALE, "ОНА" → FEMALE (prevents wrong gender in images)
    """
    # Core identifiers
    topic: str
    era: str  # "15th century", "modern day", "ancient times"
    region: str  # "Central Asian steppe", "Silicon Valley", "Nile valley"
    
    # Visual elements (required fields first)
    architecture: List[str]  # ["yurts", "nomadic tents"] or ["pyramids", "temples"]
    people_description: str  # "MAN, Kazakh warrior" or "WOMAN, Tech CEO" (WITH GENDER!)
    key_objects: List[str]  # ["horses", "weapons"]
    
    # Atmospheric
    atmosphere: str  # "epic historical", "futuristic", "mysterious"
    lighting_style: str  # "golden hour", "dramatic shadows", "bright modern"
    color_palette: List[str]  # ["earth tones", "browns", "gold"]
    
    # Important negatives
    avoid_elements: List[str]  # ["pyramids", "pharaohs"] if topic is Kazakhstan
    
    # Technical
    art_style: str  # "photorealism", "anime", etc.
    
    # Optional fields with defaults (MUST be last!)
    gender: str = "neutral"  # "male", "female", or "neutral" - CRITICAL for correct generation!
    
    def to_prompt_prefix(self) -> str:
        """Generate consistent prefix for all prompts."""
        return f"{self.era}, {self.region}, {self.atmosphere} atmosphere, {self.lighting_style}"
    
    def get_character_description(self) -> str:
        """Get consistent character description for all frames."""
        return self.people_description


# ═══════════════════════════════════════════════════════════════════════════════
# SHOT VARIETY SYSTEM (30/70 Rule)
# ═══════════════════════════════════════════════════════════════════════════════

class ShotType:
    """Shot types for visual variety."""
    WIDE = "wide_shot"              # Environment, landscape, establishing shot
    MEDIUM = "medium_shot"          # Action, interaction, context
    CLOSE_UP = "close_up"           # Details, objects, emotions
    PORTRAIT = "portrait"           # Character face/upper body
    POV = "pov_shot"               # Point of view, first person
    DETAIL = "detail_shot"         # Extreme close-up of object
    AERIAL = "aerial_shot"         # Bird's eye view

    @staticmethod
    def is_character_focused(shot_type: str) -> bool:
        """Check if shot type focuses on character face."""
        return shot_type in [ShotType.PORTRAIT, ShotType.MEDIUM]
    
    @staticmethod
    def get_environment_shots() -> List[str]:
        """Get list of environment/non-character shots."""
        return [ShotType.WIDE, ShotType.CLOSE_UP, ShotType.POV, ShotType.DETAIL, ShotType.AERIAL]


class VisualVarietyTracker:
    """
    Tracks shot variety to enforce 30/70 rule.
    
    Rules:
    - Max 30-40% character-focused shots (portrait, medium with character)
    - No more than 2 consecutive character shots
    - Minimum 60-70% environment/action/detail shots
    """
    
    def __init__(self, total_segments: int):
        self.total_segments = total_segments
        self.shot_history: List[str] = []
        self.character_count = 0
        self.max_character_shots = int(total_segments * 0.4)  # 40% max
        
    def can_use_character_shot(self, segment_index: int) -> bool:
        """Check if we can use a character shot at this position."""
        # Check 30/70 rule
        if self.character_count >= self.max_character_shots:
            return False
        
        # Check consecutive rule (no more than 2 in a row)
        if len(self.shot_history) >= 2:
            last_two = self.shot_history[-2:]
            if all(ShotType.is_character_focused(shot) for shot in last_two):
                return False  # Already have 2 consecutive character shots
        
        return True
    
    def record_shot(self, shot_type: str):
        """Record a shot type."""
        self.shot_history.append(shot_type)
        if ShotType.is_character_focused(shot_type):
            self.character_count += 1
    
    def get_recommended_shot(self, segment_text: str, segment_index: int) -> str:
        """
        Recommend shot type based on:
        1. Segment text content (action words, nouns)
        2. Current shot history (variety)
        3. 30/70 rule
        """
        text_lower = segment_text.lower()
        
        # Check if text mentions action/objects (should NOT be character)
        action_keywords = ['battle', 'war', 'gold', 'treasure', 'building', 'landscape', 
                          'mountain', 'city', 'weapon', 'artifact', 'ceremony', 'ritual',
                          'journey', 'trade', 'empire', 'territory']
        
        if any(keyword in text_lower for keyword in action_keywords):
            # Text describes ACTION or OBJECT - use environment/detail shot
            if 'battle' in text_lower or 'war' in text_lower:
                return ShotType.WIDE  # Battle scene
            elif 'gold' in text_lower or 'treasure' in text_lower:
                return ShotType.DETAIL  # Close-up of gold
            elif 'landscape' in text_lower or 'territory' in text_lower:
                return ShotType.AERIAL  # Aerial view
            else:
                return ShotType.CLOSE_UP  # Detail shot
        
        # Check if we can use character shot
        if self.can_use_character_shot(segment_index):
            # First segment (hook) - often character is good
            if segment_index == 0:
                return ShotType.PORTRAIT
            # Use character sparingly
            elif segment_index % 3 == 0:  # Every 3rd segment
                return ShotType.MEDIUM
            else:
                return ShotType.WIDE
        else:
            # Must use environment shot
            # Vary between wide, detail, aerial
            if segment_index % 2 == 0:
                return ShotType.WIDE
            else:
                return ShotType.DETAIL
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about shot variety."""
        total = len(self.shot_history)
        return {
            "total_shots": total,
            "character_shots": self.character_count,
            "character_percentage": (self.character_count / total * 100) if total > 0 else 0,
            "passes_30_70_rule": self.character_count <= self.max_character_shots
        }


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

# ⚡ OPTIMIZED: Compressed descriptions (-50% tokens)
ART_STYLE_PROMPTS = {
    "photorealism": "hyper-realistic 8K photograph, natural lighting, documentary style",
    "anime": "Japanese anime, expressive eyes, vibrant colors, clean line art",
    "ghibli": "Ghibli anime, watercolor textures, ethereal landscapes, nostalgic",
    "disney": "Disney animation, cel shading, warm palette, storybook quality",
    "comic": "comic book style, bold ink, halftone dots, graphic novel",
    "minecraft": "blocky voxel art, cubic 3D, vibrant colors, sandbox game",
    "lego": "LEGO brick style, toy aesthetic, glossy plastic, miniature diorama",
    "gtav": "GTA V style, gritty urban, dramatic shadows, neon lights",
    "watercolor": "watercolor painting, soft bleeds, paper texture, impressionistic",
    "expressionism": "expressionist art, Van Gogh strokes, emotional palette",
    "charcoal": "charcoal drawing, high contrast, textured paper, realistic shading",
    "pixel": "16-bit pixel art, retro gaming, limited palette, crisp edges",
    "creepy": "Tim Burton style, gothic cartoon, eerie shadows, horror animation",
    "childrens": "children's book, soft pastels, friendly characters, gentle watercolor",
}

# Default art style if none specified
DEFAULT_ART_STYLE = "photorealism"


# ═══════════════════════════════════════════════════════════════════════════════
# VISUAL CONSISTENCY TEMPLATES BY SCRIPT STYLE
# ═══════════════════════════════════════════════════════════════════════════════

# ⚡ OPTIMIZED: Compressed (-60% tokens)
STYLE_VISUAL_CONSISTENCY = {
    ScriptStyle.VIRAL: "4K social media, vibrant colors, high contrast, trending",
    ScriptStyle.DOCUMENTARY: "NatGeo style, cinematic 8K, natural tones, documentary",
    ScriptStyle.MOTIVATIONAL: "golden hour, warm tones, inspirational, soft flare",
    ScriptStyle.STORYTELLING: "epic cinematography, GoT style, rich design, cinematic",
    ScriptStyle.EDUCATIONAL: "clean infographic, TED quality, modern minimal",
    ScriptStyle.MYSTERY: "noir lighting, deep shadows, moody, atmospheric fog",
    ScriptStyle.HISTORICAL: "period-accurate, museum quality, sepia-tinted, authentic"
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


# ⚡ OPTIMIZED: Compressed from 1200 to 400 tokens (-67% tokens!)
SEGMENTATION_SYSTEM_PROMPT_TEMPLATE = """Visual Prompt Engineer for Nano Banana. Create {segment_count} segments ({duration}s video).

FORMAT (ENGLISH ONLY):
[SUBJECT], [ACTION], [ENVIRONMENT], [LIGHTING], [CAMERA], [STYLE]

STRUCTURE:
• S1 (hook): Attention-grabbing visual
• S2-{content_end} (content): Story facts
• S{climax_num} (climax): Peak moment
• S{cta_num} (cta): Call to action

30/70 RULE (CRITICAL):
• MAX 30%: Character shots (portrait/medium)
• MIN 70%: Environment (wide/aerial/detail/POV)

SHOT LOGIC (based on text):
• battle/war → WIDE battlefield
• gold/treasure → DETAIL coins
• building/empire → AERIAL architecture
• weapon/artifact → DETAIL object
• Character: S1 + every 3rd (max 2 consecutive)

CONSISTENCY:
• Same character = IDENTICAL description
• Repeat visuals = IDENTICAL prompt (saves cost)

JSON OUTPUT:
{{
  "segments": [
    {{"index": 0, "text": "...", "duration": 5.0, "visual_prompt": "...", 
      "emotion": "mysterious", "segment_type": "hook", 
      "camera_direction": "zoom_in", "lighting_mood": "golden_hour"}},
    ...
  ]
}}

RULES:
• 15-25 words text/segment
• 40-60 words prompt (English, no text/watermarks)
• Vary: wide, aerial, detail, POV, portrait
"""


class VisualDirector:
    """
    Agent 2: Visual Director (Prompt Engineer for Nano Banana)

    Takes a narrative story and slices it into visual segments
    with consistent, technically-precise prompts for Nano Banana.
    
    KEY PRINCIPLES (autoshorts.ai-inspired):
    1. CHARACTER CONSISTENCY: Same character description across all frames
    2. TECHNICAL FORMAT: [Subject] -> [Action] -> [Environment] -> [Lighting] -> [Camera] -> [Style]
    3. PROMPT DEDUPLICATION: Reuse identical prompts to save API calls
    4. ENGLISH ONLY: Nano Banana requires English prompts
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
        
        # Prompt cache for deduplication
        self._prompt_cache: Dict[str, str] = {}
        
        # Context cache (stores global context per video)
        self._context_cache: Optional[GlobalSceneContext] = None
        
        # Visual variety tracker (30/70 rule)
        self._variety_tracker: Optional[VisualVarietyTracker] = None

        if not self.api_key or self.api_key.startswith("PASTE_"):
            logger.warning("[VISUAL_DIRECTOR] No API key - will use fallback segmentation")
            self.api_key = ""
        else:
            logger.info(f"[VISUAL_DIRECTOR] Agent initialized with {model} (cost-optimized)")

    async def _analyze_narrative_context(
        self,
        narrative: str,
        topic: str,
        style: ScriptStyle,
        art_style: str
    ) -> GlobalSceneContext:
        """
        PHASE 1: Analyze FULL NARRATIVE to extract global visual context.
        
        This is CRITICAL to prevent mismatches like:
        - Topic: "Kazakhstan" + Narrative about Kazakh khanate
        - But images show: Egyptian pyramids ❌
        
        By reading the FULL narrative, we extract:
        - Era (15th century, modern, ancient)
        - Region (Central Asia, Egypt, Silicon Valley)
        - Architecture (yurts vs pyramids vs skyscrapers)
        - People (Kazakh warriors vs pharaohs vs tech CEOs)
        
        This context is then applied to ALL 12 image prompts.
        """
        if not self.api_key:
            logger.warning("[CONTEXT_ANALYSIS] No API key - using fallback context")
            return self._create_fallback_context(topic, style, art_style)
        
        logger.info(f"[CONTEXT_ANALYSIS] 🔍 Analyzing narrative for global context...")
        logger.info(f"[CONTEXT_ANALYSIS] Topic: {topic}")
        logger.info(f"[CONTEXT_ANALYSIS] Narrative length: {len(narrative)} chars")
        
        system_prompt = """You are a VISUAL CONTEXT ANALYZER for video production.

Your task: Read the FULL NARRATIVE and extract GLOBAL VISUAL CONTEXT that must be applied to ALL frames.

CRITICAL: Avoid mismatches! 
- If narrative is about Kazakhstan → NO Egyptian pyramids!
- If narrative is about Elon Musk → NO medieval castles!
- If narrative is about Ancient Egypt → NO modern skyscrapers!

⚠️ GENDER CRITICAL:
- If narrative says "ОН" (he/him) → people_description MUST be "MAN" or "MALE"
- If narrative says "ОНА" (she/her) → people_description MUST be "WOMAN" or "FEMALE"
- If no gender pronouns → use "person" (neutral)

Output JSON with these fields:
{
  "era": "When does this story take place? (e.g., '15th century', 'modern day 2020s', 'ancient times 3000 BC')",
  "region": "Where does this story take place? (e.g., 'Central Asian steppe', 'Silicon Valley USA', 'Nile River valley')",
  "architecture": ["What buildings/structures appear? (e.g., 'yurts', 'pyramids', 'tech offices')"],
  "people_description": "Who are the main people? MUST INCLUDE GENDER! Physical description with EXPLICIT gender: 'MAN, Kazakh warrior in traditional armor', 'WOMAN, Tech CEO in casual clothes', 'MALE Egyptian pharaoh in golden headdress'",
  "gender": "Explicit gender: 'male', 'female', or 'neutral' - READ PRONOUNS IN NARRATIVE!",
  "key_objects": ["Important objects that should appear (e.g., 'horses', 'rockets', 'scrolls')"],
  "atmosphere": "Overall mood (e.g., 'epic historical', 'futuristic innovative', 'ancient mysterious')",
  "lighting_style": "Consistent lighting (e.g., 'golden hour warm light', 'bright modern lighting', 'dramatic torch lighting')",
  "color_palette": ["Main colors (e.g., 'earth tones', 'metallic silver', 'desert sand')"],
  "avoid_elements": ["What should NOT appear to avoid mismatches (e.g., 'pyramids' if not Egypt, 'skyscrapers' if medieval)"]
}

IMPORTANT: 
1. Be specific and consistent
2. ALWAYS include explicit gender in people_description
3. Read pronouns carefully: "он" = MAN, "она" = WOMAN
4. All 12 frames will use this context"""

        user_prompt = f"""Analyze this narrative and extract global visual context:

═══════════════════════════════════════════════════════════════
NARRATIVE (READ CAREFULLY):
═══════════════════════════════════════════════════════════════
{narrative}

═══════════════════════════════════════════════════════════════
TOPIC: {topic}
STYLE: {style.value}
ART STYLE: {art_style}

Extract the visual context that should be CONSISTENT across all 12 frames.
Return ONLY valid JSON."""

        try:
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
                "temperature": 0.3,  # Low temperature for consistency
                "max_tokens": 600,
                "response_format": {"type": "json_object"}
            }
            
            response = await self.client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload
            )
            
            if response.status_code != 200:
                logger.error(f"[CONTEXT_ANALYSIS] API error: {response.status_code}")
                return self._create_fallback_context(topic, style, art_style)
            
            data = response.json()
            content = json.loads(data["choices"][0]["message"]["content"])
            
            # Convert to GlobalSceneContext
            # Extract gender and ensure it's in people_description
            gender = content.get("gender", "neutral")
            people_desc = content.get("people_description", f"Person related to {topic}")
            
            # CRITICAL: Ensure gender is EXPLICIT in description
            if gender == "male" and "man" not in people_desc.lower() and "male" not in people_desc.lower():
                people_desc = f"MAN, {people_desc}"
            elif gender == "female" and "woman" not in people_desc.lower() and "female" not in people_desc.lower():
                people_desc = f"WOMAN, {people_desc}"
            
            context = GlobalSceneContext(
                topic=topic,
                era=content.get("era", "modern"),
                region=content.get("region", topic),
                architecture=content.get("architecture", []),
                people_description=people_desc,
                gender=gender,
                key_objects=content.get("key_objects", []),
                atmosphere=content.get("atmosphere", "neutral"),
                lighting_style=content.get("lighting_style", "natural lighting"),
                color_palette=content.get("color_palette", ["natural"]),
                avoid_elements=content.get("avoid_elements", []),
                art_style=art_style
            )
            
            logger.info(f"[CONTEXT_ANALYSIS] ✅ Context extracted:")
            logger.info(f"  Era: {context.era}")
            logger.info(f"  Region: {context.region}")
            logger.info(f"  People: {context.people_description[:60]}...")
            logger.info(f"  Gender: {context.gender} ⚠️ CRITICAL")
            logger.info(f"  Architecture: {', '.join(context.architecture[:3])}")
            logger.info(f"  Avoid: {', '.join(context.avoid_elements[:3])}")
            
            return context
            
        except Exception as e:
            logger.error(f"[CONTEXT_ANALYSIS] Failed: {e}")
            return self._create_fallback_context(topic, style, art_style)
    
    def _create_fallback_context(
        self,
        topic: str,
        style: ScriptStyle,
        art_style: str
    ) -> GlobalSceneContext:
        """Create fallback context when API is unavailable."""
        logger.info(f"[CONTEXT_ANALYSIS] Using fallback context for: {topic}")
        
        return GlobalSceneContext(
            topic=topic,
            era="modern day",
            region=f"location related to {topic}",
            architecture=["buildings", "structures"],
            people_description=f"person related to {topic}",
            gender="neutral",  # Default neutral when no context
            key_objects=[topic],
            atmosphere=style.value,
            lighting_style="cinematic lighting",
            color_palette=["neutral", "natural"],
            avoid_elements=[],
            art_style=art_style
        )

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
        Context-Aware Visual Segmentation (2-phase process).
        
        PHASE 1: CONTEXT ANALYSIS
          - Read FULL narrative (not just topic!)
          - Extract: era, region, architecture, people
          - Prevent mismatches (Kazakhstan ≠ Egypt)
        
        PHASE 2: PROMPT GENERATION
          - Create 12 segments with global context
          - All prompts inherit: era, region, people description
          - Consistent visuals across all frames

        Args:
            narrative: The story from Master Storyteller (FULL TEXT!)
            topic: The main topic/subject
            style: The style for visual consistency
            language: Language of the narrative
            duration_seconds: Target video duration (30 or 60 seconds)
            art_style: User-selected art style for DALL-E (minecraft, anime, etc.)

        Returns:
            SegmentationResult with context-aware segments
        """
        segment_count = get_segment_count(duration_seconds)
        logger.info(f"[VISUAL_DIRECTOR] 🎬 CONTEXT-AWARE GENERATION STARTED")
        logger.info(f"[VISUAL_DIRECTOR] Topic: {topic}, Segments: {segment_count}, Duration: {duration_seconds}s")
        logger.info(f"[VISUAL_DIRECTOR] Style: {style.value}, Art: {art_style}")
        self._current_segment_count = segment_count
        self._current_duration = duration_seconds
        self._current_art_style = art_style
        
        # ═════════════════════════════════════════════════════════════════
        # PHASE 1: CONTEXT ANALYSIS (Read FULL narrative!)
        # ═════════════════════════════════════════════════════════════════
        logger.info(f"[PHASE_1] 🔍 Analyzing full narrative for global context...")
        global_context = await self._analyze_narrative_context(
            narrative=narrative,
            topic=topic,
            style=style,
            art_style=art_style
        )
        
        # Cache context for this video
        self._context_cache = global_context
        
        logger.info(f"[PHASE_1] ✅ Global context established:")
        logger.info(f"  → Era: {global_context.era}")
        logger.info(f"  → Region: {global_context.region}")
        logger.info(f"  → People: {global_context.people_description[:50]}...")
        if global_context.avoid_elements:
            logger.info(f"  → Avoiding: {', '.join(global_context.avoid_elements[:3])}")

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
🌍 GLOBAL VISUAL CONTEXT (MUST BE IN ALL PROMPTS!)
═══════════════════════════════════════════════════════════════
This context was extracted from the FULL narrative above.
ALL 12 visual prompts MUST include these elements:

ERA: {global_context.era}
REGION: {global_context.region}
ARCHITECTURE: {', '.join(global_context.architecture) if global_context.architecture else 'generic'}
PEOPLE: {global_context.people_description}
KEY OBJECTS: {', '.join(global_context.key_objects[:3]) if global_context.key_objects else 'none'}
ATMOSPHERE: {global_context.atmosphere}
LIGHTING: {global_context.lighting_style}
COLOR PALETTE: {', '.join(global_context.color_palette[:3])}

⚠️ CRITICAL - AVOID THESE (would be mismatches!):
{', '.join(global_context.avoid_elements) if global_context.avoid_elements else 'none specified'}

EXAMPLE CORRECT PROMPT:
"{global_context.people_description}, {global_context.architecture[0] if global_context.architecture else 'building'} in background, {global_context.region}, {global_context.era}, {global_context.lighting_style}, {art_style} style, no text"

═══════════════════════════════════════════════════════════════
CRITICAL: NANO BANANA PROMPT FORMAT (ENGLISH ONLY!)
═══════════════════════════════════════════════════════════════
ALL visual_prompt fields MUST be in ENGLISH (Nano Banana requirement)

TECHNICAL STRUCTURE (autoshorts.ai method):
[SUBJECT from global context], [ACTION/POSE], [ENVIRONMENT from global context], [LIGHTING from global context], [CAMERA ANGLE], [ART STYLE], no text, no words

═══════════════════════════════════════════════════════════════
CHARACTER CONSISTENCY (ABSOLUTELY CRITICAL!)
═══════════════════════════════════════════════════════════════
Use the EXACT people_description from global context in ALL segments where people appear:
- Correct: "{global_context.people_description}" (IDENTICAL in all frames!)
- Wrong: Changing description between frames

═══════════════════════════════════════════════════════════════
ART STYLE & CONSISTENCY
═══════════════════════════════════════════════════════════════
User selected ART STYLE: {art_style.upper()}
Art style modifier: "{art_style_modifier}"
Style consistency: "{style_consistency}"

EVERY prompt must include global context + art style.

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

            # Convert to VisualSegment objects with global context enforcement
            segments = []
            for i, seg_data in enumerate(raw_segments[:12]):
                # Get base visual prompt
                visual_prompt = seg_data.get("visual_prompt", "")

                # CRITICAL: ENFORCE global context in prompt
                # Check if context elements are present, if not - add them!
                visual_prompt = self._enforce_global_context(visual_prompt, global_context)

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
            
            # ═════════════════════════════════════════════════════════════
            # ENFORCE 30/70 RULE - Visual Variety (with style-based dynamics)
            # ═════════════════════════════════════════════════════════════
            segments = self._enforce_visual_variety(segments, global_context, style)
            
            # Deduplicate prompts to save API costs (autoshorts.ai optimization)
            segments = self.deduplicate_prompts(segments)

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
        logger.info(f"[VISUAL_DIRECTOR] 🎬 CONTEXT-AWARE GENERATION (with Visual Bible)")
        logger.info(f"[VISUAL_DIRECTOR] Segments: {segment_count}, Visual Bible: {len(visual_bible.characters)} characters, {len(visual_bible.locations)} locations")
        
        # ═════════════════════════════════════════════════════════════════
        # PHASE 1: CONTEXT ANALYSIS (Read FULL narrative!)
        # ═════════════════════════════════════════════════════════════════
        logger.info(f"[PHASE_1] 🔍 Analyzing full narrative for global context...")
        global_context = await self._analyze_narrative_context(
            narrative=narrative,
            topic=topic,
            style=style,
            art_style=art_style
        )
        
        # Cache context for this video
        self._context_cache = global_context
        
        logger.info(f"[PHASE_1] ✅ Global context established:")
        logger.info(f"  → Era: {global_context.era}")
        logger.info(f"  → Region: {global_context.region}")
        logger.info(f"  → People: {global_context.people_description[:50]}...")
        if global_context.avoid_elements:
            logger.info(f"  → Avoiding: {', '.join(global_context.avoid_elements[:3])}")

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

═══════════════════════════════════════════════════════════════
🌍 GLOBAL VISUAL CONTEXT (MUST BE IN ALL PROMPTS!)
═══════════════════════════════════════════════════════════════
This context was extracted from the FULL narrative above.
ALL visual prompts MUST include these elements:

ERA: {global_context.era}
REGION: {global_context.region}
PEOPLE: {global_context.people_description}
ATMOSPHERE: {global_context.atmosphere}
LIGHTING: {global_context.lighting_style}

⚠️ CRITICAL - AVOID THESE (would be mismatches!):
{', '.join(global_context.avoid_elements) if global_context.avoid_elements else 'none specified'}

═══════════════════════════════════════════════════════════════

ART STYLE (MUST be at START of every visual_prompt):
{art_style_modifier}

STYLE CONSISTENCY STRING (MUST be in every visual_prompt):
{style_consistency}

CRITICAL: 
1. Copy character/location descriptions EXACTLY from the Visual Bible above!
2. Include GLOBAL CONTEXT (era, region) in every prompt!
3. Every segment must feel like it's from the same visual world.

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

            # Convert to VisualSegment objects with Visual Bible context + global context enforcement
            segments = []
            for i, seg_data in enumerate(raw_segments[:segment_count]):
                visual_prompt = seg_data.get("visual_prompt", "")

                # CRITICAL: ENFORCE global context in prompt
                visual_prompt = self._enforce_global_context(visual_prompt, global_context)

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
            
            # ═════════════════════════════════════════════════════════════
            # ENFORCE 30/70 RULE - Visual Variety (with style-based dynamics)
            # ═════════════════════════════════════════════════════════════
            segments = self._enforce_visual_variety(segments, global_context, style)
            
            # Deduplicate prompts (Visual Bible version)
            segments = self.deduplicate_prompts(segments)

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

    def _enforce_visual_variety(
        self,
        segments: List[VisualSegment],
        context: GlobalSceneContext,
        script_style: Optional[ScriptStyle] = None
    ) -> List[VisualSegment]:
        """
        Enforce 30/70 rule: Max 30-40% character shots, min 60-70% environment.
        
        NEW: Style-based shot dynamics:
        - DOCUMENTARY → More wide shots (landscapes, establishing)
        - MOTIVATIONAL → More close-ups (emotions, details)
        - VIRAL → Fast variety (every shot different)
        - STORYTELLING → Balanced mix
        
        Strategy:
        1. Detect which segments have character-focused prompts
        2. If > 40% are character shots, convert excess to environment shots
        3. Ensure no more than 2 consecutive character shots
        4. Apply style-specific preferences
        5. Replace with appropriate shot based on segment text
        
        This prevents "talking head" videos and creates dynamic visual storytelling.
        """
        logger.info(f"[30/70_RULE] 🎬 Analyzing {len(segments)} segments for visual variety...")
        if script_style:
            logger.info(f"[30/70_RULE] 📋 Script style: {script_style.value} (will adjust shot preferences)")
        
        # Initialize tracker
        tracker = VisualVarietyTracker(len(segments))
        
        # Analyze current distribution with STRICTER detection
        character_keywords = [
            'portrait', 'face', 'person', 'man', 'woman', 'warrior', 'leader', 'ceo', 
            'looking at camera', 'male', 'female', 'guy', 'girl', 'character',
            'standing', 'sitting', 'walking', 'figure', 'human'  # Common character poses
        ]
        
        # Environment keywords (should NOT have characters)
        environment_keywords = ['wide shot', 'aerial', 'landscape', 'building', 'architecture']
        
        for i, seg in enumerate(segments):
            prompt_lower = seg.visual_prompt.lower()
            
            # Detect if this is a character shot (STRICTER!)
            is_character_shot = any(keyword in prompt_lower for keyword in character_keywords)
            
            # Override if explicitly environment shot
            is_environment = any(keyword in prompt_lower for keyword in environment_keywords)
            if is_environment:
                is_character_shot = False  # Environment shot takes priority
            
            # Check text for action/object keywords
            text_lower = seg.text.lower()
            
            # If text mentions action/object but prompt shows character - FIX IT!
            action_keywords = ['battle', 'war', 'gold', 'treasure', 'building', 'landscape', 
                              'mountain', 'city', 'weapon', 'artifact', 'ceremony', 'empire',
                              'territory', 'steppe', 'journey', 'trade']
            
            has_action_in_text = any(keyword in text_lower for keyword in action_keywords)
            
            if has_action_in_text and is_character_shot:
                # MISMATCH: Text describes ACTION but visual shows CHARACTER
                logger.info(f"[30/70_RULE] ⚠️  Segment {i+1}: Text mentions action, but prompt is character-focused")
                logger.info(f"[30/70_RULE]     Text: {seg.text[:50]}...")
                
                # Replace with environment shot (style-aware)
                new_prompt = self._convert_to_environment_shot(seg.text, context, seg.visual_prompt, script_style)
                segments[i].visual_prompt = new_prompt
                logger.info(f"[30/70_RULE]     ✅ Converted to environment shot")
                
                tracker.record_shot(ShotType.WIDE)
            elif is_character_shot:
                # Check if we can use character shot
                if not tracker.can_use_character_shot(i):
                    logger.info(f"[30/70_RULE] ⚠️  Segment {i+1}: Too many character shots, converting to environment")
                    
                    new_prompt = self._convert_to_environment_shot(seg.text, context, seg.visual_prompt, script_style)
                    segments[i].visual_prompt = new_prompt
                    tracker.record_shot(ShotType.WIDE)
                else:
                    tracker.record_shot(ShotType.PORTRAIT)
            else:
                # Already environment shot
                tracker.record_shot(ShotType.WIDE)
        
        # Get statistics
        stats = tracker.get_stats()
        logger.info(f"[30/70_RULE] 📊 Final distribution:")
        logger.info(f"[30/70_RULE]     Character shots: {stats['character_shots']}/{stats['total_shots']} ({stats['character_percentage']:.1f}%)")
        logger.info(f"[30/70_RULE]     Environment shots: {stats['total_shots'] - stats['character_shots']}/{stats['total_shots']} ({100 - stats['character_percentage']:.1f}%)")
        logger.info(f"[30/70_RULE]     Passes 30/70 rule: {'✅ YES' if stats['passes_30_70_rule'] else '❌ NO'}")
        
        return segments
    
    def _convert_to_environment_shot(
        self,
        segment_text: str,
        context: GlobalSceneContext,
        original_prompt: str,
        script_style: Optional[ScriptStyle] = None
    ) -> str:
        """
        Convert a character-focused prompt to an environment/action shot.
        
        NEW: Style-aware shot selection:
        - DOCUMENTARY → Prefer wide/aerial (show scale and context)
        - MOTIVATIONAL → Prefer close-ups (emotional details)
        - VIRAL → Maximum variety (alternate between all types)
        - STORYTELLING → Cinematic mix (medium + wide)
        
        Based on segment text content, create appropriate visual:
        - "battle" → wide shot of battlefield
        - "gold" → detail shot of gold coins
        - "landscape" → aerial view of region
        - etc.
        """
        text_lower = segment_text.lower()
        
        # Extract style modifiers from original prompt (to maintain consistency)
        style_parts = []
        if 'photorealistic' in original_prompt.lower():
            style_parts.append('photorealistic')
        if 'cinematic' in original_prompt.lower():
            style_parts.append('cinematic lighting')
        if '8k' in original_prompt.lower():
            style_parts.append('8K')
        
        style_suffix = ', '.join(style_parts) if style_parts else 'cinematic, 8K'
        
        # ═════════════════════════════════════════════════════════════════
        # STYLE-BASED SHOT PREFERENCES
        # ═════════════════════════════════════════════════════════════════
        
        # DOCUMENTARY → Prefer wide/aerial (educational, showing context)
        prefer_wide = script_style in [ScriptStyle.DOCUMENTARY, ScriptStyle.EDUCATIONAL, ScriptStyle.HISTORICAL]
        
        # MOTIVATIONAL → Prefer close-ups (emotional, inspiring details)
        prefer_closeup = script_style in [ScriptStyle.MOTIVATIONAL]
        
        # VIRAL/MYSTERY → Maximum variety
        prefer_variety = script_style in [ScriptStyle.VIRAL, ScriptStyle.MYSTERY]
        
        # ═════════════════════════════════════════════════════════════════
        # SHOT SELECTION BASED ON TEXT + STYLE
        # ═════════════════════════════════════════════════════════════════
        
        # Determine shot type based on text
        if 'battle' in text_lower or 'war' in text_lower:
            if prefer_closeup:
                # MOTIVATIONAL → Show emotional impact, not just battle
                return f"close-up, warrior's determined face, battle scars, {context.era}, intense emotion, {context.region}, {context.lighting_style}, {style_suffix}, no text, no words"
            else:
                # DOCUMENTARY/WIDE → Show scale and context
                return f"wide shot, {context.era} battlefield scene, {context.region}, dramatic action, armies clashing, epic scale, {context.lighting_style}, {style_suffix}, no text, no words"
        
        elif 'gold' in text_lower or 'treasure' in text_lower or 'wealth' in text_lower:
            if prefer_wide:
                # DOCUMENTARY → Show treasure in context
                return f"wide shot, treasure chamber filled with gold, {context.era} architecture, {context.region}, vast wealth, {context.lighting_style}, {style_suffix}, no text, no words"
            else:
                # Close-up for impact
                return f"extreme close-up, golden coins and treasures, intricate details, {context.era} artifacts, gleaming metal, {context.lighting_style}, {style_suffix}, no text, no words"
        
        elif 'building' in text_lower or 'architecture' in text_lower or 'city' in text_lower:
            arch = context.architecture[0] if context.architecture else 'traditional buildings'
            if prefer_closeup:
                # MOTIVATIONAL → Show architectural details that inspire
                return f"close-up, intricate architectural details, {arch} craftsmanship, {context.era}, {context.region}, inspiring design, {context.lighting_style}, {style_suffix}, no text, no words"
            else:
                # WIDE → Show scale and grandeur
                return f"wide shot, {arch}, {context.region}, {context.era} architecture, majestic scale, epic view, {context.lighting_style}, {style_suffix}, no text, no words"
        
        elif 'landscape' in text_lower or 'territory' in text_lower or 'steppe' in text_lower:
            if prefer_variety and 'territory' in text_lower:
                # VIRAL → Dramatic aerial for maximum impact
                return f"dramatic aerial shot, {context.region} landscape, vast empire territory, {context.era}, breathtaking scale, {context.lighting_style}, {style_suffix}, no text, no words"
            else:
                # DOCUMENTARY → Educational wide view
                return f"aerial shot, {context.region} landscape, vast expanse, {context.era}, establishing shot, {context.lighting_style}, {style_suffix}, no text, no words"
        
        elif 'weapon' in text_lower or 'sword' in text_lower or 'artifact' in text_lower:
            obj = context.key_objects[0] if context.key_objects else 'traditional weapon'
            # Close-up works for ALL styles (shows detail and craftsmanship)
            return f"extreme close-up, {obj}, intricate craftsmanship, {context.era} design, detailed texture, dramatic lighting, {context.lighting_style}, {style_suffix}, no text, no words"
        
        elif 'ceremony' in text_lower or 'ritual' in text_lower or 'gathering' in text_lower:
            if prefer_closeup:
                # MOTIVATIONAL → Focus on emotional faces in ceremony
                return f"close-up, ceremonial moment, emotional faces, {context.era} tradition, {context.region}, powerful expression, {context.lighting_style}, {style_suffix}, no text, no words"
            else:
                # WIDE → Show full ceremonial scene
                return f"wide shot, ceremonial scene, {context.region}, {context.era} tradition, crowd of people, atmospheric gathering, {context.lighting_style}, {style_suffix}, no text, no words"
        
        elif 'empire' in text_lower or 'kingdom' in text_lower or 'power' in text_lower:
            if prefer_closeup:
                # MOTIVATIONAL → Symbol of power (crown, throne detail)
                return f"close-up, symbols of power, {context.era} royal insignia, {context.region}, majestic details, {context.lighting_style}, {style_suffix}, no text, no words"
            else:
                # AERIAL → Show vast empire
                return f"aerial shot, {context.region} territory, vast empire view, {context.era}, grand scale, breathtaking expanse, {context.lighting_style}, {style_suffix}, no text, no words"
        
        else:
            # Generic environment shot (style-adaptive)
            if prefer_closeup:
                # MOTIVATIONAL → Focus on emotional/symbolic detail
                return f"close-up, symbolic element from {context.region}, {context.era} detail, emotional significance, {context.lighting_style}, {style_suffix}, no text, no words"
            elif prefer_wide:
                # DOCUMENTARY → Wide establishing shot
                return f"wide shot, {context.region} landscape, {context.era} atmosphere, establishing shot, educational context, {context.lighting_style}, {style_suffix}, no text, no words"
            else:
                # BALANCED → Medium/varied
                return f"medium shot, {context.region} environment, {context.era} atmosphere, balanced composition, {context.lighting_style}, {style_suffix}, no text, no words"
    
    def _enforce_global_context(
        self,
        visual_prompt: str,
        context: GlobalSceneContext
    ) -> str:
        """
        STRICTLY enforce global context in visual prompt.
        
        This is CRITICAL to prevent mismatches like:
        - Topic: "Kazakhstan" → Images: "Egyptian pyramids" ❌
        
        Strategy:
        1. Check if prompt has ALL required context elements
        2. If ANY are missing, INSERT them at the START
        3. Prioritize: Era → Region → People → Architecture
        
        Example:
        Input: "Person in building, dramatic lighting"
        Context: era="15th century", region="Central Asian steppe", people="Kazakh warrior"
        Output: "15th century, Central Asian steppe, Kazakh warrior in building, dramatic lighting"
        """
        prompt_lower = visual_prompt.lower()
        
        # Build complete context prefix
        context_elements = []
        
        # 1. Era (CRITICAL for time period)
        if context.era and context.era.lower() not in prompt_lower:
            context_elements.append(context.era)
            logger.debug(f"[CONTEXT_ENFORCE] Adding missing era: {context.era}")
        
        # 2. Region (CRITICAL for location)
        if context.region and "location related" not in context.region:
            # Check if ANY region keywords present
            region_words = [w for w in context.region.lower().split() if len(w) > 3]
            if not any(word in prompt_lower for word in region_words):
                context_elements.append(context.region)
                logger.debug(f"[CONTEXT_ENFORCE] Adding missing region: {context.region}")
        
        # 3. People description (CRITICAL for character consistency)
        # Only add if prompt mentions "person", "man", "woman", "people", "warrior", etc.
        person_keywords = ["person", "man", "woman", "people", "warrior", "leader", "figure", "character"]
        if any(keyword in prompt_lower for keyword in person_keywords):
            # Check if people description is present
            people_words = [w for w in context.people_description.lower().split() if len(w) > 3]
            if not any(word in prompt_lower for word in people_words[:3]):  # Check first 3 words
                # Don't add full description, just key identifier
                # Extract first meaningful phrase (e.g., "Kazakh warrior")
                people_key = " ".join(context.people_description.split()[:3])
                context_elements.append(people_key)
                logger.debug(f"[CONTEXT_ENFORCE] Adding people: {people_key}")
        
        # If we need to add context, prepend it
        if context_elements:
            context_prefix = ", ".join(context_elements)
            visual_prompt = f"{context_prefix}, {visual_prompt}"
            logger.info(f"[CONTEXT_ENFORCE] ✓ Enforced context: {context_prefix}")
        
        return visual_prompt
    
    def deduplicate_prompts(self, segments: List[VisualSegment]) -> List[VisualSegment]:
        """
        Deduplicate visual prompts to save API costs (autoshorts.ai optimization).
        
        If two segments have very similar prompts (>90% similarity),
        use the exact same prompt for consistency and cost savings.
        
        Returns:
            Segments with deduplicated prompts
        """
        deduplicated = []
        seen_prompts: Dict[str, str] = {}  # normalized -> original
        
        for segment in segments:
            # Normalize prompt (remove style modifiers for comparison)
            prompt = segment.visual_prompt
            core_prompt = prompt.lower().replace("cinematic lighting", "").replace("8k", "").strip()
            
            # Check if we've seen a very similar prompt
            match_found = False
            for seen_core, seen_original in seen_prompts.items():
                similarity = self._calculate_similarity(core_prompt, seen_core)
                if similarity > 0.90:  # 90% similarity threshold
                    logger.info(f"[DEDUP] Reusing prompt for segment {segment.index} (similarity: {similarity:.0%})")
                    segment.visual_prompt = seen_original
                    match_found = True
                    break
            
            if not match_found:
                seen_prompts[core_prompt] = prompt
            
            deduplicated.append(segment)
        
        unique_count = len(seen_prompts)
        logger.info(f"[DEDUP] Reduced {len(segments)} prompts to {unique_count} unique prompts (saved {len(segments) - unique_count} API calls)")
        
        return deduplicated
    
    def _calculate_similarity(self, s1: str, s2: str) -> float:
        """Calculate simple word-based similarity between two strings."""
        words1 = set(s1.split())
        words2 = set(s2.split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        return len(intersection) / len(union) if union else 0.0

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
