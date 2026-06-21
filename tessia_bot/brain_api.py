from __future__ import annotations

from pydantic import BaseModel, Field


class IncomingMessagePayload(BaseModel):
    source: str = Field(default="telegram_userbot")
    chat_id: str
    sender_id: str
    sender_name: str = ""
    username: str = ""
    message_text: str = ""
    message_type: str = "text"
    is_private: bool = True
    reply_to_text: str = ""
    metadata: dict = Field(default_factory=dict)


class BrainActionResponse(BaseModel):
    action: str
    text: str = ""
    target_chat_id: str = ""
    mention_user_id: str = ""
    reason: str = ""
    metadata: dict = Field(default_factory=dict)
