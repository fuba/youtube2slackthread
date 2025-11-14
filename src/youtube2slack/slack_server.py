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
        
        # Start processing in background
        thread = threading.Thread(
            target=self._process_video_in_background,
            args=(text, channel_id, user_id, response_url)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'response_type': 'ephemeral',
            'text': f'🚀 Starting to process YouTube video: {text}\nI\'ll create a thread when ready!'
        })
    
    def _process_video_in_background(self, video_url: str, channel_id: str, 
                                   user_id: str, response_url: str) -> None:
        """Process video in background thread.
        
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


def create_slack_server(config_path: Optional[str] = None, port: int = 3000) -> SlackServer:
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