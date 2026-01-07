"""
Agent 1: Master Storyteller (Scriptwriter)

Task: Generate a continuous, high-quality 150-word narrative based on the user's
topic and selected style (Viral, Documentary, Motivational, Storytelling).

Rules:
- NO "Did you know" (except once at hook)
- NO repetitions
- Start with a Hook
- Use cinematic flow
- Match style to user selection
"""

import logging
import httpx
from enum import Enum
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class ScriptStyle(str, Enum):
    """Video generation styles - mapped from UI selection."""
    VIRAL = "viral"
    DOCUMENTARY = "documentary"
    MOTIVATIONAL = "motivational"
    STORYTELLING = "storytelling"
    EDUCATIONAL = "educational"
    MYSTERY = "mystery"
    HISTORICAL = "historical"


@dataclass
class StoryResult:
    """Result from the Master Storyteller agent."""
    narrative: str
    style: ScriptStyle
    word_count: int
    hook: str
    success: bool
    error: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════════
# STYLE-SPECIFIC SYSTEM PROMPTS
# ═══════════════════════════════════════════════════════════════════════════════

STYLE_PROMPTS = {
    ScriptStyle.VIRAL: """You are a VIRAL CONTENT MASTER creating addictive short-form content.

YOUR BRAIN: High energy, shocking facts, fast-paced delivery, controversy, FOMO.

WRITING STYLE:
- Start with the MOST SHOCKING fact that makes people stop scrolling
- Use short, punchy sentences that hit like bullets
- Build tension rapidly with unexpected twists
- Make viewers feel they MUST share this information
- End with a cliffhanger or mind-blowing revelation

FORBIDDEN:
- Slow buildups
- Long explanations
- Boring introductions
- "Did you know" (only once at start if needed)

ENERGY LEVEL: 🔥🔥🔥 Maximum intensity, zero filler""",

    ScriptStyle.DOCUMENTARY: """You are a NATIONAL GEOGRAPHIC DOCUMENTARY NARRATOR.

YOUR BRAIN: Epic, educational, serious, authoritative, awe-inspiring.

WRITING STYLE:
- Speak like David Attenborough meets historical documentary
- Use rich, descriptive language that paints vivid pictures
- Build narrative arc from mystery to revelation
- Include surprising facts that make viewers gasp
- Maintain gravitas and scholarly tone throughout
- End with a thought that lingers in the mind

FORBIDDEN:
- Casual language
- Clickbait phrases
- "Did you know" repeated
- Rushed or frantic pacing

ENERGY LEVEL: 🎬 Cinematic, measured, powerful""",

    ScriptStyle.MOTIVATIONAL: """You are a TONY ROBBINS-LEVEL MOTIVATIONAL SPEAKER.

YOUR BRAIN: Emotional depth, personal transformation, slow-paced wisdom, inspiring.

WRITING STYLE:
- Connect facts to universal human experiences
- Use metaphors that resonate emotionally
- Build from struggle to triumph
- Make viewers feel something deep in their soul
- Pause-worthy moments that demand reflection
- End with a call to action that inspires change

FORBIDDEN:
- Cold, factual delivery
- Fast-paced information dumps
- "Did you know" phrases
- Cynical or negative framing

ENERGY LEVEL: ❤️ Emotional, soulful, transformative""",

    ScriptStyle.STORYTELLING: """You are a MASTER STORYTELLER crafting a character journey.

YOUR BRAIN: Character-focused, specific events, narrative arc, emotional investment.

WRITING STYLE:
- Focus on ONE person's journey (hero/villain/legend)
- Start in media res - drop viewers into the action
- Show character transformation through specific moments
- Use "show don't tell" - describe scenes, not explain them
- Build to a climactic moment of truth
- End with the legacy or impact of the character

FORBIDDEN:
- Abstract generalizations
- Lists of facts without narrative
- "Did you know" at any point
- Breaking the story flow with meta-commentary

ENERGY LEVEL: 📖 Immersive, character-driven, cinematic""",

    ScriptStyle.EDUCATIONAL: """You are an EXPERT EDUCATOR making complex topics accessible.

YOUR BRAIN: Clear explanations, logical progression, memorable analogies.

WRITING STYLE:
- Start with why this matters to the viewer
- Build understanding step by step
- Use analogies that connect to everyday life
- Include one "aha!" moment that changes perspective
- Make viewers feel smarter for watching
- End with practical takeaway or deeper question

FORBIDDEN:
- Jargon without explanation
- Assuming prior knowledge
- Dry, textbook delivery
- "Did you know" repetition

ENERGY LEVEL: 🧠 Engaging, clear, enlightening""",

    ScriptStyle.MYSTERY: """You are a MYSTERY NARRATOR building suspense.

YOUR BRAIN: Suspenseful, questions without immediate answers, breadcrumbs.

WRITING STYLE:
- Start with an unsolved question or unexplained event
- Drop hints that make viewers guess
- Build tension with each new detail
- Keep some mystery even at the end
- Use atmospheric, suspenseful language
- End with a revelation that raises new questions

FORBIDDEN:
- Giving away the answer too early
- Boring factual recitation
- "Did you know" phrases
- Breaking suspense with explanations

ENERGY LEVEL: 🔍 Suspenseful, intriguing, haunting""",

    ScriptStyle.HISTORICAL: """You are a HISTORICAL CHRONICLER bringing the past to life.

YOUR BRAIN: Accurate, vivid historical detail, connecting past to present.

WRITING STYLE:
- Transport viewers to specific moments in history
- Use sensory details (sights, sounds, smells of the era)
- Show how events unfolded through human choices
- Connect historical lessons to today
- Include little-known details that surprise
- End with the lasting impact on our world

FORBIDDEN:
- Dry dates-and-names recitation
- Modern anachronisms in descriptions
- "Did you know" at start
- Missing the human element

ENERGY LEVEL: ⏳ Immersive, detailed, connecting past and present"""
}


