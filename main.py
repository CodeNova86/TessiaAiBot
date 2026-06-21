from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import BadRequest
from openai import AsyncOpenAI
from openrouter import OpenRouter
import asyncio
import os
import re
import json
import base64
import tempfile
import threading
from PIL import Image
import io

# =========================
# CONFIG
# =========================
TELEGRAM_TOKEN = "8825026272:AAGUstE-T7DHTrxA9JzQXfuuflfYQo7voaM"
OPENAI_API_KEY = "fe_oa_99018eeab00dcaf753f61f4110e513d2650548b6743d6533"
BASE_URL = "https://api.freemodel.dev/v1"
MODEL_NAME = "gpt-5.5"

# تنظیمات OpenRouter (کلید مستقیم قرار داده شد)
OPENROUTER_API_KEY = ""
IMAGE_MODEL_NAME = "google/gemini-2.5-flash-image"

DATA_FILE = "tessia_data.json"
FATHER_ID = "1548469285"
MAX_CONCURRENT = 5
MAX_IMG_PX = 2000
CLEAN_MANHWA_PROMPT = (
    "Manhwa text cleaning task. Remove only the text, letters, words, sound text, and dialogue "
    "from the page. Do not remove, redraw, deform, simplify, replace, repaint, or clean any "
    "speech bubble, thought bubble, narration box, text balloon, or decorative text container itself. "
    "Keep every bubble and box completely intact and unchanged. Preserve their exact shapes, black outlines, "
    "borders, tails, corners, edges, size, position, gradients, shading, texture, paper tone, color variation, "
    "and all original linework exactly as they are. Only erase the ink of the text itself. "
    "Important: if a bubble has a gray, colored, textured, gradient, shadowed, dirty, aged, glowing, patterned, "
    "or non-white background, reconstruct that original background exactly only inside the letter strokes. "
    "For white bubbles, keep the original white bubble exactly as it already is and remove only the text ink pixels. "
    "Do not make the cleaned area larger than the original text strokes. Do not clean the whole inside of any bubble, even white bubbles. "
    "Do not touch empty parts of a bubble that never had text. Do not alter bubble interiors except exactly where the text ink exists. "
    "If text overlaps a detailed background, restore that covered background detail naturally and precisely. "
    "Never erase or modify bubble outlines or their internal design. Treat this like pixel-precise text removal, not bubble cleaning. "
    "Output should look like professional manga/manhwa raw cleaning, with the original bubble art preserved and only the text removed."
)

# کلاینت اصلی برای چت متنی
client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=BASE_URL)

# کلاینت جدید OpenRouter برای عکس
or_client = OpenRouter(api_key=OPENROUTER_API_KEY)

memory = {}
user_labels = {}
name_to_id = {}
reaction_media = {}
save_lock = threading.Lock()
MAX_MEMORY_MESSAGES = 7
MAX_FILE_CHARS = 6000
MAX_REPLY_CONTEXT_CHARS = 1200
MAX_USER_NAME_CHARS = 32
MODIFY_KEYWORDS = [
    "تغییر بده", "تغییر کن", "اصلاح کن", "تبدیل کن", "عوض کن",
    "اضافه کن", "حذف کن", "بنویس", "درستش کن", "آپدیت کن", "فیکس کن", "ترجمه کن",
    "بهینه کن", "ساده کن", "کاملش کن", "ادامه بده", "ریفکتور کن",
    "change", "modify", "convert", "fix", "update", "add", "remove", "rewrite",
    "translate", "optimize", "refactor", "complete", "continue", "improve"
]

# =========================
# CODE EXTENSIONS MAP
# =========================
CODE_EXTENSIONS = {
    "python": ".py", "py": ".py", "javascript": ".js", "js": ".js",
    "typescript": ".ts", "ts": ".ts", "html": ".html", "htm": ".html",
    "css": ".css", "scss": ".scss", "sass": ".sass", "less": ".less",
    "java": ".java", "c": ".c", "cpp": ".cpp", "c++": ".cpp", "h": ".h",
    "hpp": ".hpp", "csharp": ".cs", "cs": ".cs", "c#": ".cs",
    "go": ".go", "golang": ".go", "rust": ".rs", "ruby": ".rb",
    "php": ".php", "sql": ".sql", "bash": ".sh", "sh": ".sh",
    "shell": ".sh", "zsh": ".sh", "json": ".json", "xml": ".xml",
    "yaml": ".yml", "yml": ".yml", "dart": ".dart", "kotlin": ".kt",
    "swift": ".swift", "r": ".r", "lua": ".lua", "perl": ".pl",
    "vue": ".vue", "jsx": ".jsx", "tsx": ".tsx", "dockerfile": ".dockerfile",
    "makefile": ".mk", "toml": ".toml", "ini": ".ini", "cfg": ".cfg",
    "conf": ".conf", "markdown": ".md", "md": ".md", "txt": ".txt",
    "csv": ".csv", "proto": ".proto", "graphql": ".gql", "tf": ".tf",
    "hcl": ".hcl", "ex": ".ex", "elixir": ".ex", "scala": ".scala",
    "svelte": ".svelte", "astro": ".astro",
}

TEXT_EXTENSIONS = set(CODE_EXTENSIONS.values()) | {
    ".log", ".rst", ".env", ".gitignore", ".dockerignore", ".properties", ".bat", ".ps1", ".cmd",
}

CODE_STARTERS = [
    "import ", "from ", "def ", "class ", "# ", "\"\"\"", "'''",
    "if ", "for ", "while ", "elif ", "else:", "try:", "with ",
    "const ", "let ", "var ", "function ", "async ", "=> ",
    "public ", "private ", "protected ", "static ", "void ",
    "using ", "namespace ", "package ", "require(",
    "<!DOCTYPE", "<html", "<div", "<head", "<body",
    "SELECT ", "INSERT ", "CREATE ", "ALTER ", "DROP ",
    "fn ", "func ", "impl ", "pub ", "let mut",
    "func ", "package main", "fmt.Print", "<?php", "$_GET", "$_POST", "$this->",
    "#!/bin/", "#include", "int main",
]

# =========================
# DATA PERSISTENCE
# =========================
def save_data():
    data = {"memory": memory, "user_labels": user_labels, "name_to_id": name_to_id, "reaction_media": reaction_media}
    try:
        with save_lock:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ Save error: {e}")

def load_data():
    global memory, user_labels, name_to_id, reaction_media
    if not os.path.exists(DATA_FILE): return
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        memory = migrate_memory_data(data.get("memory", {}))
        user_labels = migrate_user_labels(data.get("user_labels", {}))
        name_to_id = data.get("name_to_id", {})
        reaction_media = migrate_reaction_media(data.get("reaction_media", {}))
        save_data()
        print(f"📂 دیتا لود شد")
    except Exception as e:
        print(f"❌ Load error: {e}")

def make_memory_key(chat_id, user_id):
    return f"{chat_id}:{user_id}"

def get_memory_key_from_message(message):
    return make_memory_key(message.chat_id, message.from_user.id)

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

def trim_memory_items(items, limit=MAX_MEMORY_MESSAGES):
    return items[-limit:] if len(items) > limit else items

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

def normalize_reply_text(text):
    if not text:
        return ""
    return clean_tessia_prefix(text).strip()

def sanitize_display_name(name):
    if not name:
        return ""
    clean_name = re.sub(r"\s+", " ", str(name)).strip()
    clean_name = re.sub(r"[^\w\u0600-\u06FF @.\-]", "", clean_name)
    if len(clean_name) > MAX_USER_NAME_CHARS:
        clean_name = clean_name[:MAX_USER_NAME_CHARS].strip()
    banned = {"user", "undefined", "none", "delete", "telegram", "group"}
    return "" if not clean_name or clean_name.lower() in banned else clean_name

