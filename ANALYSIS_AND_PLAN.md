# 🔍 АНАЛИЗ ПРОБЛЕМ И ПЛАН ИСПРАВЛЕНИЙ

**Дата:** 8 января 2026  
**Статус:** 📋 ПЛАН К ОБСУЖДЕНИЮ (требует одобрения)

---

## 🎯 ПРОБЛЕМА 1: Повтор аудио в последних 5 секундах

### Анализ текущей логики:

#### 📍 **Место проблемы:** `app/services/faceless_engine.py`

**Строка 996-1011:**
```python
cmd = [
    FFMPEG_PATH, "-y",
    "-i", video_path,           # Вход 0: видео (склеенные клипы)
    "-i", job.audio_path,        # Вход 1: аудио (TTS)
    "-filter_complex", f"[0:v]{filter_str}[vout]",
    "-map", "[vout]",
    "-map", "1:a",               # Берём аудио из входа 1
    "-c:v", "libx264",
    "-preset", "fast",
    "-crf", "18",
    "-c:a", "aac",
    "-b:a", "192k",
    "-t", str(job.audio_duration),  # ⚠️ ПРОБЛЕМА ЗДЕСЬ!
    "-shortest",                     # ⚠️ И ЗДЕСЬ!
    output_path
]
```

### 🐛 **Причина проблемы:**

#### Сценарий возникновения:
```
1. Генерация аудио (TTS):
   Длительность: 57.3 секунды

2. Расчёт длительности сегментов:
   12 сегментов × 5 секунд = 60 секунд

3. Ken Burns анимация:
   Создаёт 12 клипов × 5 сек = 60 секунд

4. Склейка клипов:
   Итоговое видео: 60 секунд

5. Финальный рендер FFmpeg:
   -t 57.3  → Обрезает до 57.3 сек
   -shortest → Останавливается на минимальной длительности
   
   НО! Если последний клип уже начался (55-60 сек),
   а аудио заканчивается на 57.3 сек,
   FFmpeg может "зациклить" аудио для заполнения!
```

### 🔍 **Глубинная проблема:**

**В `_calculate_segment_durations()` (строка 937-962):**
```python
def _calculate_segment_durations(
    self,
    segments: List[Dict[str, Any]],
    total_audio_duration: float
) -> List[float]:
    """Calculate segment durations based on audio timing."""
    num_segments = len(segments)
    avg_duration = total_audio_duration / num_segments
    
    # ... дальше код ...
    
    durations = [max(d, min_duration) for d in durations]
    return durations
```

**Проблема:**
- Сумма `durations` может быть **больше** `total_audio_duration`!
- Например: аудио 57.3с, но видео 60с
- Последние 2.7 секунды видео = **без аудио** или **зацикленное аудио**

---

## 🎯 ПРОБЛЕМА 2: Хаотичная генерация промптов (нет контекста)

### Анализ текущей логики:

#### 📍 **Место проблемы:** `app/services/agents/visual_director.py`

**Текущий процесс (строка 286-448):**
```python
async def segment_story(self, narrative, topic, style, ...):
    # 1. Получает весь narrative целиком ✅
    
    # 2. Отправляет ONE API call в GPT-4o-mini
    payload = {
        "model": self.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}  # Весь narrative
        ],
        ...
    }
    
    # 3. GPT возвращает 12 сегментов с промптами
    
    # 4. Post-processing:
    segments = self._clean_repetitive_phrases(segments)
    segments = self.deduplicate_prompts(segments)
    
    return SegmentationResult(segments=segments, ...)
```

### 🐛 **Проблемы:**

#### **Проблема 2.1: Нет явного "global_scene_context"**

**Текущий prompt (строка 346-396):**
```python
user_prompt = f"""Divide this narrative into EXACTLY {segment_count} segments...

NARRATIVE:
{narrative}

TOPIC: {topic}
STYLE: {style.value.upper()}

CHARACTER CONSISTENCY (ABSOLUTELY CRITICAL!):
If a character appears in multiple segments, use IDENTICAL description...
```