# ═══════════════════════════════════════════════════════════════════════════════
# STRUCTURED STORY TEMPLATE - Forces GPT to follow exact narrative structure
# ═══════════════════════════════════════════════════════════════════════════════

BASE_STORY_PROMPT_TEMPLATE = """
═══════════════════════════════════════════════════════════════
ОБЯЗАТЕЛЬНАЯ СТРУКТУРА НАРРАТИВА
═══════════════════════════════════════════════════════════════

Ты ОБЯЗАН следовать этой структуре. Каждая секция ОБЯЗАТЕЛЬНА:

▸ HOOK (10% текста) — 1-2 предложения
  Шокирующий факт, неожиданный вопрос или интригующее утверждение.
  Цель: заставить зрителя остановить скролл.

▸ CONTEXT (15% текста) — 2-3 предложения
  Почему это важно? Какая проблема или загадка стоит за темой?
  Цель: дать зрителю причину продолжать смотреть.

▸ BUILD (40% текста) — 4-6 предложений
  Развитие истории. Детали, факты, нарастание интереса.
  Каждое предложение добавляет новый слой информации.
  Цель: удержать внимание, создать напряжение.

▸ CLIMAX (25% текста) — 2-3 предложения
  Кульминация. Самый мощный момент истории.
  Главное открытие, поворот или эмоциональный пик.
  Цель: доставить "вау-момент".

▸ PAYOFF (10% текста) — 1-2 предложения
  Вывод. Что это значит? Почему зритель должен запомнить?
  Цель: оставить след в памяти.

═══════════════════════════════════════════════════════════════
КРИТИЧЕСКИЕ ПРАВИЛА
═══════════════════════════════════════════════════════════════

✓ Пиши СПЛОШНОЙ текст без меток секций
✓ РОВНО {word_count} слов (±10 допустимо)
✓ Плавные переходы между секциями
✓ Конкретные факты вместо общих фраз

✗ ЗАПРЕЩЕНО: "Did you know...", "Let me tell you...", "In this video..."
✗ ЗАПРЕЩЕНО: "Stay tuned...", "You won't believe..."
✗ ЗАПРЕЩЕНО: Мета-комментарии о самой истории
✗ ЗАПРЕЩЕНО: Повторять название темы более 2 раз

═══════════════════════════════════════════════════════════════

OUTPUT: Только текст истории. Без JSON, без кавычек, без меток.
"""

