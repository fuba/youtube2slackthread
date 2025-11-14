"""YouTube video downloader module."""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

import yt_dlp


logger = logging.getLogger(__name__)


class DownloadError(Exception):
    """Exception raised for download failures."""
    pass


class YouTubeDownloader:
    """Downloads YouTube videos using yt-dlp."""

    def __init__(self, output_dir: str = "./downloads", format_spec: str = "best"):
        """Initialize the downloader.
        
        Args:
            output_dir: Directory to save downloaded videos
            format_spec: yt-dlp format specification
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.format_spec = format_spec
        
        self.ydl_opts = {
            'format': format_spec,
            'outtmpl': str(self.output_dir / '%(title)s.%(ext)s'),
            'quiet': False,
            'no_warnings': False,
            'extract_flat': False,
            'ignoreerrors': False,
            'retries': 3,
            'fragment_retries': 3,
            'skip_unavailable_fragments': True,
            'keepvideo': False,
            'overwrites': True,
            'continuedl': True,
            'noprogress': False,
            'progress_hooks': [self._progress_hook],
            'postprocessors': [],
        }

    def _progress_hook(self, d: Dict[str, Any]) -> None:
        """Hook to track download progress."""
        if d['status'] == 'downloading':
            percent = d.get('_percent_str', 'N/A')
            speed = d.get('_speed_str', 'N/A')
            eta = d.get('_eta_str', 'N/A')
            logger.info(f"Downloading: {percent} at {speed} ETA: {eta}")
        elif d['status'] == 'finished':
            logger.info(f"Download completed: {d.get('filename', 'unknown')}")

    def download(self, url: str) -> Dict[str, Any]:
        """Download a single video.
        
        Args:
            url: YouTube video URL
            
        Returns:
            Dictionary with video information and file path
            
        Raises:
            DownloadError: If download fails
        """
        if not self.is_valid_url(url):
            raise DownloadError(f"Invalid YouTube URL: {url}")

        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                logger.info(f"Starting download: {url}")
                info = ydl.extract_info(url, download=True)
                
                if not info:
                    raise DownloadError("No video information extracted")

                # Determine the actual output filename
                title = self._clean_filename(info.get('title', 'unknown'))
                ext = info.get('ext', 'mp4')
                video_path = self.output_dir / f"{title}.{ext}"
                
                # Return video information
                return {
                    'video_path': str(video_path),
                    'title': info.get('title', 'Unknown'),
                    'video_id': info.get('id', ''),
                    'duration': info.get('duration', 0),
                    'uploader': info.get('uploader', ''),
                    'upload_date': info.get('upload_date', ''),
                    'description': info.get('description', ''),
                    'url': url
                }

        except Exception as e:
            logger.error(f"Download failed: {e}")
            raise DownloadError(f"Failed to download video: {e}")

    def download_playlist(self, url: str) -> List[Dict[str, Any]]:
        """Download all videos from a playlist.
        
        Args:
            url: YouTube playlist URL
            
        Returns:
            List of dictionaries with video information
        """
        if not self.is_valid_url(url):
            raise DownloadError(f"Invalid YouTube URL: {url}")

        results = []
        
        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                logger.info(f"Extracting playlist info: {url}")
                playlist_info = ydl.extract_info(url, download=True)
                
                if not playlist_info:
                    raise DownloadError("No playlist information extracted")

                # Handle playlist
                if playlist_info.get('_type') == 'playlist':
                    entries = playlist_info.get('entries', [])
                    logger.info(f"Found {len(entries)} videos in playlist")
                    
                    for entry in entries:
                        if entry:
                            title = self._clean_filename(entry.get('title', 'unknown'))
                            ext = entry.get('ext', 'mp4')
                            video_path = self.output_dir / f"{title}.{ext}"
                            
                            results.append({
                                'video_path': str(video_path),
                                'title': entry.get('title', 'Unknown'),
                                'video_id': entry.get('id', ''),
                                'duration': entry.get('duration', 0),
                                'uploader': entry.get('uploader', ''),
                                'upload_date': entry.get('upload_date', ''),
                            })
                else:
                    # Single video
                    title = self._clean_filename(playlist_info.get('title', 'unknown'))
                    ext = playlist_info.get('ext', 'mp4')
                    video_path = self.output_dir / f"{title}.{ext}"
                    
                    results.append({
                        'video_path': str(video_path),
                        'title': playlist_info.get('title', 'Unknown'),
                        'video_id': playlist_info.get('id', ''),
                        'duration': playlist_info.get('duration', 0),
                        'uploader': playlist_info.get('uploader', ''),
                        'upload_date': playlist_info.get('upload_date', ''),
                    })

                return results

        except Exception as e:
            logger.error(f"Playlist download failed: {e}")
            raise DownloadError(f"Failed to download playlist: {e}")

    def get_info(self, url: str) -> Dict[str, Any]:
        """Get video information without downloading.
        
        Args:
            url: YouTube video URL
            
        Returns:
            Dictionary with video information
        """
        if not self.is_valid_url(url):
            raise DownloadError(f"Invalid YouTube URL: {url}")

        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if not info:
                    raise DownloadError("No video information extracted")

                return {
                    'title': info.get('title', 'Unknown'),
                    'video_id': info.get('id', ''),
                    'duration': info.get('duration', 0),
                    'uploader': info.get('uploader', ''),
                    'upload_date': info.get('upload_date', ''),
                    'view_count': info.get('view_count', 0),
                    'like_count': info.get('like_count', 0),
                    'description': info.get('description', ''),
                    'thumbnail': info.get('thumbnail', ''),
                    'is_live': info.get('is_live', False),
                    'url': url
                }

        except Exception as e:
            logger.error(f"Failed to get video info: {e}")
            raise DownloadError(f"Failed to get video information: {e}")

    def is_valid_url(self, url: str) -> bool:
        """Check if the URL is a valid YouTube URL.
        
        Args:
            url: URL to validate
            
        Returns:
            True if valid YouTube URL
        """
        youtube_patterns = [
            r'^https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+',
            r'^https?://(?:www\.)?youtube\.com/playlist\?list=[\w-]+',
            r'^https?://youtu\.be/[\w-]+',
            r'^https?://(?:www\.)?youtube\.com/shorts/[\w-]+',
        ]
        
        return any(re.match(pattern, url) for pattern in youtube_patterns)

    def _clean_filename(self, filename: str) -> str:
        """Clean filename for filesystem safety.
        
        Args:
            filename: Original filename
            
        Returns:
            Cleaned filename
        """
        # Remove or replace problematic characters
        cleaned = re.sub(r'[<>:"/\\|?*]', '_', filename)
        # Remove control characters
        cleaned = re.sub(r'[\x00-\x1f\x80-\x9f]', '', cleaned)
        # Limit length
        if len(cleaned) > 200:
            cleaned = cleaned[:200]
        # Remove trailing dots and spaces (Windows compatibility)
        cleaned = cleaned.strip('. ')
        
        return cleaned or 'unknown'