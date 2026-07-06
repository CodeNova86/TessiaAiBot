import os

from openai import AsyncOpenAI

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8825026272:AAGUstE-T7DHTrxA9JzQXfuuflfYQo7voaM")
TEXT_API_KEY = "sk-afc2375580623837-kmaznl-cee6358f"
BASE_URL = "http://204.10.192.34:20128/v1"
MODEL_NAME = os.getenv("MODEL_NAME", "AllModels")

OPENROUTER_API_KEY = TEXT_API_KEY
OPENROUTER_BASE_URL = BASE_URL
IMAGE_MODEL_NAME = os.getenv("IMAGE_MODEL_NAME", "google/gemini-2.5-flash-image")
TRANSCRIBE_MODEL = os.getenv("TRANSCRIBE_MODEL", "openai/whisper-large-v3-turbo")
EDGE_TTS_VOICE = os.getenv("EDGE_TTS_VOICE", "fa-IR-DilaraNeural")

DATA_FILE = "tessia_data.json"
AUTOMATION_RULES_FILE = "tessia_automation_rules.json"
FATHER_WHITELIST_FILE = "father_whitelist.json"
FATHER_PERSONA_FILE = "father_persona.json"
FATHER_GATEWAY_STATE_FILE = "father_gateway_state.json"
FATHER_LEARNING_FILE = "father_learning.json"
LOG_FILE = "tessia_bot.log"
FATHER_ID = "1548469285"
MAX_CONCURRENT = 5
MAX_IMG_PX = 2000
SUMMARY_TRIGGER_MESSAGES = 12
SUMMARY_KEEP_RECENT = 6
FILE_INDEX_SNIPPET_CHARS = 2500
RATE_LIMIT_WINDOW = 20
RATE_LIMIT_BURST = 8
RATE_LIMIT_MUTE_SECONDS = 45
MAX_MEMORY_MESSAGES = 7
MAX_FILE_CHARS = 6000
MAX_REPLY_CONTEXT_CHARS = 1200
MAX_USER_NAME_CHARS = 32
FATHER_AUTO_REPLY_ENABLED = os.getenv("FATHER_AUTO_REPLY_ENABLED", "true").strip().lower() == "true"
TELETHON_API_ID = 24781074
TELETHON_API_HASH = "15f8e891f97681f4deeb690d0e4116b3"
TELETHON_SESSION_NAME = os.getenv("TELETHON_SESSION_NAME", "father_session").strip() or "father_session"

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

client = AsyncOpenAI(api_key=TEXT_API_KEY, base_url=BASE_URL)
