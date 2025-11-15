"""Main workflow orchestration module."""

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Any
import yaml

from .user_cookie_manager import UserCookieManager


logger = logging.getLogger(__name__)


@dataclass
class WorkflowConfig:
    """Configuration for the YouTube2Slack workflow."""
    # Download settings
    download_dir: str = "./downloads"
    video_format: str = "best"
    keep_video: bool = True
    
    # YouTube settings
    youtube_cookies_file: Optional[str] = None
    
    # Whisper settings
    whisper_model: str = "base"
    whisper_device: Optional[str] = None
    whisper_language: Optional[str] = None
    whisper_download_root: Optional[str] = None
    
    # Slack settings
    slack_webhook: Optional[str] = None
    slack_channel: Optional[str] = None
    slack_app_token: Optional[str] = None
    include_timestamps: bool = False
    send_errors_to_slack: bool = False
    
    # User-specific cookie management
    cookie_manager: Optional[UserCookieManager] = None
    enable_user_cookies: bool = True
    
    def get_cookies_file_for_user(self, user_id: Optional[str] = None) -> Optional[str]:
        """Get cookies file path for specific user.
        
        Args:
            user_id: Slack user ID, if None uses default cookies
            
        Returns:
            Path to cookies file or None
        """
        if not user_id or not self.enable_user_cookies or not self.cookie_manager:
            return self.youtube_cookies_file
        
        # Try to get user-specific cookies first
        user_cookies_path = self.cookie_manager.get_cookies_file_path(user_id)
        if user_cookies_path:
            logger.info(f"Using user-specific cookies for {user_id}")
            return user_cookies_path
        
        # Fall back to default cookies if no user-specific cookies
        logger.info(f"No user-specific cookies for {user_id}, using default cookies")
        return self.youtube_cookies_file
    
    def cleanup_user_temp_files(self, user_id: str) -> None:
        """Clean up temporary files for user."""
        if self.cookie_manager:
            self.cookie_manager.cleanup_temp_files(user_id)
    
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
        cookie_config = config_dict.get('cookie_management', {})
        
        # Initialize cookie manager if configured
        cookie_manager = None
        if cookie_config.get('enabled', False):
            encryption_key = cookie_config.get('encryption_key')
            if encryption_key:
                try:
                    cookie_manager = UserCookieManager(
                        db_path=cookie_config.get('database_path', 'user_cookies.db'),
                        encryption_key=encryption_key
                    )
                except Exception as e:
                    logger.warning(f"Failed to initialize cookie manager: {e}")
        
        return cls(
            # YouTube settings
            download_dir=youtube_config.get('download_dir', './downloads'),
            video_format=youtube_config.get('format', 'best'),
            keep_video=youtube_config.get('keep_video', True),
            youtube_cookies_file=youtube_config.get('cookies_file'),
            
            # Whisper settings
            whisper_model=whisper_config.get('model', 'base'),
            whisper_device=whisper_config.get('device'),
            whisper_language=whisper_config.get('language'),
            whisper_download_root=whisper_config.get('download_root'),
            
            # Slack settings
            slack_webhook=slack_config.get('webhook_url'),
            slack_channel=slack_config.get('channel'),
            slack_app_token=slack_config.get('app_token'),
            include_timestamps=slack_config.get('include_timestamps', False),
            send_errors_to_slack=slack_config.get('send_errors_to_slack', False),
            
            # Cookie management settings
            cookie_manager=cookie_manager,
            enable_user_cookies=cookie_config.get('enabled', True)
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


