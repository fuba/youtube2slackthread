"""Command-line interface for YouTube2SlackThread with multi-workspace support."""

import os
import sys
import logging
from pathlib import Path
from typing import Optional
import click

from .workflow import WorkflowConfig
from .slack_server import SlackServer
from .slack_bot_client import SlackBotClient

# Logger for CLI
logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False, log_file: Optional[str] = None) -> None:
    """Set up logging configuration.
    
    Args:
        verbose: Enable debug logging
        log_file: Optional log file path
    """
    level = logging.DEBUG if verbose else logging.INFO
    
    # Configure formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)
    
    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(level)
    logger.addHandler(console_handler)
    
    # File handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)


@click.group()
@click.option('--config', '-c', 
              type=click.Path(exists=True), 
              help='Path to configuration file')
@click.option('--verbose', '-v', is_flag=True, 
              help='Enable verbose logging')
@click.option('--log-file', type=click.Path(), 
              help='Log file path')
@click.pass_context
def cli(ctx, config: Optional[str], verbose: bool, log_file: Optional[str]):
    """YouTube2SlackThread: Real-time transcription with Slack threads via slash commands."""
    
    setup_logging(verbose, log_file)
    
    # Load configuration
    if config:
        workflow_config = WorkflowConfig.from_yaml(config)
        click.echo(f"Using config file: {config}")
    else:
        # Look for default config files
        default_configs = ['config.yaml', 'config.yml', '.youtube2slack.yaml', '.youtube2slack.yml']
        config_found = False
        
        for default_config in default_configs:
            if Path(default_config).exists():
                workflow_config = WorkflowConfig.from_yaml(default_config)
                click.echo(f"Using config file: {default_config}")
                config_found = True
                break
        
        if not config_found:
            workflow_config = WorkflowConfig()
            click.echo("Using default configuration")
    
    # Store config in context for subcommands
    ctx.ensure_object(dict)
    ctx.obj['config'] = workflow_config