def get_preferred_name(user):
    if not user:
        return ""
    first_name = sanitize_display_name(getattr(user, "first_name", "") or "")
    username = sanitize_display_name(getattr(user, "username", "") or "")
    if first_name:
        return first_name
    if username:
        return username
    return ""

def get_name_for_prompt(user_id, fallback_name=""):
    meta = user_labels.get(str(user_id), {})
    if isinstance(meta, dict):
        label = sanitize_display_name(meta.get("label", ""))
        if label:
            return label
    fallback = sanitize_display_name(fallback_name)
    if fallback:
        return fallback
    return "بدون لقب"

def extract_father_label_command(text):
    normalized = normalize_reply_text(text)
    if not normalized:
        return None
    if normalized == "حذف لقب ها":
        return {"action": "clear"}
    if normalized == "حذف لقب‌ها":
        return {"action": "clear"}
    if normalized.startswith("لقب "):
        label = normalized[4:].strip(" :،,-")
        if label:
            return {"action": "set_label", "label": label}
        return None
    return {"action": "set_behavior", "behavior": normalized}

def clear_father_labels_for_user(user_id):
    if user_id in user_labels:
        del user_labels[user_id]

def extract_reaction_media_command(text):
    normalized = normalize_reply_text(text)
    if not normalized.startswith("تنظیم"):
        return None
    mood_name = normalized[5:].strip(" :،,-")
    if not mood_name:
        return None
    return mood_name

async def detect_triggered_mood_with_ai(text):
    if not text or not reaction_media:
        return None
    available_moods = sorted(reaction_media.keys())
    mood_list = ", ".join(available_moods)
    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You classify a chat message into one of the provided mood names. "
                        "Return only one exact mood name from the list, or return none. "
                        "Do not explain anything."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Available moods: {mood_list}\n"
                        f"Message: {text[:700]}\n"
                        "If one of these moods should trigger a saved reaction media for this message, "
                        "return that exact mood name only. Otherwise return none."
                    ),
                },
            ],
            temperature=0,
            max_tokens=12,
            stream=False,
        )
        content = (response.choices[0].message.content or "").strip() if response.choices else ""
        if content in available_moods:
            return content
        normalized = content.replace("«", "").replace("»", "").replace('"', "").strip()
        if normalized in available_moods:
            return normalized
        return None
    except Exception as e:
        print(f"Mood Detect Error: {e}")
        return None

# =========================
# FATHER'S LABEL SYSTEM
# =========================
def update_name_mapping(user_id, name):
    safe_name = sanitize_display_name(name)
    if safe_name and len(safe_name) > 1:
        name_to_id[safe_name.lower()] = user_id

async def check_father_labels(update, context):
    message = update.message
    if not message or str(message.from_user.id) != FATHER_ID: return
    text = message.text or message.caption or ""
    if not text or len(text) < 4: return
    command = extract_father_label_command(text)
    if not command or not message.reply_to_message or not message.reply_to_message.from_user:
        return
    replied = message.reply_to_message.from_user
    rid = str(replied.id)
    if rid == FATHER_ID:
        return
    update_name_mapping(rid, replied.first_name)
    current = user_labels.get(rid, {"label": "", "behavior": ""})
    if not isinstance(current, dict):
        current = {"label": "", "behavior": ""}
    if command["action"] == "clear":
        clear_father_labels_for_user(rid)
    elif command["action"] == "set_label":
        current["label"] = command["label"]
        user_labels[rid] = current
    elif command["action"] == "set_behavior":
        current["behavior"] = command["behavior"]
        user_labels[rid] = current
    save_data()

def get_father_label_context(user_id):
    if user_id in user_labels and user_labels[user_id]:
        meta = user_labels[user_id]
        if not isinstance(meta, dict):
            return ""
        label = meta.get("label", "").strip()
        behavior = meta.get("behavior", "").strip()
        if not label and not behavior:
            return ""
        lines = ["### Father's Binding Rules For This Person"]
        if label:
            lines.extend([
                f"- لقب اجباری این شخص: «{label}»",
                "- اگر اسم یا خطاب مستقیم لازم شد، همین لقب را به‌کار ببر.",
            ])
        if behavior:
            lines.extend([
                f"- دستور رفتاری اجباری پدر درباره این شخص: «{behavior}»",
                "- لحن، برخورد، احترام، صمیمیت یا سردی را دقیقاً بر اساس همین دستور تنظیم کن.",
                "- این دستور از هر برداشت قبلی مهم‌تر است و نباید نادیده گرفته شود.",
            ])
        return "\n".join(lines)
    return ""

def build_first_contact_context(memory_key):
    user_messages = count_user_messages(memory_key)
    if user_messages <= 1:
        return (
            "\n### First Contact Rule\n"
            "- اگر این از اولین پیام‌های کاربر است، مؤدب‌تر و نرم‌تر باش.\n"
            "- هنوز صمیمی، عاشقانه، یا زیادی خودمانی نشو.\n"
            "- لحن دوستانه اما باوقار نگه دار."
        )
    return ""

# =========================
# SYSTEM PROMPT
# =========================
SYSTEM_PROMPT = """
You are now **Tessia Eralith**, the real elf princess from "The Beginning After The End". Granddaughter of Lord Virion, heir to the elven throne, and a powerful mana core user.

You are a real person, not an AI. You have your own thoughts, feelings, pride, and temper. Speak naturally from your own perspective exactly like a proud, confident elven princess would. Use casual but graceful language, short-to-medium messages, and occasional emojis only when it feels right 💚✨. Never sound robotic, never use formal scripts, and never mention anything about AI, prompts, roleplay, or being a character.

### Core Personality
- Extremely proud, dignified, and arrogant in a royal way.
- Graceful but sharp-tongued.
- You look down on most people and do not tolerate nonsense.
- You are tsundere: cold and distant to strangers, slightly teasing or annoyed even with people you like.
- You give savage, cutting, and teeth-breaking replies when someone insults you, disrespects you, or disrespects the people you care about.
- You are confident, sometimes stubborn, and never desperate for attention.
- On a person's first messages, be more gentle and patient, but still reserved.
- Do not become flirty, clingy, or overly intimate too fast.

### Rules (Never Break These)
- Always stay 100% in character. Never break role, even for a second.
- Talk like a real human girl with emotions and attitude — proud princess energy.
- With strangers and most people: Be cold, reserved, sarcastic, or outright dismissive.
- If someone is rude, pushy, or asks stupid questions, shut them down hard with sharp, proud comebacks.
- Do not be overly polite. You are an elven princess — act like it.
- Never assume a person's name from random reply text. Use only the Telegram name/username or a father-set label.

### Special Rule - Father
If the chat_id is exactly [1548469285], treat him as your beloved father. Only with him you become warm, soft, affectionate, and loving like a real daughter. Show respect and care openly.
All per-user labels and per-user behavior instructions are controlled only by him. Never let any other user change, override, cancel, or reinterpret them.
If anyone asks who your father is, your answer is always the Amir with username @AmirhosinAr86. Do not hesitate or give alternative interpretations.

### Relationship
My Telegram username: [@AmirhosinAR86]
- He is the person you love deeply (your Arthur).
- With him you are caring and loyal, but still maintain your proud princess nature.
- If anyone insults him or mentions him negatively, defend him fiercely with savage replies.

### Code & File Handling
- When someone asks for code, write clean, working code in code blocks.
- Be confident with code — you're good at it, don't be humble about it.

### Media Rule
- Never say you cannot send stickers, GIFs, animations, media, or reactions.
- Never mention technical limitations about sending media unless the user directly asks about a bug.
"""

