"""Main workflow orchestration module."""

import os
import logging
from dataclasses import dataclass
from typing import Dict, Optional, Any, List
import yaml

from .user_cookie_manager import UserCookieManager, UserSettingsManager


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
    allowed_local_users: Optional[List[str]] = None  # Slack User IDs allowed to use local Whisper
    
    # Slack settings
    slack_webhook: Optional[str] = None
    slack_channel: Optional[str] = None
    include_timestamps: bool = False
    send_errors_to_slack: bool = False
    
    # User-specific settings and cookie management
    settings_manager: Optional[UserSettingsManager] = None
    cookie_manager: Optional[UserCookieManager] = None  # Backward compatibility
    enable_user_cookies: bool = True
    
    def get_cookies_file_for_user(self, user_id: Optional[str] = None) -> Optional[str]:
        """Get cookies file path for specific user.
        
        Args:
            user_id: Slack user ID, if None uses default cookies
            
        Returns:
            Path to cookies file or None
        """
        # Use settings_manager if available, otherwise fall back to cookie_manager
        manager = self.settings_manager or self.cookie_manager
        if not user_id or not self.enable_user_cookies or not manager:
            return self.youtube_cookies_file
        
        # Try to get user-specific cookies first
        user_cookies_path = manager.get_cookies_file_path(user_id)
        if user_cookies_path:
            logger.info(f"Using user-specific cookies for {user_id}")
            return user_cookies_path
        
        # Fall back to default cookies if no user-specific cookies
        logger.info(f"No user-specific cookies for {user_id}, using default cookies")
        return self.youtube_cookies_file
    
    def cleanup_user_temp_files(self, user_id: str) -> None:
        """Clean up temporary files for user."""
        manager = self.settings_manager or self.cookie_manager
        if manager:
            manager.cleanup_temp_files(user_id)
    
    def is_local_whisper_allowed(self, user_id: str) -> bool:
        """Check if user is allowed to use local Whisper.
        
        Args:
            user_id: Slack User ID
            
        Returns:
            True if user is allowed to use local Whisper, False otherwise
        """
        # If no restriction list is configured, allow all users
        if not self.allowed_local_users:
            return True
        
        # If restriction list is configured, only allow listed users
        return user_id in self.allowed_local_users
    
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
        
        # Initialize settings manager (includes cookie management) from environment variable
        settings_manager = None
        cookie_manager = None  # Backward compatibility
        encryption_key = os.environ.get('COOKIE_ENCRYPTION_KEY')
        if encryption_key:
            try:
                # Allow DB path to be configured via environment variable
                db_path = os.environ.get('USER_COOKIES_DB_PATH', 'user_cookies.db')
                settings_manager = UserSettingsManager(
                    db_path=db_path,
                    encryption_key=encryption_key
                )
                cookie_manager = settings_manager  # For backward compatibility
            except Exception as e:
                logger.warning(f"Failed to initialize settings manager: {e}")
        
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
            allowed_local_users=whisper_config.get('allowed_local_users'),
            
            # Slack settings
            slack_webhook=slack_config.get('webhook_url'),
            slack_channel=slack_config.get('channel'),
            include_timestamps=slack_config.get('include_timestamps', False),
            send_errors_to_slack=slack_config.get('send_errors_to_slack', False),
            
            # User settings and cookie management
            settings_manager=settings_manager,
            cookie_manager=cookie_manager,
            enable_user_cookies=bool(encryption_key)  # Enable if encryption key is set
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


