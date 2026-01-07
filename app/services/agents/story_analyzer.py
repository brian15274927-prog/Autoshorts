"""
Story Analyzer Agent - Creates Visual Bible for consistent image generation.

Analyzes the complete story and extracts:
- Characters with detailed visual descriptions
- Locations with consistent visual details
- Atmosphere, mood, and color palette
- Key objects and visual symbols
- Timeline and visual progression

This ensures all generated images maintain visual coherence throughout the video.
"""

import logging
import httpx
import json
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Character:
    """Character with consistent visual description."""
    id: str
    name: str
    description: str  # Detailed visual description
    appears_in_segments: List[int] = field(default_factory=list)


@dataclass
class Location:
    """Location with consistent visual description."""
    id: str
    name: str
    description: str  # Detailed visual description
    appears_in_segments: List[int] = field(default_factory=list)


@dataclass
class VisualBible:
    """Complete visual context for the story."""
    story_title: str
    characters: List[Character]
    locations: List[Location]
    atmosphere: Dict[str, Any]  # mood, lighting, color_palette, style
    key_objects: List[str]
    visual_thread: str  # The visual journey/progression
    segment_mapping: List[Dict[str, Any]]  # Which elements appear where

    def to_dict(self) -> dict:
        return {
            "story_title": self.story_title,
            "characters": [
                {
                    "id": c.id,
                    "name": c.name,
                    "description": c.description,
                    "appears_in_segments": c.appears_in_segments
                }
                for c in self.characters
            ],
            "locations": [
                {
                    "id": l.id,
                    "name": l.name,
                    "description": l.description,
                    "appears_in_segments": l.appears_in_segments
                }
                for l in self.locations
            ],
            "atmosphere": self.atmosphere,
            "key_objects": self.key_objects,
            "visual_thread": self.visual_thread,
            "segment_mapping": self.segment_mapping
        }

    def get_context_for_segment(self, segment_index: int) -> Dict[str, Any]:
        """Get relevant visual context for a specific segment."""
        context = {
            "characters": [],
            "location": None,
            "atmosphere": self.atmosphere,
            "key_objects": [],
            "segment_info": None
        }

        # Find characters in this segment
        for char in self.characters:
            if segment_index in char.appears_in_segments:
                context["characters"].append({
                    "name": char.name,
                    "description": char.description
                })

        # Find location for this segment
        for loc in self.locations:
            if segment_index in loc.appears_in_segments:
                context["location"] = {
                    "name": loc.name,
                    "description": loc.description
                }
                break

        # Get segment mapping info
        if segment_index < len(self.segment_mapping):
            context["segment_info"] = self.segment_mapping[segment_index]
            context["key_objects"] = self.segment_mapping[segment_index].get("key_objects", [])

        return context


# System prompt for story analysis
STORY_ANALYZER_PROMPT = """You are a VISUAL STORY ANALYZER for video production.

Your task is to analyze a complete script and create a VISUAL BIBLE - a document that ensures
all generated images maintain visual coherence throughout the video.

CRITICAL: You must identify and describe visual elements CONSISTENTLY so that:
1. The same character looks THE SAME in every frame
2. The same location looks THE SAME when revisited
3. The atmosphere and style remain UNIFIED throughout
4. Key objects are RECOGNIZABLE across scenes

OUTPUT FORMAT (JSON):
{
  "story_title": "Brief title of the story",

  "characters": [
    {
      "id": "unique_id",
      "name": "Character name or role",
      "description": "DETAILED visual description: age, gender, hair (color, length, style),
                      face (shape, features), body type, clothing (specific items, colors),
                      distinguishing features (scars, accessories, posture)",
      "appears_in_segments": [0, 1, 3, 5]
    }
  ],

  "locations": [
    {
      "id": "unique_id",
      "name": "Location name",
      "description": "DETAILED visual description: type of place, architecture style,
                      materials (stone, wood, metal), colors, lighting conditions,
                      key visual elements, size/scale, weather/atmosphere",
      "appears_in_segments": [0, 1]
    }
  ],

  "atmosphere": {
    "mood": "overall emotional tone (mysterious, joyful, tense, etc.)",
    "lighting": "lighting style (dramatic shadows, soft diffused, harsh sunlight, etc.)",
    "color_palette": ["primary color", "secondary color", "accent color"],
    "style": "visual style (cinematic documentary, anime, photorealistic, etc.)"
  },

  "key_objects": [
    "object 1 with brief description",
    "object 2 with brief description"
  ],

  "visual_thread": "The visual journey - how visuals should progress (e.g., 'from darkness to light', 'from chaos to order')",

  "segment_mapping": [
    {
      "segment_index": 0,
      "location_id": "temple_exterior",
      "character_ids": ["hero"],
      "time_of_day": "morning",
      "mood_shift": "anticipation",
      "key_objects": ["ancient map"],
      "visual_focus": "wide shot of temple, hero small in frame"
    }
  ]
}

RULES:
1. Be EXTREMELY SPECIFIC in descriptions - vague descriptions lead to inconsistent images
2. Use CONCRETE details: "short dark brown hair with gray at temples" NOT "dark hair"
3. Describe clothing COMPLETELY: "worn brown leather jacket with brass buttons, dark blue jeans, hiking boots"
4. For locations, describe ARCHITECTURE and MATERIALS specifically
5. Ensure segment_mapping covers ALL segments in order
6. If a character/location reappears, use the SAME id to link them
7. Think about VISUAL CONTINUITY - how does one scene flow to the next?

IMPORTANT: Output ONLY valid JSON, no explanations before or after."""


