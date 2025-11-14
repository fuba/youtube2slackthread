"""Tests for Slack server functionality."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json

from youtube2slack.slack_server import SlackServer, create_slack_server
from youtube2slack.slack_bot_client import SlackBotClient, ThreadInfo
from youtube2slack.workflow import WorkflowConfig


class TestSlackServer:
    """Test cases for SlackServer."""
    
    @pytest.fixture
    def mock_bot_client(self):
        """Create a mock bot client."""
        with patch('youtube2slack.slack_bot_client.WebClient'):
            client = Mock(spec=SlackBotClient)
            client.create_thread.return_value = ThreadInfo(
                channel='C1234567890',
                thread_ts='1234567890.123456'
            )
            client.post_to_thread.return_value = True
            client.post_transcription_to_thread.return_value = True
            return client
    
    @pytest.fixture
    def workflow_config(self):
        """Create a test workflow config."""
        return WorkflowConfig(
            whisper_model='tiny',  # Use smallest model for tests
            include_timestamps=False
        )
    
    @pytest.fixture
    def slack_server(self, mock_bot_client, workflow_config):
        """Create a SlackServer instance for testing."""
        with patch('youtube2slack.slack_server.SignatureVerifier') as mock_verifier:
            mock_verifier_instance = Mock()
            mock_verifier_instance.is_valid.return_value = True
            mock_verifier.return_value = mock_verifier_instance
            
            server = SlackServer(
                bot_client=mock_bot_client,
                workflow_config=workflow_config,
                signing_secret='test_signing_secret',
                port=3000
            )
            # Override the verifier with our mock
            server.signature_verifier = mock_verifier_instance
            return server
    
    def test_health_endpoint(self, slack_server):
        """Test health check endpoint."""
        with slack_server.app.test_client() as client:
            response = client.get('/health')
            
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['status'] == 'healthy'
            assert data['service'] == 'youtube2slackthread'
    
    def test_slash_command_invalid_signature(self, slack_server):
        """Test slash command with invalid signature."""
        # Override the verifier to return False for this test
        slack_server.signature_verifier.is_valid.return_value = False
        
        with slack_server.app.test_client() as client:
            response = client.post('/slack/commands', data={
                'command': '/youtube2thread',
                'text': 'https://youtube.com/watch?v=test'
            }, headers={
                'X-Slack-Request-Timestamp': '1234567890',
                'X-Slack-Signature': 'invalid_signature'
            })
            
            assert response.status_code == 401
    
    def test_slash_command_no_url(self, slack_server):
        """Test slash command without URL."""
        
        with slack_server.app.test_client() as client:
            response = client.post('/slack/commands', data={
                'command': '/youtube2thread',
                'text': '',
                'channel_id': 'C1234567890',
                'user_id': 'U1234567890'
            }, headers={
                'X-Slack-Request-Timestamp': '1234567890',
                'X-Slack-Signature': 'valid_signature'
            })
            
            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'Please provide a YouTube URL' in data['text']
            assert data['response_type'] == 'ephemeral'
    
    def test_slash_command_invalid_url(self, slack_server):
        """Test slash command with invalid URL."""
        
        with slack_server.app.test_client() as client:
            response = client.post('/slack/commands', data={
                'command': '/youtube2thread',
                'text': 'https://example.com/watch?v=test',
                'channel_id': 'C1234567890',
                'user_id': 'U1234567890'
            }, headers={
                'X-Slack-Request-Timestamp': '1234567890',
                'X-Slack-Signature': 'valid_signature'
            })
            
            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'Please provide a valid YouTube URL' in data['text']
            assert data['response_type'] == 'ephemeral'
    
    @patch('threading.Thread')
    def test_slash_command_valid_url(self, mock_thread, slack_server):
        """Test slash command with valid URL."""
        
        mock_thread_instance = Mock()
        mock_thread.return_value = mock_thread_instance
        
        with slack_server.app.test_client() as client:
            response = client.post('/slack/commands', data={
                'command': '/youtube2thread',
                'text': 'https://youtube.com/watch?v=test123',
                'channel_id': 'C1234567890',
                'user_id': 'U1234567890',
                'response_url': 'https://hooks.slack.com/response'
            }, headers={
                'X-Slack-Request-Timestamp': '1234567890',
                'X-Slack-Signature': 'valid_signature'
            })
            
            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'Starting to process' in data['text']
            assert data['response_type'] == 'ephemeral'
            
            # Verify thread was started
            mock_thread.assert_called_once()
            mock_thread_instance.start.assert_called_once()
    
    def test_unknown_command(self, slack_server):
        """Test unknown slash command."""
        
        with slack_server.app.test_client() as client:
            response = client.post('/slack/commands', data={
                'command': '/unknown',
                'text': 'test',
                'channel_id': 'C1234567890',
                'user_id': 'U1234567890'
            }, headers={
                'X-Slack-Request-Timestamp': '1234567890',
                'X-Slack-Signature': 'valid_signature'
            })
            
            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'Unknown command' in data['text']
    
    def test_get_active_threads(self, slack_server):
        """Test getting active threads."""
        # Initially should be empty
        threads = slack_server.get_active_threads()
        assert len(threads) == 0
        
        # Add a thread
        thread_info = ThreadInfo(channel='C1234567890', thread_ts='1234567890.123456')
        slack_server.active_threads['test_key'] = thread_info
        
        threads = slack_server.get_active_threads()
        assert len(threads) == 1
        assert 'test_key' in threads


class TestCreateSlackServer:
    """Test cases for create_slack_server function."""
    
    @patch.dict('os.environ', {
        'SLACK_BOT_TOKEN': 'xoxb-test-token',
        'SLACK_SIGNING_SECRET': 'test-secret',
        'SLACK_DEFAULT_CHANNEL': 'general'
    })
    @patch('youtube2slack.slack_server.SlackBotClient')
    def test_create_slack_server_success(self, mock_client_class):
        """Test successful server creation."""
        mock_client_instance = Mock()
        mock_client_class.return_value = mock_client_instance
        
        server = create_slack_server(port=3001)
        
        assert server.port == 3001
        mock_client_class.assert_called_once_with(
            bot_token='xoxb-test-token',
            app_token=None,
            default_channel='general'
        )
    
    @patch.dict('os.environ', {}, clear=True)
    def test_create_slack_server_missing_bot_token(self):
        """Test server creation with missing bot token."""
        with pytest.raises(ValueError, match="SLACK_BOT_TOKEN"):
            create_slack_server()
    
    @patch.dict('os.environ', {
        'SLACK_BOT_TOKEN': 'xoxb-test-token'
    })
    def test_create_slack_server_missing_signing_secret(self):
        """Test server creation with missing signing secret."""
        with pytest.raises(ValueError, match="SLACK_SIGNING_SECRET"):
            create_slack_server()
    
    @patch.dict('os.environ', {
        'SLACK_BOT_TOKEN': 'xoxb-test-token',
        'SLACK_SIGNING_SECRET': 'test-secret',
        'SLACK_APP_TOKEN': 'xapp-test-token'
    })
    @patch('youtube2slack.slack_server.SlackBotClient')
    def test_create_slack_server_with_app_token(self, mock_client_class):
        """Test server creation with app token."""
        mock_client_instance = Mock()
        mock_client_class.return_value = mock_client_instance
        
        server = create_slack_server()
        
        mock_client_class.assert_called_once_with(
            bot_token='xoxb-test-token',
            app_token='xapp-test-token',
            default_channel=None
        )