**ЧТО НЕ ТАК:**
- ✅ GPT видит весь narrative
- ✅ Есть инструкция про character consistency
- ❌ НЕТ explicit "global_scene_context" переменной
- ❌ Нет pre-analysis: "Какая эпоха? Какой стиль освещения? Какая палитра?"

**РЕЗУЛЬТАТ:**
- Сегмент 1: "Medieval castle, dark lighting, foggy atmosphere"
- Сегмент 5: "Castle interior, bright daylight, clear sky"
- ❌ НЕСОГЛАСОВАННОСТЬ! День стал ночью? Туман исчез?

#### **Проблема 2.2: Нет "Storyboard" этапа**

**Текущий процесс:**
```
1. GPT получает narrative
2. GPT сразу генерирует 12 промптов
3. Готово
```

**ЧТО НЕ ТАК:**
- Нет этапа **планирования**: "Какие ключевые визуальные элементы?"
- Нет этапа **анализа**: "Какие персонажи? Какие локации?"
- Нет этапа **согласования**: "Кадр 5 логически следует из кадра 4?"

**ИДЕАЛЬНЫЙ ПРОЦЕСС (как в autoshorts.ai/Hollywood):**
```
1. ANALYSIS: Анализ narrative → Извлечь:
   - Персонажи (с детальным описанием)
   - Локации (с атмосферой)
   - Временной период (эпоха, время суток)
   - Цветовая палитра
   - Эмоциональная арка

2. STORYBOARD: Создать визуальный план:
   - Кадр 1: [Персонаж X] в [Локация Y] - [Действие] - [Эмоция]
   - Кадр 2: [Тот же персонаж] в [Та же локация] - [Продолжение действия]
   - ...
   - Проверка: Есть ли логическая связь между кадрами?

3. PROMPTS: Преобразовать storyboard → технические промпты:
   - Все промпты наследуют global_scene_context
   - Персонажи описываются ОДИНАКОВО во всех кадрах
   - Атмосфера консистентна (если нет явного перехода день→ночь)
```

#### **Проблема 2.3: Нет frame-to-frame consistency check**

**После генерации промптов НЕТ проверки:**
```python
# НЕТ ЭТОГО:
def check_frame_consistency(segment_n, segment_n_plus_1):
    """
    Проверить логическую связь между кадрами.
    
    Вопросы:
    - Персонаж тот же?
    - Локация та же или логичный переход?
    - Освещение консистентно?
    - Нет внезапных скачков (день→ночь без объяснения)?
    """
    pass
```

---

## 🛠️ ПЛАН ИСПРАВЛЕНИЙ

### ✅ **ЭТАП 1: Исправление аудио-видео синхронизации**

#### Файл: `app/services/faceless_engine.py`

**Изменение 1.1:** Строка 937-962 - `_calculate_segment_durations()`

**БЫЛО:**
```python
def _calculate_segment_durations(self, segments, total_audio_duration):
    num_segments = len(segments)
    avg_duration = total_audio_duration / num_segments
    # ... расчёт ...
    durations = [max(d, min_duration) for d in durations]
    return durations
```

**СТАНЕТ:**
```python
def _calculate_segment_durations(self, segments, total_audio_duration):
    """
    Calculate segment durations that EXACTLY match audio duration.
    
    CRITICAL FIX: Ensures sum(durations) == total_audio_duration
    to prevent audio repetition in last frames.
    """
    num_segments = len(segments)
    min_duration = 2.0  # Минимум 2 секунды на сегмент
    
    # Initial equal distribution
    base_duration = total_audio_duration / num_segments
    durations = [base_duration] * num_segments
    
    # Apply min_duration constraint
    for i in range(num_segments):
        if durations[i] < min_duration:
            shortage = min_duration - durations[i]
            durations[i] = min_duration
            
            # Redistribute shortage across other segments
            remaining_segments = num_segments - i - 1
            if remaining_segments > 0:
                per_segment_reduction = shortage / remaining_segments
                for j in range(i + 1, num_segments):
                    durations[j] = max(min_duration, durations[j] - per_segment_reduction)
    
    # CRITICAL: Force exact match to audio duration
    current_total = sum(durations)
    if abs(current_total - total_audio_duration) > 0.1:  # 100ms tolerance
        # Scale all durations proportionally
        scale_factor = total_audio_duration / current_total
        durations = [d * scale_factor for d in durations]
        
        logger.info(f"[DURATION_FIX] Scaled durations to match audio: {current_total:.2f}s → {total_audio_duration:.2f}s")
    
    # Verify
    final_total = sum(durations)
    logger.info(f"[DURATION_CHECK] Audio: {total_audio_duration:.2f}s, Video segments: {final_total:.2f}s, Diff: {abs(final_total - total_audio_duration):.3f}s")
    
    return durations
```

