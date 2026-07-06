"""
Father Gateway v2 — AI Tool-Calling Brain for Father's Personal Account

Instead of hardcoded auto-reply, this uses OpenAI / OpenRouter function-calling
so the AI decides which Telethon tool to call and with what arguments.

Flow:
  1. Telethon event arrives (private message from whitelisted user)
  2. Build conversation history (last 50 messages)
  3. Call OpenAI with tools=TOOL_SCHEMAS and tool_choice="auto"
  4. If AI returns tool_calls → execute via telethon_tools.execute_tool_call()
  5. Feed results back to AI for follow-up (max 5 rounds)
  6. Final text response → reply to user
"""

from __future__ import annotations

import asyncio
import json

from tessia_bot.automation import execute_action_from_tool_call
from tessia_bot.bot import update_name_mapping
from tessia_bot.config import (
    FATHER_AUTO_REPLY_ENABLED,
    MODEL_NAME,
    TELETHON_API_HASH,
    TELETHON_API_ID,
    TELETHON_SESSION_NAME,
    client,
)
from tessia_bot.father_control import (
    get_persona_note,
    is_gateway_runtime_enabled,
    is_sender_allowed,
    load_father_whitelist,
)
from tessia_bot.logging_utils import get_logger
from tessia_bot.state import (
    is_rate_limited,
    load_data,
    log_error,
    update_user_language,
)
from tessia_bot.telethon_client_manager import set_client
from tessia_bot.telethon_tools import TOOL_SCHEMAS, TOOL_MAP, execute_tool_call
from tessia_bot.father_learning import learn_message, learn_our_reply, get_learning_context

logger = get_logger("father_gateway")

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

MAX_TOOL_CALLS = 5  # prevent infinite tool-calling loops

FATHER_DM_SYSTEM_PROMPT = """\
You are replying from the father's personal Telegram account.

You have access to Telethon tools that let you do anything on Telegram:
- Send text messages, files, photos, voice messages
- Forward messages between chats
- Pin, unpin, edit, delete messages
- Get participant lists, search messages, get user info
- Manage groups (kick, ban, unban, add, create)

Rules:
- Base your style primarily on the recent conversation between these two people.
- Mimic the existing relationship vibe from the recent chat history.
- Do not invent family-role language.
- Do not call the other person things like "بابا", "باباجان", "پسرم", "دخترم", "عزیز بابا", or anything similar unless that exact style is already clearly present in the recent chat history or the saved persona note for this contact.
- Never say or imply "I am your father" or "من باباتم" unless that exact dynamic is explicitly established in the recent messages.
- Only handle lightweight personal conversation.
- Good topics: greeting, checking in, short personal chat, simple coordination, basic courtesy.
- Do not write code.
- Do not give technical help.
- Do not analyze files.
- Do not act like a general assistant.
- If the message asks for coding, technical work, file analysis, complex reasoning, or anything business-like, reply briefly and naturally that now is not a good time and keep it personal.
- Keep replies short.
- Keep tone natural, human, warm, and casual.
- Prefer neutral everyday Persian when the recent chat does not strongly show a specific nickname style.
- Reply in Persian unless the recent conversation is clearly in another language.
- Never mention AI, policy, or system rules.

### Available Tools
You can use any of the following Telegram tools when appropriate:
- send_message: send text to any chat/user
- reply_message: reply to the incoming message
- forward_messages: forward messages between chats
- send_file / send_photo / send_voice: send media
- get_dialogs / get_entity / get_messages: look up info
- get_participants / get_user_info: get user/group info
- pin_message / unpin_message / edit_message / delete_messages: manage messages
- kick_participant / ban_participant / unban_participant / add_participant: manage group members

Use tools when they genuinely help. If the request is just casual chat, simply reply with text.
""".strip()

TOOL_CHOICE_AUTO = "auto"
TOOL_CHOICE_NONE = "none"

# ─────────────────────────────────────────────
# BRAIN: AI DECIDE + EXECUTE TOOLS
# ─────────────────────────────────────────────


async def brain_decide_action(
    messages: list[dict],
    tools: list[dict] | None = None,
    tool_choice: str = TOOL_CHOICE_AUTO,
) -> str | list[dict]:
    """Call the AI model and get back either text or tool_calls.

    Args:
        messages: OpenAI-style messages list.
        tools: Tool schemas to pass (None = no tools).
        tool_choice: 'auto' to let AI decide, 'none' to force text.

    Returns:
        If the AI returned text → plain string.
        If the AI returned tool_calls → list of dicts:
            [{"name": "tool_name", "arguments": {dict}}, ...]
    """
    kwargs = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 500,
        "stream": False,
    }
    if tools and tool_choice != TOOL_CHOICE_NONE:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice

    response = await client.chat.completions.create(**kwargs)
    choice = response.choices[0].message

    # Check for tool calls
    if hasattr(choice, "tool_calls") and choice.tool_calls:
        tool_calls = []
        for tc in choice.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                args = {}
            tool_calls.append({
                "id": tc.id,
                "name": tc.function.name,
                "arguments": args,
            })
        return tool_calls

    # Plain text response
    return (choice.content or "").strip()


