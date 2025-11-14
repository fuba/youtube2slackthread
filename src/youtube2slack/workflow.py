"""Main workflow orchestration module."""

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Any
import yaml


logger = logging.getLogger(__name__)


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


