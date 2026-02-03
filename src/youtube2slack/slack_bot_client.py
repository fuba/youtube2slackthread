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

from .user_cookie_manager import UserSettingsManager, UserCookieManager, CookieFileProcessor, WhisperService


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
                 cookie_manager: Optional[UserCookieManager] = None,
                 settings_manager: Optional[UserSettingsManager] = None):
        """Initialize Slack Bot client.
        
        Args:
            bot_token: Slack Bot User OAuth Token (starts with xoxb-)
            app_token: Slack App-Level Token for socket mode (starts with xapp-)
            default_channel: Default channel to post messages
            cookie_manager: User cookie manager instance (deprecated, use settings_manager)
            settings_manager: User settings manager instance
            
        Raises:
            SlackBotError: If tokens are invalid
        """
        if not bot_token or not bot_token.startswith('xoxb-'):
            raise SlackBotError("Invalid bot token. Must start with 'xoxb-'")
        
        self.bot_token = bot_token
        self.app_token = app_token
        self.default_channel = default_channel
        
        # Support both old cookie_manager and new settings_manager for compatibility
        self.settings_manager = settings_manager or cookie_manager or UserSettingsManager()
        self.cookie_manager = self.settings_manager  # Backward compatibility
        
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
                elif event_type == "message":
                    self._handle_dm_text_message(event)
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

    # === DM Text Message Handling ===
    
    def _handle_dm_text_message(self, event: Dict[str, Any]) -> None:
        """Handle DM text messages for settings commands."""
        try:
            channel_id = event.get("channel")
            user_id = event.get("user")
            text = event.get("text", "").strip()
            
            # Only process DMs (channel ID starts with 'D')
            if not channel_id or not channel_id.startswith('D'):
                return
            
            # Ignore bot messages and empty messages
            if event.get("bot_id") or not text or not user_id:
                return
            
            logger.info(f"Processing DM command from user {user_id}: '{text}'")
            
            # Parse and handle command
            self._process_dm_command(channel_id, user_id, text)
            
        except Exception as e:
            logger.error(f"Error handling DM text message: {e}")
    
    def _process_dm_command(self, channel_id: str, user_id: str, text: str) -> None:
        """Process DM command and send response."""
        try:
            # Split command and arguments
            parts = text.split(None, 1)
            command = parts[0].lower() if parts else ""
            args = parts[1] if len(parts) > 1 else ""
            
            # Handle different commands
            if command in ['/help', 'help', 'ヘルプ']:
                self._handle_help_command(channel_id)
            elif command in ['/show-settings', '/settings', '設定確認', '設定表示']:
                self._handle_show_settings_command(channel_id, user_id)
            elif command in ['/set-openai-key', 'set-openai-key']:
                self._handle_set_openai_key_command(channel_id, user_id, args)
            elif command in ['/set-whisper', 'set-whisper']:
                self._handle_set_whisper_command(channel_id, user_id, args)
            elif command in ['/set-model', 'set-model']:
                self._handle_set_model_command(channel_id, user_id, args)
            elif command in ['/web-settings', 'web-settings', 'ウェブ設定']:
                self._handle_web_settings_command(channel_id, user_id)
            else:
                # Unknown command
                self._send_dm_message(channel_id, 
                    "❓ **利用可能なコマンド**\n\n"
                    "• `/help` - このヘルプを表示\n"
                    "• `/show-settings` - 現在の設定を表示\n"
                    "• `/set-openai-key <API_KEY>` - OpenAI APIキーを設定\n"
                    "• `/set-whisper local|openai` - Whisperサービスを選択\n"
                    "• `/set-model <MODEL>` - ローカルWhisperモデルを設定\n"
                    "• `/web-settings` - Web設定ページのURLを取得\n\n"
                    "または直接cookies.txtファイルをアップロードしてください。"
                )
                
        except Exception as e:
            logger.error(f"Error processing DM command: {e}")
            self._send_dm_message(channel_id, f"❌ コマンド処理中にエラーが発生しました: {str(e)}")
    
    def _handle_help_command(self, channel_id: str) -> None:
        """Handle /help command."""
        help_text = """
🤖 **YouTube2SlackThread Bot ヘルプ**

**設定コマンド:**
• `/show-settings` - 現在の設定を表示
• `/set-openai-key <API_KEY>` - OpenAI APIキーを設定
• `/set-whisper local|openai` - Whisperサービスを選択
• `/set-model <MODEL>` - ローカルWhisperモデルを設定 (tiny/base/small/medium/large)
• `/web-settings` - Web設定ページのURLを取得

**ファイルアップロード:**
• cookies.txtファイルを直接送信してYouTubeCookiesを設定

**YouTube処理:**
• チャンネルで `/youtube2thread <URL>` を実行

**その他:**
• `/help` - このヘルプを表示

設定は暗号化されて安全に保存されます。
        """
        self._send_dm_message(channel_id, help_text.strip())
    
    def _handle_show_settings_command(self, channel_id: str, user_id: str) -> None:
        """Handle /show-settings command."""
        try:
            settings = self.settings_manager.get_settings(user_id)
            has_cookies = self.settings_manager.has_cookies(user_id)
            
            settings_text = f"""
⚙️ **現在の設定 (User: {user_id})**

**Whisperサービス:** {settings.whisper_service.value}
**OpenAI APIキー:** {'✅ 設定済み' if settings.openai_api_key else '❌ 未設定'}
**ローカルWhisperモデル:** {settings.whisper_model}
**言語設定:** {settings.whisper_language or '自動検出'}
**タイムスタンプ表示:** {'有効' if settings.include_timestamps else '無効'}
**YouTubeCookies:** {'✅ 設定済み' if has_cookies else '❌ 未設定'}

設定を変更するには対応するコマンドを使用してください。
`/help` でコマンド一覧を表示できます。
            """
            self._send_dm_message(channel_id, settings_text.strip())
            
        except Exception as e:
            logger.error(f"Error showing settings: {e}")
            self._send_dm_message(channel_id, f"❌ 設定の取得中にエラーが発生しました: {str(e)}")
    
    def _handle_set_openai_key_command(self, channel_id: str, user_id: str, api_key: str) -> None:
        """Handle /set-openai-key command."""
        try:
            if not api_key or not api_key.strip():
                self._send_dm_message(channel_id, 
                    "❌ APIキーが指定されていません。\n\n"
                    "使用方法: `/set-openai-key sk-...`"
                )
                return
            
            api_key = api_key.strip()
            
            # Basic validation
            if not api_key.startswith('sk-'):
                self._send_dm_message(channel_id, 
                    "⚠️ 無効なAPIキー形式です。OpenAI APIキーは 'sk-' で始まります。"
                )
                return
            
            # Store API key and automatically switch to OpenAI service
            self.settings_manager.update_openai_api_key(user_id, api_key)
            
            self._send_dm_message(channel_id, 
                "✅ **OpenAI APIキーが設定されました！**\n\n"
                "Whisperサービスが自動的にOpenAI APIに切り替わりました。\n"
                "設定確認: `/show-settings`"
            )
            
        except Exception as e:
            logger.error(f"Error setting OpenAI API key: {e}")
            self._send_dm_message(channel_id, f"❌ APIキーの設定中にエラーが発生しました: {str(e)}")
    
    def _handle_set_whisper_command(self, channel_id: str, user_id: str, service: str) -> None:
        """Handle /set-whisper command."""
        try:
            if not service or service.lower() not in ['local', 'openai']:
                self._send_dm_message(channel_id, 
                    "❌ 無効なサービスです。\n\n"
                    "使用方法: `/set-whisper local` または `/set-whisper openai`"
                )
                return
            
            service = service.lower()
            whisper_service = WhisperService.LOCAL if service == 'local' else WhisperService.OPENAI
            
            # Check local Whisper permissions when switching to local
            if whisper_service == WhisperService.LOCAL:
                # Check if local Whisper is allowed for this user via workflow config
                # Note: We can't access workflow_config here directly, but we'll check when the transcriber is created
                # For now, just warn if they're trying to set local without checking permissions
                pass
            
            # Check if OpenAI API key is available when switching to OpenAI
            if whisper_service == WhisperService.OPENAI:
                if not self.settings_manager.has_openai_api_key(user_id):
                    self._send_dm_message(channel_id, 
                        "⚠️ **OpenAI APIキーが設定されていません**\n\n"
                        "OpenAI Whisperを使用するには、まずAPIキーを設定してください:\n"
                        "`/set-openai-key sk-...`"
                    )
                    return
            
            self.settings_manager.update_whisper_service(user_id, whisper_service)
            
            service_name = "ローカルWhisper" if whisper_service == WhisperService.LOCAL else "OpenAI API"
            self._send_dm_message(channel_id, 
                f"✅ **Whisperサービスが {service_name} に変更されました！**\n\n"
                "設定確認: `/show-settings`\n\n"
                "※ローカルWhisperは管理者によって制限されている場合があります。"
            )
            
        except Exception as e:
            logger.error(f"Error setting Whisper service: {e}")
            self._send_dm_message(channel_id, f"❌ Whisperサービスの設定中にエラーが発生しました: {str(e)}")
    
    def _handle_set_model_command(self, channel_id: str, user_id: str, model: str) -> None:
        """Handle /set-model command."""
        try:
            if not model:
                self._send_dm_message(channel_id, 
                    "❌ モデル名が指定されていません。\n\n"
                    "使用方法: `/set-model <MODEL>`\n"
                    "利用可能: tiny, base, small, medium, large"
                )
                return
            
            model = model.lower().strip()
            valid_models = ['tiny', 'base', 'small', 'medium', 'large', 'large-v2', 'large-v3']
            
            if model not in valid_models:
                self._send_dm_message(channel_id, 
                    f"❌ 無効なモデル名: {model}\n\n"
                    f"利用可能なモデル: {', '.join(valid_models)}"
                )
                return
            
            self.settings_manager.update_whisper_model(user_id, model)
            
            self._send_dm_message(channel_id, 
                f"✅ **ローカルWhisperモデルが '{model}' に変更されました！**\n\n"
                "設定確認: `/show-settings`"
            )
            
        except Exception as e:
            logger.error(f"Error setting Whisper model: {e}")
            self._send_dm_message(channel_id, f"❌ モデルの設定中にエラーが発生しました: {str(e)}")
    
    def _handle_web_settings_command(self, channel_id: str, user_id: str) -> None:
        """Handle /web-settings command."""
        try:
            from .web_token_manager import WebTokenManager
            
            # Initialize token manager
            token_manager = WebTokenManager(
                db_path='web_tokens.db',
                token_lifetime_hours=1
            )
            
            # Generate secure access token
            access_token = token_manager.generate_token(user_id)
            
            # Get server configuration
            server_host = os.environ.get('WEB_UI_HOST', '127.0.0.1')
            server_port = int(os.environ.get('WEB_UI_PORT', '42390'))
            base_url = os.environ.get('WEB_UI_BASE_URL', f'http://{server_host}:{server_port}')
            
            # Generate secure URL
            settings_url = f"{base_url}/settings/{access_token.token}"
            
            # Format expiration time
            expires_in = access_token.expires_at.strftime('%Y-%m-%d %H:%M:%S')
            
            self._send_dm_message(channel_id, 
                f"🔒 **セキュア設定ページ**\n\n"
                f"以下のURLから設定を変更できます：\n"
                f"🔗 {settings_url}\n\n"
                f"**重要な注意事項：**\n"
                f"• 📅 有効期限: {expires_in}\n"
                f"• 🔒 このURLは一度使用すると無効になります\n"
                f"• 🚫 他の人と共有しないでください\n"
                f"• 💻 PCまたはモバイルブラウザでアクセス可能\n\n"
                f"設定を変更するには、URLをクリックしてブラウザで開いてください。"
            )
            
            logger.info(f"Generated web settings URL for user {user_id}, expires at {expires_in}")
            
        except Exception as e:
            logger.error(f"Error generating web settings URL: {e}")
            self._send_dm_message(channel_id, 
                "❌ **Web設定ページエラー**\n\n"
                "設定ページURLの生成中にエラーが発生しました。\n"
                "現在はDMコマンドで設定を変更してください。\n\n"
                "利用可能なコマンド: `/help`"
            )

    # === Backward Compatibility ===
    
    def send_direct_message(self, channel_id: str, message: str) -> bool:
        """Send direct message (alias for _send_dm_message for compatibility)."""
        return self._send_dm_message(channel_id, message)