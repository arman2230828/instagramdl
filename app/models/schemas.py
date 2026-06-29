from pydantic import BaseModel, HttpUrl

class ProcessRequest(BaseModel):
    url: str
    mode: str = "reel"

class MediaItem(BaseModel):
    thumbnail_url: str | None = None
    action_url: str | None = None
    is_video: bool = True

class ProcessResponse(BaseModel):
    success: bool
    message: str
    media_title: str | None = None
    thumbnail_url: str | None = None
    action_url: str | None = None
    items: list[MediaItem] = []
    timestamp: str | None = None
