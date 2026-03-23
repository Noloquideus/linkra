from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AttachmentRecord(BaseModel):
    attachment_id: str
    original_name: str
    stored_name: str
    content_type: str
    size_bytes: int
    created_at: datetime = Field(default_factory=utcnow)


class ChatEventRecord(BaseModel):
    event_type: str
    author: str
    text: str | None = None
    attachment_id: str | None = None
    file_name: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class CallRecord(BaseModel):
    room_name: str
    room_title: str
    invite_token: str
    invite_short_code: str | None = None
    password: str | None = None
    telegram_alert_enabled: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    is_active: bool = True
    participant_names: list[str] = Field(default_factory=list)
    chat_events: list[ChatEventRecord] = Field(default_factory=list)
    attachments: list[AttachmentRecord] = Field(default_factory=list)
