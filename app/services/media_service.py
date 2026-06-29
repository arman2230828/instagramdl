import logging
import asyncio
import random
import os
import re
import json
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple, List
import yt_dlp
import httpx
from bs4 import BeautifulSoup
from cachetools import TTLCache
from app.models.schemas import ProcessResponse, MediaItem

logger = logging.getLogger(__name__)

# Cache for metadata (10 minutes)
_cache = TTLCache(maxsize=100, ttl=600)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.2; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36"
]

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
    """Parses a Netscape cookies.txt file into a dictionary for httpx."""
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
                    # Target instagram.com cookies
                    if 'instagram.com' in domain:
                        name = parts[5]
                        value = parts[6]
                        cookies[name] = value
        logger.info(f"Successfully parsed {len(cookies)} Instagram cookies from cookies.txt")
    except Exception as e:
        logger.error(f"Error parsing cookies.txt: {e}")
    return cookies

class MediaExtractor:
    """Base class for extractors."""
    async def extract(self, url: str) -> dict:
        raise NotImplementedError

class YtDlpExtractor(MediaExtractor):
    """Extraction using yt-dlp."""
    def _extract_sync(self, url: str) -> dict:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'noplaylist': True,
            'socket_timeout': 15,
            'format': 'best',
            'retries': 3,
            'extractor_retries': 3,
            'http_headers': {
                'User-Agent': random.choice(USER_AGENTS),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
            }
        }
        
        cookie_path = get_cookie_path()
        if cookie_path:
            ydl_opts['cookiefile'] = cookie_path
            
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)
            
    async def extract(self, url: str) -> dict:
        return await asyncio.to_thread(self._extract_sync, url)

class GraphQLScraper(MediaExtractor):
    """Extraction using Instagram's ?__a=1&__d=dis endpoint."""
    async def extract(self, url: str) -> dict:
        # Ensure trailing slash for the API endpoint
        base_url = url.split('?')[0].rstrip('/') + '/'
        api_url = f"{base_url}?__a=1&__d=dis"
        
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "X-IG-App-ID": "936619743392459", 
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        
        cookie_path = get_cookie_path()
        cookies = parse_cookies_txt(cookie_path)
        
        async with httpx.AsyncClient(cookies=cookies, follow_redirects=True, timeout=15.0) as client:
            resp = await client.get(api_url, headers=headers)
            resp.raise_for_status()
            
            try:
                data = resp.json()
            except ValueError:
                raise Exception("GraphQL Scraper failed: response is not JSON")
            
            # 1. Handle modern {"items": [...]} structure
            if 'items' in data and len(data['items']) > 0:
                item = data['items'][0]
                # Carousel/Slideshow post
                if 'carousel_media' in item:
                    entries = []
                    for sub_item in item['carousel_media']:
                        is_vid = 'video_versions' in sub_item
                        entry_url = sub_item['video_versions'][0]['url'] if is_vid else sub_item['image_versions2']['candidates'][0]['url']
                        entries.append({
                            'url': entry_url,
                            'thumbnail': sub_item['image_versions2']['candidates'][0]['url'],
                            'vcodec': 'h264' if is_vid else 'none',
                            'ext': 'mp4' if is_vid else 'jpg'
                        })
                    return {
                        'title': item.get('caption', {}).get('text', 'Instagram Media') if item.get('caption') else 'Instagram Media',
                        'entries': entries
                    }
                else:
                    is_vid = 'video_versions' in item
                    media_url = item['video_versions'][0]['url'] if is_vid else item['image_versions2']['candidates'][0]['url']
                    return {
                        'title': item.get('caption', {}).get('text', 'Instagram Media') if item.get('caption') else 'Instagram Media',
                        'thumbnail': item['image_versions2']['candidates'][0]['url'],
                        'url': media_url,
                        'ext': 'mp4' if is_vid else 'jpg',
                        'vcodec': 'h264' if is_vid else 'none'
                    }
            
            # 2. Handle legacy {"graphql": {"shortcode_media": ...}} structure
            elif 'graphql' in data and 'shortcode_media' in data['graphql']:
                media = data['graphql']['shortcode_media']
                
                # Check if it's a carousel (multiple images/videos)
                if 'edge_sidecar_to_children' in media:
                    entries = []
                    for edge in media['edge_sidecar_to_children']['edges']:
                        node = edge['node']
                        entry_url = node.get('video_url') or node.get('display_url')
                        entries.append({
                            'url': entry_url,
                            'thumbnail': node.get('display_url'),
                            'vcodec': 'h264' if node.get('is_video') else 'none',
                            'ext': 'mp4' if node.get('is_video') else 'jpg'
                        })
                    return {
                        'title': media.get('title') or 'Instagram Media',
                        'entries': entries
                    }
                else:
                    vid_url = media.get('video_url')
                    if vid_url:
                        return {
                            'title': media.get('title') or 'Instagram Media',
                            'thumbnail': media.get('display_url', ''),
                            'url': vid_url,
                            'ext': 'mp4',
                            'vcodec': 'h264'
                        }
                    else:
                        return {
                            'title': media.get('title') or 'Instagram Media',
                            'thumbnail': media.get('display_url', ''),
                            'url': media.get('display_url', ''),
                            'ext': 'jpg',
                            'vcodec': 'none'
                        }
            
            raise Exception("GraphQL Scraper failed to find media in JSON structure.")

