"""Workspace management for multi-Slack-workspace support.

This module handles CRUD operations for workspace configurations in the database.
"""

import sqlite3
import json
import logging
from typing import Optional, List
from dataclasses import dataclass
from datetime import datetime

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

logger = logging.getLogger(__name__)


@dataclass
class WorkspaceConfig:
    """Configuration for a Slack workspace."""
    team_id: str
    team_name: str
    bot_token: str
    app_token: Optional[str]
    signing_secret: str
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class WorkspaceManager:
    """Manages workspace configurations in the database."""

    def __init__(self, db_path: str, encryption_key: str):
        """Initialize workspace manager.

        Args:
            db_path: Path to SQLite database.
            encryption_key: Key for encrypting sensitive data (tokens, secrets).
        """
        self.db_path = db_path
        self._encryption_key = encryption_key
        self._fernet = self._create_fernet()

    def _create_fernet(self) -> Fernet:
        """Create Fernet encryption instance from password."""
        password = self._encryption_key.encode()
        # Use a different salt than user_cookie_manager to separate encryption contexts
        salt = b'youtube2slack_ws_salt'

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password))
        return Fernet(key)

    def _encrypt(self, data: str) -> bytes:
        """Encrypt a string."""
        return self._fernet.encrypt(data.encode())

    def _decrypt(self, data: bytes) -> str:
        """Decrypt encrypted data."""
        return self._fernet.decrypt(data).decode()

    def add_workspace(self, team_id: str, team_name: str, bot_token: str,
                      signing_secret: str, app_token: Optional[str] = None) -> WorkspaceConfig:
        """Add a new workspace configuration.

        Args:
            team_id: Slack team ID (e.g., T0123456789).
            team_name: Human-readable team name.
            bot_token: Slack Bot User OAuth Token (xoxb-...).
            signing_secret: Slack app signing secret.
            app_token: Slack App-Level Token for Socket Mode (xapp-...).

        Returns:
            WorkspaceConfig for the added workspace.

        Raises:
            ValueError: If team_id already exists or invalid token format.
        """
        # Validate tokens
        if not bot_token.startswith('xoxb-'):
            raise ValueError("Bot token must start with 'xoxb-'")
        if app_token and not app_token.startswith('xapp-'):
            raise ValueError("App token must start with 'xapp-'")

        # Encrypt sensitive data
        encrypted_bot_token = self._encrypt(bot_token)
        encrypted_signing_secret = self._encrypt(signing_secret)
        encrypted_app_token = self._encrypt(app_token) if app_token else None

        try:
            with sqlite3.connect(self.db_path) as conn:
                # Check if workspace already exists
                cursor = conn.execute(
                    'SELECT 1 FROM workspaces WHERE team_id = ?',
                    (team_id,)
                )
                if cursor.fetchone():
                    raise ValueError(f"Workspace {team_id} already exists. Use update_workspace() instead.")

                conn.execute('''
                    INSERT INTO workspaces (team_id, team_name, encrypted_bot_token,
                                           encrypted_app_token, encrypted_signing_secret)
                    VALUES (?, ?, ?, ?, ?)
                ''', (team_id, team_name, encrypted_bot_token,
                      encrypted_app_token, encrypted_signing_secret))
                conn.commit()

            logger.info(f"Added workspace: {team_id} ({team_name})")

            return WorkspaceConfig(
                team_id=team_id,
                team_name=team_name,
                bot_token=bot_token,
                app_token=app_token,
                signing_secret=signing_secret,
                is_active=True,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )

        except sqlite3.IntegrityError as e:
            logger.error(f"Failed to add workspace {team_id}: {e}")
            raise ValueError(f"Workspace {team_id} already exists")
        except Exception as e:
            logger.error(f"Failed to add workspace {team_id}: {e}")
            raise

    def remove_workspace(self, team_id: str) -> bool:
        """Remove a workspace configuration.

        Args:
            team_id: Slack team ID to remove.

        Returns:
            True if workspace was removed, False if not found.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'DELETE FROM workspaces WHERE team_id = ?',
                    (team_id,)
                )
                conn.commit()

                if cursor.rowcount > 0:
                    logger.info(f"Removed workspace: {team_id}")
                    return True
                else:
                    logger.warning(f"Workspace not found: {team_id}")
                    return False

        except Exception as e:
            logger.error(f"Failed to remove workspace {team_id}: {e}")
            raise

    def get_workspace(self, team_id: str) -> Optional[WorkspaceConfig]:
        """Get workspace configuration by team ID.

        Args:
            team_id: Slack team ID.

        Returns:
            WorkspaceConfig or None if not found.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute('''
                    SELECT team_id, team_name, encrypted_bot_token, encrypted_app_token,
                           encrypted_signing_secret, is_active, created_at, updated_at
                    FROM workspaces
                    WHERE team_id = ?
                ''', (team_id,))

                row = cursor.fetchone()
                if not row:
                    return None

                return self._row_to_workspace(row)

        except Exception as e:
            logger.error(f"Failed to get workspace {team_id}: {e}")
            return None

    def list_workspaces(self, active_only: bool = True) -> List[WorkspaceConfig]:
        """List all workspaces.

        Args:
            active_only: If True, only return active workspaces.

        Returns:
            List of WorkspaceConfig instances.
        """
        workspaces = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row

                if active_only:
                    cursor = conn.execute('''
                        SELECT team_id, team_name, encrypted_bot_token, encrypted_app_token,
                               encrypted_signing_secret, is_active, created_at, updated_at
                        FROM workspaces
                        WHERE is_active = 1
                        ORDER BY created_at
                    ''')
                else:
                    cursor = conn.execute('''
                        SELECT team_id, team_name, encrypted_bot_token, encrypted_app_token,
                               encrypted_signing_secret, is_active, created_at, updated_at
                        FROM workspaces
                        ORDER BY created_at
                    ''')

                for row in cursor.fetchall():
                    workspaces.append(self._row_to_workspace(row))

        except Exception as e:
            logger.error(f"Failed to list workspaces: {e}")

        return workspaces

    def update_workspace(self, team_id: str, team_name: Optional[str] = None,
                         bot_token: Optional[str] = None, app_token: Optional[str] = None,
                         signing_secret: Optional[str] = None,
                         is_active: Optional[bool] = None) -> Optional[WorkspaceConfig]:
        """Update workspace configuration.

        Args:
            team_id: Slack team ID to update.
            team_name: New team name (optional).
            bot_token: New bot token (optional).
            app_token: New app token (optional).
            signing_secret: New signing secret (optional).
            is_active: New active status (optional).

        Returns:
            Updated WorkspaceConfig or None if not found.

        Raises:
            ValueError: If invalid token format.
        """
        # Validate tokens if provided
        if bot_token and not bot_token.startswith('xoxb-'):
            raise ValueError("Bot token must start with 'xoxb-'")
        if app_token and not app_token.startswith('xapp-'):
            raise ValueError("App token must start with 'xapp-'")

        try:
            # Build update query dynamically
            updates = []
            params = []

            if team_name is not None:
                updates.append("team_name = ?")
                params.append(team_name)

            if bot_token is not None:
                updates.append("encrypted_bot_token = ?")
                params.append(self._encrypt(bot_token))

            if app_token is not None:
                updates.append("encrypted_app_token = ?")
                params.append(self._encrypt(app_token))

            if signing_secret is not None:
                updates.append("encrypted_signing_secret = ?")
                params.append(self._encrypt(signing_secret))

            if is_active is not None:
                updates.append("is_active = ?")
                params.append(1 if is_active else 0)

            if not updates:
                return self.get_workspace(team_id)

            params.append(team_id)

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    f"UPDATE workspaces SET {', '.join(updates)} WHERE team_id = ?",
                    params
                )
                conn.commit()

                if cursor.rowcount == 0:
                    logger.warning(f"Workspace not found for update: {team_id}")
                    return None

            logger.info(f"Updated workspace: {team_id}")
            return self.get_workspace(team_id)

        except Exception as e:
            logger.error(f"Failed to update workspace {team_id}: {e}")
            raise

    def set_workspace_active(self, team_id: str, is_active: bool) -> bool:
        """Set workspace active/inactive status.

        Args:
            team_id: Slack team ID.
            is_active: New active status.

        Returns:
            True if updated successfully.
        """
        return self.update_workspace(team_id, is_active=is_active) is not None

    def get_first_workspace(self) -> Optional[WorkspaceConfig]:
        """Get the first registered workspace.

        Useful for backward compatibility when no specific team_id is provided.

        Returns:
            First WorkspaceConfig or None if no workspaces registered.
        """
        workspaces = self.list_workspaces(active_only=True)
        return workspaces[0] if workspaces else None

    def has_workspaces(self) -> bool:
        """Check if any workspaces are registered.

        Returns:
            True if at least one workspace is registered.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('SELECT 1 FROM workspaces LIMIT 1')
                return cursor.fetchone() is not None
        except Exception:
            return False

    def _row_to_workspace(self, row: sqlite3.Row) -> WorkspaceConfig:
        """Convert database row to WorkspaceConfig."""
        # Decrypt sensitive data
        bot_token = self._decrypt(row['encrypted_bot_token'])
        signing_secret = self._decrypt(row['encrypted_signing_secret'])
        app_token = None
        if row['encrypted_app_token']:
            app_token = self._decrypt(row['encrypted_app_token'])

        # Parse timestamps
        created_at = None
        updated_at = None
        if row['created_at']:
            created_at = datetime.fromisoformat(row['created_at'])
        if row['updated_at']:
            updated_at = datetime.fromisoformat(row['updated_at'])

        return WorkspaceConfig(
            team_id=row['team_id'],
            team_name=row['team_name'],
            bot_token=bot_token,
            app_token=app_token,
            signing_secret=signing_secret,
            is_active=bool(row['is_active']),
            created_at=created_at,
            updated_at=updated_at
        )
