"""Tests for stream processor module."""

import os
import tempfile
import shutil
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest

from youtube2slack.stream_processor import (
    StreamProcessor,
    StreamProcessingError
)


class TestStreamProcessor:
    """Test cases for StreamProcessor."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def mock_transcriber(self):
        """Create a mock transcriber."""
        mock = MagicMock()
        mock.transcribe.return_value = {
            'text': 'Test transcription',
            'language': 'en',
            'segments': [
                {
                    'start': 0.0,
                    'end': 5.0,
                    'text': 'Test transcription'
                }
            ]
        }
        return mock

    @pytest.fixture
    def mock_slack_client(self):
        """Create a mock Slack client."""
        mock = MagicMock()
        mock.send_blocks.return_value = True
        return mock

    def test_init(self, mock_transcriber, mock_slack_client):
        """Test StreamProcessor initialization."""
        processor = StreamProcessor(
            transcriber=mock_transcriber,
            slack_client=mock_slack_client,
            chunk_duration=30,
            overlap_duration=5
        )
        
        assert processor.transcriber == mock_transcriber
        assert processor.slack_client == mock_slack_client
        assert processor.chunk_duration == 30
        assert processor.overlap_duration == 0  # Forced to 0 for live streams
        assert processor.is_running is False
        assert processor.temp_dir is not None
        assert os.path.exists(processor.temp_dir)

    def test_init_without_slack(self, mock_transcriber):
        """Test initialization without Slack client."""
        processor = StreamProcessor(
            transcriber=mock_transcriber,
            slack_client=None
        )
        
        assert processor.slack_client is None
        assert processor.transcriber == mock_transcriber

    @patch('subprocess.run')
    def test_get_stream_info_success(self, mock_run, mock_transcriber):
        """Test successful stream info retrieval."""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "Test Stream|||test123|||300|||True"
        
        processor = StreamProcessor(transcriber=mock_transcriber)
        info = processor._get_stream_info("https://youtube.com/watch?v=test")
        
        assert info['title'] == 'Test Stream'
        assert info['id'] == 'test123'
        assert info['duration'] == '300'
        assert info['is_live'] == 'True'
        assert info['url'] == 'https://youtube.com/watch?v=test'

    @patch('subprocess.run')
    def test_get_stream_info_failure(self, mock_run, mock_transcriber):
        """Test stream info retrieval failure."""
        mock_run.side_effect = Exception("Command failed")
        
        processor = StreamProcessor(transcriber=mock_transcriber)
        info = processor._get_stream_info("https://youtube.com/watch?v=test")
        
        assert info['title'] == 'Live Stream'
        assert info['url'] == 'https://youtube.com/watch?v=test'

    @patch('subprocess.run')
    def test_capture_chunk_success(self, mock_run, mock_transcriber, temp_dir):
        """Test successful chunk capture."""
        mock_run.return_value.returncode = 0
        
        # Create a dummy audio file to simulate ffmpeg output
        chunk_path = os.path.join(temp_dir, "test_chunk.wav")
        with open(chunk_path, 'wb') as f:
            f.write(b'dummy audio data' * 100)  # Make it larger than 1KB
        
        processor = StreamProcessor(transcriber=mock_transcriber)
        
        # Mock os.path.exists and os.path.getsize
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=1500):
            
            success = processor._capture_chunk(
                "https://youtube.com/watch?v=test",
                chunk_path,
                0
            )
        
        assert success is True
        mock_run.assert_called_once()

    @patch('subprocess.run')
    def test_capture_chunk_failure(self, mock_run, mock_transcriber):
        """Test chunk capture failure."""
        mock_run.return_value.returncode = 1
        
        processor = StreamProcessor(transcriber=mock_transcriber)
        
        success = processor._capture_chunk(
            "https://youtube.com/watch?v=test",
            "/tmp/test_chunk.wav",
            0
        )
        
        assert success is False

    def test_transcribe_chunk(self, mock_transcriber, mock_slack_client, temp_dir):
        """Test chunk transcription."""
        # Create a dummy audio file
        chunk_path = os.path.join(temp_dir, "test_chunk.wav")
        with open(chunk_path, 'wb') as f:
            f.write(b'dummy audio data')
        
        processor = StreamProcessor(
            transcriber=mock_transcriber,
            slack_client=mock_slack_client
        )
        
        chunk_info = {
            'path': chunk_path,
            'index': 0,
            'timestamp': time.time(),
            'start_time': 0.0
        }
        
        result = processor._transcribe_chunk(chunk_info)
        
        assert result is not None
        assert result['text'] == 'Test transcription'
        assert result['chunk_index'] == 0
        assert result['stream_start_time'] == 0.0
        
        # Check that segments have stream timestamps
        assert 'segments' in result
        segment = result['segments'][0]
        assert 'stream_start' in segment
        assert 'stream_end' in segment
        assert 'stream_start_formatted' in segment
        assert 'stream_end_formatted' in segment

    def test_transcribe_chunk_failure(self, mock_transcriber, temp_dir):
        """Test chunk transcription failure."""
        mock_transcriber.transcribe.side_effect = Exception("Transcription failed")
        
        # Create a dummy audio file
        chunk_path = os.path.join(temp_dir, "test_chunk.wav")
        with open(chunk_path, 'wb') as f:
            f.write(b'dummy audio data')
        
        processor = StreamProcessor(transcriber=mock_transcriber)
        
        chunk_info = {
            'path': chunk_path,
            'index': 0,
            'timestamp': time.time(),
            'start_time': 0.0
        }
        
        result = processor._transcribe_chunk(chunk_info)
        
        assert result is None

    def test_format_timestamp(self, mock_transcriber):
        """Test timestamp formatting."""
        processor = StreamProcessor(transcriber=mock_transcriber)
        
        assert processor._format_timestamp(0) == "00:00:00"
        assert processor._format_timestamp(61) == "00:01:01"
        assert processor._format_timestamp(3661) == "01:01:01"
        assert processor._format_timestamp(3661.5) == "01:01:01"

    def test_post_chunk_to_slack(self, mock_transcriber, mock_slack_client):
        """Test posting chunk to Slack."""
        processor = StreamProcessor(
            transcriber=mock_transcriber,
            slack_client=mock_slack_client
        )
        
        processor.stream_info = {
            'title': 'Test Stream',
            'url': 'https://youtube.com/watch?v=test'
        }
        
        chunk_info = {
            'index': 0,
            'start_time': 60.0  # 1 minute
        }
        
        transcription = {
            'text': 'This is a test transcription.',
            'language': 'en'
        }
        
        processor._post_chunk_to_slack(chunk_info, transcription)
        
        # Verify Slack client was called with send_message (not send_blocks)
        mock_slack_client.send_message.assert_called_once()
        
        # Check the message content for first chunk (index 0)
        call_args = mock_slack_client.send_message.call_args
        message = call_args[0][0]
        
        # Should include stream title for first chunk
        assert '🔴 Test Stream' in message
        assert 'This is a test transcription.' in message

    def test_post_subsequent_chunk_to_slack(self, mock_transcriber, mock_slack_client):
        """Test posting subsequent chunks to Slack (text only)."""
        processor = StreamProcessor(
            transcriber=mock_transcriber,
            slack_client=mock_slack_client
        )
        
        processor.stream_info = {
            'title': 'Test Stream',
            'url': 'https://youtube.com/watch?v=test'
        }
        
        # Test subsequent chunk (index > 0)
        chunk_info = {
            'index': 5,  # Not first chunk
            'start_time': 300.0
        }
        
        transcription = {
            'text': 'This is chunk 6 text.',
            'language': 'en'
        }
        
        processor._post_chunk_to_slack(chunk_info, transcription)
        
        # Verify Slack client was called
        mock_slack_client.send_message.assert_called_once()
        
        # Check message content for subsequent chunk
        call_args = mock_slack_client.send_message.call_args
        message = call_args[0][0]
        
        # Should NOT include stream title, just the text
        assert message == 'This is chunk 6 text.'
        assert '🔴' not in message
        
    def test_duplicate_text_detection(self, mock_transcriber, mock_slack_client):
        """Test duplicate text detection and filtering."""
        processor = StreamProcessor(
            transcriber=mock_transcriber,
            slack_client=mock_slack_client
        )
        
        processor.stream_info = {
            'title': 'Test Stream',
            'url': 'https://youtube.com/watch?v=test'
        }
        
        # First chunk with original text
        chunk_info_1 = {'index': 1, 'start_time': 10.0}
        transcription_1 = {'text': 'Hello world this is a test', 'language': 'en'}
        processor._post_chunk_to_slack(chunk_info_1, transcription_1)
        
        # Second chunk with exact duplicate
        chunk_info_2 = {'index': 2, 'start_time': 20.0}
        transcription_2 = {'text': 'Hello world this is a test', 'language': 'en'}
        processor._post_chunk_to_slack(chunk_info_2, transcription_2)
        
        # Third chunk with similar text (should be detected as duplicate)
        chunk_info_3 = {'index': 3, 'start_time': 30.0}
        transcription_3 = {'text': 'Hello world this is a test message', 'language': 'en'}
        processor._post_chunk_to_slack(chunk_info_3, transcription_3)
        
        # Fourth chunk with different text (should not be duplicate)
        chunk_info_4 = {'index': 4, 'start_time': 40.0}
        transcription_4 = {'text': 'Completely different message here', 'language': 'en'}
        processor._post_chunk_to_slack(chunk_info_4, transcription_4)
        
        # Should have only called send_message twice (original + different text)
        assert mock_slack_client.send_message.call_count == 2
        
    def test_is_duplicate_text(self, mock_transcriber):
        """Test duplicate text detection logic."""
        processor = StreamProcessor(transcriber=mock_transcriber)
        
        # Empty recent texts - nothing is duplicate
        assert not processor._is_duplicate_text("Any text")
        
        # Add some texts
        processor.recent_texts = ["Hello world", "Another message", "Third text"]
        
        # Exact match should be duplicate
        assert processor._is_duplicate_text("Hello world")
        
        # Similar text (high overlap) should be duplicate
        assert processor._is_duplicate_text("Hello world test")
        assert processor._is_duplicate_text("world Hello")
        
        # Very different text should not be duplicate
        assert not processor._is_duplicate_text("Completely different message")
        
        # Empty text should not be duplicate
        assert not processor._is_duplicate_text("")
        
    def test_normalize_text(self, mock_transcriber):
        """Test text normalization for duplicate detection."""
        processor = StreamProcessor(transcriber=mock_transcriber)
        
        # Test punctuation removal and lowercasing
        assert processor._normalize_text("Hello, World!") == "hello world"
        
        # Test extra whitespace removal
        assert processor._normalize_text("  multiple   spaces  ") == "multiple spaces"
        
        # Test mixed case and punctuation
        assert processor._normalize_text("Test... Text?!") == "test text"
        
        # Test Japanese text (should preserve characters)
        assert processor._normalize_text("こんにちは、世界！") == "こんにちは世界"

    def test_cleanup_chunk(self, mock_transcriber, temp_dir):
        """Test chunk cleanup."""
        # Create a test file
        chunk_path = os.path.join(temp_dir, "test_chunk.wav")
        with open(chunk_path, 'w') as f:
            f.write("test")
        
        assert os.path.exists(chunk_path)
        
        processor = StreamProcessor(transcriber=mock_transcriber)
        processor._cleanup_chunk(chunk_path)
        
        assert not os.path.exists(chunk_path)

    def test_cleanup_chunk_nonexistent(self, mock_transcriber):
        """Test cleanup of non-existent chunk."""
        processor = StreamProcessor(transcriber=mock_transcriber)
        
        # Should not raise an exception
        processor._cleanup_chunk("/nonexistent/file.wav")

    def test_get_status(self, mock_transcriber, mock_slack_client):
        """Test status information retrieval."""
        processor = StreamProcessor(
            transcriber=mock_transcriber,
            slack_client=mock_slack_client,
            chunk_duration=45,
            overlap_duration=10
        )
        
        processor.stream_info = {'title': 'Test Stream'}
        processor.is_running = True
        
        status = processor.get_status()
        
        assert status['is_running'] is True
        assert status['stream_info']['title'] == 'Test Stream'
        assert status['chunk_duration'] == 45
        assert status['overlap_duration'] == 0  # Forced to 0 for live streams
        assert 'pending_chunks' in status
        assert 'temp_dir' in status

    def test_stop_processing(self, mock_transcriber):
        """Test stopping stream processing."""
        processor = StreamProcessor(transcriber=mock_transcriber)
        temp_dir = processor.temp_dir
        
        processor.is_running = True
        processor.stop_processing()
        
        assert processor.is_running is False
        assert not os.path.exists(temp_dir)

    @patch('threading.Thread')
    @patch.object(StreamProcessor, '_start_stream_capture')
    @patch.object(StreamProcessor, '_get_stream_info')
    def test_start_stream_processing(self, mock_get_info, mock_capture, 
                                   mock_thread_class, mock_transcriber):
        """Test starting stream processing."""
        mock_get_info.return_value = {'title': 'Test Stream'}
        mock_thread = MagicMock()
        mock_thread_class.return_value = mock_thread
        
        processor = StreamProcessor(transcriber=mock_transcriber)
        
        def progress_callback(msg):
            pass
        
        # Mock the _start_stream_capture to avoid infinite loop
        def mock_capture_func(url, callback):
            time.sleep(0.1)  # Brief pause
            processor.is_running = False  # Stop the loop
        
        mock_capture.side_effect = mock_capture_func
        
        processor.start_stream_processing(
            "https://youtube.com/watch?v=test",
            progress_callback
        )
        
        # Verify initialization
        mock_get_info.assert_called_once_with("https://youtube.com/watch?v=test")
        mock_thread.start.assert_called_once()
        
        # Clean up
        processor.stop_processing()

    def test_start_stream_processing_already_running(self, mock_transcriber):
        """Test starting stream processing when already running."""
        processor = StreamProcessor(transcriber=mock_transcriber)
        processor.is_running = True
        
        with pytest.raises(StreamProcessingError) as exc_info:
            processor.start_stream_processing("https://youtube.com/watch?v=test")
        
        assert "already running" in str(exc_info.value)