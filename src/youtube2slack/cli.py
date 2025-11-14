"""Command-line interface for YouTube2Slack."""

import os
import sys
import logging
from pathlib import Path
from typing import Optional, List
import click

from .workflow import YouTube2SlackWorkflow, WorkflowConfig, ProcessingResult
from .downloader import YouTubeDownloader


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


def print_result_summary(results: List[ProcessingResult]) -> None:
    """Print a summary of processing results.
    
    Args:
        results: List of processing results
    """
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]
    
    click.echo(f"\n{'='*60}")
    click.echo(f"Processing Summary:")
    click.echo(f"{'='*60}")
    click.echo(f"Total videos: {len(results)}")
    click.echo(f"Successful: {len(successful)} ✓")
    
    if successful:
        for result in successful:
            click.echo(f"  ✓ {result.video_title} ({result.language})")
    
    if failed:
        click.echo(f"Failed: {len(failed)} ✗")
        for result in failed:
            click.echo(f"  ✗ {result.video_title or result.video_url}")
            click.echo(f"    Error: {result.error}")


@click.group()
@click.option('--config', '-c', type=click.Path(exists=True), 
              help='Configuration file path (YAML)')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
@click.option('--log-file', type=click.Path(), help='Log to file')
@click.pass_context
def cli(ctx, config: Optional[str], verbose: bool, log_file: Optional[str]):
    """YouTube2Slack - Download, transcribe, and share YouTube videos on Slack."""
    setup_logging(verbose, log_file)
    
    # Load configuration
    if config:
        workflow_config = WorkflowConfig.from_yaml(config)
    else:
        # Try to load from default locations
        default_configs = [
            'config.yaml', 
            'config.yml',
            os.path.expanduser('~/.youtube2slack/config.yaml'),
            os.path.expanduser('~/.config/youtube2slack/config.yaml')
        ]
        
        workflow_config = None
        for config_path in default_configs:
            if os.path.exists(config_path):
                workflow_config = WorkflowConfig.from_yaml(config_path)
                click.echo(f"Using config file: {config_path}")
                break
        
        if workflow_config is None:
            workflow_config = WorkflowConfig()
            if not config:
                click.echo("No config file found, using defaults")
    
    ctx.ensure_object(dict)
    ctx.obj['config'] = workflow_config


@cli.command()
@click.argument('url')
@click.option('--output-dir', '-o', type=click.Path(), help='Output directory for downloads')
@click.option('--format', '-f', default='best', help='Video format (default: best)')
@click.option('--whisper-model', '-m', default='base', help='Whisper model size')
@click.option('--language', '-l', help='Language code (auto-detect if not specified)')
@click.option('--slack-webhook', help='Slack webhook URL')
@click.option('--slack-channel', help='Slack channel override')
@click.option('--include-timestamps', is_flag=True, help='Include timestamps in transcription')
@click.option('--keep-video', is_flag=True, default=True, help='Keep downloaded video file')
@click.pass_context
def process(ctx, url: str, output_dir: Optional[str], format: str, 
           whisper_model: str, language: Optional[str],
           slack_webhook: Optional[str], slack_channel: Optional[str],
           include_timestamps: bool, keep_video: bool):
    """Process a single YouTube video."""
    
    config: WorkflowConfig = ctx.obj['config']
    
    # Override config with CLI options
    if output_dir:
        config.download_dir = output_dir
    if format != 'best':
        config.video_format = format
    if whisper_model != 'base':
        config.whisper_model = whisper_model
    if language:
        config.whisper_language = language
    if slack_webhook:
        config.slack_webhook = slack_webhook
    if slack_channel:
        config.slack_channel = slack_channel
    if include_timestamps:
        config.include_timestamps = include_timestamps
    
    config.keep_video = keep_video
    
    # Validate required configuration
    if not config.slack_webhook and not slack_webhook:
        click.echo("Error: Slack webhook URL is required", err=True)
        click.echo("Either provide --slack-webhook or set it in config file", err=True)
        sys.exit(1)
    
    # Create workflow and process video
    workflow = YouTube2SlackWorkflow(config)
    
    with click.progressbar(length=100, label='Processing video') as bar:
        def progress_callback(message: str):
            click.echo(f"  {message}")
        
        result = workflow.process_video(url, progress_callback)
        bar.update(100)
    
    # Show result
    print_result_summary([result])
    
    if not result.success:
        sys.exit(1)


@cli.command()
@click.argument('playlist_url')
@click.option('--output-dir', '-o', type=click.Path(), help='Output directory for downloads')
@click.option('--whisper-model', '-m', default='base', help='Whisper model size')
@click.option('--language', '-l', help='Language code (auto-detect if not specified)')
@click.option('--slack-webhook', help='Slack webhook URL')
@click.option('--slack-channel', help='Slack channel override')
@click.option('--include-timestamps', is_flag=True, help='Include timestamps in transcription')
@click.option('--keep-video', is_flag=True, default=False, help='Keep downloaded video files')
@click.pass_context
def playlist(ctx, playlist_url: str, output_dir: Optional[str],
            whisper_model: str, language: Optional[str],
            slack_webhook: Optional[str], slack_channel: Optional[str],
            include_timestamps: bool, keep_video: bool):
    """Process all videos in a YouTube playlist."""
    
    config: WorkflowConfig = ctx.obj['config']
    
    # Override config with CLI options
    if output_dir:
        config.download_dir = output_dir
    if whisper_model != 'base':
        config.whisper_model = whisper_model
    if language:
        config.whisper_language = language
    if slack_webhook:
        config.slack_webhook = slack_webhook
    if slack_channel:
        config.slack_channel = slack_channel
    if include_timestamps:
        config.include_timestamps = include_timestamps
    
    config.keep_video = keep_video
    
    # Validate required configuration
    if not config.slack_webhook:
        click.echo("Error: Slack webhook URL is required", err=True)
        sys.exit(1)
    
    # Create workflow and process playlist
    workflow = YouTube2SlackWorkflow(config)
    
    def progress_callback(message: str):
        click.echo(f"  {message}")
    
    results = workflow.process_playlist(playlist_url, progress_callback)
    
    # Show results
    print_result_summary(results)
    
    failed_count = sum(1 for r in results if not r.success)
    if failed_count > 0:
        sys.exit(1)


