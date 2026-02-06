"""Secure token management for temporary web UI access.

Supports multi-workspace environments with team_id context.
"""

import os
import time
import secrets
import sqlite3
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Default team_id for backward compatibility (single workspace mode)
DEFAULT_TEAM_ID = "_default_"


@dataclass
class WebAccessToken:
    """Web access token information."""
    token: str
    user_id: str
    team_id: str
    created_at: datetime
    expires_at: datetime
    used_at: Optional[datetime] = None
    is_valid: bool = True


class WebTokenManager:
    """Manages temporary access tokens for web UI.

    Supports multi-workspace environments with team_id context.
    """

    def __init__(self, db_path: str = "web_tokens.db", token_lifetime_hours: int = 1,
                 default_team_id: Optional[str] = None):
        """Initialize token manager.

        Args:
            db_path: SQLite database path for token storage.
            token_lifetime_hours: Token expiration time in hours.
            default_team_id: Default team_id to use when not specified.
        """
        self.db_path = db_path
        self.token_lifetime = timedelta(hours=token_lifetime_hours)
        self._default_team_id = default_team_id or DEFAULT_TEAM_ID
        self._init_database()

    def _resolve_team_id(self, team_id: Optional[str]) -> str:
        """Resolve team_id, using default if not specified."""
        return team_id if team_id else self._default_team_id

    def _init_database(self) -> None:
        """Initialize SQLite database for token storage."""
        with sqlite3.connect(self.db_path) as conn:
            # Check if we need to migrate from old schema
            self._migrate_schema_if_needed(conn)

            conn.execute('''
                CREATE TABLE IF NOT EXISTS web_tokens (
                    token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    team_id TEXT NOT NULL DEFAULT '_default_',
                    created_at TIMESTAMP NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    used_at TIMESTAMP NULL,
                    is_valid BOOLEAN DEFAULT 1
                )
            ''')

            # Create index for faster lookups (including team_id)
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_user_team_tokens ON web_tokens(team_id, user_id, expires_at)
            ''')

            # Create index for cleanup
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_expires_at ON web_tokens(expires_at)
            ''')

            conn.commit()

    def _migrate_schema_if_needed(self, conn: sqlite3.Connection) -> None:
        """Migrate from old schema (without team_id) to new schema if needed."""
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='web_tokens'")
        if not cursor.fetchone():
            # Table doesn't exist yet, no migration needed
            return

        # Check if team_id column exists
        cursor = conn.execute("PRAGMA table_info(web_tokens)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'team_id' in columns:
            # Already migrated
            return

        logger.info("Migrating web_tokens schema to support multi-workspace...")

        # Add team_id column with default value
        conn.execute('''
            ALTER TABLE web_tokens ADD COLUMN team_id TEXT NOT NULL DEFAULT '_default_'
        ''')

        # Drop old index if exists
        try:
            conn.execute('DROP INDEX IF EXISTS idx_user_tokens')
        except Exception:
            pass

        logger.info("Web tokens schema migration completed")
    
    def generate_token(self, user_id: str, single_use: bool = True,
                       team_id: Optional[str] = None) -> WebAccessToken:
        """Generate a new access token for user.

        Args:
            user_id: Slack user ID.
            single_use: If True, token is invalidated after first use.
            team_id: Slack team ID (optional, uses default if not specified).

        Returns:
            WebAccessToken instance.
        """
        team_id = self._resolve_team_id(team_id)

        # Cleanup old tokens for this user first
        self._cleanup_expired_tokens()
        self._invalidate_old_user_tokens(user_id, team_id)

        # Generate secure token
        token = secrets.token_urlsafe(32)
        now = datetime.now()
        expires_at = now + self.token_lifetime

        # Store in database
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO web_tokens (token, user_id, team_id, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (token, user_id, team_id, now, expires_at))
            conn.commit()

        access_token = WebAccessToken(
            token=token,
            user_id=user_id,
            team_id=team_id,
            created_at=now,
            expires_at=expires_at
        )

        logger.info(f"Generated web access token for user {user_id} in team {team_id}, expires at {expires_at}")
        return access_token

    def validate_token(self, token: str, mark_used: bool = True) -> Optional[WebAccessToken]:
        """Validate and optionally mark token as used.

        Args:
            token: Token to validate.
            mark_used: Whether to mark token as used.

        Returns:
            WebAccessToken if valid, None if invalid/expired.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute('''
                    SELECT token, user_id, team_id, created_at, expires_at, used_at, is_valid
                    FROM web_tokens
                    WHERE token = ? AND is_valid = 1
                ''', (token,))

                row = cursor.fetchone()
                if not row:
                    logger.warning("Token validation failed: token not found or invalid")
                    return None

                # Parse timestamps
                created_at = datetime.fromisoformat(row['created_at'])
                expires_at = datetime.fromisoformat(row['expires_at'])
                used_at = datetime.fromisoformat(row['used_at']) if row['used_at'] else None

                # Check expiration
                if datetime.now() > expires_at:
                    logger.warning("Token validation failed: token expired")
                    return None

                # Handle team_id (may be None for old tokens)
                team_id = row['team_id'] if 'team_id' in row.keys() else DEFAULT_TEAM_ID

                access_token = WebAccessToken(
                    token=row['token'],
                    user_id=row['user_id'],
                    team_id=team_id,
                    created_at=created_at,
                    expires_at=expires_at,
                    used_at=used_at,
                    is_valid=bool(row['is_valid'])
                )

                # Mark as used if requested
                if mark_used and not used_at:
                    self._mark_token_used(token)
                    access_token.used_at = datetime.now()

                logger.info(f"Token validated for user {access_token.user_id} in team {access_token.team_id}")
                return access_token

        except Exception as e:
            logger.error(f"Error validating token: {e}")
            return None
    
    def invalidate_token(self, token: str) -> bool:
        """Invalidate a specific token.
        
        Args:
            token: Token to invalidate
            
        Returns:
            True if token was invalidated, False if not found
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    UPDATE web_tokens SET is_valid = 0 WHERE token = ?
                ''', (token,))
                conn.commit()
                
                if cursor.rowcount > 0:
                    logger.info("Token invalidated successfully")
                    return True
                else:
                    logger.warning("Token invalidation failed: token not found")
                    return False
                    
        except Exception as e:
            logger.error(f"Error invalidating token: {e}")
            return False
    
    def _mark_token_used(self, token: str) -> None:
        """Mark token as used."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                UPDATE web_tokens SET used_at = ? WHERE token = ?
            ''', (datetime.now(), token))
            conn.commit()
    
    def _invalidate_old_user_tokens(self, user_id: str, team_id: Optional[str] = None) -> None:
        """Invalidate all existing tokens for a user in a specific team."""
        team_id = self._resolve_team_id(team_id)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                UPDATE web_tokens SET is_valid = 0
                WHERE user_id = ? AND team_id = ? AND is_valid = 1
            ''', (user_id, team_id))
            conn.commit()
    
    def _cleanup_expired_tokens(self) -> None:
        """Remove expired tokens from database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    DELETE FROM web_tokens 
                    WHERE expires_at < ? OR is_valid = 0
                ''', (datetime.now(),))
                conn.commit()
                
                if cursor.rowcount > 0:
                    logger.info(f"Cleaned up {cursor.rowcount} expired tokens")
                    
        except Exception as e:
            logger.error(f"Error cleaning up tokens: {e}")
    
    def get_user_active_tokens(self, user_id: str, team_id: Optional[str] = None) -> List[WebAccessToken]:
        """Get all active tokens for a user in a specific team.

        Args:
            user_id: Slack user ID.
            team_id: Slack team ID (optional, uses default if not specified).

        Returns:
            List of active WebAccessToken instances.
        """
        team_id = self._resolve_team_id(team_id)
        tokens = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute('''
                    SELECT token, user_id, team_id, created_at, expires_at, used_at, is_valid
                    FROM web_tokens
                    WHERE user_id = ? AND team_id = ? AND is_valid = 1 AND expires_at > ?
                    ORDER BY created_at DESC
                ''', (user_id, team_id, datetime.now()))

                for row in cursor.fetchall():
                    row_team_id = row['team_id'] if 'team_id' in row.keys() else DEFAULT_TEAM_ID
                    tokens.append(WebAccessToken(
                        token=row['token'],
                        user_id=row['user_id'],
                        team_id=row_team_id,
                        created_at=datetime.fromisoformat(row['created_at']),
                        expires_at=datetime.fromisoformat(row['expires_at']),
                        used_at=datetime.fromisoformat(row['used_at']) if row['used_at'] else None,
                        is_valid=bool(row['is_valid'])
                    ))

        except Exception as e:
            logger.error(f"Error getting user tokens: {e}")

        return tokens