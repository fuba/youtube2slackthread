"""Tests for Whisper transcription module."""

import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest
import numpy as np

from youtube2slack.whisper_transcriber import (
    WhisperTranscriber, 
    TranscriptionError,
    format_timestamp,
    split_long_text
)


class TestWhisperTranscriber:
    """Test cases for WhisperTranscriber."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def mock_whisper_model(self):
        """Create a mock Whisper model."""
        mock_model = MagicMock()
        
        # Mock transcribe method
        mock_result = {
            'text': 'This is a test transcription.',
            'segments': [
                {
                    'id': 0,
                    'seek': 0,
                    'start': 0.0,
                    'end': 2.5,
                    'text': 'This is a test',
                    'temperature': 0.0,
                    'avg_logprob': -0.5,
                    'compression_ratio': 1.2,
                    'no_speech_prob': 0.01
                },
                {
                    'id': 1,
                    'seek': 250,
                    'start': 2.5,
                    'end': 4.0,
                    'text': ' transcription.',
                    'temperature': 0.0,
                    'avg_logprob': -0.4,
                    'compression_ratio': 1.1,
                    'no_speech_prob': 0.02
                }
            ],
            'language': 'en'
        }
        mock_model.transcribe.return_value = mock_result
        
        return mock_model

    @patch('whisper.load_model')
    def test_init_loads_model(self, mock_load_model):
        """Test that initialization loads the Whisper model."""
        mock_model = MagicMock()
        mock_load_model.return_value = mock_model
        
        transcriber = WhisperTranscriber(model_name="base")
        
        mock_load_model.assert_called_once_with("base", device="cpu", download_root=None)
        assert transcriber.model == mock_model
        assert transcriber.model_name == "base"

    @patch('whisper.load_model')
    def test_init_with_custom_device(self, mock_load_model):
        """Test initialization with custom device."""
        mock_model = MagicMock()
        mock_load_model.return_value = mock_model
        
        transcriber = WhisperTranscriber(model_name="small", device="cuda")
        
        mock_load_model.assert_called_once_with("small", device="cuda", download_root=None)

    @patch('whisper.load_model')
    def test_transcribe_audio_file(self, mock_load_model, mock_whisper_model, temp_dir):
        """Test transcribing an audio file."""
        mock_load_model.return_value = mock_whisper_model
        
        # Create a dummy audio file
        audio_path = Path(temp_dir) / "test_audio.mp3"
        audio_path.write_bytes(b"dummy audio content")
        
        transcriber = WhisperTranscriber(model_name="base")
        result = transcriber.transcribe(str(audio_path))
        
        assert result['text'] == 'This is a test transcription.'
        assert result['language'] == 'en'
        assert len(result['segments']) == 2
        assert 'timing' in result
        
        mock_whisper_model.transcribe.assert_called_once()
        call_args = mock_whisper_model.transcribe.call_args
        assert call_args[0][0] == str(audio_path)

    @patch('whisper.load_model')
    def test_transcribe_with_language(self, mock_load_model, mock_whisper_model, temp_dir):
        """Test transcribing with specific language."""
        mock_load_model.return_value = mock_whisper_model
        
        audio_path = Path(temp_dir) / "test_audio.mp3"
        audio_path.write_bytes(b"dummy audio content")
        
        transcriber = WhisperTranscriber(model_name="base")
        result = transcriber.transcribe(str(audio_path), language="ja")
        
        # Check that language was passed to transcribe
        call_kwargs = mock_whisper_model.transcribe.call_args[1]
        assert call_kwargs['language'] == 'ja'

    @patch('whisper.load_model')
    def test_transcribe_nonexistent_file(self, mock_load_model):
        """Test transcribing a non-existent file."""
        mock_model = MagicMock()
        mock_load_model.return_value = mock_model
        
        transcriber = WhisperTranscriber(model_name="base")
        
        with pytest.raises(TranscriptionError) as exc_info:
            transcriber.transcribe("/path/to/nonexistent/file.mp3")
        
        assert "Audio file not found" in str(exc_info.value)

    @patch('whisper.load_model')
    def test_transcribe_with_whisper_error(self, mock_load_model, temp_dir):
        """Test handling of Whisper errors during transcription."""
        mock_model = MagicMock()
        mock_model.transcribe.side_effect = RuntimeError("CUDA out of memory")
        mock_load_model.return_value = mock_model
        
        audio_path = Path(temp_dir) / "test_audio.mp3"
        audio_path.write_bytes(b"dummy audio content")
        
        transcriber = WhisperTranscriber(model_name="base")
        
        with pytest.raises(TranscriptionError) as exc_info:
            transcriber.transcribe(str(audio_path))
        
        assert "Transcription failed" in str(exc_info.value)

    @patch('whisper.load_model')
    def test_extract_audio_from_video(self, mock_load_model, temp_dir):
        """Test extracting audio from video file."""
        mock_load_model.return_value = MagicMock()
        
        video_path = Path(temp_dir) / "test_video.mp4"
        video_path.write_bytes(b"dummy video content")
        
        transcriber = WhisperTranscriber(model_name="base")
        
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 0
            
            audio_path = transcriber.extract_audio(str(video_path), temp_dir)
            
            assert audio_path.endswith('.wav')
            assert temp_dir in audio_path
            
            # Verify ffmpeg was called correctly
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert 'ffmpeg' in cmd
            assert str(video_path) in cmd
            assert '.wav' in cmd[-1]

    @patch('whisper.load_model')
    def test_extract_audio_ffmpeg_error(self, mock_load_model, temp_dir):
        """Test handling of ffmpeg errors during audio extraction."""
        mock_load_model.return_value = MagicMock()
        
        video_path = Path(temp_dir) / "test_video.mp4"
        video_path.write_bytes(b"dummy video content")
        
        transcriber = WhisperTranscriber(model_name="base")
        
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "No such file or directory"
            
            with pytest.raises(TranscriptionError) as exc_info:
                transcriber.extract_audio(str(video_path), temp_dir)
            
            assert "Failed to extract audio" in str(exc_info.value)

    def test_format_timestamp(self):
        """Test timestamp formatting."""
        assert format_timestamp(0) == "00:00:00"
        assert format_timestamp(61) == "00:01:01"
        assert format_timestamp(3661) == "01:01:01"
        assert format_timestamp(3661.5) == "01:01:01"

    def test_split_long_text(self):
        """Test splitting long text into chunks."""
        # Test short text
        short_text = "This is a short text."
        chunks = split_long_text(short_text, max_length=100)
        assert len(chunks) == 1
        assert chunks[0] == short_text
        
        # Test long text
        long_text = "This is a very long text. " * 100
        chunks = split_long_text(long_text, max_length=100)
        assert len(chunks) > 1
        assert all(len(chunk) <= 100 for chunk in chunks)
        
        # Test that sentences are not broken
        text_with_sentences = "First sentence. Second sentence. Third sentence. Fourth sentence."
        chunks = split_long_text(text_with_sentences, max_length=30)
        assert all(chunk.endswith('.') or chunk == chunks[-1] for chunk in chunks)

    @patch('whisper.load_model')
    def test_transcribe_with_timestamps(self, mock_load_model, mock_whisper_model, temp_dir):
        """Test transcription with timestamp information."""
        mock_load_model.return_value = mock_whisper_model
        
        audio_path = Path(temp_dir) / "test_audio.mp3"
        audio_path.write_bytes(b"dummy audio content")
        
        transcriber = WhisperTranscriber(model_name="base")
        result = transcriber.transcribe(str(audio_path), include_timestamps=True)
        
        assert 'segments' in result
        assert all('start' in seg for seg in result['segments'])
        assert all('end' in seg for seg in result['segments'])
        assert all('text' in seg for seg in result['segments'])

    @patch('whisper.load_model')
    def test_get_available_models(self, mock_load_model):
        """Test getting list of available models."""
        transcriber = WhisperTranscriber()
        models = transcriber.get_available_models()
        
        expected_models = ['tiny', 'base', 'small', 'medium', 'large', 'large-v2', 'large-v3']
        assert all(model in models for model in expected_models)

    @patch('whisper.load_model')
    def test_model_caching(self, mock_load_model):
        """Test that model is cached and reused."""
        mock_model = MagicMock()
        mock_load_model.return_value = mock_model
        
        transcriber = WhisperTranscriber(model_name="base")
        
        # First transcription
        with patch('os.path.exists', return_value=True):
            transcriber.transcribe("dummy1.mp3")
            transcriber.transcribe("dummy2.mp3")
        
        # Model should only be loaded once
        mock_load_model.assert_called_once()

    @patch('whisper.load_model')
    def test_progress_callback(self, mock_load_model, temp_dir):
        """Test progress callback during transcription."""
        mock_model = MagicMock()
        mock_load_model.return_value = mock_model
        
        # Set up mock to call progress callback
        def mock_transcribe(audio, **kwargs):
            if 'progress_callback' in kwargs and kwargs['progress_callback']:
                kwargs['progress_callback'](0.5)  # 50% progress
            return {
                'text': 'Test',
                'segments': [],
                'language': 'en'
            }
        
        mock_model.transcribe.side_effect = mock_transcribe
        
        audio_path = Path(temp_dir) / "test_audio.mp3"
        audio_path.write_bytes(b"dummy audio content")
        
        progress_called = False
        progress_value = 0
        
        def progress_callback(progress):
            nonlocal progress_called, progress_value
            progress_called = True
            progress_value = progress
        
        transcriber = WhisperTranscriber(model_name="base")
        transcriber.transcribe(str(audio_path), progress_callback=progress_callback)
        
        assert progress_called
        assert progress_value == 0.5