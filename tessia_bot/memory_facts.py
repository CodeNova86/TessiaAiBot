"""
Tessia Smart Memory — Long-Term Per-User Fact Memory

Stores structured facts about each user (preferences, name, behavior, topics, etc.)
Facts are keyed by user_id, shared across all chats. No user confusion.

Usage:
    from tessia_bot.memory_facts import fact_memory
    fact_memory.add_fact("123", "name", "اسمش علی است")
    context = fact_memory.build_context("123")
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

FACT_TYPES = {
    "name",           # user's name / nickname
    "preference",     # likes, dislikes, favorites
    "fact",           # statement about the user
    "relationship",   # how they relate (friend, brother, etc.)
    "language",       # preferred language
    "topic",          # topics they like discussing
    "behavior",       # how they like to be treated
    "catchphrase",    # their common phrases
    "important",      # important things to remember
}

FACT_ICONS = {
    "name": "👤",
    "preference": "❤️",
    "fact": "📌",
    "relationship": "🤝",
    "language": "🌐",
    "topic": "📚",
    "behavior": "⚡",
    "catchphrase": "💬",
    "important": "⭐",
}


class FactMemory:
    """Per-user fact storage with JSON persistence."""

    def __init__(self, file_path: str = "memory_facts.json"):
        self.file_path = file_path
        self.lock = threading.Lock()
        self._facts: dict[str, list[dict]] = {}
        self._load()

    def _load(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    self._facts = json.load(f)
            except Exception:
                self._facts = {}
        if not isinstance(self._facts, dict):
            self._facts = {}

    def _save(self):
        with self.lock:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self._facts, f, ensure_ascii=False, indent=2)

    def add_fact(
        self,
        user_id: str,
        fact_type: str,
        content: str,
        confidence: float = 1.0,
        source_chat_id: str = "",
    ) -> bool:
        """Add a fact about a user. Deduplicates and boosts confidence on repeats."""
        user_id = str(user_id)
        content = content.strip()
        if not content or fact_type not in FACT_TYPES:
            return False
        if len(content) > 500:
            content = content[:500]
        if confidence < 0.3:
            return False

        now = time.time()
        fact = {
            "fact_id": f"f_{user_id}_{int(now)}_{hash(content) % 10000}",
            "user_id": user_id,
            "fact_type": fact_type,
            "content": content,
            "confidence": min(1.0, max(0.3, confidence)),
            "created_at": now,
            "updated_at": now,
            "source_chat_id": str(source_chat_id),
        }

        if user_id not in self._facts:
            self._facts[user_id] = []

        # Dedup: same type + content = boost confidence
        for existing in self._facts[user_id]:
            if existing["fact_type"] == fact_type and existing["content"] == content:
                existing["confidence"] = min(1.0, existing["confidence"] + 0.15)
                existing["updated_at"] = now
                self._save()
                return True

        self._facts[user_id].append(fact)
        # Keep max 150 facts per user
        self._facts[user_id] = sorted(
            self._facts[user_id], key=lambda f: -f["confidence"]
        )[:150]
        self._save()
        return True

    def add_facts_bulk(self, user_id: str, facts: list[dict]):
        """Add multiple facts at once (from extractor)."""
        for fact in facts:
            self.add_fact(
                user_id=user_id,
                fact_type=fact.get("fact_type", "fact"),
                content=fact.get("content", ""),
                confidence=fact.get("confidence", 0.6),
                source_chat_id=fact.get("source_chat_id", ""),
            )

    def get_facts(
        self,
        user_id: str,
        min_confidence: float = 0.4,
        fact_types: set[str] | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Get facts for a user, filtered and sorted by confidence."""
        user_id = str(user_id)
        results = []
        for fact in self._facts.get(user_id, []):
            if fact["confidence"] < min_confidence:
                continue
            if fact_types and fact["fact_type"] not in fact_types:
                continue
            results.append(fact)
        return sorted(results, key=lambda f: -f["confidence"])[:limit]

    def build_context(self, user_id: str, max_facts: int = 15) -> str:
        """Build a natural-language context block for AI system prompts."""
        facts = self.get_facts(user_id)
        if not facts:
            return ""
        parts = ["## 📝 Memory About You"]
        for fact in facts[:max_facts]:
            icon = FACT_ICONS.get(fact["fact_type"], "•")
            parts.append(f"{icon} {fact['content']}")
        return "\n".join(parts)

    def count(self, user_id: str) -> int:
        return len(self._facts.get(str(user_id), []))

    def clear_user(self, user_id: str):
        self._facts.pop(str(user_id), None)
        self._save()


# Global instance
fact_memory = FactMemory()
