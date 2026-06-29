from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
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
        return JSONResponse(
            status_code=404,
            content={"success": False, "message": "Image not found"}
        )

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

@router.post("/process")
async def process_media(request: Request, payload: ProcessRequest):
    """
    Endpoint to process a given media URL.
    """
    logger.info(f"POST /api/process - Received payload: {payload.dict()}")
    
    url_str = str(payload.url).strip()
    if not url_str:
        logger.warning("POST /api/process - Validation failure: Empty URL provided")
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "message": "The Instagram URL cannot be empty.",
                "reason": "validation_failure"
            }
        )
        
    if "instagram.com" not in url_str:
        logger.warning(f"POST /api/process - Validation failure: Non-Instagram URL provided: {url_str}")
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "message": "Only valid Instagram links (Reels, Posts, Videos) are supported.",
                "reason": "unsupported_url"
            }
        )

    try:
        response = await MediaService.process_url(url_str, mode=payload.mode)
        if not response.success:
            logger.error(f"POST /api/process - Extraction failure for URL {url_str}. Message: {response.message}")
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": response.message,
                    "reason": "extraction_failure"
                }
            )
            
        logger.info(f"POST /api/process - Successful extraction for URL {url_str}")
        return response
        
    except Exception as e:
        logger.exception(f"POST /api/process - Unexpected internal error for URL {url_str}: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An unexpected error occurred during processing.",
                "reason": "internal_error"
            }
        )

@router.get("/health")
async def health_check():
    """
    Health check endpoint for Render/Docker.
    """
    return {"status": "ok", "service": "InstaDL"}