@cli.command()
@click.option('--port', '-p', default=42389, help='Server port')
@click.option('--debug', is_flag=True, help='Enable debug mode')
@click.pass_context
def serve(ctx, port: int, debug: bool):
    """Start Slack server for handling slash commands."""
    
    # Check required environment variables
    required_env_vars = ['SLACK_BOT_TOKEN', 'SLACK_SIGNING_SECRET']
    missing_vars = [var for var in required_env_vars if not os.environ.get(var)]
    
    if missing_vars:
        click.echo("Error: Missing required environment variables:", err=True)
        for var in missing_vars:
            click.echo(f"  - {var}", err=True)
        click.echo("\nPlease set these in your environment.", err=True)
        sys.exit(1)
    
    try:
        config: WorkflowConfig = ctx.obj['config']
        
        # Get Slack configuration from environment
        bot_token = os.environ.get('SLACK_BOT_TOKEN')
        app_token = os.environ.get('SLACK_APP_TOKEN')
        signing_secret = os.environ.get('SLACK_SIGNING_SECRET')
        default_channel = os.environ.get('SLACK_DEFAULT_CHANNEL')
        
        # Cookie manager is already initialized in WorkflowConfig if configured
        if config.cookie_manager:
            click.echo("✅ User cookie management enabled")
            if app_token:
                click.echo("✅ Socket Mode enabled for file uploads")
            else:
                click.echo("⚠️  Socket Mode disabled - set app_token in config.yaml for file uploads")
        elif config.enable_user_cookies:
            click.echo("⚠️  Cookie management enabled but encryption key not set in config.yaml")
        else:
            click.echo("ℹ️  User cookie management disabled")
        
        # Create bot client with cookie manager from config
        bot_client = SlackBotClient(
            bot_token=bot_token,
            app_token=app_token,
            default_channel=default_channel,
            cookie_manager=config.cookie_manager
        )
        
        # Create server with our config
        server = SlackServer(
            bot_client=bot_client,
            workflow_config=config,
            signing_secret=signing_secret,
            port=port
        )
        
        click.echo(f"🚀 Starting Slack server on port {port}")
        click.echo(f"📡 Webhook URL: http://localhost:{port}/slack/commands")
        click.echo("👀 Configure your Slack app to use this URL for slash commands")
        
        # Run server
        server.run(debug=debug)
        
    except Exception as e:
        click.echo(f"❌ Failed to start server: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--host', default='127.0.0.1', help='Web UI host (default: 127.0.0.1)')
@click.option('--port', '-p', default=42390, help='Web UI port (default: 42390)')
@click.option('--debug', is_flag=True, help='Enable debug mode')
@click.pass_context
def web(ctx, host: str, port: int, debug: bool):
    """Start secure web UI server for settings management."""
    
    # Check required environment variables
    required_env_vars = ['COOKIE_ENCRYPTION_KEY']
    missing_vars = [var for var in required_env_vars if not os.environ.get(var)]
    
    if missing_vars:
        click.echo("Error: Missing required environment variables:", err=True)
        for var in missing_vars:
            click.echo(f"  - {var}", err=True)
        click.echo("\nCOOKIE_ENCRYPTION_KEY is required for secure settings storage.", err=True)
        sys.exit(1)
    
    try:
        config: WorkflowConfig = ctx.obj['config']
        
        # Initialize settings manager
        if not config.settings_manager:
            click.echo("❌ Settings manager not initialized. Please check your configuration.", err=True)
            sys.exit(1)
        
        # Import web UI components
        from .web_ui import SecureWebUI
        from .web_token_manager import WebTokenManager
        
        # Initialize token manager
        db_path = os.environ.get('WEB_TOKENS_DB_PATH', 'web_tokens.db')
        token_manager = WebTokenManager(
            db_path=db_path,
            token_lifetime_hours=1
        )
        
        # Create web UI
        web_ui = SecureWebUI(
            settings_manager=config.settings_manager,
            token_manager=token_manager,
            workflow_config=config
        )
        
        click.echo(f"🌐 Starting secure web UI on http://{host}:{port}")
        click.echo("📋 Users can request access URLs via Slack DM: /web-settings")
        click.echo("🔒 All access URLs are temporary and secure")
        
        # Set environment variables for URL generation
        os.environ['WEB_UI_HOST'] = host
        os.environ['WEB_UI_PORT'] = str(port)
        if host != '127.0.0.1':
            os.environ['WEB_UI_BASE_URL'] = f"http://{host}:{port}"
        
        # Start web UI server
        web_ui.run(host=host, port=port, debug=debug)
        
    except KeyboardInterrupt:
        click.echo("\n🛑 Web UI server stopped by user")
        
    except Exception as e:
        logger.error(f"Web UI server error: {e}")
        click.echo(f"❌ Web UI server error: {e}", err=True)
        sys.exit(1)


@cli.command()
def create_config():
    """Create a sample configuration file."""

    config_content = '''# YouTube2SlackThread Configuration File

youtube:
  download_dir: "./downloads"        # Directory to save downloaded videos
  format: "best"                     # Video format (best, bestaudio, etc.)
  keep_video: true                   # Whether to keep video files after processing

whisper:
  model: "medium"                    # Whisper model (tiny, base, small, medium, large)
  device: null                       # Device to use (cpu, cuda, or null for auto)
  language: null                     # Language code (en, ja, etc. or null for auto-detect)

slack:
  webhook_url: null                  # Legacy webhook URL (not used in slash command mode)
  channel: null                      # Optional channel override (e.g., "#transcripts")
  include_timestamps: false          # Include timestamps in transcription
  send_errors_to_slack: true         # Send error notifications to Slack
'''

    config_path = 'config.yaml'
    if Path(config_path).exists():
        if not click.confirm(f'{config_path} already exists. Overwrite?'):
            click.echo("Config creation cancelled.")
            return

    try:
        with open(config_path, 'w') as f:
            f.write(config_content)
        click.echo(f"Created config file: {config_path}")
        click.echo("\nNext steps:")
        click.echo("1. Edit config.yaml to set your preferences")
        click.echo("2. Set the following environment variables:")
        click.echo("   - SLACK_BOT_TOKEN")
        click.echo("   - SLACK_SIGNING_SECRET")
        click.echo("   - SLACK_APP_TOKEN (for Socket Mode file uploads)")
        click.echo("   - SLACK_DEFAULT_CHANNEL (optional)")
        click.echo("   - COOKIE_ENCRYPTION_KEY (for user cookie management)")
        click.echo("\n3. Generate encryption key:")
        click.echo("   python -c \"import secrets; print(secrets.token_urlsafe(32))\"")

    except Exception as e:
        click.echo(f"Failed to create config: {e}", err=True)
        sys.exit(1)


# ============================================================================
# Workspace Management Commands
# ============================================================================

@cli.group()
def workspace():
    """Manage Slack workspaces for multi-workspace deployment."""
    pass


@workspace.command('add')
@click.option('--team-id', required=True, help='Slack team ID (e.g., T0123456789)')
@click.option('--team-name', required=True, help='Human-readable team name')
@click.option('--bot-token', required=True, help='Slack Bot User OAuth Token (xoxb-...)')
@click.option('--signing-secret', required=True, help='Slack app signing secret')
@click.option('--app-token', default=None, help='Slack App-Level Token for Socket Mode (xapp-...)')
@click.pass_context
def workspace_add(ctx, team_id: str, team_name: str, bot_token: str,
                  signing_secret: str, app_token: Optional[str]):
    """Add a new Slack workspace."""
    try:
        from .workspace_manager import WorkspaceManager

        encryption_key = os.environ.get('COOKIE_ENCRYPTION_KEY')
        if not encryption_key:
            click.echo("Error: COOKIE_ENCRYPTION_KEY environment variable is required.", err=True)
            sys.exit(1)

        db_path = os.environ.get('USER_COOKIES_DB_PATH', 'user_cookies.db')
        manager = WorkspaceManager(db_path=db_path, encryption_key=encryption_key)

        workspace = manager.add_workspace(
            team_id=team_id,
            team_name=team_name,
            bot_token=bot_token,
            signing_secret=signing_secret,
            app_token=app_token
        )

        click.echo(f"Added workspace: {workspace.team_id} ({workspace.team_name})")
        if app_token:
            click.echo("  Socket Mode: enabled")
        else:
            click.echo("  Socket Mode: disabled (no app_token)")

    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Failed to add workspace: {e}", err=True)
        sys.exit(1)


@workspace.command('list')
@click.option('--all', 'show_all', is_flag=True, help='Show inactive workspaces too')
@click.pass_context
def workspace_list(ctx, show_all: bool):
    """List all registered workspaces."""
    try:
        from .workspace_manager import WorkspaceManager

        encryption_key = os.environ.get('COOKIE_ENCRYPTION_KEY')
        if not encryption_key:
            click.echo("Error: COOKIE_ENCRYPTION_KEY environment variable is required.", err=True)
            sys.exit(1)

        db_path = os.environ.get('USER_COOKIES_DB_PATH', 'user_cookies.db')
        manager = WorkspaceManager(db_path=db_path, encryption_key=encryption_key)

        workspaces = manager.list_workspaces(active_only=not show_all)

        if not workspaces:
            click.echo("No workspaces registered.")
            click.echo("\nTo add a workspace:")
            click.echo("  youtube2slack workspace add --team-id T... --team-name \"Name\" --bot-token xoxb-... --signing-secret ...")
            return

        click.echo(f"Registered workspaces ({len(workspaces)}):\n")
        for ws in workspaces:
            status = "active" if ws.is_active else "inactive"
            socket_mode = "enabled" if ws.app_token else "disabled"
            click.echo(f"  {ws.team_id} - {ws.team_name}")
            click.echo(f"    Status: {status}")
            click.echo(f"    Socket Mode: {socket_mode}")
            if ws.created_at:
                click.echo(f"    Created: {ws.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
            click.echo()

    except Exception as e:
        click.echo(f"Failed to list workspaces: {e}", err=True)
        sys.exit(1)


@workspace.command('remove')
@click.option('--team-id', required=True, help='Slack team ID to remove')
@click.option('--force', is_flag=True, help='Skip confirmation')
@click.pass_context
def workspace_remove(ctx, team_id: str, force: bool):
    """Remove a Slack workspace."""
    try:
        from .workspace_manager import WorkspaceManager

        encryption_key = os.environ.get('COOKIE_ENCRYPTION_KEY')
        if not encryption_key:
            click.echo("Error: COOKIE_ENCRYPTION_KEY environment variable is required.", err=True)
            sys.exit(1)

        db_path = os.environ.get('USER_COOKIES_DB_PATH', 'user_cookies.db')
        manager = WorkspaceManager(db_path=db_path, encryption_key=encryption_key)

        # Check if workspace exists
        workspace = manager.get_workspace(team_id)
        if not workspace:
            click.echo(f"Workspace not found: {team_id}", err=True)
            sys.exit(1)

        if not force:
            if not click.confirm(f"Remove workspace {team_id} ({workspace.team_name})?"):
                click.echo("Cancelled.")
                return

        if manager.remove_workspace(team_id):
            click.echo(f"Removed workspace: {team_id}")
        else:
            click.echo(f"Failed to remove workspace: {team_id}", err=True)
            sys.exit(1)

    except Exception as e:
        click.echo(f"Failed to remove workspace: {e}", err=True)
        sys.exit(1)


@workspace.command('migrate')
@click.option('--team-id', required=True, help='Target Slack team ID for migration')
@click.option('--from-team-id', default=None, help='Source team ID (default: _default_)')
@click.pass_context
def workspace_migrate(ctx, team_id: str, from_team_id: Optional[str]):
    """Migrate existing user data to a specific workspace.

    This command migrates user cookies and settings from the default team
    (or another specified team) to the target workspace.
    """
    try:
        from .user_cookie_manager import UserSettingsManager, DEFAULT_TEAM_ID

        encryption_key = os.environ.get('COOKIE_ENCRYPTION_KEY')
        if not encryption_key:
            click.echo("Error: COOKIE_ENCRYPTION_KEY environment variable is required.", err=True)
            sys.exit(1)

        db_path = os.environ.get('USER_COOKIES_DB_PATH', 'user_cookies.db')
        settings_manager = UserSettingsManager(db_path=db_path, encryption_key=encryption_key)

        source_team = from_team_id or DEFAULT_TEAM_ID
        click.echo(f"Migrating user data from '{source_team}' to '{team_id}'...")

        migrated = settings_manager.migrate_user_data_to_team(team_id, from_team_id)

        click.echo(f"Migration complete. {migrated} records migrated.")

    except Exception as e:
        click.echo(f"Migration failed: {e}", err=True)
        sys.exit(1)


@workspace.command('discover')
@click.pass_context
def workspace_discover(ctx):
    """Discover team_id from current SLACK_BOT_TOKEN.

    Uses the Slack API to get the team_id for the currently configured bot token.
    Useful for finding the correct team_id when setting up a workspace.
    """
    try:
        from slack_sdk import WebClient

        bot_token = os.environ.get('SLACK_BOT_TOKEN')
        if not bot_token:
            click.echo("Error: SLACK_BOT_TOKEN environment variable is required.", err=True)
            sys.exit(1)

        client = WebClient(token=bot_token)
        auth_result = client.auth_test()

        team_id = auth_result.get('team_id')
        team_name = auth_result.get('team')
        bot_user = auth_result.get('user')
        bot_user_id = auth_result.get('user_id')

        click.echo("Workspace discovered:\n")
        click.echo(f"  Team ID: {team_id}")
        click.echo(f"  Team Name: {team_name}")
        click.echo(f"  Bot User: {bot_user} ({bot_user_id})")
        click.echo("\nTo add this workspace:")
        click.echo(f"  youtube2slack workspace add \\")
        click.echo(f"    --team-id {team_id} \\")
        click.echo(f"    --team-name \"{team_name}\" \\")
        click.echo(f"    --bot-token $SLACK_BOT_TOKEN \\")
        click.echo(f"    --signing-secret $SLACK_SIGNING_SECRET \\")
        click.echo(f"    --app-token $SLACK_APP_TOKEN  # Optional, for Socket Mode")

    except Exception as e:
        click.echo(f"Failed to discover workspace: {e}", err=True)
        sys.exit(1)


@workspace.command('activate')
@click.option('--team-id', required=True, help='Slack team ID to activate')
@click.pass_context
def workspace_activate(ctx, team_id: str):
    """Activate a workspace."""
    try:
        from .workspace_manager import WorkspaceManager

        encryption_key = os.environ.get('COOKIE_ENCRYPTION_KEY')
        if not encryption_key:
            click.echo("Error: COOKIE_ENCRYPTION_KEY environment variable is required.", err=True)
            sys.exit(1)

        db_path = os.environ.get('USER_COOKIES_DB_PATH', 'user_cookies.db')
        manager = WorkspaceManager(db_path=db_path, encryption_key=encryption_key)

        if manager.set_workspace_active(team_id, True):
            click.echo(f"Activated workspace: {team_id}")
        else:
            click.echo(f"Workspace not found: {team_id}", err=True)
            sys.exit(1)

    except Exception as e:
        click.echo(f"Failed to activate workspace: {e}", err=True)
        sys.exit(1)


@workspace.command('deactivate')
@click.option('--team-id', required=True, help='Slack team ID to deactivate')
@click.pass_context
def workspace_deactivate(ctx, team_id: str):
    """Deactivate a workspace (keep data but stop processing)."""
    try:
        from .workspace_manager import WorkspaceManager

        encryption_key = os.environ.get('COOKIE_ENCRYPTION_KEY')
        if not encryption_key:
            click.echo("Error: COOKIE_ENCRYPTION_KEY environment variable is required.", err=True)
            sys.exit(1)

        db_path = os.environ.get('USER_COOKIES_DB_PATH', 'user_cookies.db')
        manager = WorkspaceManager(db_path=db_path, encryption_key=encryption_key)

        if manager.set_workspace_active(team_id, False):
            click.echo(f"Deactivated workspace: {team_id}")
        else:
            click.echo(f"Workspace not found: {team_id}", err=True)
            sys.exit(1)

    except Exception as e:
        click.echo(f"Failed to deactivate workspace: {e}", err=True)
        sys.exit(1)


def main():
    """Main entry point."""
    cli()


if __name__ == '__main__':
    main()