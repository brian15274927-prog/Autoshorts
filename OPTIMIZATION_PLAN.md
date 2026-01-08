# 🚀 TOKEN & SPEED OPTIMIZATION PLAN

## 📊 Current Token Usage Analysis

### Per Video Generation (60s):
```
1. Storyteller (Agent 1):
   - System prompt: ~800 tokens
   - User prompt: ~200 tokens
   - Response: ~1000 tokens
   TOTAL: ~2000 tokens

2. Context Analysis:
   - System prompt: ~600 tokens
   - User prompt (narrative): ~1000 tokens
   - Response: ~400 tokens
   TOTAL: ~2000 tokens

3. Visual Director (Agent 2):
   - System prompt: ~1200 tokens (HUGE!)
   - User prompt: ~1500 tokens
   - Response (12 segments): ~2000 tokens
   TOTAL: ~4700 tokens

4. Deduplication Check:
   - Per segment pair: ~500 tokens
   - 12 segments = ~3000 tokens
   TOTAL: ~3000 tokens

5. Multi-Subject Fix:
   - Per segment: ~300 tokens
   - 12 segments = ~1800 tokens
   TOTAL: ~1800 tokens

GRAND TOTAL: ~13,500 tokens per video!
```

### Cost:
- GPT-4o-mini: $0.15 per 1M input tokens, $0.60 per 1M output tokens
- **Current cost: ~$0.005 per video** (just LLM, not images/TTS)

---

## ⚡ OPTIMIZATION STRATEGIES

### 1. **Compress System Prompts** (-60% tokens)
```
BEFORE: 1200 tokens
AFTER:  500 tokens

Changes:
- Remove verbose examples
- Use bullet points instead of paragraphs
- Remove redundant instructions
- Shorten art style descriptions
```

**Savings: ~700 tokens per video**

---

### 2. **Smart Prompt Caching** (reuse prompts)
```javascript
// Cache identical prompts
const promptCache = new Map();

function getCachedPrompt(key) {
  if (promptCache.has(key)) {
    return promptCache.get(key);  // Reuse!
  }
  // Generate new...
}
```

**Savings: ~30% on repeated prompts**

---

### 3. **Batch API Calls** (parallel processing)
```
BEFORE (Sequential):
1. Context Analysis → wait
2. Visual Segmentation → wait
3. Deduplication → wait
Time: 15-20 seconds

AFTER (Parallel where possible):
1. Context Analysis + Visual Segmentation (parallel)
2. Deduplication (only if needed)
Time: 8-10 seconds
```

**Speed improvement: 50% faster**

---

### 4. **Skip Unnecessary Steps**
```
Deduplication:
- BEFORE: Check ALL 12 segments (78 comparisons!)
- AFTER: Only check if text similarity > 80%
         (most segments are unique)

Multi-Subject Fix:
- BEFORE: Check ALL segments
- AFTER: Only check if segment mentions 2+ names

Context Analysis:
- BEFORE: Full narrative analysis
- AFTER: Extract key facts only (era, region, people)
```

**Savings: ~2000 tokens per video**

---

### 5. **Optimize Visual Bible** (optional)
```
Visual Bible is great for consistency but EXPENSIVE:
- Adds ~2000 tokens per generation

Solution:
- Make it OPTIONAL (default: OFF)
- Only use for complex narratives (90s+ videos)
- For 30-60s videos, use lightweight context
```

**Savings: ~2000 tokens for short videos**

---

### 6. **Parallel Image Generation**
```python
# BEFORE (Sequential):
for segment in segments:
    image = await generate_image(segment.visual_prompt)
    # Wait for each...

# AFTER (Parallel):
tasks = [generate_image(seg.visual_prompt) for seg in segments]
images = await asyncio.gather(*tasks)
```

**Speed improvement: Generate 12 images in parallel!**
**Time: From 60s → 15s** (if API allows)

---

### 7. **TTS Optimization**
```python
# BEFORE:
for segment in segments:
    audio = await tts.generate(segment.text)

# AFTER (Parallel):
tasks = [tts.generate(seg.text) for seg in segments]
audios = await asyncio.gather(*tasks)
```

**Speed improvement: 3x faster TTS**

---

### 8. **Reduce Context Size**
```
Context Analysis System Prompt:
BEFORE: 600 tokens (detailed instructions)
AFTER:  200 tokens (concise JSON schema)

Example:
BEFORE:
"Analyze the narrative carefully. Extract the historical era,
geographical region, architectural styles, people descriptions..."

AFTER:
"Extract: {era, region, people, avoid_elements}"
```

