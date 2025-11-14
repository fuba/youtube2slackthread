"""Command-line interface for YouTube2Slack."""

import os
import sys
import logging
import time
from pathlib import Path
from typing import Optional, List
import click

from .workflow import YouTube2SlackWorkflow, WorkflowConfig, ProcessingResult
from .downloader import YouTubeDownloader
from .stream_processor import StreamProcessor
from .vad_stream_processor import VADStreamProcessor
from .whisper_transcriber import WhisperTranscriber
from .slack_client import SlackClient
from .slack_bot_client import SlackBotClient, ThreadInfo, SlackBotError
from .slack_server import SlackServer, create_slack_server


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
@click.option('--whisper-model', '-m', default='medium', help='Whisper model size')
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
@click.option('--whisper-model', '-m', default='medium', help='Whisper model size')
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
@click.option('--whisper-model', '-m', default='medium', help='Whisper model size')
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
@click.argument('stream_url')
@click.option('--chunk-duration', '-d', default=30, help='Duration of each chunk in seconds')
@click.option('--overlap', '-p', default=5, help='Overlap between chunks in seconds')
@click.option('--whisper-model', '-m', default='medium', help='Whisper model size')
@click.option('--language', '-l', help='Language code (auto-detect if not specified)')
@click.option('--slack-webhook', help='Slack webhook URL')
@click.option('--slack-channel', help='Slack channel override')
@click.pass_context
def stream(ctx, stream_url: str, chunk_duration: int, overlap: int,
          whisper_model: str, language: Optional[str],
          slack_webhook: Optional[str], slack_channel: Optional[str]):
    """Process a live YouTube stream in real-time chunks."""
    
    config: WorkflowConfig = ctx.obj['config']
    
    # Override config with CLI options
    if whisper_model != 'base':
        config.whisper_model = whisper_model
    if language:
        config.whisper_language = language
    if slack_webhook:
        config.slack_webhook = slack_webhook
    if slack_channel:
        config.slack_channel = slack_channel
    
    # Validate required configuration
    if not config.slack_webhook:
        click.echo("Error: Slack webhook URL is required", err=True)
        sys.exit(1)
    
    # Initialize components
    click.echo("Initializing stream processor...")
    
    transcriber = WhisperTranscriber(
        model_name=config.whisper_model,
        device=config.whisper_device,
        download_root=config.whisper_download_root
    )
    
    slack_client = SlackClient(
        webhook_url=config.slack_webhook,
        channel=config.slack_channel
    )
    
    processor = StreamProcessor(
        transcriber=transcriber,
        slack_client=slack_client,
        chunk_duration=chunk_duration,
        overlap_duration=overlap
    )
    
    def progress_callback(message: str):
        click.echo(f"  {message}")
    
    try:
        click.echo(f"🔴 Starting live stream processing...")
        click.echo(f"⏱️  Chunk duration: {chunk_duration}s (overlap: {overlap}s)")
        click.echo("Press Ctrl+C to stop processing")
        
        # Start processing
        processor.start_stream_processing(stream_url, progress_callback)
        
        # Keep running until interrupted
        try:
            while processor.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            click.echo("\n🛑 Stopping stream processing...")
            processor.stop_processing()
            click.echo("✓ Stream processing stopped")
            
    except Exception as e:
        click.echo(f"✗ Stream processing failed: {e}", err=True)
        processor.stop_processing()
        sys.exit(1)


@cli.command()
@click.argument('stream_url')
@click.option('--vad-aggressiveness', '-a', default=2, type=int, 
              help='VAD aggressiveness level (0-3, higher = more strict)')
@click.option('--frame-duration', '-f', default=30, type=int,
              help='VAD frame duration in ms (10, 20, or 30)')
@click.option('--whisper-model', '-m', default='medium', help='Whisper model size')
@click.option('--language', '-l', help='Language code (auto-detect if not specified)')
@click.option('--slack-webhook', help='Slack webhook URL')
@click.option('--slack-channel', help='Slack channel override')
@click.pass_context
def vad_stream(ctx, stream_url: str, vad_aggressiveness: int, frame_duration: int,
               whisper_model: str, language: Optional[str],
               slack_webhook: Optional[str], slack_channel: Optional[str]):
    """Process a live YouTube stream with Voice Activity Detection and sentence boundary detection."""
    
    config: WorkflowConfig = ctx.obj['config']
    
    # Override config with CLI options
    if whisper_model != 'base':
        config.whisper_model = whisper_model
    if language:
        config.whisper_language = language
    if slack_webhook:
        config.slack_webhook = slack_webhook
    if slack_channel:
        config.slack_channel = slack_channel
    
    # Validate required configuration
    if not config.slack_webhook:
        click.echo("Error: Slack webhook URL is required", err=True)
        sys.exit(1)
    
    # Validate VAD parameters
    if vad_aggressiveness not in [0, 1, 2, 3]:
        click.echo("Error: VAD aggressiveness must be 0-3", err=True)
        sys.exit(1)
    
    if frame_duration not in [10, 20, 30]:
        click.echo("Error: Frame duration must be 10, 20, or 30 ms", err=True)
        sys.exit(1)
    
    # Initialize components
    click.echo("Initializing VAD stream processor...")
    
    transcriber = WhisperTranscriber(
        model_name=config.whisper_model,
        device=config.whisper_device,
        download_root=config.whisper_download_root
    )
    
    slack_client = SlackClient(
        webhook_url=config.slack_webhook,
        channel=config.slack_channel
    )
    
    processor = VADStreamProcessor(
        transcriber=transcriber,
        slack_client=slack_client,
        vad_aggressiveness=vad_aggressiveness,
        frame_duration_ms=frame_duration
    )
    
    def progress_callback(message: str):
        click.echo(f"  {message}")
    
    try:
        click.echo(f"🔴 Starting VAD-based stream processing...")
        click.echo(f"🎤 VAD aggressiveness: {vad_aggressiveness} | Frame: {frame_duration}ms")
        click.echo(f"📝 Processing speech segments with sentence boundary detection")
        click.echo("Press Ctrl+C to stop processing")
        
        # Start processing
        processor.start_stream_processing(stream_url, progress_callback)
        
        # Keep running until interrupted
        try:
            while processor.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            click.echo("\n🛑 Stopping VAD stream processing...")
            processor.stop_processing()
            click.echo("✓ VAD stream processing stopped")
            
    except Exception as e:
        click.echo(f"✗ VAD stream processing failed: {e}", err=True)
        processor.stop_processing()
        sys.exit(1)


