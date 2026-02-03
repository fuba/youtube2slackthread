"""Tests for UserSettingsManager and related functionality."""

import pytest
import tempfile
import os
from datetime import datetime

from youtube2slack.user_cookie_manager import (
    UserSettingsManager, UserSettings, WhisperService
)


class TestUserSettingsManager:
    """Test cases for UserSettingsManager."""
    
    @pytest.fixture
    def temp_db(self):
        """Create temporary database for testing."""
        with tempfile.NamedTemporaryFile(delete=False, suffix='.db') as f:
            temp_path = f.name
        
        yield temp_path
        
        # Cleanup
        if os.path.exists(temp_path):
            os.remove(temp_path)
    
    @pytest.fixture
    def settings_manager(self, temp_db):
        """Create UserSettingsManager instance for testing."""
        return UserSettingsManager(
            db_path=temp_db,
            encryption_key="test_encryption_key_12345"
        )
    
    def test_default_settings(self, settings_manager):
        """Test getting default settings for new user."""
        settings = settings_manager.get_settings("test_user")
        
        assert settings.whisper_service == WhisperService.LOCAL
        assert settings.openai_api_key is None
        assert settings.whisper_model == "base"
        assert settings.whisper_language is None
        assert settings.include_timestamps is True
    
    def test_store_and_retrieve_settings(self, settings_manager):
        """Test storing and retrieving user settings."""
        user_id = "test_user_123"
        
        # Create custom settings
        settings = UserSettings(
            whisper_service=WhisperService.OPENAI,
            openai_api_key="sk-test-key-12345",
            whisper_model="medium",
            whisper_language="ja",
            include_timestamps=False
        )
        
        # Store settings
        settings_manager.store_settings(user_id, settings)
        
        # Retrieve and verify
        retrieved = settings_manager.get_settings(user_id)
        assert retrieved.whisper_service == WhisperService.OPENAI
        assert retrieved.openai_api_key == "sk-test-key-12345"
        assert retrieved.whisper_model == "medium"
        assert retrieved.whisper_language == "ja"
        assert retrieved.include_timestamps is False
    
    def test_update_whisper_service(self, settings_manager):
        """Test updating whisper service."""
        user_id = "test_user_456"
        
        # Update to OpenAI
        settings_manager.update_whisper_service(user_id, WhisperService.OPENAI)
        
        settings = settings_manager.get_settings(user_id)
        assert settings.whisper_service == WhisperService.OPENAI
        
        # Update back to local
        settings_manager.update_whisper_service(user_id, WhisperService.LOCAL)
        
        settings = settings_manager.get_settings(user_id)
        assert settings.whisper_service == WhisperService.LOCAL
    
    def test_update_openai_api_key(self, settings_manager):
        """Test updating OpenAI API key."""
        user_id = "test_user_789"
        api_key = "sk-new-test-key-67890"
        
        # Update API key
        settings_manager.update_openai_api_key(user_id, api_key)
        
        settings = settings_manager.get_settings(user_id)
        assert settings.openai_api_key == api_key
        assert settings.whisper_service == WhisperService.OPENAI  # Auto-switch
    
    def test_update_whisper_model(self, settings_manager):
        """Test updating whisper model."""
        user_id = "test_user_model"
        
        settings_manager.update_whisper_model(user_id, "large")
        
        settings = settings_manager.get_settings(user_id)
        assert settings.whisper_model == "large"
    
    def test_has_openai_api_key(self, settings_manager):
        """Test checking for OpenAI API key."""
        user_id = "test_user_key"
        
        # Initially no key
        assert not settings_manager.has_openai_api_key(user_id)
        
        # Set key
        settings_manager.update_openai_api_key(user_id, "sk-test-key")
        assert settings_manager.has_openai_api_key(user_id)
        
        # Set empty key
        settings = settings_manager.get_settings(user_id)
        settings.openai_api_key = ""
        settings_manager.store_settings(user_id, settings)
        assert not settings_manager.has_openai_api_key(user_id)
    
    def test_delete_settings(self, settings_manager):
        """Test deleting user settings."""
        user_id = "test_user_delete"
        
        # Store some settings
        settings_manager.update_openai_api_key(user_id, "sk-test")
        assert settings_manager.has_openai_api_key(user_id)
        
        # Delete settings
        result = settings_manager.delete_settings(user_id)
        assert result is True
        
        # Verify settings are back to defaults
        settings = settings_manager.get_settings(user_id)
        assert not settings_manager.has_openai_api_key(user_id)
        assert settings.whisper_service == WhisperService.LOCAL
        
        # Try deleting non-existent settings
        result = settings_manager.delete_settings("non_existent_user")
        assert result is False
    
    def test_cookie_functionality_preserved(self, settings_manager):
        """Test that original cookie functionality is preserved."""
        user_id = "test_user_cookies"
        cookies_content = """# Netscape HTTP Cookie File
.youtube.com	TRUE	/	FALSE	1234567890	session_token	abc123
.google.com	TRUE	/	FALSE	1234567890	auth_token	def456"""
        
        # Store cookies (inherited functionality)
        settings_manager.store_cookies(user_id, cookies_content)
        
        # Check cookies exist
        assert settings_manager.has_cookies(user_id)
        
        # Get cookies data
        cookies_data = settings_manager.get_cookies(user_id)
        assert cookies_data is not None
        assert 'content' in cookies_data
        assert cookies_content in cookies_data['content']
        
        # Get cookies file path
        cookies_path = settings_manager.get_cookies_file_path(user_id)
        assert cookies_path is not None
        assert os.path.exists(cookies_path)
        
        # Cleanup
        settings_manager.cleanup_temp_files(user_id)
    
    def test_encryption_and_decryption(self, settings_manager):
        """Test that settings are properly encrypted."""
        user_id = "test_user_encryption"
        api_key = "sk-secret-key-should-be-encrypted"
        
        # Store sensitive data
        settings_manager.update_openai_api_key(user_id, api_key)
        
        # Check that raw database doesn't contain plaintext API key
        import sqlite3
        with sqlite3.connect(settings_manager.db_path) as conn:
            cursor = conn.execute(
                'SELECT encrypted_settings FROM user_settings WHERE user_id = ?',
                (user_id,)
            )
            row = cursor.fetchone()
            assert row is not None
            
            # The encrypted data should not contain the plaintext API key
            encrypted_blob = row[0]
            assert api_key not in str(encrypted_blob)
        
        # But retrieval should work correctly
        settings = settings_manager.get_settings(user_id)
        assert settings.openai_api_key == api_key
    
    def test_settings_enum_serialization(self, settings_manager):
        """Test that enum values are properly serialized and deserialized."""
        user_id = "test_user_enum"
        
        # Test LOCAL service
        settings_manager.update_whisper_service(user_id, WhisperService.LOCAL)
        settings = settings_manager.get_settings(user_id)
        assert settings.whisper_service == WhisperService.LOCAL
        assert isinstance(settings.whisper_service, WhisperService)
        
        # Test OPENAI service
        settings_manager.update_whisper_service(user_id, WhisperService.OPENAI)
        settings = settings_manager.get_settings(user_id)
        assert settings.whisper_service == WhisperService.OPENAI
        assert isinstance(settings.whisper_service, WhisperService)


