# Tessia Memory System — Smart Long-Term Memory

> **Goal:** Replace the current 7-message rolling memory with a structured long-term memory system that stores durable facts per user, shares useful context across chats without mixing users, and automatically summarizes conversations.

**Architecture:**

```
User Message
  → Short-Term Memory (last 20 messages, per chat_id:user_id)
  → AI response
  → Fact Extractor (background) → extracts durable facts
  → Long-Term Memory (facts, preferences, relationships, names)
  → Cross-Chat Context Builder (merges relevant facts from all chats with this user)
```

**Tech Stack:** Python 3.11, JSON file storage (same as current), Threading lock for writes.

---

## Phase 1: Fact Model (`tessia_bot/memory_facts.py`)

### Task 1.1: Define the fact data model

**Objective:** Create a structured fact type with metadata.

**Files:**
- Create: `tessia_bot/memory_facts.py`

```python
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any

FACT_TYPES = {
    "name",           # user's name / nickname
    "preference",     # likes, dislikes, favorites
    "fact",           # statement about the user
    "relationship",   # how they relate to the user (friend, brother, etc.)
    "language",       # preferred language
    "topic",          # topics they like discussing
    "behavior",       # how they like to be treated
    "catchphrase",    # their common phrases
}

@dataclass
class Fact:
    fact_id: str
    user_id: str
    fact_type: str          # one of FACT_TYPES
    content: str            # the fact text
    confidence: float = 1.0  # 0.0 to 1.0 (how sure we are)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    source_chat_id: str = ""
    expiry: float = 0.0     # 0 = never expires

    def is_valid(self) -> bool:
        return self.fact_type in FACT_TYPES and bool(self.content.strip()) and self.confidence > 0.3
```

### Task 1.2: Fact storage and retrieval

**Objective:** Save, load, search, and merge facts.

**Same file:** `tessia_bot/memory_facts.py`

```python
import json
import os
import threading
from typing import Optional

class FactMemory:
    def __init__(self, file_path: str = "memory_facts.json"):
        self.file_path = file_path
        self.lock = threading.Lock()
        self.facts: dict[str, list[dict]] = {}  # user_id -> [fact_dicts]
        self._load()

    def _load(self):
        if os.path.exists(self.file_path):
            with open(self.file_path, "r", encoding="utf-8") as f:
                self.facts = json.load(f)

    def _save(self):
        with self.lock:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.facts, f, ensure_ascii=False, indent=2)

    def add_fact(self, user_id: str, fact_type: str, content: str,
                 confidence: float = 1.0, source_chat_id: str = "") -> bool:
        user_id = str(user_id)
        if not content.strip() or fact_type not in FACT_TYPES:
            return False
        now = time.time()
        fact = {
            "fact_id": f"f_{user_id}_{int(now)}",
            "user_id": user_id,
            "fact_type": fact_type,
            "content": content.strip()[:500],
            "confidence": min(1.0, max(0.0, confidence)),
            "created_at": now,
            "updated_at": now,
            "source_chat_id": source_chat_id,
            "expiry": 0,
        }
        if user_id not in self.facts:
            self.facts[user_id] = []
        # Deduplicate: if same fact_type + content exists, update confidence
        for existing in self.facts[user_id]:
            if existing["fact_type"] == fact_type and existing["content"] == fact["content"]:
                existing["confidence"] = min(1.0, existing["confidence"] + 0.15)
                existing["updated_at"] = now
                self._save()
                return True
        self.facts[user_id].append(fact)
        # Trim per user to max 100 facts
        self.facts[user_id] = self.facts[user_id][-100:]
        self._save()
        return True

    def get_facts(self, user_id: str, min_confidence: float = 0.4,
                  fact_types: set[str] | None = None) -> list[dict]:
        user_id = str(user_id)
        results = []
        for fact in self.facts.get(user_id, []):
            if fact["confidence"] < min_confidence:
                continue
            if fact_types and fact["fact_type"] not in fact_types:
                continue
            results.append(fact)
        return sorted(results, key=lambda f: -f["confidence"])

    def build_context(self, user_id: str, max_facts: int = 15) -> str:
        """Build a natural-language context string for the AI system prompt."""
        facts = self.get_facts(user_id)
        if not facts:
            return ""
        parts = ["## Memory about you"]
        for fact in facts[:max_facts]:
            icon = {"name": "👤", "preference": "❤️", "fact": "📌",
                    "relationship": "🤝", "language": "🌐", "topic": "📚",
                    "behavior": "⚡", "catchphrase": "💬"}.get(fact["fact_type"], "•")
            parts.append(f"{icon} {fact['content']}")
        return "\n".join(parts)

    def merge_facts(self, user_id: str, new_facts: list[dict]):
        """Bulk add facts from fact extractor."""
        for fact in new_facts:
            self.add_fact(
                user_id=user_id,
                fact_type=fact.get("fact_type", "fact"),
                content=fact.get("content", ""),
                confidence=fact.get("confidence", 0.6),
                source_chat_id=fact.get("source_chat_id", ""),
            )

# Global instance
fact_memory = FactMemory()
```

---

## Phase 2: Fact Extractor (`tessia_bot/memory_extractor.py`)

### Task 2.1: AI-powered fact extraction

**Objective:** After every conversation turn, ask a fast LLM to extract facts from the exchange.