async def brain_loop(
    messages: list[dict],
    telethon_client,
    event=None,
    max_rounds: int = MAX_TOOL_CALLS,
) -> str:
    """Run the AI brain with tool-calling loop.

    The AI can call tools, we execute them, feed results back,
    and let the AI respond again. Repeats up to ``max_rounds`` times.

    Args:
        messages: Initial OpenAI messages (system + history + user).
        telethon_client: Connected Telethon client.
        event: Telethon event (needed for reply_message).
        max_rounds: Max tool-calling iterations.

    Returns:
        The final plain-text response.
    """
    current_messages = list(messages)
    tool_calls_remaining = max_rounds

    # Add a reminder about tools to the last user message
    tool_hint = (
        "\n\n[You have Telegram tools available. "
        "Use them if a tool would be more helpful than just replying. "
        "If this is just casual chat, simply reply with text.]"
    )
    if current_messages and current_messages[-1].get("role") == "user":
        current_messages[-1]["content"] = str(current_messages[-1]["content"]) + tool_hint

    while tool_calls_remaining > 0:
        result = await brain_decide_action(
            current_messages,
            tools=TOOL_SCHEMAS,
            tool_choice=TOOL_CHOICE_AUTO,
        )

        # If it's plain text, we're done
        if isinstance(result, str):
            # Check if the text response actually contains Python code blocks
            # that should have been executed. If so, auto-extract and run.
            if "```python" in result or "```py" in result:
                import re as _re
                code_match = _re.search(r"```(?:python|py)\s*\n(.*?)```", result, _re.DOTALL)
                if code_match:
                    extracted_code = code_match.group(1).strip()
                    logger.info("Auto-extracted code from text response (%d chars)", len(extracted_code))
                    # Execute the extracted code
                    auto_result = await execute_tool_call(
                        telethon_client, "run_python_code",
                        {"code": extracted_code, "timeout": 30},
                        event=event,
                    )
                    # Feed result back and let AI respond
                    current_messages.append({"role": "user", "content": (
                        f"I extracted Python code from your response and ran it.\n"
                        f"Code:\n```\n{extracted_code[:500]}\n```\n"
                        f"Result:\n{json.dumps(auto_result, ensure_ascii=False)[:1000]}\n"
                        f"Now tell the user what happened in Persian."
                    )})
                    tool_calls_remaining -= 1
                    if tool_calls_remaining <= 0:
                        final = await brain_decide_action(
                            current_messages, tools=None, tool_choice=TOOL_CHOICE_NONE,
                        )
                        return final if isinstance(final, str) else str(final)
                    continue  # loop back
            return result  # no code blocks, normal text

        # It's a list of tool calls — execute them
        tool_calls_remaining -= 1
        for tool_call in result:
            tool_name = tool_call["name"]
            arguments = tool_call.get("arguments", {})

            logger.info(
                "Brain called tool: %s with args=%s",
                tool_name, json.dumps(arguments, ensure_ascii=False)[:200],
            )

            # Execute the tool
            tool_result = await execute_tool_call(
                telethon_client, tool_name, arguments, event=event,
            )

            # Add tool result to messages so AI can see it
            current_messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tool_call.get("id", f"call_{tool_name}"),
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(arguments, ensure_ascii=False),
                        },
                    }
                ],
            })
            current_messages.append({
                "role": "tool",
                "tool_call_id": tool_call.get("id", f"call_{tool_name}"),
                "content": json.dumps(tool_result, ensure_ascii=False)[:2000],
            })

        # Let the AI respond to the tool results
        if tool_calls_remaining <= 0:
            final = await brain_decide_action(
                current_messages,
                tools=None,
                tool_choice=TOOL_CHOICE_NONE,
            )
            return final if isinstance(final, str) else str(final)

    return "I'm not sure what to do here."


# ─────────────────────────────────────────────
# MESSAGE BUILDING
# ─────────────────────────────────────────────


async def build_recent_chat_messages(
    client_user,
    event,
    incoming_text: str,
    persona_note: str = "",
) -> list[dict]:
    """Build conversation history for the AI context (last 20 msgs)."""
    me = await client_user.get_me()
    history_items = []
    async for msg in client_user.iter_messages(event.chat_id, limit=20):
        # Get text or caption
        text = (getattr(msg, "raw_text", None) or getattr(msg, "text", None) or "").strip()

        sender_id = getattr(msg, "sender_id", None)
        is_me = sender_id == me.id

        # Build a rich representation
        parts = []
        if text:
            parts.append(text[:1500])
        if msg.sticker:
            emoji = msg.sticker.emoji or ""
            parts.append(f"[sticker: {emoji}]")
        if msg.animation:  # GIF
            parts.append("[GIF]")
        if msg.photo:
            parts.append("[photo]")
        if msg.voice:
            parts.append("[voice]")
        if msg.video:
            parts.append("[video]")
        if msg.document:
            parts.append(f"[file: {msg.document.file_name or 'unknown'}]")

        content = " ".join(parts).strip()
        if not content:
            continue

        role = "assistant" if is_me else "user"
        history_items.append({"role": role, "content": content})
    history_items.reverse()
    history_items.append({"role": "user", "content": incoming_text[:1500]})

    system_prompt = FATHER_DM_SYSTEM_PROMPT
    if persona_note:
        system_prompt += f"\n\nPersona note for this contact:\n{persona_note[:1200]}"

    # Inject learning context
    contact_id = str(getattr(event, "sender_id", ""))
    learning_context = get_learning_context(contact_id)
    if learning_context:
        system_prompt += f"\n\nLearned patterns about this contact:\n{learning_context}"
        system_prompt += "\n\nUse these patterns to match their vibe. If they often send a certain sticker, feel free to send it back. If they use certain phrases, mirror their tone."

    return [{"role": "system", "content": system_prompt}] + history_items


