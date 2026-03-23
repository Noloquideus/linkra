from threading import Lock
from typing import Optional

from .models import AttachmentRecord, CallRecord, ChatEventRecord, utcnow


class InMemoryCallStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._calls: dict[str, CallRecord] = {}
        self._short_to_room: dict[str, str] = {}

    def create(self, call: CallRecord) -> CallRecord:
        with self._lock:
            self._calls[call.room_name] = call
            return call

    def register_short_invite(self, short_code: str, room_name: str) -> bool:
        with self._lock:
            if short_code in self._short_to_room:
                return False
            self._short_to_room[short_code] = room_name
            return True

    def resolve_short_invite(self, short_code: str) -> Optional[str]:
        with self._lock:
            return self._short_to_room.get(short_code)

    def get(self, room_name: str) -> Optional[CallRecord]:
        with self._lock:
            return self._calls.get(room_name)

    def deactivate(self, room_name: str) -> Optional[CallRecord]:
        with self._lock:
            call = self._calls.get(room_name)
            if call is None:
                return None
            if call.invite_short_code:
                self._short_to_room.pop(call.invite_short_code, None)
            updated = call.model_copy(update={"is_active": False})
            self._calls[room_name] = updated
            return updated

    def mark_started(self, room_name: str):
        with self._lock:
            call = self._calls.get(room_name)
            if call is None or call.started_at is not None:
                return call
            updated = call.model_copy(update={"started_at": utcnow()})
            self._calls[room_name] = updated
            return updated

    def add_participant(self, room_name: str, display_name: str):
        with self._lock:
            call = self._calls.get(room_name)
            if call is None:
                return None
            name = display_name.strip()
            if not name or name in call.participant_names:
                return call
            updated = call.model_copy(update={"participant_names": [*call.participant_names, name]})
            self._calls[room_name] = updated
            return updated

    def add_chat_event(self, room_name: str, event: ChatEventRecord) -> Optional[CallRecord]:
        with self._lock:
            call = self._calls.get(room_name)
            if call is None:
                return None
            updated = call.model_copy(update={"chat_events": [*call.chat_events, event]})
            self._calls[room_name] = updated
            return updated

    def update_chat_events_author_by_identity(
        self, room_name: str, participant_identity: str, display_name: str
    ) -> Optional[CallRecord]:
        with self._lock:
            call = self._calls.get(room_name)
            if call is None:
                return None
            new_events: list[ChatEventRecord] = []
            for ev in call.chat_events:
                if ev.author_identity and ev.author_identity == participant_identity:
                    new_events.append(ev.model_copy(update={"author": display_name}))
                else:
                    new_events.append(ev)
            updated = call.model_copy(update={"chat_events": new_events})
            self._calls[room_name] = updated
            return updated

    def add_attachment(self, room_name: str, attachment: AttachmentRecord) -> Optional[CallRecord]:
        with self._lock:
            call = self._calls.get(room_name)
            if call is None:
                return None
            updated = call.model_copy(update={"attachments": [*call.attachments, attachment]})
            self._calls[room_name] = updated
            return updated

    def list_attachments(self, room_name: str) -> list[AttachmentRecord]:
        with self._lock:
            call = self._calls.get(room_name)
            if call is None:
                return []
            return list(call.attachments)

    def get_attachment(self, room_name: str, attachment_id: str) -> Optional[AttachmentRecord]:
        with self._lock:
            call = self._calls.get(room_name)
            if call is None:
                return None
            for attachment in call.attachments:
                if attachment.attachment_id == attachment_id:
                    return attachment
            return None

    def clear_attachments(self, room_name: str) -> Optional[CallRecord]:
        with self._lock:
            call = self._calls.get(room_name)
            if call is None:
                return None
            updated = call.model_copy(update={"attachments": []})
            self._calls[room_name] = updated
            return updated


store = InMemoryCallStore()