**Изменение 1.2:** Строка 996-1011 - `_render_final_video()`

**БЫЛО:**
```python
cmd = [
    FFMPEG_PATH, "-y",
    "-i", video_path,
    "-i", job.audio_path,
    "-filter_complex", f"[0:v]{filter_str}[vout]",
    "-map", "[vout]",
    "-map", "1:a",
    "-c:v", "libx264",
    "-preset", "fast",
    "-crf", "18",
    "-c:a", "aac",
    "-b:a", "192k",
    "-t", str(job.audio_duration),  # ⚠️ Может вызвать проблемы
    "-shortest",                     # ⚠️ Конфликтует с -t
    output_path
]
```

**СТАНЕТ:**
```python
# CRITICAL FIX: Remove conflicting -t and -shortest flags
# Instead, ensure video and audio are EXACTLY same duration before FFmpeg
cmd = [
    FFMPEG_PATH, "-y",
    "-i", video_path,
    "-i", job.audio_path,
    "-filter_complex", f"[0:v]{filter_str}[vout]",
    "-map", "[vout]",
    "-map", "1:a",
    "-c:v", "libx264",
    "-preset", "fast",
    "-crf", "18",
    "-c:a", "aac",
    "-b:a", "192k",
    # ✅ REMOVED: "-t", str(job.audio_duration),
    # ✅ REMOVED: "-shortest",
    # Instead, video segments are pre-calculated to match audio exactly
    output_path
]
```

**Изменение 1.3:** Строка 846-850 - Pre-verification перед concatenation

**ДОБАВИТЬ:**
```python
# Concatenate animated clips (only if we have clips)
concat_video_path = str(job_dir / "concat_video.mp4")
if animated_clips:
    # CRITICAL: Verify total clip duration matches audio
    total_clip_duration = sum(clip.duration for clip in animated_clips)
    audio_duration = job.audio_duration
    
    if abs(total_clip_duration - audio_duration) > 0.5:  # 500ms tolerance
        logger.warning(f"[DURATION_MISMATCH] Clips: {total_clip_duration:.2f}s, Audio: {audio_duration:.2f}s")
        logger.warning(f"[DURATION_MISMATCH] Adjusting last clip to match audio exactly")
        
        # Adjust last clip duration
        diff = audio_duration - (total_clip_duration - animated_clips[-1].duration)
        animated_clips[-1].duration = max(2.0, diff)  # Min 2 seconds
    
    await self.ken_burns.concatenate_clips(animated_clips, concat_video_path)
```

---

### ✅ **ЭТАП 2: Context-Aware Visual Generation**

#### Файл: `app/services/agents/visual_director.py`

**Изменение 2.1:** Добавить dataclass для Global Scene Context

