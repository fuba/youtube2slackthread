"""Tests for WebTokenManager functionality."""

import pytest
import tempfile
import os
import time
from datetime import datetime, timedelta

from youtube2slack.web_token_manager import WebTokenManager, WebAccessToken


class TestWebTokenManager:
    """Test cases for WebTokenManager."""
    
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
    def token_manager(self, temp_db):
        """Create WebTokenManager instance for testing."""
        return WebTokenManager(
            db_path=temp_db,
            token_lifetime_hours=1
        )
    
    def test_generate_token(self, token_manager):
        """Test generating access token."""
        user_id = "test_user_123"
        
        token = token_manager.generate_token(user_id)
        
        assert isinstance(token, WebAccessToken)
        assert token.user_id == user_id
        assert len(token.token) > 20  # Should be a long secure token
        assert token.is_valid is True
        assert token.used_at is None
        assert token.expires_at > datetime.now()
        assert token.created_at <= datetime.now()
    
    def test_token_uniqueness(self, token_manager):
        """Test that generated tokens are unique."""
        user_id = "test_user_456"
        
        token1 = token_manager.generate_token(user_id)
        token2 = token_manager.generate_token(user_id)
        
        assert token1.token != token2.token
    
    def test_validate_token_success(self, token_manager):
        """Test successful token validation."""
        user_id = "test_user_789"
        
        # Generate token
        original_token = token_manager.generate_token(user_id)
        
        # Validate token
        validated_token = token_manager.validate_token(original_token.token)
        
        assert validated_token is not None
        assert validated_token.token == original_token.token
        assert validated_token.user_id == user_id
        assert validated_token.is_valid is True
        assert validated_token.used_at is not None  # Should be marked as used
    
    def test_validate_token_invalid(self, token_manager):
        """Test validation of invalid token."""
        invalid_token = "invalid_token_12345"
        
        result = token_manager.validate_token(invalid_token)
        assert result is None
    
    def test_validate_token_without_marking_used(self, token_manager):
        """Test validation without marking as used."""
        user_id = "test_user_no_mark"
        
        # Generate token
        original_token = token_manager.generate_token(user_id)
        
        # Validate without marking as used
        validated_token = token_manager.validate_token(original_token.token, mark_used=False)
        
        assert validated_token is not None
        assert validated_token.used_at is None
        
        # Validate again with marking as used
        validated_token2 = token_manager.validate_token(original_token.token, mark_used=True)
        assert validated_token2.used_at is not None
    
    def test_invalidate_token(self, token_manager):
        """Test invalidating a token."""
        user_id = "test_user_invalidate"
        
        # Generate token
        token = token_manager.generate_token(user_id)
        
        # Token should be valid initially
        assert token_manager.validate_token(token.token, mark_used=False) is not None
        
        # Invalidate token
        result = token_manager.invalidate_token(token.token)
        assert result is True
        
        # Token should now be invalid
        assert token_manager.validate_token(token.token, mark_used=False) is None
        
        # Try invalidating non-existent token
        result = token_manager.invalidate_token("non_existent_token")
        assert result is False
    
    def test_token_expiration(self, token_manager):
        """Test token expiration functionality."""
        # Create token manager with very short lifetime for testing
        short_lifetime_manager = WebTokenManager(
            db_path=token_manager.db_path,
            token_lifetime_hours=0.001  # ~3.6 seconds
        )
        
        user_id = "test_user_expire"
        
        # Generate token
        token = short_lifetime_manager.generate_token(user_id)
        
        # Should be valid immediately
        assert short_lifetime_manager.validate_token(token.token, mark_used=False) is not None
        
        # Wait for expiration
        time.sleep(4)
        
        # Should be expired now
        assert short_lifetime_manager.validate_token(token.token, mark_used=False) is None
    
    def test_old_user_tokens_invalidation(self, token_manager):
        """Test that old user tokens are invalidated when new one is generated."""
        user_id = "test_user_old_tokens"
        
        # Generate first token
        token1 = token_manager.generate_token(user_id)
        assert token_manager.validate_token(token1.token, mark_used=False) is not None
        
        # Generate second token (should invalidate first)
        token2 = token_manager.generate_token(user_id)
        
        # First token should be invalid now
        assert token_manager.validate_token(token1.token, mark_used=False) is None
        
        # Second token should be valid
        assert token_manager.validate_token(token2.token, mark_used=False) is not None
    
    def test_cleanup_expired_tokens(self, token_manager):
        """Test cleanup of expired tokens."""
        user_id = "test_user_cleanup"
        
        # Create a token that's already expired by manually setting database
        import sqlite3
        from datetime import datetime, timedelta
        
        expired_time = datetime.now() - timedelta(hours=2)
        token = "expired_token_12345"
        
        with sqlite3.connect(token_manager.db_path) as conn:
            conn.execute('''
                INSERT INTO web_tokens (token, user_id, created_at, expires_at, is_valid)
                VALUES (?, ?, ?, ?, 1)
            ''', (token, user_id, expired_time, expired_time))
            conn.commit()
        
        # Verify token exists in database
        with sqlite3.connect(token_manager.db_path) as conn:
            cursor = conn.execute('SELECT COUNT(*) FROM web_tokens WHERE token = ?', (token,))
            count_before = cursor.fetchone()[0]
            assert count_before == 1
        
        # Trigger cleanup by generating a new token
        token_manager.generate_token(user_id)
        
        # Expired token should be cleaned up
        with sqlite3.connect(token_manager.db_path) as conn:
            cursor = conn.execute('SELECT COUNT(*) FROM web_tokens WHERE token = ?', (token,))
            count_after = cursor.fetchone()[0]
            assert count_after == 0
    
    def test_get_user_active_tokens(self, token_manager):
        """Test getting active tokens for a user."""
        user_id = "test_user_active"
        
        # Initially no tokens
        active_tokens = token_manager.get_user_active_tokens(user_id)
        assert len(active_tokens) == 0
        
        # Generate a token
        token = token_manager.generate_token(user_id)
        
        # Should have one active token
        active_tokens = token_manager.get_user_active_tokens(user_id)
        assert len(active_tokens) == 1
        assert active_tokens[0].token == token.token
        assert active_tokens[0].user_id == user_id
        
        # Invalidate token
        token_manager.invalidate_token(token.token)
        
        # Should have no active tokens
        active_tokens = token_manager.get_user_active_tokens(user_id)
        assert len(active_tokens) == 0
    
    def test_token_security(self, token_manager):
        """Test token security properties."""
        user_id = "test_user_security"
        
        # Generate multiple tokens and check they're sufficiently different
        tokens = []
        for i in range(10):
            token = token_manager.generate_token(f"{user_id}_{i}")
            tokens.append(token.token)
        
        # All tokens should be unique
        assert len(set(tokens)) == len(tokens)
        
        # Tokens should be sufficiently long (URL-safe base64 with 32 bytes = ~43 chars)
        for token in tokens:
            assert len(token) >= 40
            # Should only contain URL-safe characters
            assert all(c.isalnum() or c in '-_' for c in token)
    
    def test_database_schema(self, token_manager):
        """Test database schema is created correctly."""
        import sqlite3
        
        with sqlite3.connect(token_manager.db_path) as conn:
            # Check table exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='web_tokens'"
            )
            assert cursor.fetchone() is not None
            
            # Check columns exist
            cursor = conn.execute("PRAGMA table_info(web_tokens)")
            columns = [column[1] for column in cursor.fetchall()]
            
            expected_columns = ['token', 'user_id', 'created_at', 'expires_at', 'used_at', 'is_valid']
            for col in expected_columns:
                assert col in columns
            
            # Check indexes exist
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
            index_names = [row[0] for row in cursor.fetchall()]
            
            assert 'idx_user_tokens' in index_names
            assert 'idx_expires_at' in index_names


class TestWebAccessToken:
    """Test cases for WebAccessToken dataclass."""
    
    def test_token_creation(self):
        """Test creating WebAccessToken."""
        now = datetime.now()
        expires = now + timedelta(hours=1)
        
        token = WebAccessToken(
            token="test_token_123",
            user_id="user_456",
            created_at=now,
            expires_at=expires,
            used_at=None,
            is_valid=True
        )
        
        assert token.token == "test_token_123"
        assert token.user_id == "user_456"
        assert token.created_at == now
        assert token.expires_at == expires
        assert token.used_at is None
        assert token.is_valid is True
    
    def test_token_defaults(self):
        """Test default values."""
        now = datetime.now()
        expires = now + timedelta(hours=1)
        
        token = WebAccessToken(
            token="test_token",
            user_id="test_user",
            created_at=now,
            expires_at=expires
        )
        
        assert token.used_at is None
        assert token.is_valid is True