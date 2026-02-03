"""Whisper transcription module."""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Optional, Any, Callable, List
import logging

import whisper
import torch
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    openai = None


logger = logging.getLogger(__name__)


class TranscriptionError(Exception):
    """Exception raised for transcription failures."""
    pass


class OpenAITranscriptionError(TranscriptionError):
    """Exception raised for OpenAI API transcription failures."""
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


class OpenAIWhisperTranscriber:
    """Transcribe audio using OpenAI Whisper API."""

    def __init__(self, api_key: str, model: str = "whisper-1"):
        """Initialize the OpenAI Whisper transcriber.
        
        Args:
            api_key: OpenAI API key
            model: OpenAI Whisper model name (whisper-1)
        """
        if not OPENAI_AVAILABLE:
            raise OpenAITranscriptionError("OpenAI library is not available. Please install openai>=1.0.0")
        
        if not api_key:
            raise OpenAITranscriptionError("OpenAI API key is required")
        
        self.client = openai.OpenAI(api_key=api_key)
        self.model = model
        
        logger.info(f"Initialized OpenAI Whisper transcriber with model '{model}'")

    def transcribe(self, audio_path: str, language: Optional[str] = None,
                  include_timestamps: bool = True,
                  progress_callback: Optional[Callable[[float], None]] = None) -> Dict[str, Any]:
        """Transcribe audio file using OpenAI API.
        
        Args:
            audio_path: Path to audio file
            language: Language code (e.g., 'en', 'ja') or None for auto-detect
            include_timestamps: Whether to include timestamp information (limited support in API)
            progress_callback: Optional callback for progress updates (not used for API)
            
        Returns:
            Dictionary with transcription results
            
        Raises:
            OpenAITranscriptionError: If transcription fails
        """
        if not os.path.exists(audio_path):
            raise OpenAITranscriptionError(f"Audio file not found: {audio_path}")

        try:
            logger.info(f"Starting OpenAI transcription of {audio_path}")
            
            # Check file size (OpenAI limit is 25MB)
            file_size = os.path.getsize(audio_path)
            if file_size > 25 * 1024 * 1024:  # 25MB
                raise OpenAITranscriptionError(f"File too large: {file_size / (1024*1024):.1f}MB (max: 25MB)")
            
            # Prepare transcription options
            transcribe_params = {
                'model': self.model,
                'response_format': 'verbose_json' if include_timestamps else 'text',
            }
            
            if language:
                transcribe_params['language'] = language
            
            # Open and transcribe file
            with open(audio_path, 'rb') as audio_file:
                result = self.client.audio.transcriptions.create(
                    file=audio_file,
                    **transcribe_params
                )
            
            # Format result based on response format
            if include_timestamps and hasattr(result, 'segments'):
                # Verbose JSON format with segments
                formatted_result = {
                    'text': result.text.strip(),
                    'language': getattr(result, 'language', 'unknown'),
                    'segments': []
                }
                
                # Format segments if available
                if hasattr(result, 'segments') and result.segments:
                    for segment in result.segments:
                        formatted_result['segments'].append({
                            'start': segment.get('start', 0),
                            'end': segment.get('end', 0),
                            'text': segment.get('text', '').strip(),
                            'start_formatted': format_timestamp(segment.get('start', 0)),
                            'end_formatted': format_timestamp(segment.get('end', 0))
                        })
                    
                    # Add timing information
                    if formatted_result['segments']:
                        total_duration = formatted_result['segments'][-1]['end']
                        formatted_result['timing'] = {
                            'duration': total_duration,
                            'duration_formatted': format_timestamp(total_duration)
                        }
                
            else:
                # Simple text format
                formatted_result = {
                    'text': result if isinstance(result, str) else result.text.strip(),
                    'language': 'unknown',  # API doesn't return language in text mode
                    'segments': []
                }
            
            logger.info(f"OpenAI transcription completed. Language: {formatted_result['language']}")
            return formatted_result
            
        except openai.OpenAIError as e:
            logger.error(f"OpenAI API error: {e}")
            raise OpenAITranscriptionError(f"OpenAI API error: {e}")
        except Exception as e:
            logger.error(f"OpenAI transcription failed: {e}")
            raise OpenAITranscriptionError(f"Transcription failed: {e}")

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
        # Use local Whisper's audio extraction since it's already implemented
        local_transcriber = WhisperTranscriber("base")  # Dummy model for audio extraction
        audio_path = None
        
        try:
            # Extract audio
            audio_path = local_transcriber.extract_audio(video_path)
            
            # Transcribe with OpenAI
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

    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the OpenAI model.
        
        Returns:
            Dictionary with model information
        """
        return {
            'model_name': self.model,
            'service': 'openai',
            'api_based': True,
            'max_file_size_mb': 25,
        }


class TranscriberFactory:
    """Factory class to create appropriate transcriber based on user settings."""
    
    @staticmethod
    def create_transcriber(user_settings, fallback_config=None, user_id=None):
        """Create transcriber instance based on user settings.
        
        Args:
            user_settings: UserSettings object from user_cookie_manager
            fallback_config: Optional fallback configuration for local Whisper
            user_id: User ID for permission checking
            
        Returns:
            WhisperTranscriber or OpenAIWhisperTranscriber instance
            
        Raises:
            TranscriptionError: If configuration is invalid
        """
        # Import here to avoid circular imports
        try:
            from .user_cookie_manager import WhisperService
        except ImportError:
            # Fallback for testing or standalone usage
            from enum import Enum
            class WhisperService(Enum):
                LOCAL = "local"
                OPENAI = "openai"
        
        # Check local Whisper permissions
        local_whisper_allowed = True
        if fallback_config and hasattr(fallback_config, 'is_local_whisper_allowed') and user_id:
            local_whisper_allowed = fallback_config.is_local_whisper_allowed(user_id)
        
        if user_settings.whisper_service == WhisperService.OPENAI:
            # Try OpenAI API transcriber
            if not user_settings.openai_api_key:
                if local_whisper_allowed:
                    logger.warning("OpenAI service selected but no API key found, falling back to local Whisper")
                    return TranscriberFactory._create_local_transcriber(user_settings, fallback_config)
                else:
                    logger.error("OpenAI service selected but no API key found, and local Whisper not allowed for this user")
                    raise TranscriptionError("OpenAI API key required. Local Whisper access restricted for this user.")
            
            try:
                return OpenAIWhisperTranscriber(
                    api_key=user_settings.openai_api_key,
                    model="whisper-1"
                )
            except OpenAITranscriptionError as e:
                if local_whisper_allowed:
                    logger.warning(f"Failed to create OpenAI transcriber: {e}, falling back to local Whisper")
                    return TranscriberFactory._create_local_transcriber(user_settings, fallback_config)
                else:
                    logger.error(f"Failed to create OpenAI transcriber: {e}, and local Whisper not allowed for this user")
                    raise TranscriptionError(f"OpenAI API failed: {e}. Local Whisper access restricted for this user.")
        
        else:
            # User wants local Whisper - check permissions
            if not local_whisper_allowed:
                logger.warning(f"User {user_id} attempted to use local Whisper but is not authorized")
                raise TranscriptionError("Local Whisper access restricted. Please set up OpenAI API key with '/set-openai-key' command.")
            
            # Use local Whisper
            return TranscriberFactory._create_local_transcriber(user_settings, fallback_config)
    
    @staticmethod
    def _create_local_transcriber(user_settings, fallback_config):
        """Create local WhisperTranscriber instance."""
        # Use user's preferred model or fallback
        model_name = user_settings.whisper_model if user_settings.whisper_model else "base"
        
        # Use fallback config if available
        device = None
        download_root = None
        if fallback_config:
            device = getattr(fallback_config, 'whisper_device', None)
            download_root = getattr(fallback_config, 'whisper_download_root', None)
        
        return WhisperTranscriber(
            model_name=model_name,
            device=device,
            download_root=download_root
        )