**ДОБАВИТЬ в начало файла (после imports):**
```python
@dataclass
class GlobalSceneContext:
    """
    Global visual context for the entire video.
    Ensures all frames share consistent visual language.
    """
    # Core identifiers
    topic: str
    era: str  # "medieval", "modern", "futuristic", etc.
    time_of_day: str  # "morning", "noon", "evening", "night"
    season: str  # "spring", "summer", "fall", "winter"
    
    # Visual style
    color_palette: List[str]  # ["dark blue", "gold", "crimson"]
    lighting_style: str  # "golden hour", "dramatic shadows", "soft diffused"
    atmosphere: str  # "mystical", "gritty", "serene", "tense"
    weather: str  # "clear", "foggy", "rainy", "snowy"
    
    # Characters (consistent descriptions)
    main_characters: List[Dict[str, str]]  # [{"id": "hero", "description": "Man, 35, brown hair, ..."}]
    
    # Locations
    primary_location: str  # "medieval castle"
    secondary_locations: List[str]  # ["throne room", "courtyard", "battlefield"]
    
    # Technical
    art_style: str  # "photorealistic", "anime", etc.
    camera_style: str  # "cinematic", "documentary", "action"
    
    def to_prompt_prefix(self) -> str:
        """Generate consistent prefix for all prompts."""
        return f"{self.era} era, {self.time_of_day} {self.lighting_style}, {self.atmosphere} atmosphere, {self.weather} weather"
```

**Изменение 2.2:** Новый метод - `_analyze_narrative_context()`

**ДОБАВИТЬ в класс VisualDirector:**
```python
async def _analyze_narrative_context(
    self,
    narrative: str,
    topic: str,
    style: ScriptStyle,
    art_style: str
) -> GlobalSceneContext:
    """
    PHASE 1: Analyze narrative to extract global visual context.
    
    This ensures all frames share the same:
    - Era/period
    - Lighting style
    - Color palette
    - Character descriptions
    - Atmospheric mood
    
    Example:
    Input: "Чингисхан родился в степи..."
    Output: GlobalSceneContext(
        era="13th century Mongol Empire",
        time_of_day="golden hour",
        lighting_style="dramatic sunset lighting",
        atmosphere="epic historical",
        main_characters=[{"id": "genghis", "description": "Man, 35, mongolian warrior, ..."}],
        ...
    )
    """
    if not self.api_key:
        # Fallback context
        return self._create_fallback_context(topic, style, art_style)
    
    system_prompt = """You are a VISUAL CONTEXT ANALYZER for video production.

Your task: Analyze a narrative and extract GLOBAL VISUAL CONTEXT that will be applied to ALL frames.

Output JSON with these fields:
{
  "era": "Historical period (e.g., '13th century', 'modern day', 'futuristic 2050')",
  "time_of_day": "morning/noon/evening/night",
  "season": "spring/summer/fall/winter",
  "color_palette": ["color1", "color2", "color3"],
  "lighting_style": "Consistent lighting (e.g., 'golden hour', 'dramatic shadows')",
  "atmosphere": "Overall mood (e.g., 'epic', 'mysterious', 'serene')",
  "weather": "clear/foggy/rainy/snowy",
  "main_characters": [
    {
      "id": "character1",
      "description": "Detailed physical description (e.g., 'Man, 35, brown hair, beard, traditional clothes')"
    }
  ],
  "primary_location": "Main setting",
  "secondary_locations": ["location1", "location2"],
  "camera_style": "cinematic/documentary/action"
}

CRITICAL: This context will be applied to ALL 12 frames, so it must be:
- Consistent (no contradictions)
- Detailed (enough to generate identical visuals)
- Era-appropriate (lighting, colors match the period)
"""

    user_prompt = f"""Analyze this narrative and extract global visual context:

NARRATIVE:
{narrative}

TOPIC: {topic}
STYLE: {style.value}
ART STYLE: {art_style}

Return ONLY valid JSON with the visual context."""

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
            "max_tokens": 800,
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
        context = GlobalSceneContext(
            topic=topic,
            era=content.get("era", "modern"),
            time_of_day=content.get("time_of_day", "day"),
            season=content.get("season", "summer"),
            color_palette=content.get("color_palette", ["neutral"]),
            lighting_style=content.get("lighting_style", "natural"),
            atmosphere=content.get("atmosphere", "neutral"),
            weather=content.get("weather", "clear"),
            main_characters=content.get("main_characters", []),
            primary_location=content.get("primary_location", topic),
            secondary_locations=content.get("secondary_locations", []),
            art_style=art_style,
            camera_style=content.get("camera_style", "cinematic")
        )
        
        logger.info(f"[CONTEXT_ANALYSIS] Extracted context: {context.era}, {context.atmosphere}, {len(context.main_characters)} characters")
        return context
        
    except Exception as e:
        logger.error(f"[CONTEXT_ANALYSIS] Failed: {e}")
        return self._create_fallback_context(topic, style, art_style)
```

