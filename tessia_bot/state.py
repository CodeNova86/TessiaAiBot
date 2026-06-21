import json
import os
import re
import threading
import time
import traceback
from collections import defaultdict, deque

from .config import (
    AUTOMATION_RULES_FILE,
    DATA_FILE,
    FILE_INDEX_SNIPPET_CHARS,
    LOG_FILE,
    MAX_MEMORY_MESSAGES,
    RATE_LIMIT_BURST,
    RATE_LIMIT_MUTE_SECONDS,
    RATE_LIMIT_WINDOW,
)
from .logging_utils import get_logger

memory = {}
user_labels = {}
name_to_id = {}
reaction_media = {}
user_profiles = {}
user_file_index = {}
automation_rules = []
save_lock = threading.Lock()
log_lock = threading.Lock()
rate_limit_events = defaultdict(deque)
rate_limit_blocked_until = {}
bot_started_at = 0.0
logger = get_logger("state")


def trim_memory_items(items, limit=MAX_MEMORY_MESSAGES):
    return items[-limit:] if len(items) > limit else items


def default_user_profile():
    return {
        "relationship": "stranger",
        "memory_summary": "",
        "voice_reply": False,
        "preferred_language": "",
        "last_seen_language": "",
    }


def make_memory_key(chat_id, user_id):
    return f"{chat_id}:{user_id}"


def migrate_memory_data(raw_memory):
    migrated = {}
    if not isinstance(raw_memory, dict):
        return migrated
    for key, items in raw_memory.items():
        if not isinstance(items, list):
            continue
        new_key = key if ":" in str(key) else make_memory_key("legacy", key)
        cleaned_items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant", "system"} and content:
                cleaned_items.append({"role": role, "content": content})
        migrated[new_key] = trim_memory_items(cleaned_items)
    return migrated


def migrate_user_labels(raw_labels):
    migrated = {}
    if not isinstance(raw_labels, dict):
        return migrated
    for user_id, labels in raw_labels.items():
        if isinstance(labels, dict):
            label = str(labels.get("label", "")).strip()
            behavior = str(labels.get("behavior", "")).strip()
            if label or behavior:
                migrated[str(user_id)] = {"label": label, "behavior": behavior}
            continue
        source_text = ""
        if isinstance(labels, list) and labels:
            source_text = str(labels[-1]).strip()
        elif isinstance(labels, str):
            source_text = labels.strip()
        if source_text.startswith("لقب "):
            migrated[str(user_id)] = {"label": source_text[4:].strip(" :،,-"), "behavior": ""}
    return migrated


def migrate_reaction_media(raw_media):
    migrated = {}
    if not isinstance(raw_media, dict):
        return migrated
    for mood, meta in raw_media.items():
        if not isinstance(meta, dict):
            continue
        file_id = meta.get("file_id")
        media_type = meta.get("type")
        if file_id and media_type in {"animation", "sticker"}:
            migrated[str(mood)] = {
                "file_id": str(file_id),
                "type": media_type,
                "file_unique_id": str(meta.get("file_unique_id", "")),
            }
    if "sad" in migrated and "ناراحت" not in migrated:
        migrated["ناراحت"] = migrated.pop("sad")
    return migrated


def migrate_user_profiles(raw_profiles):
    migrated = {}
    if not isinstance(raw_profiles, dict):
        return migrated
    for user_id, profile in raw_profiles.items():
        base = default_user_profile()
        if isinstance(profile, dict):
            for key in base:
                value = profile.get(key)
                if isinstance(value, type(base[key])) or (base[key] == "" and isinstance(value, str)):
                    base[key] = value
        migrated[str(user_id)] = base
    return migrated


def migrate_user_file_index(raw_index):
    migrated = {}
    if not isinstance(raw_index, dict):
        return migrated
    for user_id, entries in raw_index.items():
        if not isinstance(entries, list):
            continue
        cleaned = []
        for entry in entries[-40:]:
            if not isinstance(entry, dict):
                continue
            cleaned.append({
                "file_name": str(entry.get("file_name", ""))[:200],
                "content": str(entry.get("content", ""))[:12000],
                "caption": str(entry.get("caption", ""))[:1000],
                "mime": str(entry.get("mime", ""))[:120],
                "timestamp": float(entry.get("timestamp", 0) or 0),
            })
        migrated[str(user_id)] = cleaned
    return migrated


def save_data():
    data = {
        "memory": memory,
        "user_labels": user_labels,
        "name_to_id": name_to_id,
        "reaction_media": reaction_media,
        "user_profiles": user_profiles,
        "user_file_index": user_file_index,
    }
    with save_lock:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def load_automation_rules():
    global automation_rules
    if not os.path.exists(AUTOMATION_RULES_FILE):
        automation_rules = []
        return
    with open(AUTOMATION_RULES_FILE, "r", encoding="utf-8") as f:
        raw_rules = json.load(f)
    automation_rules = raw_rules if isinstance(raw_rules, list) else []


