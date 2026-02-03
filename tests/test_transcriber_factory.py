"""Tests for TranscriberFactory and OpenAI integration."""

import pytest
from unittest.mock import Mock, patch, MagicMock

from youtube2slack.whisper_transcriber import (
    TranscriberFactory, WhisperTranscriber, OpenAIWhisperTranscriber,
    TranscriptionError, OpenAITranscriptionError
)
from youtube2slack.user_cookie_manager import UserSettings, WhisperService


class MockWorkflowConfig:
    """Mock workflow configuration for testing."""
    
    def __init__(self, allowed_users=None):
        self.whisper_model = "base"
        self.whisper_device = "cpu"
        self.whisper_download_root = None
        self.allowed_local_users = allowed_users
    
    def is_local_whisper_allowed(self, user_id):
        """Check if user is allowed to use local Whisper."""
        if not self.allowed_local_users:
            return True
        return user_id in self.allowed_local_users


class TestTranscriberFactory:
    """Test cases for TranscriberFactory."""
    
    def test_create_local_transcriber_default_settings(self):
        """Test creating local transcriber with default settings."""
        user_settings = UserSettings()  # Default: LOCAL service
        
        with patch('youtube2slack.whisper_transcriber.WhisperTranscriber') as mock_whisper:
            mock_instance = Mock()
            mock_whisper.return_value = mock_instance
            
            result = TranscriberFactory.create_transcriber(user_settings)
            
            # Should create WhisperTranscriber with default settings
            mock_whisper.assert_called_once_with(
                model_name="base",
                device=None,
                download_root=None
            )
            assert result == mock_instance
    
    def test_create_local_transcriber_with_config(self):
        """Test creating local transcriber with workflow config."""
        user_settings = UserSettings(whisper_model="medium")
        config = MockWorkflowConfig()
        
        with patch('youtube2slack.whisper_transcriber.WhisperTranscriber') as mock_whisper:
            mock_instance = Mock()
            mock_whisper.return_value = mock_instance
            
            result = TranscriberFactory.create_transcriber(user_settings, config)
            
            # Should use user's model preference and config's device
            mock_whisper.assert_called_once_with(
                model_name="medium",
                device="cpu",
                download_root=None
            )
            assert result == mock_instance
    
    def test_create_openai_transcriber_success(self):
        """Test creating OpenAI transcriber successfully."""
        user_settings = UserSettings(
            whisper_service=WhisperService.OPENAI,
            openai_api_key="sk-test-key-12345"
        )
        
        with patch('youtube2slack.whisper_transcriber.OpenAIWhisperTranscriber') as mock_openai:
            mock_instance = Mock()
            mock_openai.return_value = mock_instance
            
            result = TranscriberFactory.create_transcriber(user_settings)
            
            mock_openai.assert_called_once_with(
                api_key="sk-test-key-12345",
                model="whisper-1"
            )
            assert result == mock_instance
    
    def test_openai_fallback_to_local_no_api_key(self):
        """Test fallback to local when OpenAI selected but no API key."""
        user_settings = UserSettings(
            whisper_service=WhisperService.OPENAI,
            openai_api_key=None  # No API key
        )
        config = MockWorkflowConfig()  # Local allowed
        
        with patch('youtube2slack.whisper_transcriber.WhisperTranscriber') as mock_whisper:
            mock_instance = Mock()
            mock_whisper.return_value = mock_instance
            
            result = TranscriberFactory.create_transcriber(user_settings, config, "test_user")
            
            # Should fall back to local Whisper
            mock_whisper.assert_called_once()
            assert result == mock_instance
    
    def test_openai_no_key_local_not_allowed(self):
        """Test error when OpenAI selected, no API key, and local not allowed."""
        user_settings = UserSettings(
            whisper_service=WhisperService.OPENAI,
            openai_api_key=None
        )
        config = MockWorkflowConfig(allowed_users=["other_user"])  # test_user not allowed
        
        with pytest.raises(TranscriptionError) as exc_info:
            TranscriberFactory.create_transcriber(user_settings, config, "test_user")
        
        assert "OpenAI API key required" in str(exc_info.value)
        assert "Local Whisper access restricted" in str(exc_info.value)
    
    def test_openai_failure_fallback_to_local(self):
        """Test fallback to local when OpenAI transcriber creation fails."""
        user_settings = UserSettings(
            whisper_service=WhisperService.OPENAI,
            openai_api_key="sk-test-key"
        )
        config = MockWorkflowConfig()  # Local allowed
        
        with patch('youtube2slack.whisper_transcriber.OpenAIWhisperTranscriber') as mock_openai, \
             patch('youtube2slack.whisper_transcriber.WhisperTranscriber') as mock_whisper:
            
            # OpenAI creation fails
            mock_openai.side_effect = OpenAITranscriptionError("API error")
            
            # Local creation succeeds
            mock_local_instance = Mock()
            mock_whisper.return_value = mock_local_instance
            
            result = TranscriberFactory.create_transcriber(user_settings, config, "test_user")
            
            # Should attempt OpenAI first, then fall back to local
            mock_openai.assert_called_once()
            mock_whisper.assert_called_once()
            assert result == mock_local_instance
    
    def test_openai_failure_no_local_fallback(self):
        """Test error when OpenAI fails and local not allowed."""
        user_settings = UserSettings(
            whisper_service=WhisperService.OPENAI,
            openai_api_key="sk-test-key"
        )
        config = MockWorkflowConfig(allowed_users=["other_user"])  # test_user not allowed
        
        with patch('youtube2slack.whisper_transcriber.OpenAIWhisperTranscriber') as mock_openai:
            mock_openai.side_effect = OpenAITranscriptionError("API connection failed")
            
            with pytest.raises(TranscriptionError) as exc_info:
                TranscriberFactory.create_transcriber(user_settings, config, "test_user")
            
            assert "OpenAI API failed" in str(exc_info.value)
            assert "Local Whisper access restricted" in str(exc_info.value)
    
    def test_local_service_not_allowed(self):
        """Test error when local service requested but not allowed."""
        user_settings = UserSettings(
            whisper_service=WhisperService.LOCAL
        )
        config = MockWorkflowConfig(allowed_users=["other_user"])  # test_user not allowed
        
        with pytest.raises(TranscriptionError) as exc_info:
            TranscriberFactory.create_transcriber(user_settings, config, "test_user")
        
        assert "Local Whisper access restricted" in str(exc_info.value)
        assert "Please set up OpenAI API key" in str(exc_info.value)
    
    def test_local_service_allowed_user(self):
        """Test local service works for allowed user."""
        user_settings = UserSettings(
            whisper_service=WhisperService.LOCAL,
            whisper_model="large"
        )
        config = MockWorkflowConfig(allowed_users=["test_user", "other_user"])
        
        with patch('youtube2slack.whisper_transcriber.WhisperTranscriber') as mock_whisper:
            mock_instance = Mock()
            mock_whisper.return_value = mock_instance
            
            result = TranscriberFactory.create_transcriber(user_settings, config, "test_user")
            
            mock_whisper.assert_called_once_with(
                model_name="large",
                device="cpu",
                download_root=None
            )
            assert result == mock_instance
    
    def test_no_permission_config(self):
        """Test that local Whisper works when no permission config is provided."""
        user_settings = UserSettings(whisper_service=WhisperService.LOCAL)
        
        with patch('youtube2slack.whisper_transcriber.WhisperTranscriber') as mock_whisper:
            mock_instance = Mock()
            mock_whisper.return_value = mock_instance
            
            # No config provided - should allow local
            result = TranscriberFactory.create_transcriber(user_settings, None, "test_user")
            assert result == mock_instance
            
            # Config without permission method - should allow local
            basic_config = Mock()
            basic_config.whisper_device = "cuda"
            # No is_local_whisper_allowed method
            
            result = TranscriberFactory.create_transcriber(user_settings, basic_config, "test_user")
            assert result == mock_instance