**Изменение 2.3:** Новый метод - `_create_storyboard()`

**ДОБАВИТЬ:**
```python
async def _create_storyboard(
    self,
    narrative: str,
    segments: List[VisualSegment],
    global_context: GlobalSceneContext
) -> List[VisualSegment]:
    """
    PHASE 2: Create visual storyboard with frame-to-frame consistency.
    
    Takes raw segments and enriches them with:
    - Global context inheritance
    - Character consistency
    - Location transitions
    - Logical flow between frames
    
    Example:
    Frame 4: "Hero in castle courtyard, preparing for battle"
    Frame 5: "Hero on horseback, riding towards battlefield"
    ✅ LOGICAL: Courtyard → Battlefield transition makes sense
    
    Frame 4: "Hero in castle, daylight"
    Frame 5: "Hero in cave, nighttime"
    ❌ ILLOGICAL: How did he teleport to a cave at night?
    """
    if not self.api_key:
        # Apply fallback context
        return self._apply_fallback_storyboard(segments, global_context)
    
    # Build character map for easy reference
    character_map = {char["id"]: char["description"] for char in global_context.main_characters}
    
    system_prompt = f"""You are a STORYBOARD ARTIST creating visual shot list.

GLOBAL CONTEXT (MUST be applied to ALL frames):
Era: {global_context.era}
Time: {global_context.time_of_day}
Lighting: {global_context.lighting_style}
Atmosphere: {global_context.atmosphere}
Weather: {global_context.weather}
Color Palette: {', '.join(global_context.color_palette)}
Primary Location: {global_context.primary_location}

CHARACTERS (use EXACT descriptions):
{json.dumps(character_map, indent=2)}

Your task: For each segment, create a detailed SHOT DESCRIPTION that:
1. Inherits global context (era, lighting, atmosphere)
2. Uses IDENTICAL character descriptions if character appears
3. Ensures logical transitions between frames
4. Specifies camera angle and shot type

Output JSON array with 12 shots:
[
  {{
    "index": 0,
    "shot_type": "wide shot/close-up/medium shot",
    "subject": "EXACT character description or object",
    "action": "What's happening",
    "location": "Specific location from global context",
    "camera_angle": "low angle/high angle/eye level",
    "transition_from_previous": "How this connects to previous frame (null for frame 0)"
  }},
  ...
]"""

    # Prepare segment texts for context
    segment_texts = [f"Segment {i}: {seg.text}" for i, seg in enumerate(segments)]
    
    user_prompt = f"""Create storyboard for these narrative segments:

{chr(10).join(segment_texts)}

CRITICAL RULES:
1. ALL frames must share: {global_context.era}, {global_context.time_of_day}, {global_context.lighting_style}
2. Character descriptions MUST be IDENTICAL across frames
3. Each frame must logically follow the previous (no teleportation!)
4. Mix shot types for variety (wide, medium, close-up)

Return valid JSON array with 12 detailed shots."""

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
            "temperature": 0.5,
            "max_tokens": 3000,
            "response_format": {"type": "json_object"}
        }
        
        response = await self.client.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload
        )
        
        if response.status_code != 200:
            logger.error(f"[STORYBOARD] API error: {response.status_code}")
            return self._apply_fallback_storyboard(segments, global_context)
        
        data = response.json()
        content = json.loads(data["choices"][0]["message"]["content"])
        shots = content.get("shots", content.get("storyboard", []))
        
        # Enrich segments with storyboard data
        for i, seg in enumerate(segments):
            if i < len(shots):
                shot = shots[i]
                # Store storyboard info in segment for prompt generation
                seg.visual_keywords.extend([
                    shot.get("subject", ""),
                    shot.get("location", ""),
                    shot.get("shot_type", "")
                ])
                seg.camera_direction = shot.get("camera_angle", "eye level")
        
        logger.info(f"[STORYBOARD] Created {len(shots)} shots with logical transitions")
        return segments
        
    except Exception as e:
        logger.error(f"[STORYBOARD] Failed: {e}")
        return self._apply_fallback_storyboard(segments, global_context)
```