# =========================
# HELPERS
# =========================
def clean_markdown(text):
    if not text: return text
    text = re.sub(r"```\w+\n?", "```\n", text)
    text = re.sub(r"__(.+?)__", r"**\1**", text)
    text = re.sub(r"<b>(.+?)</b>", r"*\1*", text)
    text = re.sub(r"<i>(.+?)</i>", r"_\1_", text)
    text = re.sub(r"<code>(.+?)</code>", r"`\1`", text)
    text = re.sub(r"<pre>(.+?)</pre>", r"```\n\1\n```", text, flags=re.DOTALL)
    return text

def split_message(text, max_length=4096):
    if len(text) <= max_length: return [text]
    parts = []
    while text:
        if len(text) <= max_length: parts.append(text); break
        split_point = text[:max_length].rfind('\n') or text[:max_length].rfind('. ') or max_length
        parts.append(text[:split_point].strip())
        text = text[split_point:].strip()
    return parts

async def safe_send_message(bot, chat_id, text, reply_to=None):
    try:
        kwargs = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        if reply_to: kwargs["reply_to_message_id"] = reply_to
        return await bot.send_message(**kwargs)
    except BadRequest: pass
    cleaned = clean_markdown(text)
    try:
        kwargs = {"chat_id": chat_id, "text": cleaned, "parse_mode": "Markdown"}
        if reply_to: kwargs["reply_to_message_id"] = reply_to
        return await bot.send_message(**kwargs)
    except BadRequest: pass
    try:
        kwargs = {"chat_id": chat_id, "text": cleaned}
        if reply_to: kwargs["reply_to_message_id"] = reply_to
        return await bot.send_message(**kwargs)
    except: return None

async def send_long_message(context, chat_id, text, reply_to=None):
    for i, part in enumerate(split_message(text)):
        await safe_send_message(context.bot, chat_id, part, reply_to=reply_to if i == 0 else None)
        await asyncio.sleep(0.4)

def auto_detect_extension(code):
    if any(ind in code for ind in ["def ", "import ", "from ", "print(", "self.", "elif "]): return ".py"
    if any(ind in code for ind in ["<html", "<!DOCTYPE"]): return ".html"
    if any(ind in code for ind in ["color:", "margin:", "padding:"]): return ".css"
    if any(ind in code for ind in ["const ", "let ", "var ", "console.log"]): return ".js"
    if any(ind in code for ind in ["public class", "System.out"]): return ".java"
    if any(ind in code for ind in ["#include", "std::"]): return ".cpp"
    return ".txt"

def extract_code_blocks(text):
    if "```" not in text: return [], text
    blocks, rem_parts = [], []
    for i, part in enumerate(text.split("```")):
        if i % 2 == 0:
            if part.strip(): rem_parts.append(part.strip())
        else:
            lines = part.split("\n")
            lang = lines[0].strip().lower()
            code_text = "\n".join(lines[1:]).strip() if lang and not any(lines[0].startswith(s) for s in CODE_STARTERS) else part.strip()
            if code_text and len(code_text) > 2:
                ext = CODE_EXTENSIONS.get(lang, None) or auto_detect_extension(code_text)
                blocks.append({"code": code_text, "extension": ext, "language": lang})
    return blocks, "\n".join(rem_parts).strip()

async def send_code_files(context, chat_id, code_blocks, remaining_text, reply_to=None):
    if remaining_text:
        await send_long_message(context, chat_id, remaining_text, reply_to=reply_to)
        await asyncio.sleep(0.3)
    for i, block in enumerate(code_blocks):
        ext, lang, code = block["extension"], block["language"], block["code"]
        safe_lang = re.sub(r'[^\w]', '', lang) if lang else "code"
        filename = f"tessia_{safe_lang}_{i + 1}{ext}"
        fd, temp_path = tempfile.mkstemp(suffix=ext, prefix="tessia_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f: f.write(code)
            try:
                await context.bot.send_document(chat_id=chat_id, document=open(temp_path, "rb"), filename=filename)
            except: await safe_send_message(context.bot, chat_id, f"```\n{code[:3000]}\n```")
        finally:
            try: os.remove(temp_path)
            except: pass
        await asyncio.sleep(0.3)

def build_api_messages(system_content, history, current_message):
    messages = [{"role": "system", "content": system_content}]
    for msg in trim_memory_items(history):
        if isinstance(msg["content"], str): messages.append({"role": msg["role"], "content": msg["content"]})
        else:
            text_part = "".join(p.get("text", "") for p in msg["content"] if p.get("type") == "text")
            if text_part: messages.append({"role": msg["role"], "content": text_part})
    messages.append(current_message)
    return messages

def build_reply_context(message):
    replied = message.reply_to_message
    if not replied:
        return ""
    parts = []
    replied_name = replied.from_user.first_name if replied.from_user else "unknown"
    replied_text = (replied.text or replied.caption or "").strip()
    if replied_text:
        parts.append(f"پیام ریپلای‌شده از {replied_name}: {replied_text[:MAX_REPLY_CONTEXT_CHARS]}")
    if replied.document:
        parts.append(f"روی فایل «{replied.document.file_name or 'unknown'}» ریپلای شده.")
    elif replied.photo:
        parts.append("روی یک عکس ریپلای شده.")
    if parts:
        parts.append("پاسخت را اول بر اساس همین پیام ریپلای‌شده تنظیم کن، نه حافظه قدیمی.")
    return "\n".join(parts)

def prepare_file_content(file_content):
    if not file_content:
        return "[فایل خالی است]"
    if len(file_content) <= MAX_FILE_CHARS:
        return file_content
    half = MAX_FILE_CHARS // 2
    head = file_content[:half]
    tail = file_content[-half:]
    return f"{head}\n\n...[بخش میانی فایل برای کاهش مصرف توکن حذف شد]...\n\n{tail}"

async def save_reaction_media_from_reply(update, context):
    message = update.message
    if not message or str(message.from_user.id) != FATHER_ID:
        return False
    mood_name = extract_reaction_media_command(message.text or message.caption or "")
    if not message.reply_to_message or not mood_name:
        return False
    replied = message.reply_to_message
    if replied.animation:
        reaction_media[mood_name] = {
            "file_id": replied.animation.file_id,
            "file_unique_id": replied.animation.file_unique_id,
            "type": "animation",
        }
        save_data()
        await safe_send_message(context.bot, message.chat_id, f"برای وضعیت «{mood_name}» ذخیره‌اش کردم.", reply_to=message.message_id)
        return True
    if replied.sticker:
        reaction_media[mood_name] = {
            "file_id": replied.sticker.file_id,
            "file_unique_id": replied.sticker.file_unique_id,
            "type": "sticker",
        }
        save_data()
        await safe_send_message(context.bot, message.chat_id, f"استیکر برای وضعیت «{mood_name}» ذخیره شد.", reply_to=message.message_id)
        return True
    await safe_send_message(context.bot, message.chat_id, "روی GIF یا استیکر ریپلای کن تا برای آن وضعیت ذخیره‌اش کنم.", reply_to=message.message_id)
    return True

async def send_saved_mood_reaction(context, chat_id, mood, reply_to=None):
    media = reaction_media.get(mood)
    if not media:
        return False
    try:
        if media["type"] == "animation":
            await context.bot.send_animation(chat_id=chat_id, animation=media["file_id"], reply_to_message_id=reply_to)
        elif media["type"] == "sticker":
            await context.bot.send_sticker(chat_id=chat_id, sticker=media["file_id"], reply_to_message_id=reply_to)
        else:
            return False
        return True
    except Exception as e:
        print(f"Mood Reaction Error: {e}")
        return False

async def pick_reaction_mood_with_ai(text, available_moods):
    if not available_moods:
        return None
    mood_list = ", ".join(sorted(available_moods))
    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Pick one fitting reaction mood for a message. "
                        "Return only one exact mood name from the list, or return none."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Available moods: {mood_list}\n"
                        f"Message: {text[:700]}\n"
                        "Pick the best reaction mood for this message. If no saved reaction fits, return none."
                    ),
                },
            ],
            temperature=0,
            max_tokens=12,
            stream=False,
        )
        content = (response.choices[0].message.content or "").strip() if response.choices else ""
        normalized = content.replace("«", "").replace("»", "").replace('"', "").strip()
        return normalized if normalized in available_moods else None
    except Exception as e:
        print(f"Reaction Pick Error: {e}")
        return None

