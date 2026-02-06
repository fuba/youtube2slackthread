"""
User-specific settings management with encryption (cookies, OpenAI API keys, Whisper preferences)
Supports multi-workspace environments with team_id isolation.
"""
import os
import sqlite3
import base64
import json
from typing import Optional, Dict, Any, Literal, List, Tuple
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import logging
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)

# Default team_id for backward compatibility (single workspace mode)
DEFAULT_TEAM_ID = "_default_"


class WhisperService(Enum):
    """Available Whisper transcription services"""
    LOCAL = "local"
    OPENAI = "openai"


@dataclass
class UserSettings:
    """User configuration settings"""
    whisper_service: WhisperService = WhisperService.LOCAL
    openai_api_key: Optional[str] = None
    whisper_model: str = "base"  # For local Whisper
    whisper_language: Optional[str] = None
    include_timestamps: bool = True


class UserSettingsManager:
    """Manages encrypted user-specific settings including cookies, API keys, and preferences in SQLite database.

    Supports multi-workspace environments with team_id isolation.
    """

    def __init__(self, db_path: str = "user_cookies.db", encryption_key: Optional[str] = None,
                 default_team_id: Optional[str] = None):
        """Initialize the settings manager.

        Args:
            db_path: Path to the SQLite database file.
            encryption_key: Encryption key for storing sensitive data.
            default_team_id: Default team_id to use when not specified (for backward compatibility).
        """
        self.db_path = db_path
        self._encryption_key = encryption_key or os.environ.get("COOKIE_ENCRYPTION_KEY")
        if not self._encryption_key:
            raise ValueError("Encryption key is required. Set COOKIE_ENCRYPTION_KEY environment variable.")

        self._default_team_id = default_team_id or DEFAULT_TEAM_ID
        self._fernet = self._create_fernet()
        self._init_database()
    
    def _create_fernet(self) -> Fernet:
        """Create Fernet encryption instance from password"""
        password = self._encryption_key.encode()
        salt = b'youtube2slack_salt'  # In production, use random salt per user
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password))
        return Fernet(key)
    
    def _init_database(self) -> None:
        """Initialize SQLite database with user tables and workspaces table."""
        with sqlite3.connect(self.db_path) as conn:
            # Check if we need to migrate from old schema (without team_id)
            self._migrate_schema_if_needed(conn)

            # Create workspaces table for multi-workspace support
            conn.execute('''
                CREATE TABLE IF NOT EXISTS workspaces (
                    team_id TEXT PRIMARY KEY,
                    team_name TEXT NOT NULL,
                    encrypted_bot_token BLOB NOT NULL,
                    encrypted_app_token BLOB,
                    encrypted_signing_secret BLOB NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Create cookies table with team_id (composite primary key)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS user_cookies (
                    team_id TEXT NOT NULL DEFAULT '_default_',
                    user_id TEXT NOT NULL,
                    encrypted_cookies BLOB NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (team_id, user_id)
                )
            ''')

            # Create settings table with team_id (composite primary key)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS user_settings (
                    team_id TEXT NOT NULL DEFAULT '_default_',
                    user_id TEXT NOT NULL,
                    encrypted_settings BLOB NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (team_id, user_id)
                )
            ''')

            # Create indexes for faster lookups
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_user_cookies_team ON user_cookies(team_id)
            ''')
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_user_settings_team ON user_settings(team_id)
            ''')

            # Create triggers for workspaces table
            conn.execute('''
                CREATE TRIGGER IF NOT EXISTS update_workspaces_timestamp
                AFTER UPDATE ON workspaces
                BEGIN
                    UPDATE workspaces SET updated_at = CURRENT_TIMESTAMP
                    WHERE team_id = NEW.team_id;
                END
            ''')

            # Create triggers for cookies table (updated for composite key)
            conn.execute('''
                CREATE TRIGGER IF NOT EXISTS update_cookies_timestamp
                AFTER UPDATE ON user_cookies
                BEGIN
                    UPDATE user_cookies SET updated_at = CURRENT_TIMESTAMP
                    WHERE team_id = NEW.team_id AND user_id = NEW.user_id;
                END
            ''')

            # Create triggers for settings table (updated for composite key)
            conn.execute('''
                CREATE TRIGGER IF NOT EXISTS update_settings_timestamp
                AFTER UPDATE ON user_settings
                BEGIN
                    UPDATE user_settings SET updated_at = CURRENT_TIMESTAMP
                    WHERE team_id = NEW.team_id AND user_id = NEW.user_id;
                END
            ''')

            conn.commit()

    def _migrate_schema_if_needed(self, conn: sqlite3.Connection) -> None:
        """Migrate from old schema (without team_id) to new schema if needed."""
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_cookies'")
        if not cursor.fetchone():
            # Table doesn't exist yet, no migration needed
            return

        # Check if team_id column exists in user_cookies
        cursor = conn.execute("PRAGMA table_info(user_cookies)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'team_id' in columns:
            # Already migrated
            return

        logger.info("Migrating database schema to support multi-workspace...")

        # Migrate user_cookies table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_cookies_new (
                team_id TEXT NOT NULL DEFAULT '_default_',
                user_id TEXT NOT NULL,
                encrypted_cookies BLOB NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (team_id, user_id)
            )
        ''')
        conn.execute('''
            INSERT INTO user_cookies_new (team_id, user_id, encrypted_cookies, created_at, updated_at)
            SELECT '_default_', user_id, encrypted_cookies, created_at, updated_at
            FROM user_cookies
        ''')
        conn.execute('DROP TABLE user_cookies')
        conn.execute('ALTER TABLE user_cookies_new RENAME TO user_cookies')

        # Drop old trigger (may fail if doesn't exist, that's ok)
        try:
            conn.execute('DROP TRIGGER IF EXISTS update_cookies_timestamp')
        except Exception:
            pass

        # Check if user_settings table exists
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_settings'")
        if cursor.fetchone():
            # Migrate user_settings table
            cursor = conn.execute("PRAGMA table_info(user_settings)")
            settings_columns = [row[1] for row in cursor.fetchall()]

            if 'team_id' not in settings_columns:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS user_settings_new (
                        team_id TEXT NOT NULL DEFAULT '_default_',
                        user_id TEXT NOT NULL,
                        encrypted_settings BLOB NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (team_id, user_id)
                    )
                ''')
                conn.execute('''
                    INSERT INTO user_settings_new (team_id, user_id, encrypted_settings, created_at, updated_at)
                    SELECT '_default_', user_id, encrypted_settings, created_at, updated_at
                    FROM user_settings
                ''')
                conn.execute('DROP TABLE user_settings')
                conn.execute('ALTER TABLE user_settings_new RENAME TO user_settings')

                # Drop old trigger
                try:
                    conn.execute('DROP TRIGGER IF EXISTS update_settings_timestamp')
                except Exception:
                    pass

        logger.info("Database schema migration completed")

    # === Cookie Management Methods ===

    def _resolve_team_id(self, team_id: Optional[str]) -> str:
        """Resolve team_id, using default if not specified."""
        return team_id if team_id else self._default_team_id

    def store_cookies(self, user_id: str, cookies_content: str, team_id: Optional[str] = None) -> None:
        """Store encrypted cookies for a user.

        Args:
            user_id: Slack user ID.
            cookies_content: Cookies file content in Netscape format.
            team_id: Slack team ID (optional, uses default if not specified).
        """
        team_id = self._resolve_team_id(team_id)
        try:
            # Parse and validate cookies content
            parsed_cookies = self._parse_cookies_content(cookies_content)

            # Encrypt the cookies data
            cookies_data = {
                'content': cookies_content,
                'parsed': parsed_cookies,
                'youtube_domains': self._get_youtube_domains(parsed_cookies)
            }

            encrypted_data = self._fernet.encrypt(json.dumps(cookies_data).encode())

            # Store in database with team_id
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO user_cookies (team_id, user_id, encrypted_cookies)
                    VALUES (?, ?, ?)
                ''', (team_id, user_id, encrypted_data))
                conn.commit()

            logger.info(f"Successfully stored cookies for user {user_id} in team {team_id}")
        except Exception as e:
            logger.error(f"Failed to store cookies for user {user_id} in team {team_id}: {e}")
            raise

    def get_cookies(self, user_id: str, team_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get decrypted cookies data for a user.

        Args:
            user_id: Slack user ID.
            team_id: Slack team ID (optional, uses default if not specified).

        Returns:
            Decrypted cookies data or None if not found.
        """
        team_id = self._resolve_team_id(team_id)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'SELECT encrypted_cookies FROM user_cookies WHERE team_id = ? AND user_id = ?',
                    (team_id, user_id)
                )
                row = cursor.fetchone()

                if not row:
                    return None

                # Decrypt the data
                decrypted_data = self._fernet.decrypt(row[0])
                return json.loads(decrypted_data.decode())

        except Exception as e:
            logger.error(f"Failed to retrieve cookies for user {user_id} in team {team_id}: {e}")
            return None

    def get_cookies_file_path(self, user_id: str, team_id: Optional[str] = None) -> Optional[str]:
        """Get temporary cookies file path for yt-dlp.

        Args:
            user_id: Slack user ID.
            team_id: Slack team ID (optional, uses default if not specified).

        Returns:
            Path to temporary cookies file or None if no cookies stored.
        """
        team_id = self._resolve_team_id(team_id)
        cookies_data = self.get_cookies(user_id, team_id)
        if not cookies_data:
            return None

        # Create temporary cookies file (include team_id in filename for isolation)
        temp_dir = "/tmp/youtube2slack_cookies"
        os.makedirs(temp_dir, exist_ok=True)

        # Sanitize team_id for filename
        safe_team_id = team_id.replace('/', '_').replace('\\', '_')
        cookies_file = os.path.join(temp_dir, f"cookies_{safe_team_id}_{user_id}.txt")

        try:
            with open(cookies_file, 'w') as f:
                f.write(cookies_data['content'])

            logger.info(f"Created temporary cookies file for user {user_id} in team {team_id}")
            return cookies_file

        except Exception as e:
            logger.error(f"Failed to create cookies file for user {user_id} in team {team_id}: {e}")
            return None

    def delete_cookies(self, user_id: str, team_id: Optional[str] = None) -> bool:
        """Delete cookies for a user.

        Args:
            user_id: Slack user ID.
            team_id: Slack team ID (optional, uses default if not specified).

        Returns:
            True if cookies were deleted, False otherwise.
        """
        team_id = self._resolve_team_id(team_id)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'DELETE FROM user_cookies WHERE team_id = ? AND user_id = ?',
                    (team_id, user_id)
                )
                conn.commit()

                if cursor.rowcount > 0:
                    logger.info(f"Deleted cookies for user {user_id} in team {team_id}")
                    return True
                else:
                    logger.warning(f"No cookies found for user {user_id} in team {team_id}")
                    return False

        except Exception as e:
            logger.error(f"Failed to delete cookies for user {user_id} in team {team_id}: {e}")
            return False

    def has_cookies(self, user_id: str, team_id: Optional[str] = None) -> bool:
        """Check if user has cookies stored.

        Args:
            user_id: Slack user ID.
            team_id: Slack team ID (optional, uses default if not specified).

        Returns:
            True if cookies exist for the user.
        """
        team_id = self._resolve_team_id(team_id)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'SELECT 1 FROM user_cookies WHERE team_id = ? AND user_id = ? LIMIT 1',
                    (team_id, user_id)
                )
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Failed to check cookies for user {user_id} in team {team_id}: {e}")
            return False

    def cleanup_temp_files(self, user_id: str, team_id: Optional[str] = None) -> None:
        """Clean up temporary cookies files for user.

        Args:
            user_id: Slack user ID.
            team_id: Slack team ID (optional, uses default if not specified).
        """
        team_id = self._resolve_team_id(team_id)
        temp_dir = "/tmp/youtube2slack_cookies"
        safe_team_id = team_id.replace('/', '_').replace('\\', '_')
        cookies_file = os.path.join(temp_dir, f"cookies_{safe_team_id}_{user_id}.txt")

        try:
            if os.path.exists(cookies_file):
                os.remove(cookies_file)
                logger.info(f"Cleaned up temporary cookies file for user {user_id} in team {team_id}")
        except Exception as e:
            logger.error(f"Failed to cleanup cookies file for user {user_id} in team {team_id}: {e}")

    # === Settings Management Methods ===

    def store_settings(self, user_id: str, settings: UserSettings, team_id: Optional[str] = None) -> None:
        """Store encrypted user settings.

        Args:
            user_id: Slack user ID.
            settings: UserSettings instance to store.
            team_id: Slack team ID (optional, uses default if not specified).
        """
        team_id = self._resolve_team_id(team_id)
        try:
            settings_data = asdict(settings)
            # Convert enum to string for JSON serialization
            if isinstance(settings_data['whisper_service'], WhisperService):
                settings_data['whisper_service'] = settings_data['whisper_service'].value

            encrypted_data = self._fernet.encrypt(json.dumps(settings_data).encode())

            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO user_settings (team_id, user_id, encrypted_settings)
                    VALUES (?, ?, ?)
                ''', (team_id, user_id, encrypted_data))
                conn.commit()

            logger.info(f"Stored settings for user {user_id} in team {team_id}")
        except Exception as e:
            logger.error(f"Failed to store settings for user {user_id} in team {team_id}: {e}")
            raise

    def get_settings(self, user_id: str, team_id: Optional[str] = None) -> UserSettings:
        """Retrieve and decrypt user settings, return defaults if not found.

        Args:
            user_id: Slack user ID.
            team_id: Slack team ID (optional, uses default if not specified).

        Returns:
            UserSettings instance (defaults if not found).
        """
        team_id = self._resolve_team_id(team_id)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'SELECT encrypted_settings FROM user_settings WHERE team_id = ? AND user_id = ?',
                    (team_id, user_id)
                )
                row = cursor.fetchone()

                if not row:
                    # Return default settings
                    logger.info(f"No settings found for user {user_id} in team {team_id}, returning defaults")
                    return UserSettings()

                # Decrypt and return settings
                decrypted_data = self._fernet.decrypt(row[0])
                settings_data = json.loads(decrypted_data.decode())

                # Convert string back to enum
                if 'whisper_service' in settings_data:
                    settings_data['whisper_service'] = WhisperService(settings_data['whisper_service'])

                logger.info(f"Retrieved settings for user {user_id} in team {team_id}")
                return UserSettings(**settings_data)

        except Exception as e:
            logger.error(f"Failed to retrieve settings for user {user_id} in team {team_id}: {e}")
            return UserSettings()  # Return defaults on error

    def update_whisper_service(self, user_id: str, service: WhisperService, team_id: Optional[str] = None) -> None:
        """Update user's preferred Whisper service.

        Args:
            user_id: Slack user ID.
            service: WhisperService to use.
            team_id: Slack team ID (optional, uses default if not specified).
        """
        settings = self.get_settings(user_id, team_id)
        settings.whisper_service = service
        self.store_settings(user_id, settings, team_id)

    def update_openai_api_key(self, user_id: str, api_key: str, team_id: Optional[str] = None) -> None:
        """Update user's OpenAI API key.

        Args:
            user_id: Slack user ID.
            api_key: OpenAI API key.
            team_id: Slack team ID (optional, uses default if not specified).
        """
        settings = self.get_settings(user_id, team_id)
        settings.openai_api_key = api_key
        # Auto-switch to OpenAI service when API key is set
        settings.whisper_service = WhisperService.OPENAI
        self.store_settings(user_id, settings, team_id)

    def update_whisper_model(self, user_id: str, model: str, team_id: Optional[str] = None) -> None:
        """Update user's preferred Whisper model (for local Whisper).

        Args:
            user_id: Slack user ID.
            model: Whisper model name.
            team_id: Slack team ID (optional, uses default if not specified).
        """
        settings = self.get_settings(user_id, team_id)
        settings.whisper_model = model
        self.store_settings(user_id, settings, team_id)

    def delete_settings(self, user_id: str, team_id: Optional[str] = None) -> bool:
        """Delete all settings for a user.

        Args:
            user_id: Slack user ID.
            team_id: Slack team ID (optional, uses default if not specified).

        Returns:
            True if settings were deleted, False otherwise.
        """
        team_id = self._resolve_team_id(team_id)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'DELETE FROM user_settings WHERE team_id = ? AND user_id = ?',
                    (team_id, user_id)
                )
                conn.commit()

                if cursor.rowcount > 0:
                    logger.info(f"Deleted settings for user {user_id} in team {team_id}")
                    return True
                else:
                    logger.warning(f"No settings found for user {user_id} in team {team_id}")
                    return False
        except Exception as e:
            logger.error(f"Failed to delete settings for user {user_id} in team {team_id}: {e}")
            return False

    def has_openai_api_key(self, user_id: str, team_id: Optional[str] = None) -> bool:
        """Check if user has a valid OpenAI API key.

        Args:
            user_id: Slack user ID.
            team_id: Slack team ID (optional, uses default if not specified).

        Returns:
            True if a valid API key is set.
        """
        settings = self.get_settings(user_id, team_id)
        return settings.openai_api_key is not None and len(settings.openai_api_key.strip()) > 0

    # === Migration Methods ===

    def migrate_user_data_to_team(self, team_id: str, from_team_id: Optional[str] = None) -> int:
        """Migrate user data from one team to another.

        This is useful for migrating existing data to a specific workspace.

        Args:
            team_id: Target team ID.
            from_team_id: Source team ID (default team if not specified).

        Returns:
            Number of records migrated.
        """
        from_team_id = from_team_id or DEFAULT_TEAM_ID
        if from_team_id == team_id:
            logger.warning("Source and target team IDs are the same, no migration needed")
            return 0

        migrated = 0
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Migrate cookies
                cursor = conn.execute('''
                    UPDATE user_cookies SET team_id = ?
                    WHERE team_id = ?
                ''', (team_id, from_team_id))
                migrated += cursor.rowcount

                # Migrate settings
                cursor = conn.execute('''
                    UPDATE user_settings SET team_id = ?
                    WHERE team_id = ?
                ''', (team_id, from_team_id))
                migrated += cursor.rowcount

                conn.commit()

            logger.info(f"Migrated {migrated} records from team {from_team_id} to {team_id}")
            return migrated

        except Exception as e:
            logger.error(f"Failed to migrate user data to team {team_id}: {e}")
            raise

    def get_all_user_ids(self, team_id: Optional[str] = None) -> List[str]:
        """Get all user IDs with data in a specific team.

        Args:
            team_id: Slack team ID (optional, uses default if not specified).

        Returns:
            List of user IDs.
        """
        team_id = self._resolve_team_id(team_id)
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Get users from both cookies and settings tables
                cursor = conn.execute('''
                    SELECT DISTINCT user_id FROM user_cookies WHERE team_id = ?
                    UNION
                    SELECT DISTINCT user_id FROM user_settings WHERE team_id = ?
                ''', (team_id, team_id))
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get user IDs for team {team_id}: {e}")
            return []
    
    # === Helper Methods ===
    
    def _parse_cookies_content(self, content: str) -> Dict[str, str]:
        """Parse Netscape cookies format and extract key information"""
        cookies = {}
        lines = content.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            parts = line.split('\t')
            if len(parts) >= 7:
                domain, flag, path, secure, expiration, name, value = parts[:7]
                cookies[name] = {
                    'value': value,
                    'domain': domain,
                    'path': path,
                    'secure': secure == 'TRUE',
                    'expiration': expiration
                }
        
        return cookies

    def _get_youtube_domains(self, cookies: Dict[str, Any]) -> List[str]:
        """Extract YouTube related domains from cookies"""
        domains = set()
        for cookie_data in cookies.values():
            if isinstance(cookie_data, dict) and 'domain' in cookie_data:
                domain = cookie_data['domain']
                if any(yt_domain in domain.lower() for yt_domain in ['youtube', 'google', 'gstatic']):
                    domains.add(domain)
        return list(domains)


class CookieFileProcessor:
    """Process uploaded cookies.txt files"""
    
    @staticmethod
    def validate_cookies_file(content: str) -> bool:
        """Validate if the content is a valid Netscape cookies format"""
        lines = content.strip().split('\n')
        
        # Check for Netscape header
        has_netscape_header = any('Netscape HTTP Cookie File' in line for line in lines[:5])
        
        # Check for valid cookie entries
        valid_entries = 0
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            parts = line.split('\t')
            if len(parts) >= 7:
                # Basic validation of cookie structure
                domain, flag, path, secure, expiration, name, value = parts[:7]
                if domain and name and value:
                    valid_entries += 1
        
        return has_netscape_header and valid_entries > 0
    
    @staticmethod
    def extract_youtube_cookies(content: str) -> str:
        """Extract YouTube-specific cookies from the content"""
        lines = content.strip().split('\n')
        youtube_lines = []
        
        # Keep header comments
        for line in lines:
            if line.startswith('#'):
                youtube_lines.append(line)
                continue
            
            line = line.strip()
            if not line:
                continue
            
            parts = line.split('\t')
            if len(parts) >= 7:
                domain = parts[0]
                # Include YouTube and Google domains
                if any(yt_domain in domain for yt_domain in [
                    'youtube.com', 'googlevideo.com', 'google.com', 
                    'googleapis.com', 'gstatic.com'
                ]):
                    youtube_lines.append(line)
        
        return '\n'.join(youtube_lines)


# Maintain backward compatibility
UserCookieManager = UserSettingsManager