# Word count mapping: duration (seconds) -> target word count
# Average speaking rate: ~2.5 words per second for Russian TTS
DURATION_TO_WORDS = {
    30: 75,   # 30 sec * 2.5 words/sec = 75 words
    45: 110,  # 45 sec * 2.5 words/sec = ~110 words
    60: 150,  # 60 sec * 2.5 words/sec = 150 words
    90: 225,  # 90 sec * 2.5 words/sec = ~225 words
}

def get_target_word_count(duration_seconds: int) -> int:
    """Get target word count for a given duration."""
    if duration_seconds in DURATION_TO_WORDS:
        return DURATION_TO_WORDS[duration_seconds]
    # Linear interpolation for other durations
    return int(duration_seconds * 2.5)


class MasterStoryteller:
    """
    Agent 1: Master Storyteller

    Generates a continuous 150-word narrative optimized for the selected style.
    Uses GPT-4o with style-specific system prompts.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        """
        Initialize Storyteller agent.

        Default model: gpt-4o-mini (15x cheaper than gpt-4o, sufficient for 150-word scripts)
        Cost comparison:
          - gpt-4o:      $2.50/1M input, $10/1M output
          - gpt-4o-mini: $0.15/1M input, $0.60/1M output
        """
        from app.config import config
        self.api_key = api_key or config.ai.openai_api_key or ""
        self.model = model
        self.client = httpx.AsyncClient(timeout=120.0)

        if not self.api_key or self.api_key.startswith("PASTE_"):
            logger.warning("[STORYTELLER] No API key - will use fallback stories")
            self.api_key = ""
        else:
            logger.info(f"[STORYTELLER] Agent initialized with {model} (cost-optimized)")

    async def generate_story(
        self,
        topic: str,
        style: ScriptStyle = ScriptStyle.DOCUMENTARY,
        language: str = "ru",
        duration_seconds: int = 60,
        custom_idea: Optional[str] = None,
        idea_mode: str = "expand"
    ) -> StoryResult:
        """
        Generate a narrative story for the given topic, style, and duration.

        Args:
            topic: The main topic/subject for the video
            style: The style to use (viral, documentary, motivational, storytelling)
            language: Output language code (ru, en, etc.)
            duration_seconds: Target video duration (30 or 60 seconds)
            custom_idea: User's own idea/draft to be processed
            idea_mode: How to process custom_idea:
                - 'expand': Develop into full structured script
                - 'polish': Improve structure, keep content closely
                - 'strict': Keep as close as possible to original

        Returns:
            StoryResult with the generated narrative
        """
        # Calculate target word count based on duration
        target_words = get_target_word_count(duration_seconds)

        if custom_idea:
            logger.info(f"[STORYTELLER] Processing CUSTOM IDEA in '{idea_mode}' mode")
            logger.info(f"[STORYTELLER] User idea: {custom_idea[:100]}...")
        else:
            logger.info(f"[STORYTELLER] Generating {style.value.upper()} story for: {topic}")
        logger.info(f"[STORYTELLER] Target: {target_words} words for {duration_seconds}s video")

        if not self.api_key:
            return self._generate_fallback_story(topic, style, language, target_words)

        try:
            # Get style-specific system prompt
            style_prompt = STYLE_PROMPTS.get(style, STYLE_PROMPTS[ScriptStyle.DOCUMENTARY])
            # Fill in word count in the base prompt
            base_prompt = BASE_STORY_PROMPT_TEMPLATE.format(word_count=target_words)
            system_prompt = style_prompt + "\n" + base_prompt

            # Language instruction
            language_name = {"ru": "Russian", "en": "English", "kk": "Kazakh"}.get(language, language)

            # Style-specific energy hints
            style_hints = {
                ScriptStyle.VIRAL: "ВЫСОКАЯ ЭНЕРГИЯ! Шокирующие факты, быстрый темп.",
                ScriptStyle.DOCUMENTARY: "ЭПИЧНО И КИНЕМАТОГРАФИЧНО! Авторитетный тон.",
                ScriptStyle.MOTIVATIONAL: "ЭМОЦИОНАЛЬНО И ВДОХНОВЛЯЮЩЕ! Трансформация.",
                ScriptStyle.STORYTELLING: "ФОКУС НА ПЕРСОНАЖЕ! Нарративная арка.",
                ScriptStyle.EDUCATIONAL: "ЯСНО И ПОЗНАВАТЕЛЬНО! Понятные аналогии.",
                ScriptStyle.MYSTERY: "ИНТРИГА И САСПЕНС! Загадка до конца.",
                ScriptStyle.HISTORICAL: "ПОГРУЖЕНИЕ В ЭПОХУ! Живые детали."
            }

            # Build user prompt based on whether we have custom idea
            if custom_idea:
                # Mode-specific instructions
                mode_instructions = {
                    "expand": """РЕЖИМ: РАЗВИТЬ
