"""
User-specific cookie management with encryption
"""
import os
import sqlite3
import base64
import json
from typing import Optional, Dict, Any
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import logging

logger = logging.getLogger(__name__)


class UserCookieManager:
    """Manages encrypted user-specific cookies in SQLite database"""
    
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
        """Initialize SQLite database with user_cookies table"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS user_cookies (
                    user_id TEXT PRIMARY KEY,
                    encrypted_cookies BLOB NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TRIGGER IF NOT EXISTS update_timestamp 
                AFTER UPDATE ON user_cookies
                BEGIN
                    UPDATE user_cookies SET updated_at = CURRENT_TIMESTAMP 
                    WHERE user_id = NEW.user_id;
                END
            ''')
            conn.commit()
    
    def store_cookies(self, user_id: str, cookies_content: str) -> None:
        """Store encrypted cookies for a user"""
        try:
            # Parse and validate cookies content
            parsed_cookies = self._parse_cookies_content(cookies_content)
            
            # Encrypt cookies data
            cookies_data = {
                'content': cookies_content,
                'parsed': parsed_cookies,
                'format': 'netscape'
            }
            encrypted_data = self._fernet.encrypt(json.dumps(cookies_data).encode())
            
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO user_cookies (user_id, encrypted_cookies)
                    VALUES (?, ?)
                ''', (user_id, encrypted_data))
                conn.commit()
            
            logger.info(f"Stored cookies for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to store cookies for user {user_id}: {e}")
            raise
    
    def get_cookies(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve and decrypt cookies for a user"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'SELECT encrypted_cookies FROM user_cookies WHERE user_id = ?',
                    (user_id,)
                )
                row = cursor.fetchone()
                
                if not row:
                    return None
                
                # Decrypt and return cookies data
                decrypted_data = self._fernet.decrypt(row[0])
                cookies_data = json.loads(decrypted_data.decode())
                
                logger.info(f"Retrieved cookies for user {user_id}")
                return cookies_data
        except Exception as e:
            logger.error(f"Failed to retrieve cookies for user {user_id}: {e}")
            return None
    
    def get_cookies_file_path(self, user_id: str) -> Optional[str]:
        """Create temporary cookies file for user and return path"""
        cookies_data = self.get_cookies(user_id)
        if not cookies_data:
            return None
        
        # Create user-specific temporary cookies file
        temp_dir = "/tmp/youtube2slack_cookies"
        os.makedirs(temp_dir, exist_ok=True)
        
        cookies_file = os.path.join(temp_dir, f"cookies_{user_id}.txt")
        
        with open(cookies_file, 'w') as f:
            f.write(cookies_data['content'])
        
        # Set restrictive permissions
        os.chmod(cookies_file, 0o600)
        
        logger.info(f"Created temporary cookies file for user {user_id}: {cookies_file}")
        return cookies_file
    
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
        """Check if user has stored cookies"""
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