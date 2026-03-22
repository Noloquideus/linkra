import json
import mimetypes
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from shutil import rmtree
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import settings
from .livekit_service import build_participant_token, create_room_if_needed
from .models import AttachmentRecord, CallRecord, ChatEventRecord
from .schemas import (
    AttachmentListResponse,
    AttachmentResponse,
    CallInfoResponse,
    ChatMessageLogRequest,
    CreateCallRequest,
    CreateCallResponse,
    FinishCallRequest,
    JoinCallRequest,
    JoinCallResponse,
)
from .store import store

app = FastAPI(title="Video Call MVP")

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

settings.uploads_path.mkdir(parents=True, exist_ok=True)


def render_call_error(
    request: Request,
    *,
    status_code: int,
    page_title: str,
    heading: str,
    message: str,
    error_code: str,
    variant: str,
    show_retry: bool = False,
):
    return templates.TemplateResponse(
        "call_error.html",
        {
            "request": request,
            "page_title": page_title,
            "heading": heading,
            "message": message,
            "error_code": error_code,
            "variant": variant,
            "show_retry": show_retry,
        },
        status_code=status_code,
    )


def build_attachment_response(room_name: str, attachment: AttachmentRecord) -> AttachmentResponse:
    return AttachmentResponse(
        attachment_id=attachment.attachment_id,
        file_name=attachment.original_name,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        download_url=f"/api/calls/{room_name}/attachments/{attachment.attachment_id}",
    )


def ensure_call_access(room_name: str, invite_token: str) -> CallRecord:
    call = store.get(room_name)
    if call is None or not call.is_active:
        raise HTTPException(status_code=404, detail="Call not found")
    if invite_token != call.invite_token:
        raise HTTPException(status_code=403, detail="Invalid invite token")
    return call


def room_upload_dir(room_name: str) -> Path:
    return settings.uploads_path / room_name


def human_dt(value: datetime) -> str:
    return value.astimezone().strftime("%d.%m.%Y %H:%M:%S %Z")


def format_duration(seconds: int) -> str:
    minutes, secs = divmod(max(0, seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def split_text_chunks(text: str, limit: int = 3500) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.splitlines():
        candidate = f"{current}\n{line}".strip() if current else line
        if len(candidate) > limit and current:
            chunks.append(current)
            current = line
        elif len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(line), limit):
                chunks.append(line[start:start + limit])
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def telegram_targets() -> list[dict[str, str | int]]:
    chat_id = settings.telegram_chat_id.strip()
    if settings.telegram_topic_id is not None:
        return [
            {
                "chat_id": chat_id,
                "message_thread_id": settings.telegram_topic_id,
            }
        ]
    return [{"chat_id": chat_id}]


def telegram_request(
    method: str,
    fields: dict[str, str | int],
    file_path: Path | None = None,
    file_name: str | None = None,
    content_type: str | None = None,
) -> None:
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token.strip()}/{method}"
    if file_path is None:
        data = urllib.parse.urlencode({k: v for k, v in fields.items() if v is not None}).encode("utf-8")
        request = urllib.request.Request(url, data=data, method="POST")
    else:
        boundary = f"----ChatGPTBoundary{uuid4().hex}"
        body = bytearray()
        for key, value in fields.items():
            if value is None:
                continue
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode("utf-8"))
        guessed_type = content_type or mimetypes.guess_type(file_name or file_path.name)[0] or "application/octet-stream"
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="document"; filename="{file_name or file_path.name}"\r\n'.encode(
                "utf-8"
            )
        )
        body.extend(f"Content-Type: {guessed_type}\r\n\r\n".encode("utf-8"))
        body.extend(file_path.read_bytes())
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())
        request = urllib.request.Request(
            url,
            data=bytes(body),
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description") or "Telegram API error")


def send_telegram_text(text: str) -> None:
    for target in telegram_targets():
        for chunk in split_text_chunks(text):
            telegram_request(
                "sendMessage",
                {
                    **target,
                    "text": chunk,
                    "disable_web_page_preview": "true",
                },
            )


def send_telegram_document(file_path: Path, attachment: AttachmentRecord, caption: str | None = None) -> None:
    for target in telegram_targets():
        telegram_request(
            "sendDocument",
            {
                **target,
                "caption": caption or attachment.original_name,
            },
            file_path=file_path,
            file_name=attachment.original_name,
            content_type=attachment.content_type,
        )


def send_finish_alert(call: CallRecord) -> None:
    if not (settings.telegram_alerting_available and call.telegram_alert_enabled):
        return

    started_at = call.started_at or call.created_at
    finished_at = datetime.now(started_at.tzinfo)
    duration_seconds = int((finished_at - started_at).total_seconds()) if started_at else 0

    if duration_seconds < 60:
        return
    if len(call.participant_names) < 2:
        return
    has_activity = bool(call.chat_events or call.attachments)
    if not has_activity:
        return
    if call.started_at is None:
        return
    
    participants = ", ".join(call.participant_names) if call.participant_names else "—"

    summary = "\n".join(
        [
            f"Итоги созвона: {call.room_title}",
            f"Комната: {call.room_name}",
            f"Создана: {human_dt(call.created_at)}",
            f"Таймер созвона: {format_duration(duration_seconds)}",
            f"Участники: {participants}",
        ]
    )
    send_telegram_text(summary)

    transcript_lines: list[str] = []
    for event in call.chat_events:
        timestamp = event.created_at.astimezone().strftime("%H:%M:%S")
        if event.event_type == "text" and event.text:
            transcript_lines.append(f"[{timestamp}] {event.author}: {event.text}")
        elif event.event_type == "file":
            transcript_lines.append(f"[{timestamp}] {event.author}: файл {event.file_name or 'без названия'}")

    if transcript_lines:
        send_telegram_text("Сообщения и файлы из чата:\n" + "\n".join(transcript_lines))
    else:
        send_telegram_text("Сообщения и файлы из чата: нет пользовательских сообщений.")

    attachment_authors = {
        event.attachment_id: event.author
        for event in call.chat_events
        if event.event_type == "file" and event.attachment_id
    }
    upload_dir = room_upload_dir(call.room_name)
    for attachment in call.attachments:
        file_path = upload_dir / attachment.stored_name
        if not file_path.exists():
            continue
        author = attachment_authors.get(attachment.attachment_id)
        caption = f"Файл из чата: {attachment.original_name}"
        if author:
            caption = f"{caption} — {author}"
        send_telegram_document(file_path, attachment, caption=caption[:1000])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "telegram_alerting_available": settings.telegram_alerting_available,
        },
    )


