"""Tests for YouTube downloader module."""

import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest

from youtube2slack.downloader import YouTubeDownloader, DownloadError


class TestYouTubeDownloader:
    """Test cases for YouTubeDownloader."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for downloads."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def downloader(self, temp_dir):
        """Create a YouTubeDownloader instance."""
        return YouTubeDownloader(output_dir=temp_dir)

    def test_init_creates_output_directory(self, temp_dir):
        """Test that initialization creates output directory if it doesn't exist."""
        output_dir = Path(temp_dir) / "new_dir"
        downloader = YouTubeDownloader(output_dir=str(output_dir))
        assert output_dir.exists()
        assert output_dir.is_dir()

    def test_init_with_existing_directory(self, temp_dir):
        """Test initialization with existing directory."""
        downloader = YouTubeDownloader(output_dir=temp_dir)
        assert downloader.output_dir == Path(temp_dir)

    @patch('yt_dlp.YoutubeDL')
    def test_download_video_success(self, mock_ydl_class, downloader, temp_dir):
        """Test successful video download."""
        # Mock YoutubeDL instance
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl
        
        # Mock extract_info and download
        mock_info = {
            'title': 'Test Video',
            'id': 'test123',
            'ext': 'mp4',
            'duration': 120,
            'upload_date': '20240101'
        }
        mock_ydl.extract_info.return_value = mock_info
        
        # Create a dummy file to simulate download
        video_path = Path(temp_dir) / "Test Video.mp4"
        video_path.write_text("dummy video content")
        
        # Test download
        result = downloader.download("https://youtube.com/watch?v=test123")
        
        assert result['video_path'] == str(video_path)
        assert result['title'] == 'Test Video'
        assert result['video_id'] == 'test123'
        assert result['duration'] == 120
        
        # Verify yt-dlp was called correctly
        mock_ydl.extract_info.assert_called_once_with(
            "https://youtube.com/watch?v=test123",
            download=True
        )

    @patch('yt_dlp.YoutubeDL')
    def test_download_video_failure(self, mock_ydl_class, downloader):
        """Test handling of download failure."""
        # Mock YoutubeDL to raise an exception
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.side_effect = Exception("Download failed")
        
        # Test that DownloadError is raised
        with pytest.raises(DownloadError) as exc_info:
            downloader.download("https://youtube.com/watch?v=invalid")
        
        assert "Failed to download video" in str(exc_info.value)

    @patch('yt_dlp.YoutubeDL')
    def test_download_playlist(self, mock_ydl_class, downloader, temp_dir):
        """Test downloading a playlist."""
        # Mock YoutubeDL instance
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl
        
        # Mock playlist info
        mock_playlist_info = {
            '_type': 'playlist',
            'title': 'Test Playlist',
            'entries': [
                {
                    'title': 'Video 1',
                    'id': 'video1',
                    'ext': 'mp4',
                    'duration': 60
                },
                {
                    'title': 'Video 2',
                    'id': 'video2',
                    'ext': 'mp4',
                    'duration': 90
                }
            ]
        }
        mock_ydl.extract_info.return_value = mock_playlist_info
        
        # Create dummy files
        for i in range(2):
            video_path = Path(temp_dir) / f"Video {i+1}.mp4"
            video_path.write_text(f"dummy video {i+1}")
        
        # Test playlist download
        results = downloader.download_playlist("https://youtube.com/playlist?list=test")
        
        assert len(results) == 2
        assert results[0]['title'] == 'Video 1'
        assert results[1]['title'] == 'Video 2'
        assert all('video_path' in r for r in results)

    def test_get_video_info_only(self, downloader):
        """Test getting video info without downloading."""
        with patch('yt_dlp.YoutubeDL') as mock_ydl_class:
            mock_ydl = MagicMock()
            mock_ydl_class.return_value.__enter__.return_value = mock_ydl
            
            mock_info = {
                'title': 'Test Video',
                'id': 'test123',
                'duration': 120,
                'uploader': 'Test Channel',
                'upload_date': '20240101',
                'view_count': 1000
            }
            mock_ydl.extract_info.return_value = mock_info
            
            # Test get_info
            info = downloader.get_info("https://youtube.com/watch?v=test123")
            
            assert info['title'] == 'Test Video'
            assert info['duration'] == 120
            assert info['uploader'] == 'Test Channel'
            
            # Verify download was not called
            mock_ydl.extract_info.assert_called_once_with(
                "https://youtube.com/watch?v=test123",
                download=False
            )

    def test_validate_url(self, downloader):
        """Test URL validation."""
        # Valid URLs
        assert downloader.is_valid_url("https://www.youtube.com/watch?v=test123")
        assert downloader.is_valid_url("https://youtube.com/watch?v=test123")
        assert downloader.is_valid_url("https://youtu.be/test123")
        assert downloader.is_valid_url("https://www.youtube.com/playlist?list=PLtest")
        
        # Invalid URLs
        assert not downloader.is_valid_url("https://example.com/video")
        assert not downloader.is_valid_url("not-a-url")
        assert not downloader.is_valid_url("")

    @patch('yt_dlp.YoutubeDL')
    def test_download_with_format_selection(self, mock_ydl_class, temp_dir):
        """Test downloading with specific format."""
        downloader = YouTubeDownloader(output_dir=temp_dir, format_spec='bestaudio')
        
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl
        
        mock_info = {
            'title': 'Audio Test',
            'id': 'audio123',
            'ext': 'm4a',
            'duration': 180
        }
        mock_ydl.extract_info.return_value = mock_info
        
        # Create dummy audio file
        audio_path = Path(temp_dir) / "Audio Test.m4a"
        audio_path.write_text("dummy audio")
        
        result = downloader.download("https://youtube.com/watch?v=audio123")
        
        assert result['video_path'].endswith('.m4a')
        
        # Check that format was passed to yt-dlp
        ydl_opts = mock_ydl_class.call_args[0][0]
        assert ydl_opts['format'] == 'bestaudio'

    def test_cleanup_filename(self, downloader):
        """Test filename cleaning for filesystem safety."""
        # Test various problematic characters
        assert downloader._clean_filename("Video: Test") == "Video_ Test"
        assert downloader._clean_filename("Video/Test") == "Video_Test"
        assert downloader._clean_filename("Video|Test<>") == "Video_Test__"
        assert downloader._clean_filename("Video\\Test") == "Video_Test"
        assert downloader._clean_filename("Video?Test*") == "Video_Test_"