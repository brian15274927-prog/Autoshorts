# 🎬 MVP: Script Preview & Edit Before Generation

## ✅ РЕАЛИЗОВАНО

Новый 2-шаговый flow для полного контроля над сценарием!

---

## 🎯 Новый Flow

### ДО (старый способ):
```
User вводит тему → Генерация видео → Готово
❌ Нет контроля
❌ Нельзя исправить
❌ Деньги потрачены на плохой контент
```

### ПОСЛЕ (MVP):
```
User вводит тему
    ↓
Агент генерирует сценарий
    ↓
📝 PREVIEW: User видит и редактирует сегменты
    ↓
User нажимает "Создать видео"
    ↓
Генерация с отредактированным сценарием
    ↓
✅ Готово!
```

---

## 🔧 API Changes

### 1. Enhanced: `/api/faceless/preview-script`

**Что изменилось:**
- ✅ Теперь поддерживает `custom_idea` (user может ввести свой текст)
- ✅ Поддерживает `idea_mode` (expand/polish/strict)

**Request:**
```json
POST /api/faceless/preview-script
{
  "topic": "История искусственного интеллекта",
  "style": "documentary",
  "language": "ru",
  "duration": 30,
  "art_style": "photorealism",
  "custom_idea": "Мой черновик текста...",  // NEW! Optional
  "idea_mode": "expand"  // NEW! Optional
}
```

**Response:**
```json
{
  "script": {
    "title": "История AI",
    "narrative": "Полный текст...",
    "segments": [
      {
        "text": "В 1950 году началась революция...",
        "duration": 5.0,
        "visual_prompt": "Wide shot, 1950s laboratory...",
        "emotion": "mysterious",
        "segment_type": "hook"
      },
      ...
    ],
    "total_duration": 30.0,
    "art_style": "photorealism"
  },
  "estimated_cost": {
    "images_cost": "$0.24",
    "total_cost": "$0.25",
    "note": "Preview FREE. Costs apply on /generate"
  }
}
```

---

### 2. NEW: `/api/faceless/generate-from-script`

**Что делает:**
- Принимает отредактированные user сегменты
- Использует `idea_mode="strict"` чтобы сохранить текст как есть
- Запускает генерацию видео

**Request:**
```json
POST /api/faceless/generate-from-script
{
  "topic": "История AI",
  "style": "documentary",
  "language": "ru",
  "voice": "ru-RU-DmitryNeural",
  "duration": 30,
  "format": "9:16",
  "subtitle_style": "hormozi",
  "art_style": "photorealism",
  "background_music": true,
  "music_volume": 0.2,
  "image_provider": "dalle",
  
  "edited_segments": [
    {
      "index": 0,
      "text": "Мой отредактированный текст сегмента 1..."
    },
    {
      "index": 1,
      "text": "Мой отредактированный текст сегмента 2..."
    },
    ...
  ]
}
```

**Response:**
```json
{
  "job_id": "abc-123",
  "status": "pending",
  "message": "🎬 Видео с вашим сценарием запущено!"
}
```

---

## 📝 Frontend Implementation

### Шаг 1: Preview Script

```javascript
// 1. User submits topic
const previewScript = async () => {
  const response = await fetch('/api/faceless/preview-script', {
    method: 'POST',
    body: JSON.stringify({
      topic: document.getElementById('topic').value,
      style: 'documentary',
      duration: 30,
      art_style: 'photorealism'
    })
  });
  
  const data = await response.json();
  
  // 2. Show editable segments
  displaySegments(data.script.segments);
};

const displaySegments = (segments) => {
  const container = document.getElementById('segments-container');
  container.innerHTML = '';
  
  segments.forEach((seg, i) => {
    const segmentDiv = document.createElement('div');
    segmentDiv.className = 'segment';
    segmentDiv.innerHTML = `
      <h4>Сегмент ${i + 1} (${seg.segment_type})</h4>
      <textarea 
        id="segment-${i}" 
        rows="3"
      >${seg.text}</textarea>
      <p class="visual-hint">🎨 Visual: ${seg.visual_prompt.substring(0, 60)}...</p>
    `;
    container.appendChild(segmentDiv);
  });
  
  // Show generate button
  document.getElementById('generate-btn').style.display = 'block';
};
```

### Шаг 2: Generate from Edited Script

```javascript
const generateVideo = async () => {
  // Collect edited segments
  const editedSegments = [];
  const textareas = document.querySelectorAll('[id^="segment-"]');
  
  textareas.forEach((textarea, i) => {
    editedSegments.push({
      index: i,
      text: textarea.value
    });
  });
  
  // Send to generation
  const response = await fetch('/api/faceless/generate-from-script', {
    method: 'POST',
    body: JSON.stringify({
      topic: originalTopic,
      style: 'documentary',
      language: 'ru',
      duration: 30,
      // ... other params ...
      edited_segments: editedSegments
    })
  });
  
  const data = await response.json();
  
  // Start polling for status
  pollJobStatus(data.job_id);
};
```

---

## 🎨 UI Example

```html
<!-- Step 1: Input -->
<div id="input-step">
  <h2>Создать видео</h2>
  <textarea id="topic" placeholder="Введите тему..."></textarea>
  <button onclick="previewScript()">Подготовить сценарий</button>
</div>

<!-- Step 2: Preview & Edit -->
<div id="preview-step" style="display: none;">
  <h2>Отредактируйте сценарий</h2>
  
  <div id="segments-container">
    <!-- Segments will be inserted here -->
  </div>
  
  <div class="actions">
    <button onclick="backToInput()">← Назад</button>
    <button onclick="generateVideo()" id="generate-btn">
      Создать видео →
    </button>
  </div>
</div>

<!-- Step 3: Generation Progress -->
<div id="progress-step" style="display: none;">
  <h2>Генерация видео...</h2>
  <div class="progress-bar">
    <div id="progress" style="width: 0%"></div>
  </div>
  <p id="progress-text">Preparing...</p>
</div>
```