@app.get("/call/overloaded", response_class=HTMLResponse)
def call_overloaded_page(request: Request):
    return render_call_error(
        request,
        status_code=503,
        page_title="Сервер перегружен",
        heading="Сервис временно недоступен",
        message="Сервер перегружен. Подождите немного и обновите страницу или зайдите позже.",
        error_code="503",
        variant="overloaded",
        show_retry=True,
    )


@app.get("/call/{room_name}", response_class=HTMLResponse)
def call_page(request: Request, room_name: str, invite: str | None = Query(default=None)):
    invite_val = (invite or "").strip()
    call = store.get(room_name)
    if call is None:
        return render_call_error(
            request,
            status_code=404,
            page_title="Комната не найдена",
            heading="Комната не найдена",
            message="Такой комнаты нет или ссылка устарела. Проверьте адрес или создайте новый звонок на главной странице.",
            error_code="404",
            variant="not_found",
        )
    if not call.is_active:
        return render_call_error(
            request,
            status_code=410,
            page_title="Звонок завершён",
            heading="Звонок завершён",
            message="Эта встреча уже закончена. Попросите организатора прислать новую ссылку.",
            error_code="410",
            variant="ended",
        )
    if invite_val and invite_val != call.invite_token:
        return render_call_error(
            request,
            status_code=403,
            page_title="Приглашение недействительно",
            heading="Приглашение недействительно",
            message="Ссылка приглашения недействительна или была заменена. Запросите новую ссылку у организатора.",
            error_code="403",
            variant="invalid_invite",
        )
    return templates.TemplateResponse(
        "call.html",
        {
            "request": request,
            "room_name": room_name,
            "room_title": call.room_title,
            "has_password": bool(call.password),
            "max_attachment_size_mb": settings.max_attachment_size_mb,
        },
    )


@app.post("/api/calls", response_model=CreateCallResponse)
async def create_call(payload: CreateCallRequest | None = None) -> CreateCallResponse:
    room_name = f"call-{uuid4().hex[:10]}"
    invite_token = uuid4().hex
    room_title = (payload.room_title if payload and payload.room_title else room_name)
    password = payload.password.strip() if payload and payload.password else None
    telegram_alert_enabled = bool(payload.telegram_alert_enabled) if payload else False

    call = CallRecord(
        room_name=room_name,
        room_title=room_title,
        invite_token=invite_token,
        password=password or None,
        telegram_alert_enabled=settings.telegram_alerting_available and telegram_alert_enabled,
    )
    store.create(call)
    await create_room_if_needed(room_name)

    invite_link = f"{settings.app_base_url.strip()}/call/{room_name}?invite={invite_token}"
    return CreateCallResponse(
        room_name=room_name,
        room_title=room_title,
        invite_token=invite_token,
        invite_link=invite_link,
        has_password=bool(password),
    )