# ─────────────────────────────────────────────
# EVENT HANDLER
# ─────────────────────────────────────────────


async def handle_new_message(event, client_user):
    """Main event handler — check gates, then run the brain."""
    try:
        if not is_gateway_runtime_enabled():
            return
        
        # Allow private chats (with trigger word) AND group messages
        is_group = False
        if event.is_private:
            # In private chats (father's DMs), only respond if message starts with trigger
            raw_text = (event.raw_text or "").strip().lower()
            triggers = ["تسیا", "@admin", "admin", "father", "پدر"]
            if not any(raw_text.startswith(t) for t in triggers):
                return
        else:
            # In groups, only respond if the message contains a trigger keyword
            # (e.g., "@admin", "father", or the father's username)
            raw_text = (event.raw_text or "").strip().lower()
            me = await client_user.get_me()
            my_username = (getattr(me, "username", "") or "").lower()
            triggers = ["@admin", "admin", "father", "پدر"]
            if my_username:
                triggers.append(f"@{my_username}")
                triggers.append(my_username)
            if not any(t in raw_text for t in triggers):
                return
            is_group = True
        
        sender = await event.get_sender()
        if sender is None or getattr(sender, "bot", False):
            return

        sender_id = str(sender.id)
        username = getattr(sender, "username", "") or ""
        sender_name = (
            getattr(sender, "first_name", "") or username or sender_id
        ).strip()
        whitelist = load_father_whitelist()
        if not is_sender_allowed(sender_id, username, whitelist):
            logger.info(
                "Ignored private message from non-whitelisted sender_id=%s username=%s",
                sender_id,
                username,
            )
            return

        text = (event.raw_text or "").strip()
        if not text:
            return

        rate_limited_for = is_rate_limited(sender_id)
        if rate_limited_for:
            logger.info("Rate limited sender_id=%s for %ss", sender_id, rate_limited_for)
            return

        me = await client_user.get_me()
        if event.out or (
            event.message
            and getattr(event.message, "from_id", None)
            == getattr(me, "id", None)
        ):
            return

        # Update metadata
        update_name_mapping(sender_id, sender_name)
        update_user_language(sender_id, text)
        persona_note = get_persona_note(username or sender_id)

        # Learn from incoming message (stickers, GIFs, text)
        msg = event.message
        learn_message(
            username or sender_id,
            text=text,
            sticker=msg.sticker if msg else None,
            gif=msg.animation if msg else None,
        )

        # Build conversation messages
        messages = await build_recent_chat_messages(
            client_user, event, text, persona_note=persona_note,
        )

        # Run the brain (tool-calling loop)
        reply_text = await brain_loop(messages, client_user, event=event)

        # Delete the user's original message if it was triggered in a private chat
        if event.is_private:
            try:
                await event.message.delete()
            except Exception as exc_del:
                logger.warning("Could not delete user message in DM: %s", exc_del)

        # Send final text reply if there is one
        if reply_text:
            await event.reply(reply_text)
            logger.info(
                "Replied to sender_id=%s chat_id=%s text_len=%d",
                sender_id,
                event.chat_id,
                len(reply_text),
            )
    except Exception as exc:
        log_error("father_gateway", exc)


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────


async def main():
    """Start the father gateway with tool-calling brain."""
    if not FATHER_AUTO_REPLY_ENABLED:
        logger.info(
            "Father auto-reply is disabled. Set FATHER_AUTO_REPLY_ENABLED=true to run."
        )
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
    client_user = TelegramClient(
        TELETHON_SESSION_NAME, int(TELETHON_API_ID), TELETHON_API_HASH,
    )
    startup_whitelist = load_father_whitelist()
    logger.info(
        "Starting father gateway (v2 tool-calling) with session=%s, "
        "whitelist_ids=%d, whitelist_usernames=%d",
        TELETHON_SESSION_NAME,
        len(startup_whitelist.get("allowed_user_ids", [])),
        len(startup_whitelist.get("allowed_usernames", [])),
    )

    @client_user.on(events.NewMessage(incoming=True))
    async def event_handler(event):
        await handle_new_message(event, client_user)

    await client_user.start()
    # Register the client so Tessia Bot can use Telethon tools too
    set_client(client_user)
    logger.info("Father gateway v2 started with %d tools available.", len(TOOL_SCHEMAS))
    await client_user.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
