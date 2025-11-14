"""Tests for Slack Bot client functionality."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from slack_sdk.errors import SlackApiError

from youtube2slack.slack_bot_client import (
    SlackBotClient, SlackBotError, ThreadInfo,
    split_text_for_slack, format_video_header_blocks
)


class TestSlackBotClient:
    """Test cases for SlackBotClient."""
    
    def test_init_valid_tokens(self):
        """Test initialization with valid tokens."""
        with patch('youtube2slack.slack_bot_client.WebClient') as mock_web_client:
            # Mock successful auth test
            mock_client_instance = Mock()
            mock_client_instance.auth_test.return_value = {'user': 'testbot'}
            mock_web_client.return_value = mock_client_instance
            
            client = SlackBotClient(
                bot_token='xoxb-test-token',
                app_token='xapp-test-token',
                default_channel='#general'
            )
            
            assert client.bot_token == 'xoxb-test-token'
            assert client.app_token == 'xapp-test-token'
            assert client.default_channel == '#general'
            mock_client_instance.auth_test.assert_called_once()
    
    def test_init_invalid_bot_token(self):
        """Test initialization with invalid bot token."""
        with pytest.raises(SlackBotError, match="Invalid bot token"):
            SlackBotClient(bot_token='invalid-token')
    
    def test_init_invalid_app_token(self):
        """Test initialization with invalid app token."""
        with patch('youtube2slack.slack_bot_client.WebClient') as mock_web_client:
            mock_client_instance = Mock()
            mock_client_instance.auth_test.return_value = {'user': 'testbot'}
            mock_web_client.return_value = mock_client_instance
            
            with pytest.raises(SlackBotError, match="Invalid app token"):
                SlackBotClient(
                    bot_token='xoxb-test-token',
                    app_token='invalid-app-token'
                )
    
    def test_init_auth_failure(self):
        """Test initialization with authentication failure."""
        with patch('youtube2slack.slack_bot_client.WebClient') as mock_web_client:
            mock_client_instance = Mock()
            mock_client_instance.auth_test.side_effect = SlackApiError(
                message="Invalid token",
                response={'error': 'invalid_auth'}
            )
            mock_web_client.return_value = mock_client_instance
            
            with pytest.raises(SlackBotError, match="Failed to authenticate"):
                SlackBotClient(bot_token='xoxb-invalid-token')
    
    def test_create_thread_success(self):
        """Test successful thread creation."""
        with patch('youtube2slack.slack_bot_client.WebClient') as mock_web_client:
            mock_client_instance = Mock()
            mock_client_instance.auth_test.return_value = {'user': 'testbot'}
            mock_client_instance.chat_postMessage.return_value = {
                'ts': '1234567890.123456'
            }
            mock_web_client.return_value = mock_client_instance
            
            client = SlackBotClient(bot_token='xoxb-test-token')
            
            thread_info = client.create_thread(
                channel='C1234567890',
                video_title='Test Video',
                video_url='https://youtube.com/watch?v=test',
                duration=120,
                language='en'
            )
            
            assert thread_info.channel == 'C1234567890'
            assert thread_info.thread_ts == '1234567890.123456'
            assert thread_info.initial_message == 'Test Video'
            
            # Verify the message was posted with correct parameters
            mock_client_instance.chat_postMessage.assert_called_once()
            call_args = mock_client_instance.chat_postMessage.call_args
            assert call_args[1]['channel'] == 'C1234567890'
            assert call_args[1]['text'] == '🎥 Test Video'
            assert 'blocks' in call_args[1]
    
    def test_create_thread_failure(self):
        """Test thread creation failure."""
        with patch('youtube2slack.slack_bot_client.WebClient') as mock_web_client:
            mock_client_instance = Mock()
            mock_client_instance.auth_test.return_value = {'user': 'testbot'}
            mock_client_instance.chat_postMessage.side_effect = SlackApiError(
                message="Channel not found",
                response={'error': 'channel_not_found'}
            )
            mock_web_client.return_value = mock_client_instance
            
            client = SlackBotClient(bot_token='xoxb-test-token')
            
            with pytest.raises(SlackBotError, match="Failed to create thread"):
                client.create_thread(
                    channel='C1234567890',
                    video_title='Test Video',
                    video_url='https://youtube.com/watch?v=test'
                )
    
    def test_post_to_thread_success(self):
        """Test successful posting to thread."""
        with patch('youtube2slack.slack_bot_client.WebClient') as mock_web_client:
            mock_client_instance = Mock()
            mock_client_instance.auth_test.return_value = {'user': 'testbot'}
            mock_client_instance.chat_postMessage.return_value = {'ok': True}
            mock_web_client.return_value = mock_client_instance
            
            client = SlackBotClient(bot_token='xoxb-test-token')
            
            thread_info = ThreadInfo(
                channel='C1234567890',
                thread_ts='1234567890.123456'
            )
            
            result = client.post_to_thread(thread_info, 'Test message')
            
            assert result is True
            mock_client_instance.chat_postMessage.assert_called_once_with(
                channel='C1234567890',
                thread_ts='1234567890.123456',
                text='Test message',
                blocks=None
            )
    
    def test_post_transcription_to_thread(self):
        """Test posting transcription to thread."""
        with patch('youtube2slack.slack_bot_client.WebClient') as mock_web_client:
            mock_client_instance = Mock()
            mock_client_instance.auth_test.return_value = {'user': 'testbot'}
            mock_client_instance.chat_postMessage.return_value = {'ok': True}
            mock_web_client.return_value = mock_client_instance
            
            client = SlackBotClient(bot_token='xoxb-test-token')
            
            thread_info = ThreadInfo(
                channel='C1234567890',
                thread_ts='1234567890.123456'
            )
            
            result = client.post_transcription_to_thread(
                thread_info,
                'This is a test transcription.',
                include_timestamps=False
            )
            
            assert result is True
            # Should be called twice: once for header, once for transcription
            assert mock_client_instance.chat_postMessage.call_count == 2
    
    def test_post_transcription_with_timestamps(self):
        """Test posting transcription with timestamps."""
        with patch('youtube2slack.slack_bot_client.WebClient') as mock_web_client:
            mock_client_instance = Mock()
            mock_client_instance.auth_test.return_value = {'user': 'testbot'}
            mock_client_instance.chat_postMessage.return_value = {'ok': True}
            mock_web_client.return_value = mock_client_instance
            
            client = SlackBotClient(bot_token='xoxb-test-token')
            
            thread_info = ThreadInfo(
                channel='C1234567890',
                thread_ts='1234567890.123456'
            )
            
            segments = [
                {'start_formatted': '00:00:01', 'text': 'Hello world.'},
                {'start_formatted': '00:00:05', 'text': 'This is a test.'}
            ]
            
            result = client.post_transcription_to_thread(
                thread_info,
                'Full transcription text',
                include_timestamps=True,
                segments=segments
            )
            
            assert result is True
            # Should be called for header and segments
            assert mock_client_instance.chat_postMessage.call_count >= 2
    
    def test_get_channel_id_success(self):
        """Test successful channel ID retrieval."""
        with patch('youtube2slack.slack_bot_client.WebClient') as mock_web_client:
            mock_client_instance = Mock()
            mock_client_instance.auth_test.return_value = {'user': 'testbot'}
            mock_client_instance.conversations_list.return_value = {
                'channels': [
                    {'id': 'C1234567890', 'name': 'general'},
                    {'id': 'C0987654321', 'name': 'random'}
                ]
            }
            mock_web_client.return_value = mock_client_instance
            
            client = SlackBotClient(bot_token='xoxb-test-token')
            
            channel_id = client.get_channel_id('general')
            assert channel_id == 'C1234567890'
            
            # Test with # prefix
            channel_id = client.get_channel_id('#random')
            assert channel_id == 'C0987654321'
    
    def test_get_channel_id_not_found(self):
        """Test channel ID retrieval when channel not found."""
        with patch('youtube2slack.slack_bot_client.WebClient') as mock_web_client:
            mock_client_instance = Mock()
            mock_client_instance.auth_test.return_value = {'user': 'testbot'}
            mock_client_instance.conversations_list.return_value = {
                'channels': [
                    {'id': 'C1234567890', 'name': 'general'}
                ]
            }
            mock_web_client.return_value = mock_client_instance
            
            client = SlackBotClient(bot_token='xoxb-test-token')
            
            channel_id = client.get_channel_id('nonexistent')
            assert channel_id is None


class TestUtilityFunctions:
    """Test cases for utility functions."""
    
    def test_split_text_for_slack_short_text(self):
        """Test splitting short text."""
        text = "This is a short message."
        chunks = split_text_for_slack(text, max_length=100)
        
        assert len(chunks) == 1
        assert chunks[0] == text
    
    def test_split_text_for_slack_long_text(self):
        """Test splitting long text."""
        # Create text longer than limit
        text = "This is a long sentence. " * 50  # Should be > 100 chars
        chunks = split_text_for_slack(text, max_length=100)
        
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 100
    
    def test_split_text_for_slack_japanese(self):
        """Test splitting Japanese text."""
        text = "これは日本語のテストです。これも日本語です。" * 20
        chunks = split_text_for_slack(text, max_length=100)
        
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 100
    
    def test_format_video_header_blocks(self):
        """Test video header block formatting."""
        blocks = format_video_header_blocks(
            title="Test Video",
            url="https://youtube.com/watch?v=test",
            duration=120,
            language="en"
        )
        
        assert len(blocks) >= 3  # Header, context, link, divider
        
        # Check header
        header = blocks[0]
        assert header['type'] == 'header'
        assert 'Test Video' in header['text']['text']
        
        # Check context (metadata)
        context = blocks[1]
        assert context['type'] == 'context'
        
        # Check link section
        link_section = blocks[2]
        assert link_section['type'] == 'section'
        assert 'youtube.com' in link_section['text']['text']
    
    def test_format_video_header_blocks_minimal(self):
        """Test video header block formatting with minimal data."""
        blocks = format_video_header_blocks(
            title="Minimal Video",
            url="https://youtube.com/watch?v=minimal"
        )
        
        # Should still have header, link, and divider
        assert len(blocks) >= 3
        
        header = blocks[0]
        assert 'Minimal Video' in header['text']['text']