from fastapi import APIRouter, Request, HTTPException, Response
from fastapi.responses import StreamingResponse
from app.models.schemas import ProcessRequest, ProcessResponse
from app.services.media_service import MediaService
import logging
import urllib.request
import asyncio

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/proxy-image")
async def proxy_image(url: str):
    """
    Proxies image requests to bypass CORS and hotlinking restrictions.
    """
    def fetch_image():
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read(), response.headers.get_content_type()
            
    try:
        image_data, content_type = await asyncio.to_thread(fetch_image)
        return Response(content=image_data, media_type=content_type)
    except Exception as e:
        logger.error(f"Failed to proxy image {url}: {e}")
        raise HTTPException(status_code=404, detail="Image not found")

@router.get("/proxy-download")
def proxy_download(url: str, title: str = "media", ext: str = "mp4"):
    """
    Proxies video downloads to bypass CORS and force direct file download instead of opening in a new tab.
    """
    def stream_file():
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                while True:
                    chunk = response.read(65536) # 64KB chunks
                    if not chunk:
                        break
                    yield chunk
        except Exception as e:
            logger.error(f"Failed to stream video {url}: {e}")
            
    content_type = "video/mp4" if ext == "mp4" else f"image/{ext}"
    headers = {
        "Content-Disposition": f'attachment; filename="{title}.{ext}"'
    }
    return StreamingResponse(stream_file(), headers=headers, media_type=content_type)
@router.post("/process", response_model=ProcessResponse)
async def process_media(request: Request, payload: ProcessRequest):
    """
    Endpoint to process a given media URL.
    Rate limiting should ideally be applied here.
    """
    limiter = request.app.state.limiter
    # Rate limit: 10 requests per minute per IP
    # (In slowapi, you usually decorate the route, but since it's dynamic here, we use the decorator format)
    
    try:
        response = await MediaService.process_url(str(payload.url), mode=payload.mode)
        if not response.success:
            # We return a 400 for bad processing to trigger error card
            raise HTTPException(status_code=400, detail=response.message)
        return response
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error processing URL: {e}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred during processing.")

@router.get("/health")
async def health_check():
    """
    Health check endpoint for Render/Docker.
    """
    return {"status": "ok", "service": "InstaDL"}
