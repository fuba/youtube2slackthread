"""VAD-based real-time stream processing module."""

import os
import threading
import time
import tempfile
import subprocess
import queue
import wave
import struct
import re
from pathlib import Path
from typing import Dict, Optional, Any, Callable, List
import logging

try:
    import webrtcvad
    VAD_AVAILABLE = True
except ImportError:
    VAD_AVAILABLE = False
    logging.warning("webrtcvad not available, falling back to simple silence detection")

from .whisper_transcriber import WhisperTranscriber, TranscriptionError
from .slack_client import SlackClient, SlackError


logger = logging.getLogger(__name__)


class VADStreamProcessingError(Exception):
    """Exception raised for VAD stream processing failures."""
    pass


class VADStreamProcessor:
    """Process live YouTube streams with Voice Activity Detection."""

    def __init__(self, transcriber: WhisperTranscriber, slack_client: Optional[SlackClient] = None,
                 vad_aggressiveness: int = 2, frame_duration_ms: int = 30):
        """Initialize VAD stream processor.
        
        Args:
            transcriber: WhisperTranscriber instance
            slack_client: Optional SlackClient for posting results
            vad_aggressiveness: VAD aggressiveness level (0-3, higher = more strict)
            frame_duration_ms: Frame duration for VAD analysis (10, 20, or 30 ms)
        """
        self.transcriber = transcriber
        self.slack_client = slack_client
        self.vad_aggressiveness = vad_aggressiveness
        self.frame_duration_ms = frame_duration_ms
        
        # Initialize VAD
        if VAD_AVAILABLE:
            self.vad = webrtcvad.Vad(vad_aggressiveness)
            logger.info(f"WebRTC VAD initialized with aggressiveness {vad_aggressiveness}")
        else:
            self.vad = None
            logger.warning("Using simple silence detection instead of WebRTC VAD")
        
        self.is_running = False
        self.audio_queue = queue.Queue()
        self.processing_thread = None
        self.stream_info = {}
        
        # Audio buffering for VAD processing
        self.audio_buffer = b''
        self.speech_buffer = b''
        self.is_speaking = False
        self.silence_duration = 0.0
        self.min_speech_duration = 3.0  # Minimum speech duration in seconds  
        self.max_silence_duration = 2.0  # Maximum silence before processing chunk
        
        # Text buffering for sentence detection
        self.text_buffer = ""
        self.sentence_endings = re.compile(r'[。！？\.\!\?]')
        self.max_buffer_length = 80  # Maximum characters before forced posting
        
        # Audio settings
        self.sample_rate = 16000
        self.frame_size = int(self.sample_rate * self.frame_duration_ms / 1000)
        self.bytes_per_frame = self.frame_size * 2  # 16-bit audio
        
        # Temporary directory for audio chunks
        self.temp_dir = tempfile.mkdtemp(prefix="youtube2slack_vad_")
        
        logger.info(f"VAD stream processor initialized")

    def start_stream_processing(self, stream_url: str, 
                               progress_callback: Optional[Callable[[str], None]] = None) -> None:
        """Start processing a live stream with VAD.
        
        Args:
            stream_url: YouTube live stream URL
            progress_callback: Optional callback for progress updates
        """
        if self.is_running:
            raise VADStreamProcessingError("Stream processing already running")
            
        self.is_running = True
        self.stream_info = self._get_stream_info(stream_url)
        
        logger.info(f"Starting VAD-based processing of: {self.stream_info.get('title', 'Unknown Stream')}")
        
        # Post initial stream title to Slack
        if self.slack_client:
            stream_title = self.stream_info.get('title', 'Live Stream')
            initial_message = f"🔴 {stream_title}\n\n📡 VADベースリアルタイム処理を開始しました"
            try:
                self.slack_client.send_message(initial_message)
                logger.info("Posted stream start message to Slack")
            except Exception as e:
                logger.error(f"Failed to post initial message: {e}")
        
        if progress_callback:
            progress_callback(f"Starting VAD stream: {self.stream_info.get('title', 'Unknown')}")
        
        # Start background thread for processing audio segments
        self.processing_thread = threading.Thread(
            target=self._process_audio_worker,
            args=(progress_callback,),
            daemon=True
        )
        self.processing_thread.start()
        
        # Start continuous audio streaming with VAD
        self._start_vad_stream_capture(stream_url, progress_callback)

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

    def _start_vad_stream_capture(self, stream_url: str, 
                                progress_callback: Optional[Callable[[str], None]] = None) -> None:
        """Start continuous audio capture with VAD processing."""
        # Get the actual stream URL
        actual_stream_url = self._get_actual_stream_url(stream_url)
        if not actual_stream_url:
            raise VADStreamProcessingError("Could not get actual stream URL")
        
        try:
            # Start FFmpeg process for continuous audio streaming
            cmd = [
                'ffmpeg',
                '-i', actual_stream_url,
                '-vn',  # No video
                '-acodec', 'pcm_s16le',  # PCM 16-bit
                '-ar', str(self.sample_rate),  # 16kHz sample rate
                '-ac', '1',  # Mono
                '-f', 'wav',  # WAV format
                '-loglevel', 'error',
                '-avoid_negative_ts', 'make_zero',
                '-flush_packets', '1',
                'pipe:1'  # Output to stdout
            ]
            
            logger.info("Starting continuous FFmpeg audio stream...")
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            if progress_callback:
                progress_callback("Processing continuous audio stream with VAD...")
            
            # Read audio data continuously
            self._process_continuous_audio_stream(process, progress_callback)
            
        except Exception as e:
            logger.error(f"VAD stream capture failed: {e}")
            raise VADStreamProcessingError(f"Stream capture failed: {e}")

    def _get_actual_stream_url(self, youtube_url: str) -> Optional[str]:
        """Get the actual stream URL that ffmpeg can process."""
        try:
            cmd = [
                'yt-dlp',
                '-g',  # Get URL
                '-f', 'best[ext=mp4]',  # Best quality mp4 format
                youtube_url
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0 and result.stdout.strip():
                actual_url = result.stdout.strip().split('\n')[0]
                logger.info(f"Got actual stream URL: {actual_url[:100]}...")
                return actual_url
            else:
                logger.error(f"Failed to get stream URL: {result.stderr}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting stream URL: {e}")
            return None

    def _process_continuous_audio_stream(self, process: subprocess.Popen,
                                       progress_callback: Optional[Callable[[str], None]] = None) -> None:
        """Process continuous audio stream with VAD."""
        chunk_count = 0
        last_segment_time = time.time()
        
        try:
            while self.is_running and process.poll() is None:
                # Read audio frame
                audio_data = process.stdout.read(self.bytes_per_frame)
                if not audio_data:
                    break
                
                # Force process long speech segments (timeout)
                current_time = time.time()
                if (self.is_speaking and 
                    current_time - last_segment_time > 10 and  # 10 seconds timeout
                    len(self.speech_buffer) >= int(self.sample_rate * 2 * 2)):  # At least 2 seconds
                    
                    logger.info("Forcing segment processing due to timeout")
                    self._queue_speech_segment(chunk_count, progress_callback)
                    chunk_count += 1
                    last_segment_time = current_time
                    
                    # Reset for next segment
                    self.speech_buffer = b''
                    self.is_speaking = False
                    self.silence_duration = 0.0
                
                # Accumulate audio buffer
                self.audio_buffer += audio_data
                
                # Process when we have enough data for VAD
                while len(self.audio_buffer) >= self.bytes_per_frame:
                    frame = self.audio_buffer[:self.bytes_per_frame]
                    self.audio_buffer = self.audio_buffer[self.bytes_per_frame:]
                    
                    # Perform VAD analysis
                    is_speech = self._is_speech(frame)
                    
                    if is_speech:
                        if not self.is_speaking:
                            logger.info("Speech detected, starting recording")
                            self.is_speaking = True
                        
                        self.speech_buffer += frame
                        self.silence_duration = 0.0
                    else:
                        if self.is_speaking:
                            self.silence_duration += self.frame_duration_ms / 1000.0
                            self.speech_buffer += frame  # Include some silence
                            
                            # Debug: Log silence accumulation
                            if int(self.silence_duration) != int(self.silence_duration - self.frame_duration_ms / 1000.0):
                                speech_duration = len(self.speech_buffer) / (self.sample_rate * 2)
                                logger.debug(f"Silence: {self.silence_duration:.1f}s, Speech: {speech_duration:.1f}s")
                            
                            # If silence is long enough and we have enough speech, process it
                            speech_duration = len(self.speech_buffer) / (self.sample_rate * 2)
                            if (self.silence_duration >= self.max_silence_duration and 
                                speech_duration >= self.min_speech_duration):
                                
                                logger.info(f"Processing speech segment: duration={speech_duration:.2f}s, "
                                          f"silence={self.silence_duration:.2f}s")
                                self._queue_speech_segment(chunk_count, progress_callback)
                                chunk_count += 1
                                last_segment_time = current_time
                                
                                # Reset for next segment
                                self.speech_buffer = b''
                                self.is_speaking = False
                                self.silence_duration = 0.0
                
        except Exception as e:
            logger.error(f"Audio stream processing failed: {e}")
        finally:
            if process.poll() is None:
                process.terminate()

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

    def _queue_speech_segment(self, segment_index: int,
                            progress_callback: Optional[Callable[[str], None]] = None) -> None:
        """Queue a speech segment for transcription."""
        if len(self.speech_buffer) < int(self.sample_rate * 0.5 * 2):  # Less than 0.5 seconds
            return
            
        # Save audio segment to file
        segment_path = os.path.join(self.temp_dir, f"speech_{segment_index:04d}.wav")
        
        try:
            with wave.open(segment_path, 'wb') as wav_file:
                wav_file.setnchannels(1)  # Mono
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(self.speech_buffer)
            
            # Add to processing queue
            segment_info = {
                'path': segment_path,
                'index': segment_index,
                'timestamp': time.time(),
                'duration': len(self.speech_buffer) / (self.sample_rate * 2)
            }
            
            self.audio_queue.put(segment_info)
            logger.info(f"Queued speech segment {segment_index} "
                       f"(duration: {segment_info['duration']:.2f}s)")
            
            if progress_callback:
                progress_callback(f"Processing speech segment {segment_index + 1}")
                
        except Exception as e:
            logger.error(f"Failed to save speech segment: {e}")

    def _process_audio_worker(self, progress_callback: Optional[Callable[[str], None]] = None) -> None:
        """Background worker to process audio segments."""
        processed_segments = 0
        
        while self.is_running or not self.audio_queue.empty():
            try:
                # Get segment from queue
                segment_info = self.audio_queue.get(timeout=5)
                logger.info(f"Got audio segment {segment_info['index']} from queue")
                
                # Transcribe segment
                transcription = self._transcribe_segment(segment_info)
                
                if transcription and transcription['text'].strip():
                    logger.info(f"Transcription result: {transcription['text'][:100]}...")
                    # Add to text buffer and process sentences
                    self._process_transcription(transcription['text'].strip())
                    processed_segments += 1
                else:
                    logger.warning(f"Empty or failed transcription for segment {segment_info['index']}")
                
                # Cleanup segment file
                self._cleanup_segment(segment_info['path'])
                self.audio_queue.task_done()
                
            except queue.Empty:
                logger.debug("No audio segments in queue, waiting...")
                continue
            except Exception as e:
                logger.error(f"Audio processing failed: {e}")
                continue

    def _transcribe_segment(self, segment_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Transcribe a single audio segment."""
        try:
            result = self.transcriber.transcribe(segment_info['path'])
            return result
            
        except (TranscriptionError, Exception) as e:
            logger.error(f"Failed to transcribe segment {segment_info['index']}: {e}")
            return None

    def _process_transcription(self, text: str) -> None:
        """Process transcription text and detect sentence boundaries."""
        logger.info(f"Processing transcription: {text[:100]}...")
        self.text_buffer += text + " "  # Add space between segments
        logger.info(f"Current buffer length: {len(self.text_buffer)} chars")
        
        # Find complete sentences using regex search
        while True:
            match = self.sentence_endings.search(self.text_buffer)
            if not match:
                break
                
            # Extract sentence up to the ending
            sentence_end = match.end()
            sentence = self.text_buffer[:sentence_end].strip()
            
            # Remove the processed sentence from buffer
            self.text_buffer = self.text_buffer[sentence_end:].strip()
            
            # Post if sentence is substantial
            if sentence and len(sentence) > 5:
                logger.info(f"Found complete sentence: {sentence}")
                self._post_sentence_to_slack(sentence)
        
        # If buffer gets too long without sentence endings, force post
        if len(self.text_buffer) > self.max_buffer_length:
            # Try to break at natural points (like "という" "ですが" etc.)
            break_points = ['という', 'ですが', 'ましたが', 'ますが', 'になります', 'ということで']
            best_break = -1
            
            for point in break_points:
                pos = self.text_buffer.rfind(point)
                if pos > 50:  # Don't break too early
                    best_break = max(best_break, pos + len(point))
            
            if best_break > 0:
                # Break at natural point
                sentence = self.text_buffer[:best_break].strip()
                self.text_buffer = self.text_buffer[best_break:].strip()
                logger.info(f"Natural break at: {sentence[-20:]}...")
                self._post_sentence_to_slack(sentence)
            else:
                # Force break at character limit
                logger.info(f"Buffer too long, forcing post: {self.text_buffer[:50]}...")
                self._post_sentence_to_slack(self.text_buffer.strip())
                self.text_buffer = ""

    def _post_sentence_to_slack(self, sentence: str) -> None:
        """Post a complete sentence to Slack."""
        if not self.slack_client:
            return
            
        try:
            # Add period if missing
            if not self.sentence_endings.search(sentence[-1:]):
                sentence += "。"
            
            logger.info(f"Posting sentence to Slack: {sentence[:50]}...")
            self.slack_client.send_message(sentence)
            
        except SlackError as e:
            logger.error(f"Failed to post sentence to Slack: {e}")

    def _cleanup_segment(self, segment_path: str) -> None:
        """Clean up processed segment file."""
        try:
            if os.path.exists(segment_path):
                os.remove(segment_path)
        except Exception as e:
            logger.warning(f"Failed to cleanup segment {segment_path}: {e}")

    def stop_processing(self) -> None:
        """Stop stream processing."""
        if self.is_running:
            logger.info("Stopping VAD stream processing...")
            self.is_running = False
            
            # Process any remaining text in buffer
            if self.text_buffer.strip():
                self._post_sentence_to_slack(self.text_buffer.strip())
            
            # Wait for processing thread to finish
            if self.processing_thread and self.processing_thread.is_alive():
                self.processing_thread.join(timeout=10)
            
            # Cleanup temporary directory
            self._cleanup_temp_dir()
            
            logger.info("VAD stream processing stopped")

    def _cleanup_temp_dir(self) -> None:
        """Clean up temporary directory and all segment files."""
        try:
            if os.path.exists(self.temp_dir):
                import shutil
                shutil.rmtree(self.temp_dir)
                logger.info(f"Cleaned up temp directory: {self.temp_dir}")
        except Exception as e:
            logger.warning(f"Failed to cleanup temp directory: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Get current processing status."""
        return {
            'is_running': self.is_running,
            'stream_info': self.stream_info,
            'pending_segments': self.audio_queue.qsize(),
            'vad_available': VAD_AVAILABLE,
            'is_speaking': self.is_speaking,
            'text_buffer_length': len(self.text_buffer),
            'temp_dir': self.temp_dir
        }