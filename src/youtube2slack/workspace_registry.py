"""Runtime registry for Slack clients across multiple workspaces.

This module manages active Slack client connections for all registered workspaces.
"""

import os
import logging
from typing import Optional, Dict, Callable, Any, List
from dataclasses import dataclass

from slack_sdk import WebClient
from slack_sdk.socket_mode import SocketModeClient

from .workspace_manager import WorkspaceManager, WorkspaceConfig
from .user_cookie_manager import UserSettingsManager

logger = logging.getLogger(__name__)


@dataclass
class WorkspaceClient:
    """Active Slack client for a workspace."""
    team_id: str
    team_name: str
    web_client: WebClient
    socket_client: Optional[SocketModeClient]
    signing_secret: str
    is_connected: bool = False


class WorkspaceRegistry:
    """Runtime registry for Slack clients across multiple workspaces."""

    def __init__(self, workspace_manager: WorkspaceManager,
                 settings_manager: Optional[UserSettingsManager] = None):
        """Initialize workspace registry.

        Args:
            workspace_manager: WorkspaceManager for database operations.
            settings_manager: UserSettingsManager for user data (optional).
        """
        self.workspace_manager = workspace_manager
        self.settings_manager = settings_manager
        self._clients: Dict[str, WorkspaceClient] = {}
        self._socket_mode_handlers: List[Callable] = []
        self._fallback_team_id: Optional[str] = None

    def initialize(self) -> int:
        """Initialize clients for all active workspaces.

        Returns:
            Number of workspaces initialized.
        """
        workspaces = self.workspace_manager.list_workspaces(active_only=True)

        for workspace in workspaces:
            try:
                self._initialize_workspace_client(workspace)
            except Exception as e:
                logger.error(f"Failed to initialize workspace {workspace.team_id}: {e}")

        # Set fallback to first workspace
        if workspaces:
            self._fallback_team_id = workspaces[0].team_id

        logger.info(f"Initialized {len(self._clients)} workspace clients")
        return len(self._clients)

    def _initialize_workspace_client(self, workspace: WorkspaceConfig) -> WorkspaceClient:
        """Initialize Slack clients for a workspace.

        Args:
            workspace: WorkspaceConfig to initialize.

        Returns:
            WorkspaceClient instance.
        """
        # Create web client
        web_client = WebClient(token=workspace.bot_token)

        # Test connection
        try:
            auth_result = web_client.auth_test()
            logger.info(f"Connected to workspace {workspace.team_id} as {auth_result.get('user', 'unknown')}")
        except Exception as e:
            logger.error(f"Failed to authenticate with workspace {workspace.team_id}: {e}")
            raise

        # Create socket mode client if app token available
        socket_client = None
        if workspace.app_token:
            socket_client = SocketModeClient(
                app_token=workspace.app_token,
                web_client=web_client
            )

        client = WorkspaceClient(
            team_id=workspace.team_id,
            team_name=workspace.team_name,
            web_client=web_client,
            socket_client=socket_client,
            signing_secret=workspace.signing_secret,
            is_connected=True
        )

        self._clients[workspace.team_id] = client
        return client

    def get_client(self, team_id: str) -> Optional[WorkspaceClient]:
        """Get Slack client for a specific workspace.

        Args:
            team_id: Slack team ID.

        Returns:
            WorkspaceClient or None if not found.
        """
        return self._clients.get(team_id)

    def get_web_client(self, team_id: str) -> Optional[WebClient]:
        """Get WebClient for a specific workspace.

        Args:
            team_id: Slack team ID.

        Returns:
            WebClient or None if not found.
        """
        client = self.get_client(team_id)
        return client.web_client if client else None

    def get_signing_secret(self, team_id: str) -> Optional[str]:
        """Get signing secret for a specific workspace.

        Args:
            team_id: Slack team ID.

        Returns:
            Signing secret string or None if not found.
        """
        client = self.get_client(team_id)
        return client.signing_secret if client else None

    def get_fallback_client(self) -> Optional[WorkspaceClient]:
        """Get fallback client (first registered workspace).

        Used for backward compatibility when team_id is not specified.

        Returns:
            WorkspaceClient or None if no workspaces registered.
        """
        if self._fallback_team_id:
            return self._clients.get(self._fallback_team_id)
        return None

    def get_all_team_ids(self) -> List[str]:
        """Get all registered team IDs.

        Returns:
            List of team IDs.
        """
        return list(self._clients.keys())

    def add_socket_mode_handler(self, handler: Callable) -> None:
        """Add a handler for Socket Mode events.

        The handler will be called for all workspaces.

        Args:
            handler: Function to handle Socket Mode events.
                    Signature: handler(client, team_id, req)
        """
        self._socket_mode_handlers.append(handler)

    def start_all_socket_modes(self) -> int:
        """Start Socket Mode connections for all workspaces with app tokens.

        Returns:
            Number of Socket Mode connections started.
        """
        started = 0
        for team_id, client in self._clients.items():
            if client.socket_client:
                try:
                    # Add handlers to this socket client
                    for handler in self._socket_mode_handlers:
                        # Wrap handler to include team_id
                        def make_wrapped_handler(tid, h):
                            def wrapped(socket_client, req):
                                return h(socket_client, tid, req)
                            return wrapped

                        client.socket_client.socket_mode_request_listeners.append(
                            make_wrapped_handler(team_id, handler)
                        )

                    client.socket_client.connect()
                    logger.info(f"Started Socket Mode for workspace {team_id}")
                    started += 1
                except Exception as e:
                    logger.error(f"Failed to start Socket Mode for workspace {team_id}: {e}")

        logger.info(f"Started {started} Socket Mode connections")
        return started

    def stop_all_socket_modes(self) -> int:
        """Stop all Socket Mode connections.

        Returns:
            Number of connections stopped.
        """
        stopped = 0
        for team_id, client in self._clients.items():
            if client.socket_client:
                try:
                    client.socket_client.disconnect()
                    logger.info(f"Stopped Socket Mode for workspace {team_id}")
                    stopped += 1
                except Exception as e:
                    logger.error(f"Failed to stop Socket Mode for workspace {team_id}: {e}")

        logger.info(f"Stopped {stopped} Socket Mode connections")
        return stopped

    def refresh_workspace(self, team_id: str) -> bool:
        """Refresh client for a specific workspace.

        Useful after updating workspace configuration.

        Args:
            team_id: Slack team ID to refresh.

        Returns:
            True if refreshed successfully.
        """
        # Stop existing socket mode if running
        existing_client = self._clients.get(team_id)
        if existing_client and existing_client.socket_client:
            try:
                existing_client.socket_client.disconnect()
            except Exception:
                pass

        # Get updated workspace config
        workspace = self.workspace_manager.get_workspace(team_id)
        if not workspace or not workspace.is_active:
            # Remove from registry
            if team_id in self._clients:
                del self._clients[team_id]
            return False

        try:
            self._initialize_workspace_client(workspace)
            return True
        except Exception as e:
            logger.error(f"Failed to refresh workspace {team_id}: {e}")
            return False

    def add_workspace(self, team_id: str, team_name: str, bot_token: str,
                      signing_secret: str, app_token: Optional[str] = None) -> WorkspaceClient:
        """Add and initialize a new workspace.

        Args:
            team_id: Slack team ID.
            team_name: Human-readable team name.
            bot_token: Slack Bot User OAuth Token.
            signing_secret: Slack app signing secret.
            app_token: Slack App-Level Token for Socket Mode (optional).

        Returns:
            WorkspaceClient for the new workspace.
        """
        # Add to database
        workspace = self.workspace_manager.add_workspace(
            team_id=team_id,
            team_name=team_name,
            bot_token=bot_token,
            signing_secret=signing_secret,
            app_token=app_token
        )

        # Initialize client
        return self._initialize_workspace_client(workspace)

    def remove_workspace(self, team_id: str) -> bool:
        """Remove a workspace from registry and database.

        Args:
            team_id: Slack team ID to remove.

        Returns:
            True if removed successfully.
        """
        # Stop socket mode if running
        client = self._clients.get(team_id)
        if client and client.socket_client:
            try:
                client.socket_client.disconnect()
            except Exception:
                pass

        # Remove from registry
        if team_id in self._clients:
            del self._clients[team_id]

        # Remove from database
        return self.workspace_manager.remove_workspace(team_id)

    def is_registered(self, team_id: str) -> bool:
        """Check if a workspace is registered.

        Args:
            team_id: Slack team ID.

        Returns:
            True if workspace is registered in the registry.
        """
        return team_id in self._clients

    def get_workspace_count(self) -> int:
        """Get number of registered workspaces.

        Returns:
            Number of workspaces in registry.
        """
        return len(self._clients)