class HtmlFallbackExtractor(MediaExtractor):
    """Extraction using beautifulsoup4 and regex on the raw HTML."""
    async def extract(self, url: str) -> dict:
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1"
        }
        
        cookie_path = get_cookie_path()
        cookies = parse_cookies_txt(cookie_path)
        
        async with httpx.AsyncClient(cookies=cookies, follow_redirects=True, timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            html = resp.text
            
            # Try to parse Open Graph tags
            soup = BeautifulSoup(html, 'html.parser')
            og_video = soup.find('meta', property='og:video')
            og_image = soup.find('meta', property='og:image')
            og_title = soup.find('meta', property='og:title')
            
            if og_video and og_video.get('content'):
                return {
                    'title': og_title.get('content') if og_title else 'Instagram Media',
                    'thumbnail': og_image.get('content') if og_image else '',
                    'url': og_video.get('content'),
                    'ext': 'mp4',
                    'vcodec': 'h264'
                }
            
            # If no OG video, look for raw JSON blobs
            json_pattern = re.compile(r'window\._sharedData\s*=\s*({.+?});</script>')
            match = json_pattern.search(html)
            if match:
                data = json.loads(match.group(1))
                try:
                    post_data = data['entry_data']['PostPage'][0]['graphql']['shortcode_media']
                    vid_url = post_data.get('video_url')
                    if vid_url:
                        return {
                            'title': 'Instagram Media',
                            'thumbnail': post_data.get('display_url', ''),
                            'url': vid_url,
                            'ext': 'mp4',
                            'vcodec': 'h264'
                        }
                except KeyError:
                    pass
            
            raise Exception("HTML Fallback Extractor failed to find media.")

class MediaService:
    """
    Service for media processing with robust fallback mechanisms.
    """
    
    @staticmethod
    def _normalize_info(info_dict: dict) -> Tuple[str, str, str, List[MediaItem]]:
        """Extracts standard fields from a raw info dictionary (either from yt-dlp or custom scrapers)."""
        items = []
        media_title = info_dict.get('title') or info_dict.get('description') or 'Instagram Media'
        # Limit title length
        if len(media_title) > 100:
            media_title = media_title[:97] + "..."
            
        thumbnail_url = info_dict.get('thumbnail') or info_dict.get('thumbnails', [{}])[0].get('url') or ''
        action_url = info_dict.get('url')
        
        # If the post is a carousel/playlist, extract all entries
        if 'entries' in info_dict and info_dict['entries']:
            for entry in info_dict['entries']:
                if not entry:
                    continue
                entry_thumb = entry.get('thumbnail') or entry.get('thumbnails', [{}])[0].get('url') or ''
                entry_url = entry.get('url')
                if not entry_url and 'formats' in entry and entry['formats']:
                    entry_url = entry['formats'][-1].get('url', '#')
                
                is_vid = entry.get('vcodec') != 'none' or (entry.get('ext') in ['mp4', 'webm'])
                items.append(MediaItem(thumbnail_url=entry_thumb, action_url=entry_url, is_video=is_vid))
                
            if items:
                thumbnail_url = thumbnail_url or items[0].thumbnail_url
                action_url = action_url or items[0].action_url
        else:
            if not action_url and 'formats' in info_dict and info_dict['formats']:
                # Find the best format
                formats = [f for f in info_dict['formats'] if f.get('url')]
                if formats:
                    action_url = formats[-1].get('url', '#')
            elif not action_url:
                action_url = '#'
            
            is_vid = info_dict.get('vcodec') != 'none' or (info_dict.get('ext') in ['mp4', 'webm'])
            items.append(MediaItem(thumbnail_url=thumbnail_url, action_url=action_url, is_video=is_vid))
            
        return media_title, thumbnail_url, action_url, items

    @staticmethod
    async def process_url(url: str, mode: str = "reel") -> ProcessResponse:
        # Normalize and clean the URL
        url = url.strip()
        if "instagram.com" in url:
            # Remove query parameters and ensure trailing slash
            base_url = url.split('?')[0]
            url = base_url.rstrip('/') + '/'
            
        logger.info(f"Processing normalized URL: {url} (mode: {mode})")
        
        # Check cache
        if url in _cache:
            logger.info(f"Cache hit for {url}")
            return _cache[url]
            
        # Define extraction strategies in order of preference
        extractors = [
            YtDlpExtractor(),
            GraphQLScraper(),
            HtmlFallbackExtractor()
        ]
        
        info_dict = None
        last_error = None
        
        for i, extractor in enumerate(extractors):
            extractor_name = extractor.__class__.__name__
            logger.info(f"Attempt {i+1}: Trying {extractor_name} for {url}")
            try:
                info_dict = await extractor.extract(url)
                if info_dict:
                    logger.info(f"Success with {extractor_name}")
                    break
            except Exception as e:
                logger.warning(f"{extractor_name} failed: {e}")
                last_error = e
                continue
                
        if not info_dict:
            logger.error(f"All extraction methods failed for {url}. Last error: {last_error}")
            
            err_msg = str(last_error).lower()
            user_msg = "Failed to process. Make sure the profile is public and the URL is correct."
            
            if "empty media response" in err_msg or "not exists" in err_msg or "403" in err_msg or "blocked" in err_msg:
                user_msg = "Instagram blocked the request or the account is private. Please ensure the link is correct and the account is public."
                
            return ProcessResponse(
                success=False,
                message=user_msg
            )
            
        try:
            media_title, thumbnail_url, action_url, items = MediaService._normalize_info(info_dict)
            timestamp_str = datetime.now(timezone.utc).isoformat()
            
            response = ProcessResponse(
                success=True,
                message="Process completed successfully.",
                media_title=media_title,
                thumbnail_url=thumbnail_url,
                action_url=action_url,
                items=items,
                timestamp=timestamp_str
            )
            
            # Save to cache
            _cache[url] = response
            return response
            
        except Exception as e:
            logger.error(f"Error normalizing extracted data: {e}")
            return ProcessResponse(
                success=False,
                message="An unexpected error occurred while parsing the media data."
            )