### CSS для красивого вида:

```css
.segment {
  border: 1px solid #ddd;
  border-radius: 8px;
  padding: 15px;
  margin-bottom: 15px;
  background: #f9f9f9;
}

.segment h4 {
  margin: 0 0 10px 0;
  color: #333;
}

.segment textarea {
  width: 100%;
  border: 1px solid #ccc;
  border-radius: 4px;
  padding: 10px;
  font-size: 14px;
  font-family: inherit;
  resize: vertical;
  min-height: 60px;
}

.segment textarea:focus {
  outline: none;
  border-color: #4CAF50;
  box-shadow: 0 0 0 2px rgba(76, 175, 80, 0.1);
}

.visual-hint {
  margin: 8px 0 0 0;
  font-size: 12px;
  color: #666;
  font-style: italic;
}

.actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  margin-top: 20px;
}

.actions button {
  padding: 12px 24px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
}

.actions button:first-child {
  background: #f0f0f0;
  color: #333;
}

.actions button:last-child {
  background: #4CAF50;
  color: white;
}

.actions button:hover {
  opacity: 0.9;
}
```

---

## 🔄 Complete Flow Diagram

```
┌─────────────────────────────────────────────────┐
│ 1. USER INPUT                                   │
│                                                 │
│ Topic: "История AI"                             │
│ Style: Documentary                              │
│ Duration: 30s                                   │
│                                                 │
│ [Подготовить сценарий] ──────────────┐          │
└──────────────────────────────────────┘          │
                                        │          
                                        ↓          
┌─────────────────────────────────────────────────┐
│ 2. API: /preview-script                         │
│                                                 │
│ • Storyteller generates narrative               │
│ • Visual Director creates segments              │
│ • Returns editable script                       │
│                                                 │
└──────────────┬──────────────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────────────┐
│ 3. USER PREVIEW & EDIT                          │
│                                                 │
│ ┌─ Segment 1 (Hook) ────────────────────────┐  │
│ │ [Editable textarea]                       │  │
│ │ 🎨 Visual: Wide shot, laboratory...       │  │
│ └───────────────────────────────────────────┘  │
│                                                 │
│ ┌─ Segment 2 (Content) ─────────────────────┐  │
│ │ [Editable textarea]                       │  │
│ │ 🎨 Visual: Close-up, computer...          │  │
│ └───────────────────────────────────────────┘  │
│                                                 │
│ [← Назад] [Создать видео →] ────────────┐      │
└──────────────────────────────────────────┘      │
                                           │      
                                           ↓      
┌─────────────────────────────────────────────────┐
│ 4. API: /generate-from-script                   │
│                                                 │
│ • Receives edited_segments[]                    │
│ • Uses idea_mode="strict"                       │
│ • Starts video generation                       │
│ • Returns job_id                                │
│                                                 │
└──────────────┬──────────────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────────────┐
│ 5. VIDEO GENERATION                             │
│                                                 │
│ • TTS with edited text                          │
│ • Images from original visual_prompts           │
│ • Ken Burns animation                           │
│ • Final assembly                                │
│                                                 │
│ → /api/faceless/status/{job_id}                 │
│                                                 │
└─────────────────────────────────────────────────┘
```

---

## ✅ Benefits

### For Users:
1. ✅ **Full Control** - See script BEFORE spending money
2. ✅ **Fix Errors** - Correct AI mistakes immediately
3. ✅ **Add Details** - Include your own facts/info
4. ✅ **Save Money** - Don't generate bad content

### For System:
1. ✅ **Better Quality** - User-reviewed content
2. ✅ **Fewer Regenerations** - Less wasted API calls
3. ✅ **User Satisfaction** - Full transparency
4. ✅ **Flexibility** - Supports custom text input

---

## 🚀 Next Steps (Future)

### Phase 2 enhancements:
1. Show visual prompt previews (images)
2. Allow regenerating individual segments
3. AI suggestions for improvements
4. Save drafts functionality
5. Voice preview for each segment

### Phase 3 (Advanced):
6. Drag & drop to reorder segments
7. Split/merge segments
8. Bulk edit actions
9. Template library
10. A/B testing different scripts

---

## 📝 Usage Examples

### Example 1: Topic-based

```javascript
// User enters topic
POST /api/faceless/preview-script
{
  "topic": "10 фактов о космосе",
  "style": "viral",
  "duration": 30
}

// AI generates 6 segments
// User edits segment 3: adds more details
// User submits

POST /api/faceless/generate-from-script
{
  "topic": "10 фактов о космосе",
  "edited_segments": [
    {"index": 0, "text": "AI generated text"},
    {"index": 1, "text": "AI generated text"},
    {"index": 2, "text": "USER EDITED: добавил свои факты!"},
    ...
  ]
}
```

### Example 2: Custom Text

```javascript
// User pastes own draft
POST /api/faceless/preview-script
{
  "topic": "My topic",
  "custom_idea": "Мой черновик:\n\nПервый абзац...\n\nВторой абзац...",
  "idea_mode": "expand",  // AI will structure it
  "duration": 30
}

// AI structures into 6 segments
// User reviews and edits
// Generates video
```

---

## ✨ MVP Complete!

**ГОТОВО:**
- ✅ Backend API endpoints
- ✅ Two-step flow
- ✅ Custom idea support
- ✅ Strict mode for user edits

**TODO (Frontend):**
- 🔲 Update faceless.html UI
- 🔲 Add segment editing interface
- 🔲 Connect to new endpoints

**НАЧИНАЕМ С FRONTEND? 🚀**