**Изменение 2.4:** Модифицировать `segment_story()` - добавить фазы

**ИЗМЕНИТЬ основной метод:**
```python
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
    Context-Aware Visual Generation (3-phase process):
    
    PHASE 1: CONTEXT ANALYSIS
      - Analyze narrative to extract global visual context
      - Determine era, lighting, atmosphere, characters, locations
      
    PHASE 2: STORYBOARD CREATION
      - Create visual shot list with frame-to-frame consistency
      - Ensure logical transitions between frames
      
    PHASE 3: PROMPT GENERATION
      - Convert storyboard to technical Nano Banana prompts
      - Apply global context to every prompt
      - Deduplicate similar prompts
    """
    segment_count = get_segment_count(duration_seconds)
    logger.info(f"[VISUAL_DIRECTOR] 🎬 CONTEXT-AWARE GENERATION: {segment_count} segments")
    logger.info(f"[VISUAL_DIRECTOR] Topic: {topic}, Style: {style.value}, Art: {art_style}")
    
    # =================================================================
    # PHASE 1: CONTEXT ANALYSIS
    # =================================================================
    logger.info(f"[PHASE_1] 🔍 Analyzing narrative for global visual context...")
    global_context = await self._analyze_narrative_context(
        narrative, topic, style, art_style
    )
    logger.info(f"[PHASE_1] ✅ Context extracted:")
    logger.info(f"  Era: {global_context.era}")
    logger.info(f"  Lighting: {global_context.lighting_style}")
    logger.info(f"  Atmosphere: {global_context.atmosphere}")
    logger.info(f"  Characters: {len(global_context.main_characters)}")
    
    # =================================================================
    # PHASE 2: INITIAL SEGMENTATION (from GPT)
    # =================================================================
    logger.info(f"[PHASE_2] 📝 Generating initial segments from narrative...")
    
    # ... (existing segment generation code) ...
    # Generate raw segments as before
    segments = await self._generate_segments_from_narrative(
        narrative, topic, style, language, 
        duration_seconds, art_style, global_context
    )
    
    # =================================================================
    # PHASE 3: STORYBOARD WITH CONSISTENCY
    # =================================================================
    logger.info(f"[PHASE_3] 🎨 Creating visual storyboard with frame-to-frame logic...")
    segments = await self._create_storyboard(narrative, segments, global_context)
    
    # =================================================================
    # PHASE 4: FINAL PROMPT GENERATION
    # =================================================================
    logger.info(f"[PHASE_4] 🖼️ Converting storyboard to technical prompts...")
    segments = self._generate_technical_prompts(segments, global_context)
    
    # =================================================================
    # PHASE 5: CONSISTENCY CHECKS & DEDUPLICATION
    # =================================================================
    logger.info(f"[PHASE_5] ✓ Running consistency checks...")
    segments = self._verify_frame_consistency(segments, global_context)
    segments = self.deduplicate_prompts(segments)
    
    total_duration = sum(seg.duration for seg in segments)
    logger.info(f"[VISUAL_DIRECTOR] ✅ COMPLETE: {len(segments)} context-aware segments, {total_duration:.1f}s")
    
    return SegmentationResult(
        segments=segments,
        style_consistency_string=global_context.to_prompt_prefix(),
        total_duration=total_duration,
        success=True
    )
```

**Изменение 2.5:** Новый метод - `_verify_frame_consistency()`