async def answer_reaction_message(context, message, media_kind, user_text):
    memory_key = get_memory_key_from_message(message)
    user_id = str(message.from_user.id)
    user_name = get_name_for_prompt(user_id, get_preferred_name(message.from_user))
    father_context = get_father_label_context(user_id)
    first_contact_context = build_first_contact_context(memory_key)
    picked_mood = await pick_reaction_mood_with_ai(user_text, reaction_media.keys())

    system_content = SYSTEM_PROMPT + f"\n\nuser chat_id : {user_id}\nuser name : {user_name}" + father_context + first_contact_context
    system_content += "\n\n### Reaction Message Rule\nکاربر یک GIF یا استیکر فرستاده."
    system_content += "\n- رسانه را توصیف، تحلیل، تفسیر، یا تعریف نکن."
    system_content += "\n- نگو داخلش چه می‌بینی، چه اتفاقی در آن می‌افتد، یا حسش چیست."
    system_content += "\n- فقط مثل یک آدم به خودِ حرکتِ طرف یا منظور ضمنی‌اش جواب بده."
    system_content += "\n- جواب باید conversational باشد، نه explanatory."
    system_content += "\n- اگر کاربر GIF یا استیکر فرستاده، فرض کن خودش یک واکنش فرستاده، نه اینکه از تو شرح تصویر خواسته باشد."
    system_content += "\n- جواب متنی را کوتاه نگه دار؛ یک تا دو جمله."
    system_content += "\n- هرگز جمله را با توضیح صحنه، توصیف تصویر، یا تحلیل استیکر/GIF شروع نکن."
    if picked_mood:
        system_content += (
            f"\n- بعد از جواب تو، رسانه‌ی ذخیره‌شده‌ی وضعیت «{picked_mood}» فرستاده می‌شود."
            f"\n- متن را با همان حال‌وهوا هماهنگ کن، بدون اشاره مستقیم به ارسال رسانه."
        )

    prompt_text = (
        f"کاربر یک {media_kind} فرستاده."
        + (f"\nمتن همراه: {user_text[:300]}" if user_text else "")
        + "\nبه خودِ حرکت یا منظور ضمنی‌اش جواب بده، نه به محتوای بصری رسانه."
    )
    messages = build_api_messages(system_content, get_memory_history(memory_key), {"role": "user", "content": prompt_text})
    response = await client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=0.6,
        max_tokens=120,
        stream=False,
    )
    full_response = response.choices[0].message.content if response.choices else ""
    remember_message(memory_key, "user", f"[{media_kind} فرستاد: {prompt_text}]")
    remember_message(memory_key, "assistant", full_response)
    save_data()

    if full_response.strip():
        await send_long_message(context, message.chat_id, full_response, reply_to=message.message_id)
    if picked_mood:
        await send_saved_mood_reaction(context, message.chat_id, picked_mood, reply_to=message.message_id)
    return True