**Savings: 400 tokens**

---

## 📈 EXPECTED RESULTS

### Token Reduction:
```
BEFORE: 13,500 tokens per video
AFTER:   6,500 tokens per video

SAVINGS: 52% fewer tokens! 💰
```

### Speed Improvement:
```
BEFORE: 25-30 seconds total
AFTER:  12-15 seconds total

SPEED UP: 2x faster! ⚡
```

### Cost Savings:
```
BEFORE: $0.005 per video
AFTER:  $0.002 per video

SAVINGS: 60% cheaper!
```

---

## 🔧 IMPLEMENTATION PRIORITIES

### Phase 1 (Immediate - High Impact):
1. ✅ Compress system prompts (Visual Director)
2. ✅ Make Visual Bible optional
3. ✅ Skip deduplication for short videos (<60s)
4. ✅ Parallel image generation

**Impact: 40% faster, 30% cheaper**

### Phase 2 (Medium Impact):
5. ✅ Optimize context analysis
6. ✅ Parallel TTS generation
7. ✅ Smart prompt caching

**Impact: 60% faster, 50% cheaper**

### Phase 3 (Polish):
8. ✅ Batch API calls
9. ✅ Response streaming
10. ✅ Precompute common prompts

**Impact: 70% faster, 60% cheaper**

---

## 🎯 OPTIMIZED ARCHITECTURE

```
┌─────────────────────────────────────────────────┐
│ 1. Storyteller                                  │
│    - Compressed prompt (400 tokens)             │
│    - Cache narrative patterns                   │
│    Time: 3-4s                                   │
└──────────────┬──────────────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────────────┐
│ 2. PARALLEL: Context + Visual Director         │
│    ┌──────────────┐    ┌──────────────────┐    │
│    │ Context (2s) │    │ Segments (4s)    │    │
│    │ 200 tokens   │    │ 800 tokens       │    │
│    └──────────────┘    └──────────────────┘    │
│    Time: 4s (parallel!)                         │
└──────────────┬──────────────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────────────┐
│ 3. OPTIONAL: Deduplication (only if needed)    │
│    - Skip for <60s videos                       │
│    - Quick similarity check                     │
│    Time: 0-2s                                   │
└──────────────┬──────────────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────────────┐
│ 4. PARALLEL: Images + TTS + Music              │
│    ┌─────────┐  ┌─────────┐  ┌─────────┐       │
│    │ Images  │  │ TTS (12)│  │ Music   │       │
│    │ (12)    │  │ async   │  │ select  │       │
│    │ async   │  │ 3s      │  │ 1s      │       │
│    │ 5s      │  └─────────┘  └─────────┘       │
│    └─────────┘                                  │
│    Time: 5s (parallel!)                         │
└──────────────┬──────────────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────────────┐
│ 5. Video Assembly                               │
│    - Ken Burns effects                          │
│    - Subtitle overlay                           │
│    Time: 3-5s                                   │
└─────────────────────────────────────────────────┘

TOTAL TIME: ~15 seconds (down from 30!)
```

---

## 💡 SMART DEFAULTS

```python
# Auto-optimize based on video duration
def get_optimization_level(duration: int) -> str:
    if duration <= 30:
        return "ultra_fast"  # Skip Visual Bible, minimal checks
    elif duration <= 60:
        return "balanced"    # Optional Visual Bible, smart caching
    else:
        return "quality"     # Full analysis, all features

ULTRA_FAST (30s):
- No Visual Bible
- No deduplication
- Lightweight context (100 tokens)
- Time: 10s

BALANCED (60s):
- Optional Visual Bible
- Smart deduplication (only if similar)
- Standard context (200 tokens)
- Time: 15s

QUALITY (90s+):
- Full Visual Bible
- Full deduplication
- Deep context (400 tokens)
- Time: 25s
```

---

## 🚀 START IMPLEMENTATION?

**Priorities:**
1. ✅ Compress Visual Director prompt (biggest win!)
2. ✅ Make Visual Bible optional
3. ✅ Parallel image + TTS generation
4. ✅ Smart deduplication skip

**Expected Result:**
- 2x faster generation
- 50% fewer tokens
- Better user experience

**ГОТОВ НАЧАТЬ! 🔥**
