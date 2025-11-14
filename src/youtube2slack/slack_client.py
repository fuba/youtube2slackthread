"""Slack integration module."""

import json
import time
import re
from typing import Dict, List, Optional, Any
import logging

import requests
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


logger = logging.getLogger(__name__)


class SlackError(Exception):
    """Exception raised for Slack-related failures."""
    pass


def format_transcription_message(data: Dict[str, Any], include_timestamps: bool = False) -> List[Dict[str, Any]]:
    """Format transcription data into Slack blocks.
    
    Args:
        data: Transcription data with video information
        include_timestamps: Whether to include timestamp information
        
    Returns:
        List of Slack block elements
    """
    blocks = []
    
    # Header with video title
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"🎥 {data.get('video_title', 'Untitled Video')}",
            "emoji": True
        }
    })
    
    # Metadata context
    metadata_elements = []
    
    if 'language' in data:
        metadata_elements.append({
            "type": "mrkdwn",
            "text": f"*Language:* {data['language']}"
        })
    
    if 'duration' in data:
        duration = int(data['duration'])
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
    if 'video_url' in data:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"<{data['video_url']}|View on YouTube>"
            }
        })
    
    # Divider
    blocks.append({"type": "divider"})
    
    # Transcription content
    if include_timestamps and 'segments' in data:
        # Add timestamps with segments
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Transcription with timestamps:*"
            }
        })
        
        for segment in data.get('segments', []):
            timestamp = segment.get('start_formatted', '00:00:00')
            text = segment.get('text', '').strip()
            if text:
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"`{timestamp}` {text}"
                    }
                })
    else:
        # Just the full transcription text
        text = data.get('text', 'No transcription available.')
        
        # Split long text into multiple blocks if needed
        if len(text) > 2000:
            chunks = split_text_for_slack(text, 2000)
            for i, chunk in enumerate(chunks):
                if i == 0:
                    blocks.append({
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Transcription:*\n\n{chunk}"
                        }
                    })
                else:
                    blocks.append({
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": chunk
                        }
                    })
        else:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Transcription:*\n\n{text}"
                }
            })
    
    return blocks


