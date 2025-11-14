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

from .workflow import WorkflowConfig
from .slack_bot_client import SlackBotClient, ThreadInfo, SlackBotError
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
            
            # Get active threads count
            active_threads = len(self.active_threads)
            vad_stream_count = 0
            
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
                            "text": f"*Processing Streams:*\n{vad_stream_count}"
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
                        "text": "*🎬 Active Streams:*\nNo active streams"
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
            # Note: Stream stopping not implemented in VADStreamProcessor
            return jsonify({
                'response_type': 'ephemeral',
                'text': '⚠️ Stream stopping not yet implemented for this processor.'
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
        
        # Start VAD stream processing
        thread = threading.Thread(
            target=self._process_simple_vad_in_background,
            args=(text, channel_id, user_id, response_url)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'response_type': 'ephemeral',
            'text': f'🚀 Starting VAD stream processing: {text}\nI\'ll create a thread when ready!'
        })
    
    def _process_simple_vad_in_background(self, video_url: str, channel_id: str, 
                                        user_id: str, response_url: str) -> None:
        """VAD processing using VADStreamProcessor.
        
        Args:
            video_url: YouTube video/stream URL
            channel_id: Slack channel ID
            user_id: User ID who initiated the command
            response_url: Response URL for updates
        """
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
                cookies_file=self.workflow_config.youtube_cookies_file
            )
            
            # Create thread first
            import yt_dlp
            ydl_opts = {
                'quiet': True, 
                'no_warnings': True,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                }
            }
            
            # Add cookies if available
            if self.workflow_config.youtube_cookies_file and os.path.exists(self.workflow_config.youtube_cookies_file):
                ydl_opts['cookiefile'] = self.workflow_config.youtube_cookies_file
                logger.info(f"Using cookies for video info: {self.workflow_config.youtube_cookies_file}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
                video_title = info.get('title', 'Unknown Stream')
            
            thread_info = self.bot_client.create_thread(
                channel=channel_id,
                video_title=video_title,
                video_url=video_url,
                duration=None
            )
            
            logger.info(f"VAD processing started for {video_url} in thread {thread_info.thread_ts}")
            
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
            logger.error(f"VAD processing error: {e}")
            try:
                self.bot_client.send_direct_message(
                    channel_id, 
                    f"❌ *VAD処理エラー*\n{str(e)}"
                )
            except Exception:
                pass

    
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