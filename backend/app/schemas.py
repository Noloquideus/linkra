from typing import Optional

from pydantic import BaseModel, Field


class CreateCallRequest(BaseModel):
    room_title: str = Field(default="", max_length=100)
    password: str = Field(default="", max_length=100)
    telegram_alert_enabled: bool = False


class CreateCallResponse(BaseModel):
    room_name: str
    room_title: str
    invite_token: str
    invite_link: str
    short_invite_link: str
    has_password: bool = False


class JoinCallRequest(BaseModel):
    invite_token: str = Field(min_length=8)
    display_name: str = Field(min_length=1, max_length=50)
    password: str = Field(default="", max_length=100)
    with_video: bool = True
    with_audio: bool = True
    identity: Optional[str] = Field(default=None, max_length=64)


class JoinCallResponse(BaseModel):
    server_url: str
    participant_token: str
    room_name: str
    room_title: str
    identity: str
    display_name: str


class CallInfoResponse(BaseModel):
    room_name: str
    room_title: str
    is_active: bool
    created_at: str
    has_password: bool = False


class FinishCallRequest(BaseModel):
    invite_token: str = Field(min_length=8)


class AttachmentResponse(BaseModel):
    attachment_id: str
    file_name: str
    content_type: str
    size_bytes: int
    download_url: str


class AttachmentListResponse(BaseModel):
    items: list[AttachmentResponse] = Field(default_factory=list)


class ChatMessageLogRequest(BaseModel):
    invite_token: str = Field(min_length=8)
    display_name: str = Field(min_length=1, max_length=50)
    text: str = Field(min_length=1, max_length=1000)
