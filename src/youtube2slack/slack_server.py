"""Flask server for handling Slack slash commands via webhooks."""

import os
import json
import logging
from typing import Dict, Any, Optional
import threading
import time
from urllib.parse import parse_qs

from flask import Flask, request, jsonify
from slack_sdk.signature import SignatureVerifier

from .workflow import YouTube2SlackWorkflow, WorkflowConfig
from .slack_bot_client import SlackBotClient, ThreadInfo, SlackBotError
from .vad_thread_processor import VADThreadProcessor, VADThreadProcessingError
from .whisper_transcriber import WhisperTranscriber


logger = logging.getLogger(__name__)


class SlackServer:
    """Flask server for handling Slack interactions."""
    
    def __init__(self, bot_client: SlackBotClient, workflow_config: WorkflowConfig,
                 signing_secret: str, port: int = 3000):
        """Initialize Slack server.
        
        Args:
            bot_client: Slack Bot client
            workflow_config: Workflow configuration
            signing_secret: Slack app signing secret
            port: Server port
        """
        self.bot_client = bot_client
        self.workflow_config = workflow_config
        self.signature_verifier = SignatureVerifier(signing_secret)
        self.port = port
        
        # Setup Flask app
        self.app = Flask(__name__)
        self.setup_routes()
        
        # Track ongoing processing
        self.active_threads: Dict[str, ThreadInfo] = {}
        
    def setup_routes(self):
        """Setup Flask routes."""
        
        @self.app.route('/slack/commands', methods=['POST'])
        def handle_slash_command():
            return self._handle_slash_command()
        
        @self.app.route('/health', methods=['GET'])
        def health_check():
            return jsonify({'status': 'healthy', 'service': 'youtube2slackthread'})
    
    def _verify_request(self) -> bool:
        """Verify Slack request signature.
        
        Returns:
            True if signature is valid
        """
        try:
            timestamp = request.headers.get('X-Slack-Request-Timestamp', '')
            signature = request.headers.get('X-Slack-Signature', '')
            body = request.get_data()
            
            return self.signature_verifier.is_valid(
                timestamp=timestamp,
                signature=signature,
                body=body
            )
        except Exception as e:
            logger.error(f"Error verifying signature: {e}")
            return False
    
    def _handle_slash_command(self) -> Dict[str, Any]:
        """Handle incoming slash command.
        
        Returns:
            JSON response for Slack
        """
        # Verify signature
        if not self._verify_request():
            logger.warning("Invalid request signature")
            return jsonify({'text': 'Invalid request signature'}), 401
        
        try:
            # Parse form data
            form_data = request.form
            command = form_data.get('command')
            text = form_data.get('text', '').strip()
            channel_id = form_data.get('channel_id')
            user_id = form_data.get('user_id')
            response_url = form_data.get('response_url')
            
            logger.info(f"Received command: {command} from user {user_id} in channel {channel_id}")
            
            # Handle different commands
            if command == '/youtube2thread':
                return self._handle_youtube_command(text, channel_id, user_id, response_url)
            elif command == '/youtube2thread-status':
                return self._handle_status_command(channel_id, user_id)
            elif command == '/youtube2thread-stop':
                return self._handle_stop_command(text, channel_id, user_id)
            else:
                return jsonify({
                    'response_type': 'ephemeral',
                    'text': f'Unknown command: {command}'
                })
                
        except Exception as e:
            logger.error(f"Error handling slash command: {e}")
            return jsonify({
                'response_type': 'ephemeral',
                'text': f'Error processing command: {e}'
            }), 500
    
    def _handle_status_command(self, channel_id: str, user_id: str) -> Dict[str, Any]:
        """Handle /youtube2thread-status command for system diagnostics.
        
        Args:
            channel_id: Channel ID
            user_id: User ID
            
        Returns:
            JSON response with status information
        """
        import platform
        import pkg_resources
        import datetime
        
        try:
            # Get system information
            python_version = platform.python_version()
            system_info = f"{platform.system()} {platform.release()}"
            
            # Get package versions
            packages = {
                'slack-sdk': 'Unknown',
                'flask': 'Unknown',
                'yt-dlp': 'Unknown',
                'openai-whisper': 'Unknown'
            }
            
            for package_name in packages:
                try:
                    packages[package_name] = pkg_resources.get_distribution(package_name).version
                except:
                    pass
            
            # Get active threads count and VAD streams
            active_threads = len(self.active_threads)
            active_vad_streams = VADThreadProcessor.get_active_streams()
            vad_stream_count = len(active_vad_streams)
            
            # Get bot info
            bot_info = "Unknown"
            try:
                auth_result = self.bot_client.web_client.auth_test()
                bot_info = f"{auth_result.get('user', 'Unknown')} ({auth_result.get('user_id', 'Unknown')})"
            except:
                pass
            
            # Format response
            status_blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "🔧 YouTube2SlackThread Status",
                        "emoji": True
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Server Time:*\n{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*System:*\n{system_info}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Python:*\nv{python_version}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Active Threads:*\n{active_threads}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*VAD Streams:*\n{vad_stream_count}"
                        }
                    ]
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*📦 Package Versions:*"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*slack-sdk:*\nv{packages['slack-sdk']}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*flask:*\nv{packages['flask']}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*yt-dlp:*\nv{packages['yt-dlp']}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*whisper:*\nv{packages['openai-whisper']}"
                        }
                    ]
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*🤖 Bot Configuration:*"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Bot User:*\n{bot_info}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Default Channel:*\n{self.bot_client.default_channel or 'Not set'}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Server Port:*\n{self.port}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Webhook URL:*\nhttps://your-domain.com:{self.port}/slack/commands"
                        }
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*🎬 Active VAD Streams:*"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "\n".join([
                            f"• *{info['title'][:50]}{'...' if len(info['title']) > 50 else ''}* (ID: {stream_id})"
                            for stream_id, info in active_vad_streams.items()
                        ]) if active_vad_streams else "No active VAD streams"
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "✅ *Status:* All systems operational"
                        }
                    ]
                }
            ]
            
            return jsonify({
                'response_type': 'ephemeral',
                'blocks': status_blocks
            })
            
        except Exception as e:
            logger.error(f"Error generating status: {e}")
            return jsonify({
                'response_type': 'ephemeral',
                'text': f'❌ Error generating status: {str(e)}'
            })
    
    def _handle_stop_command(self, text: str, channel_id: str, user_id: str) -> Dict[str, Any]:
        """Handle /youtube2thread-stop command.
        
        Args:
            text: Command text (optional stream ID)
            channel_id: Channel ID
            user_id: User ID
            
        Returns:
            JSON response
        """
        try:
            active_streams = VADThreadProcessor.get_active_streams()
            
            if not active_streams:
                return jsonify({
                    'response_type': 'ephemeral',
                    'text': 'No active streams to stop.'
                })
            
            # If specific stream ID provided, stop that one
            if text.strip():
                stream_id = text.strip()
                if VADThreadProcessor.stop_stream_by_id(stream_id):
                    return jsonify({
                        'response_type': 'ephemeral',
                        'text': f'🛑 Stopped stream: {stream_id}'
                    })
                else:
                    return jsonify({
                        'response_type': 'ephemeral',
                        'text': f'Stream not found: {stream_id}'
                    })
            else:
                # No specific ID - show list and stop all if user confirms
                if len(active_streams) == 1:
                    stream_id = list(active_streams.keys())[0]
                    VADThreadProcessor.stop_stream_by_id(stream_id)
                    stream_info = list(active_streams.values())[0]
                    return jsonify({
                        'response_type': 'ephemeral',
                        'text': f'🛑 Stopped stream: {stream_info["title"]}'
                    })
                else:
                    # Multiple streams - stop all
                    stopped_count = VADThreadProcessor.stop_all_streams()
                    return jsonify({
                        'response_type': 'ephemeral',
                        'text': f'🛑 Stopped {stopped_count} active streams.'
                    })
                    
        except Exception as e:
            logger.error(f"Error stopping streams: {e}")
            return jsonify({
                'response_type': 'ephemeral',
                'text': f'❌ Error stopping streams: {str(e)}'
            })
    
    def _handle_youtube_command(self, text: str, channel_id: str, user_id: str, 
                               response_url: str) -> Dict[str, Any]:
        """Handle /youtube2thread command.
        
        Args:
            text: Command text (YouTube URL)
            channel_id: Channel ID
            user_id: User ID
            response_url: Response URL for delayed responses
            
        Returns:
            JSON response
        """
        if not text:
            return jsonify({
                'response_type': 'ephemeral',
                'text': 'Please provide a YouTube URL. Usage: `/youtube2thread https://youtube.com/watch?v=...`'
            })
        
        # Validate YouTube URL
        import re
        youtube_pattern = r'(youtube\.com|youtu\.be)'
        if not re.search(youtube_pattern, text):
            return jsonify({
                'response_type': 'ephemeral',
                'text': 'Please provide a valid YouTube URL.'
            })
        
        # TESTING: Use simpler VAD stream processing
        thread = threading.Thread(
            target=self._process_simple_vad_in_background,
            args=(text, channel_id, user_id, response_url)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'response_type': 'ephemeral',
            'text': f'🚀 Starting simple VAD stream processing: {text}\nI\'ll create a thread when ready!'
        })
    
    def _process_vad_stream_in_background(self, video_url: str, channel_id: str, 
                                        user_id: str, response_url: str) -> None:
        """Process video/stream with VAD in background thread.
        
        Args:
            video_url: YouTube video/stream URL
            channel_id: Slack channel ID
            user_id: User ID who initiated the command
            response_url: Response URL for updates
        """
        try:
            # Create transcriber
            transcriber = WhisperTranscriber(
                model_name=self.workflow_config.whisper_model,
                device=self.workflow_config.whisper_device
            )
            
            # Create VAD processor
            vad_processor = VADThreadProcessor(
                transcriber=transcriber,
                slack_bot_client=self.bot_client,
                vad_aggressiveness=2
            )
            
            # Define progress callback
            def progress_callback(message: str):
                logger.info(f"VAD Progress: {message}")
            
            # Start VAD stream processing
            thread_info = vad_processor.start_stream_processing(
                video_url, 
                channel_id, 
                progress_callback
            )
            
            logger.info(f"VAD processing started for {video_url} in thread {thread_info.thread_ts}")
            
        except VADThreadProcessingError as e:
            logger.error(f"VAD processing error: {e}")
            try:
                self.bot_client.send_direct_message(
                    channel_id, 
                    f"❌ *VAD処理エラー*\n{str(e)}"
                )
            except Exception:
                pass
                
        except SlackBotError as e:
            logger.error(f"Slack error during processing: {e}")
            
        except Exception as e:
            logger.error(f"Unexpected error during processing: {e}")
            try:
                self.bot_client.send_direct_message(
                    channel_id, 
                    f"❌ *予期しないエラー*\n{str(e)}"
                )
            except Exception:
                pass

    def _process_simple_vad_in_background(self, video_url: str, channel_id: str, 
                                        user_id: str, response_url: str) -> None:
        """Simple VAD processing using existing VADStreamProcessor."""
        try:
            from .vad_stream_processor import VADStreamProcessor
            
            # Create transcriber
            transcriber = WhisperTranscriber(
                model_name=self.workflow_config.whisper_model,
                device=self.workflow_config.whisper_device
            )
            
            # Create VAD processor (existing working implementation)
            vad_processor = VADStreamProcessor(
                transcriber=transcriber,
                slack_client=None  # We'll handle Slack posting ourselves
            )
            
            # Create thread first
            import yt_dlp
            ydl_opts = {'quiet': True, 'no_warnings': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
                video_title = info.get('title', 'Unknown Stream')
            
            thread_info = self.bot_client.create_thread(
                channel=channel_id,
                video_title=video_title,
                video_url=video_url,
                duration=None
            )
            
            logger.info(f"Simple VAD processing started for {video_url} in thread {thread_info.thread_ts}")
            
            # Start processing with callback to post to our thread
            def progress_callback(message: str):
                # Filter out progress messages - only post actual transcription content
                if (message.strip() and 
                    not message.startswith("Processing speech segment") and
                    not message.startswith("Processing continuous audio stream") and
                    not message.startswith("Starting VAD stream")):
                    try:
                        self.bot_client.post_to_thread(thread_info, message)
                        logger.info(f"Posted to thread: {message[:50]}...")
                    except Exception as e:
                        logger.error(f"Failed to post to thread: {e}")
            
            vad_processor.start_stream_processing(video_url, progress_callback)
            
        except Exception as e:
            logger.error(f"Simple VAD processing error: {e}")
            try:
                self.bot_client.send_direct_message(
                    channel_id, 
                    f"❌ *Simple VAD処理エラー*\n{str(e)}"
                )
            except Exception:
                pass

    def _process_video_in_background(self, video_url: str, channel_id: str, 
                                   user_id: str, response_url: str) -> None:
        """Process video in background thread (legacy method for non-VAD processing).
        
        Args:
            video_url: YouTube video URL
            channel_id: Slack channel ID
            user_id: User ID who initiated the command
            response_url: Response URL for updates
        """
        thread_info = None
        
        try:
            # Create workflow
            workflow = YouTube2SlackWorkflow(self.workflow_config)
            
            # Get video info first for thread creation
            video_info = workflow.downloader.get_info(video_url)
            video_title = video_info['title']
            duration = video_info.get('duration', 0)
            
            # Create thread
            thread_info = self.bot_client.create_thread(
                channel=channel_id,
                video_title=video_title,
                video_url=video_url,
                duration=duration
            )
            
            # Track thread
            thread_key = f"{channel_id}:{video_url}"
            self.active_threads[thread_key] = thread_info
            
            # Post processing status
            self.bot_client.post_to_thread(thread_info, "🔄 *Processing video...*")
            
            def progress_callback(message: str):
                """Update progress in thread."""
                self.bot_client.post_to_thread(thread_info, f"⏳ {message}")
                logger.info(f"Progress: {message}")
            
            # Process video
            result = workflow.process_video(video_url, progress_callback)
            
            if result.success:
                # Post transcription to thread
                self.bot_client.post_transcription_to_thread(
                    thread_info,
                    result.transcription_text,
                    include_timestamps=self.workflow_config.include_timestamps
                )
                
                # Final status
                self.bot_client.post_to_thread(
                    thread_info, 
                    f"✅ *Processing complete!* Language detected: {result.language}"
                )
                
                logger.info(f"Successfully processed video: {video_title}")
                
            else:
                # Post error to thread
                self.bot_client.post_error_to_thread(
                    thread_info,
                    result.error or "Unknown error occurred",
                    context={
                        'video_url': video_url,
                        'video_title': video_title
                    }
                )
                
                logger.error(f"Failed to process video: {result.error}")
                
        except SlackBotError as e:
            logger.error(f"Slack error during processing: {e}")
            if thread_info:
                try:
                    self.bot_client.post_error_to_thread(thread_info, str(e))
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"Unexpected error during processing: {e}")
            if thread_info:
                try:
                    self.bot_client.post_error_to_thread(
                        thread_info, 
                        f"Unexpected error: {e}"
                    )
                except:
                    pass
        
        finally:
            # Cleanup thread tracking
            thread_key = f"{channel_id}:{video_url}"
            if thread_key in self.active_threads:
                del self.active_threads[thread_key]
    
    def run(self, debug: bool = False) -> None:
        """Run the Flask server.
        
        Args:
            debug: Enable debug mode
        """
        logger.info(f"Starting Slack server on port {self.port}")
        self.app.run(host='0.0.0.0', port=self.port, debug=debug)
    
    def get_active_threads(self) -> Dict[str, ThreadInfo]:
        """Get currently active threads.
        
        Returns:
            Dictionary of active threads
        """
        return self.active_threads.copy()


