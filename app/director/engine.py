"""
Director Engine - AI-powered clip decision making.

Uses LLM to analyze transcripts and identify the best moments for short clips.
Inspired by video-db/Director architecture.
"""
import os
import json
import logging
import uuid
from typing import List, Dict, Any, Optional
from pathlib import Path

from .models import ClipDecision, DirectorResult, ClipStyle

logger = logging.getLogger(__name__)

# System prompt for clip analysis
CLIP_ANALYSIS_PROMPT = """You are an expert video editor and content strategist specializing in viral short-form content.
Your task is to analyze a video transcript and identify the BEST moments for creating engaging short clips (15-60 seconds).

ANALYSIS CRITERIA:
1. **Hook Potential**: Does the segment grab attention in the first 3 seconds?
2. **Standalone Value**: Can this segment be understood without context?
3. **Emotional Impact**: Does it evoke emotion (funny, inspiring, shocking, educational)?
4. **Viral Potential**: Would people share this clip?
5. **Completeness**: Does it have a clear beginning, middle, and end?

CLIP REQUIREMENTS:
- Duration: 15-60 seconds (ideal: 30-45 seconds)
- Must start with a hook or compelling statement
- Must end on a strong note (punchline, insight, call-to-action)
- Avoid clips that cut off mid-sentence or mid-thought

OUTPUT FORMAT:
Return a JSON object with the following structure:
{
    "clips": [
        {
            "start": <start_time_in_seconds>,
            "end": <end_time_in_seconds>,
            "reason": "<why this clip was selected>",
            "score": <0.0-1.0 virality score>,
            "style": "<dramatic|funny|educational|motivational|storytelling|controversial|emotional|action|default>",
            "title": "<suggested catchy title for the clip>",
            "keywords": ["keyword1", "keyword2", "keyword3"]
        }
    ]
}

IMPORTANT:
- Return 3-7 clips maximum
- Clips should not overlap
- Higher scores for clips with strong hooks and emotional payoffs
- Consider the target audience: social media users with short attention spans
"""