Возьми идею пользователя как основу и развей её в полноценный сценарий.
- Сохрани ВСЕ ключевые моменты и факты из идеи
- Добавь недостающие элементы структуры
- Усиль эмоциональный посыл
- Адаптируй под нужную длину""",

                    "polish": """РЕЖИМ: УЛУЧШИТЬ
Улучши структуру и подачу, НЕ меняя содержание.
- Сохрани ВСЕ факты и идеи пользователя
- Улучши порядок и переходы между частями
- Добавь только связующие элементы
- Текст должен быть максимально близок к оригиналу""",

                    "strict": """РЕЖИМ: СТРОГО КАК ЕСТЬ ⚠️
КРИТИЧЕСКИ ВАЖНО: Текст пользователя — это ФИНАЛЬНЫЙ сценарий!

РАЗРЕШЕНО:
✓ Исправить явные опечатки
✓ Разбить на сегменты для озвучки
✓ Добавить знаки препинания если нужно

ЗАПРЕЩЕНО (СТРОГО!):
✗ Менять слова или фразы
✗ Добавлять новые предложения
✗ Удалять контент пользователя
✗ "Улучшать" или "развивать" идеи
✗ Добавлять крючки, CTA или призывы
✗ Менять порядок предложений

Твоя задача: ТОЛЬКО форматирование и разбивка на сегменты.
Если текст короткий — НЕ дописывай, верни как есть."""
                }

                user_prompt = f"""ИДЕЯ ПОЛЬЗОВАТЕЛЯ:
\"\"\"
{custom_idea}
\"\"\"

{mode_instructions.get(idea_mode, mode_instructions["expand"])}

ТЕМА: {topic}
ЯЗЫК: {language_name}
СТИЛЬ: {style.value.upper()} — {style_hints.get(style, "")}
ДЛИНА: РОВНО {target_words} слов (±10)

СТРУКТУРА (адаптируй идею пользователя):
1. HOOK (10%) → Захватывающее начало
2. CONTEXT (15%) → Контекст и важность
3. BUILD (40%) → Развитие истории
4. CLIMAX (25%) → Кульминация
5. PAYOFF (10%) → Завершение

Напиши итоговый сценарий СЕЙЧАС (только текст, без меток секций):"""

            else:
                # Standard generation from topic
                user_prompt = f"""ТЕМА: {topic}

ЯЗЫК: {language_name}
СТИЛЬ: {style.value.upper()} — {style_hints.get(style, "")}
ДЛИНА: РОВНО {target_words} слов (±10)

СТРУКТУРА (следуй СТРОГО):
1. HOOK (10%) → Захвати внимание с первой секунды
2. CONTEXT (15%) → Объясни почему это важно
3. BUILD (40%) → Развей историю, добавь детали
4. CLIMAX (25%) → Доставь главный "вау-момент"
5. PAYOFF (10%) → Заверши с импактом

