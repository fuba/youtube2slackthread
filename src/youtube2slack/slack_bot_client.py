"""Slack Bot API integration with thread support."""

import json
import time
import logging
import tempfile
import requests
from typing import Dict, List, Optional, Any, Union, Callable
from dataclasses import dataclass

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

from .user_cookie_manager import UserCookieManager, CookieFileProcessor


logger = logging.getLogger(__name__)


class SlackBotError(Exception):
    """Exception raised for Slack Bot API failures."""
    pass


@dataclass
class ThreadInfo:
    """Information about a Slack thread."""
    channel: str
    thread_ts: str
    initial_message: Optional[str] = None


def split_text_for_slack(text: str, max_length: int = 3000) -> List[str]:
    """Split text into chunks suitable for Slack messages.
    
    Args:
        text: Text to split
        max_length: Maximum length per chunk
        
    Returns:
        List of text chunks
    """
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    current_chunk = ""
    
    # Split by sentences first
    import re
    sentences = re.split(r'(?<=[.!?。！？])\s*', text)
    
    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 <= max_length:
            if current_chunk:
                current_chunk += " "
            current_chunk += sentence
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            
            # If a single sentence is too long, split by words
            if len(sentence) > max_length:
                words = sentence.split()
                current_chunk = ""
                for word in words:
                    if len(current_chunk) + len(word) + 1 <= max_length:
                        if current_chunk:
                            current_chunk += " "
                        current_chunk += word
                    else:
                        if current_chunk:
                            chunks.append(current_chunk.strip())
                        current_chunk = word
            else:
                current_chunk = sentence
    
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    return chunks


def format_video_header_blocks(title: str, url: str, duration: Optional[int] = None,
                               language: Optional[str] = None) -> List[Dict[str, Any]]:
    """Format video header as Slack blocks.
    
    Args:
        title: Video title
        url: Video URL
        duration: Video duration in seconds
        language: Video language
        
    Returns:
        List of Slack block elements
    """
    blocks = []
    
    # Header with video title
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"🎥 {title}",
            "emoji": True
        }
    })
    
    # Metadata context
    metadata_elements = []
    
    if language:
        metadata_elements.append({
            "type": "mrkdwn",
            "text": f"*Language:* {language}"
        })
    
    if duration:
        hours = duration // 3600
        minutes = (duration % 3600) // 60
        seconds = duration % 60
        duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        metadata_elements.append({
            "type": "mrkdwn",
            "text": f"*Duration:* {duration_str}"
        })
    
    if metadata_elements:
        blocks.append({
            "type": "context",
            "elements": metadata_elements
        })
    
    # Video link
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"<{url}|View on YouTube>"
        }
    })
    
    blocks.append({"type": "divider"})
    
    return blocks


