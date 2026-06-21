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
