"""
YouTube integration module:
- Search via YouTube Data API v3 search.list endpoint
- Link drop-in metadata fetch via public oEmbed endpoint (no API key needed)
- Just-in-time audio stream resolution via yt-dlp (best audio-only format)
"""

import sys
import os
import re
import json
import html
from typing import Optional, List, Dict, Any
import requests
import yt_dlp


class YouTubeError(Exception):
    """Base exception for YouTube operations."""
    pass


class MissingApiKeyError(YouTubeError):
    """Raised when YouTube Data API key is missing or not configured."""
    pass


class InvalidApiKeyError(YouTubeError):
    """Raised when YouTube Data API key is invalid or quota is exceeded."""
    pass


class InvalidYouTubeUrlError(YouTubeError):
    """Raised when pasted link is not a valid YouTube video URL."""
    pass


class AudioResolutionError(YouTubeError):
    """Raised when yt-dlp fails to resolve an audio-only stream."""
    pass


def get_api_key(config_path: Optional[str] = None) -> Optional[str]:
    """
    Read YouTube Data API key from environment variable or local JSON config files.
    Checks config.json first, and falls back to config.json.example if populated.
    Handles relative paths correctly regardless of the caller's working directory.
    """
    env_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if env_key and not env_key.startswith("YOUR_"):
        return env_key

    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    candidates = []
    if config_path:
        candidates.append(config_path)
        if not os.path.isabs(config_path):
            candidates.append(os.path.join(base_dir, config_path))
    else:
        candidates.extend([
            os.path.join(base_dir, "config.json"),
            "config.json",
            os.path.join(base_dir, "config.json.example"),
            "config.json.example",
        ])

    for path in candidates:
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    key = (data.get("youtube_api_key") or data.get("api_key") or "").strip()
                    if key and not key.startswith("YOUR_"):
                        return key
            except Exception:
                pass

    return None


def extract_video_id(url_or_id: str) -> Optional[str]:
    """
    Extract 11-character YouTube video ID from various URL formats or raw ID.
    Supports:
      - https://www.youtube.com/watch?v=VIDEO_ID
      - https://youtu.be/VIDEO_ID
      - https://www.youtube.com/embed/VIDEO_ID
      - https://www.youtube.com/shorts/VIDEO_ID
      - raw 11-character ID
    """
    if not url_or_id:
        return None
    text = url_or_id.strip()

    patterns = [
        r'(?:v=|\/v\/|youtu\.be\/|embed\/|\/shorts\/|\/watch\?.*v=)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$'
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def fetch_oembed(url_or_id: str) -> Dict[str, Any]:
    """
    Fetch metadata (title, thumbnail, author) for a video using YouTube's public oEmbed endpoint.
    Requires no API key and does not consume Data API quota.
    """
    video_id = extract_video_id(url_or_id)
    if not video_id:
        raise InvalidYouTubeUrlError("The entered text is not a valid YouTube video link or ID.")

    oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"

    try:
        response = requests.get(oembed_url, timeout=7)
    except requests.RequestException as e:
        raise InvalidYouTubeUrlError(f"Network error contacting YouTube oEmbed: {e}")

    if response.status_code == 404:
        raise InvalidYouTubeUrlError("Video not found or private.")
    elif response.status_code != 200:
        raise InvalidYouTubeUrlError(f"YouTube returned error {response.status_code} for this link.")

    try:
        data = response.json()
    except Exception:
        raise InvalidYouTubeUrlError("Received invalid response from YouTube oEmbed endpoint.")

    title = data.get("title", f"YouTube Video ({video_id})")
    author = data.get("author_name", "YouTube")
    thumbnail = data.get("thumbnail_url") or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

    return {
        "video_id": video_id,
        "title": title,
        "thumbnail_url": thumbnail,
        "channel": author,
        "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
    }


def search_videos(query: str, max_results: int = 6, api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Search YouTube videos using YouTube Data API v3 search.list endpoint.
    Returns list of {video_id, title, thumbnail_url, channel, webpage_url}.
    """
    if not api_key:
        api_key = get_api_key()

    if not api_key:
        raise MissingApiKeyError(
            "YouTube Data API key is missing. Add your API key to config.json to enable search."
        )

    clean_query = query.strip()
    if not clean_query:
        return []

    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "type": "video",
        "maxResults": min(10, max(1, max_results)),
        "q": clean_query,
        "key": api_key,
    }

    try:
        response = requests.get(url, params=params, timeout=8)
    except requests.RequestException as e:
        raise YouTubeError(f"Network error during search: {e}")

    if response.status_code in (400, 403):
        try:
            err_data = response.json().get("error", {})
            err_msg = err_data.get("message", "API key invalid or quota exceeded.")
        except Exception:
            err_msg = f"HTTP {response.status_code} authorization error."
        raise InvalidApiKeyError(f"YouTube API Error: {err_msg}")
    elif response.status_code != 200:
        raise YouTubeError(f"Search request failed with HTTP {response.status_code}.")

    try:
        data = response.json()
    except Exception:
        raise YouTubeError("Invalid JSON received from YouTube Data API.")

    results: List[Dict[str, Any]] = []
    for item in data.get("items", []):
        vid = item.get("id", {}).get("videoId")
        if not vid:
            continue
        snippet = item.get("snippet", {})
        title = html.unescape(snippet.get("title", "Untitled Video"))
        channel = html.unescape(snippet.get("channelTitle", "YouTube"))
        thumbnails = snippet.get("thumbnails", {})
        thumb_url = (
            thumbnails.get("medium", {}).get("url")
            or thumbnails.get("default", {}).get("url")
            or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
        )
        results.append({
            "video_id": vid,
            "title": title,
            "thumbnail_url": thumb_url,
            "channel": channel,
            "webpage_url": f"https://www.youtube.com/watch?v={vid}",
        })

    return results


def resolve_audio_stream(video_id_or_url: str) -> str:
    """
    Resolve best audio-only direct stream URL via yt-dlp just-in-time.
    Never selects video+audio stream.
    """
    video_id = extract_video_id(video_id_or_url)
    target_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else video_id_or_url

    ydl_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(target_url, download=False)
            if not info:
                raise AudioResolutionError("Could not extract stream info from video.")

            stream_url = info.get("url")
            if not stream_url and "formats" in info:
                for fmt in info["formats"]:
                    if fmt.get("vcodec") == "none" and fmt.get("acodec") != "none" and fmt.get("url"):
                        stream_url = fmt.get("url")
                        break

            if not stream_url:
                raise AudioResolutionError("No suitable audio-only format was found.")

            return stream_url
    except yt_dlp.utils.YoutubeDLError as e:
        raise AudioResolutionError(f"yt-dlp extraction failed: {e}")
    except Exception as e:
        raise AudioResolutionError(f"Failed to resolve audio stream: {e}")


resolve_url_metadata = fetch_oembed
extract_audio_stream_url = resolve_audio_stream