def create_registry_from_env() -> Optional[WorkspaceRegistry]:
    """Create a WorkspaceRegistry from environment variables.

    For backward compatibility, this creates a registry with a single workspace
    configured via environment variables.

    Returns:
        WorkspaceRegistry or None if required env vars are missing.
    """
    bot_token = os.environ.get('SLACK_BOT_TOKEN')
    signing_secret = os.environ.get('SLACK_SIGNING_SECRET')
    app_token = os.environ.get('SLACK_APP_TOKEN')
    encryption_key = os.environ.get('COOKIE_ENCRYPTION_KEY')
    db_path = os.environ.get('USER_COOKIES_DB_PATH', 'user_cookies.db')

    if not all([bot_token, signing_secret, encryption_key]):
        logger.warning("Missing required environment variables for workspace registry")
        return None

    # Create workspace manager
    workspace_manager = WorkspaceManager(db_path=db_path, encryption_key=encryption_key)

    # Check if we need to register the env-based workspace
    if not workspace_manager.has_workspaces():
        # Get team_id from auth.test
        try:
            web_client = WebClient(token=bot_token)
            auth_result = web_client.auth_test()
            team_id = auth_result.get('team_id')
            team_name = auth_result.get('team', 'Default Workspace')

            if team_id:
                workspace_manager.add_workspace(
                    team_id=team_id,
                    team_name=team_name,
                    bot_token=bot_token,
                    signing_secret=signing_secret,
                    app_token=app_token
                )
                logger.info(f"Registered workspace from environment: {team_id} ({team_name})")
        except Exception as e:
            logger.error(f"Failed to register workspace from environment: {e}")
            return None

    # Create registry
    settings_manager = UserSettingsManager(db_path=db_path, encryption_key=encryption_key)
    registry = WorkspaceRegistry(workspace_manager, settings_manager)

    # Initialize clients
    registry.initialize()

    return registry
