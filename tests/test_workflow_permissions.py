"""Tests for workflow permission system and configuration."""

import pytest
import tempfile
import os
from unittest.mock import Mock, patch

from youtube2slack.workflow import WorkflowConfig
from youtube2slack.user_cookie_manager import UserSettingsManager


class TestWorkflowPermissions:
    """Test cases for workflow permission system."""
    
    def test_is_local_whisper_allowed_no_restriction(self):
        """Test local Whisper allowed when no restrictions configured."""
        config = WorkflowConfig(allowed_local_users=None)
        
        # Any user should be allowed
        assert config.is_local_whisper_allowed("user123") is True
        assert config.is_local_whisper_allowed("another_user") is True
        assert config.is_local_whisper_allowed("") is True
    
    def test_is_local_whisper_allowed_empty_list(self):
        """Test local Whisper allowed when empty list configured."""
        config = WorkflowConfig(allowed_local_users=[])
        
        # Any user should be allowed when list is empty
        assert config.is_local_whisper_allowed("user123") is True
        assert config.is_local_whisper_allowed("another_user") is True
    
    def test_is_local_whisper_allowed_with_restrictions(self):
        """Test local Whisper restricted to specific users."""
        allowed_users = ["U1234567890", "U0987654321"]
        config = WorkflowConfig(allowed_local_users=allowed_users)
        
        # Allowed users should be permitted
        assert config.is_local_whisper_allowed("U1234567890") is True
        assert config.is_local_whisper_allowed("U0987654321") is True
        
        # Non-allowed users should be denied
        assert config.is_local_whisper_allowed("U1111111111") is False
        assert config.is_local_whisper_allowed("unauthorized_user") is False
        assert config.is_local_whisper_allowed("") is False
    
    def test_from_dict_loads_allowed_users(self):
        """Test that from_dict properly loads allowed_local_users."""
        config_dict = {
            'whisper': {
                'model': 'medium',
                'device': 'cuda',
                'allowed_local_users': ['U1234567890', 'U0987654321']
            },
            'youtube': {},
            'slack': {}
        }
        
        with patch.dict(os.environ, {'COOKIE_ENCRYPTION_KEY': 'test_key'}):
            config = WorkflowConfig.from_dict(config_dict)
        
        assert config.allowed_local_users == ['U1234567890', 'U0987654321']
        assert config.whisper_model == 'medium'
        assert config.whisper_device == 'cuda'
        
        # Test permission checking
        assert config.is_local_whisper_allowed('U1234567890') is True
        assert config.is_local_whisper_allowed('U0987654321') is True
        assert config.is_local_whisper_allowed('unauthorized') is False
    
    def test_from_dict_no_allowed_users_config(self):
        """Test configuration without allowed_local_users field."""
        config_dict = {
            'whisper': {
                'model': 'base',
                'device': 'cpu'
                # No allowed_local_users field
            },
            'youtube': {},
            'slack': {}
        }
        
        with patch.dict(os.environ, {'COOKIE_ENCRYPTION_KEY': 'test_key'}):
            config = WorkflowConfig.from_dict(config_dict)
        
        assert config.allowed_local_users is None
        
        # Should allow all users
        assert config.is_local_whisper_allowed('any_user') is True
        assert config.is_local_whisper_allowed('another_user') is True
    
    def test_settings_manager_integration(self):
        """Test integration with UserSettingsManager."""
        with tempfile.NamedTemporaryFile(delete=False, suffix='.db') as temp_file:
            temp_db_path = temp_file.name
        
        try:
            with patch.dict(os.environ, {'COOKIE_ENCRYPTION_KEY': 'test_key_12345'}):
                config_dict = {
                    'whisper': {'model': 'base'},
                    'youtube': {},
                    'slack': {}
                }
                
                config = WorkflowConfig.from_dict(config_dict)
                
                # Should have settings manager initialized
                assert config.settings_manager is not None
                assert isinstance(config.settings_manager, UserSettingsManager)
                
                # Backward compatibility - cookie_manager should point to settings_manager
                assert config.cookie_manager is config.settings_manager
                
        finally:
            # Cleanup
            if os.path.exists(temp_db_path):
                os.remove(temp_db_path)
    
    def test_get_cookies_file_with_settings_manager(self):
        """Test get_cookies_file_for_user works with settings manager."""
        mock_settings_manager = Mock()
        mock_settings_manager.get_cookies_file_path.return_value = "/tmp/user_cookies.txt"
        
        config = WorkflowConfig(
            settings_manager=mock_settings_manager,
            enable_user_cookies=True,
            youtube_cookies_file="/default/cookies.txt"
        )
        
        # Should use settings manager
        result = config.get_cookies_file_for_user("test_user")
        assert result == "/tmp/user_cookies.txt"
        mock_settings_manager.get_cookies_file_path.assert_called_once_with("test_user")
    
    def test_get_cookies_file_fallback_to_cookie_manager(self):
        """Test fallback to cookie_manager when settings_manager is None."""
        mock_cookie_manager = Mock()
        mock_cookie_manager.get_cookies_file_path.return_value = "/tmp/legacy_cookies.txt"
        
        config = WorkflowConfig(
            settings_manager=None,
            cookie_manager=mock_cookie_manager,
            enable_user_cookies=True,
            youtube_cookies_file="/default/cookies.txt"
        )
        
        # Should fall back to cookie manager
        result = config.get_cookies_file_for_user("test_user")
        assert result == "/tmp/legacy_cookies.txt"
        mock_cookie_manager.get_cookies_file_path.assert_called_once_with("test_user")
    
    def test_get_cookies_file_no_user_cookies(self):
        """Test default cookies when user cookies disabled."""
        config = WorkflowConfig(
            settings_manager=Mock(),
            enable_user_cookies=False,
            youtube_cookies_file="/default/cookies.txt"
        )
        
        # Should return default cookies
        result = config.get_cookies_file_for_user("test_user")
        assert result == "/default/cookies.txt"
    
    def test_cleanup_user_temp_files_with_settings_manager(self):
        """Test cleanup works with settings manager."""
        mock_settings_manager = Mock()
        
        config = WorkflowConfig(settings_manager=mock_settings_manager)
        config.cleanup_user_temp_files("test_user")
        
        mock_settings_manager.cleanup_temp_files.assert_called_once_with("test_user")
    
    def test_cleanup_user_temp_files_fallback(self):
        """Test cleanup fallback to cookie manager."""
        mock_cookie_manager = Mock()
        
        config = WorkflowConfig(
            settings_manager=None,
            cookie_manager=mock_cookie_manager
        )
        config.cleanup_user_temp_files("test_user")
        
        mock_cookie_manager.cleanup_temp_files.assert_called_once_with("test_user")


