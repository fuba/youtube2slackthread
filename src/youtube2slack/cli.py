"""Simplified command-line interface for YouTube2SlackThread - Slash commands only."""

import os
import sys
import logging
from pathlib import Path
from typing import Optional
import click

from .workflow import WorkflowConfig
from .slack_server import SlackServer
from .slack_bot_client import SlackBotClient


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
        
        # Get Slack configuration from environment and config
        bot_token = os.environ.get('SLACK_BOT_TOKEN')
        signing_secret = os.environ.get('SLACK_SIGNING_SECRET')
        default_channel = os.environ.get('SLACK_DEFAULT_CHANNEL')
        
        # Get app_token from config first, then fall back to env var
        app_token = config.slack_app_token or os.environ.get('SLACK_APP_TOKEN')
        
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
  app_token: null                    # Slack App-Level Token for Socket Mode (starts with xapp-)

# User-specific cookie management
cookie_management:
  enabled: true                      # Enable user-specific cookies
  encryption_key: null               # Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
  database_path: "user_cookies.db"   # SQLite database path
  temp_dir: "/tmp/youtube2slack_cookies"  # Temporary directory
'''
    
    config_path = 'config.yaml'
    if Path(config_path).exists():
        if not click.confirm(f'{config_path} already exists. Overwrite?'):
            click.echo("Config creation cancelled.")
            return
    
    try:
        with open(config_path, 'w') as f:
            f.write(config_content)
        click.echo(f"✓ Created config file: {config_path}")
        click.echo("\nNext steps:")
        click.echo("1. Edit config.yaml to set your preferences")
        click.echo("2. Set the following environment variables:")
        click.echo("   - SLACK_BOT_TOKEN")
        click.echo("   - SLACK_SIGNING_SECRET") 
        click.echo("   - SLACK_DEFAULT_CHANNEL (optional)")
        click.echo("\n3. For user cookie management:")
        click.echo("   - Generate encryption key: python -c \"import secrets; print(secrets.token_urlsafe(32))\"")
        click.echo("   - Set slack.app_token in config.yaml for Socket Mode")
        
    except Exception as e:
        click.echo(f"✗ Failed to create config: {e}", err=True)
        sys.exit(1)


def main():
    """Main entry point."""
    cli()


if __name__ == '__main__':
    main()