@cli.command()
@click.argument('file_path', type=click.Path(exists=True))
@click.option('--output-dir', '-o', type=click.Path(), help='Output directory for downloads')
@click.option('--whisper-model', '-m', default='base', help='Whisper model size')
@click.option('--language', '-l', help='Language code (auto-detect if not specified)')
@click.option('--slack-webhook', help='Slack webhook URL')
@click.option('--slack-channel', help='Slack channel override')
@click.option('--include-timestamps', is_flag=True, help='Include timestamps in transcription')
@click.option('--keep-video', is_flag=True, default=False, help='Keep downloaded video files')
@click.pass_context
def batch(ctx, file_path: str, output_dir: Optional[str],
         whisper_model: str, language: Optional[str],
         slack_webhook: Optional[str], slack_channel: Optional[str],
         include_timestamps: bool, keep_video: bool):
    """Process videos from a file containing URLs (one per line)."""
    
    config: WorkflowConfig = ctx.obj['config']
    
    # Override config with CLI options
    if output_dir:
        config.download_dir = output_dir
    if whisper_model != 'base':
        config.whisper_model = whisper_model
    if language:
        config.whisper_language = language
    if slack_webhook:
        config.slack_webhook = slack_webhook
    if slack_channel:
        config.slack_channel = slack_channel
    if include_timestamps:
        config.include_timestamps = include_timestamps
    
    config.keep_video = keep_video
    
    # Validate required configuration
    if not config.slack_webhook:
        click.echo("Error: Slack webhook URL is required", err=True)
        sys.exit(1)
    
    # Create workflow and process from file
    workflow = YouTube2SlackWorkflow(config)
    results = workflow.process_from_file(file_path)
    
    # Show results
    print_result_summary(results)
    
    failed_count = sum(1 for r in results if not r.success)
    if failed_count > 0:
        sys.exit(1)


@cli.command()
@click.argument('url')
@click.option('--output-dir', '-o', type=click.Path(), help='Output directory')
@click.option('--format', '-f', default='best', help='Video format')
def download_only(url: str, output_dir: Optional[str], format: str):
    """Download a video without transcribing or posting to Slack."""
    
    if not output_dir:
        output_dir = './downloads'
    
    downloader = YouTubeDownloader(output_dir=output_dir, format_spec=format)
    
    try:
        with click.progressbar(length=100, label='Downloading') as bar:
            # Note: yt-dlp doesn't provide easy progress callbacks, 
            # so we'll just show indeterminate progress
            result = downloader.download(url)
            bar.update(100)
        
        click.echo(f"✓ Downloaded: {result['title']}")
        click.echo(f"  File: {result['video_path']}")
        click.echo(f"  Duration: {result.get('duration', 0)} seconds")
        
    except Exception as e:
        click.echo(f"✗ Download failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument('url')
def info(url: str):
    """Get information about a YouTube video without downloading."""
    
    downloader = YouTubeDownloader(output_dir='.')
    
    try:
        info = downloader.get_info(url)
        
        click.echo(f"Title: {info['title']}")
        click.echo(f"Video ID: {info['video_id']}")
        click.echo(f"Uploader: {info['uploader']}")
        click.echo(f"Duration: {info.get('duration', 0)} seconds")
        click.echo(f"Views: {info.get('view_count', 0):,}")
        click.echo(f"Upload Date: {info.get('upload_date', 'Unknown')}")
        
        if info.get('description'):
            desc = info['description'][:200] + "..." if len(info['description']) > 200 else info['description']
            click.echo(f"Description: {desc}")
            
    except Exception as e:
        click.echo(f"✗ Failed to get info: {e}", err=True)
        sys.exit(1)


@cli.command()
def create_config():
    """Create a sample configuration file."""
    
    config_content = '''# YouTube2Slack Configuration File

youtube:
  download_dir: "./downloads"        # Directory to save downloaded videos
  format: "best"                     # Video format (best, bestaudio, etc.)
  keep_video: true                   # Whether to keep video files after processing

whisper:
  model: "base"                      # Whisper model (tiny, base, small, medium, large)
  device: null                       # Device to use (cpu, cuda, or null for auto)
  language: null                     # Language code (en, ja, etc. or null for auto-detect)

slack:
  webhook_url: "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
  channel: null                      # Optional channel override (e.g., "#transcripts")
  include_timestamps: false          # Include timestamps in transcription
  send_errors_to_slack: true         # Send error notifications to Slack
'''
    
    config_path = 'config.yaml'
    
    if os.path.exists(config_path):
        if not click.confirm(f"Config file {config_path} exists. Overwrite?"):
            return
    
    with open(config_path, 'w') as f:
        f.write(config_content)
    
    click.echo(f"✓ Created config file: {config_path}")
    click.echo("Please edit the file to set your Slack webhook URL and other preferences.")


def main():
    """Main entry point."""
    cli()


if __name__ == '__main__':
    main()