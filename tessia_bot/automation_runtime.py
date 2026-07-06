"""
Automation Runtime — Stateful Multi-Step Workflows

Handles workflows that span multiple messages:
  - wait_for_file: pause, wait for user to upload a file, then process and forward
  - mark_for_review: hold a message for father approval before sending

Each pending workflow is tracked in ``_pending_workflows`` (in-memory dict).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from tessia_bot.automation import AutomationAction, AutomationEvent, AutomationRule, build_rule_context

logger = logging.getLogger("tessia.automation_runtime")

# ─────────────────────────────────────────────
# DATA MODELS
# ─────────────────────────────────────────────


@dataclass
class Workflow:
    """A pending workflow waiting for a follow-up event."""

    workflow_id: str
    action: str  # the action that started this workflow (e.g. "wait_for_file")
    rule_id: str
    chat_id: str
    sender_id: str
    created_at: float = field(default_factory=time.time)
    state: dict[str, Any] = field(default_factory=dict)


# In-memory store of pending workflows
_pending_workflows: dict[str, Workflow] = {}


# ─────────────────────────────────────────────
# CALLBACK TYPE
# ─────────────────────────────────────────────

WorkflowCallback = Callable[[AutomationEvent, dict[str, Any]], AutomationAction | None]
"""Signature: (event, workflow_state) -> AutomationAction or None.

Return an AutomationAction for the next step, or None to end the workflow.
"""

# Registered workflow handlers
_workflow_handlers: dict[str, WorkflowCallback] = {}


def register_workflow(action_name: str, handler: WorkflowCallback):
    """Register a handler for a specific workflow action type."""
    _workflow_handlers[action_name] = handler
    logger.info("Registered workflow handler: %s", action_name)


# ─────────────────────────────────────────────
# CORE WORKFLOW ENGINE
# ─────────────────────────────────────────────


async def start_workflow(
    action: AutomationAction,
    event: AutomationEvent,
    rule: AutomationRule | None = None,
) -> bool:
    """Start a new pending workflow.

    Only certain actions create pending workflows:
      - wait_for_file
      - mark_for_review

    Returns True if a workflow was started.
    """
    if action.action == "wait_for_file":
        wf = Workflow(
            workflow_id=f"wf_{event.chat_id}_{event.sender_id}_{int(time.time())}",
            action="wait_for_file",
            rule_id=rule.rule_id if rule else "unknown",
            chat_id=event.chat_id,
            sender_id=event.sender_id,
            state={
                "target_chat_id": action.target_chat_id,
                "mention_user_id": action.mention_user_id,
                "instructions": action.text or "",
                "require_review": action.metadata.get("require_review", False) if hasattr(action, "metadata") else False,
            },
        )
        _pending_workflows[wf.workflow_id] = wf
        logger.info(
            "Started workflow: %s (action=%s sender=%s)",
            wf.workflow_id, action.action, event.sender_id,
        )
        return True

    if action.action == "mark_for_review":
        wf = Workflow(
            workflow_id=f"review_{event.chat_id}_{event.sender_id}_{int(time.time())}",
            action="mark_for_review",
            rule_id=rule.rule_id if rule else "unknown",
            chat_id=event.chat_id,
            sender_id=event.sender_id,
            state={
                "message_text": event.message_text,
                "target_chat_id": action.target_chat_id,
                "mention_user_id": action.mention_user_id,
                "reviewed": False,
            },
        )
        _pending_workflows[wf.workflow_id] = wf
        logger.info(
            "Started review workflow: %s (sender=%s)",
            wf.workflow_id, event.sender_id,
        )
        return True

    return False


async def resume_workflow(
    event: AutomationEvent,
    telethon_client,
) -> AutomationAction | None:
    """Check if a pending workflow exists for this sender/chat and resume it.

    Returns an AutomationAction for the next step, or None if no pending workflow.
    """
    matching = []
    for wf in _pending_workflows.values():
        if wf.chat_id == event.chat_id and wf.sender_id == event.sender_id:
            matching.append(wf)

    if not matching:
        return None

    # Resume the most recent workflow
    wf = sorted(matching, key=lambda w: w.created_at, reverse=True)[0]
    handler = _workflow_handlers.get(wf.action)
    if handler:
        result = handler(event, wf.state)
        if result is None:
            # Workflow complete — remove
            _pending_workflows.pop(wf.workflow_id, None)
            logger.info("Workflow %s completed (handler returned None)", wf.workflow_id)
        return result

    logger.warning("No handler registered for workflow action: %s", wf.action)
    return None


def get_pending_workflow(sender_id: str, chat_id: str) -> Workflow | None:
    """Get the most recent pending workflow for a user in a chat."""
    matches = [
        wf
        for wf in _pending_workflows.values()
        if wf.chat_id == chat_id and wf.sender_id == sender_id
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda w: w.created_at, reverse=True)[0]


def cancel_workflow(workflow_id: str) -> bool:
    """Cancel/remove a pending workflow."""
    if workflow_id in _pending_workflows:
        _pending_workflows.pop(workflow_id)
        logger.info("Cancelled workflow: %s", workflow_id)
        return True
    return False


def list_pending_workflows() -> list[dict]:
    """List all pending workflows (for status/debug)."""
    return [
        {
            "workflow_id": wf.workflow_id,
            "action": wf.action,
            "rule_id": wf.rule_id,
            "chat_id": wf.chat_id,
            "sender_id": wf.sender_id,
            "created_at": wf.created_at,
            "state": wf.state,
        }
        for wf in _pending_workflows.values()
    ]


# ─────────────────────────────────────────────
# BUILT-IN WORKFLOW HANDLERS
# ─────────────────────────────────────────────


def handle_wait_for_file(event: AutomationEvent, state: dict[str, Any]) -> AutomationAction | None:
    """Handle a ``wait_for_file`` workflow continuation.

    When the user sends another message after being asked for a file,
    this handler checks if the new message has a file/document attached.
    """
    # If the new message has no file, ask again
    if event.message_type != "document" and not event.metadata.get("has_media"):
        return AutomationAction(
            action="reply_text",
            text="منتظر فایلت هستم. وقتی آماده شد بفرست.",
        )

    # File received — forward to target chat if configured
    target = state.get("target_chat_id", "")
    mention = state.get("mention_user_id", "")

    if target:
        # Forward the file to the target group
        return AutomationAction(
            action="forward_to_group",
            text=f"فایل از {event.sender_name} رسید.",
            target_chat_id=target,
            mention_user_id=mention,
            metadata={"message_ids": event.metadata.get("message_ids", [])},
        )
    else:
        # Just acknowledge receipt
        return AutomationAction(
            action="reply_text",
            text="فایلت رو دریافت کردم. بررسی می‌کنم.",
        )


def handle_mark_for_review(event: AutomationEvent, state: dict[str, Any]) -> AutomationAction | None:
    """Handle a ``mark_for_review`` workflow continuation.

    The reviewed message is already stored in state. This handler
    currently just logs the review to avoid spamming; future versions
    can forward reviewed items.
    """
    logger.info(
        "Review workflow for sender=%s: message=%s",
        event.sender_id,
        state.get("message_text", "")[:200],
    )
    # Mark as reviewed and complete
    state["reviewed"] = True
    return None  # complete


# Register built-in handlers
register_workflow("wait_for_file", handle_wait_for_file)
register_workflow("mark_for_review", handle_mark_for_review)
