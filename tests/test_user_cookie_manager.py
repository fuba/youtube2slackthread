"""
Tests for UserCookieManager
"""
import os
import tempfile
import sqlite3
import pytest
from unittest.mock import patch

from src.youtube2slack.user_cookie_manager import UserCookieManager, CookieFileProcessor


class TestUserCookieManager:
    """Test UserCookieManager functionality"""
    
    def setup_method(self):
        """Setup test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_cookies.db")
        self.encryption_key = "test_encryption_key_12345"
        
    def teardown_method(self):
        """Cleanup test environment"""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_init_creates_database(self):
        """Test that database is created on initialization"""
        manager = UserCookieManager(self.db_path, self.encryption_key)
        
        assert os.path.exists(self.db_path)
        
        # Check table exists
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='user_cookies'"
            )
            assert cursor.fetchone() is not None
    
    def test_store_and_retrieve_cookies(self):
        """Test storing and retrieving cookies"""
        manager = UserCookieManager(self.db_path, self.encryption_key)
        
        test_cookies = """# Netscape HTTP Cookie File
.youtube.com	TRUE	/	FALSE	1234567890	test_cookie	test_value
"""
        
        user_id = "U123456789"
        
        # Store cookies
        manager.store_cookies(user_id, test_cookies)
        
        # Retrieve cookies
        retrieved = manager.get_cookies(user_id)
        
        assert retrieved is not None
        assert retrieved['content'] == test_cookies
        assert 'test_cookie' in retrieved['parsed']
        assert retrieved['parsed']['test_cookie']['value'] == 'test_value'
    
    def test_has_cookies(self):
        """Test checking if user has cookies"""
        manager = UserCookieManager(self.db_path, self.encryption_key)
        
        user_id = "U123456789"
        
        # User doesn't have cookies initially
        assert not manager.has_cookies(user_id)
        
        # Store cookies
        test_cookies = """# Netscape HTTP Cookie File
.youtube.com	TRUE	/	FALSE	1234567890	test_cookie	test_value
"""
        manager.store_cookies(user_id, test_cookies)
        
        # User should have cookies now
        assert manager.has_cookies(user_id)
    
    def test_get_cookies_file_path(self):
        """Test getting temporary cookies file path"""
        manager = UserCookieManager(self.db_path, self.encryption_key)
        
        test_cookies = """# Netscape HTTP Cookie File
.youtube.com	TRUE	/	FALSE	1234567890	test_cookie	test_value
"""
        user_id = "U123456789"
        
        # Store cookies first
        manager.store_cookies(user_id, test_cookies)
        
        # Get file path
        file_path = manager.get_cookies_file_path(user_id)
        
        assert file_path is not None
        assert os.path.exists(file_path)
        
        # Verify file content
        with open(file_path, 'r') as f:
            content = f.read()
        assert content == test_cookies
        
        # Cleanup
        manager.cleanup_temp_files(user_id)
        assert not os.path.exists(file_path)
    
    def test_delete_cookies(self):
        """Test deleting user cookies"""
        manager = UserCookieManager(self.db_path, self.encryption_key)
        
        test_cookies = """# Netscape HTTP Cookie File
.youtube.com	TRUE	/	FALSE	1234567890	test_cookie	test_value
"""
        user_id = "U123456789"
        
        # Store cookies
        manager.store_cookies(user_id, test_cookies)
        assert manager.has_cookies(user_id)
        
        # Delete cookies
        result = manager.delete_cookies(user_id)
        assert result is True
        assert not manager.has_cookies(user_id)
    
    def test_encryption_integrity(self):
        """Test that cookies are properly encrypted in database"""
        manager = UserCookieManager(self.db_path, self.encryption_key)
        
        test_cookies = """# Netscape HTTP Cookie File
.youtube.com	TRUE	/	FALSE	1234567890	secret_cookie	secret_value
"""
        user_id = "U123456789"
        
        # Store cookies
        manager.store_cookies(user_id, test_cookies)
        
        # Check that raw database doesn't contain plaintext
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                'SELECT encrypted_cookies FROM user_cookies WHERE user_id = ?',
                (user_id,)
            )
            row = cursor.fetchone()
            assert row is not None
            
            # Encrypted data should not contain plaintext
            encrypted_data = row[0]
            assert b'secret_value' not in encrypted_data
            assert b'secret_cookie' not in encrypted_data


class TestCookieFileProcessor:
    """Test CookieFileProcessor functionality"""
    
    def test_validate_valid_cookies_file(self):
        """Test validating a valid cookies file"""
        valid_cookies = """# Netscape HTTP Cookie File
# This file contains the HTTP cookies for www.youtube.com

.youtube.com	TRUE	/	FALSE	1234567890	test_cookie	test_value
"""
        assert CookieFileProcessor.validate_cookies_file(valid_cookies)
    
    def test_validate_invalid_cookies_file(self):
        """Test validating an invalid cookies file"""
        invalid_cookies = "This is not a cookies file"
        assert not CookieFileProcessor.validate_cookies_file(invalid_cookies)
    
    def test_extract_youtube_cookies(self):
        """Test extracting YouTube-specific cookies"""
        mixed_cookies = """# Netscape HTTP Cookie File
.youtube.com	TRUE	/	FALSE	1234567890	yt_cookie	yt_value
.google.com	TRUE	/	FALSE	1234567890	google_cookie	google_value
.facebook.com	TRUE	/	FALSE	1234567890	fb_cookie	fb_value
.googleapis.com	TRUE	/	FALSE	1234567890	api_cookie	api_value
"""
        
        youtube_only = CookieFileProcessor.extract_youtube_cookies(mixed_cookies)
        
        # Should contain YouTube and Google related cookies
        assert 'yt_cookie' in youtube_only
        assert 'google_cookie' in youtube_only
        assert 'api_cookie' in youtube_only
        
        # Should not contain Facebook cookies
        assert 'fb_cookie' not in youtube_only
    
    def test_error_handling_missing_encryption_key(self):
        """Test error handling when encryption key is missing"""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            db_path = f.name
        
        try:
            with pytest.raises(ValueError, match="Encryption key is required"):
                UserCookieManager(db_path, None)
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)