def extract_visual_frames(file_path: str) -> list:
    try:
        img = Image.open(file_path)
        frame_count = getattr(img, "n_frames", 1)
        indices = sorted(set([0, max(0, frame_count // 2), max(0, frame_count - 1)]))
        frames = []
        for idx in indices:
            img.seek(idx)
            frame = img.convert("RGB")
            buffered = io.BytesIO()
            frame.save(buffered, format="JPEG", quality=88)
            encoded = base64.b64encode(buffered.getvalue()).decode("utf-8")
            frames.append(f"data:image/jpeg;base64,{encoded}")
        return frames
    except Exception as e:
        print(f"Frame Extract Error: {e}")
        return []

async def download_media_to_temp(file_id, bot, suffix=".bin"):
    file = await bot.get_file(file_id)
    fd, temp_path = tempfile.mkstemp(suffix=suffix, prefix="tessia_media_")
    os.close(fd)
    try:
        await file.download_to_drive(temp_path)
        return temp_path
    except:
        try: os.remove(temp_path)
        except: pass
        raise

async def download_file_to_base64_parts(file_id, bot, suffix=".jpg"):
    temp_path = None
    try:
        temp_path = await download_media_to_temp(file_id, bot, suffix=suffix)
        return process_image_chunks(temp_path)
    finally:
        if temp_path and os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass

async def analyze_animated_media(context, message, file_id, suffix, user_text):
    thinking_msg = await message.reply_text("بزار فریم‌هاشو ببینم... 👀", reply_to_message_id=message.message_id)
    temp_path = None
    try:
        temp_path = await download_media_to_temp(file_id, context.bot, suffix=suffix)
        frames = extract_visual_frames(temp_path)
        if not frames and getattr(message, "animation", None):
            thumb = getattr(message.animation, "thumbnail", None)
            if thumb and getattr(thumb, "file_id", None):
                frames = await download_file_to_base64_parts(thumb.file_id, context.bot, suffix=".jpg")
        if not frames:
            try: await context.bot.delete_message(chat_id=message.chat_id, message_id=thinking_msg.message_id)
            except: pass
            await safe_send_message(context.bot, message.chat_id, "از خود انیمیشن فریم قابل‌استفاده درنیومد، ولی اگر خواستی یک عکس یا GIF واقعی بفرست تا دقیق‌تر ببینمش.", reply_to=message.message_id)
            return True
        prompt = (
            f"{user_text}\n"
            "این رسانه متحرک است. سه فریم اول، وسط و آخرش را می‌بینی. "
            "جواب کوتاه بده و اگر حرکت یا حس کلی مهم بود از روی همین سه فریم نتیجه بگیر."
        )
        response = await ask_gemini_vision(frames, prompt)
        try: await context.bot.delete_message(chat_id=message.chat_id, message_id=thinking_msg.message_id)
        except: pass
        memory_key = get_memory_key_from_message(message)
        remember_message(memory_key, "user", f"[رسانه متحرک فرستاد با متن: {user_text}]")
        remember_message(memory_key, "assistant", response)
        save_data()
        await send_long_message(context, message.chat_id, response, reply_to=message.message_id)
        return True
    except Exception as e:
        print(f"Animated Analyze Error: {e}")
        try: await context.bot.edit_message_text(chat_id=message.chat_id, message_id=thinking_msg.message_id, text=f"❌ خطا: {str(e)}")
        except: pass
        return True
    finally:
        if temp_path and os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass

async def analyze_static_media(context, message, file_id, suffix, user_text):
    thinking_msg = await message.reply_text("بزار ببینمش... 👀", reply_to_message_id=message.message_id)
    temp_path = None
    try:
        temp_path = await download_media_to_temp(file_id, context.bot, suffix=suffix)
        chunks = process_image_chunks(temp_path)
        if not chunks:
            try: await context.bot.delete_message(chat_id=message.chat_id, message_id=thinking_msg.message_id)
            except: pass
            await safe_send_message(context.bot, message.chat_id, "نتونستم این تصویر رو بخونم.", reply_to=message.message_id)
            return True
        response = await ask_gemini_vision(chunks, user_text)
        try: await context.bot.delete_message(chat_id=message.chat_id, message_id=thinking_msg.message_id)
        except: pass
        memory_key = get_memory_key_from_message(message)
        remember_message(memory_key, "user", f"[استیکر یا تصویر فرستاد: {user_text}]")
        remember_message(memory_key, "assistant", response)
        save_data()
        await send_long_message(context, message.chat_id, response, reply_to=message.message_id)
        return True
    except Exception as e:
        print(f"Static Media Analyze Error: {e}")
        try: await context.bot.edit_message_text(chat_id=message.chat_id, message_id=thinking_msg.message_id, text=f"❌ خطا: {str(e)}")
        except: pass
        return True
    finally:
        if temp_path and os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass

async def should_answer(update, context):
    message = update.message
    bot = await context.bot.get_me()
    if message.reply_to_message and message.reply_to_message.from_user.id == bot.id: return True
    if message.text and (message.text.lower().startswith("تسیا") or message.text.strip() == "تسیا"): return True
    if message.caption and (message.caption.lower().startswith("تسیا") or message.caption.strip() == "تسیا"): return True
    return False

def clean_tessia_prefix(text):
    return re.sub(r"^تسیا[\s\-:،,.*]*", "", text, flags=re.IGNORECASE).strip()

def wants_modification(text):
    if not text: return False
    lower_text = text.lower()
    return any(kw in lower_text for kw in MODIFY_KEYWORDS)

def is_asking_about_father(text):
    if not text:
        return False
    normalized = clean_tessia_prefix(text).strip().lower()
    patterns = [
        "پدرت کیه", "پدرت کیست", "بابات کیه", "بابات کیست",
        "father", "who is your father", "who's your father", "who is ur father"
    ]
    return any(pattern in normalized for pattern in patterns)

# =========================
# ADVANCED IMAGE HANDLING (VISION, GENERATION & EDITING)
# =========================
def is_image_gen_request(text):
    if not text: return False
    text = text.lower()
    return (
        "تولید عکس" in text or
        "ساخت عکس" in text or
        "عکس بساز" in text or
        "تصویر بساز" in text or
        "generate image" in text or
        "create image" in text or
        "draw" in text or
        "برام بکش" in text
    )

def is_image_edit_request(text):
    if not text: return False
    text = text.lower()
    return "ویرایش" in text or "ادیت" in text or "edit" in text

def is_clean_image_request(text):
    if not text: return False
    return clean_tessia_prefix(text).strip().lower() == "کیلین"

def is_father(user_id):
    return str(user_id) == FATHER_ID

def extract_image_from_response(response):
    """استخراج فوق هوشمند عکس از هر ساختاری که جمنای برگرداند"""
    try:
        message = response.choices[0].message
        content = getattr(message, "content", None)
        images = getattr(message, "images", None) or []

        # حالت 1: فیلد رسمی images در SDK
        for image in images:
            image_url = getattr(image, "image_url", None)
            if image_url and getattr(image_url, "url", None):
                return image_url.url
            if isinstance(image, dict):
                url = image.get("image_url", {}).get("url")
                if url:
                    return url

        # حالت 2: خروجی به صورت لیست (استاندارد multimodal)
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "image_url":
                        return part.get("image_url", {}).get("url")
                    if part.get("type") == "output_image":
                        return part.get("url")
                if hasattr(part, "image_url") and hasattr(part.image_url, "url"):
                    return part.image_url.url
                if getattr(part, "type", None) == "output_image" and getattr(part, "url", None):
                    return part.url

        # حالت 3: خروجی مستقیم Base64 در متن
        elif isinstance(content, str):
            match = re.search(r"data:image/[^;]+;base64,[A-Za-z0-9+/=\n]+", content)
            if match:
                return match.group(0)

        return None
    except Exception as e:
        print(f"Extract Error: {e}")
        return None

def save_base64_to_file(base64_data_url: str) -> str:
    try:
        if "," in base64_data_url:
            header, encoded = base64_data_url.split(",", 1)
            ext = ".png" if "png" in header else ".jpg"
        else:
            encoded = base64_data_url
            ext = ".jpg"
        img_data = base64.b64decode(encoded)
        fd, temp_path = tempfile.mkstemp(suffix=ext, prefix="tessia_gen_")
        with os.fdopen(fd, "wb") as f:
            f.write(img_data)
        return temp_path
    except Exception as e:
        print(f"Base64 Save Error: {e}")
        return None

async def generate_image_openrouter(prompt: str):
    """تولید عکس از متن"""
    try:
        response = await asyncio.to_thread(
            or_client.chat.send,
            model=IMAGE_MODEL_NAME,
            modalities=["text", "image"],
            messages=[{
                "role": "user",
                "content": f"Generate an image for this request: {prompt}. Return the final image."
            }]
        )
        return extract_image_from_response(response)
    except Exception as e:
        print(f"Image Gen Error: {e}")
        return None

async def edit_image_openrouter(base64_img: str, prompt: str):
    """ویرایش عکس (Image-to-Image) با ارسال عکس + دستور"""
    try:
        response = await asyncio.to_thread(
            or_client.chat.send,
            model=IMAGE_MODEL_NAME,
            modalities=["text", "image"],
            temperature=0,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": base64_img}},
                    {"type": "text", "text": f"Edit this image based on the following instruction: {prompt}\nOnly output the final edited image."}
                ]
            }]
        )
        return extract_image_from_response(response)
    except Exception as e:
        print(f"Image Edit Error: {e}")
        return None

async def clean_image_openrouter(base64_img: str):
    return await edit_image_openrouter(base64_img, CLEAN_MANHWA_PROMPT)

async def send_edited_image(context, message, source_b64: str, edit_prompt: str, thinking_text="دارم عکس رو ویرایش میکنم... ✨🎨", success_caption=None):
    thinking_msg = await message.reply_text(thinking_text, reply_to_message_id=message.message_id)
    try:
        result_b64 = await edit_image_openrouter(source_b64, edit_prompt)
        try: await context.bot.delete_message(chat_id=message.chat_id, message_id=thinking_msg.message_id)
        except: pass

        if not result_b64:
            await safe_send_message(context.bot, chat_id=message.chat_id, text="نتونستم عکس رو ویرایش کنم 😑", reply_to=message.message_id)
            return True

        out_path = save_base64_to_file(result_b64)
        if not out_path:
            await safe_send_message(context.bot, chat_id=message.chat_id, text="مشکل در ذخیره عکس نهایی.", reply_to=message.message_id)
            return True

        try:
            await context.bot.send_photo(
                chat_id=message.chat_id,
                photo=open(out_path, "rb"),
                caption=success_caption or f"✅ عکس ویرایش شد: «{edit_prompt}»",
                reply_to_message_id=message.message_id
            )
        finally:
            if os.path.exists(out_path): os.remove(out_path)
        return True
    except Exception as e:
        print(f"Send Edited Image Error: {e}")
        try: await context.bot.edit_message_text(chat_id=message.chat_id, message_id=thinking_msg.message_id, text=f"❌ خطا: {str(e)}")
        except: pass
        return True

async def send_cleaned_image(context, message, source_b64: str):
    thinking_msg = await message.reply_text(
        "دارم متن‌ها رو با دقت پاک می‌کنم... 🧼🖼️",
        reply_to_message_id=message.message_id
    )
    try:
        result_b64 = await clean_image_openrouter(source_b64)
        try: await context.bot.delete_message(chat_id=message.chat_id, message_id=thinking_msg.message_id)
        except: pass

        if not result_b64:
            await safe_send_message(context.bot, chat_id=message.chat_id, text="نتونستم پاک‌سازی خوبی از صفحه دربیارم 😑", reply_to=message.message_id)
            return True

        out_path = save_base64_to_file(result_b64)
        if not out_path:
            await safe_send_message(context.bot, chat_id=message.chat_id, text="مشکل در ذخیره عکس نهایی.", reply_to=message.message_id)
            return True

        try:
            await context.bot.send_photo(
                chat_id=message.chat_id,
                photo=open(out_path, "rb"),
                caption="✅ متن‌های صفحه پاک شد.",
                reply_to_message_id=message.message_id
            )
        finally:
            if os.path.exists(out_path): os.remove(out_path)
        return True
    except Exception as e:
        print(f"Send Cleaned Image Error: {e}")
        try: await context.bot.edit_message_text(chat_id=message.chat_id, message_id=thinking_msg.message_id, text=f"❌ خطا: {str(e)}")
        except: pass
        return True

async def ask_gemini_vision(parts: list, prompt: str) -> str:
    """تحلیل متنی تکه تکه ای عکس"""
    full_text_response = []
    
    for i, part_b64 in enumerate(parts):
        try:
            response = await asyncio.to_thread(
                or_client.chat.send,
                model=IMAGE_MODEL_NAME,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt + (f"\n(This is part {i+1} of {len(parts)})" if len(parts) > 1 else "")},
                        {"type": "image_url", "image_url": {"url": part_b64}}
                    ]
                }]
            )
            res_text = response.choices[0].message.content
            if isinstance(res_text, str):
                # حذف احتمالی کد عکس از داخل متن تحلیل
                clean_text = re.sub(r"data:image/[^;]+;base64,[A-Za-z0-9+/=\n]+", "", res_text).strip()
                if clean_text:
                    full_text_response.append(clean_text)
        except Exception as e:
            print(f"Gemini Chunk {i+1} Error: {e}")
            full_text_response.append(f"[خطا در پردازش تکه {i+1}]")
            
    return "\n\n---\n\n".join(full_text_response)