class TestWhisperService:
    """Test cases for WhisperService enum."""
    
    def test_enum_values(self):
        """Test enum values."""
        assert WhisperService.LOCAL.value == "local"
        assert WhisperService.OPENAI.value == "openai"
    
    def test_enum_from_string(self):
        """Test creating enum from string."""
        local_service = WhisperService("local")
        assert local_service == WhisperService.LOCAL
        
        openai_service = WhisperService("openai")
        assert openai_service == WhisperService.OPENAI
    
    def test_enum_invalid_value(self):
        """Test invalid enum value."""
        with pytest.raises(ValueError):
            WhisperService("invalid")


class TestUserSettings:
    """Test cases for UserSettings dataclass."""
    
    def test_default_values(self):
        """Test default values."""
        settings = UserSettings()
        assert settings.whisper_service == WhisperService.LOCAL
        assert settings.openai_api_key is None
        assert settings.whisper_model == "base"
        assert settings.whisper_language is None
        assert settings.include_timestamps is True
    
    def test_custom_values(self):
        """Test custom values."""
        settings = UserSettings(
            whisper_service=WhisperService.OPENAI,
            openai_api_key="sk-test",
            whisper_model="large",
            whisper_language="en",
            include_timestamps=False
        )
        
        assert settings.whisper_service == WhisperService.OPENAI
        assert settings.openai_api_key == "sk-test"
        assert settings.whisper_model == "large"
        assert settings.whisper_language == "en"
        assert settings.include_timestamps is False