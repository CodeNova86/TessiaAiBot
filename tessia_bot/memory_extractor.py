"""
Memory Fact Extractor — uses AI to extract durable facts from conversations.

After every user interaction, runs a fast LLM call to extract facts
(name, preferences, behavior, catchphrases, etc.) and stores them
in the fact_memory. Runs asynchronously — never blocks the response.
"""

from __future__ import annotations

import json
import logging

from tessia_bot.config import client, MODEL_NAME
from tessia_bot.memory_facts import fact_memory

logger = logging.getLogger("tessia.memory_extractor")

EXTRACTOR_SYSTEM_PROMPT = """\
You extract durable facts about the USER from a conversation turn.

Only extract facts that are:
- Explicitly stated or very strongly implied
- Likely to be useful across multiple future conversations
- Not temporary/transient states (e.g. "I'm tired now" = skip)

Return a JSON array of objects with:
- "fact_type": one of "name", "preference", "fact", "relationship", "language", "topic", "behavior", "catchphrase", "important"
- "content": short fact text in Persian (max 120 chars)
- "confidence": 0.0 to 1.0

Examples:
User: "اسم من علیه" → [{"fact_type": "name", "content": "اسمش علی است", "confidence": 0.9}]
User: "من فیلم ترسناک دوست دارم" → [{"fact_type": "preference", "content": "فیلم ترسناک دوست دارد", "confidence": 0.8}]
User: "به داداشم میگم پوری" → [{"fact_type": "relationship", "content": "داداشی به اسم پوریا دارد", "confidence": 0.7}]
User: "سلام خوبی" → []

Return ONLY valid JSON array. No markdown, no explanation.
"""


async def extract_and_store(
    user_id: str,
    user_text: str,
    ai_text: str,
    chat_id: str = "",
    source: str = "tessia_bot",
):
    """Extract facts from a conversation turn and store them.

    This is fire-and-forget (async task) — never blocks.
    """
    combined = f"User: {user_text}\nAI: {ai_text}"
    if len(combined) < 10:
        return

    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": EXTRACTOR_SYSTEM_PROMPT},
                {"role": "user", "content": combined[:2000]},
            ],
            temperature=0.1,
            max_tokens=600,
            stream=False,
        )
        content = (response.choices[0].message.content or "").strip()

        # Strip markdown code fences
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        facts = json.loads(content)
        if not isinstance(facts, list):
            return

        # Add source chat_id to each fact and store
        for fact in facts:
            fact["source_chat_id"] = str(chat_id)
        fact_memory.add_facts_bulk(user_id, facts)

        if facts:
            logger.info(
                "Extracted %d facts for user=%s: %s",
                len(facts),
                user_id,
                [f["content"][:40] for f in facts],
            )
    except json.JSONDecodeError:
        pass  # LLM returned invalid JSON — skip silently
    except Exception as e:
        logger.warning("Fact extraction error: %s", e)
