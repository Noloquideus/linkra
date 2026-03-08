from datetime import timedelta

from livekit import api

from .config import settings


async def create_room_if_needed(room_name: str) -> None:
    lkapi = api.LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    try:
        rooms = await lkapi.room.list_rooms(api.ListRoomsRequest(names=[room_name]))
        if rooms.rooms:
            return
        await lkapi.room.create_room(
            api.CreateRoomRequest(
                name=room_name,
                empty_timeout=settings.room_empty_timeout_seconds,
                max_participants=20,
            )
        )
    finally:
        await lkapi.aclose()


async def build_participant_token(*, room_name: str, identity: str, display_name: str) -> str:
    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity)
        .with_name(display_name)
        .with_ttl(timedelta(hours=settings.call_token_ttl_hours))
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
            )
        )
    )
    return token.to_jwt()
