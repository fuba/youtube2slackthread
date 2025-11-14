"""Tests for main workflow module."""

import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, call
import pytest

from youtube2slack.workflow import (
    YouTube2SlackWorkflow,
    WorkflowConfig,
    ProcessingResult,
    WorkflowError
)


class TestWorkflowConfig:
    """Test cases for WorkflowConfig."""

    def test_from_dict(self):
        """Test creating config from dictionary."""
        config_dict = {
            'youtube': {
                'download_dir': '/tmp/downloads',
                'format': 'bestaudio',
                'keep_video': False
            },
            'whisper': {
                'model': 'small',
                'device': 'cuda',
                'language': 'ja'
            },
            'slack': {
                'webhook_url': 'https://hooks.slack.com/services/T/B/xyz',
                'channel': '#transcriptions',
                'include_timestamps': True
            }
        }
        
        config = WorkflowConfig.from_dict(config_dict)
        
        assert config.download_dir == '/tmp/downloads'
        assert config.video_format == 'bestaudio'
        assert config.keep_video is False
        assert config.whisper_model == 'small'
        assert config.whisper_device == 'cuda'
        assert config.whisper_language == 'ja'
        assert config.slack_webhook == 'https://hooks.slack.com/services/T/B/xyz'
        assert config.slack_channel == '#transcriptions'
        assert config.include_timestamps is True

    def test_from_yaml_file(self, tmp_path):
        """Test loading config from YAML file."""
        yaml_content = """
youtube:
  download_dir: /tmp/yt-downloads
  format: best
  keep_video: true

whisper:
  model: base
  device: cpu
  language: en

slack:
  webhook_url: https://hooks.slack.com/services/TEST/HOOK/URL
  channel: "#videos"
  include_timestamps: false
"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content)
        
        config = WorkflowConfig.from_yaml(str(config_file))
        
        assert config.download_dir == '/tmp/yt-downloads'
        assert config.video_format == 'best'
        assert config.keep_video is True
        assert config.whisper_model == 'base'
        assert config.slack_channel == '#videos'

    def test_default_config(self):
        """Test default configuration values."""
        config = WorkflowConfig()
        
        assert config.download_dir == './downloads'
        assert config.video_format == 'best'
        assert config.keep_video is True
        assert config.whisper_model == 'base'
        assert config.whisper_device is None
        assert config.whisper_language is None
        assert config.slack_channel is None
        assert config.include_timestamps is False


class TestYouTube2SlackWorkflow:
    """Test cases for YouTube2SlackWorkflow."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def workflow_config(self):
        """Create a test workflow configuration."""
        return WorkflowConfig(
            download_dir='./test_downloads',
            video_format='best',
            whisper_model='tiny',
            slack_webhook='https://hooks.slack.com/services/T/B/xyz'
        )

    @pytest.fixture
    def mock_components(self):
        """Create mocked components."""
        with patch('youtube2slack.workflow.YouTubeDownloader') as mock_downloader_class, \
             patch('youtube2slack.workflow.WhisperTranscriber') as mock_transcriber_class, \
             patch('youtube2slack.workflow.SlackClient') as mock_slack_class:
            
            # Create mock instances
            mock_downloader = MagicMock()
            mock_transcriber = MagicMock()
            mock_slack = MagicMock()
            
            # Configure constructors to return mock instances
            mock_downloader_class.return_value = mock_downloader
            mock_transcriber_class.return_value = mock_transcriber
            mock_slack_class.return_value = mock_slack
            
            yield {
                'downloader': mock_downloader,
                'transcriber': mock_transcriber,
                'slack': mock_slack,
                'downloader_class': mock_downloader_class,
                'transcriber_class': mock_transcriber_class,
                'slack_class': mock_slack_class
            }

    def test_init_creates_components(self, workflow_config, mock_components):
        """Test workflow initialization creates all components."""
        workflow = YouTube2SlackWorkflow(workflow_config)
        
        # Verify components were created with correct parameters
        mock_components['downloader_class'].assert_called_once_with(
            output_dir=workflow_config.download_dir,
            format_spec=workflow_config.video_format
        )
        
        mock_components['transcriber_class'].assert_called_once_with(
            model_name=workflow_config.whisper_model,
            device=workflow_config.whisper_device,
            download_root=None
        )
        
        mock_components['slack_class'].assert_called_once_with(
            webhook_url=workflow_config.slack_webhook,
            channel=workflow_config.slack_channel
        )

    def test_process_video_success(self, workflow_config, mock_components, temp_dir):
        """Test successful video processing."""
        # Setup mocks
        video_path = os.path.join(temp_dir, "test_video.mp4")
        Path(video_path).touch()
        
        mock_components['downloader'].download.return_value = {
            'video_path': video_path,
            'title': 'Test Video',
            'video_id': 'abc123',
            'duration': 120,
            'url': 'https://youtube.com/watch?v=abc123'
        }
        
        mock_components['transcriber'].transcribe_video.return_value = {
            'text': 'This is the transcribed text.',
            'language': 'en',
            'segments': [
                {'start': 0, 'end': 5, 'text': 'This is'},
                {'start': 5, 'end': 10, 'text': ' the transcribed text.'}
            ]
        }
        
        mock_components['slack'].send_transcription.return_value = True
        
        # Create workflow and process video
        workflow = YouTube2SlackWorkflow(workflow_config)
        result = workflow.process_video('https://youtube.com/watch?v=abc123')
        
        # Verify result
        assert result.success is True
        assert result.video_url == 'https://youtube.com/watch?v=abc123'
        assert result.video_title == 'Test Video'
        assert result.transcription_text == 'This is the transcribed text.'
        assert result.error is None
        
        # Verify component calls
        mock_components['downloader'].download.assert_called_once_with(
            'https://youtube.com/watch?v=abc123'
        )
        
        mock_components['transcriber'].transcribe_video.assert_called_once()
        
        mock_components['slack'].send_transcription.assert_called_once()
        slack_call_args = mock_components['slack'].send_transcription.call_args[0][0]
        assert slack_call_args['text'] == 'This is the transcribed text.'
        assert slack_call_args['video_title'] == 'Test Video'

    def test_process_video_download_failure(self, workflow_config, mock_components):
        """Test handling of download failure."""
        mock_components['downloader'].download.side_effect = Exception("Download failed")
        
        workflow = YouTube2SlackWorkflow(workflow_config)
        result = workflow.process_video('https://youtube.com/watch?v=invalid')
        
        assert result.success is False
        assert result.video_url == 'https://youtube.com/watch?v=invalid'
        assert "Download failed" in result.error
        
        # Should not call transcriber or slack
        mock_components['transcriber'].transcribe_video.assert_not_called()
        mock_components['slack'].send_transcription.assert_not_called()

    def test_process_video_transcription_failure(self, workflow_config, mock_components, temp_dir):
        """Test handling of transcription failure."""
        video_path = os.path.join(temp_dir, "test_video.mp4")
        Path(video_path).touch()
        
        mock_components['downloader'].download.return_value = {
            'video_path': video_path,
            'title': 'Test Video',
            'video_id': 'abc123',
            'duration': 120
        }
        
        mock_components['transcriber'].transcribe_video.side_effect = Exception(
            "Transcription failed"
        )
        
        workflow = YouTube2SlackWorkflow(workflow_config)
        result = workflow.process_video('https://youtube.com/watch?v=abc123')
        
        assert result.success is False
        assert "Transcription failed" in result.error
        
        # Should not call slack
        mock_components['slack'].send_transcription.assert_not_called()

    def test_process_video_slack_failure(self, workflow_config, mock_components, temp_dir):
        """Test handling of Slack sending failure."""
        video_path = os.path.join(temp_dir, "test_video.mp4")
        Path(video_path).touch()
        
        mock_components['downloader'].download.return_value = {
            'video_path': video_path,
            'title': 'Test Video',
            'video_id': 'abc123',
            'duration': 120
        }
        
        mock_components['transcriber'].transcribe_video.return_value = {
            'text': 'Transcribed text',
            'language': 'en'
        }
        
        mock_components['slack'].send_transcription.side_effect = Exception("Slack error")
        
        workflow = YouTube2SlackWorkflow(workflow_config)
        result = workflow.process_video('https://youtube.com/watch?v=abc123')
        
        assert result.success is False
        assert "Slack error" in result.error
        # But transcription should still be in result
        assert result.transcription_text == 'Transcribed text'

    def test_process_video_cleanup(self, workflow_config, mock_components, temp_dir):
        """Test video cleanup after processing."""
        video_path = os.path.join(temp_dir, "test_video.mp4")
        Path(video_path).touch()
        
        mock_components['downloader'].download.return_value = {
            'video_path': video_path,
            'title': 'Test Video',
            'video_id': 'abc123',
            'duration': 120
        }
        
        mock_components['transcriber'].transcribe_video.return_value = {
            'text': 'Transcribed text',
            'language': 'en'
        }
        
        mock_components['slack'].send_transcription.return_value = True
        
        # Test with keep_video=False
        workflow_config.keep_video = False
        workflow = YouTube2SlackWorkflow(workflow_config)
        result = workflow.process_video('https://youtube.com/watch?v=abc123')
        
        assert result.success is True
        assert not os.path.exists(video_path)  # Video should be deleted

    def test_process_video_keep_video(self, workflow_config, mock_components, temp_dir):
        """Test keeping video after processing."""
        video_path = os.path.join(temp_dir, "test_video.mp4")
        Path(video_path).touch()
        
        mock_components['downloader'].download.return_value = {
            'video_path': video_path,
            'title': 'Test Video',
            'video_id': 'abc123',
            'duration': 120
        }
        
        mock_components['transcriber'].transcribe_video.return_value = {
            'text': 'Transcribed text',
            'language': 'en'
        }
        
        mock_components['slack'].send_transcription.return_value = True
        
        # Test with keep_video=True
        workflow_config.keep_video = True
        workflow = YouTube2SlackWorkflow(workflow_config)
        result = workflow.process_video('https://youtube.com/watch?v=abc123')
        
        assert result.success is True
        assert os.path.exists(video_path)  # Video should still exist

    def test_process_playlist(self, workflow_config, mock_components, temp_dir):
        """Test processing a playlist."""
        # Setup playlist download mock
        video1_path = os.path.join(temp_dir, "video1.mp4")
        video2_path = os.path.join(temp_dir, "video2.mp4")
        Path(video1_path).touch()
        Path(video2_path).touch()
        
        mock_components['downloader'].download_playlist.return_value = [
            {
                'video_path': video1_path,
                'title': 'Video 1',
                'video_id': 'vid1',
                'duration': 60
            },
            {
                'video_path': video2_path,
                'title': 'Video 2',
                'video_id': 'vid2',
                'duration': 90
            }
        ]
        
        mock_components['transcriber'].transcribe_video.side_effect = [
            {'text': 'Transcription 1', 'language': 'en'},
            {'text': 'Transcription 2', 'language': 'en'}
        ]
        
        mock_components['slack'].send_transcription.return_value = True
        
        workflow = YouTube2SlackWorkflow(workflow_config)
        results = workflow.process_playlist('https://youtube.com/playlist?list=PLtest')
        
        assert len(results) == 2
        assert all(r.success for r in results)
        assert results[0].video_title == 'Video 1'
        assert results[1].video_title == 'Video 2'
        
        # Verify calls
        mock_components['downloader'].download_playlist.assert_called_once_with(
            'https://youtube.com/playlist?list=PLtest'
        )
        assert mock_components['transcriber'].transcribe_video.call_count == 2
        assert mock_components['slack'].send_transcription.call_count == 2

    def test_process_playlist_partial_failure(self, workflow_config, mock_components, temp_dir):
        """Test playlist processing with some failures."""
        video1_path = os.path.join(temp_dir, "video1.mp4")
        video2_path = os.path.join(temp_dir, "video2.mp4")
        Path(video1_path).touch()
        Path(video2_path).touch()
        
        mock_components['downloader'].download_playlist.return_value = [
            {
                'video_path': video1_path,
                'title': 'Video 1',
                'video_id': 'vid1',
                'duration': 60
            },
            {
                'video_path': video2_path,
                'title': 'Video 2',
                'video_id': 'vid2',
                'duration': 90
            }
        ]
        
        # First transcription succeeds, second fails
        mock_components['transcriber'].transcribe_video.side_effect = [
            {'text': 'Transcription 1', 'language': 'en'},
            Exception("Transcription failed for video 2")
        ]
        
        mock_components['slack'].send_transcription.return_value = True
        
        workflow = YouTube2SlackWorkflow(workflow_config)
        results = workflow.process_playlist('https://youtube.com/playlist?list=PLtest')
        
        assert len(results) == 2
        assert results[0].success is True
        assert results[1].success is False
        assert "Transcription failed for video 2" in results[1].error

    def test_send_error_notifications(self, workflow_config, mock_components):
        """Test sending error notifications to Slack."""
        mock_components['downloader'].download.side_effect = Exception("Download error")
        mock_components['slack'].send_error_notification.return_value = True
        
        workflow_config.send_errors_to_slack = True
        workflow = YouTube2SlackWorkflow(workflow_config)
        
        result = workflow.process_video('https://youtube.com/watch?v=error')
        
        assert result.success is False
        
        # Should send error notification
        mock_components['slack'].send_error_notification.assert_called_once()
        call_args = mock_components['slack'].send_error_notification.call_args
        assert "Download error" in call_args[0][0]