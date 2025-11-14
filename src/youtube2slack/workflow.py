"""Main workflow orchestration module."""

import os
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Union
from pathlib import Path
import yaml

from .downloader import YouTubeDownloader, DownloadError
from .whisper_transcriber import WhisperTranscriber, TranscriptionError
from .slack_client import SlackClient, SlackError


logger = logging.getLogger(__name__)


class WorkflowError(Exception):
    """Exception raised for workflow failures."""
    pass


@dataclass
class ProcessingResult:
    """Result of processing a single video."""
    success: bool
    video_url: str
    video_title: Optional[str] = None
    video_path: Optional[str] = None
    transcription_text: Optional[str] = None
    language: Optional[str] = None
    error: Optional[str] = None
    duration: Optional[int] = None


@dataclass
class WorkflowConfig:
    """Configuration for the YouTube2Slack workflow."""
    # Download settings
    download_dir: str = "./downloads"
    video_format: str = "best"
    keep_video: bool = True
    
    # Whisper settings
    whisper_model: str = "base"
    whisper_device: Optional[str] = None
    whisper_language: Optional[str] = None
    whisper_download_root: Optional[str] = None
    
    # Slack settings
    slack_webhook: Optional[str] = None
    slack_channel: Optional[str] = None
    include_timestamps: bool = False
    send_errors_to_slack: bool = False
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'WorkflowConfig':
        """Create config from dictionary.
        
        Args:
            config_dict: Configuration dictionary
            
        Returns:
            WorkflowConfig instance
        """
        youtube_config = config_dict.get('youtube', {})
        whisper_config = config_dict.get('whisper', {})
        slack_config = config_dict.get('slack', {})
        
        return cls(
            # YouTube settings
            download_dir=youtube_config.get('download_dir', './downloads'),
            video_format=youtube_config.get('format', 'best'),
            keep_video=youtube_config.get('keep_video', True),
            
            # Whisper settings
            whisper_model=whisper_config.get('model', 'base'),
            whisper_device=whisper_config.get('device'),
            whisper_language=whisper_config.get('language'),
            whisper_download_root=whisper_config.get('download_root'),
            
            # Slack settings
            slack_webhook=slack_config.get('webhook_url'),
            slack_channel=slack_config.get('channel'),
            include_timestamps=slack_config.get('include_timestamps', False),
            send_errors_to_slack=slack_config.get('send_errors_to_slack', False)
        )
    
    @classmethod
    def from_yaml(cls, yaml_path: str) -> 'WorkflowConfig':
        """Load config from YAML file.
        
        Args:
            yaml_path: Path to YAML configuration file
            
        Returns:
            WorkflowConfig instance
        """
        with open(yaml_path, 'r') as f:
            config_dict = yaml.safe_load(f)
        return cls.from_dict(config_dict or {})


