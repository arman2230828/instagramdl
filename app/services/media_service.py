import logging
import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple, List
import instaloader
from cachetools import TTLCache
from app.models.schemas import ProcessResponse, MediaItem

logger = logging.getLogger(__name__)

# Cache for metadata (10 minutes)
_cache = TTLCache(maxsize=100, ttl=600)

def get_cookie_path() -> Optional[str]:
    """Finds cookies.txt in multiple possible locations."""
    possible_paths = [
        os.path.join(os.getcwd(), 'cookies.txt'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'cookies.txt'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'cookies.txt'),
        '/app/cookies.txt'
    ]
    for path in possible_paths:
        if os.path.exists(path):
            logger.info(f"Found cookies.txt at: {path}")
            return path
    return None

def parse_cookies_txt(cookie_path: Optional[str]) -> dict:
    """Parses a Netscape cookies.txt file into a dictionary."""
    cookies = {}
    if not cookie_path or not os.path.exists(cookie_path):
        return cookies
    try:
        with open(cookie_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip() or line.startswith('#'):
                    continue
                parts = line.strip().split('\t')
                if len(parts) >= 7:
                    domain = parts[0]
                    if 'instagram.com' in domain:
                        name = parts[5]
                        value = parts[6]
                        cookies[name] = value
        logger.info(f"Successfully parsed {len(cookies)} Instagram cookies from cookies.txt")
    except Exception as e:
        logger.error(f"Error parsing cookies.txt: {e}")
    return cookies

def clean_url(url: str) -> str:
    """Decodes escaped slashes and unicode characters in URLs."""
    if not url:
        return ""
    url = url.replace('\\/', '/')
    url = url.replace('\\u0026', '&')
    return url

class MediaExtractor:
    """Base class for extractors."""
    async def extract(self, url: str) -> dict:
        raise NotImplementedError

class InstaloaderExtractor(MediaExtractor):
    """Extraction using the official instaloader library (supports cookies.txt)."""
    def __init__(self):
        self.L = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False
        )
        
        # Load cookies into Instaloader context if available
        cookie_path = get_cookie_path()
        if cookie_path:
            cookies = parse_cookies_txt(cookie_path)
            for name, value in cookies.items():
                self.L.context._session.cookies.set(name, value, domain='.instagram.com')
            logger.info("InstaloaderExtractor: Loaded cookies into Instaloader context")

    async def extract(self, url: str) -> dict:
        match = re.search(r'/(?:p|reel|tv)/([A-Za-z0-9_-]+)', url)
        if not match:
            raise Exception("Could not parse shortcode from URL")
        shortcode = match.group(1)
        
        logger.info(f"InstaloaderExtractor: Fetching metadata for shortcode: {shortcode}")
        
        def _fetch():
            post = instaloader.Post.from_shortcode(self.L.context, shortcode)
            like_count = post.likes
            title = post.caption or "Instagram Media"
            
            if post.is_video:
                return {
                    'title': title,
                    'thumbnail': post.url,
                    'url': post.video_url,
                    'ext': 'mp4',
                    'vcodec': 'h264',
                    'like_count': like_count
                }
            else:
                if post.mediacount > 1:
                    entries = []
                    for node in post.get_sidecar_nodes():
                        entry_url = node.video_url if node.is_video else node.display_url
                        entries.append({
                            'url': entry_url,
                            'thumbnail': node.display_url,
                            'vcodec': 'h264' if node.is_video else 'none',
                            'ext': 'mp4' if node.is_video else 'jpg'
                        })
                    return {
                        'title': title,
                        'entries': entries,
                        'like_count': like_count
                    }
                else:
                    return {
                        'title': title,
                        'thumbnail': post.url,
                        'url': post.url,
                        'ext': 'jpg',
                        'vcodec': 'none',
                        'like_count': like_count
                    }
                    
        return await asyncio.to_thread(_fetch)

class MediaService:
    """
    Service for media processing using Instaloader.
    """
    
    @staticmethod
    def _normalize_info(info_dict: dict) -> Tuple[str, str, str, List[MediaItem]]:
        """Extracts standard fields from a raw info dictionary."""
        items = []
        media_title = info_dict.get('title') or info_dict.get('description') or 'Instagram Media'
        if len(media_title) > 100:
            media_title = media_title[:97] + "..."
            
        thumbnail_url = clean_url(info_dict.get('thumbnail') or info_dict.get('thumbnails', [{}])[0].get('url') or '')
        action_url = clean_url(info_dict.get('url'))
        
        if 'entries' in info_dict and info_dict['entries']:
            for entry in info_dict['entries']:
                if not entry:
                    continue
                entry_thumb = clean_url(entry.get('thumbnail') or entry.get('thumbnails', [{}])[0].get('url') or '')
                entry_url = clean_url(entry.get('url'))
                if not entry_url and 'formats' in entry and entry['formats']:
                    entry_url = clean_url(entry['formats'][-1].get('url', '#'))
                
                is_vid = entry.get('vcodec') != 'none' or (entry.get('ext') in ['mp4', 'webm'])
                items.append(MediaItem(thumbnail_url=entry_thumb, action_url=entry_url, is_video=is_vid))
                
            if items:
                thumbnail_url = thumbnail_url or items[0].thumbnail_url
                action_url = action_url or items[0].action_url
        else:
            if not action_url and 'formats' in info_dict and info_dict['formats']:
                formats = [f for f in info_dict['formats'] if f.get('url')]
                if formats:
                    action_url = clean_url(formats[-1].get('url', '#'))
            elif not action_url:
                action_url = '#'
            
            is_vid = info_dict.get('vcodec') != 'none' or (info_dict.get('ext') in ['mp4', 'webm'])
            items.append(MediaItem(thumbnail_url=thumbnail_url, action_url=action_url, is_video=is_vid))
            
        return media_title, thumbnail_url, action_url, items

    @staticmethod
    async def process_url(url: str, mode: str = "reel") -> ProcessResponse:
        url = url.strip()
        if "instagram.com" in url:
            base_url = url.split('?')[0]
            url = base_url.rstrip('/') + '/'
            
        logger.info(f"Processing normalized URL: {url} (mode: {mode})")
        
        if url in _cache:
            logger.info(f"Cache hit for {url}")
            return _cache[url]
            
        extractor = InstaloaderExtractor()
        
        try:
            info_dict = await extractor.extract(url)
            if not info_dict:
                raise Exception("No media extracted by Instaloader")
                
            media_title, thumbnail_url, action_url, items = MediaService._normalize_info(info_dict)
            timestamp_str = datetime.now(timezone.utc).isoformat()
            
            response = ProcessResponse(
                success=True,
                message="Process completed successfully.",
                media_title=media_title,
                thumbnail_url=thumbnail_url,
                action_url=action_url,
                like_count=info_dict.get('like_count'),
                items=items,
                timestamp=timestamp_str
            )
            
            _cache[url] = response
            return response
            
        except Exception as e:
            logger.error(f"Instaloader extraction failed: {e}")
            err_msg = str(e).lower()
            user_msg = "Failed to process. Make sure the profile is public and the URL is correct."
            
            if "login" in err_msg or "403" in err_msg or "connection" in err_msg:
                user_msg = "Instagram blocked the request. Please upload a valid cookies.txt file to the project root to authenticate."
                
            return ProcessResponse(
                success=False,
                message=user_msg
            )
