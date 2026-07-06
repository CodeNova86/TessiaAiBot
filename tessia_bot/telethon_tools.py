"""
Telethon Tool Layer — 20+ wrapped Telethon API functions
with OpenAI function-calling schemas for AI-driven tool execution.

Each tool:
  - Is an async function taking (client, ...) where client is a TelegramClient
  - Has typed parameters with descriptive names
  - Handles errors gracefully, logs them
  - Has a matching schema in TOOL_SCHEMAS

Usage:
  from tessia_bot.telethon_tools import TOOL_MAP, TOOL_SCHEMAS
  tool_fn = TOOL_MAP["send_message"]
  result = await tool_fn(client, chat_id="123", text="hello")
"""

from __future__ import annotations

import json
import logging
import os
import traceback
from typing import Any

from telethon import TelegramClient
from telethon.errors import (
    ChatAdminRequiredError,
    FloodWaitError,
    UserNotParticipantError,
    UsernameNotOccupiedError,
)
from telethon.tl.functions.messages import AddChatUserRequest, EditChatTitleRequest
from telethon.tl.types import InputPeerEmpty

logger = logging.getLogger("tessia.telethon_tools")

# ─────────────────────────────────────────────
# 1. MESSAGE TOOLS
# ─────────────────────────────────────────────