class DirectorEngine:
    """AI Director for clip selection decisions."""

    def __init__(self, llm_provider: str = "auto"):
        """
        Initialize Director Engine.

        Args:
            llm_provider: LLM provider to use ("openai", "anthropic", "auto")
        """
        self.llm_provider = llm_provider
        self._llm_client = None
        self._init_llm()

    def _init_llm(self):
        """Initialize LLM client based on available API keys."""
        # Try OpenAI first
        openai_key = os.getenv("OPENAI_API_KEY", "")
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

        # Check for valid keys (not empty or placeholder)
        has_valid_openai = openai_key and not openai_key.startswith("PASTE_") and openai_key.startswith("sk-")
        has_valid_anthropic = anthropic_key and not anthropic_key.startswith("PASTE_")

        if self.llm_provider == "openai" or (self.llm_provider == "auto" and has_valid_openai):
            try:
                import openai
                self._llm_client = openai.OpenAI(api_key=openai_key)
                self._llm_type = "openai"
                logger.info("Director using OpenAI")
                return
            except ImportError:
                logger.warning("OpenAI package not installed")
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI: {e}")

        if self.llm_provider == "anthropic" or (self.llm_provider == "auto" and has_valid_anthropic):
            try:
                import anthropic
                self._llm_client = anthropic.Anthropic(api_key=anthropic_key)
                self._llm_type = "anthropic"
                logger.info("Director using Anthropic")
                return
            except ImportError:
                logger.warning("Anthropic package not installed")
            except Exception as e:
                logger.warning(f"Failed to initialize Anthropic: {e}")

        # Fallback to rule-based
        self._llm_client = None
        self._llm_type = "fallback"
        logger.warning("No LLM available, using rule-based fallback")

    def _call_llm(self, prompt: str) -> Optional[str]:
        """Call LLM with prompt and return response."""
        if self._llm_type == "openai":
            try:
                response = self._llm_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": CLIP_ANALYSIS_PROMPT},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.7,
                    max_tokens=2000
                )
                return response.choices[0].message.content
            except Exception as e:
                logger.error(f"OpenAI API error: {e}")
                return None

        elif self._llm_type == "anthropic":
            try:
                response = self._llm_client.messages.create(
                    model="claude-3-haiku-20240307",
                    max_tokens=2000,
                    system=CLIP_ANALYSIS_PROMPT,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.content[0].text
            except Exception as e:
                logger.error(f"Anthropic API error: {e}")
                return None

        return None

    def _parse_llm_response(self, response: str, segments: List[Dict]) -> List[ClipDecision]:
        """Parse LLM response into ClipDecision objects."""
        clips = []
        try:
            # Extract JSON from response
            content = response.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            data = json.loads(content)
            clip_data = data.get("clips", [])

            # Create segment lookup for text preview
            def get_text_preview(start: float, end: float) -> str:
                text_parts = []
                for seg in segments:
                    seg_start = seg.get("start", 0)
                    seg_end = seg.get("end", seg_start + 1)
                    if seg_end > start and seg_start < end:
                        text_parts.append(seg.get("text", ""))
                return " ".join(text_parts)[:200]

            for i, clip in enumerate(clip_data):
                try:
                    start = float(clip.get("start", 0))
                    end = float(clip.get("end", start + 30))
                    duration = end - start

                    # Validate duration
                    if duration < 10 or duration > 90:
                        continue

                    style_str = clip.get("style", "default").lower()
                    try:
                        style = ClipStyle(style_str)
                    except ValueError:
                        style = ClipStyle.DEFAULT

                    clips.append(ClipDecision(
                        clip_id=f"clip_{uuid.uuid4().hex[:8]}",
                        start=start,
                        end=end,
                        duration=duration,
                        reason=clip.get("reason", "AI selected moment"),
                        score=min(1.0, max(0.0, float(clip.get("score", 0.7)))),
                        suggested_style=style,
                        title=clip.get("title", f"Clip {i+1}"),
                        text_preview=get_text_preview(start, end),
                        keywords=clip.get("keywords", [])
                    ))
                except (ValueError, KeyError) as e:
                    logger.warning(f"Failed to parse clip {i}: {e}")
                    continue

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
        except Exception as e:
            logger.error(f"Error parsing LLM response: {e}")

        return clips

    def _fallback_analysis(self, segments: List[Dict], total_duration: float) -> List[ClipDecision]:
        """
        Fallback rule-based clip detection when LLM is not available.
        Uses heuristics to find good clip moments.
        """
        clips = []

        if not segments:
            return clips

        # Target clip duration
        target_duration = 30.0
        min_duration = 15.0
        max_duration = 60.0

        # Score segments by various factors
        segment_scores = []
        for i, seg in enumerate(segments):
            text = seg.get("text", "").lower()
            start = seg.get("start", 0)
            end = seg.get("end", start + 1)

            score = 0.5  # Base score

            # Hook words (increase score)
            hook_words = ["secret", "amazing", "incredible", "shocking", "never", "always",
                         "best", "worst", "truth", "why", "how", "what if", "imagine",
                         "important", "crucial", "must", "need to", "you should"]
            for word in hook_words:
                if word in text:
                    score += 0.1

            # Emotional words
            emotional_words = ["love", "hate", "fear", "excited", "angry", "happy", "sad",
                              "surprised", "funny", "hilarious", "terrible", "wonderful"]
            for word in emotional_words:
                if word in text:
                    score += 0.08

            # Sentence starters (good for hooks)
            if text.startswith(("the thing is", "here's the", "let me tell", "i'm going to")):
                score += 0.15

            # Questions (engaging)
            if "?" in text:
                score += 0.1

            segment_scores.append({
                "index": i,
                "segment": seg,
                "score": min(1.0, score),
                "start": start,
                "end": end
            })

        # Find clip boundaries using sliding window
        window_segments = 5  # Look at groups of 5 segments

        for i in range(0, len(segment_scores) - window_segments, window_segments // 2):
            window = segment_scores[i:i + window_segments]
            if not window:
                continue

            start_time = window[0]["start"]
            end_time = window[-1]["end"]
            duration = end_time - start_time

            # Adjust to target duration
            if duration > max_duration:
                end_time = start_time + target_duration
                duration = target_duration
            elif duration < min_duration:
                continue

            # Calculate average score for window
            avg_score = sum(w["score"] for w in window) / len(window)

            # Get text preview
            text_preview = " ".join(w["segment"].get("text", "") for w in window)[:200]

            # Determine style based on content
            style = ClipStyle.DEFAULT
            text_lower = text_preview.lower()
            if any(w in text_lower for w in ["funny", "laugh", "joke", "hilarious"]):
                style = ClipStyle.FUNNY
            elif any(w in text_lower for w in ["learn", "how to", "step", "tutorial"]):
                style = ClipStyle.EDUCATIONAL
            elif any(w in text_lower for w in ["believe", "achieve", "success", "dream"]):
                style = ClipStyle.MOTIVATIONAL
            elif any(w in text_lower for w in ["story", "happened", "once", "remember"]):
                style = ClipStyle.STORYTELLING

            clips.append(ClipDecision(
                clip_id=f"clip_{uuid.uuid4().hex[:8]}",
                start=start_time,
                end=end_time,
                duration=duration,
                reason="Auto-detected engaging moment",
                score=avg_score,
                suggested_style=style,
                title=f"Clip at {int(start_time // 60)}:{int(start_time % 60):02d}",
                text_preview=text_preview,
                keywords=[]
            ))

        # Sort by score and return top clips
        clips.sort(key=lambda c: c.score, reverse=True)

        # Remove overlapping clips
        final_clips = []
        for clip in clips:
            overlap = False
            for existing in final_clips:
                if not (clip.end <= existing.start or clip.start >= existing.end):
                    overlap = True
                    break
            if not overlap:
                final_clips.append(clip)
            if len(final_clips) >= 5:
                break

        return final_clips

    def analyze(
        self,
        transcript_segments: List[Dict[str, Any]],
        total_duration: float,
        source_title: Optional[str] = None,
        prompt: Optional[str] = None
    ) -> DirectorResult:
        """
        Analyze transcript and return clip decisions.

        Args:
            transcript_segments: List of {start, end, text} segments
            total_duration: Total video duration in seconds
            source_title: Optional title of source video
            prompt: Optional custom prompt for clip selection

        Returns:
            DirectorResult with clip decisions
        """
        logger.info(f"Director analyzing {len(transcript_segments)} segments, {total_duration:.1f}s")

        if not transcript_segments:
            return DirectorResult(
                success=False,
                clips=[],
                total_duration=total_duration,
                source_title=source_title,
                error="No transcript segments provided"
            )

        # Build transcript text with timestamps
        transcript_text = ""
        for seg in transcript_segments:
            start = seg.get("start", 0)
            text = seg.get("text", "")
            transcript_text += f"[{start:.1f}s] {text}\n"

        # Build analysis prompt
        user_prompt = f"""Analyze this video transcript and identify the best moments for short clips.

VIDEO TITLE: {source_title or 'Unknown'}
TOTAL DURATION: {total_duration:.1f} seconds

TRANSCRIPT:
{transcript_text}

{f'SPECIAL INSTRUCTIONS: {prompt}' if prompt else ''}

Find 3-7 of the most engaging, viral-worthy moments. Return valid JSON."""

        # Try LLM analysis
        clips = []
        if self._llm_client:
            response = self._call_llm(user_prompt)
            if response:
                clips = self._parse_llm_response(response, transcript_segments)
                logger.info(f"Director LLM found {len(clips)} clips")

        # Fallback if LLM failed or no clips found
        if not clips:
            logger.info("Using fallback rule-based analysis")
            clips = self._fallback_analysis(transcript_segments, total_duration)

        # Sort by start time
        clips.sort(key=lambda c: c.start)

        return DirectorResult(
            success=len(clips) > 0,
            clips=clips,
            total_duration=total_duration,
            source_title=source_title
        )
