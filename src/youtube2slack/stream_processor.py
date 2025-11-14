"""Real-time stream processing module."""

import os
import threading
import time
import tempfile
import subprocess
import queue
from pathlib import Path
from typing import Dict, Optional, Any, Callable, List
import logging

from .whisper_transcriber import WhisperTranscriber, TranscriptionError
from .slack_client import SlackClient, SlackError


logger = logging.getLogger(__name__)


class StreamProcessingError(Exception):
    """Exception raised for stream processing failures."""
    pass


class StreamProcessor:
    """Process live YouTube streams in real-time chunks."""

    def __init__(self, transcriber: WhisperTranscriber, slack_client: Optional[SlackClient] = None,
                 chunk_duration: int = 30, overlap_duration: int = 5):
        """Initialize stream processor.
        
        Args:
            transcriber: WhisperTranscriber instance
            slack_client: Optional SlackClient for posting results
            chunk_duration: Length of each audio chunk in seconds
            overlap_duration: Overlap between chunks to avoid cutting words
        """
        self.transcriber = transcriber
        self.slack_client = slack_client
        self.chunk_duration = chunk_duration
        self.overlap_duration = overlap_duration
        
        self.is_running = False
        self.chunk_queue = queue.Queue()
        self.processing_thread = None
        self.stream_info = {}
        
        # Temporary directory for audio chunks
        self.temp_dir = tempfile.mkdtemp(prefix="youtube2slack_stream_")
        
        logger.info(f"Stream processor initialized with {chunk_duration}s chunks")

    def start_stream_processing(self, stream_url: str, 
                               progress_callback: Optional[Callable[[str], None]] = None) -> None:
        """Start processing a live stream.
        
        Args:
            stream_url: YouTube live stream URL
            progress_callback: Optional callback for progress updates
        """
        if self.is_running:
            raise StreamProcessingError("Stream processing already running")
            
        self.is_running = True
        self.stream_info = self._get_stream_info(stream_url)
        
        logger.info(f"Starting real-time processing of: {self.stream_info.get('title', 'Unknown Stream')}")
        
        if progress_callback:
            progress_callback(f"Starting stream: {self.stream_info.get('title', 'Unknown')}")
        
        # Start background thread for processing chunks
        self.processing_thread = threading.Thread(
            target=self._process_chunks_worker,
            args=(progress_callback,),
            daemon=True
        )
        self.processing_thread.start()
        
        # Start streaming and chunking
        self._start_stream_capture(stream_url, progress_callback)

    def _get_stream_info(self, stream_url: str) -> Dict[str, Any]:
        """Get stream information without downloading.
        
        Args:
            stream_url: Stream URL
            
        Returns:
            Dictionary with stream information
        """
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

    def _start_stream_capture(self, stream_url: str, 
                            progress_callback: Optional[Callable[[str], None]] = None) -> None:
        """Start capturing stream in chunks.
        
        Args:
            stream_url: Stream URL
            progress_callback: Progress callback
        """
        # Get the actual stream URL that ffmpeg can process
        actual_stream_url = self._get_actual_stream_url(stream_url)
        if not actual_stream_url:
            raise StreamProcessingError("Could not get actual stream URL")
            
        chunk_index = 0
        
        try:
            while self.is_running:
                chunk_path = os.path.join(self.temp_dir, f"chunk_{chunk_index:04d}.wav")
                
                if progress_callback:
                    progress_callback(f"Capturing chunk {chunk_index + 1}...")
                
                # Capture chunk using ffmpeg
                success = self._capture_chunk(actual_stream_url, chunk_path, chunk_index)
                
                if success and os.path.exists(chunk_path):
                    # Add chunk to processing queue
                    chunk_info = {
                        'path': chunk_path,
                        'index': chunk_index,
                        'timestamp': time.time(),
                        'start_time': chunk_index * (self.chunk_duration - self.overlap_duration)
                    }
                    
                    self.chunk_queue.put(chunk_info)
                    logger.info(f"Added chunk {chunk_index} to processing queue")
                    chunk_index += 1
                else:
                    logger.warning(f"Failed to capture chunk {chunk_index}")
                    time.sleep(1)  # Brief pause before retrying
                    
        except Exception as e:
            logger.error(f"Stream capture failed: {e}")
            raise StreamProcessingError(f"Stream capture failed: {e}")

    def _get_actual_stream_url(self, youtube_url: str) -> Optional[str]:
        """Get the actual stream URL that ffmpeg can process.
        
        Args:
            youtube_url: YouTube URL
            
        Returns:
            Actual stream URL or None if failed
        """
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

    def _capture_chunk(self, stream_url: str, output_path: str, chunk_index: int) -> bool:
        """Capture a single audio chunk from stream.
        
        Args:
            stream_url: Stream URL  
            output_path: Output file path
            chunk_index: Chunk index number
            
        Returns:
            True if successful
        """
        try:
            # For live streams, capture current chunk without seeking
            cmd = [
                'ffmpeg',
                '-y',  # Overwrite output
                '-i', stream_url,
                '-t', str(self.chunk_duration),  # Duration
                '-vn',  # No video
                '-acodec', 'pcm_s16le',  # PCM 16-bit
                '-ar', '16000',  # 16kHz sample rate
                '-ac', '1',  # Mono
                '-loglevel', 'error',  # Reduce ffmpeg output
                '-avoid_negative_ts', 'make_zero',  # Handle live stream timing
                output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, timeout=self.chunk_duration + 15)
            
            if result.returncode == 0 and os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                if file_size > 1000:  # At least 1KB of audio data
                    logger.info(f"Successfully captured chunk {chunk_index}: {file_size} bytes")
                    return True
                else:
                    logger.warning(f"Chunk {chunk_index} too small: {file_size} bytes")
                    if os.path.exists(output_path):
                        os.remove(output_path)
            else:
                logger.error(f"ffmpeg failed for chunk {chunk_index}: {result.stderr.decode()}")
            
            return False
            
        except subprocess.TimeoutExpired:
            logger.warning(f"Chunk {chunk_index} capture timed out")
            return False
        except Exception as e:
            logger.error(f"Chunk {chunk_index} capture failed: {e}")
            return False

    def _process_chunks_worker(self, progress_callback: Optional[Callable[[str], None]] = None) -> None:
        """Background worker to process audio chunks.
        
        Args:
            progress_callback: Progress callback
        """
        processed_chunks = 0
        
        while self.is_running or not self.chunk_queue.empty():
            try:
                # Get chunk from queue (with timeout)
                chunk_info = self.chunk_queue.get(timeout=5)
                
                if progress_callback:
                    progress_callback(f"Processing chunk {chunk_info['index'] + 1}...")
                
                # Transcribe chunk
                transcription = self._transcribe_chunk(chunk_info)
                
                if transcription and transcription['text'].strip():
                    # Post to Slack if available
                    if self.slack_client:
                        self._post_chunk_to_slack(chunk_info, transcription)
                    
                    processed_chunks += 1
                    logger.info(f"Successfully processed chunk {chunk_info['index']}")
                
                # Cleanup chunk file
                self._cleanup_chunk(chunk_info['path'])
                
                self.chunk_queue.task_done()
                
            except queue.Empty:
                # No chunks to process, continue waiting
                continue
            except Exception as e:
                logger.error(f"Chunk processing failed: {e}")
                continue

    def _transcribe_chunk(self, chunk_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Transcribe a single audio chunk.
        
        Args:
            chunk_info: Chunk information dictionary
            
        Returns:
            Transcription result or None if failed
        """
        try:
            result = self.transcriber.transcribe(
                chunk_info['path'],
                include_timestamps=True
            )
            
            # Adjust timestamps to stream time
            if 'segments' in result:
                stream_start_time = chunk_info['start_time']
                for segment in result['segments']:
                    segment['stream_start'] = stream_start_time + segment['start']
                    segment['stream_end'] = stream_start_time + segment['end']
                    segment['stream_start_formatted'] = self._format_timestamp(segment['stream_start'])
                    segment['stream_end_formatted'] = self._format_timestamp(segment['stream_end'])
            
            result['chunk_index'] = chunk_info['index']
            result['stream_start_time'] = chunk_info['start_time']
            
            return result
            
        except (TranscriptionError, Exception) as e:
            logger.error(f"Failed to transcribe chunk {chunk_info['index']}: {e}")
            return None

    def _format_timestamp(self, seconds: float) -> str:
        """Format timestamp for stream display.
        
        Args:
            seconds: Time in seconds
            
        Returns:
            Formatted timestamp
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def _post_chunk_to_slack(self, chunk_info: Dict[str, Any], 
                           transcription: Dict[str, Any]) -> None:
        """Post chunk transcription to Slack.
        
        Args:
            chunk_info: Chunk information
            transcription: Transcription result
        """
        try:
            stream_time = self._format_timestamp(chunk_info['start_time'])
            
            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"🔴 Live: {self.stream_info.get('title', 'Stream')} @ {stream_time}",
                        "emoji": True
                    }
                }
            ]
            
            # Add transcript text
            text = transcription['text'].strip()
            if text:
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Chunk {chunk_info['index'] + 1}:*\n{text}"
                    }
                })
                
                # Add stream link
                if 'url' in self.stream_info:
                    blocks.append({
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"<{self.stream_info['url']}|🔗 View Live Stream>"
                        }
                    })
                
                # Add context
                blocks.append({
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Language: {transcription.get('language', 'unknown')} | Chunk: {chunk_info['index'] + 1} | Time: {stream_time}"
                        }
                    ]
                })
                
                self.slack_client.send_blocks(
                    blocks,
                    text=f"Live Stream: {text[:100]}..."
                )
                
        except SlackError as e:
            logger.error(f"Failed to post chunk to Slack: {e}")

    def _cleanup_chunk(self, chunk_path: str) -> None:
        """Clean up processed chunk file.
        
        Args:
            chunk_path: Path to chunk file
        """
        try:
            if os.path.exists(chunk_path):
                os.remove(chunk_path)
        except Exception as e:
            logger.warning(f"Failed to cleanup chunk {chunk_path}: {e}")

    def stop_processing(self) -> None:
        """Stop stream processing."""
        if self.is_running:
            logger.info("Stopping stream processing...")
            self.is_running = False
            
            # Wait for processing thread to finish
            if self.processing_thread and self.processing_thread.is_alive():
                self.processing_thread.join(timeout=10)
            
            # Cleanup temporary directory
            self._cleanup_temp_dir()
            
            logger.info("Stream processing stopped")

    def _cleanup_temp_dir(self) -> None:
        """Clean up temporary directory and all chunk files."""
        try:
            if os.path.exists(self.temp_dir):
                import shutil
                shutil.rmtree(self.temp_dir)
                logger.info(f"Cleaned up temp directory: {self.temp_dir}")
        except Exception as e:
            logger.warning(f"Failed to cleanup temp directory: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Get current processing status.
        
        Returns:
            Status information dictionary
        """
        return {
            'is_running': self.is_running,
            'stream_info': self.stream_info,
            'pending_chunks': self.chunk_queue.qsize(),
            'chunk_duration': self.chunk_duration,
            'overlap_duration': self.overlap_duration,
            'temp_dir': self.temp_dir
        }