@app.get("/api/calls/{room_name}", response_model=CallInfoResponse)
def get_call(room_name: str) -> CallInfoResponse:
    call = store.get(room_name)
    if call is None:
        raise HTTPException(status_code=404, detail="Call not found")
    return CallInfoResponse(
        room_name=call.room_name,
        room_title=call.room_title,
        is_active=call.is_active,
        created_at=call.created_at.isoformat(),
        has_password=bool(call.password),
    )


@app.post("/api/calls/{room_name}/join", response_model=JoinCallResponse)
async def join_call(room_name: str, payload: JoinCallRequest) -> JoinCallResponse:
    call = store.get(room_name)
    if call is None or not call.is_active:
        raise HTTPException(status_code=404, detail="Call not found")
    if payload.invite_token != call.invite_token:
        raise HTTPException(status_code=403, detail="Invalid invite token")
    if call.password and payload.password.strip() != call.password:
        raise HTTPException(status_code=403, detail="Неверный пароль комнаты")

    identity = payload.identity or f"user-{uuid4().hex[:12]}"
    participant_token = await build_participant_token(
        room_name=room_name,
        identity=identity,
        display_name=payload.display_name,
    )
    store.mark_started(room_name)
    store.add_participant(room_name, payload.display_name)

    return JoinCallResponse(
        server_url=settings.livekit_public_url,
        participant_token=participant_token,
        room_name=room_name,
        room_title=call.room_title,
        identity=identity,
        display_name=payload.display_name,
    )


@app.post("/api/calls/{room_name}/chat-events")
def log_chat_message(room_name: str, payload: ChatMessageLogRequest) -> dict[str, str]:
    ensure_call_access(room_name, payload.invite_token)
    store.add_chat_event(
        room_name,
        ChatEventRecord(
            event_type="text",
            author=payload.display_name.strip(),
            text=payload.text.strip(),
        ),
    )
    return {"status": "ok"}


@app.get("/api/calls/{room_name}/attachments", response_model=AttachmentListResponse)
def list_attachments(room_name: str, invite_token: str) -> AttachmentListResponse:
    ensure_call_access(room_name, invite_token)
    items = [build_attachment_response(room_name, item) for item in store.list_attachments(room_name)]
    return AttachmentListResponse(items=items)


@app.post("/api/calls/{room_name}/attachments", response_model=AttachmentResponse)
async def upload_attachment(
    room_name: str,
    invite_token: str,
    file: UploadFile = File(...),
    display_name: str = Form(default=""),
) -> AttachmentResponse:
    ensure_call_access(room_name, invite_token)
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="Файл не выбран")

    upload_dir = room_upload_dir(room_name)
    upload_dir.mkdir(parents=True, exist_ok=True)

    attachment_id = uuid4().hex
    ext = Path(filename).suffix
    stored_name = f"{attachment_id}{ext}"
    destination = upload_dir / stored_name

    size_bytes = 0
    try:
        with destination.open("wb") as target:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > settings.max_attachment_size_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Максимальный размер файла — {settings.max_attachment_size_mb} МБ",
                    )
                target.write(chunk)
    except Exception:
        if destination.exists():
            destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    attachment = AttachmentRecord(
        attachment_id=attachment_id,
        original_name=filename,
        stored_name=stored_name,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=size_bytes,
    )
    store.add_attachment(room_name, attachment)
    author = display_name.strip() or "Участник"
    store.add_chat_event(
        room_name,
        ChatEventRecord(
            event_type="file",
            author=author,
            attachment_id=attachment_id,
            file_name=filename,
        ),
    )
    return build_attachment_response(room_name, attachment)


@app.get("/api/calls/{room_name}/attachments/{attachment_id}")
def download_attachment(room_name: str, attachment_id: str, invite_token: str):
    ensure_call_access(room_name, invite_token)
    attachment = store.get_attachment(room_name, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    file_path = room_upload_dir(room_name) / attachment.stored_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(
        path=file_path,
        filename=attachment.original_name,
        media_type=attachment.content_type or "application/octet-stream",
    )


@app.post("/api/calls/{room_name}/finish")
def finish_call(room_name: str, payload: FinishCallRequest) -> dict[str, str]:
    call = store.get(room_name)
    if call is None or not call.is_active:
        raise HTTPException(status_code=404, detail="Call not found")
    if payload.invite_token != call.invite_token:
        raise HTTPException(status_code=403, detail="Invalid invite token")

    alert_status = "disabled"
    if settings.telegram_alerting_available and call.telegram_alert_enabled:
        try:
            send_finish_alert(call)
            alert_status = "sent"
        except Exception:
            alert_status = "failed"

    store.clear_attachments(room_name)
    upload_dir = room_upload_dir(room_name)
    if upload_dir.exists():
        rmtree(upload_dir, ignore_errors=True)
    store.deactivate(room_name)
    return {"status": "finished", "telegram_alert_status": alert_status}