class SlackBotClient:
    """Slack Bot client with thread support and file handling."""
    
    def __init__(self, bot_token: str, app_token: Optional[str] = None,
                 default_channel: Optional[str] = None,
                 cookie_manager: Optional[UserCookieManager] = None):
        """Initialize Slack Bot client.
        
        Args:
            bot_token: Slack Bot User OAuth Token (starts with xoxb-)
            app_token: Slack App-Level Token for socket mode (starts with xapp-)
            default_channel: Default channel to post messages
            cookie_manager: User cookie manager instance
            
        Raises:
            SlackBotError: If tokens are invalid
        """
        if not bot_token or not bot_token.startswith('xoxb-'):
            raise SlackBotError("Invalid bot token. Must start with 'xoxb-'")
        
        self.bot_token = bot_token
        self.app_token = app_token
        self.default_channel = default_channel
        self.cookie_manager = cookie_manager
        
        # File event handlers
        self.file_handlers: Dict[str, Callable] = {}
        
        # Initialize web client
        self.web_client = WebClient(token=bot_token)
        
        # Initialize socket mode client if app token provided
        self.socket_client = None
        if app_token:
            if not app_token.startswith('xapp-'):
                raise SlackBotError("Invalid app token. Must start with 'xapp-'")
            self.socket_client = SocketModeClient(
                app_token=app_token,
                web_client=self.web_client
            )
        
        # Test the connection
        try:
            auth_result = self.web_client.auth_test()
            logger.info(f"Connected to Slack as {auth_result['user']}")
        except SlackApiError as e:
            raise SlackBotError(f"Failed to authenticate with Slack: {e.response['error']}")
    
    def create_thread(self, channel: str, video_title: str, video_url: str,
                     duration: Optional[int] = None, language: Optional[str] = None) -> ThreadInfo:
        """Create a new thread for a video.
        
        Args:
            channel: Channel to post in
            video_title: Video title
            video_url: Video URL
            duration: Video duration in seconds
            language: Video language
            
        Returns:
            ThreadInfo with thread details
            
        Raises:
            SlackBotError: If thread creation fails
        """
        try:
            # Format header blocks
            blocks = format_video_header_blocks(video_title, video_url, duration, language)
            
            # Post initial message
            result = self.web_client.chat_postMessage(
                channel=channel,
                text=f"🎥 {video_title}",
                blocks=blocks
            )
            
            thread_info = ThreadInfo(
                channel=channel,
                thread_ts=result['ts'],
                initial_message=video_title
            )
            
            logger.info(f"Created thread in {channel}: {video_title}")
            return thread_info
            
        except SlackApiError as e:
            raise SlackBotError(f"Failed to create thread: {e.response['error']}")
    
    def post_to_thread(self, thread_info: ThreadInfo, text: str,
                      blocks: Optional[List[Dict[str, Any]]] = None) -> bool:
        """Post a message to an existing thread.
        
        Args:
            thread_info: Thread information
            text: Message text (fallback)
            blocks: Optional Slack blocks
            
        Returns:
            True if successful
            
        Raises:
            SlackBotError: If posting fails
        """
        try:
            self.web_client.chat_postMessage(
                channel=thread_info.channel,
                thread_ts=thread_info.thread_ts,
                text=text,
                blocks=blocks
            )
            return True
            
        except SlackApiError as e:
            raise SlackBotError(f"Failed to post to thread: {e.response['error']}")
    
    def post_transcription_to_thread(self, thread_info: ThreadInfo, transcription_text: str,
                                   include_timestamps: bool = False,
                                   segments: Optional[List[Dict[str, Any]]] = None) -> bool:
        """Post transcription text to a thread, split into multiple messages if needed.
        
        Args:
            thread_info: Thread information
            transcription_text: Full transcription text
            include_timestamps: Whether to include timestamps
            segments: Optional segments with timestamps
            
        Returns:
            True if successful
            
        Raises:
            SlackBotError: If posting fails
        """
        try:
            if include_timestamps and segments:
                # Post with timestamps
                self.post_to_thread(thread_info, "*Transcription with timestamps:*")
                
                current_text = ""
                for segment in segments:
                    timestamp = segment.get('start_formatted', '00:00:00')
                    text = segment.get('text', '').strip()
                    
                    if text:
                        line = f"`{timestamp}` {text}"
                        
                        # Check if adding this line would exceed the limit
                        if len(current_text) + len(line) + 2 > 3000:  # +2 for newlines
                            if current_text:
                                self.post_to_thread(thread_info, current_text)
                                time.sleep(0.5)  # Rate limit protection
                            current_text = line
                        else:
                            if current_text:
                                current_text += "\n"
                            current_text += line
                
                # Post remaining text
                if current_text:
                    self.post_to_thread(thread_info, current_text)
                    
            else:
                # Post without timestamps
                self.post_to_thread(thread_info, "*Transcription:*")
                
                # Split long transcription into chunks
                chunks = split_text_for_slack(transcription_text)
                
                for i, chunk in enumerate(chunks):
                    self.post_to_thread(thread_info, chunk)
                    
                    # Rate limit protection between chunks
                    if i < len(chunks) - 1:
                        time.sleep(0.5)
            
            return True
            
        except SlackBotError:
            raise
        except Exception as e:
            raise SlackBotError(f"Failed to post transcription: {e}")
    
    def post_error_to_thread(self, thread_info: ThreadInfo, error_message: str,
                           context: Optional[Dict[str, Any]] = None) -> bool:
        """Post an error message to a thread.
        
        Args:
            thread_info: Thread information
            error_message: Error message
            context: Optional context information
            
        Returns:
            True if successful
        """
        try:
            blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"❌ *Error:* {error_message}"
                    }
                }
            ]
            
            if context:
                context_text = "\n".join([f"*{k}:* {v}" for k, v in context.items()])
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Details:*\n{context_text}"
                    }
                })
            
            return self.post_to_thread(thread_info, f"❌ Error: {error_message}", blocks)
            
        except SlackBotError:
            raise
        except Exception as e:
            raise SlackBotError(f"Failed to post error: {e}")
    
    def setup_slash_command_handler(self, command_handler: callable) -> None:
        """Setup slash command handler using Socket Mode.
        
        Args:
            command_handler: Function to handle slash commands
                           Should accept (command, channel, user_id, text) and return response
        """
        if not self.socket_client:
            raise SlackBotError("Socket Mode not available. App token required.")
        
        @self.socket_client.socket_mode_request_listeners.append
        def handle_slash_commands(client: SocketModeClient, req: SocketModeRequest):
            if req.type == "slash_commands":
                try:
                    # Extract command details
                    payload = req.payload
                    command = payload.get('command')
                    channel = payload.get('channel_id')
                    user_id = payload.get('user_id')
                    text = payload.get('text', '')
                    
                    # Call the handler
                    response_text = command_handler(command, channel, user_id, text)
                    
                    # Acknowledge the command
                    response = SocketModeResponse(envelope_id=req.envelope_id)
                    client.send_socket_mode_response(response)
                    
                    # Send response if provided
                    if response_text:
                        self.web_client.chat_postEphemeral(
                            channel=channel,
                            user=user_id,
                            text=response_text
                        )
                        
                except Exception as e:
                    logger.error(f"Error handling slash command: {e}")
                    response = SocketModeResponse(envelope_id=req.envelope_id)
                    client.send_socket_mode_response(response)
    
    def start_socket_mode(self) -> None:
        """Start Socket Mode client for real-time events."""
        if not self.socket_client:
            raise SlackBotError("Socket Mode not available. App token required.")
        
        logger.info("Starting Socket Mode client...")
        # Connect and start listening
        self.socket_client.connect()
        logger.info("Socket Mode client connected and listening for events")
        
    def stop_socket_mode(self) -> None:
        """Stop Socket Mode client."""
        if self.socket_client:
            self.socket_client.disconnect()
    
    def _handle_socket_mode_events(self, client: SocketModeClient, req: SocketModeRequest):
        """Internal handler for socket mode events."""
        try:
            logger.info(f"Received Socket Mode event: type={req.type}")
            
            if req.type == "events_api":
                event = req.payload.get("event", {})
                event_type = event.get("type")
                logger.info(f"Events API event: {event_type}")
                
                if event_type == "file_shared":
                    self._handle_file_shared_event(event)
                elif event_type == "message" and event.get("files"):
                    self._handle_message_with_files(event)
            elif req.type == "slash_commands":
                logger.info(f"Slash command received: {req.payload}")
                # This will be handled by the setup_slash_command_handler method
            
        except Exception as e:
            logger.error(f"Error handling socket mode event: {e}")
        finally:
            # Always acknowledge events
            response = SocketModeResponse(envelope_id=req.envelope_id)
            client.send_socket_mode_response(response)
    
    def _handle_file_shared_event(self, event: Dict[str, Any]) -> None:
        """Handle file_shared event for cookies.txt uploads."""
        try:
            file_id = event.get("file_id")
            user_id = event.get("user_id")
            channel_id = event.get("channel_id")
            
            if not all([file_id, user_id, channel_id]):
                logger.warning("Missing required fields in file_shared event")
                return
            
            # Check if it's a DM (channel ID starts with 'D')
            if not channel_id.startswith('D'):
                logger.info(f"File shared in non-DM channel {channel_id}, ignoring")
                return
            
            # Get file information
            file_info = self._get_file_info(file_id)
            if not file_info:
                return
            
            # Process the file if it's a cookies file
            self._process_uploaded_file(file_info, user_id, channel_id)
            
        except Exception as e:
            logger.error(f"Error handling file_shared event: {e}")
    
    def _handle_message_with_files(self, event: Dict[str, Any]) -> None:
        """Handle message events that contain file attachments."""
        try:
            files = event.get("files", [])
            user_id = event.get("user")
            channel_id = event.get("channel")
            
            if not channel_id.startswith('D'):
                return  # Only process DM files
            
            for file_data in files:
                self._process_uploaded_file(file_data, user_id, channel_id)
                
        except Exception as e:
            logger.error(f"Error handling message with files: {e}")
    
    def _get_file_info(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed file information from Slack."""
        try:
            response = self.web_client.files_info(file=file_id)
            if response.get("ok"):
                return response.get("file")
            else:
                logger.error(f"Failed to get file info: {response.get('error')}")
                return None
                
        except SlackApiError as e:
            logger.error(f"API error getting file info: {e.response['error']}")
            return None
    
    def _process_uploaded_file(self, file_info: Dict[str, Any], user_id: str, channel_id: str) -> None:
        """Process uploaded file for cookies management."""
        try:
            filename = file_info.get("name", "").lower()
            filetype = file_info.get("filetype", "").lower()
            mimetype = file_info.get("mimetype", "")
            
            # Check if it's a cookies file
            is_cookies_file = (
                "cookies" in filename or 
                filename.endswith(".txt") or
                filetype == "text" or
                "text/plain" in mimetype
            )
            
            if not is_cookies_file:
                self._send_dm_message(
                    channel_id,
                    "このファイルはサポートされていません。cookies.txtファイルをアップロードしてください。"
                )
                return
            
            # Download and validate the file
            file_content = self._download_file_content(file_info)
            if not file_content:
                self._send_dm_message(
                    channel_id,
                    "ファイルのダウンロードに失敗しました。"
                )
                return
            
            # Validate cookies format
            if not CookieFileProcessor.validate_cookies_file(file_content):
                self._send_dm_message(
                    channel_id,
                    "無効なcookiesファイル形式です。Netscape HTTP Cookieファイル形式のcookies.txtをアップロードしてください。"
                )
                return
            
            # Process and store cookies
            if self.cookie_manager:
                # Extract only YouTube-related cookies for security
                youtube_cookies = CookieFileProcessor.extract_youtube_cookies(file_content)
                
                self.cookie_manager.store_cookies(user_id, youtube_cookies)
                
                self._send_dm_message(
                    channel_id,
                    "✅ Cookiesが正常に保存されました！これで YouTube動画の処理で あなた専用のcookiesが使用されます。"
                )
                
                logger.info(f"Successfully stored cookies for user {user_id}")
            else:
                self._send_dm_message(
                    channel_id,
                    "Cookie管理システムが利用できません。"
                )
                
        except Exception as e:
            logger.error(f"Error processing uploaded file: {e}")
            self._send_dm_message(
                channel_id,
                f"ファイル処理中にエラーが発生しました: {str(e)}"
            )
    
    def _download_file_content(self, file_info: Dict[str, Any]) -> Optional[str]:
        """Download file content from Slack."""
        try:
            download_url = file_info.get("url_private_download")
            if not download_url:
                logger.error("No download URL available for file")
                return None
            
            headers = {
                "Authorization": f"Bearer {self.bot_token}"
            }
            
            response = requests.get(download_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            # Try to decode as UTF-8
            try:
                content = response.content.decode('utf-8')
            except UnicodeDecodeError:
                # Try other encodings
                for encoding in ['utf-8-sig', 'iso-8859-1', 'cp1252']:
                    try:
                        content = response.content.decode(encoding)
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    logger.error("Could not decode file content")
                    return None
            
            return content
            
        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            return None
    
    def _send_dm_message(self, channel_id: str, message: str) -> bool:
        """Send a direct message to a user."""
        try:
            self.web_client.chat_postMessage(
                channel=channel_id,
                text=message
            )
            return True
            
        except SlackApiError as e:
            logger.error(f"Failed to send DM: {e.response['error']}")
            return False
    
    def setup_file_handler(self, file_type: str, handler: Callable) -> None:
        """Setup custom file type handler.
        
        Args:
            file_type: File type to handle (e.g., 'cookies', 'audio')
            handler: Function to handle the file
        """
        self.file_handlers[file_type] = handler
    
    def get_channel_id(self, channel_name: str) -> Optional[str]:
        """Get channel ID from channel name.
        
        Args:
            channel_name: Channel name (with or without #)
            
        Returns:
            Channel ID or None if not found
        """
        try:
            # Remove # if present
            channel_name = channel_name.lstrip('#')
            
            # Get list of channels
            response = self.web_client.conversations_list(types="public_channel,private_channel")
            
            for channel in response['channels']:
                if channel['name'] == channel_name:
                    return channel['id']
            
            return None
            
        except SlackApiError as e:
            logger.error(f"Failed to get channel ID: {e.response['error']}")
            return None