**Files:**
- Create: `tessia_bot/memory_extractor.py`

```python
"""
Fact Extractor — uses AI to extract durable facts from conversations.
Runs in the background after each user interaction.
"""

import json
from .config import client, MODEL_NAME, FACT_MEMORY_FILE
from .memory_facts import FACT_TYPES, FactMemory

EXTRACTOR_SYSTEM_PROMPT = """\
Extract durable facts about the USER from this conversation turn.
Only extract facts that are:
- Explicitly stated or very strongly implied
- Likely to be true for more than one conversation
- Not temporary/transient states

Return JSON array of objects with:
- "fact_type": one of "name", "preference", "fact", "relationship", "language", "topic", "behavior", "catchphrase"
- "content": short fact text in Persian (max 100 chars)
- "confidence": 0.0 to 1.0

Examples:
Input: User: "اسم من علیه" → [{"fact_type": "name", "content": "اسمش علی است", "confidence": 0.9}]
Input: User: "من فیلم ترسناک دوست دارم" → [{"fact_type": "preference", "content": "فیلم ترسناک دوست دارد", "confidence": 0.8}]
Input: User: "سلام خوبی" (casual greeting) → []

Return ONLY valid JSON array, nothing else.
"""

fact_memory_extractor = FactMemory()


async def extract_and_store(user_id: str, user_text: str, ai_text: str,
                            chat_id: str, source: str = "tessia_bot"):
    """Extract facts from a conversation turn and store them."""
    if not user_text.strip() or len(user_text) < 4:
        return

    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": EXTRACTOR_SYSTEM_PROMPT},
                {"role": "user", "content": f"User: {user_text[:1000]}\nAI: {ai_text[:500]}"},
            ],
            temperature=0.1,
            max_tokens=500,
            stream=False,
        )
        content = (response.choices[0].message.content or "").strip()
        # Strip markdown code fences if present
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        facts = json.loads(content)
        if isinstance(facts, list):
            for fact in facts:
                fact["source_chat_id"] = chat_id
            fact_memory_extractor.merge_facts(user_id, facts)
    except Exception as e:
        # Silent fail — fact extraction is best-effort
        pass
```

---

## Phase 3: Short-Term Memory Upgrade (`tessia_bot/state.py`)

### Task 3.1: Increase memory from 7 to 20 messages

**Files:**
- Modify: `tessia_bot/state.py`

Change `MAX_MEMORY_MESSAGES = 7` to `MAX_MEMORY_MESSAGES = 20` in `config.py`.

### Task 3.2: Add cross-chat memory lookup

In `bot.py`, when building the system context for a user, fetch facts from ALL their chats:

```python
from .memory_facts import fact_memory

def build_memory_context(user_id: str) -> str:
    return fact_memory.build_context(user_id)
```

Append this to `build_common_system_context()` in `bot.py`.

---

## Phase 4: Integration

### Task 4.1: Wire extractor into bot.py

In `handle_text()` in `bot.py`, after getting the AI response, call:

```python
from .memory_extractor import extract_and_store

# After full_response is generated:
asyncio.create_task(extract_and_store(
    user_id=user_id,
    user_text=text,
    ai_text=full_response,
    chat_id=str(message.chat.id),
    source="tessia_bot",
))
```

### Task 4.2: Wire extractor into father_gateway.py

Same pattern in `father_gateway.py` after `event.reply()`.

### Task 4.3: Update build_common_system_context

In `bot.py:build_common_system_context()`, add:

```python
memory_context = fact_memory.build_context(user_id)
if memory_context:
    system_content += "\n\n" + memory_context
```

---

## Phase 5: Cleanup & Commit

### Task 5.1: Add `FACT_MEMORY_FILE` config

```python
FACT_MEMORY_FILE = "memory_facts.json"
```

### Task 5.2: Test

```bash
cd /root/TessiaAiBot && python3 -c "
from tessia_bot.memory_facts import fact_memory
fact_memory.add_fact('123', 'name', 'اسمش علی است')
print(fact_memory.build_context('123'))
print('✅ Memory system OK')
"
```

Expected:
```
## Memory about you
👤 اسمش علی است
```

---

## Summary of Files Changed

| File | Action | ~Lines |
|------|--------|--------|
| `tessia_bot/memory_facts.py` | **Create** | 140 |
| `tessia_bot/memory_extractor.py` | **Create** | 80 |
| `tessia_bot/config.py` | **Modify** (+FACT_MEMORY_FILE, +MAX_MEMORY_MESSAGES=20) | 2 |
| `tessia_bot/state.py` | **Modify** (import MAX_MEMORY_MESSAGES already) | 0 |
| `tessia_bot/bot.py` | **Modify** (import + wire extractor + build_memory_context) | +15 |
| `father_gateway.py` | **Modify** (wire extractor) | +5 |

## Key Design Decisions

1. **Per-user, not per-chat:** Facts are keyed by `user_id`, visible across all chats (group, DM, etc.)
2. **Confidence scoring:** Repeated facts get higher confidence; low-confidence facts are filtered out
3. **Async extraction:** Fact extraction is fire-and-forget via `asyncio.create_task` — never blocks the response
4. **JSON file storage:** Same pattern as existing `tessia_data.json` — simple and debuggable
5. **Max 100 facts per user:** Prevents bloat