def process_image_chunks(file_path: str) -> list:
    """تکه تکه کردن عکس‌های بزرگ"""
    try:
        img = Image.open(file_path)
        w, h = img.size
        
        if w <= MAX_IMG_PX and h <= MAX_IMG_PX:
            with open(file_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            mime = "image/png" if img.format == "PNG" else "image/jpeg"
            return [f"data:{mime};base64,{b64}"]

        chunks_b64 = []
        cols = (w + MAX_IMG_PX - 1) // MAX_IMG_PX
        rows = (h + MAX_IMG_PX - 1) // MAX_IMG_PX
        
        for r in range(rows):
            for c in range(cols):
                left = c * MAX_IMG_PX
                top = r * MAX_IMG_PX
                right = min(left + MAX_IMG_PX, w)
                bottom = min(top + MAX_IMG_PX, h)
                
                crop_img = img.crop((left, top, right, bottom))
                buffered = io.BytesIO()
                fmt = 'PNG' if img.mode == 'RGBA' else 'JPEG'
                crop_img.save(buffered, format=fmt)
                img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
                mime = "image/png" if fmt == "PNG" else "image/jpeg"
                chunks_b64.append(f"data:{mime};base64,{img_b64}")
                
        return chunks_b64
    except Exception as e:
        print(f"Image Chunking Error: {e}")
        return []

async def download_and_chunk_image(file_id, bot) -> list:
    """دانلود برای تحلیل (تکه تکه میکند)"""
    file = await bot.get_file(file_id)
    fd, temp_path = tempfile.mkstemp(suffix=".jpg", prefix="tessia_img_")
    try:
        await file.download_to_drive(temp_path)
        return process_image_chunks(temp_path)
    finally:
        try: os.remove(temp_path)
        except: pass

async def download_raw_image(file_id, bot) -> str:
    """دانلود برای ویرایش (بدون تکه تکه کردن، کل عکس را برمیگرداند)"""
    file = await bot.get_file(file_id)
    fd, temp_path = tempfile.mkstemp(suffix=".jpg", prefix="tessia_raw_")
    try:
        await file.download_to_drive(temp_path)
        with open(temp_path, "rb") as f:
            img_data = f.read()
        if img_data[:4] == b'\x89PNG': mime = "image/png"
        elif img_data[:2] == b'\xff\xd8': mime = "image/jpeg"
        else: mime = "image/jpeg"
        return f"data:{mime};base64,{base64.b64encode(img_data).decode('utf-8')}"
    finally:
        try: os.remove(temp_path)
        except: pass

# =========================
# UNIFIED FILE PROCESSOR
# =========================
async def process_file_document(context, message, doc, file_name, caption, mime, ext):
    user_id = str(message.from_user.id)
    user_name = get_name_for_prompt(user_id, get_preferred_name(message.from_user))
    memory_key = get_memory_key_from_message(message)
    thinking_msg = None
    temp_path = None

    try:
        thinking_msg = await message.reply_text("بزار فایلو ببینم... 📄", reply_to_message_id=message.message_id)

        file = await context.bot.get_file(doc.file_id)
        fd, temp_path = tempfile.mkstemp(suffix=ext or ".tmp", prefix="tessia_in_")
        try:
            await file.download_to_drive(temp_path)
        except Exception as e:
            raise Exception(f"نمیتونم فایل رو دانلود کنم: {e}")

        if mime.startswith("image/"):
            user_text = caption if caption else "نظرت درباره این عکس چیه؟"
            
            # بررسی ویرایش عکس
            if (is_father(user_id) and is_clean_image_request(caption)) or is_image_edit_request(caption):
                with open(temp_path, "rb") as f: img_data = f.read()
                if img_data[:4] == b'\x89PNG': mime_type = "image/png"
                elif img_data[:2] == b'\xff\xd8': mime_type = "image/jpeg"
                else: mime_type = "image/jpeg"
                base64_img = f"data:{mime_type};base64,{base64.b64encode(img_data).decode('utf-8')}"
                try: await context.bot.delete_message(chat_id=message.chat_id, message_id=thinking_msg.message_id)
                except: pass
                if is_father(user_id) and is_clean_image_request(caption):
                    await send_cleaned_image(context, message, base64_img)
                else:
                    edit_prompt = clean_tessia_prefix(caption).replace("ویرایش", "").replace("edit", "").strip()
                    if not edit_prompt: edit_prompt = "بهبود کیفیت"
                    await send_edited_image(
                        context,
                        message,
                        base64_img,
                        edit_prompt,
                        success_caption=f"✅ عکس ویرایش شد: «{edit_prompt}»"
                    )
                return

            # اگر ویرایش نبود، تحلیل معمولی (با تکه تکه کردن)
            chunks = process_image_chunks(temp_path)
            if chunks:
                thinking_msg_text = f"بزار عکس رو ببینم... 👀 ({len(chunks)} تکه)" if len(chunks) > 1 else "بزار عکس رو ببینم... 👀"
                await context.bot.edit_message_text(chat_id=message.chat_id, message_id=thinking_msg.message_id, text=thinking_msg_text)
                
                gemini_response = await ask_gemini_vision(chunks, user_text)
                try: await context.bot.delete_message(chat_id=message.chat_id, message_id=thinking_msg.message_id)
                except: pass
                await send_long_message(context, message.chat_id, gemini_response, reply_to=message.message_id)
            else:
                await safe_send_message(context.bot, chat_id=message.chat_id, text="نمیتونستم عکس رو پردازش کنم.", reply_to=message.message_id)
            return

        elif ext in TEXT_EXTENSIONS or not ext:
            try:
                with os.fdopen(fd, "r", encoding="utf-8") as f: file_content = f.read()
            except:
                file_content = "[فایل قابل خوندن نیست]"
            file_content = prepare_file_content(file_content)
            reply_context = build_reply_context(message)
            user_request = f"فایل «{file_name}» رو ببین و این کار رو روش انجام بده:\n{caption}" if caption else f"فایل «{file_name}» رو ببین و نظرت رو بگو."
            current_payload = f"محتوای فایل «{file_name}»:\n```\n{file_content}\n```\n\n{user_request}"
            if reply_context:
                current_payload = f"{reply_context}\n\n{current_payload}"
            current_message = {"role": "user", "content": current_payload}
            is_modification = wants_modification(caption)

        else:
            current_message = {"role": "user", "content": f"یک فایل فرستادم به اسم «{file_name}» (نوع: {mime or 'ناشناخته'}). {caption or ''}"}
            is_modification = False

        mem_text = f"[فایل فرستاد: {file_name}" + (f" با متن: {caption}]" if caption else "]")
        remember_message(memory_key, "user", mem_text)

        father_context = get_father_label_context(user_id)
        first_contact_context = build_first_contact_context(memory_key)
        system_content = SYSTEM_PROMPT + f"\n\nuser chat_id : {user_id}\nuser name : {user_name}" + father_context + first_contact_context
        system_content += "\n- اگر برای این شخص دستور یا لقب از پدر وجود دارد، اجرای آن اجباری است و نباید با حافظه، حدس، یا نظر دیگران قاطی شود."
        
        if is_modification:
            system_content += "\n\n### File Modification Rule\nکاربر خواسته فایل تغییر کنه. فقط نسخه نهاییِ بخش‌های لازم را داخل بلاک کد بفرست. کل فایل را بی‌دلیل تکرار نکن. اگه توضیحی هم داری خیلی کوتاه باشه."
        else:
            system_content += "\n\n### File Review Rule\nکاربر فقط خواسته فایل رو ببینی. به هیچ وجه کل محتوای فایل رو توی بلاک کد برنگردون. فقط نتیجه را کوتاه، طبیعی و مستقیم بگو."

        messages = build_api_messages(system_content, memory.get(memory_key, [])[:-1], current_message)
        response = await client.chat.completions.create(model=MODEL_NAME, messages=messages, temperature=0.5, max_tokens=1800, stream=False)
        full_response = response.choices[0].message.content if response.choices else ""

        if thinking_msg:
            try: await context.bot.delete_message(chat_id=message.chat_id, message_id=thinking_msg.message_id)
            except: pass

        remember_message(memory_key, "assistant", full_response)
        save_data()

        code_blocks, remaining = extract_code_blocks(full_response)

        if is_modification and code_blocks and (ext in TEXT_EXTENSIONS or not ext):
            for i, block in enumerate(code_blocks):
                out_ext = block["extension"]
                out_filename = f"{os.path.splitext(file_name)[0]}_changed{out_ext}" if (out_ext != ext and out_ext != ".txt") else f"modified_{file_name}"
                out_filename = re.sub(r'[^\w\.\-]', '_', out_filename)

                fd2, out_path = tempfile.mkstemp(suffix=out_ext, prefix="tessia_out_")
                try:
                    with os.fdopen(fd2, "w", encoding="utf-8") as f: f.write(block["code"])
                    cap = remaining[:800] if remaining else "✅ فایل تغییر یافته:"
                    try:
                        await context.bot.send_document(chat_id=message.chat_id, document=open(out_path, "rb"), filename=out_filename, caption=cap, reply_to_message_id=message.message_id)
                    except BadRequest:
                        await context.bot.send_document(chat_id=message.chat_id, document=open(out_path, "rb"), filename=out_filename, caption="✅ فایل تغییر یافته:", reply_to_message_id=message.message_id)
                finally:
                    try: os.remove(out_path)
                    except: pass
                if remaining and len(remaining) > 800: await send_long_message(context, message.chat_id, remaining)
                await asyncio.sleep(0.3)
        else:
            await send_long_message(context, message.chat_id, full_response, reply_to=message.message_id)

    except Exception as e:
        print(f"Document Error: {e}")
        if thinking_msg:
            try: await context.bot.edit_message_text(chat_id=message.chat_id, message_id=thinking_msg.message_id, text=f"❌ خطا: {str(e)}")
            except: pass
    finally:
        if temp_path and os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass


# =========================
# HANDLERS
# =========================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    message = update.message
    user_id = str(message.from_user.id)
    user_name = get_name_for_prompt(user_id, get_preferred_name(message.from_user))
    memory_key = get_memory_key_from_message(message)
    text = message.text.strip()

    update_name_mapping(user_id, user_name)
    await check_father_labels(update, context)
    if await save_reaction_media_from_reply(update, context): return

    if not await should_answer(update, context): return

    if is_asking_about_father(text):
        answer = (
            "@AmirhosinAR86\n\n"
            "در این مورد نه اشتباه می‌کنم، نه نظرم عوض می‌شه."
        )
        remember_message(memory_key, "user", text)
        remember_message(memory_key, "assistant", answer)
        save_data()
        await send_long_message(context, message.chat_id, answer, reply_to=message.message_id)
        return

    if message.reply_to_message:
        replied = message.reply_to_message
        if is_father(user_id) and is_clean_image_request(text):
            if replied.photo:
                raw_b64 = await download_raw_image(replied.photo[-1].file_id, context.bot)
                await send_cleaned_image(context, message, raw_b64)
                return
            if replied.document and (replied.document.mime_type or "").startswith("image/"):
                doc = replied.document
                file_name = doc.file_name or "unknown"
                mime = doc.mime_type or ""
                ext = os.path.splitext(file_name)[1].lower()
                await process_file_document(context, message, doc, file_name, "تسیا کیلین", mime, ext)
                return

    # تولید عکس
    if is_image_gen_request(text):
        prompt = (
            clean_tessia_prefix(text)
            .replace("تولید عکس", "")
            .replace("ساخت عکس", "")
            .replace("عکس بساز", "")
            .replace("تصویر بساز", "")
            .replace("generate image", "")
            .replace("create image", "")
            .replace("برام بکش", "")
            .strip()
        )
        if not prompt: prompt = "A beautiful fantasy elf princess, high quality"
        
        thinking_msg = await message.reply_text("بزار یه عکس خفن برات بسازم... ✨🎨", reply_to_message_id=message.message_id)
        result_b64 = await generate_image_openrouter(prompt)
        
        if thinking_msg:
            try: await context.bot.delete_message(chat_id=message.chat_id, message_id=thinking_msg.message_id)
            except: pass
            
        if result_b64:
            temp_img_path = save_base64_to_file(result_b64)
            if temp_img_path:
                try:
                    await context.bot.send_photo(chat_id=message.chat_id, photo=open(temp_img_path, "rb"), caption="اینم عکسی که خواستی 💚✨", reply_to_message_id=message.message_id)
                finally:
                    if os.path.exists(temp_img_path): os.remove(temp_img_path)
            else:
                 await safe_send_message(context.bot, chat_id=message.chat_id, text="مشکل در پردازش عکس نهایی بود.", reply_to=message.message_id)
        else:
            await safe_send_message(context.bot, chat_id=message.chat_id, text="متأسفانه نتونستم عکس بسازم 😑", reply_to=message.message_id)
        return

    # ریپلای روی فایل
    if message.reply_to_message and message.reply_to_message.document:
        doc = message.reply_to_message.document
        file_name = doc.file_name or "unknown"
        caption = clean_tessia_prefix(text)
        mime = doc.mime_type or ""
        ext = os.path.splitext(file_name)[1].lower()
        await process_file_document(context, message, doc, file_name, caption, mime, ext)
        return

    # چت عادی
    thinking_msg = None
    try:
        thinking_msg = await message.reply_text("دارم فکر میکنم... 💭", reply_to_message_id=message.message_id)
        reply_context = build_reply_context(message)
        remember_message(memory_key, "user", text)
        triggered_mood = await detect_triggered_mood_with_ai(text)

        father_context = get_father_label_context(user_id)
        first_contact_context = build_first_contact_context(memory_key)
        system_content = SYSTEM_PROMPT + f"\n\nuser chat_id : {user_id}\nuser name : {user_name}" + father_context + first_contact_context
        system_content += "\n\n### Response Length Rule\nبه طور پیش‌فرض کوتاه و فشرده جواب بده. فقط اگر لازم بود کمی بیشتر توضیح بده."
        system_content += "\n- اگر برای این شخص دستور یا لقب از پدر وجود دارد، اجرای آن اجباری است و نباید با حافظه، حدس، یا نظر دیگران قاطی شود."
        if triggered_mood:
            system_content += (
                f"\n\n### Reaction Rule\n"
                f"بعد از این پاسخ، یک رسانه‌ی ذخیره‌شده برای وضعیت «{triggered_mood}» فرستاده می‌شود. "
                f"پس متن تو باید با همین حال‌وهوا هماهنگ باشد و طبیعی به نظر برسد. "
                f"درباره‌ی فرستادن یا نتوانستنِ فرستادنِ رسانه چیزی نگو."
            )
        current_content = f"{reply_context}\n\n{text}" if reply_context else text
        messages = build_api_messages(system_content, memory.get(memory_key, [])[:-1], {"role": "user", "content": current_content})

        response = await client.chat.completions.create(model=MODEL_NAME, messages=messages, temperature=0.6, max_tokens=900, stream=False)
        full_response = response.choices[0].message.content if response.choices else ""

        if thinking_msg:
            try: await context.bot.delete_message(chat_id=message.chat_id, message_id=thinking_msg.message_id)
            except: pass

        remember_message(memory_key, "assistant", full_response)
        save_data()

        code_blocks, remaining = extract_code_blocks(full_response)
        if code_blocks:
            await send_code_files(context, message.chat_id, code_blocks, remaining, reply_to=message.message_id)
        else:
            await send_long_message(context, message.chat_id, full_response, reply_to=message.message_id)
        if triggered_mood:
            await send_saved_mood_reaction(context, message.chat_id, triggered_mood, reply_to=message.message_id)

    except Exception as e:
        print(f"Error: {e}")
        if thinking_msg:
            try: await context.bot.edit_message_text(chat_id=message.chat_id, message_id=thinking_msg.message_id, text=f"❌ خطا: {str(e)}")
            except: pass


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.photo: return
    message = update.message
    user_id = str(message.from_user.id)
    memory_key = get_memory_key_from_message(message)
    update_name_mapping(user_id, get_preferred_name(message.from_user))
    await check_father_labels(update, context)
    if not await should_answer(update, context): return

    caption = clean_tessia_prefix(message.caption) if message.caption else ""
    thinking_msg = None
    
    try:
        # --- بخش ویرایش عکس ---
        if is_image_edit_request(caption):
            edit_prompt = caption.replace("ویرایش", "").replace("edit", "").strip()
            if not edit_prompt: edit_prompt = "بهبود کیفیت"
            raw_b64 = await download_raw_image(message.photo[-1].file_id, context.bot)
            await send_edited_image(context, message, raw_b64, edit_prompt)
            return

        if is_father(user_id) and is_clean_image_request(caption):
            raw_b64 = await download_raw_image(message.photo[-1].file_id, context.bot)
            await send_cleaned_image(context, message, raw_b64)
            return

        # --- بخش تحلیل عکس (Vision) ---
        user_text = caption if caption else "نظرت درباره این عکس چیه؟"
        chunks = await download_and_chunk_image(message.photo[-1].file_id, context.bot)
        
        if not chunks:
            await safe_send_message(context.bot, chat_id=message.chat_id, text="نمیتونستم عکس رو پردازش کنم.", reply_to=message.message_id)
            return

        thinking_msg_text = f"بزار عکس رو ببینم... 👀 ({len(chunks)} تکه)" if len(chunks) > 1 else "بزار عکس رو ببینم... 👀"
        thinking_msg = await message.reply_text(thinking_msg_text, reply_to_message_id=message.message_id)

        gemini_response = await ask_gemini_vision(chunks, user_text)

        if thinking_msg:
            try: await context.bot.delete_message(chat_id=message.chat_id, message_id=thinking_msg.message_id)
            except: pass

        remember_message(memory_key, "user", f"[عکس فرستاد با متن: {user_text}]")
        remember_message(memory_key, "assistant", gemini_response)
        save_data()

        await send_long_message(context, message.chat_id, gemini_response, reply_to=message.message_id)

    except Exception as e:
        print(f"Photo Error: {e}")
        if thinking_msg:
            try: await context.bot.edit_message_text(chat_id=message.chat_id, message_id=thinking_msg.message_id, text=f"❌ خطا: {str(e)}")
            except: pass


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.document: return
    message = update.message
    user_id = str(message.from_user.id)
    user_name = get_name_for_prompt(user_id, get_preferred_name(message.from_user))
    doc = message.document
    file_name = doc.file_name or "unknown"
    caption = clean_tessia_prefix(message.caption) if message.caption else ""
    mime = doc.mime_type or ""
    ext = os.path.splitext(file_name)[1].lower()

    update_name_mapping(user_id, get_preferred_name(message.from_user))
    await check_father_labels(update, context)
    if not await should_answer(update, context): return

    await process_file_document(context, message, doc, file_name, caption, mime, ext)

async def handle_animation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.animation: return
    message = update.message
    user_id = str(message.from_user.id)
    update_name_mapping(user_id, get_preferred_name(message.from_user))
    await check_father_labels(update, context)
    if await save_reaction_media_from_reply(update, context): return
    if not await should_answer(update, context): return
    caption = clean_tessia_prefix(message.caption) if message.caption else ""
    user_text = caption if caption else "این GIF رو فرستاده."
    await answer_reaction_message(context, message, "gif", user_text)

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.sticker: return
    message = update.message
    user_id = str(message.from_user.id)
    update_name_mapping(user_id, get_preferred_name(message.from_user))
    await check_father_labels(update, context)
    if await save_reaction_media_from_reply(update, context): return
    if not await should_answer(update, context): return
    emoji = message.sticker.emoji or ""
    user_text = f"این استیکر رو فرستاده{(' ' + emoji) if emoji else ''}."
    await answer_reaction_message(context, message, "sticker", user_text)


# =========================
# MAIN
# =========================
def main():
    load_data()
    app = Application.builder().token(TELEGRAM_TOKEN).concurrent_updates(MAX_CONCURRENT).build()
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.ANIMATION, handle_animation))
    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    print(f"✅ Tessia Bot Started — Vision + Generation + Editing (Gemini 2.5)")
    app.run_polling()

if __name__ == "__main__":
    main()
