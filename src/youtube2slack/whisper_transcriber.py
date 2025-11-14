"""Whisper transcription module."""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Optional, Any, Callable, List
import logging

import whisper
import torch


logger = logging.getLogger(__name__)


class TranscriptionError(Exception):
    """Exception raised for transcription failures."""
    pass


def format_timestamp(seconds: float) -> str:
    """Format seconds to HH:MM:SS format.
    
    Args:
        seconds: Time in seconds
        
    Returns:
        Formatted time string
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def split_long_text(text: str, max_length: int = 2000) -> List[str]:
    """Split long text into chunks at sentence boundaries.
    
    Args:
        text: Text to split
        max_length: Maximum length of each chunk
        
    Returns:
        List of text chunks
    """
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    current_chunk = ""
    sentences = text.split('. ')
    
    for sentence in sentences:
        if not sentence:
            continue
            
        # Add period back if not the last sentence
        if sentence != sentences[-1]:
            sentence += '.'
            
        if len(current_chunk) + len(sentence) + 1 <= max_length:
            if current_chunk:
                current_chunk += ' '
            current_chunk += sentence
        else:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = sentence
    
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks


class WhisperTranscriber:
    """Transcribe audio using local Whisper model."""

    def __init__(self, model_name: str = "base", device: Optional[str] = None, 
                 download_root: Optional[str] = None):
        """Initialize the transcriber.
        
        Args:
            model_name: Whisper model size (tiny, base, small, medium, large, large-v2, large-v3)
            device: Device to use (cuda, cpu, or None for auto-detect)
            download_root: Directory to download/load models from
        """
        self.model_name = model_name
        self.download_root = download_root
        
        # Auto-detect device if not specified
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device
            
        logger.info(f"Loading Whisper model '{model_name}' on device '{self.device}'")
        
        try:
            self.model = whisper.load_model(
                model_name, 
                device=self.device,
                download_root=download_root
            )
        except Exception as e:
            raise TranscriptionError(f"Failed to load Whisper model: {e}")
            
        logger.info(f"Whisper model loaded successfully")

    def transcribe(self, audio_path: str, language: Optional[str] = None,
                  include_timestamps: bool = True,
                  progress_callback: Optional[Callable[[float], None]] = None) -> Dict[str, Any]:
        """Transcribe audio file.
        
        Args:
            audio_path: Path to audio file
            language: Language code (e.g., 'en', 'ja') or None for auto-detect
            include_timestamps: Whether to include timestamp information
            progress_callback: Optional callback for progress updates
            
        Returns:
            Dictionary with transcription results
            
        Raises:
            TranscriptionError: If transcription fails
        """
        if not os.path.exists(audio_path):
            raise TranscriptionError(f"Audio file not found: {audio_path}")

        try:
            logger.info(f"Starting transcription of {audio_path}")
            
            # Prepare transcription options
            options = {
                'language': language,
                'task': 'transcribe',
                'verbose': False,
                'temperature': 0,
                'compression_ratio_threshold': 2.4,
                'logprob_threshold': -1.0,
                'no_speech_threshold': 0.6,
                'condition_on_previous_text': True,
                'initial_prompt': None,
                'word_timestamps': False,
                'prepend_punctuations': "\"'¿([{-",
                'append_punctuations': "\"'.。,，!！?？:：)]}、",
            }
            
            if progress_callback:
                options['progress_callback'] = progress_callback
            
            # Transcribe
            result = self.model.transcribe(audio_path, **options)
            
            # Format result
            formatted_result = {
                'text': result['text'].strip(),
                'language': result.get('language', 'unknown'),
                'segments': []
            }
            
            if include_timestamps and 'segments' in result:
                for segment in result['segments']:
                    formatted_result['segments'].append({
                        'start': segment['start'],
                        'end': segment['end'],
                        'text': segment['text'].strip(),
                        'start_formatted': format_timestamp(segment['start']),
                        'end_formatted': format_timestamp(segment['end'])
                    })
                    
            # Add timing information
            if result.get('segments'):
                total_duration = result['segments'][-1]['end'] if result['segments'] else 0
                formatted_result['timing'] = {
                    'duration': total_duration,
                    'duration_formatted': format_timestamp(total_duration)
                }
            
            logger.info(f"Transcription completed. Language: {formatted_result['language']}")
            return formatted_result
            
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise TranscriptionError(f"Transcription failed: {e}")

    def extract_audio(self, video_path: str, output_dir: Optional[str] = None) -> str:
        """Extract audio from video file.
        
        Args:
            video_path: Path to video file
            output_dir: Directory to save extracted audio (uses temp dir if None)
            
        Returns:
            Path to extracted audio file
            
        Raises:
            TranscriptionError: If audio extraction fails
        """
        if not os.path.exists(video_path):
            raise TranscriptionError(f"Video file not found: {video_path}")

        # Determine output path
        if output_dir is None:
            output_dir = tempfile.gettempdir()
            
        video_name = Path(video_path).stem
        audio_path = os.path.join(output_dir, f"{video_name}_audio.wav")
        
        # Extract audio using ffmpeg
        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-vn',  # No video
            '-acodec', 'pcm_s16le',  # PCM 16-bit
            '-ar', '16000',  # 16kHz sample rate (Whisper's expected rate)
            '-ac', '1',  # Mono
            '-y',  # Overwrite output
            audio_path
        ]
        
        logger.info(f"Extracting audio from {video_path}")
        
        try:
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True,
                check=False
            )
            
            if result.returncode != 0:
                raise TranscriptionError(
                    f"Failed to extract audio: {result.stderr}"
                )
                
            logger.info(f"Audio extracted to {audio_path}")
            return audio_path
            
        except subprocess.SubprocessError as e:
            raise TranscriptionError(f"Failed to extract audio: {e}")

    def transcribe_video(self, video_path: str, language: Optional[str] = None,
                        include_timestamps: bool = True,
                        cleanup_audio: bool = True,
                        progress_callback: Optional[Callable[[float], None]] = None) -> Dict[str, Any]:
        """Transcribe video file by extracting audio first.
        
        Args:
            video_path: Path to video file
            language: Language code or None for auto-detect
            include_timestamps: Whether to include timestamp information
            cleanup_audio: Whether to delete extracted audio after transcription
            progress_callback: Optional callback for progress updates
            
        Returns:
            Dictionary with transcription results
        """
        audio_path = None
        
        try:
            # Extract audio
            audio_path = self.extract_audio(video_path)
            
            # Transcribe
            result = self.transcribe(
                audio_path, 
                language=language,
                include_timestamps=include_timestamps,
                progress_callback=progress_callback
            )
            
            # Add video information
            result['video_path'] = video_path
            
            return result
            
        finally:
            # Cleanup if requested
            if cleanup_audio and audio_path and os.path.exists(audio_path):
                try:
                    os.remove(audio_path)
                    logger.info(f"Cleaned up temporary audio file: {audio_path}")
                except Exception as e:
                    logger.warning(f"Failed to cleanup audio file: {e}")

    def get_available_models(self) -> List[str]:
        """Get list of available Whisper models.
        
        Returns:
            List of model names
        """
        return [
            'tiny', 'tiny.en',
            'base', 'base.en',
            'small', 'small.en',
            'medium', 'medium.en',
            'large', 'large-v1', 'large-v2', 'large-v3'
        ]

    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the loaded model.
        
        Returns:
            Dictionary with model information
        """
        return {
            'model_name': self.model_name,
            'device': self.device,
            'n_mels': self.model.dims.n_mels,
            'n_vocab': self.model.dims.n_vocab,
            'n_audio_ctx': self.model.dims.n_audio_ctx,
            'n_audio_state': self.model.dims.n_audio_state,
            'n_audio_head': self.model.dims.n_audio_head,
            'n_audio_layer': self.model.dims.n_audio_layer,
        }