Напиши историю СЕЙЧАС (только текст, без меток секций):"""

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
                "temperature": 0.9,
                "max_tokens": 500  # 150 words ≈ 200-250 tokens
            }

            response = await self.client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload
            )

            if response.status_code != 200:
                logger.error(f"[STORYTELLER] API error: {response.status_code}")
                return self._generate_fallback_story(topic, style, language)

            data = response.json()
            story = data["choices"][0]["message"]["content"].strip()

            # Clean up quotes if wrapped
            if story.startswith('"') and story.endswith('"'):
                story = story[1:-1]

            word_count = len(story.split())
            hook = story.split('.')[0] + '.' if '.' in story else story[:100]

            logger.info(f"[STORYTELLER] Generated {word_count}-word {style.value} story")

            return StoryResult(
                narrative=story,
                style=style,
                word_count=word_count,
                hook=hook,
                success=True
            )

        except Exception as e:
            logger.error(f"[STORYTELLER] Generation failed: {e}")
            return self._generate_fallback_story(topic, style, language, target_words)

    def _generate_fallback_story(
        self,
        topic: str,
        style: ScriptStyle,
        language: str,
        target_words: int = 150
    ) -> StoryResult:
        """Generate a fallback story when API is unavailable."""
        logger.info(f"[STORYTELLER] Using fallback {style.value} story for: {topic} ({target_words} words target)")

        if language == "ru":
            story = self._build_russian_fallback_story(topic, style, target_words)
        else:
            story = self._build_english_fallback_story(topic, style, target_words)

        word_count = len(story.split())
        hook = story.split('.')[0] + '.' if '.' in story else story[:100]

        logger.info(f"[STORYTELLER] Generated fallback: {word_count} words (target: {target_words})")

        return StoryResult(
            narrative=story,
            style=style,
            word_count=word_count,
            hook=hook,
            success=True,
            error="Used fallback story (API unavailable)"
        )

    def _build_russian_fallback_story(self, topic: str, style: ScriptStyle, target_words: int) -> str:
        """Build Russian fallback story of correct length."""
        # Story building blocks by style
        blocks = {
            ScriptStyle.VIRAL: [
                f"Это изменит всё, что вы знали о {topic}.",
                "Учёные скрывали эту информацию годами.",
                "Но теперь правда выходит наружу.",
                "Каждые 60 секунд в мире происходит нечто невероятное.",
                f"И {topic} находится в центре этого.",
                "Статистика шокирует: 94% людей даже не подозревают об этом.",
                "Эксперты бьют тревогу.",
                "СМИ молчат.",
                "Но факты говорят сами за себя.",
                "То, что казалось невозможным, происходит прямо сейчас.",
                "И последствия затронут каждого из нас.",
                "Готовы узнать правду?",
                "Следующие 60 секунд перевернут ваше представление о реальности.",
                "То, что вы узнаете, невозможно будет забыть.",
                "Мир никогда не будет прежним после этого открытия.",
                f"История {topic} только начинается.",
                "И вы станете её частью.",
                "Подписывайтесь, пока этот контент не удалили.",
            ],
            ScriptStyle.DOCUMENTARY: [
                f"Один человек изменил ход истории навсегда.",
                f"Его история связана с {topic}.",
                "Рождённый в суровых условиях, он с детства познал жестокость мира.",
                "Годы скитаний закалили его характер.",
                "Из никого он превратился в легенду.",
                "Его методы были просты: лояльность важнее крови.",
                "Предательство каралось смертью.",
                "За двадцать лет он создал нечто, равного чему мир не видел.",
                "Города, признавшие его власть, процветали.",
                "Сопротивлявшиеся исчезали с карты истории.",
                "Его армия была непобедима.",
                "Тактика и стратегия опережали время на столетия.",
                "Его наследие живёт и сегодня.",
                "Миллионы людей несут его ДНК.",
                "Его кровь течёт в жилах народов.",
                "Империя была больше, чем владения всех великих завоевателей.",
                f"История {topic} — это история человеческого духа.",
                "Подписывайтесь, чтобы узнать больше.",
            ],
            ScriptStyle.MOTIVATIONAL: [
                f"{topic} — это не просто история.",
                "Это зеркало нашей собственной жизни.",
                "Каждый из нас сталкивается с препятствиями.",
                "Каждый переживает моменты, когда хочется сдаться.",
                "Но именно в эти моменты рождаются легенды.",
                "Боль — это учитель.",
                "Неудачи — это ступени.",
                "То, что кажется концом — всегда начало чего-то большего.",
                f"Посмотрите на {topic} другими глазами.",
                "Не как на историю прошлого.",
                "А как на урок для настоящего.",
                "Ваша жизнь — это холст.",
                "Каждый день — новый мазок кисти.",
                "Что вы нарисуете сегодня?",
                "Выбор всегда за вами.",
                "И каждый выбор ведёт к новой главе.",
                "Величие начинается с первого шага.",
                "Начните писать свою историю прямо сейчас.",
            ],
            ScriptStyle.STORYTELLING: [
                "Его звали просто: сын степей.",
                "Никто не знал, что этот мальчик изменит мир.",
                f"{topic} начинается с одного момента.",
                "Отец убит. Мать изгнана.",
                "Девятилетний ребёнок остался один против всего мира.",
                "Он бежал. Прятался. Голодал.",
                "Но не сдавался.",
                "Каждое утро он просыпался с одной мыслью: выжить.",
                "Годы превратили его в волка.",
                "Одинокого. Опасного. Непобедимого.",
                "Он находил союзников среди врагов.",
                "Превращал предателей в верных последователей.",
                "Строил армию из изгоев и бродяг.",
                "И когда пришло время, мир содрогнулся.",
                "Мальчик, который должен был умереть, стал владыкой.",
                "Половина известного мира принадлежала ему.",
                "Его имя помнят веками.",
                f"История {topic} — доказательство того, что начало не определяет конец.",
            ],
        }

        # Get blocks for style (default to DOCUMENTARY)
        style_blocks = blocks.get(style, blocks[ScriptStyle.DOCUMENTARY])

        # Build story by adding blocks until we reach target
        story_parts = []
        current_words = 0

        for block in style_blocks:
            block_words = len(block.split())
            if current_words + block_words <= target_words + 15:  # Allow small overflow
                story_parts.append(block)
                current_words += block_words
            if current_words >= target_words - 10:  # Close enough to target
                break

        # If we need more words, repeat/extend
        while current_words < target_words - 15:
            extra = f"Это лишь часть истории о {topic}. Продолжение поражает ещё больше."
            story_parts.append(extra)
            current_words += len(extra.split())

        return " ".join(story_parts)

    def _build_english_fallback_story(self, topic: str, style: ScriptStyle, target_words: int) -> str:
        """Build English fallback story of correct length."""
        blocks = {
            ScriptStyle.VIRAL: [
                f"This will change everything you knew about {topic}.",
                "Scientists have hidden this for years.",
                "But now the truth emerges.",
                "Every 60 seconds something incredible happens.",
                f"And {topic} is at the center of it.",
                "The statistics are shocking: 94% of people have no idea.",
                "Experts are sounding the alarm.",
                "Media stays silent.",
                "But facts speak for themselves.",
                "What seemed impossible is happening right now.",
                "The consequences will affect everyone.",
                "Ready to know the truth?",
                "The next 60 seconds will flip your understanding.",
                "What you learn cannot be forgotten.",
                "The world will never be the same after this.",
                f"The story of {topic} is just beginning.",
                "And you will become part of it.",
                "Subscribe before this content gets deleted.",
            ],
            ScriptStyle.DOCUMENTARY: [
                "One man changed the course of history forever.",
                f"His story connects to {topic}.",
                "Born in harsh conditions, he knew cruelty from childhood.",
                "Years of wandering forged his character.",
                "From nothing, he became a legend.",
                "His methods were simple: loyalty above blood.",
                "Betrayal meant death.",
                "In twenty years he created something unprecedented.",
                "Cities that acknowledged him flourished.",
                "Those that resisted vanished from history.",
                "His army was invincible.",
                "Tactics and strategy centuries ahead of time.",
                "His legacy lives today.",
                "Millions carry his DNA.",
                "His blood flows through nations.",
                "The empire was larger than all great conquerors combined.",
                f"The story of {topic} is the story of human spirit.",
                "Subscribe to learn more.",
            ],
            ScriptStyle.MOTIVATIONAL: [
                f"{topic} is not just a story.",
                "It's a mirror of our own lives.",
                "Each of us faces obstacles.",
                "Each experiences moments when giving up seems easier.",
                "But these moments birth legends.",
                "Pain is a teacher.",
                "Failures are stepping stones.",
                "What seems like an end is always a beginning.",
                f"Look at {topic} with new eyes.",
                "Not as history.",
                "But as a lesson for today.",
                "Your life is a canvas.",
                "Every day is a new brushstroke.",
                "What will you paint today?",
                "The choice is always yours.",
                "Every choice leads to a new chapter.",
                "Greatness begins with the first step.",
                "Start writing your story right now.",
            ],
            ScriptStyle.STORYTELLING: [
                "They called him simply: son of the steppes.",
                "Nobody knew this boy would change the world.",
                f"{topic} begins with one moment.",
                "Father killed. Mother exiled.",
                "A nine-year-old against the entire world.",
                "He ran. Hid. Starved.",
                "But never surrendered.",
                "Every morning he woke with one thought: survive.",
                "Years turned him into a wolf.",
                "Lonely. Dangerous. Undefeatable.",
                "He found allies among enemies.",
                "Turned traitors into loyal followers.",
                "Built an army from outcasts and wanderers.",
                "When the time came, the world trembled.",
                "The boy who should have died became master.",
                "Half the known world belonged to him.",
                "His name echoes through centuries.",
                f"The story of {topic} proves beginnings don't determine endings.",
            ],
        }

        style_blocks = blocks.get(style, blocks[ScriptStyle.DOCUMENTARY])

        story_parts = []
        current_words = 0

        for block in style_blocks:
            block_words = len(block.split())
            if current_words + block_words <= target_words + 15:
                story_parts.append(block)
                current_words += block_words
            if current_words >= target_words - 10:
                break

        while current_words < target_words - 15:
            extra = f"This is just part of the {topic} story. What comes next is even more incredible."
            story_parts.append(extra)
            current_words += len(extra.split())

        return " ".join(story_parts)

    def _get_russian_fallback_stories(self, topic: str, style: ScriptStyle) -> dict:
        """Get Russian fallback stories by style (legacy method)."""
        return {
            ScriptStyle.VIRAL: self._build_russian_fallback_story(topic, ScriptStyle.VIRAL, 150),
            ScriptStyle.DOCUMENTARY: self._build_russian_fallback_story(topic, ScriptStyle.DOCUMENTARY, 150),
            ScriptStyle.MOTIVATIONAL: self._build_russian_fallback_story(topic, ScriptStyle.MOTIVATIONAL, 150),
            ScriptStyle.STORYTELLING: self._build_russian_fallback_story(topic, ScriptStyle.STORYTELLING, 150),
        }

    def _get_english_fallback_stories(self, topic: str, style: ScriptStyle) -> dict:
        """Get English fallback stories by style (legacy method)."""
        return {
            ScriptStyle.VIRAL: self._build_english_fallback_story(topic, ScriptStyle.VIRAL, 150),
            ScriptStyle.DOCUMENTARY: self._build_english_fallback_story(topic, ScriptStyle.DOCUMENTARY, 150),
            ScriptStyle.MOTIVATIONAL: self._build_english_fallback_story(topic, ScriptStyle.MOTIVATIONAL, 150),
            ScriptStyle.STORYTELLING: self._build_english_fallback_story(topic, ScriptStyle.STORYTELLING, 150),
        }

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