class StoryAnalyzer:
    """
    Analyzes complete story and creates Visual Bible for consistent image generation.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        from app.config import config
        self.api_key = api_key or config.ai.openai_api_key or ""
        self.model = model
        self.client = httpx.AsyncClient(timeout=120.0)

        if not self.api_key or self.api_key.startswith("PASTE_"):
            logger.warning("[STORY_ANALYZER] No API key - will use fallback analysis")
            self.api_key = ""
        else:
            logger.info(f"[STORY_ANALYZER] Initialized with {model}")

    async def analyze_story(
        self,
        full_script: str,
        segments: List[Dict[str, Any]],
        topic: str,
        style: str = "documentary"
    ) -> VisualBible:
        """
        Analyze the complete story and create Visual Bible.

        Args:
            full_script: The complete narrative text
            segments: List of script segments with text
            topic: Original topic/theme
            style: Visual style (documentary, viral, etc.)

        Returns:
            VisualBible with all visual context
        """
        logger.info(f"[STORY_ANALYZER] Analyzing story: {topic[:50]}...")
        logger.info(f"[STORY_ANALYZER] Segments to analyze: {len(segments)}")

        if not self.api_key:
            return self._create_fallback_bible(topic, segments, style)

        try:
            # Prepare segment texts for analysis
            segment_texts = []
            for i, seg in enumerate(segments):
                text = seg.get("text", "") or seg.get("content", "")
                segment_texts.append(f"[Segment {i}]: {text}")

            segments_formatted = "\n\n".join(segment_texts)

            user_prompt = f"""ANALYZE THIS STORY AND CREATE A VISUAL BIBLE:

TOPIC: {topic}
STYLE: {style}
NUMBER OF SEGMENTS: {len(segments)}

FULL SCRIPT:
{full_script}

SEGMENTS BREAKDOWN:
{segments_formatted}

Create a detailed Visual Bible that ensures visual consistency across all {len(segments)} segments.
Remember: segment_mapping must have exactly {len(segments)} entries (indices 0 to {len(segments)-1}).

