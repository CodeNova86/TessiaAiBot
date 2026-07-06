"""
Father Gateway — Learning Module

Tracks patterns per contact:
- Which stickers/GIFs they send most
- Their common catchphrases / tone patterns
- Which stickers/GIFs we replied with in what context

Data is saved to father_learning.json and used in the system prompt
to make the father's replies more natural and personalized.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict
from typing import Any

from .config import FATHER_LEARNING_FILE

logger = __import__("logging").getLogger("tessia.father_learning")

# ─────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────

LEARNING_DATA: dict[str, dict[str, Any]] = {}
_loaded = False


def default_contact_data() -> dict:
    return {
        "frequent_stickers": [],       # [{"file_id": ..., "emoji": ..., "count": N}, ...]
        "frequent_gifs": [],           # [{"file_id": ..., "count": N}, ...]
        "catchphrases": {},            # {"phrase": count, ...}
        "topics": Counter(),           # {"topic_word": count, ...}
        "our_replied_stickers": [],    # stickers we sent them: [{"file_id":..., "context": "...", "count": N}]
        "our_replied_gifs": [],        # GIFs we sent them
        "total_messages": 0,
        "last_interaction": 0.0,
    }


def load() -> dict:
    global LEARNING_DATA, _loaded
    if _loaded:
        return LEARNING_DATA
    if os.path.exists(FATHER_LEARNING_FILE):
        try:
            with open(FATHER_LEARNING_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                LEARNING_DATA.update(raw)
        except Exception as e:
            logger.error("Failed to load learning data: %s", e)
    _loaded = True
    return LEARNING_DATA


def save():
    os.makedirs(os.path.dirname(FATHER_LEARNING_FILE) or ".", exist_ok=True)
    with open(FATHER_LEARNING_FILE, "w", encoding="utf-8") as f:
        json.dump(LEARNING_DATA, f, ensure_ascii=False, indent=2)


def get_contact(contact_id: str) -> dict:
    load()
    contact_id = str(contact_id).lower().lstrip("@")
    if contact_id not in LEARNING_DATA:
        LEARNING_DATA[contact_id] = default_contact_data()
    else:
        # Ensure topics is a Counter (JSON loads it as plain dict)
        if not isinstance(LEARNING_DATA[contact_id].get("topics"), Counter):
            LEARNING_DATA[contact_id]["topics"] = Counter(LEARNING_DATA[contact_id].get("topics", {}))
    return LEARNING_DATA[contact_id]


# ─────────────────────────────────────────────
# LEARNING FUNCTIONS
# ─────────────────────────────────────────────


def learn_message(contact_id: str, text: str = "", sticker=None, gif=None):
    """Learn from a message the contact sent us."""
    contact = get_contact(contact_id)
    contact["total_messages"] += 1
    contact["last_interaction"] = time.time()

    # Learn catchphrases (3-gram phrases that appear repeatedly)
    if text:
        words = text.strip().split()
        for i in range(len(words) - 1):
            phrase = " ".join(words[i:i+2]).strip(" .,!?")
            if 2 <= len(phrase) <= 40:
                contact["catchphrases"][phrase] = contact["catchphrases"].get(phrase, 0) + 1

        # Learn topic words (meaningful words with 3+ chars)
        import re
        for w in words:
            clean = re.sub(r"[^\w\u0600-\u06FF]", "", w)
            if len(clean) >= 3:
                contact["topics"][clean] += 1

    # Learn stickers
    if sticker:
        emoji = sticker.emoji or "🤔"
        sticker_id = sticker.file_id
        existing = [s for s in contact["frequent_stickers"] if s["file_id"] == sticker_id]
        if existing:
            existing[0]["count"] += 1
        else:
            contact["frequent_stickers"].append({"file_id": sticker_id, "emoji": emoji, "count": 1})

    # Learn GIFs
    if gif:
        gif_id = gif.file_id
        existing = [g for g in contact["frequent_gifs"] if g["file_id"] == gif_id]
        if existing:
            existing[0]["count"] += 1
        else:
            contact["frequent_gifs"].append({"file_id": gif_id, "count": 1})

    # Trim to keep top items
    contact["frequent_stickers"] = sorted(contact["frequent_stickers"], key=lambda x: x["count"], reverse=True)[:20]
    contact["frequent_gifs"] = sorted(contact["frequent_gifs"], key=lambda x: x["count"], reverse=True)[:10]
    # Keep top catchphrases
    top = sorted(contact["catchphrases"].items(), key=lambda x: -x[1])[:30]
    contact["catchphrases"] = dict(top)
    # Keep top topics
    contact["topics"] = Counter(dict(contact["topics"].most_common(20)))

    save()


def learn_our_reply(contact_id: str, sticker=None, gif=None, context_text: str = ""):
    """Learn what we (father) replied with, for consistency."""
    contact = get_contact(contact_id)

    if sticker:
        sid = sticker.file_id
        existing = [s for s in contact["our_replied_stickers"] if s["file_id"] == sid]
        if existing:
            existing[0]["count"] += 1
        else:
            contact["our_replied_stickers"].append({
                "file_id": sid, "context": context_text[:100], "count": 1,
            })

    if gif:
        gid = gif.file_id
        existing = [g for g in contact["our_replied_gifs"] if g["file_id"] == gid]
        if existing:
            existing[0]["count"] += 1
        else:
            contact["our_replied_gifs"].append({
                "file_id": gid, "context": context_text[:100], "count": 1,
            })

    contact["our_replied_stickers"] = sorted(
        contact["our_replied_stickers"], key=lambda x: x["count"], reverse=True
    )[:10]
    contact["our_replied_gifs"] = sorted(
        contact["our_replied_gifs"], key=lambda x: x["count"], reverse=True
    )[:10]
    save()


def get_learning_context(contact_id: str) -> str:
    """Build a learning context string for the AI system prompt."""
    contact = get_contact(contact_id)
    parts = []

    if contact["total_messages"] > 0:
        parts.append(f"📊 {contact['total_messages']} messages exchanged so far.")

    # Frequent stickers they use
    if contact["frequent_stickers"]:
        top_stickers = contact["frequent_stickers"][:5]
        sticker_list = ", ".join(
            f"{s['emoji']} (×{s['count']})" for s in top_stickers
        )
        parts.append(f"🔹 Their frequent stickers: {sticker_list}")

    # Catchphrases
    top_phrases = sorted(contact["catchphrases"].items(), key=lambda x: -x[1])[:5]
    if top_phrases:
        phrase_list = ", ".join(f"\"{p}\" (×{c})" for p, c in top_phrases)
        parts.append(f"🔹 Their common phrases: {phrase_list}")

    # Topics they talk about
    if contact["topics"]:
        top_topics = contact["topics"].most_common(5)
        topic_list = ", ".join(f"{t}" for t, c in top_topics)
        parts.append(f"🔹 Frequent topics: {topic_list}")

    # Stickers/GIFs we've sent them
    if contact["our_replied_stickers"]:
        our_stickers = [s["emoji"] for s in contact["our_replied_stickers"][:3]]
        parts.append(f"🔹 Stickers you've sent them before: {', '.join(our_stickers)}")

    return "\n".join(parts)


def get_learning_summary() -> dict:
    """Get overall learning stats for the panel."""
    load()
    total_contacts = len(LEARNING_DATA)
    total_msgs = sum(c.get("total_messages", 0) for c in LEARNING_DATA.values())
    return {
        "total_contacts_learned": total_contacts,
        "total_messages_tracked": total_msgs,
    }
