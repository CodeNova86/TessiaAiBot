from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ALLOWED_ACTIONS = {
    "ignore",
    "reply_text",
    "reply_voice",
    "request_file",
    "forward_to_group",
    "mention_user",
    "wait_for_file",
    "mark_for_review",
}


@dataclass
class AutomationEvent:
    source: str
    chat_id: str
    sender_id: str
    sender_name: str = ""
    username: str = ""
    message_text: str = ""
    message_type: str = "text"
    is_private: bool = True
    reply_to_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AutomationAction:
    action: str
    text: str = ""
    target_chat_id: str = ""
    mention_user_id: str = ""
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_valid(self) -> bool:
        return self.action in ALLOWED_ACTIONS


@dataclass
class AutomationRule:
    rule_id: str
    enabled: bool = True
    scope: str = "private"
    allowed_senders: list[str] = field(default_factory=list)
    trigger_keywords: list[str] = field(default_factory=list)
    action_template: str = "reply_text"
    instructions: str = ""
    target_chat_id: str = ""
    mention_user_id: str = ""
    require_review: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AutomationRule":
        return cls(
            rule_id=str(raw.get("rule_id", "")).strip(),
            enabled=bool(raw.get("enabled", True)),
            scope=str(raw.get("scope", "private")).strip() or "private",
            allowed_senders=[str(item) for item in raw.get("allowed_senders", []) if str(item).strip()],
            trigger_keywords=[str(item).strip() for item in raw.get("trigger_keywords", []) if str(item).strip()],
            action_template=str(raw.get("action_template", "reply_text")).strip() or "reply_text",
            instructions=str(raw.get("instructions", "")).strip(),
            target_chat_id=str(raw.get("target_chat_id", "")).strip(),
            mention_user_id=str(raw.get("mention_user_id", "")).strip(),
            require_review=bool(raw.get("require_review", False)),
        )

    def matches(self, event: AutomationEvent) -> bool:
        if not self.enabled or not self.rule_id:
            return False
        if self.scope == "private" and not event.is_private:
            return False
        if self.allowed_senders and event.sender_id not in self.allowed_senders and event.username not in self.allowed_senders:
            return False
        if self.trigger_keywords:
            haystack = f"{event.message_text}\n{event.reply_to_text}".lower()
            if not any(keyword.lower() in haystack for keyword in self.trigger_keywords):
                return False
        return True


def match_automation_rules(event: AutomationEvent, rules: list[AutomationRule]) -> list[AutomationRule]:
    return [rule for rule in rules if rule.matches(event)]


def build_rule_context(event: AutomationEvent, rule: AutomationRule) -> dict[str, Any]:
    return {
        "rule_id": rule.rule_id,
        "action_template": rule.action_template,
        "instructions": rule.instructions,
        "target_chat_id": rule.target_chat_id,
        "mention_user_id": rule.mention_user_id,
        "require_review": rule.require_review,
        "event": {
            "source": event.source,
            "chat_id": event.chat_id,
            "sender_id": event.sender_id,
            "sender_name": event.sender_name,
            "username": event.username,
            "message_text": event.message_text,
            "message_type": event.message_type,
            "is_private": event.is_private,
            "reply_to_text": event.reply_to_text,
            "metadata": event.metadata,
        },
    }


# ─────────────────────────────────────────────
# TOOL EXECUTION LAYER (bridges AutomationAction → telethon_tools)
# ─────────────────────────────────────────────

# Maps AutomationAction.action names to telethon_tools.TOOL_MAP function names
ACTION_TO_TOOL: dict[str, str | None] = {
    "ignore": None,
    "reply_text": "reply_message",
    "reply_voice": "send_voice",
    "request_file": "send_message",
    "forward_to_group": "forward_messages",
    "mention_user": "send_message",
    "wait_for_file": "send_message",
    "mark_for_review": "forward_messages",
}

# Maps action names to default argument overrides for the target tool
ACTION_TO_TOOL_ARGS: dict[str, dict] = {
    "request_file": {
        "text": "لطفاً فایل مورد نظر را آپلود کنید."
    },
    "wait_for_file": {
        "text": "باشه، فایلت رو بفرست تا بررسی کنم."
    },
    "mention_user": {
        "text": "شما منشن شده‌اید."
    },
}


async def execute_automation_action(
    action: AutomationAction,
    event: AutomationEvent,
    telethon_client,
) -> dict:
    """Execute an AutomationAction using the Telethon tools layer.

    This bridges the old ``AutomationAction``-based rule system with the
    new ``telethon_tools`` function-calling architecture.

    Args:
        action: The matched action to execute.
        event: The original event that triggered the match.
        telethon_client: Connected Telethon TelegramClient instance.

    Returns:
        dict with success/error information.
    """
    tool_name = ACTION_TO_TOOL.get(action.action)
    if tool_name is None:
        if action.action == "ignore":
            return {"success": True, "action": "ignored"}
        return {"success": False, "error": f"No tool mapping for action: {action.action}"}

    # Import here to avoid circular imports
    from tessia_bot.telethon_tools import TOOL_MAP, execute_tool_call

    tool_fn = TOOL_MAP.get(tool_name)
    if not tool_fn:
        return {"success": False, "error": f"Unknown tool: {tool_name}"}

    # Build arguments for the tool
    args = {}

    # Every message tool needs a chat_id
    chat_id = action.target_chat_id or event.chat_id
    args["chat_id"] = chat_id

    # Add default args for this action type
    default_args = ACTION_TO_TOOL_ARGS.get(action.action, {})
    args.update(default_args)

    # If the action has explicit text, use it
    if action.text:
        args["text"] = action.text

    # Handle forward_to_group specially
    if action.action == "forward_to_group" and event.metadata.get("message_ids"):
        args["message_ids"] = event.metadata["message_ids"]
        args["from_chat"] = event.chat_id
        args["to_chat"] = action.target_chat_id or event.chat_id

    # Handle mention_user
    if action.action == "mention_user" and action.mention_user_id:
        mention_text = args.get("text", "")
        args["text"] = f"[{mention_text}](tg://user?id={action.mention_user_id})"

    # Execute via the tool executor
    try:
        result = await tool_fn(telethon_client, **args)
        return {
            "success": result.get("success", False),
            "action": action.action,
            "tool": tool_name,
            "result": result,
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e), "action": action.action}


async def execute_action_from_tool_call(
    telethon_client,
    tool_name: str,
    arguments: dict | str,
    event=None,
) -> dict:
    """Execute a tool call directly (used by the OpenAI function-calling brain).

    This is a thin wrapper around ``telethon_tools.execute_tool_call``
    and exists here so the brain runtime can import from automation.py
    without needing to know about telethon_tools internals.

    Args:
        telethon_client: Connected Telethon TelegramClient instance.
        tool_name: Name of the tool to call.
        arguments: Dict or JSON string of keyword arguments.
        event: Optional Telethon event (required for ``reply_message``).

    Returns:
        dict result from the tool.
    """
    from tessia_bot.telethon_tools import execute_tool_call as _execute
    return await _execute(telethon_client, tool_name, arguments, event=event)