def create_slack_server(config_path: Optional[str] = None, port: int = 42389) -> SlackServer:
    """Create and configure Slack server.
    
    Args:
        config_path: Path to configuration file
        port: Server port
        
    Returns:
        Configured SlackServer instance
        
    Raises:
        ValueError: If required configuration is missing
    """
    # Load workflow config
    if config_path:
        workflow_config = WorkflowConfig.from_yaml(config_path)
    else:
        workflow_config = WorkflowConfig()
    
    # Get Slack configuration from environment
    bot_token = os.environ.get('SLACK_BOT_TOKEN')
    app_token = os.environ.get('SLACK_APP_TOKEN')
    signing_secret = os.environ.get('SLACK_SIGNING_SECRET')
    default_channel = os.environ.get('SLACK_DEFAULT_CHANNEL')
    
    if not bot_token:
        raise ValueError("SLACK_BOT_TOKEN environment variable is required")
    if not signing_secret:
        raise ValueError("SLACK_SIGNING_SECRET environment variable is required")
    
    # Create bot client
    bot_client = SlackBotClient(
        bot_token=bot_token,
        app_token=app_token,
        default_channel=default_channel
    )
    
    # Create server
    return SlackServer(
        bot_client=bot_client,
        workflow_config=workflow_config,
        signing_secret=signing_secret,
        port=port
    )