def split_text_for_slack(text: str, max_length: int = 2000) -> List[str]:
    """Split text into chunks suitable for Slack.
    
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
    sentences = re.split(r'(?<=[.!?])\s+', text)
    
    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 <= max_length:
            if current_chunk:
                current_chunk += " "
            current_chunk += sentence
        else:
            if current_chunk:
                chunks.append(current_chunk)
            
            # If a single sentence is too long, split it further
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
                            chunks.append(current_chunk)
                        current_chunk = word
            else:
                current_chunk = sentence
    
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks


def split_message_blocks(blocks: List[Dict[str, Any]], max_blocks_size: int = 3000) -> List[List[Dict[str, Any]]]:
    """Split blocks into chunks that fit within Slack's size limits.
    
    Args:
        blocks: List of Slack blocks
        max_blocks_size: Maximum size in characters for blocks JSON
        
    Returns:
        List of block chunks
    """
    chunks = []
    current_chunk = []
    current_size = 0
    
    for block in blocks:
        block_size = len(json.dumps(block))
        
        # If adding this block would exceed the limit, start a new chunk
        if current_size + block_size > max_blocks_size and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_size = 0
        
        current_chunk.append(block)
        current_size += block_size
    
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks


class SlackClient:
    """Client for sending messages to Slack."""

    def __init__(self, webhook_url: str, channel: Optional[str] = None):
        """Initialize Slack client.
        
        Args:
            webhook_url: Slack webhook URL
            channel: Optional channel override
            
        Raises:
            SlackError: If webhook URL is invalid
        """
        if not self._validate_webhook_url(webhook_url):
            raise SlackError(f"Invalid webhook URL: {webhook_url}")
            
        self.webhook_url = webhook_url
        self.channel = channel
        
        logger.info("Slack client initialized")

    def _validate_webhook_url(self, url: str) -> bool:
        """Validate Slack webhook URL format.
        
        Args:
            url: URL to validate
            
        Returns:
            True if valid
        """
        if not url or not isinstance(url, str):
            return False
            
        # Must be HTTPS and from Slack domain
        patterns = [
            r'^https://hooks\.slack\.com/services/[A-Z0-9]+/[A-Z0-9]+/[A-Za-z0-9]+$',
            r'^https://hooks\.slack\.com/workflows/[A-Z0-9]+/[A-Z0-9]+/[A-Za-z0-9]+$'
        ]
        
        return any(re.match(pattern, url) for pattern in patterns)

    def send_message(self, text: str, retry_on_rate_limit: bool = True) -> bool:
        """Send a simple text message to Slack.
        
        Args:
            text: Message text
            retry_on_rate_limit: Whether to retry on rate limiting
            
        Returns:
            True if successful
            
        Raises:
            SlackError: If sending fails
        """
        payload = {"text": text}
        
        if self.channel:
            payload["channel"] = self.channel
            
        return self._send_payload(payload, retry_on_rate_limit)

    def send_blocks(self, blocks: List[Dict[str, Any]], text: str = "Message", 
                   retry_on_rate_limit: bool = True) -> bool:
        """Send a message with blocks to Slack.
        
        Args:
            blocks: List of Slack block elements
            text: Fallback text for notifications
            retry_on_rate_limit: Whether to retry on rate limiting
            
        Returns:
            True if successful
        """
        payload = {
            "text": text,
            "blocks": blocks
        }
        
        if self.channel:
            payload["channel"] = self.channel
            
        return self._send_payload(payload, retry_on_rate_limit)

    def _send_payload(self, payload: Dict[str, Any], retry_on_rate_limit: bool = True) -> bool:
        """Send payload to Slack webhook.
        
        Args:
            payload: JSON payload to send
            retry_on_rate_limit: Whether to retry on rate limiting
            
        Returns:
            True if successful
            
        Raises:
            SlackError: If sending fails
        """
        headers = {"Content-Type": "application/json"}
        
        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                logger.info("Message sent successfully to Slack")
                return True
            elif response.status_code == 429 and retry_on_rate_limit:
                # Rate limited, retry after delay
                retry_after = int(response.headers.get("Retry-After", 1))
                logger.warning(f"Rate limited by Slack, retrying after {retry_after} seconds")
                time.sleep(retry_after)
                return self._send_payload(payload, retry_on_rate_limit=False)
            else:
                raise SlackError(
                    f"Failed to send message to Slack: {response.status_code} - {response.text}"
                )
                
        except requests.exceptions.RequestException as e:
            raise SlackError(f"Failed to send message to Slack: {e}")

    def send_transcription(self, transcription_data: Dict[str, Any], 
                          include_timestamps: bool = False) -> bool:
        """Send transcription to Slack with formatting.
        
        Args:
            transcription_data: Transcription data including text, video info, etc.
            include_timestamps: Whether to include timestamp information
            
        Returns:
            True if successful
        """
        # Format the transcription into blocks
        blocks = format_transcription_message(transcription_data, include_timestamps)
        
        # Check if we need to split into multiple messages
        block_chunks = split_message_blocks(blocks)
        
        success = True
        for i, chunk in enumerate(block_chunks):
            # Use video title as fallback text for first message
            if i == 0:
                fallback = f"Transcription: {transcription_data.get('video_title', 'Video')}"
            else:
                fallback = f"Transcription continued (part {i + 1})"
                
            try:
                self.send_blocks(chunk, text=fallback)
                
                # Small delay between messages to avoid rate limiting
                if i < len(block_chunks) - 1:
                    time.sleep(1)
                    
            except SlackError as e:
                logger.error(f"Failed to send transcription part {i + 1}: {e}")
                success = False
                
        return success

    def send_error_notification(self, error_message: str, context: Optional[Dict[str, Any]] = None) -> bool:
        """Send error notification to Slack.
        
        Args:
            error_message: Error message to send
            context: Optional context information
            
        Returns:
            True if successful
        """
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "❌ Error in YouTube2Slack",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": error_message
                }
            }
        ]
        
        if context:
            context_elements = []
            for key, value in context.items():
                context_elements.append({
                    "type": "mrkdwn",
                    "text": f"*{key}:* {value}"
                })
                
            if context_elements:
                blocks.append({
                    "type": "context",
                    "elements": context_elements[:10]  # Limit to 10 elements
                })
        
        try:
            return self.send_blocks(blocks, text="Error in YouTube2Slack")
        except SlackError:
            # If we can't send the error notification, just log it
            logger.error(f"Failed to send error notification: {error_message}")
            return False