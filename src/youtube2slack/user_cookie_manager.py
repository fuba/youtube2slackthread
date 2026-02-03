"""
User-specific settings management with encryption (cookies, OpenAI API keys, Whisper preferences)
"""
import os
import sqlite3
import base64
import json
from typing import Optional, Dict, Any, Literal, List
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import logging
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)


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
    """Manages encrypted user-specific settings including cookies, API keys, and preferences in SQLite database"""
    
    def __init__(self, db_path: str = "user_cookies.db", encryption_key: Optional[str] = None):
        self.db_path = db_path
        self._encryption_key = encryption_key or os.environ.get("COOKIE_ENCRYPTION_KEY")
        if not self._encryption_key:
            raise ValueError("Encryption key is required. Set COOKIE_ENCRYPTION_KEY environment variable.")
        
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
        """Initialize SQLite database with user tables"""
        with sqlite3.connect(self.db_path) as conn:
            # Create cookies table (maintain compatibility)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS user_cookies (
                    user_id TEXT PRIMARY KEY,
                    encrypted_cookies BLOB NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create settings table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id TEXT PRIMARY KEY,
                    encrypted_settings BLOB NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create triggers for both tables
            conn.execute('''
                CREATE TRIGGER IF NOT EXISTS update_cookies_timestamp 
                AFTER UPDATE ON user_cookies
                BEGIN
                    UPDATE user_cookies SET updated_at = CURRENT_TIMESTAMP 
                    WHERE user_id = NEW.user_id;
                END
            ''')
            
            conn.execute('''
                CREATE TRIGGER IF NOT EXISTS update_settings_timestamp 
                AFTER UPDATE ON user_settings
                BEGIN
                    UPDATE user_settings SET updated_at = CURRENT_TIMESTAMP 
                    WHERE user_id = NEW.user_id;
                END
            ''')
            
            conn.commit()

    # === Cookie Management Methods ===
    
    def store_cookies(self, user_id: str, cookies_content: str) -> None:
        """Store encrypted cookies for a user"""
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
            
            # Store in database
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO user_cookies (user_id, encrypted_cookies)
                    VALUES (?, ?)
                ''', (user_id, encrypted_data))
                conn.commit()
                
            logger.info(f"Successfully stored cookies for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to store cookies for user {user_id}: {e}")
            raise

    def get_cookies(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get decrypted cookies data for a user"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'SELECT encrypted_cookies FROM user_cookies WHERE user_id = ?',
                    (user_id,)
                )
                row = cursor.fetchone()
                
                if not row:
                    return None
                
                # Decrypt the data
                decrypted_data = self._fernet.decrypt(row[0])
                return json.loads(decrypted_data.decode())
                
        except Exception as e:
            logger.error(f"Failed to retrieve cookies for user {user_id}: {e}")
            return None

    def get_cookies_file_path(self, user_id: str) -> Optional[str]:
        """Get temporary cookies file path for yt-dlp"""
        cookies_data = self.get_cookies(user_id)
        if not cookies_data:
            return None
        
        # Create temporary cookies file
        temp_dir = "/tmp/youtube2slack_cookies"
        os.makedirs(temp_dir, exist_ok=True)
        
        cookies_file = os.path.join(temp_dir, f"cookies_{user_id}.txt")
        
        try:
            with open(cookies_file, 'w') as f:
                f.write(cookies_data['content'])
            
            logger.info(f"Created temporary cookies file for user {user_id}")
            return cookies_file
            
        except Exception as e:
            logger.error(f"Failed to create cookies file for user {user_id}: {e}")
            return None

    def delete_cookies(self, user_id: str) -> bool:
        """Delete cookies for a user"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'DELETE FROM user_cookies WHERE user_id = ?',
                    (user_id,)
                )
                conn.commit()
                
                if cursor.rowcount > 0:
                    logger.info(f"Deleted cookies for user {user_id}")
                    return True
                else:
                    logger.warning(f"No cookies found for user {user_id}")
                    return False
                    
        except Exception as e:
            logger.error(f"Failed to delete cookies for user {user_id}: {e}")
            return False

    def has_cookies(self, user_id: str) -> bool:
        """Check if user has cookies stored"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'SELECT 1 FROM user_cookies WHERE user_id = ? LIMIT 1',
                    (user_id,)
                )
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Failed to check cookies for user {user_id}: {e}")
            return False
    
    def cleanup_temp_files(self, user_id: str) -> None:
        """Clean up temporary cookies files for user"""
        temp_dir = "/tmp/youtube2slack_cookies"
        cookies_file = os.path.join(temp_dir, f"cookies_{user_id}.txt")
        
        try:
            if os.path.exists(cookies_file):
                os.remove(cookies_file)
                logger.info(f"Cleaned up temporary cookies file for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to cleanup cookies file for user {user_id}: {e}")

    # === Settings Management Methods ===
    
    def store_settings(self, user_id: str, settings: UserSettings) -> None:
        """Store encrypted user settings"""
        try:
            settings_data = asdict(settings)
            # Convert enum to string for JSON serialization
            if isinstance(settings_data['whisper_service'], WhisperService):
                settings_data['whisper_service'] = settings_data['whisper_service'].value
            
            encrypted_data = self._fernet.encrypt(json.dumps(settings_data).encode())
            
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO user_settings (user_id, encrypted_settings)
                    VALUES (?, ?)
                ''', (user_id, encrypted_data))
                conn.commit()
            
            logger.info(f"Stored settings for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to store settings for user {user_id}: {e}")
            raise
    
    def get_settings(self, user_id: str) -> UserSettings:
        """Retrieve and decrypt user settings, return defaults if not found"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'SELECT encrypted_settings FROM user_settings WHERE user_id = ?',
                    (user_id,)
                )
                row = cursor.fetchone()
                
                if not row:
                    # Return default settings
                    logger.info(f"No settings found for user {user_id}, returning defaults")
                    return UserSettings()
                
                # Decrypt and return settings
                decrypted_data = self._fernet.decrypt(row[0])
                settings_data = json.loads(decrypted_data.decode())
                
                # Convert string back to enum
                if 'whisper_service' in settings_data:
                    settings_data['whisper_service'] = WhisperService(settings_data['whisper_service'])
                
                logger.info(f"Retrieved settings for user {user_id}")
                return UserSettings(**settings_data)
                
        except Exception as e:
            logger.error(f"Failed to retrieve settings for user {user_id}: {e}")
            return UserSettings()  # Return defaults on error
    
    def update_whisper_service(self, user_id: str, service: WhisperService) -> None:
        """Update user's preferred Whisper service"""
        settings = self.get_settings(user_id)
        settings.whisper_service = service
        self.store_settings(user_id, settings)
    
    def update_openai_api_key(self, user_id: str, api_key: str) -> None:
        """Update user's OpenAI API key"""
        settings = self.get_settings(user_id)
        settings.openai_api_key = api_key
        # Auto-switch to OpenAI service when API key is set
        settings.whisper_service = WhisperService.OPENAI
        self.store_settings(user_id, settings)
    
    def update_whisper_model(self, user_id: str, model: str) -> None:
        """Update user's preferred Whisper model (for local Whisper)"""
        settings = self.get_settings(user_id)
        settings.whisper_model = model
        self.store_settings(user_id, settings)
    
    def delete_settings(self, user_id: str) -> bool:
        """Delete all settings for a user"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'DELETE FROM user_settings WHERE user_id = ?',
                    (user_id,)
                )
                conn.commit()
                
                if cursor.rowcount > 0:
                    logger.info(f"Deleted settings for user {user_id}")
                    return True
                else:
                    logger.warning(f"No settings found for user {user_id}")
                    return False
        except Exception as e:
            logger.error(f"Failed to delete settings for user {user_id}: {e}")
            return False
    
    def has_openai_api_key(self, user_id: str) -> bool:
        """Check if user has a valid OpenAI API key"""
        settings = self.get_settings(user_id)
        return settings.openai_api_key is not None and len(settings.openai_api_key.strip()) > 0
    
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