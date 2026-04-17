"""Streaming processor using Silero VAD + ReazonSpeech K2 via sherpa-onnx."""

import os
import queue
import re
import threading
import subprocess
import logging
import numpy as np
from typing import Dict, Optional, Any, Callable

import sherpa_onnx

from .reazonspeech_transcriber import (
    ReazonSpeechTranscriber,
    SAMPLE_RATE,
    DEFAULT_MODEL_DIR_NAME,
)
from .whisper_transcriber import TranscriptionError

logger = logging.getLogger(__name__)

# Silero VAD window size: 512 samples at 16kHz = 32ms
VAD_WINDOW_SIZE = 512
VAD_WINDOW_BYTES = VAD_WINDOW_SIZE * 2  # 16-bit PCM


class ReazonSpeechStreamProcessingError(Exception):
    """Exception raised for stream processing failures."""
    pass


class ReazonSpeechStreamProcessor:
    """Process live YouTube streams with Silero VAD + ReazonSpeech K2.

    Replaces VADStreamProcessor with sherpa-onnx based pipeline:
    - Silero VAD for speech detection (replaces webrtcvad)
    - ReazonSpeech K2 OfflineRecognizer for transcription (replaces Whisper)

    Uses a queue to decouple audio capture from transcription,
    preventing backpressure from blocking ffmpeg reads.
    """

    def __init__(self, model_dir: str, vad_model_path: str,
                 num_threads: int = 2, use_int8: bool = True,
                 cookies_file: Optional[str] = None,
                 user_id: Optional[str] = None,
                 vad_threshold: float = 0.5,
                 min_silence_duration: float = 0.5,
                 min_speech_duration: float = 0.25,
                 max_speech_duration: float = 10.0):
        """Initialize the stream processor.

        Args:
            model_dir: Path to ReazonSpeech K2 model directory
            vad_model_path: Path to silero_vad.onnx
            num_threads: CPU threads for inference
            use_int8: Use int8 quantized model
            cookies_file: Path to cookies file for YouTube auth
            user_id: Slack user ID
            vad_threshold: VAD speech detection threshold (0.0-1.0)
            min_silence_duration: Minimum silence to end speech segment (seconds)
            min_speech_duration: Minimum speech duration to process (seconds)
            max_speech_duration: Maximum speech before forced processing (seconds)
        """
        self.cookies_file = cookies_file
        self.user_id = user_id

        # Create recognizer
        self.transcriber = ReazonSpeechTranscriber(
            model_dir=model_dir,
            num_threads=num_threads,
            use_int8=use_int8,
        )

        # Create Silero VAD config
        vad_config = sherpa_onnx.VadModelConfig()
        vad_config.silero_vad.model = vad_model_path
        vad_config.silero_vad.threshold = vad_threshold
        vad_config.silero_vad.min_silence_duration = min_silence_duration
        vad_config.silero_vad.min_speech_duration = min_speech_duration
        vad_config.silero_vad.max_speech_duration = max_speech_duration
        vad_config.sample_rate = SAMPLE_RATE
        self.vad_config = vad_config

        self.is_running = False
        self.stream_info = {}
        self.progress_callback = None

        # Queue for decoupling capture from transcription
        self.segment_queue = queue.Queue()
        self.processing_thread = None

        # Lock for text buffer access
        self._lock = threading.RLock()

        # Text buffering for sentence detection
        self.text_buffer = ""
        self.sentence_endings = re.compile(r'[。！？\.\!\?]')
        self.max_buffer_length = 80

        logger.info("ReazonSpeech stream processor initialized")

    def start_stream_processing(self, stream_url: str,
                                progress_callback: Optional[Callable[[str], None]] = None) -> None:
        """Start processing a live stream.

        Args:
            stream_url: YouTube live stream URL
            progress_callback: Callback for posting transcription results

        Raises:
            ReazonSpeechStreamProcessingError: On any failure
        """
        if self.is_running:
            raise ReazonSpeechStreamProcessingError("Stream processing already running")

        self.is_running = True
        self.progress_callback = progress_callback
        self.stream_info = self._get_stream_info(stream_url)

        logger.info(f"Starting ReazonSpeech processing of: "
                     f"{self.stream_info.get('title', 'Unknown Stream')}")

        # Start background worker thread for transcription
        self.processing_thread = threading.Thread(
            target=self._transcription_worker,
            daemon=True,
        )
        self.processing_thread.start()

        # Start audio capture (blocks until stream ends or stop)
        try:
            self._start_stream_capture(stream_url)
        except Exception:
            self.is_running = False
            raise

    def _get_stream_info(self, stream_url: str) -> Dict[str, Any]:
        """Get stream information without downloading."""
        try:
            cmd = [
                "yt-dlp",
                "--print", "%(title)s|||%(id)s|||%(duration)s|||%(is_live)s",
                "--no-download",
                stream_url,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            if result.stdout.strip():
                parts = result.stdout.strip().split("|||")
                return {
                    "title": parts[0] if len(parts) > 0 else "Unknown",
                    "id": parts[1] if len(parts) > 1 else "unknown",
                    "duration": parts[2] if len(parts) > 2 else None,
                    "is_live": parts[3] if len(parts) > 3 else "False",
                    "url": stream_url,
                }
            return {"title": "Live Stream", "url": stream_url}
        except Exception as e:
            logger.error(f"Failed to get stream info: {e}")
            return {"title": "Live Stream", "url": stream_url}

    def _get_actual_stream_url(self, youtube_url: str) -> Optional[str]:
        """Get the actual stream URL that ffmpeg can process."""
        try:
            cmd = [
                "yt-dlp",
                "-g",
                "-f", "best[ext=mp4]",
                "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/120.0.0.0 Safari/537.36",
                "--remote-components", "ejs:github",
            ]
            if self.cookies_file and os.path.exists(self.cookies_file):
                cmd.extend(["--cookies", self.cookies_file])
                logger.info(f"Using cookies file: {self.cookies_file}")

            cmd.append(youtube_url)
            logger.info(f"Executing yt-dlp command: {' '.join(cmd)}")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0 and result.stdout.strip():
                actual_url = result.stdout.strip().split("\n")[0]
                logger.info(f"Got actual stream URL: {actual_url[:100]}...")
                return actual_url

            error_message = result.stderr
            logger.error(f"Failed to get stream URL: {error_message}")

            if self._is_cookie_authentication_error(error_message):
                raise ReazonSpeechStreamProcessingError(
                    "Cookie authentication failed! Please upload fresh cookies via DM."
                )
            raise ReazonSpeechStreamProcessingError(
                f"Failed to access YouTube video: {error_message}"
            )

        except ReazonSpeechStreamProcessingError:
            raise
        except Exception as e:
            logger.error(f"Error getting stream URL: {e}")
            raise ReazonSpeechStreamProcessingError(
                f"Unexpected error accessing YouTube: {str(e)}"
            )

    def _is_cookie_authentication_error(self, error_message: str) -> bool:
        """Check if error indicates cookie authentication failure."""
        patterns = [
            "Sign in to confirm you're not a bot",
            "confirm you're not a bot",
            "This helps protect our community",
            "Unable to extract initial data",
            "Requires authentication",
            "Private video",
            "Members-only content",
            "HTTP Error 403",
            "Forbidden",
        ]
        lower = error_message.lower()
        return any(p.lower() in lower for p in patterns)

    def _start_stream_capture(self, stream_url: str) -> None:
        """Start continuous audio capture with Silero VAD + ReazonSpeech."""
        actual_stream_url = self._get_actual_stream_url(stream_url)
        if not actual_stream_url:
            raise ReazonSpeechStreamProcessingError("Could not get actual stream URL")

        try:
            cmd = [
                "ffmpeg",
                "-i", actual_stream_url,
                "-vn",
                "-acodec", "pcm_s16le",
                "-ar", str(SAMPLE_RATE),
                "-ac", "1",
                "-f", "s16le",  # Raw PCM, no WAV header
                "-loglevel", "error",
                "-avoid_negative_ts", "make_zero",
                "-flush_packets", "1",
                "pipe:1",
            ]

            logger.info("Starting continuous FFmpeg audio stream...")
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            self._capture_and_vad(process)

        except ReazonSpeechStreamProcessingError:
            raise
        except Exception as e:
            logger.error(f"Stream capture failed: {e}")
            raise ReazonSpeechStreamProcessingError(f"Stream capture failed: {e}")

    def _capture_and_vad(self, process: subprocess.Popen) -> None:
        """Capture audio from ffmpeg and run VAD, enqueuing speech segments.

        This runs in the main processing thread. Speech segments detected
        by VAD are put into segment_queue for the worker thread to transcribe.
        """
        vad = sherpa_onnx.VoiceActivityDetector(self.vad_config, buffer_size_in_seconds=100)

        try:
            while self.is_running and process.poll() is None:
                raw_data = process.stdout.read(VAD_WINDOW_BYTES)
                if not raw_data or len(raw_data) < VAD_WINDOW_BYTES:
                    break

                samples = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0
                vad.accept_waveform(samples)

                # Drain any completed speech segments into the queue
                while not vad.empty():
                    speech_samples = vad.front.samples.copy()
                    vad.pop()
                    duration = len(speech_samples) / SAMPLE_RATE
                    logger.info(f"VAD detected speech segment: {duration:.2f}s")
                    self.segment_queue.put(speech_samples)

            # Flush VAD to capture any remaining speech at stream end
            vad.flush()
            while not vad.empty():
                speech_samples = vad.front.samples.copy()
                vad.pop()
                duration = len(speech_samples) / SAMPLE_RATE
                logger.info(f"VAD flush: speech segment: {duration:.2f}s")
                self.segment_queue.put(speech_samples)

        except Exception as e:
            self.is_running = False
            raise ReazonSpeechStreamProcessingError(
                f"Stream processing failed: {e}"
            ) from e
        finally:
            self.is_running = False
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()

    def _transcription_worker(self) -> None:
        """Background worker that transcribes queued speech segments."""
        while self.is_running or not self.segment_queue.empty():
            try:
                samples = self.segment_queue.get(timeout=2)
            except queue.Empty:
                continue

            try:
                stream = self.transcriber.recognizer.create_stream()
                stream.accept_waveform(SAMPLE_RATE, samples)
                self.transcriber.recognizer.decode_stream(stream)
                text = stream.result.text.strip()

                if text:
                    logger.info(f"Transcription: {text[:80]}...")
                    with self._lock:
                        if self.is_running:
                            self._process_transcription(text)
                else:
                    logger.debug("Empty transcription result, skipping")

            except Exception as e:
                logger.error(f"Transcription failed: {e}")
            finally:
                self.segment_queue.task_done()

    def _process_transcription(self, text: str) -> None:
        """Process transcription text and detect sentence boundaries.

        Caller must hold self._lock.
        """
        self.text_buffer += text + " "

        # Find and post complete sentences
        while True:
            match = self.sentence_endings.search(self.text_buffer)
            if not match:
                break

            sentence_end = match.end()
            sentence = self.text_buffer[:sentence_end].strip()
            self.text_buffer = self.text_buffer[sentence_end:].strip()

            if sentence and len(sentence) > 5:
                logger.info(f"Complete sentence: {sentence}")
                self._post_sentence(sentence)

        # Force post if buffer gets too long
        if len(self.text_buffer) > self.max_buffer_length:
            break_points = ["という", "ですが", "ましたが", "ますが",
                            "になります", "ということで"]
            best_break = -1

            for point in break_points:
                pos = self.text_buffer.rfind(point)
                if pos > 50:
                    best_break = max(best_break, pos + len(point))

            if best_break > 0:
                sentence = self.text_buffer[:best_break].strip()
                self.text_buffer = self.text_buffer[best_break:].strip()
                self._post_sentence(sentence)
            else:
                self._post_sentence(self.text_buffer.strip())
                self.text_buffer = ""

    def _post_sentence(self, sentence: str) -> None:
        """Post a complete sentence via callback."""
        if self.progress_callback:
            logger.info(f"Posting: {sentence[:50]}...")
            self.progress_callback(sentence)

    def stop_processing(self) -> None:
        """Stop stream processing."""
        if self.is_running:
            logger.info("Stopping ReazonSpeech stream processing...")
            self.is_running = False

            # Wait for worker thread to finish processing remaining segments
            if self.processing_thread and self.processing_thread.is_alive():
                self.processing_thread.join(timeout=10)

            # Flush remaining text buffer under lock
            with self._lock:
                if self.text_buffer.strip():
                    self._post_sentence(self.text_buffer.strip())
                    self.text_buffer = ""

            logger.info("ReazonSpeech stream processing stopped")

    def get_status(self) -> Dict[str, Any]:
        """Get current processing status."""
        return {
            "is_running": self.is_running,
            "stream_info": self.stream_info,
            "pending_segments": self.segment_queue.qsize(),
            "text_buffer_length": len(self.text_buffer),
            "transcriber": "reazonspeech-k2",
        }
