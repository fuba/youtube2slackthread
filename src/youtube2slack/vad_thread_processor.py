"""VAD-based real-time stream processing with Slack thread support."""

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
from .slack_bot_client import SlackBotClient, ThreadInfo, SlackBotError


logger = logging.getLogger(__name__)


class VADThreadProcessingError(Exception):
    """Exception raised for VAD thread processing failures."""
    pass


class VADThreadProcessor:
    """Process live YouTube streams with Voice Activity Detection and Slack threads."""

    # Class-level registry for active streams
    _active_streams: Dict[str, 'VADThreadProcessor'] = {}
    _stream_lock = threading.Lock()

    def __init__(self, transcriber: WhisperTranscriber, slack_bot_client: SlackBotClient,
                 vad_aggressiveness: int = 2, frame_duration_ms: int = 30):
        """Initialize VAD thread processor.
        
        Args:
            transcriber: WhisperTranscriber instance
            slack_bot_client: SlackBotClient for thread posting
            vad_aggressiveness: VAD aggressiveness level (0-3, higher = more strict)
            frame_duration_ms: Frame duration for VAD analysis (10, 20, or 30 ms)
        """
        self.transcriber = transcriber
        self.slack_bot_client = slack_bot_client
        self.vad_aggressiveness = vad_aggressiveness
        self.frame_duration_ms = frame_duration_ms
        
        # Thread info for current stream
        self.thread_info: Optional[ThreadInfo] = None
        self.stream_info: Dict[str, Any] = {}
        self.stream_id: Optional[str] = None
        
        # Processing state
        self.is_running = False
        self.ffmpeg_process = None
        self.processing_thread = None
        self.audio_queue = queue.Queue()
        
        # VAD setup
        if VAD_AVAILABLE:
            self.vad = webrtcvad.Vad(self.vad_aggressiveness)
        else:
            self.vad = None
            
        # Processing parameters
        self.sample_rate = 16000
        self.channels = 1
        self.min_voice_duration = 1.0  # Minimum seconds of voice activity (reduced for testing)
        self.max_silence_duration = 1.0  # Maximum seconds of silence before split (reduced for testing)
        self.sentence_end_patterns = {
            'ja': re.compile(r'[。！？]'),
            'en': re.compile(r'[.!?]')
        }
        
        # Sentence tracking for deduplication
        self.recent_sentences = []
        self.max_recent_sentences = 10
        
    def start_stream_processing(self, stream_url: str, channel_id: str,
                              progress_callback: Optional[Callable] = None) -> ThreadInfo:
        """Start processing the live stream and create thread.
        
        Args:
            stream_url: YouTube stream URL
            channel_id: Slack channel ID
            progress_callback: Optional callback for progress updates
            
        Returns:
            ThreadInfo for the created thread
            
        Raises:
            VADThreadProcessingError: If processing fails
        """
        if self.is_running:
            raise VADThreadProcessingError("Processing already in progress")
            
        try:
            # Get stream info
            logger.info(f"Starting VAD thread processing for: {stream_url}")
            self.stream_info = self._get_stream_info(stream_url)
            self.stream_id = self.stream_info.get('id', stream_url)
            
            # Register this stream as active
            with VADThreadProcessor._stream_lock:
                if self.stream_id in VADThreadProcessor._active_streams:
                    raise VADThreadProcessingError(f"Stream {self.stream_id} is already being processed")
                VADThreadProcessor._active_streams[self.stream_id] = self
            
            # Create thread in Slack
            self.thread_info = self.slack_bot_client.create_thread(
                channel=channel_id,
                video_title=self.stream_info['title'],
                video_url=stream_url,
                duration=None,  # Unknown for live streams
                language=None   # Will be detected
            )
            
            # Post initial status
            self.slack_bot_client.post_to_thread(
                self.thread_info,
                f"🔴 *Starting VAD-based real-time processing*\n"
                f"• Voice detection level: {self.vad_aggressiveness}\n"
                f"• Processing live audio with sentence boundary detection"
            )
            
            self.is_running = True
            
            # Start audio extraction
            self._start_audio_extraction(stream_url)
            
            # Start processing thread
            self.processing_thread = threading.Thread(
                target=self._process_audio_stream,
                args=(progress_callback,),
                daemon=True
            )
            self.processing_thread.start()
            
            logger.info("VAD thread processing started successfully")
            return self.thread_info
            
        except Exception as e:
            self.is_running = False
            raise VADThreadProcessingError(f"Failed to start processing: {e}")
    
    def stop_processing(self) -> None:
        """Stop the stream processing."""
        logger.info("Stopping VAD thread processing...")
        self.is_running = False
        
        # Terminate ffmpeg
        if self.ffmpeg_process and self.ffmpeg_process.poll() is None:
            self.ffmpeg_process.terminate()
            try:
                self.ffmpeg_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.ffmpeg_process.kill()
                
        # Post final message
        if self.thread_info:
            try:
                self.slack_bot_client.post_to_thread(
                    self.thread_info,
                    "🛑 *Stream processing stopped*"
                )
            except Exception as e:
                logger.error(f"Failed to post stop message: {e}")
        
        # Unregister this stream
        if self.stream_id:
            with VADThreadProcessor._stream_lock:
                VADThreadProcessor._active_streams.pop(self.stream_id, None)
    
    def _get_stream_info(self, stream_url: str) -> Dict[str, Any]:
        """Get information about the stream using yt-dlp.
        
        Args:
            stream_url: YouTube stream URL
            
        Returns:
            Stream information dictionary
        """
        import yt_dlp
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(stream_url, download=False)
                return {
                    'title': info.get('title', 'Unknown Stream'),
                    'url': stream_url,
                    'id': info.get('id', stream_url.split('=')[-1] if '=' in stream_url else stream_url),
                    'is_live': info.get('is_live', False),
                    'uploader': info.get('uploader', 'Unknown')
                }
        except Exception as e:
            logger.error(f"Failed to get stream info: {e}")
            return {
                'title': 'Live Stream',
                'url': stream_url,
                'id': stream_url.split('=')[-1] if '=' in stream_url else stream_url,
                'is_live': True,
                'uploader': 'Unknown'
            }
    
    def _start_audio_extraction(self, stream_url: str) -> None:
        """Start ffmpeg process to extract audio from stream.
        
        Args:
            stream_url: YouTube stream URL
        """
        # Use yt-dlp to get the actual stream URL
        import yt_dlp
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': 'bestaudio/best'
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(stream_url, download=False)
            audio_url = info['url']
        
        # ffmpeg command to extract audio
        cmd = [
            'ffmpeg',
            '-i', audio_url,
            '-f', 's16le',
            '-ar', str(self.sample_rate),
            '-ac', str(self.channels),
            '-acodec', 'pcm_s16le',
            '-loglevel', 'error',
            '-flush_packets', '1',
            '-fflags', '+nobuffer',
            '-'
        ]
        
        self.ffmpeg_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0
        )
        
        logger.info("Started audio extraction with ffmpeg")
    
    def _process_audio_stream(self, progress_callback: Optional[Callable] = None) -> None:
        """Process the audio stream with VAD and transcription."""
        audio_buffer = bytearray()
        voice_buffer = bytearray()
        silence_frames = 0
        voice_frames = 0
        
        # Frame size calculation
        frame_size = int(self.sample_rate * self.frame_duration_ms / 1000) * 2  # 2 bytes per sample
        frames_per_second = 1000 / self.frame_duration_ms
        min_voice_frames = int(self.min_voice_duration * frames_per_second)
        max_silence_frames = int(self.max_silence_duration * frames_per_second)
        max_segment_frames = int(15.0 * frames_per_second)  # Maximum 15 seconds per segment
        
        sentence_buffer = ""
        detected_language = None
        segment_start_time = time.time()
        
        try:
            logger.info(f"Starting audio processing loop. Frame size: {frame_size}")
            logger.info(f"min_voice_frames: {min_voice_frames}, max_silence_frames: {max_silence_frames}, max_segment_frames: {max_segment_frames}")
            logger.info(f"frames_per_second: {frames_per_second}")
            frame_count = 0
            while self.is_running and self.ffmpeg_process and self.ffmpeg_process.poll() is None:
                try:
                    # Read audio data with timeout
                    import select
                    if select.select([self.ffmpeg_process.stdout], [], [], 1.0)[0]:
                        data = self.ffmpeg_process.stdout.read(frame_size)
                        if not data:
                            logger.warning("No audio data received from ffmpeg")
                            break
                        if len(data) < frame_size:
                            logger.debug(f"Partial frame received: {len(data)}/{frame_size} bytes")
                            continue
                        # Debug: log data reception occasionally
                        if frame_count % 500 == 0:
                            logger.info(f"Received audio data: {len(data)} bytes at frame {frame_count}")
                    else:
                        logger.debug("Timeout waiting for audio data")
                        continue
                except Exception as e:
                    logger.error(f"Error reading audio data: {e}")
                    break
                    
                frame_count += 1
                if frame_count % 100 == 0:  # Log every 100 frames (about 3 seconds) 
                    logger.info(f"Processed {frame_count} audio frames, voice_frames={voice_frames}, silence_frames={silence_frames}")
                
                # TESTING: Force transcription every 200 frames (6 seconds) if we have voice data
                if frame_count % 200 == 0 and voice_frames > 0:
                    logger.info(f"TESTING: Force processing at frame {frame_count} with {voice_frames} voice frames")
                    transcription = self._transcribe_segment(voice_buffer, detected_language)
                    if transcription:
                        text = transcription['text'].strip()
                        if text:
                            logger.info(f"TESTING: Transcription result: {text}")
                            self.slack_bot_client.post_to_thread(self.thread_info, f"🔍 TEST: {text}")
                    # Reset for next test
                    voice_buffer = bytearray()
                    voice_frames = 0
                    silence_frames = 0
                    
                audio_buffer.extend(data)
                
                # Process when we have enough data
                while len(audio_buffer) >= frame_size:
                    frame = audio_buffer[:frame_size]
                    audio_buffer = audio_buffer[frame_size:]
                    
                    # Check for voice activity
                    is_speech = self._is_speech(frame)
                    
                    # Debug VAD decisions every 100 frames
                    if frame_count % 100 == 0:
                        logger.debug(f"VAD decision at frame {frame_count}: is_speech={is_speech}, voice_frames={voice_frames}")
                    
                    if is_speech:
                        if voice_frames == 0:  # First speech frame detected
                            logger.info("Speech detected, starting voice buffer")
                            segment_start_time = time.time()
                        voice_buffer.extend(frame)
                        voice_frames += 1
                        silence_frames = 0
                        
                        # Check if segment is getting too long (continuous speech)
                        if voice_frames >= max_segment_frames and voice_frames >= min_voice_frames:
                            logger.info(f"Processing voice segment (timeout): {voice_frames} frames ({voice_frames/frames_per_second:.1f}s)")
                            # Process the voice segment
                            transcription = self._transcribe_segment(
                                voice_buffer,
                                detected_language
                            )
                            
                            if transcription:
                                # Update detected language
                                if not detected_language:
                                    detected_language = transcription.get('language')
                                    self.slack_bot_client.post_to_thread(
                                        self.thread_info,
                                        f"🌐 *Language detected:* {detected_language}"
                                    )
                                
                                # Get transcribed text
                                text = transcription['text'].strip()
                                
                                # Check for duplicates
                                if not self._is_duplicate_sentence(text):
                                    # Add to sentence buffer
                                    sentence_buffer += text + " "
                                    
                                    # Check if we have complete sentences
                                    complete_sentences = self._extract_complete_sentences(
                                        sentence_buffer,
                                        detected_language
                                    )
                                    
                                    if complete_sentences:
                                        # Post to thread
                                        self.slack_bot_client.post_to_thread(
                                            self.thread_info,
                                            complete_sentences
                                        )
                                        
                                        # Update recent sentences
                                        self._update_recent_sentences(complete_sentences)
                                        
                                        # Remove posted sentences from buffer
                                        sentence_buffer = sentence_buffer.replace(
                                            complete_sentences, ""
                                        ).strip()
                                        
                                        if progress_callback:
                                            progress_callback(
                                                f"Posted: {len(complete_sentences)} chars"
                                            )
                            
                            # Reset buffers
                            voice_buffer = bytearray()
                            voice_frames = 0
                            silence_frames = 0
                            segment_start_time = time.time()
                    else:
                        if voice_frames > 0:
                            voice_buffer.extend(frame)
                            silence_frames += 1
                            
                            # Check if we should process the voice segment
                            if (voice_frames >= min_voice_frames and 
                                (silence_frames >= max_silence_frames or 
                                 voice_frames >= max_segment_frames or
                                 self._should_split_at_sentence(voice_buffer, detected_language))):
                                
                                reason = "silence" if silence_frames >= max_silence_frames else "timeout" if voice_frames >= max_segment_frames else "sentence"
                                logger.info(f"Processing voice segment ({reason}): {voice_frames} frames ({voice_frames/frames_per_second:.1f}s), {silence_frames} silence frames")
                                # Process the voice segment
                                transcription = self._transcribe_segment(
                                    voice_buffer,
                                    detected_language
                                )
                                
                                if transcription:
                                    # Update detected language
                                    if not detected_language:
                                        detected_language = transcription.get('language')
                                        self.slack_bot_client.post_to_thread(
                                            self.thread_info,
                                            f"🌐 *Language detected:* {detected_language}"
                                        )
                                    
                                    # Get transcribed text
                                    text = transcription['text'].strip()
                                    
                                    # Check for duplicates
                                    if not self._is_duplicate_sentence(text):
                                        # Add to sentence buffer
                                        sentence_buffer += text + " "
                                        
                                        # Check if we have complete sentences
                                        complete_sentences = self._extract_complete_sentences(
                                            sentence_buffer,
                                            detected_language
                                        )
                                        
                                        if complete_sentences:
                                            # Post to thread
                                            self.slack_bot_client.post_to_thread(
                                                self.thread_info,
                                                complete_sentences
                                            )
                                            
                                            # Update recent sentences
                                            self._update_recent_sentences(complete_sentences)
                                            
                                            # Remove posted sentences from buffer
                                            sentence_buffer = sentence_buffer.replace(
                                                complete_sentences, ""
                                            ).strip()
                                            
                                            if progress_callback:
                                                progress_callback(
                                                    f"Posted: {len(complete_sentences)} chars"
                                                )
                                
                                # Reset buffers
                                voice_buffer = bytearray()
                                voice_frames = 0
                                silence_frames = 0
                                segment_start_time = time.time()
                        else:
                            # No voice activity
                            silence_frames = 0
                            
        except Exception as e:
            logger.error(f"Error in audio processing: {e}")
            if self.thread_info:
                try:
                    self.slack_bot_client.post_error_to_thread(
                        self.thread_info,
                        f"Processing error: {e}"
                    )
                except:
                    pass
                    
        finally:
            # Process any remaining audio
            if voice_buffer and voice_frames >= min_voice_frames:
                transcription = self._transcribe_segment(voice_buffer, detected_language)
                if transcription and transcription['text'].strip():
                    self.slack_bot_client.post_to_thread(
                        self.thread_info,
                        transcription['text'].strip()
                    )
            
            # Post final buffer if any
            if sentence_buffer.strip():
                self.slack_bot_client.post_to_thread(
                    self.thread_info,
                    sentence_buffer.strip()
                )
    
    def _is_speech(self, frame: bytes) -> bool:
        """Check if frame contains speech using VAD.
        
        Args:
            frame: Audio frame data
            
        Returns:
            True if speech detected
        """
        if self.vad and VAD_AVAILABLE:
            try:
                return self.vad.is_speech(frame, self.sample_rate)
            except Exception as e:
                logger.error(f"VAD error: {e}")
                return self._simple_voice_detection(frame)
        else:
            return self._simple_voice_detection(frame)
    
    def _simple_voice_detection(self, frame: bytes) -> bool:
        """Simple voice detection based on amplitude.
        
        Args:
            frame: Audio frame data
            
        Returns:
            True if voice detected
        """
        # Convert bytes to int16 samples
        samples = struct.unpack(f'{len(frame)//2}h', frame)
        
        # Calculate RMS
        rms = (sum(s*s for s in samples) / len(samples)) ** 0.5
        
        # Simple threshold
        return rms > 500
    
    def _should_split_at_sentence(self, audio_buffer: bytearray, 
                                 language: Optional[str]) -> bool:
        """Check if we should split at a sentence boundary.
        
        Args:
            audio_buffer: Current audio buffer
            language: Detected language
            
        Returns:
            True if we should split
        """
        # For now, rely on silence detection
        # Could be enhanced with real-time transcription lookahead
        return False
    
    def _transcribe_segment(self, audio_data: bytearray, 
                          language: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Transcribe an audio segment.
        
        Args:
            audio_data: Raw audio data
            language: Optional language hint
            
        Returns:
            Transcription result or None
        """
        try:
            # Create temporary WAV file
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
                # Write WAV header
                with wave.open(tmp_file.name, 'wb') as wav_file:
                    wav_file.setnchannels(self.channels)
                    wav_file.setsampwidth(2)  # 16-bit
                    wav_file.setframerate(self.sample_rate)
                    wav_file.writeframes(bytes(audio_data))
                
                # Transcribe
                result = self.transcriber.transcribe_audio(
                    tmp_file.name,
                    language=language
                )
                
                # Clean up
                os.unlink(tmp_file.name)
                
                return result
                
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return None
    
    def _extract_complete_sentences(self, text: str, language: Optional[str]) -> str:
        """Extract complete sentences from text.
        
        Args:
            text: Text to process
            language: Language code
            
        Returns:
            Complete sentences
        """
        if not language:
            return ""
            
        pattern = self.sentence_end_patterns.get(language)
        if not pattern:
            # Default to English pattern
            pattern = self.sentence_end_patterns['en']
        
        sentences = []
        current = ""
        
        for char in text:
            current += char
            if pattern.match(char):
                sentences.append(current.strip())
                current = ""
        
        return " ".join(sentences)
    
    def _is_duplicate_sentence(self, text: str) -> bool:
        """Check if text is a duplicate of recent sentences.
        
        Args:
            text: Text to check
            
        Returns:
            True if duplicate
        """
        normalized = text.lower().strip()
        
        for recent in self.recent_sentences:
            if normalized == recent.lower().strip():
                return True
            # Check for high similarity
            if self._calculate_similarity(normalized, recent.lower().strip()) > 0.8:
                return True
                
        return False
    
    def _update_recent_sentences(self, text: str) -> None:
        """Update recent sentences list.
        
        Args:
            text: New text to add
        """
        # Split into sentences
        sentences = text.split('.')
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence:
                self.recent_sentences.append(sentence)
                
        # Keep only recent ones
        if len(self.recent_sentences) > self.max_recent_sentences:
            self.recent_sentences = self.recent_sentences[-self.max_recent_sentences:]
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity between two texts.
        
        Args:
            text1: First text
            text2: Second text
            
        Returns:
            Similarity score (0-1)
        """
        # Simple character-based similarity
        if not text1 or not text2:
            return 0.0
            
        # Remove common words for comparison
        words1 = set(text1.split())
        words2 = set(text2.split())
        
        if not words1 or not words2:
            return 0.0
            
        intersection = words1 & words2
        union = words1 | words2
        
        return len(intersection) / len(union)
    
    @classmethod
    def get_active_streams(cls) -> Dict[str, Dict[str, Any]]:
        """Get information about all active streams.
        
        Returns:
            Dictionary with stream IDs and their info
        """
        with cls._stream_lock:
            active_info = {}
            for stream_id, processor in cls._active_streams.items():
                active_info[stream_id] = {
                    'title': processor.stream_info.get('title', 'Unknown'),
                    'url': processor.stream_info.get('url', ''),
                    'channel': processor.thread_info.channel if processor.thread_info else None,
                    'thread_ts': processor.thread_info.thread_ts if processor.thread_info else None,
                    'uploader': processor.stream_info.get('uploader', 'Unknown'),
                    'is_running': processor.is_running
                }
            return active_info
    
    @classmethod
    def stop_stream_by_id(cls, stream_id: str) -> bool:
        """Stop a specific stream by its ID.
        
        Args:
            stream_id: Stream ID to stop
            
        Returns:
            True if stream was found and stopped, False otherwise
        """
        with cls._stream_lock:
            processor = cls._active_streams.get(stream_id)
            if processor:
                processor.stop_processing()
                return True
            return False
    
    @classmethod
    def stop_all_streams(cls) -> int:
        """Stop all active streams.
        
        Returns:
            Number of streams that were stopped
        """
        with cls._stream_lock:
            stopped_count = 0
            for processor in list(cls._active_streams.values()):
                processor.stop_processing()
                stopped_count += 1
            return stopped_count