class YouTube2SlackWorkflow:
    """Main workflow for downloading, transcribing, and posting to Slack."""

    def __init__(self, config: WorkflowConfig):
        """Initialize workflow with configuration.
        
        Args:
            config: Workflow configuration
        """
        self.config = config
        
        # Initialize components
        logger.info("Initializing workflow components...")
        
        self.downloader = YouTubeDownloader(
            output_dir=config.download_dir,
            format_spec=config.video_format
        )
        
        self.transcriber = WhisperTranscriber(
            model_name=config.whisper_model,
            device=config.whisper_device,
            download_root=config.whisper_download_root
        )
        
        if config.slack_webhook:
            self.slack_client = SlackClient(
                webhook_url=config.slack_webhook,
                channel=config.slack_channel
            )
        else:
            self.slack_client = None
            logger.warning("No Slack webhook configured, results will not be posted")
            
        logger.info("Workflow initialized successfully")

    def process_video(self, video_url: str, 
                     progress_callback: Optional[callable] = None) -> ProcessingResult:
        """Process a single video through the entire workflow.
        
        Args:
            video_url: YouTube video URL
            progress_callback: Optional callback for progress updates
            
        Returns:
            ProcessingResult with outcome details
        """
        logger.info(f"Starting to process video: {video_url}")
        result = ProcessingResult(success=False, video_url=video_url)
        
        try:
            # Step 1: Download video
            if progress_callback:
                progress_callback("Downloading video...")
                
            logger.info("Downloading video...")
            download_info = self.downloader.download(video_url)
            
            result.video_path = download_info['video_path']
            result.video_title = download_info['title']
            result.duration = download_info.get('duration', 0)
            
            logger.info(f"Video downloaded: {result.video_title}")
            
            # Step 2: Transcribe video
            if progress_callback:
                progress_callback("Transcribing video...")
                
            logger.info("Transcribing video...")
            transcription = self.transcriber.transcribe_video(
                result.video_path,
                language=self.config.whisper_language,
                include_timestamps=self.config.include_timestamps,
                cleanup_audio=True
            )
            
            result.transcription_text = transcription['text']
            result.language = transcription.get('language', 'unknown')
            
            logger.info(f"Transcription completed. Language: {result.language}")
            
            # Step 3: Post to Slack
            if self.slack_client:
                if progress_callback:
                    progress_callback("Posting to Slack...")
                    
                logger.info("Posting to Slack...")
                
                # Prepare data for Slack
                slack_data = {
                    'text': result.transcription_text,
                    'video_title': result.video_title,
                    'video_url': video_url,
                    'duration': result.duration,
                    'language': result.language
                }
                
                if self.config.include_timestamps and 'segments' in transcription:
                    slack_data['segments'] = transcription['segments']
                
                self.slack_client.send_transcription(
                    slack_data,
                    include_timestamps=self.config.include_timestamps
                )
                
                logger.info("Successfully posted to Slack")
            
            result.success = True
            
        except (DownloadError, TranscriptionError, SlackError) as e:
            logger.error(f"Workflow error: {e}")
            result.error = str(e)
            
            # Send error notification if configured
            if self.slack_client and self.config.send_errors_to_slack:
                try:
                    self.slack_client.send_error_notification(
                        f"Failed to process video: {e}",
                        context={
                            'video_url': video_url,
                            'video_title': result.video_title or 'Unknown',
                            'step': type(e).__name__.replace('Error', '')
                        }
                    )
                except Exception as slack_error:
                    logger.error(f"Failed to send error notification: {slack_error}")
                    
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            result.error = f"Unexpected error: {e}"
            
            # Send error notification if configured for unexpected errors too
            if self.slack_client and self.config.send_errors_to_slack:
                try:
                    self.slack_client.send_error_notification(
                        f"Failed to process video: {e}",
                        context={
                            'video_url': video_url,
                            'video_title': result.video_title or 'Unknown',
                            'step': 'Unexpected'
                        }
                    )
                except Exception as slack_error:
                    logger.error(f"Failed to send error notification: {slack_error}")
            
        finally:
            # Cleanup video if configured
            if result.video_path and not self.config.keep_video:
                try:
                    os.remove(result.video_path)
                    logger.info(f"Cleaned up video file: {result.video_path}")
                except Exception as e:
                    logger.warning(f"Failed to cleanup video: {e}")
                    
        if progress_callback:
            progress_callback("Processing complete")
            
        return result

    def process_playlist(self, playlist_url: str,
                        progress_callback: Optional[callable] = None) -> List[ProcessingResult]:
        """Process all videos in a playlist.
        
        Args:
            playlist_url: YouTube playlist URL
            progress_callback: Optional callback for progress updates
            
        Returns:
            List of ProcessingResult for each video
        """
        logger.info(f"Starting to process playlist: {playlist_url}")
        results = []
        
        try:
            # Download playlist information
            if progress_callback:
                progress_callback("Fetching playlist videos...")
                
            playlist_videos = self.downloader.download_playlist(playlist_url)
            total_videos = len(playlist_videos)
            
            logger.info(f"Found {total_videos} videos in playlist")
            
            # Process each video
            for i, video_info in enumerate(playlist_videos):
                if progress_callback:
                    progress_callback(f"Processing video {i+1}/{total_videos}: {video_info['title']}")
                
                # Create a pseudo URL for the result
                video_url = f"https://youtube.com/watch?v={video_info['video_id']}"
                result = ProcessingResult(
                    success=False,
                    video_url=video_url,
                    video_title=video_info['title'],
                    video_path=video_info['video_path'],
                    duration=video_info.get('duration', 0)
                )
                
                try:
                    # Transcribe the already downloaded video
                    transcription = self.transcriber.transcribe_video(
                        result.video_path,
                        language=self.config.whisper_language,
                        include_timestamps=self.config.include_timestamps,
                        cleanup_audio=True
                    )
                    
                    result.transcription_text = transcription['text']
                    result.language = transcription.get('language', 'unknown')
                    
                    # Post to Slack
                    if self.slack_client:
                        slack_data = {
                            'text': result.transcription_text,
                            'video_title': result.video_title,
                            'video_url': video_url,
                            'duration': result.duration,
                            'language': result.language
                        }
                        
                        if self.config.include_timestamps and 'segments' in transcription:
                            slack_data['segments'] = transcription['segments']
                        
                        self.slack_client.send_transcription(
                            slack_data,
                            include_timestamps=self.config.include_timestamps
                        )
                    
                    result.success = True
                    
                except Exception as e:
                    logger.error(f"Failed to process video {i+1}: {e}")
                    result.error = str(e)
                    
                finally:
                    # Cleanup video if configured
                    if result.video_path and not self.config.keep_video:
                        try:
                            os.remove(result.video_path)
                        except Exception as e:
                            logger.warning(f"Failed to cleanup video: {e}")
                    
                    results.append(result)
                    
        except Exception as e:
            logger.error(f"Failed to process playlist: {e}")
            # Return empty list or partial results
            
        if progress_callback:
            progress_callback("Playlist processing complete")
            
        return results

    def process_from_file(self, file_path: str) -> List[ProcessingResult]:
        """Process videos from a file containing URLs.
        
        Args:
            file_path: Path to file containing video URLs (one per line)
            
        Returns:
            List of ProcessingResult for each video
        """
        results = []
        
        try:
            with open(file_path, 'r') as f:
                urls = [line.strip() for line in f if line.strip()]
                
            logger.info(f"Found {len(urls)} URLs in file")
            
            for url in urls:
                # Check if it's a playlist or single video
                if 'playlist' in url:
                    playlist_results = self.process_playlist(url)
                    results.extend(playlist_results)
                else:
                    result = self.process_video(url)
                    results.append(result)
                    
        except Exception as e:
            logger.error(f"Failed to process file: {e}")
            
        return results