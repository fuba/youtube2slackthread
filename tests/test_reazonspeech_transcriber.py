"""Tests for ReazonSpeech K2 transcriber with sherpa-onnx."""

import os
import struct
import tempfile
import wave
from unittest.mock import Mock, patch, MagicMock
import pytest

from youtube2slack.whisper_transcriber import (
    TranscriptionError,
    format_timestamp,
)


def create_test_wav(path, duration_s=1.0, sample_rate=16000):
    """Create a test WAV file with silence."""
    num_samples = int(sample_rate * duration_s)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * num_samples)


class TestReazonSpeechTranscriber:
    """Test cases for ReazonSpeechTranscriber."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        d = tempfile.mkdtemp()
        yield d
        import shutil
        shutil.rmtree(d)

    def test_import(self):
        """Test that ReazonSpeechTranscriber can be imported."""
        from youtube2slack.reazonspeech_transcriber import ReazonSpeechTranscriber
        assert ReazonSpeechTranscriber is not None

    @patch("youtube2slack.reazonspeech_transcriber.sherpa_onnx")
    def test_init_creates_recognizer(self, mock_sherpa):
        """Test that initialization creates an OfflineRecognizer."""
        from youtube2slack.reazonspeech_transcriber import ReazonSpeechTranscriber

        mock_recognizer = Mock()
        mock_sherpa.OfflineRecognizer.from_transducer.return_value = mock_recognizer

        transcriber = ReazonSpeechTranscriber(model_dir="/fake/model")

        mock_sherpa.OfflineRecognizer.from_transducer.assert_called_once()
        assert transcriber.recognizer == mock_recognizer

    @patch("youtube2slack.reazonspeech_transcriber.sherpa_onnx")
    def test_transcribe_returns_text(self, mock_sherpa, temp_dir):
        """Test that transcribe returns structured result with text."""
        from youtube2slack.reazonspeech_transcriber import ReazonSpeechTranscriber

        # Setup mock recognizer
        mock_recognizer = Mock()
        mock_sherpa.OfflineRecognizer.from_transducer.return_value = mock_recognizer

        mock_stream = Mock()
        mock_stream.result.text = "テスト音声です"
        mock_recognizer.create_stream.return_value = mock_stream

        transcriber = ReazonSpeechTranscriber(model_dir="/fake/model")

        # Create test WAV
        wav_path = os.path.join(temp_dir, "test.wav")
        create_test_wav(wav_path, duration_s=2.0)

        result = transcriber.transcribe(wav_path)

        assert result["text"] == "テスト音声です"
        assert "language" in result
        assert result["language"] == "ja"
        assert "segments" in result

    @patch("youtube2slack.reazonspeech_transcriber.sherpa_onnx")
    def test_transcribe_nonexistent_file(self, mock_sherpa):
        """Test error on nonexistent file."""
        from youtube2slack.reazonspeech_transcriber import ReazonSpeechTranscriber

        mock_sherpa.OfflineRecognizer.from_transducer.return_value = Mock()

        transcriber = ReazonSpeechTranscriber(model_dir="/fake/model")

        with pytest.raises(TranscriptionError, match="Audio file not found"):
            transcriber.transcribe("/nonexistent/file.wav")

    @patch("youtube2slack.reazonspeech_transcriber.sherpa_onnx")
    def test_transcribe_empty_result(self, mock_sherpa, temp_dir):
        """Test handling of empty transcription result."""
        from youtube2slack.reazonspeech_transcriber import ReazonSpeechTranscriber

        mock_recognizer = Mock()
        mock_sherpa.OfflineRecognizer.from_transducer.return_value = mock_recognizer

        mock_stream = Mock()
        mock_stream.result.text = ""
        mock_recognizer.create_stream.return_value = mock_stream

        transcriber = ReazonSpeechTranscriber(model_dir="/fake/model")

        wav_path = os.path.join(temp_dir, "silence.wav")
        create_test_wav(wav_path, duration_s=1.0)

        result = transcriber.transcribe(wav_path)
        assert result["text"] == ""

    @patch("youtube2slack.reazonspeech_transcriber.sherpa_onnx")
    def test_get_model_info(self, mock_sherpa):
        """Test getting model information."""
        from youtube2slack.reazonspeech_transcriber import ReazonSpeechTranscriber

        mock_sherpa.OfflineRecognizer.from_transducer.return_value = Mock()

        transcriber = ReazonSpeechTranscriber(model_dir="/fake/model")
        info = transcriber.get_model_info()

        assert info["model_name"] == "reazonspeech-k2"
        assert info["device"] == "cpu"
        assert info["service"] == "local"


class TestReazonSpeechVADStreamProcessor:
    """Test cases for ReazonSpeech VAD stream processor."""

    def test_import(self):
        """Test that ReazonSpeechStreamProcessor can be imported."""
        from youtube2slack.reazonspeech_stream_processor import ReazonSpeechStreamProcessor
        assert ReazonSpeechStreamProcessor is not None