OUTPUT JSON:"""

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": STORY_ANALYZER_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.7,
                "max_tokens": 2000
            }

            response = await self.client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload
            )

            if response.status_code != 200:
                logger.error(f"[STORY_ANALYZER] API error: {response.status_code}")
                return self._create_fallback_bible(topic, segments, style)

            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()

            # Parse JSON response
            # Clean up potential markdown code blocks
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            content = content.strip()

            bible_data = json.loads(content)

            # Convert to VisualBible object
            visual_bible = self._parse_bible_data(bible_data, len(segments))

            logger.info(f"[STORY_ANALYZER] Visual Bible created:")
            logger.info(f"  - Characters: {len(visual_bible.characters)}")
            logger.info(f"  - Locations: {len(visual_bible.locations)}")
            logger.info(f"  - Key objects: {len(visual_bible.key_objects)}")
            logger.info(f"  - Segment mappings: {len(visual_bible.segment_mapping)}")

            return visual_bible

        except json.JSONDecodeError as e:
            logger.error(f"[STORY_ANALYZER] JSON parse error: {e}")
            return self._create_fallback_bible(topic, segments, style)
        except Exception as e:
            logger.error(f"[STORY_ANALYZER] Analysis failed: {e}")
            return self._create_fallback_bible(topic, segments, style)

    def _parse_bible_data(self, data: dict, num_segments: int) -> VisualBible:
        """Parse JSON data into VisualBible object."""

        # Parse characters
        characters = []
        for char_data in data.get("characters", []):
            characters.append(Character(
                id=char_data.get("id", f"char_{len(characters)}"),
                name=char_data.get("name", "Unknown"),
                description=char_data.get("description", ""),
                appears_in_segments=char_data.get("appears_in_segments", list(range(num_segments)))
            ))

        # Parse locations
        locations = []
        for loc_data in data.get("locations", []):
            locations.append(Location(
                id=loc_data.get("id", f"loc_{len(locations)}"),
                name=loc_data.get("name", "Unknown location"),
                description=loc_data.get("description", ""),
                appears_in_segments=loc_data.get("appears_in_segments", list(range(num_segments)))
            ))

        # Parse atmosphere
        atmosphere = data.get("atmosphere", {
            "mood": "cinematic",
            "lighting": "dramatic, natural",
            "color_palette": ["neutral", "warm", "cool"],
            "style": "photorealistic documentary"
        })

        # Parse segment mapping - ensure we have all segments
        segment_mapping = data.get("segment_mapping", [])
        while len(segment_mapping) < num_segments:
            segment_mapping.append({
                "segment_index": len(segment_mapping),
                "location_id": locations[0].id if locations else "main_location",
                "character_ids": [c.id for c in characters] if characters else [],
                "mood_shift": "continuation",
                "key_objects": [],
                "visual_focus": "medium shot"
            })

        return VisualBible(
            story_title=data.get("story_title", "Untitled Story"),
            characters=characters,
            locations=locations,
            atmosphere=atmosphere,
            key_objects=data.get("key_objects", []),
            visual_thread=data.get("visual_thread", "linear progression"),
            segment_mapping=segment_mapping
        )

    def _create_fallback_bible(
        self,
        topic: str,
        segments: List[Dict[str, Any]],
        style: str
    ) -> VisualBible:
        """Create a basic Visual Bible when API is unavailable."""
        logger.info("[STORY_ANALYZER] Using fallback Visual Bible")

        num_segments = len(segments)

        # Create basic character based on topic
        main_character = Character(
            id="narrator",
            name="Narrator/Subject",
            description=f"Visual representation related to {topic}. "
                       "Consistent visual style throughout.",
            appears_in_segments=list(range(num_segments))
        )

        # Create basic location
        main_location = Location(
            id="main_setting",
            name="Primary Setting",
            description=f"Setting appropriate for topic: {topic}. "
                       "Consistent architectural and environmental style.",
            appears_in_segments=list(range(num_segments))
        )

        # Style-based atmosphere
        style_atmospheres = {
            "viral": {
                "mood": "energetic, attention-grabbing",
                "lighting": "high contrast, dramatic",
                "color_palette": ["bold red", "electric blue", "bright yellow"],
                "style": "hyper-realistic, cinematic, high impact"
            },
            "documentary": {
                "mood": "informative, immersive",
                "lighting": "natural, documentary-style",
                "color_palette": ["earth tones", "muted blues", "warm neutrals"],
                "style": "National Geographic, cinematic realism"
            },
            "motivational": {
                "mood": "inspiring, uplifting",
                "lighting": "warm, golden hour",
                "color_palette": ["golden", "warm orange", "sky blue"],
                "style": "aspirational, epic, emotional"
            },
            "storytelling": {
                "mood": "narrative, immersive",
                "lighting": "cinematic, mood-driven",
                "color_palette": ["rich browns", "deep blues", "accent gold"],
                "style": "epic cinema, character-focused"
            }
        }

        atmosphere = style_atmospheres.get(style, style_atmospheres["documentary"])

        # Create segment mapping
        segment_mapping = []
        for i in range(num_segments):
            segment_mapping.append({
                "segment_index": i,
                "location_id": "main_setting",
                "character_ids": ["narrator"],
                "mood_shift": "building" if i < num_segments // 2 else "climax" if i == num_segments // 2 else "resolution",
                "key_objects": [],
                "visual_focus": "establishing shot" if i == 0 else "detail shot" if i == num_segments - 1 else "medium shot"
            })

        return VisualBible(
            story_title=topic,
            characters=[main_character],
            locations=[main_location],
            atmosphere=atmosphere,
            key_objects=[],
            visual_thread="Progressive revelation from introduction to conclusion",
            segment_mapping=segment_mapping
        )

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
        logger.info("[STORY_ANALYZER] Agent closed")