async def send_message(
    client: TelegramClient,
    chat_id: str | int,
    text: str,
    parse_mode: str = "markdown",
) -> dict:
    """Send a text message to a chat or user.

    Args:
        client: Telethon client instance.
        chat_id: Target chat ID, username (@user), or phone number.
        text: Message content.
        parse_mode: One of 'markdown', 'html', or empty string for plain.

    Returns:
        dict with 'message_id' and 'chat_id' on success.
    """
    try:
        entity = await client.get_input_entity(chat_id)
        msg = await client.send_message(entity, text, parse_mode=parse_mode or None)
        logger.info("send_message: chat_id=%s msg_id=%s", chat_id, msg.id)
        return {"success": True, "message_id": msg.id, "chat_id": str(msg.chat_id)}
    except FloodWaitError as e:
        logger.warning("send_message flood wait: %ds", e.seconds)
        return {"success": False, "error": f"Flood wait {e.seconds}s"}
    except Exception as e:
        logger.error("send_message error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


async def reply_message(
    client: TelegramClient,
    event,
    text: str,
    parse_mode: str = "markdown",
) -> dict:
    """Reply to an existing message event.

    Args:
        client: Telethon client instance.
        event: The NewMessage event to reply to.
        text: Reply content.
        parse_mode: One of 'markdown', 'html', or ''.

    Returns:
        dict with 'message_id' on success.
    """
    try:
        msg = await event.reply(text, parse_mode=parse_mode or None)
        logger.info("reply_message: msg_id=%s", msg.id)
        return {"success": True, "message_id": msg.id}
    except FloodWaitError as e:
        return {"success": False, "error": f"Flood wait {e.seconds}s"}
    except Exception as e:
        logger.error("reply_message error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


async def forward_messages(
    client: TelegramClient,
    to_chat: str | int,
    from_chat: str | int,
    message_ids: list[int],
) -> dict:
    """Forward messages from one chat to another.

    Args:
        client: Telethon client instance.
        to_chat: Destination chat ID or username.
        from_chat: Source chat ID or username.
        message_ids: List of message IDs to forward.

    Returns:
        dict with 'count' of forwarded messages.
    """
    try:
        to_entity = await client.get_input_entity(to_chat)
        from_entity = await client.get_input_entity(from_chat)
        msgs = await client.forward_messages(to_entity, message_ids, from_entity)
        count = len(msgs) if msgs else 0
        logger.info("forward_messages: to=%s count=%s", to_chat, count)
        return {"success": True, "count": count}
    except Exception as e:
        logger.error("forward_messages error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


async def edit_message(
    client: TelegramClient,
    chat_id: str | int,
    message_id: int,
    new_text: str,
) -> dict:
    """Edit an existing message (your own or in allowed chats).

    Args:
        client: Telethon client instance.
        chat_id: Chat containing the message.
        message_id: ID of the message to edit.
        new_text: New message text.

    Returns:
        dict on success.
    """
    try:
        entity = await client.get_input_entity(chat_id)
        msg = await client.edit_message(entity, message_id, new_text)
        logger.info("edit_message: chat_id=%s msg_id=%s", chat_id, message_id)
        return {"success": True, "message_id": msg.id}
    except Exception as e:
        logger.error("edit_message error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


async def delete_messages(
    client: TelegramClient,
    chat_id: str | int,
    message_ids: int | list[int],
) -> dict:
    """Delete one or more messages from a chat.

    Args:
        client: Telethon client instance.
        chat_id: Chat containing the messages.
        message_ids: Single message ID or list of IDs.

    Returns:
        dict on success.
    """
    try:
        ids = [message_ids] if isinstance(message_ids, int) else message_ids
        entity = await client.get_input_entity(chat_id)
        await client.delete_messages(entity, ids)
        logger.info("delete_messages: chat_id=%s count=%s", chat_id, len(ids))
        return {"success": True, "deleted_count": len(ids)}
    except Exception as e:
        logger.error("delete_messages error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────
# 2. MEDIA / FILE TOOLS
# ─────────────────────────────────────────────


async def send_file(
    client: TelegramClient,
    chat_id: str | int,
    file_path: str,
    caption: str = "",
) -> dict:
    """Send a file (document, image, video, audio) to a chat.

    Args:
        client: Telethon client instance.
        chat_id: Target chat ID or username.
        file_path: Local path to the file.
        caption: Optional caption text.

    Returns:
        dict with 'message_id' on success.
    """
    try:
        entity = await client.get_input_entity(chat_id)
        if not os.path.exists(file_path):
            return {"success": False, "error": f"File not found: {file_path}"}
        msg = await client.send_file(entity, file_path, caption=caption)
        mid = msg.id if hasattr(msg, "id") else (msg[0].id if isinstance(msg, list) else 0)
        logger.info("send_file: chat_id=%s file=%s", chat_id, os.path.basename(file_path))
        return {"success": True, "message_id": mid}
    except Exception as e:
        logger.error("send_file error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


async def send_photo(
    client: TelegramClient,
    chat_id: str | int,
    photo_path: str,
    caption: str = "",
) -> dict:
    """Send a photo to a chat.

    Args:
        client: Telethon client instance.
        chat_id: Target chat ID or username.
        photo_path: Local path to the image file.
        caption: Optional caption.

    Returns:
        dict on success.
    """
    if not os.path.exists(photo_path):
        return {"success": False, "error": f"Photo not found: {photo_path}"}
    return await send_file(client, chat_id, photo_path, caption=caption)


async def send_voice(
    client: TelegramClient,
    chat_id: str | int,
    voice_path: str,
    caption: str = "",
) -> dict:
    """Send a voice message to a chat.

    Args:
        client: Telethon client instance.
        chat_id: Target chat ID or username.
        voice_path: Local path to OGG/MP3 voice file.
        caption: Optional caption.

    Returns:
        dict on success.
    """
    if not os.path.exists(voice_path):
        return {"success": False, "error": f"Voice file not found: {voice_path}"}
    return await send_file(client, chat_id, voice_path, caption=caption)


async def send_media_group(
    client: TelegramClient,
    chat_id: str | int,
    file_paths: list[str],
    caption: str = "",
) -> dict:
    """Send an album (multiple photos/videos) to a chat.

    Args:
        client: Telethon client instance.
        chat_id: Target chat ID or username.
        file_paths: List of local file paths (images/videos).
        caption: Optional caption (applied to first media).

    Returns:
        dict on success.
    """
    try:
        entity = await client.get_input_entity(chat_id)
        existing = [p for p in file_paths if os.path.exists(p)]
        if not existing:
            return {"success": False, "error": "No valid files found"}
        msgs = await client.send_file(entity, existing, caption=caption)
        count = len(msgs) if msgs else 0
        logger.info("send_media_group: chat_id=%s count=%s", chat_id, count)
        return {"success": True, "count": count}
    except Exception as e:
        logger.error("send_media_group error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


async def download_media(
    client: TelegramClient,
    message_id: int,
    chat_id: str | int,
    output_dir: str = "downloads",
) -> dict:
    """Download media from a message to local storage.

    Args:
        client: Telethon client instance.
        message_id: ID of the message containing media.
        chat_id: Chat where the message is.
        output_dir: Directory to save the file.

    Returns:
        dict with 'file_path' on success.
    """
    try:
        entity = await client.get_input_entity(chat_id)
        msg = await client.get_messages(entity, ids=message_id)
        if not msg or not msg.media:
            return {"success": False, "error": "No media found in message"}
        os.makedirs(output_dir, exist_ok=True)
        file_path = await client.download_media(msg, file=output_dir)
        logger.info("download_media: msg_id=%s -> %s", message_id, file_path)
        return {"success": True, "file_path": str(file_path)}
    except Exception as e:
        logger.error("download_media error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────
# 3. GROUP / CHANNEL MANAGEMENT TOOLS
# ─────────────────────────────────────────────


async def get_participants(
    client: TelegramClient,
    chat_id: str | int,
    limit: int = 200,
) -> dict:
    """Get list of participants in a group or channel.

    Args:
        client: Telethon client instance.
        chat_id: Group/channel ID or username.
        limit: Maximum number of participants to fetch.

    Returns:
        dict with 'participants' list and 'count'.
    """
    try:
        entity = await client.get_input_entity(chat_id)
        participants = await client.get_participants(entity, limit=limit)
        result = []
        for p in participants:
            result.append({
                "id": p.id,
                "first_name": getattr(p, "first_name", "") or "",
                "last_name": getattr(p, "last_name", "") or "",
                "username": getattr(p, "username", "") or "",
                "bot": getattr(p, "bot", False),
            })
        logger.info("get_participants: chat_id=%s count=%s", chat_id, len(result))
        return {"success": True, "participants": result, "count": len(result)}
    except ChatAdminRequiredError:
        return {"success": False, "error": "Admin privileges required"}
    except Exception as e:
        logger.error("get_participants error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


async def kick_participant(
    client: TelegramClient,
    chat_id: str | int,
    user_id: int,
) -> dict:
    """Kick (ban + unban) a participant from a group.

    Args:
        client: Telethon client instance.
        chat_id: Group ID or username.
        user_id: User ID to kick.

    Returns:
        dict on success.
    """
    try:
        entity = await client.get_input_entity(chat_id)
        user = await client.get_input_entity(user_id)
        await client.kick_participant(entity, user)
        logger.info("kick_participant: chat_id=%s user_id=%s", chat_id, user_id)
        return {"success": True}
    except ChatAdminRequiredError:
        return {"success": False, "error": "Admin privileges required"}
    except Exception as e:
        logger.error("kick_participant error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


async def ban_participant(
    client: TelegramClient,
    chat_id: str | int,
    user_id: int,
) -> dict:
    """Ban a participant from a group permanently.

    Args:
        client: Telethon client instance.
        chat_id: Group ID or username.
        user_id: User ID to ban.

    Returns:
        dict on success.
    """
    try:
        entity = await client.get_input_entity(chat_id)
        user = await client.get_input_entity(user_id)
        await client.edit_permissions(entity, user, view_messages=False)
        logger.info("ban_participant: chat_id=%s user_id=%s", chat_id, user_id)
        return {"success": True}
    except ChatAdminRequiredError:
        return {"success": False, "error": "Admin privileges required"}
    except Exception as e:
        logger.error("ban_participant error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


async def unban_participant(
    client: TelegramClient,
    chat_id: str | int,
    user_id: int,
) -> dict:
    """Unban a previously banned participant.

    Args:
        client: Telethon client instance.
        chat_id: Group ID or username.
        user_id: User ID to unban.

    Returns:
        dict on success.
    """
    try:
        entity = await client.get_input_entity(chat_id)
        user = await client.get_input_entity(user_id)
        await client.edit_permissions(entity, user, view_messages=True)
        logger.info("unban_participant: chat_id=%s user_id=%s", chat_id, user_id)
        return {"success": True}
    except Exception as e:
        logger.error("unban_participant error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


async def add_participant(
    client: TelegramClient,
    chat_id: str | int,
    user_id: int | str,
) -> dict:
    """Add a user to a group (or invite to channel).

    Args:
        client: Telethon client instance.
        chat_id: Group/channel ID or username.
        user_id: User ID or username to add.

    Returns:
        dict on success.
    """
    try:
        entity = await client.get_input_entity(chat_id)
        user_entity = await client.get_input_entity(user_id)
        await client(AddChatUserRequest(entity, user_entity, fwd_limit=5))
        logger.info("add_participant: chat_id=%s user_id=%s", chat_id, user_id)
        return {"success": True}
    except Exception as e:
        logger.error("add_participant error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


async def leave_chat(
    client: TelegramClient,
    chat_id: str | int,
) -> dict:
    """Leave a group or channel.

    Args:
        client: Telethon client instance.
        chat_id: Group/channel ID or username.

    Returns:
        dict on success.
    """
    try:
        entity = await client.get_input_entity(chat_id)
        await client.delete_dialog(entity)
        logger.info("leave_chat: chat_id=%s", chat_id)
        return {"success": True}
    except Exception as e:
        logger.error("leave_chat error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


async def create_group(
    client: TelegramClient,
    title: str,
    users: list[int | str],
) -> dict:
    """Create a new Telegram group with initial members.

    Args:
        client: Telethon client instance.
        title: Group title.
        users: List of user IDs or usernames to add.

    Returns:
        dict with 'chat_id' on success.
    """
    try:
        user_entities = []
        for u in users:
            try:
                ent = await client.get_input_entity(u)
                user_entities.append(ent)
            except Exception:
                continue
        result = await client(telethon.tl.functions.messages.CreateChatRequest(
            users=user_entities, title=title
        ))
        chat_id = result.chats[0].id if result.chats else None
        logger.info("create_group: title=%s chat_id=%s", title, chat_id)
        return {"success": True, "chat_id": str(chat_id) if chat_id else None}
    except Exception as e:
        logger.error("create_group error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


async def create_channel(
    client: TelegramClient,
    title: str,
    about: str = "",
) -> dict:
    """Create a new Telegram channel.

    Args:
        client: Telethon client instance.
        title: Channel title.
        about: Channel description/bio.

    Returns:
        dict with 'chat_id' on success.
    """
    try:
        result = await client(telethon.tl.functions.channels.CreateChannelRequest(
            title=title, about=about, megagroup=False
        ))
        chat_id = result.chats[0].id if result.chats else None
        logger.info("create_channel: title=%s chat_id=%s", title, chat_id)
        return {"success": True, "chat_id": str(chat_id) if chat_id else None}
    except Exception as e:
        logger.error("create_channel error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────
# 4. QUERY / INFO TOOLS
# ─────────────────────────────────────────────


async def get_dialogs(
    client: TelegramClient,
    limit: int = 100,
) -> dict:
    """List all recent chats, groups, and channels.

    Args:
        client: Telethon client instance.
        limit: Maximum dialogs to fetch (default 100).

    Returns:
        dict with 'dialogs' list.
    """
    try:
        dialogs = await client.get_dialogs(limit=limit)
        result = []
        for d in dialogs:
            result.append({
                "id": d.id,
                "name": d.name or "",
                "type": str(type(d.entity).__name__) if d.entity else "unknown",
                "unread_count": d.unread_count,
                "username": getattr(d.entity, "username", "") if d.entity else "",
            })
        logger.info("get_dialogs: count=%s", len(result))
        return {"success": True, "dialogs": result, "count": len(result)}
    except Exception as e:
        logger.error("get_dialogs error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


async def get_entity(
    client: TelegramClient,
    identifier: str | int,
) -> dict:
    """Resolve a username, phone number, or ID to an entity.

    Args:
        client: Telethon client instance.
        identifier: Username (@user), phone number, or user/chat ID.

    Returns:
        dict with entity info.
    """
    try:
        entity = await client.get_entity(identifier)
        info = {
            "id": entity.id,
            "first_name": getattr(entity, "first_name", "") or "",
            "last_name": getattr(entity, "last_name", "") or "",
            "username": getattr(entity, "username", "") or "",
            "phone": getattr(entity, "phone", "") or "",
            "bot": getattr(entity, "bot", False),
            "type": type(entity).__name__,
        }
        logger.info("get_entity: identifier=%s -> id=%s", identifier, entity.id)
        return {"success": True, "entity": info}
    except (UsernameNotOccupiedError, ValueError):
        return {"success": False, "error": f"Entity not found: {identifier}"}
    except Exception as e:
        logger.error("get_entity error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


async def get_messages(
    client: TelegramClient,
    chat_id: str | int,
    limit: int = 50,
) -> dict:
    """Get recent messages from a chat.

    Args:
        client: Telethon client instance.
        chat_id: Chat ID or username.
        limit: Number of messages to fetch (default 50).

    Returns:
        dict with 'messages' list.
    """
    try:
        entity = await client.get_input_entity(chat_id)
        msgs = await client.get_messages(entity, limit=limit)
        result = []
        for m in msgs:
            result.append({
                "id": m.id,
                "date": str(m.date) if m.date else "",
                "sender_id": m.sender_id,
                "text": (m.text or "")[:2000],
                "has_media": bool(m.media),
            })
        logger.info("get_messages: chat_id=%s count=%s", chat_id, len(result))
        return {"success": True, "messages": result, "count": len(result)}
    except Exception as e:
        logger.error("get_messages error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


async def get_message_by_id(
    client: TelegramClient,
    chat_id: str | int,
    message_id: int,
) -> dict:
    """Get a specific message by ID.

    Args:
        client: Telethon client instance.
        chat_id: Chat containing the message.
        message_id: Message ID.

    Returns:
        dict with message data.
    """
    try:
        entity = await client.get_input_entity(chat_id)
        msg = await client.get_messages(entity, ids=message_id)
        if not msg:
            return {"success": False, "error": "Message not found"}
        result = {
            "id": msg.id,
            "date": str(msg.date) if msg.date else "",
            "sender_id": msg.sender_id,
            "text": (msg.text or "")[:2000],
            "has_media": bool(msg.media),
        }
        return {"success": True, "message": result}
    except Exception as e:
        logger.error("get_message_by_id error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


async def search_messages(
    client: TelegramClient,
    chat_id: str | int,
    query: str,
    limit: int = 20,
) -> dict:
    """Search for messages containing a query in a chat.

    Args:
        client: Telethon client instance.
        chat_id: Chat ID or username.
        query: Search text.
        limit: Max results (default 20).

    Returns:
        dict with 'messages' list.
    """
    try:
        entity = await client.get_input_entity(chat_id)
        msgs = await client.get_messages(entity, search=query, limit=limit)
        result = []
        for m in msgs:
            result.append({
                "id": m.id,
                "date": str(m.date) if m.date else "",
                "sender_id": m.sender_id,
                "text": (m.text or "")[:2000],
            })
        logger.info("search_messages: chat_id=%s query=%s count=%s", chat_id, query, len(result))
        return {"success": True, "messages": result, "count": len(result)}
    except Exception as e:
        logger.error("search_messages error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


async def get_user_info(
    client: TelegramClient,
    user_id: int | str,
) -> dict:
    """Get profile information about a user.

    Args:
        client: Telethon client instance.
        user_id: User ID or username.

    Returns:
        dict with user profile info.
    """
    try:
        entity = await client.get_entity(user_id)
        info = {
            "id": entity.id,
            "first_name": getattr(entity, "first_name", "") or "",
            "last_name": getattr(entity, "last_name", "") or "",
            "username": getattr(entity, "username", "") or "",
            "phone": getattr(entity, "phone", "") or "",
            "bot": getattr(entity, "bot", False),
            "verified": getattr(entity, "verified", False),
            "scam": getattr(entity, "scam", False),
            "fake": getattr(entity, "fake", False),
        }
        # Try to get common chats count & photo
        try:
            full = await client(telethon.tl.functions.users.GetFullUserRequest(entity))
            info["bio"] = getattr(full.full_user, "about", "") or ""
        except Exception:
            info["bio"] = ""
        logger.info("get_user_info: user_id=%s -> id=%s", user_id, entity.id)
        return {"success": True, "user": info}
    except Exception as e:
        logger.error("get_user_info error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────
# 5. ADMIN / UTILITY TOOLS
# ─────────────────────────────────────────────


async def pin_message(
    client: TelegramClient,
    chat_id: str | int,
    message_id: int,
) -> dict:
    """Pin a message in a chat.

    Args:
        client: Telethon client instance.
        chat_id: Chat ID or username.
        message_id: Message ID to pin.

    Returns:
        dict on success.
    """
    try:
        entity = await client.get_input_entity(chat_id)
        await client.pin_message(entity, message_id)
        logger.info("pin_message: chat_id=%s msg_id=%s", chat_id, message_id)
        return {"success": True}
    except ChatAdminRequiredError:
        return {"success": False, "error": "Admin privileges required"}
    except Exception as e:
        logger.error("pin_message error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


async def unpin_message(
    client: TelegramClient,
    chat_id: str | int,
) -> dict:
    """Unpin the pinned message in a chat.

    Args:
        client: Telethon client instance.
        chat_id: Chat ID or username.

    Returns:
        dict on success.
    """
    try:
        entity = await client.get_input_entity(chat_id)
        await client.unpin_message(entity)
        logger.info("unpin_message: chat_id=%s", chat_id)
        return {"success": True}
    except Exception as e:
        logger.error("unpin_message error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


async def mark_read(
    client: TelegramClient,
    chat_id: str | int,
) -> dict:
    """Mark all messages as read in a chat.

    Args:
        client: Telethon client instance.
        chat_id: Chat ID or username.

    Returns:
        dict on success.
    """
    try:
        entity = await client.get_input_entity(chat_id)
        await client.send_read_acknowledge(entity)
        logger.info("mark_read: chat_id=%s", chat_id)
        return {"success": True}
    except Exception as e:
        logger.error("mark_read error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


async def set_profile_photo(
    client: TelegramClient,
    photo_path: str,
) -> dict:
    """Set or change the profile/avatar photo.

    Args:
        client: Telethon client instance.
        photo_path: Local path to the image file.

    Returns:
        dict on success.
    """
    try:
        if not os.path.exists(photo_path):
            return {"success": False, "error": f"Photo not found: {photo_path}"}
        await client.upload_profile_photo(photo_path)
        logger.info("set_profile_photo: %s", photo_path)
        return {"success": True}
    except Exception as e:
        logger.error("set_profile_photo error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


async def update_profile(
    client: TelegramClient,
    first_name: str = "",
    last_name: str = "",
    bio: str = "",
) -> dict:
    """Update profile name and/or bio.

    Args:
        client: Telethon client instance.
        first_name: New first name (empty = no change).
        last_name: New last name (empty = no change).
        bio: New bio/about text (empty = no change).

    Returns:
        dict on success.
    """
    try:
        me = await client.get_me()
        kwargs = {}
        if first_name:
            kwargs["first_name"] = first_name
        if last_name:
            kwargs["last_name"] = last_name
        if kwargs:
            await client(telethon.tl.functions.account.UpdateProfileRequest(**kwargs))
        if bio:
            await client(telethon.tl.functions.account.UpdateStatusRequest(offline=False))
            await client(
                telethon.tl.functions.account.UpdateProfileRequest(about=bio)
            )
        logger.info("update_profile: first=%s last=%s", first_name or "-", last_name or "-")
        return {"success": True}
    except Exception as e:
        logger.error("update_profile error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


async def export_chat_invite_link(
    client: TelegramClient,
    chat_id: str | int,
) -> dict:
    """Get or create an invite link for a chat.

    Args:
        client: Telethon client instance.
        chat_id: Group/channel ID or username.

    Returns:
        dict with 'invite_link' on success.
    """
    try:
        entity = await client.get_input_entity(chat_id)
        link = await client.export_chat_invite(entity)
        logger.info("export_chat_invite: chat_id=%s link=%s", chat_id, link)
        return {"success": True, "invite_link": link}
    except ChatAdminRequiredError:
        return {"success": False, "error": "Admin privileges required"}
    except Exception as e:
        logger.error("export_chat_invite error: %s\n%s", e, traceback.format_exc())
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────
# TOOL MAP — name -> function
# ─────────────────────────────────────────────

TOOL_MAP: dict[str, callable] = {
    "send_message": send_message,
    "reply_message": reply_message,
    "forward_messages": forward_messages,
    "edit_message": edit_message,
    "delete_messages": delete_messages,
    "send_file": send_file,
    "send_photo": send_photo,
    "send_voice": send_voice,
    "send_media_group": send_media_group,
    "download_media": download_media,
    "get_participants": get_participants,
    "kick_participant": kick_participant,
    "ban_participant": ban_participant,
    "unban_participant": unban_participant,
    "add_participant": add_participant,
    "leave_chat": leave_chat,
    "create_group": create_group,
    "create_channel": create_channel,
    "get_dialogs": get_dialogs,
    "get_entity": get_entity,
    "get_messages": get_messages,
    "get_message_by_id": get_message_by_id,
    "search_messages": search_messages,
    "get_user_info": get_user_info,
    "pin_message": pin_message,
    "unpin_message": unpin_message,
    "mark_read": mark_read,
    "set_profile_photo": set_profile_photo,
    "update_profile": update_profile,
    "export_chat_invite_link": export_chat_invite_link,
}

# ─────────────────────────────────────────────
# OPENAI FUNCTION-CALLING SCHEMAS
# ─────────────────────────────────────────────

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "send_message",
            "description": "Send a text message to a Telegram chat or user by ID, username, or phone number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Target chat ID (e.g. '-1001234567890'), username (e.g. '@user'), or phone number"},
                    "text": {"type": "string", "description": "Message text content"},
                    "parse_mode": {"type": "string", "enum": ["markdown", "html", ""], "description": "Parse mode for formatting"},
                },
                "required": ["chat_id", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reply_message",
            "description": "Reply directly to the incoming message the AI just received.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Reply text content"},
                    "parse_mode": {"type": "string", "enum": ["markdown", "html", ""], "description": "Parse mode"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forward_messages",
            "description": "Forward one or more messages from one chat to another.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to_chat": {"type": "string", "description": "Destination chat ID or username"},
                    "from_chat": {"type": "string", "description": "Source chat ID or username"},
                    "message_ids": {"type": "array", "items": {"type": "integer"}, "description": "List of message IDs to forward"},
                },
                "required": ["to_chat", "from_chat", "message_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_message",
            "description": "Edit an existing sent message's text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Chat containing the message"},
                    "message_id": {"type": "integer", "description": "ID of the message to edit"},
                    "new_text": {"type": "string", "description": "New text content"},
                },
                "required": ["chat_id", "message_id", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_messages",
            "description": "Delete one or more messages from a chat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Chat containing the messages"},
                    "message_ids": {"oneOf": [{"type": "integer"}, {"type": "array", "items": {"type": "integer"}}], "description": "Message ID or list of message IDs to delete"},
                },
                "required": ["chat_id", "message_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_file",
            "description": "Send a file (document, image, video, audio) to a chat from a local path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Target chat ID or username"},
                    "file_path": {"type": "string", "description": "Local filesystem path to the file"},
                    "caption": {"type": "string", "description": "Optional caption text"},
                },
                "required": ["chat_id", "file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_photo",
            "description": "Send a photo image to a chat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Target chat ID or username"},
                    "photo_path": {"type": "string", "description": "Local path to the image file"},
                    "caption": {"type": "string", "description": "Optional caption"},
                },
                "required": ["chat_id", "photo_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_voice",
            "description": "Send a voice message (OGG/MP3) to a chat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Target chat ID or username"},
                    "voice_path": {"type": "string", "description": "Local path to the voice file"},
                    "caption": {"type": "string", "description": "Optional caption"},
                },
                "required": ["chat_id", "voice_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_media_group",
            "description": "Send an album of multiple photos/videos to a chat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Target chat ID or username"},
                    "file_paths": {"type": "array", "items": {"type": "string"}, "description": "List of local file paths"},
                    "caption": {"type": "string", "description": "Optional caption (applied to first media)"},
                },
                "required": ["chat_id", "file_paths"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "download_media",
            "description": "Download media from a message to local storage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message_id": {"type": "integer", "description": "ID of the message with media"},
                    "chat_id": {"type": "string", "description": "Chat where the message is"},
                    "output_dir": {"type": "string", "description": "Directory to save the file"},
                },
                "required": ["message_id", "chat_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_participants",
            "description": "Get the list of participants/members in a group or channel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Group/channel ID or username"},
                    "limit": {"type": "integer", "description": "Maximum participants to fetch", "default": 200},
                },
                "required": ["chat_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kick_participant",
            "description": "Kick (ban then immediately unban) a user from a group.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Group ID or username"},
                    "user_id": {"type": "integer", "description": "User ID to kick"},
                },
                "required": ["chat_id", "user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ban_participant",
            "description": "Permanently ban a user from a group (they cannot rejoin).",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Group ID or username"},
                    "user_id": {"type": "integer", "description": "User ID to ban"},
                },
                "required": ["chat_id", "user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unban_participant",
            "description": "Unban a previously banned user from a group.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Group ID or username"},
                    "user_id": {"type": "integer", "description": "User ID to unban"},
                },
                "required": ["chat_id", "user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_participant",
            "description": "Add a user to a group or invite them to a channel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Group/channel ID or username"},
                    "user_id": {"type": "string", "description": "User ID or username to add"},
                },
                "required": ["chat_id", "user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "leave_chat",
            "description": "Leave (delete dialog with) a group or channel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Group/channel ID or username to leave"},
                },
                "required": ["chat_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_group",
            "description": "Create a new Telegram group with initial members.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Group title"},
                    "users": {"type": "array", "items": {"type": "string"}, "description": "List of user IDs or usernames to add as initial members"},
                },
                "required": ["title", "users"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_channel",
            "description": "Create a new Telegram channel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Channel title"},
                    "about": {"type": "string", "description": "Channel description/bio"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dialogs",
            "description": "List all recent Telegram chats, groups, and channels the account is in.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Maximum dialogs to fetch", "default": 100},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_entity",
            "description": "Look up a Telegram user, group, or channel by ID, username (@user), or phone number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "identifier": {"type": "string", "description": "Username (@user), phone number, or numeric ID"},
                },
                "required": ["identifier"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_messages",
            "description": "Get the most recent messages from a chat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Chat ID or username"},
                    "limit": {"type": "integer", "description": "Number of messages to fetch", "default": 50},
                },
                "required": ["chat_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_message_by_id",
            "description": "Get a single specific message by its ID from a chat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Chat containing the message"},
                    "message_id": {"type": "integer", "description": "Message ID to retrieve"},
                },
                "required": ["chat_id", "message_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_messages",
            "description": "Search for messages containing specific text in a chat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Chat ID or username"},
                    "query": {"type": "string", "description": "Search text query"},
                    "limit": {"type": "integer", "description": "Maximum results", "default": 20},
                },
                "required": ["chat_id", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_info",
            "description": "Get detailed profile information about a Telegram user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "User ID or username (@user)"},
                },
                "required": ["user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pin_message",
            "description": "Pin a message at the top of a chat (admin rights may be needed).",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Chat ID or username"},
                    "message_id": {"type": "integer", "description": "Message ID to pin"},
                },
                "required": ["chat_id", "message_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unpin_message",
            "description": "Remove the pinned message from a chat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Chat ID or username"},
                },
                "required": ["chat_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_read",
            "description": "Mark all messages as read in a chat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Chat ID or username"},
                },
                "required": ["chat_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_profile_photo",
            "description": "Change the account's profile/avatar photo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "photo_path": {"type": "string", "description": "Local path to the new profile photo image"},
                },
                "required": ["photo_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_profile",
            "description": "Update the account's first name, last name, and/or bio.",
            "parameters": {
                "type": "object",
                "properties": {
                    "first_name": {"type": "string", "description": "New first name"},
                    "last_name": {"type": "string", "description": "New last name"},
                    "bio": {"type": "string", "description": "New bio/about text"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_chat_invite_link",
            "description": "Get or create an invite link for a group or channel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Group/channel ID or username"},
                },
                "required": ["chat_id"],
            },
        },
    },
]

# ─────────────────────────────────────────────
# TOOL EXECUTOR
# ─────────────────────────────────────────────


async def execute_tool_call(
    client: TelegramClient,
    tool_name: str,
    arguments: dict | str,
    event=None,
) -> dict:
    """Execute a tool by name with parsed arguments.

    If the tool is ``reply_message``, ``event`` must be provided.

    Args:
        client: Telethon client instance.
        tool_name: Name of the tool to call (must be in TOOL_MAP).
        arguments: Dict of keyword arguments, or JSON string.
        event: Required for ``reply_message`` tool.

    Returns:
        dict result from the tool function.
    """
    if isinstance(arguments, str):
        arguments = json.loads(arguments)

    tool_fn = TOOL_MAP.get(tool_name)
    if not tool_fn:
        return {"success": False, "error": f"Unknown tool: {tool_name}"}

    # Inject event for reply_message
    if tool_name == "reply_message" and event is not None:
        arguments["event"] = event

    try:
        result = await tool_fn(client, **arguments)
        return result
    except Exception as e:
        logger.error("execute_tool_call: %s error: %s", tool_name, e)
        return {"success": False, "error": str(e)}