class TestWorkflowConfigYAMLIntegration:
    """Test YAML configuration loading with new features."""
    
    def test_yaml_with_allowed_users(self):
        """Test loading YAML config with allowed users."""
        yaml_content = """
whisper:
  model: "medium"
  device: "cuda"
  allowed_local_users:
    - "U1234567890"
    - "U0987654321"

youtube:
  download_dir: "./downloads"

slack:
  include_timestamps: true
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as temp_file:
            temp_file.write(yaml_content)
            temp_file.flush()
            
            try:
                with patch.dict(os.environ, {'COOKIE_ENCRYPTION_KEY': 'test_key'}):
                    config = WorkflowConfig.from_yaml(temp_file.name)
                
                # Verify allowed users loaded correctly
                assert config.allowed_local_users == ["U1234567890", "U0987654321"]
                assert config.whisper_model == "medium"
                assert config.whisper_device == "cuda"
                
                # Test permissions
                assert config.is_local_whisper_allowed("U1234567890") is True
                assert config.is_local_whisper_allowed("unauthorized") is False
                
            finally:
                os.unlink(temp_file.name)
    
    def test_yaml_without_allowed_users(self):
        """Test loading YAML config without allowed users restriction."""
        yaml_content = """
whisper:
  model: "base"
  device: "cpu"

youtube:
  download_dir: "./downloads"

slack:
  include_timestamps: false
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as temp_file:
            temp_file.write(yaml_content)
            temp_file.flush()
            
            try:
                with patch.dict(os.environ, {'COOKIE_ENCRYPTION_KEY': 'test_key'}):
                    config = WorkflowConfig.from_yaml(temp_file.name)
                
                # Should allow all users
                assert config.allowed_local_users is None
                assert config.is_local_whisper_allowed("any_user") is True
                
            finally:
                os.unlink(temp_file.name)


class TestBackwardCompatibility:
    """Test backward compatibility with existing functionality."""
    
    def test_cookie_manager_still_works(self):
        """Test that existing cookie_manager functionality is preserved."""
        mock_cookie_manager = Mock()
        
        config = WorkflowConfig(cookie_manager=mock_cookie_manager)
        
        # Should still work for backward compatibility
        config.get_cookies_file_for_user("test_user")
        mock_cookie_manager.get_cookies_file_path.assert_called_once_with("test_user")
        
        config.cleanup_user_temp_files("test_user")
        mock_cookie_manager.cleanup_temp_files.assert_called_once_with("test_user")
    
    def test_settings_manager_takes_precedence(self):
        """Test that settings_manager takes precedence over cookie_manager."""
        mock_settings_manager = Mock()
        mock_cookie_manager = Mock()
        
        mock_settings_manager.get_cookies_file_path.return_value = "/settings/path"
        mock_cookie_manager.get_cookies_file_path.return_value = "/cookie/path"
        
        config = WorkflowConfig(
            settings_manager=mock_settings_manager,
            cookie_manager=mock_cookie_manager,
            enable_user_cookies=True
        )
        
        # Should use settings_manager, not cookie_manager
        result = config.get_cookies_file_for_user("test_user")
        assert result == "/settings/path"
        
        mock_settings_manager.get_cookies_file_path.assert_called_once()
        mock_cookie_manager.get_cookies_file_path.assert_not_called()