def save_automation_rules():
    with save_lock:
        with open(AUTOMATION_RULES_FILE, "w", encoding="utf-8") as f:
            json.dump(automation_rules, f, ensure_ascii=False, indent=2)


def load_data():
    global memory, user_labels, name_to_id, reaction_media, user_profiles, user_file_index
    if not os.path.exists(DATA_FILE):
        load_automation_rules()
        return
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    memory = migrate_memory_data(data.get("memory", {}))
    user_labels = migrate_user_labels(data.get("user_labels", {}))
    name_to_id = data.get("name_to_id", {})
    reaction_media = migrate_reaction_media(data.get("reaction_media", {}))
    user_profiles = migrate_user_profiles(data.get("user_profiles", {}))
    user_file_index = migrate_user_file_index(data.get("user_file_index", {}))
    load_automation_rules()
    save_data()


def get_user_profile(user_id):
    user_id = str(user_id)
    if user_id not in user_profiles or not isinstance(user_profiles[user_id], dict):
        user_profiles[user_id] = default_user_profile()
    else:
        base = default_user_profile()
        base.update(user_profiles[user_id])
        user_profiles[user_id] = base
    return user_profiles[user_id]


def remember_message(memory_key, role, content):
    if not content:
        return
    if memory_key not in memory:
        memory[memory_key] = []
    memory[memory_key].append({"role": role, "content": content})
    memory[memory_key] = trim_memory_items(memory[memory_key])


def get_memory_history(memory_key):
    return trim_memory_items(memory.get(memory_key, []))


def count_user_messages(memory_key):
    return sum(1 for item in memory.get(memory_key, []) if item.get("role") == "user")


def update_relationship_stage(user_id, memory_key):
    profile = get_user_profile(user_id)
    user_count = count_user_messages(memory_key)
    if user_count >= 25:
        profile["relationship"] = "trusted"
    elif user_count >= 8:
        profile["relationship"] = "friend"
    else:
        profile["relationship"] = "stranger"


def remember_file_for_user(user_id, file_name, content, caption="", mime=""):
    user_id = str(user_id)
    entries = user_file_index.setdefault(user_id, [])
    entries.append({
        "file_name": (file_name or "unknown")[:200],
        "content": (content or "")[:12000],
        "caption": (caption or "")[:1000],
        "mime": (mime or "")[:120],
        "timestamp": time.time(),
    })
    user_file_index[user_id] = entries[-40:]


def build_file_search_context(user_id, query):
    query = (query or "").strip().lower()
    if not query:
        return ""
    entries = user_file_index.get(str(user_id), [])
    ranked = []
    for entry in entries:
        haystack = " ".join([entry.get("file_name", ""), entry.get("caption", ""), entry.get("content", "")]).lower()
        score = sum(1 for token in query.split() if token in haystack)
        if score:
            ranked.append((score, entry))
    ranked.sort(key=lambda item: (item[0], item[1].get("timestamp", 0)), reverse=True)
    if not ranked:
        return ""
    parts = ["### Relevant Previous Files"]
    for _, entry in ranked[:5]:
        snippet = entry.get("content", "")[:FILE_INDEX_SNIPPET_CHARS]
        parts.append(
            f"File: {entry.get('file_name', 'unknown')}\n"
            f"Caption: {entry.get('caption', '')}\n"
            f"Snippet:\n{snippet}"
        )
    return "\n\n".join(parts)


def detect_language_name(text):
    if not text:
        return ""
    if re.search(r"[\u0600-\u06FF]", text):
        return "Persian"
    if re.search(r"[A-Za-z]", text):
        return "English"
    return ""


def update_user_language(user_id, text):
    lang = detect_language_name(text)
    if lang:
        profile = get_user_profile(user_id)
        profile["last_seen_language"] = lang
        if not profile.get("preferred_language"):
            profile["preferred_language"] = lang


def log_error(context_name, exc):
    logger.error("%s: %s\n%s", context_name, exc, traceback.format_exc())


def is_rate_limited(user_id):
    now = time.time()
    blocked_until = rate_limit_blocked_until.get(str(user_id), 0)
    if blocked_until > now:
        return int(blocked_until - now)
    events = rate_limit_events[str(user_id)]
    while events and now - events[0] > RATE_LIMIT_WINDOW:
        events.popleft()
    if len(events) >= RATE_LIMIT_BURST:
        rate_limit_blocked_until[str(user_id)] = now + RATE_LIMIT_MUTE_SECONDS
        return RATE_LIMIT_MUTE_SECONDS
    events.append(now)
    return 0


def mark_bot_started():
    global bot_started_at
    bot_started_at = time.time()


def is_message_from_before_start(message):
    if not bot_started_at:
        return False
    message_date = getattr(message, "date", None)
    if not message_date:
        return False
    try:
        return message_date.timestamp() < bot_started_at - 2
    except Exception:
        return False