class TestOpenAIWhisperTranscriber:
    """Test cases for OpenAIWhisperTranscriber."""
    
    def test_initialization_success(self):
        """Test successful initialization."""
        with patch('youtube2slack.whisper_transcriber.OPENAI_AVAILABLE', True), \
             patch('youtube2slack.whisper_transcriber.openai') as mock_openai:
            
            mock_client = Mock()
            mock_openai.OpenAI.return_value = mock_client
            
            transcriber = OpenAIWhisperTranscriber("sk-test-key")
            
            assert transcriber.client == mock_client
            assert transcriber.model == "whisper-1"
            mock_openai.OpenAI.assert_called_once_with(api_key="sk-test-key")
    
    def test_initialization_no_openai_library(self):
        """Test initialization fails when OpenAI library not available."""
        with patch('youtube2slack.whisper_transcriber.OPENAI_AVAILABLE', False):
            with pytest.raises(OpenAITranscriptionError) as exc_info:
                OpenAIWhisperTranscriber("sk-test-key")
            
            assert "OpenAI library is not available" in str(exc_info.value)
    
    def test_initialization_no_api_key(self):
        """Test initialization fails with no API key."""
        with patch('youtube2slack.whisper_transcriber.OPENAI_AVAILABLE', True):
            with pytest.raises(OpenAITranscriptionError) as exc_info:
                OpenAIWhisperTranscriber("")
            
            assert "OpenAI API key is required" in str(exc_info.value)
    
    @patch('youtube2slack.whisper_transcriber.OPENAI_AVAILABLE', True)
    @patch('youtube2slack.whisper_transcriber.openai')
    @patch('os.path.exists')
    @patch('os.path.getsize')
    def test_transcribe_success(self, mock_getsize, mock_exists, mock_openai):
        """Test successful transcription."""
        # Setup mocks
        mock_exists.return_value = True
        mock_getsize.return_value = 1024 * 1024  # 1MB file

        mock_client = Mock()
        mock_openai.OpenAI.return_value = mock_client
        # Mock the OpenAIError exception class
        mock_openai.OpenAIError = Exception

        mock_result = Mock()
        mock_result.text = "This is a test transcription"
        mock_result.language = "en"
        # Make segments iterable (empty list)
        mock_result.segments = []
        mock_client.audio.transcriptions.create.return_value = mock_result

        # Create transcriber and test
        transcriber = OpenAIWhisperTranscriber("sk-test-key")

        with patch('builtins.open', mock_file_open()):
            result = transcriber.transcribe("test_audio.wav")

        # Verify result
        assert result['text'] == "This is a test transcription"
        assert result['language'] == "en"
        assert 'segments' in result

        # Verify API call
        mock_client.audio.transcriptions.create.assert_called_once()
        call_args = mock_client.audio.transcriptions.create.call_args
        assert call_args[1]['model'] == "whisper-1"
        assert call_args[1]['response_format'] == "verbose_json"

    @patch('youtube2slack.whisper_transcriber.OPENAI_AVAILABLE', True)
    @patch('youtube2slack.whisper_transcriber.openai')
    @patch('os.path.exists')
    @patch('os.path.getsize')
    def test_transcribe_file_too_large(self, mock_getsize, mock_exists, mock_openai):
        """Test error when file is too large."""
        mock_exists.return_value = True
        mock_getsize.return_value = 30 * 1024 * 1024  # 30MB (over limit)

        mock_client = Mock()
        mock_openai.OpenAI.return_value = mock_client
        # Mock the OpenAIError exception class
        mock_openai.OpenAIError = Exception

        transcriber = OpenAIWhisperTranscriber("sk-test-key")

        with pytest.raises(OpenAITranscriptionError) as exc_info:
            transcriber.transcribe("large_file.wav")

        assert "File too large" in str(exc_info.value)
    
    @patch('youtube2slack.whisper_transcriber.OPENAI_AVAILABLE', True)
    @patch('youtube2slack.whisper_transcriber.openai')
    def test_transcribe_file_not_found(self, mock_openai):
        """Test error when file doesn't exist."""
        mock_client = Mock()
        mock_openai.OpenAI.return_value = mock_client
        
        transcriber = OpenAIWhisperTranscriber("sk-test-key")
        
        with pytest.raises(OpenAITranscriptionError) as exc_info:
            transcriber.transcribe("nonexistent.wav")
        
        assert "Audio file not found" in str(exc_info.value)
    
    def test_get_model_info(self):
        """Test getting model information."""
        with patch('youtube2slack.whisper_transcriber.OPENAI_AVAILABLE', True), \
             patch('youtube2slack.whisper_transcriber.openai'):
            
            transcriber = OpenAIWhisperTranscriber("sk-test-key")
            info = transcriber.get_model_info()
            
            assert info['model_name'] == "whisper-1"
            assert info['service'] == "openai"
            assert info['api_based'] is True
            assert info['max_file_size_mb'] == 25


def mock_file_open():
    """Create a mock for file opening."""
    mock_file = Mock()
    mock_file.__enter__ = Mock(return_value=mock_file)
    mock_file.__exit__ = Mock(return_value=None)
    return Mock(return_value=mock_file)