**ДОБАВИТЬ:**
```python
def _verify_frame_consistency(
    self,
    segments: List[VisualSegment],
    global_context: GlobalSceneContext
) -> List[VisualSegment]:
    """
    PHASE 5: Verify frame-to-frame consistency and fix issues.
    
    Checks:
    1. Does frame N+1 logically follow frame N?
    2. Are character descriptions identical?
    3. Is lighting/atmosphere consistent (unless explicit transition)?
    4. Are there sudden teleportations (location jumps without reason)?
    """
    logger.info(f"[CONSISTENCY_CHECK] Verifying {len(segments)} frames...")
    
    issues_found = 0
    fixes_applied = 0
    
    for i in range(1, len(segments)):
        prev_seg = segments[i - 1]
        curr_seg = segments[i]
        
        prev_prompt = prev_seg.visual_prompt.lower()
        curr_prompt = curr_seg.visual_prompt.lower()
        
        # Check 1: Character consistency
        for character in global_context.main_characters:
            char_desc = character["description"].lower()
            char_words = set(char_desc.split())
            
            prev_has_char = any(word in prev_prompt for word in char_words)
            curr_has_char = any(word in curr_prompt for word in char_words)
            
            if prev_has_char and curr_has_char:
                # Both frames have character - descriptions must match
                # Extract character description from prompts
                # If they differ, flag it
                # (Simplified check for now)
                pass
        
        # Check 2: Lighting consistency
        lighting_keywords = ["daylight", "night", "sunset", "sunrise", "dark", "bright"]
        prev_lighting = [kw for kw in lighting_keywords if kw in prev_prompt]
        curr_lighting = [kw for kw in lighting_keywords if kw in curr_prompt]
        
        if prev_lighting and curr_lighting and prev_lighting[0] != curr_lighting[0]:
            logger.warning(f"[CONSISTENCY] Frame {i}: Lighting changed from {prev_lighting[0]} to {curr_lighting[0]}")
            issues_found += 1
            
            # Auto-fix: Keep previous lighting
            if not curr_seg.text.lower().contains("later") and not curr_seg.text.lower().contains("next day"):
                # No temporal transition in narration, so keep same lighting
                curr_seg.visual_prompt = curr_seg.visual_prompt.replace(curr_lighting[0], prev_lighting[0])
                fixes_applied += 1
                logger.info(f"[CONSISTENCY] Auto-fixed: Changed lighting back to {prev_lighting[0]}")
        
        # Check 3: Location jumps
        # (More complex - would need location extraction)
        
    logger.info(f"[CONSISTENCY_CHECK] Issues found: {issues_found}, Auto-fixed: {fixes_applied}")
    
    return segments
```

---

## 📋 ИТОГОВЫЙ ПЛАН (Step-by-Step)

### 🔵 ЭТАП 1: Аудио-видео синхронизация (1-2 часа)

**Файлы:**
- `app/services/faceless_engine.py`

**Изменения:**
1. ✅ Переписать `_calculate_segment_durations()` - точное соответствие аудио
2. ✅ Убрать `-t` и `-shortest` из FFmpeg команды в `_render_final_video()`
3. ✅ Добавить pre-verification перед concatenation клипов
4. ✅ Добавить логирование: аудио vs видео длительность

**Тестирование:**
```bash
# Создать видео 60 сек
# Проверить последние 5 секунд - НЕТ повтора аудио
```

---

### 🔵 ЭТАП 2: Context-Aware Generation (3-5 часов)

**Файлы:**
- `app/services/agents/visual_director.py`

**Изменения:**
1. ✅ Добавить `GlobalSceneContext` dataclass
2. ✅ Новый метод: `_analyze_narrative_context()` - Phase 1
3. ✅ Новый метод: `_create_storyboard()` - Phase 2
4. ✅ Модифицировать `segment_story()` - 5-фазный процесс
5. ✅ Новый метод: `_verify_frame_consistency()` - Phase 5
6. ✅ Обновить промпты для включения global_context

**Тестирование:**
```bash
# Создать видео "Казахское ханство"
# Проверить:
# - Эпоха одинаковая во всех кадрах
# - Освещение консистентно
# - Персонажи описаны идентично
# - Нет скачков день→ночь
```