@cli.command()
@click.argument('url')
@click.option('--channel', '-c', help='Slack channel (e.g., #general)')
@click.option('--whisper-model', '-m', default='medium', help='Whisper model size')
@click.option('--language', '-l', help='Language code (auto-detect if not specified)')
@click.option('--include-timestamps', is_flag=True, help='Include timestamps in transcription')
@click.pass_context
def thread(ctx, url: str, channel: Optional[str], whisper_model: str,
          language: Optional[str], include_timestamps: bool):
    """Process a YouTube video and post to a Slack thread using Bot API."""
    
    # Check required environment variables
    bot_token = os.environ.get('SLACK_BOT_TOKEN')
    if not bot_token:
        click.echo("Error: SLACK_BOT_TOKEN environment variable is required", err=True)
        click.echo("Get this from your Slack app's OAuth & Permissions page", err=True)
        sys.exit(1)
    
    config: WorkflowConfig = ctx.obj['config']
    
    # Override config with CLI options
    if whisper_model != 'base':
        config.whisper_model = whisper_model
    if language:
        config.whisper_language = language
    if include_timestamps:
        config.include_timestamps = include_timestamps
    
    try:
        # Create bot client
        bot_client = SlackBotClient(bot_token=bot_token)
        
        # Get channel ID
        target_channel = channel or config.slack_channel
        if not target_channel:
            click.echo("Error: Channel is required. Use --channel or set in config", err=True)
            sys.exit(1)
        
        if not target_channel.startswith('#'):
            target_channel = f"#{target_channel}"
        
        channel_id = bot_client.get_channel_id(target_channel.lstrip('#'))
        if not channel_id:
            click.echo(f"Error: Channel {target_channel} not found", err=True)
            sys.exit(1)
        
        # Create workflow
        workflow = YouTube2SlackWorkflow(config)
        
        click.echo(f"🚀 Processing video: {url}")
        
        # Get video info
        video_info = workflow.downloader.get_info(url)
        video_title = video_info['title']
        duration = video_info.get('duration', 0)
        
        click.echo(f"📺 Title: {video_title}")
        
        # Create thread
        thread_info = bot_client.create_thread(
            channel=channel_id,
            video_title=video_title,
            video_url=url,
            duration=duration
        )
        
        click.echo(f"🧵 Created thread in {target_channel}")
        
        # Post processing status
        bot_client.post_to_thread(thread_info, "🔄 *Processing video...*")
        
        with click.progressbar(length=100, label='Processing video') as bar:
            def progress_callback(message: str):
                click.echo(f"  {message}")
                bot_client.post_to_thread(thread_info, f"⏳ {message}")
            
            result = workflow.process_video(url, progress_callback)
            bar.update(100)
        
        if result.success:
            # Post transcription to thread
            click.echo("📝 Posting transcription to thread...")
            bot_client.post_transcription_to_thread(
                thread_info,
                result.transcription_text,
                include_timestamps=config.include_timestamps
            )
            
            # Final status
            bot_client.post_to_thread(
                thread_info, 
                f"✅ *Processing complete!* Language detected: {result.language}"
            )
            
            click.echo(f"✅ Successfully processed and posted to thread!")
            
        else:
            # Post error to thread
            bot_client.post_error_to_thread(
                thread_info,
                result.error or "Unknown error occurred"
            )
            
            click.echo(f"❌ Processing failed: {result.error}")
            sys.exit(1)
            
    except SlackBotError as e:
        click.echo(f"❌ Slack error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--port', '-p', default=3000, help='Server port')
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
        
        # Create server
        server = create_slack_server(port=port)
        
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
  # For webhook mode (legacy)
  webhook_url: "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
  channel: null                      # Optional channel override (e.g., "#transcripts")
  include_timestamps: false          # Include timestamps in transcription
  send_errors_to_slack: true         # Send error notifications to Slack

# For Bot API mode (new thread functionality)
# Set these as environment variables:
# SLACK_BOT_TOKEN=xoxb-your-bot-token
# SLACK_APP_TOKEN=xapp-your-app-token (optional, for socket mode)
# SLACK_SIGNING_SECRET=your-signing-secret
# SLACK_DEFAULT_CHANNEL=general (optional)
'''
    
    config_path = 'config.yaml'
    
    if os.path.exists(config_path):
        if not click.confirm(f"Config file {config_path} exists. Overwrite?"):
            return
    
    with open(config_path, 'w') as f:
        f.write(config_content)
    
    click.echo(f"✓ Created config file: {config_path}")
    click.echo("Please edit the file and set environment variables for Slack Bot API.")


def main():
    """Main entry point."""
    cli()


if __name__ == '__main__':
    main()