"""Tests for Slack integration module."""

import json
from unittest.mock import Mock, patch, MagicMock
import pytest
import requests

from youtube2slack.slack_client import (
    SlackClient, 
    SlackError,
    format_transcription_message,
    split_message_blocks
)


class TestSlackClient:
    """Test cases for SlackClient."""

    @pytest.fixture
    def slack_client(self):
        """Create a SlackClient instance."""
        return SlackClient(webhook_url="https://hooks.slack.com/services/TEST/WEBHOOK/URL")

    @pytest.fixture
    def mock_response(self):
        """Create a mock response."""
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.text = "ok"
        return mock_resp

    def test_init_with_webhook_url(self):
        """Test initialization with webhook URL."""
        webhook_url = "https://hooks.slack.com/services/T123/B456/xyz789"
        client = SlackClient(webhook_url=webhook_url)
        assert client.webhook_url == webhook_url
        assert client.channel is None

    def test_init_with_channel_override(self):
        """Test initialization with channel override."""
        webhook_url = "https://hooks.slack.com/services/T123/B456/xyz789"
        channel = "#general"
        client = SlackClient(webhook_url=webhook_url, channel=channel)
        assert client.webhook_url == webhook_url
        assert client.channel == channel

    def test_init_invalid_webhook_url(self):
        """Test initialization with invalid webhook URL."""
        with pytest.raises(SlackError) as exc_info:
            SlackClient(webhook_url="not-a-valid-url")
        assert "Invalid webhook URL" in str(exc_info.value)

    @patch('requests.post')
    def test_send_message_success(self, mock_post, slack_client, mock_response):
        """Test successful message sending."""
        mock_post.return_value = mock_response
        
        result = slack_client.send_message("Hello, Slack!")
        
        assert result is True
        mock_post.assert_called_once_with(
            slack_client.webhook_url,
            json={"text": "Hello, Slack!"},
            headers={"Content-Type": "application/json"},
            timeout=30
        )

    @patch('requests.post')
    def test_send_message_with_channel(self, mock_post, mock_response):
        """Test sending message with channel override."""
        mock_post.return_value = mock_response
        
        client = SlackClient(
            webhook_url="https://hooks.slack.com/services/TEST/WEBHOOK/URL",
            channel="#specific-channel"
        )
        
        client.send_message("Test message")
        
        call_args = mock_post.call_args
        assert call_args[1]['json']['channel'] == "#specific-channel"

    @patch('requests.post')
    def test_send_message_failure(self, mock_post, slack_client):
        """Test handling of failed message sending."""
        mock_resp = Mock()
        mock_resp.status_code = 400
        mock_resp.text = "invalid_payload"
        mock_post.return_value = mock_resp
        
        with pytest.raises(SlackError) as exc_info:
            slack_client.send_message("Test message")
        
        assert "Failed to send message" in str(exc_info.value)
        assert "400" in str(exc_info.value)

    @patch('requests.post')
    def test_send_message_network_error(self, mock_post, slack_client):
        """Test handling of network errors."""
        mock_post.side_effect = requests.exceptions.RequestException("Network error")
        
        with pytest.raises(SlackError) as exc_info:
            slack_client.send_message("Test message")
        
        assert "Failed to send message" in str(exc_info.value)

    @patch('requests.post')
    def test_send_blocks_success(self, mock_post, slack_client, mock_response):
        """Test sending message with blocks."""
        mock_post.return_value = mock_response
        
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Test Header"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Test content"
                }
            }
        ]
        
        result = slack_client.send_blocks(blocks, text="Fallback text")
        
        assert result is True
        call_args = mock_post.call_args
        assert call_args[1]['json']['blocks'] == blocks
        assert call_args[1]['json']['text'] == "Fallback text"

    @patch('requests.post')
    def test_send_transcription(self, mock_post, slack_client, mock_response):
        """Test sending transcription."""
        mock_post.return_value = mock_response
        
        transcription_data = {
            'text': 'This is the transcribed text.',
            'video_title': 'Test Video',
            'video_url': 'https://youtube.com/watch?v=test123',
            'duration': 120,
            'language': 'en'
        }
        
        result = slack_client.send_transcription(transcription_data)
        
        assert result is True
        call_args = mock_post.call_args
        payload = call_args[1]['json']
        
        # Check that blocks were created
        assert 'blocks' in payload
        assert len(payload['blocks']) > 0
        
        # Check header
        header_block = payload['blocks'][0]
        assert header_block['type'] == 'header'
        assert 'Test Video' in header_block['text']['text']

    @patch('requests.post')
    def test_send_long_transcription_chunked(self, mock_post, slack_client, mock_response):
        """Test sending long transcription in chunks."""
        mock_post.return_value = mock_response
        
        # Create a very long transcription
        long_text = "This is a long sentence. " * 200
        
        transcription_data = {
            'text': long_text,
            'video_title': 'Long Video',
            'video_url': 'https://youtube.com/watch?v=long123',
            'duration': 3600,
            'language': 'en'
        }
        
        slack_client.send_transcription(transcription_data)
        
        # Should be called multiple times due to chunking
        assert mock_post.call_count > 1
        
        # First call should have the header
        first_call = mock_post.call_args_list[0]
        first_blocks = first_call[1]['json']['blocks']
        assert first_blocks[0]['type'] == 'header'
        
        # Subsequent calls should not have headers
        if len(mock_post.call_args_list) > 1:
            second_call = mock_post.call_args_list[1]
            second_blocks = second_call[1]['json']['blocks']
            assert all(block['type'] != 'header' for block in second_blocks)

    @patch('requests.post')
    def test_send_transcription_with_timestamps(self, mock_post, slack_client, mock_response):
        """Test sending transcription with timestamps."""
        mock_post.return_value = mock_response
        
        transcription_data = {
            'text': 'Full transcription text.',
            'video_title': 'Test Video',
            'video_url': 'https://youtube.com/watch?v=test123',
            'duration': 120,
            'language': 'en',
            'segments': [
                {
                    'start': 0,
                    'end': 5,
                    'text': 'First segment',
                    'start_formatted': '00:00:00',
                    'end_formatted': '00:00:05'
                },
                {
                    'start': 5,
                    'end': 10,
                    'text': 'Second segment',
                    'start_formatted': '00:00:05',
                    'end_formatted': '00:00:10'
                }
            ]
        }
        
        slack_client.send_transcription(transcription_data, include_timestamps=True)
        
        call_args = mock_post.call_args
        blocks = call_args[1]['json']['blocks']
        
        # Check that timestamps are included
        text_content = str(blocks)
        assert '00:00:00' in text_content
        assert '00:00:05' in text_content
        assert 'First segment' in text_content

    def test_format_transcription_message(self):
        """Test formatting transcription message."""
        data = {
            'text': 'This is the transcribed text.',
            'video_title': 'Test Video Title',
            'video_url': 'https://youtube.com/watch?v=abc123',
            'duration': 3661,  # 1 hour, 1 minute, 1 second
            'language': 'en'
        }
        
        blocks = format_transcription_message(data)
        
        # Check header block
        assert blocks[0]['type'] == 'header'
        assert 'Test Video Title' in blocks[0]['text']['text']
        
        # Check metadata block
        metadata_found = False
        for block in blocks:
            if block['type'] == 'context':
                text = str(block['elements'])
                if 'Language:' in text and 'Duration:' in text:
                    metadata_found = True
                    # Also check the actual values
                    assert 'en' in text
                    assert '01:01:01' in text
                    break
        assert metadata_found
        
        # Check video link block
        link_found = False
        for block in blocks:
            if block['type'] == 'section' and 'View on YouTube' in str(block):
                link_found = True
                break
        assert link_found
        
        # Check transcription text
        text_found = False
        for block in blocks:
            if block['type'] == 'section' and 'This is the transcribed text' in str(block):
                text_found = True
                break
        assert text_found

    def test_split_message_blocks(self):
        """Test splitting message blocks."""
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": "Header"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "A" * 2000}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "B" * 2000}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "C" * 1000}},
        ]
        
        chunks = split_message_blocks(blocks)
        
        # Should be split into multiple chunks
        assert len(chunks) > 1
        
        # Each chunk should be within size limit
        for chunk in chunks:
            chunk_size = len(json.dumps(chunk))
            assert chunk_size < 3000  # Slack's limit with some buffer

    def test_validate_webhook_url(self):
        """Test webhook URL validation."""
        # Valid URLs
        valid_urls = [
            "https://hooks.slack.com/services/T123/B456/xyz789",
            "https://hooks.slack.com/workflows/T123/B456/xyz789",
        ]
        
        for url in valid_urls:
            client = SlackClient(webhook_url=url)
            assert client.webhook_url == url
        
        # Invalid URLs
        invalid_urls = [
            "http://hooks.slack.com/services/T123/B456/xyz789",  # Not HTTPS
            "https://example.com/webhook",  # Wrong domain
            "not-a-url",  # Not a URL
            "",  # Empty
        ]
        
        for url in invalid_urls:
            with pytest.raises(SlackError):
                SlackClient(webhook_url=url)

    @patch('requests.post')
    def test_retry_on_rate_limit(self, mock_post, slack_client):
        """Test retry behavior on rate limiting."""
        # First call returns 429 (rate limited)
        rate_limit_resp = Mock()
        rate_limit_resp.status_code = 429
        rate_limit_resp.text = "rate_limited"
        rate_limit_resp.headers = {"Retry-After": "1"}
        
        # Second call succeeds
        success_resp = Mock()
        success_resp.status_code = 200
        success_resp.text = "ok"
        
        mock_post.side_effect = [rate_limit_resp, success_resp]
        
        with patch('time.sleep') as mock_sleep:
            result = slack_client.send_message("Test message")
        
        assert result is True
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(1)