---

### 🔵 ЭТАП 3: Документация и финальные тесты (1 час)

**Создать:**
- `CONTEXT_AWARE_GENERATION.md` - документация нового подхода
- Юнит-тесты для `_verify_frame_consistency()`
- Примеры "до и после"

---

## ⚠️ РИСКИ И КОМПРОМИССЫ

### Риск 1: Увеличение времени генерации

**Было:**
- 1 API call → 12 промптов (5-10 сек)

**Станет:**
- API call 1: Context analysis (5 сек)
- API call 2: Storyboard (10 сек)
- API call 3: Segment generation (10 сек)
- **ИТОГО: +20 секунд**

**Компромисс:** Качество важнее скорости

### Риск 2: Дополнительная стоимость API

**Было:**
- 1 × GPT-4o-mini call ≈ $0.002

**Станет:**
- 3 × GPT-4o-mini calls ≈ $0.006

**Компромисс:** +$0.004 за консистентность визуалов (acceptable)

### Риск 3: Сложность отладки

**Решение:** Подробное логирование каждой фазы

---

## 🎯 ОЖИДАЕМЫЕ РЕЗУЛЬТАТЫ

### ДО:
```
Кадр 1: "Medieval warrior in foggy morning"
Кадр 5: "Same warrior in bright daylight castle"
Кадр 9: "Knight at night in a cave"
❌ Несогласованность! Где он? Какое время суток?
```

### ПОСЛЕ:
```
Global Context:
  Era: 13th century
  Time: Golden hour (sunset)
  Lighting: Warm dramatic lighting
  Atmosphere: Epic historical
  Character: "Man, 35, mongolian warrior, leather armor, brown hair, weathered face"

Кадр 1: "Man, 35, mongolian warrior, leather armor, brown hair, weathered face, standing on hill, 13th century mongolian steppe, golden hour warm lighting, epic atmosphere, wide shot"

Кадр 5: "Man, 35, mongolian warrior, leather armor, brown hair, weathered face, riding horse, 13th century mongolian steppe, golden hour warm lighting, epic atmosphere, medium shot"

Кадр 9: "Man, 35, mongolian warrior, leather armor, brown hair, weathered face, leading army, 13th century mongolian steppe, golden hour warm lighting, epic atmosphere, low angle shot"

✅ PERFECT CONSISTENCY!
- Персонаж ИДЕНТИЧЕН
- Эпоха одинаковая
- Освещение стабильное
- Атмосфера консистентна
```

---

## 🤔 ВОПРОСЫ ДЛЯ ОБСУЖДЕНИЯ

1. **Приоритет:** Начать с аудио-синхронизации (быстрый фикс) или сразу с context-aware generation?

2. **API вызовы:** Согласен с 3 вызовами вместо 1 (+$0.004 и +20 сек) ради качества?

3. **Fallback:** Если GPT-4o-mini недоступен, использовать упрощённый fallback context или вернуть ошибку?

4. **Тестирование:** Нужны ли юнит-тесты или достаточно ручного тестирования "до/после"?

5. **Дополнительные фичи:** Добавить ли возможность пользователю задавать global_context вручную? (например, "Хочу все кадры в ночном освещении")

---

## ✅ ЧЕКЛИСТ ДЛЯ ОДОБРЕНИЯ

Перед началом выполнения, подтверди:

- [ ] Я понял обе проблемы (аудио повтор + хаотичные промпты)
- [ ] План исправлений выглядит разумно
- [ ] Я согласен с дополнительными API вызовами (+$0.004/видео)
- [ ] Я согласен с увеличением времени генерации (+20 сек)
- [ ] Начинаем с аудио-синхронизации (быстрый win)
- [ ] Затем context-aware generation (большая фича)

**Ответ:** Напиши "ОК" или задай вопросы!

---

**Автор:** Claude 4.5 Sonnet  
**Дата:** 8 января 2026  
**Статус:** 📋 ОЖИДАНИЕ ОДОБРЕНИЯ
