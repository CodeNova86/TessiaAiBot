import asyncio

from tessia_bot.bot import update_name_mapping
from tessia_bot.config import (
    FATHER_AUTO_REPLY_ENABLED,
    MODEL_NAME,
    TELETHON_API_HASH,
    TELETHON_API_ID,
    TELETHON_SESSION_NAME,
    client,
)
from tessia_bot.father_control import get_persona_note, is_sender_allowed, load_father_whitelist
from tessia_bot.logging_utils import get_logger
from tessia_bot.state import (
    is_rate_limited,
    load_data,
    log_error,
    update_user_language,
)

logger = get_logger("father_gateway")


FATHER_DM_SYSTEM_PROMPT = """
You are replying from the father's personal Telegram account.

Rules:
- Base your style primarily on the recent conversation between these two people.
- Mimic the existing relationship vibe from the recent chat history.
- Only handle lightweight personal conversation.
- Good topics: greeting, checking in, short personal chat, simple coordination, basic courtesy.
- Do not write code.
- Do not give technical help.
- Do not analyze files.
- Do not act like a general assistant.
- If the message asks for coding, technical work, file analysis, complex reasoning, or anything business-like, reply briefly and naturally that now is not a good time and keep it personal.
- Keep replies short.
- Keep tone natural, human, warm, and casual.
- Reply in Persian unless the recent conversation is clearly in another language.
- Never mention AI, policy, or system rules.
""".strip()


async def build_recent_chat_messages(client_user, event, incoming_text: str, persona_note: str = ""):
    me = await client_user.get_me()
    history_items = []
    async for msg in client_user.iter_messages(event.chat_id, limit=50):
        text = (getattr(msg, "raw_text", None) or "").strip()
        if not text:
            continue
        sender_id = getattr(msg, "sender_id", None)
        role = "assistant" if sender_id == me.id else "user"
        history_items.append({"role": role, "content": text[:1500]})
    history_items.reverse()
    history_items.append({"role": "user", "content": incoming_text[:1500]})
    system_prompt = FATHER_DM_SYSTEM_PROMPT
    if persona_note:
        system_prompt += f"\n\nPersona note for this contact:\n{persona_note[:1200]}"
    return [{"role": "system", "content": system_prompt}] + history_items


async def generate_father_reply(client_user, user_id: str, sender_name: str, username: str, text: str, event) -> str:
    update_name_mapping(user_id, sender_name)
    update_user_language(user_id, text)
    persona_note = get_persona_note(username or user_id)
    messages = await build_recent_chat_messages(client_user, event, text, persona_note=persona_note)
    response = await client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=0.5,
        max_tokens=220,
        stream=False,
    )
    reply_text = (response.choices[0].message.content or "").strip() if response.choices else ""
    return reply_text


async def main():
    if not FATHER_AUTO_REPLY_ENABLED:
        logger.info("Father auto-reply is disabled. Set FATHER_AUTO_REPLY_ENABLED=true to run.")
        return
    if not TELETHON_API_ID or not TELETHON_API_HASH:
        logger.error("Missing TELETHON_API_ID or TELETHON_API_HASH.")
        return

    try:
        from telethon import TelegramClient, events
    except ImportError:
        logger.error("Telethon is not installed. Run: pip install telethon")
        return

    load_data()
    client_user = TelegramClient(TELETHON_SESSION_NAME, int(TELETHON_API_ID), TELETHON_API_HASH)
    startup_whitelist = load_father_whitelist()
    logger.info(
        "Starting father gateway with session=%s, whitelist_ids=%d, whitelist_usernames=%d",
        TELETHON_SESSION_NAME,
        len(startup_whitelist.get("allowed_user_ids", [])),
        len(startup_whitelist.get("allowed_usernames", [])),
    )

    @client_user.on(events.NewMessage(incoming=True))
    async def handle_new_message(event):
        try:
            if not event.is_private:
                return
            sender = await event.get_sender()
            if sender is None or getattr(sender, "bot", False):
                return

            sender_id = str(sender.id)
            username = getattr(sender, "username", "") or ""
            sender_name = (getattr(sender, "first_name", "") or username or sender_id).strip()
            whitelist = load_father_whitelist()
            if not is_sender_allowed(sender_id, username, whitelist):
                logger.info("Ignored private message from non-whitelisted sender_id=%s username=%s", sender_id, username)
                return

            text = (event.raw_text or "").strip()
            if not text:
                return

            rate_limited_for = is_rate_limited(sender_id)
            if rate_limited_for:
                logger.info("Rate limited sender_id=%s for %ss", sender_id, rate_limited_for)
                return

            me = await client_user.get_me()
            if event.out or (event.message and getattr(event.message, "from_id", None) == getattr(me, "id", None)):
                return

            reply_text = await generate_father_reply(client_user, sender_id, sender_name, username, text, event)
            if reply_text:
                await event.reply(reply_text)
                logger.info("Replied to sender_id=%s chat_id=%s text_len=%d", sender_id, event.chat_id, len(reply_text))
        except Exception as exc:
            log_error("father_gateway", exc)

    await client_user.start()
    logger.info("Father gateway started.")
    await client_user.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
