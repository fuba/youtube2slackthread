# SPDX-License-Identifier: MIT
"""Pause-based streaming recognition with bounded, disjoint audio segments."""

import logging
import math
import os
import struct
import subprocess
import tempfile
import threading
import time
import wave
from typing import Any, Dict, Optional

try:
    import webrtcvad
    VAD_AVAILABLE = True
except ImportError:
    VAD_AVAILABLE = False

from .speech_services import ServiceError

logger = logging.getLogger(__name__)


class VADStreamProcessingError(Exception):
    """A stream failed; callers must not report successful completion."""


class VADStreamProcessor:
    """Capture PCM and recognize after pauses, at the audio limit, or at EOF.

    Only the capture thread owns buffers and finalization. Stop requests interrupt
    capture, leaving the owner to flush exactly once before cleaning up.
    """

    def __init__(self, transcriber, vad_aggressiveness=2, frame_duration_ms=30,
                 cookies_file=None, user_id=None, translator=None, endpoint_detector=None,
                 language=None, pause_duration=0.25, max_silence_duration=1.5,
                 max_segment_duration=12.0, result_callback=None):
        if frame_duration_ms not in (10, 20, 30):
            raise ValueError('VAD frame duration must be 10, 20 or 30 ms')
        durations = (pause_duration, max_silence_duration, max_segment_duration)
        if not all(isinstance(value, (float, int)) and math.isfinite(value) for value in durations):
            raise ValueError('Segment durations must be finite numbers')
        if not 0 < pause_duration <= max_silence_duration < max_segment_duration <= 120:
            raise ValueError('Require 0 < pause <= silence < maximum <= 120 seconds')
        self.transcriber = transcriber
        self.cookies_file = cookies_file
        self.user_id = user_id
        self.translator = translator
        self.endpoint_detector = endpoint_detector
        self.language = language
        self.pause_duration = pause_duration
        self.max_silence_duration = max_silence_duration
        self.max_segment_duration = max_segment_duration
        self.frame_duration_ms = frame_duration_ms
        self.vad = webrtcvad.Vad(vad_aggressiveness) if VAD_AVAILABLE else None
        self.sample_rate = 16000
        self.bytes_per_frame = self.sample_rate * frame_duration_ms // 1000 * 2
        self.max_segment_bytes = int(max_segment_duration * 1000 // frame_duration_ms) * self.bytes_per_frame
        if not self.max_segment_bytes:
            raise ValueError('Maximum segment duration must allow at least one VAD frame')
        self.temp_dir = tempfile.mkdtemp(prefix='youtube2slack_vad_')
        self.progress_callback = None
        self.result_callback = result_callback
        self.is_running = False
        self.stream_info = {}
        self._capture_process = None
        self._finished = threading.Event()
        self._finished.set()
        self._owner = None
        self._used = False
        self.audio_buffer = b''
        self.speech_buffer = b''
        self.is_speaking = False
        self.silence_duration = 0.0
        self._silence_samples = 0
        self._pause_checked = False
        self._cached_transcription = None
        self._sample_position = 0
        self._segment_start = 0
        self.asr_requests = 0
        self.asr_seconds = 0.0
        self.endpoint_failures = 0
        self.translation_failures = 0
        self.forced_segments = 0
        self.posted_segments = 0
        self.last_result = None
        self.text_buffer = ''

    def start_stream_processing(self, stream_url, progress_callback=None):
        if self._used:
            raise VADStreamProcessingError('Create a new processor for each stream')
        self._used = True
        self.progress_callback = progress_callback
        self.is_running = True
        self._owner = threading.get_ident()
        self._finished.clear()
        try:
            self.stream_info = self._get_stream_info(stream_url)
            self._start_vad_stream_capture(stream_url, progress_callback)
            if self.translation_failures or self.endpoint_failures:
                raise VADStreamProcessingError(
                    f'Inference failures: translation={self.translation_failures}, '
                    f'endpoint={self.endpoint_failures}'
                )
        finally:
            self.is_running = False
            self._capture_process = None
            self._cleanup_temp_dir()
            self._finished.set()

    def _get_stream_info(self, stream_url: str) -> Dict[str, Any]:
        """Get stream information without downloading."""
        try:
            cmd = [
                'yt-dlp',
                '--print', '%(title)s|||%(id)s|||%(duration)s|||%(is_live)s',
                '--no-download',
                stream_url
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            
            if result.stdout.strip():
                parts = result.stdout.strip().split('|||')
                return {
                    'title': parts[0] if len(parts) > 0 else 'Unknown',
                    'id': parts[1] if len(parts) > 1 else 'unknown',
                    'duration': parts[2] if len(parts) > 2 else None,
                    'is_live': parts[3] if len(parts) > 3 else 'False',
                    'url': stream_url
                }
            else:
                logger.warning("Could not get stream info")
                return {'title': 'Live Stream', 'url': stream_url}
                
        except (subprocess.CalledProcessError, Exception) as e:
            logger.error(f"Failed to get stream info: {e}")
            return {'title': 'Live Stream', 'url': stream_url}

    def _start_vad_stream_capture(self, stream_url, progress_callback=None):
        actual_url = self._get_actual_stream_url(stream_url)
        if not actual_url:
            raise VADStreamProcessingError('Could not get actual stream URL')
        # Raw PCM avoids treating FFmpeg's variable-sized WAV header as speech.
        cmd = ['ffmpeg', '-nostdin', '-i', actual_url, '-vn', '-acodec', 'pcm_s16le',
               '-ar', str(self.sample_rate), '-ac', '1', '-f', 's16le',
               '-loglevel', 'error', 'pipe:1']
        # A file avoids stderr pipe deadlocks; its contents may include signed URLs.
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errors)
            self._capture_process = process
            try:
                self.process_pcm_stream(process.stdout)
                if self.is_running:
                    try:
                        exit_code = process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        raise VADStreamProcessingError('FFmpeg did not finish after audio EOF') from None
                    if exit_code != 0:
                        raise VADStreamProcessingError('FFmpeg audio capture failed')
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                process.stdout.close()

    def _get_actual_stream_url(self, youtube_url: str) -> Optional[str]:
        """Get the actual stream URL that ffmpeg can process."""
        try:
            cmd = [
                'yt-dlp',
                '-g',  # Get URL
                '-f', 'best[ext=mp4]',  # Best quality mp4 format
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',  # Use newer Chrome user agent
                '--remote-components', 'ejs:github',  # Enable JavaScript challenge solver
            ]
            
            # Add cookies file if specified
            if self.cookies_file and os.path.exists(self.cookies_file):
                cmd.extend(['--cookies', self.cookies_file])
                logger.info(f"Using cookies file: {self.cookies_file}")
            
            cmd.append(youtube_url)
            
            logger.info(f"Executing yt-dlp command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0 and result.stdout.strip():
                actual_url = result.stdout.strip().split('\n')[0]
                logger.info("Resolved stream URL")
                return actual_url
            else:
                error_message = result.stderr
                logger.error(f"Failed to get stream URL: {error_message}")
                
                # Check for specific cookie-related errors
                if self._is_cookie_authentication_error(error_message):
                    raise VADStreamProcessingError(
                        "🔒 Cookie authentication failed! Please upload fresh cookies via DM.\n"
                        "Your YouTube cookies may have expired or are invalid."
                    )
                elif "Private video" in error_message:
                    raise VADStreamProcessingError("❌ This video is private and cannot be accessed.")
                elif "Video unavailable" in error_message:
                    raise VADStreamProcessingError("❌ This video is unavailable.")
                else:
                    raise VADStreamProcessingError(f"❌ Failed to access YouTube video: {error_message}")
                    
                return None
                
        except VADStreamProcessingError:
            # Re-raise specific errors with user-friendly messages
            raise
        except Exception as e:
            logger.error(f"Error getting stream URL: {e}")
            raise VADStreamProcessingError(f"❌ Unexpected error accessing YouTube: {str(e)}")
            
    def _is_cookie_authentication_error(self, error_message: str) -> bool:
        """Check if error message indicates cookie authentication failure."""
        cookie_error_patterns = [
            "Sign in to confirm you're not a bot",
            "confirm you're not a bot",
            "This helps protect our community",
            "Unable to extract initial data",
            "Requires authentication",
            "Private video",
            "Members-only content",
            "This video is only visible to Premium members",
            "restricted to paid members",
            "HTTP Error 403",
            "Forbidden",
            "Unable to download video info"
        ]
        
        for pattern in cookie_error_patterns:
            if pattern.lower() in error_message.lower():
                return True
        return False

    def process_pcm_stream(self, stream):
        """Consume 16 kHz mono PCM16, including short reads and the EOF remainder."""
        try:
            # Read to EOF even after the child exits: its pipe may still hold audio.
            while self.is_running:
                data = stream.read(self.bytes_per_frame)
                if not data:
                    break
                self.audio_buffer += data
                while len(self.audio_buffer) >= self.bytes_per_frame:
                    frame = self.audio_buffer[:self.bytes_per_frame]
                    self.audio_buffer = self.audio_buffer[self.bytes_per_frame:]
                    self._process_frame(frame)
            if len(self.audio_buffer) % 2:
                raise VADStreamProcessingError('Truncated PCM sample at input end')
            if self.audio_buffer:
                self._process_frame(self.audio_buffer)
                self.audio_buffer = b''
            self._finalize_segment('eof' if self.is_running else 'stop')
        finally:
            # A failure must not cause a later stop request to post the same audio again.
            self.speech_buffer = b''
            self.audio_buffer = b''
            self.is_speaking = False

    def _process_frame(self, frame):
        samples = len(frame) // 2
        position = self._sample_position
        self._sample_position += samples
        speech = self._is_speech(frame)
        if speech:
            if not self.speech_buffer:
                self._segment_start = position
            self.is_speaking = True
            self._silence_samples = 0
            self._pause_checked = False
        elif not self.is_speaking:
            return
        else:
            self._silence_samples += samples
        self.silence_duration = self._silence_samples / self.sample_rate
        self.speech_buffer += frame

        # Bound duration using samples, independent of input speed or ASR waiting time.
        if len(self.speech_buffer) >= self.max_segment_bytes:
            self._finalize_segment('maximum')
        elif self.silence_duration >= self.max_silence_duration:
            self._finalize_segment('silence')
        elif (self.endpoint_detector and not self._pause_checked and
              self.silence_duration >= self.pause_duration):
            self._pause_checked = True
            result = self._recognize()
            if result['text']:
                try:
                    if self.endpoint_detector.is_complete(result['text'], result.get('language')):
                        self._finalize_segment('semantic')
                except ServiceError as error:
                    self.endpoint_failures += 1
                    logger.warning('Endpoint detection failed: %s', error)
                    # Keep collecting audio until long silence or the independent maximum.

    def _recognize(self):
        if self._cached_transcription and self._cached_transcription[0] == self.speech_buffer:
            return self._cached_transcription[1]
        path = os.path.join(self.temp_dir, 'segment.wav')
        try:
            with wave.open(path, 'wb') as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(self.sample_rate)
                audio.writeframes(self.speech_buffer)
            started = time.monotonic()
            self.asr_requests += 1
            try:
                result = self.transcriber.transcribe(path, language=self.language)
            finally:
                self.asr_seconds += time.monotonic() - started
            if not isinstance(result, dict) or not isinstance(result.get('text'), str):
                raise VADStreamProcessingError('Invalid ASR response')
            self._cached_transcription = (self.speech_buffer, result)
            return result
        except VADStreamProcessingError:
            raise
        except Exception:
            raise VADStreamProcessingError('ASR request failed') from None
        finally:
            if os.path.exists(path):
                os.remove(path)

    def _finalize_segment(self, reason):
        if not self.speech_buffer:
            return
        result = self._recognize()
        start = self._segment_start / self.sample_rate
        end = (self._segment_start + len(self.speech_buffer) // 2) / self.sample_rate
        # Consume before callbacks: ambiguous delivery must not trigger automatic replay.
        self.speech_buffer = b''
        self.is_speaking = False
        self._silence_samples = 0
        self.silence_duration = 0.0
        self._pause_checked = False
        self._cached_transcription = None
        if reason == 'maximum':
            self.forced_segments += 1
        source = result['text'].strip()
        if not source:
            return
        self._post_result(source, result.get('language') or self.language, reason, start, end)

    def _post_result(self, source, language, reason, start, end):
        record = dict(id=self.posted_segments + 1, source=source, source_language=language,
                      start=start, end=end, boundary=reason, translation=None, error=None)
        message = source
        if self.translator:
            record['target_language'] = self.translator.target_language
            try:
                record['translation'] = self.translator.translate(source, language)
                message = (f"[{record['id']}] Original ({language or 'auto'}): {source}\n"
                           f"Translation ({self.translator.target_language}): {record['translation']}")
            except ServiceError as error:
                self.translation_failures += 1
                record['error'] = str(error)
                message = (f"[{record['id']}] Original ({language or 'auto'}): {source}\n"
                           f"Translation error ({self.translator.target_language}): {error}")
        self.last_result = record
        if self.result_callback:
            self.result_callback(record)
        if self.progress_callback:
            self.progress_callback(message)
        self.posted_segments += 1

    def stop_processing(self):
        """Request stop; the capture owner drains its buffers before cleanup."""
        self.is_running = False
        process = self._capture_process
        if process and process.poll() is None:
            process.terminate()
        if self._owner and self._owner != threading.get_ident():
            if not self._finished.wait(timeout=10):
                raise VADStreamProcessingError('Stream is still finishing its pending inference')

    def _is_speech(self, audio_frame: bytes) -> bool:
        """Determine if audio frame contains speech using VAD."""
        if self.vad and len(audio_frame) == self.bytes_per_frame:
            try:
                return self.vad.is_speech(audio_frame, self.sample_rate)
            except Exception as e:
                logger.warning(f"VAD failed, using fallback: {e}")
        
        # Fallback: simple energy-based detection
        return self._simple_voice_detection(audio_frame)

    def _simple_voice_detection(self, audio_frame: bytes) -> bool:
        """Simple energy-based voice detection as fallback."""
        if len(audio_frame) < 2:
            return False
            
        # Calculate RMS energy
        samples = struct.unpack(f'<{len(audio_frame)//2}h', audio_frame)
        rms = (sum(s*s for s in samples) / len(samples)) ** 0.5
        
        # Lower threshold for voice detection (more sensitive)
        return rms > 200  # More sensitive threshold

    def _cleanup_temp_dir(self) -> None:
        """Clean up temporary directory and all segment files."""
        try:
            if os.path.exists(self.temp_dir):
                import shutil
                shutil.rmtree(self.temp_dir)
                logger.info(f"Cleaned up temp directory: {self.temp_dir}")
        except Exception as e:
            logger.warning(f"Failed to cleanup temp directory: {e}")

    def get_status(self):
        return dict(is_running=self.is_running, stream_info=self.stream_info,
                    pending_segments=0, vad_available=VAD_AVAILABLE,
                    is_speaking=self.is_speaking, text_buffer_length=0,
                    temp_dir=self.temp_dir, asr_requests=self.asr_requests,
                    asr_seconds=self.asr_seconds, endpoint_failures=self.endpoint_failures,
                    translation_failures=self.translation_failures,
                    forced_segments=self.forced_segments, posted_segments=self.posted_segments,
                    last_result=self.last_result)
