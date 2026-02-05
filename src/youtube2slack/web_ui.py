"""Secure web interface for user settings management."""

import os
import logging
from typing import Dict, Any, Optional
from flask import Flask, render_template_string, request, flash, redirect, url_for

from .web_ui_templates import ERROR_TEMPLATE, SETTINGS_TEMPLATE
from .user_cookie_manager import WhisperService, CookieFileProcessor

logger = logging.getLogger(__name__)


class SecureWebUI:
    """Secure web interface for user settings."""
    
    def __init__(self, settings_manager, token_manager, workflow_config):
        """Initialize secure web UI.
        
        Args:
            settings_manager: UserSettingsManager instance
            token_manager: WebTokenManager instance
            workflow_config: WorkflowConfig instance
        """
        self.settings_manager = settings_manager
        self.token_manager = token_manager
        self.workflow_config = workflow_config
        
        # Create Flask app
        self.app = Flask(__name__)
        self.app.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(24))
        
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup Flask routes."""
        
        @self.app.route('/')
        def home():
            return render_template_string(ERROR_TEMPLATE,
                title="YouTube2SlackThread Settings",
                error_title="Direct Access Not Allowed", 
                error_message="This is a secure settings interface. Access is only available through temporary URLs issued via Slack DM."
            ), 403
        
        @self.app.route('/settings/<token>')
        def settings_page(token):
            return self._handle_settings_page(token)
        
        @self.app.route('/settings/<token>', methods=['POST'])
        def save_settings(token):
            return self._handle_save_settings(token)
        
        @self.app.errorhandler(404)
        def not_found(error):
            return render_template_string(ERROR_TEMPLATE, 
                title="Page Not Found",
                error_title="Page Not Found",
                error_message="The settings page you're looking for doesn't exist or has expired."
            ), 404
    
    def _handle_settings_page(self, token: str):
        """Handle GET request for settings page."""
        # Validate token
        access_token = self.token_manager.validate_token(token, mark_used=False)
        if not access_token:
            return render_template_string(ERROR_TEMPLATE,
                title="Access Denied",
                error_title="Invalid or Expired Token",
                error_message="This settings page URL is invalid or has expired. Please request a new one via Slack DM."
            ), 403
        
        try:
            # Get user settings
            settings = self.settings_manager.get_settings(access_token.user_id)
            has_cookies = self.settings_manager.has_cookies(access_token.user_id)
            has_openai_key = self.settings_manager.has_openai_api_key(access_token.user_id)
            
            # Check if local Whisper is allowed for this user
            local_allowed = True
            if self.workflow_config and hasattr(self.workflow_config, 'is_local_whisper_allowed'):
                local_allowed = self.workflow_config.is_local_whisper_allowed(access_token.user_id)
            
            return render_template_string(SETTINGS_TEMPLATE,
                title="Personal Settings",
                settings=settings,
                has_cookies=has_cookies,
                has_openai_key=has_openai_key,
                local_allowed=local_allowed,
                messages=[]
            )
            
        except Exception as e:
            logger.error(f"Error loading settings page: {e}")
            return render_template_string(ERROR_TEMPLATE,
                title="Error",
                error_title="Settings Load Error",
                error_message="An error occurred while loading your settings. Please try again."
            ), 500
    
    def _handle_save_settings(self, token: str):
        """Handle POST request to save settings."""
        # Validate token and mark as used
        access_token = self.token_manager.validate_token(token, mark_used=True)
        if not access_token:
            return render_template_string(ERROR_TEMPLATE,
                title="Access Denied",
                error_title="Invalid or Expired Token",
                error_message="This settings page URL is invalid or has expired. Please request a new one via Slack DM."
            ), 403
        
        try:
            # Handle API key deletion
            if request.form.get('delete_api_key'):
                settings = self.settings_manager.get_settings(access_token.user_id)
                settings.openai_api_key = None
                if settings.whisper_service == WhisperService.OPENAI:
                    settings.whisper_service = WhisperService.LOCAL
                self.settings_manager.store_settings(access_token.user_id, settings)

                # Generate new token for continued access
                new_token = self.token_manager.generate_token(access_token.user_id, single_use=False)
                return redirect(f'/settings/{new_token.token}?success=api_key_deleted')

            # Handle cookies deletion
            if request.form.get('delete_cookies'):
                self.settings_manager.delete_cookies(access_token.user_id)

                # Generate new token for continued access
                new_token = self.token_manager.generate_token(access_token.user_id, single_use=False)
                return redirect(f'/settings/{new_token.token}?success=cookies_deleted')

            # Get current settings
            settings = self.settings_manager.get_settings(access_token.user_id)
            
            # Update settings from form
            whisper_service = request.form.get('whisper_service', 'local')
            settings.whisper_service = WhisperService(whisper_service)
            
            settings.whisper_model = request.form.get('whisper_model', 'base')
            settings.whisper_language = request.form.get('whisper_language') or None
            settings.include_timestamps = bool(request.form.get('include_timestamps'))
            
            # Update OpenAI API key if provided
            openai_key = request.form.get('openai_api_key', '').strip()
            if openai_key:
                if not openai_key.startswith('sk-'):
                    # Return error for invalid API key format
                    has_cookies = self.settings_manager.has_cookies(access_token.user_id)
                    has_openai_key = self.settings_manager.has_openai_api_key(access_token.user_id)
                    local_allowed = True
                    if self.workflow_config and hasattr(self.workflow_config, 'is_local_whisper_allowed'):
                        local_allowed = self.workflow_config.is_local_whisper_allowed(access_token.user_id)
                    
                    return render_template_string(SETTINGS_TEMPLATE,
                        title="Personal Settings",
                        settings=settings,
                        has_cookies=has_cookies,
                        has_openai_key=has_openai_key,
                        local_allowed=local_allowed,
                        messages=[{'category': 'error', 'message': 'Invalid API key format. OpenAI API keys start with "sk-".'}]
                    ), 400
                
                settings.openai_api_key = openai_key
            
            # Validate local Whisper access
            if settings.whisper_service == WhisperService.LOCAL:
                if self.workflow_config and hasattr(self.workflow_config, 'is_local_whisper_allowed'):
                    if not self.workflow_config.is_local_whisper_allowed(access_token.user_id):
                        settings.whisper_service = WhisperService.OPENAI

            # Handle cookies file upload
            cookies_file = request.files.get('cookies_file')
            if cookies_file and cookies_file.filename:
                try:
                    cookies_content = cookies_file.read().decode('utf-8')

                    # Validate cookies format
                    if not CookieFileProcessor.validate_cookies_file(cookies_content):
                        has_cookies = self.settings_manager.has_cookies(access_token.user_id)
                        has_openai_key = self.settings_manager.has_openai_api_key(access_token.user_id)
                        local_allowed = True
                        if self.workflow_config and hasattr(self.workflow_config, 'is_local_whisper_allowed'):
                            local_allowed = self.workflow_config.is_local_whisper_allowed(access_token.user_id)

                        return render_template_string(SETTINGS_TEMPLATE,
                            title="Personal Settings",
                            settings=settings,
                            has_cookies=has_cookies,
                            has_openai_key=has_openai_key,
                            local_allowed=local_allowed,
                            messages=[{'category': 'error', 'message': 'Invalid cookies file format. Please upload a Netscape HTTP Cookie file (cookies.txt).'}]
                        ), 400

                    # Extract YouTube cookies and store
                    youtube_cookies = CookieFileProcessor.extract_youtube_cookies(cookies_content)
                    self.settings_manager.store_cookies(access_token.user_id, youtube_cookies)
                    logger.info(f"Cookies uploaded via web UI for user {access_token.user_id}")

                except UnicodeDecodeError:
                    has_cookies = self.settings_manager.has_cookies(access_token.user_id)
                    has_openai_key = self.settings_manager.has_openai_api_key(access_token.user_id)
                    local_allowed = True
                    if self.workflow_config and hasattr(self.workflow_config, 'is_local_whisper_allowed'):
                        local_allowed = self.workflow_config.is_local_whisper_allowed(access_token.user_id)

                    return render_template_string(SETTINGS_TEMPLATE,
                        title="Personal Settings",
                        settings=settings,
                        has_cookies=has_cookies,
                        has_openai_key=has_openai_key,
                        local_allowed=local_allowed,
                        messages=[{'category': 'error', 'message': 'Invalid file encoding. Please upload a text file.'}]
                    ), 400

            # Store updated settings
            self.settings_manager.store_settings(access_token.user_id, settings)

            # Generate new token for continued access
            new_token = self.token_manager.generate_token(access_token.user_id, single_use=False)
            return redirect(f'/settings/{new_token.token}?success=settings_saved')
            
        except Exception as e:
            logger.error(f"Error saving settings: {e}")
            return render_template_string(ERROR_TEMPLATE,
                title="Error",
                error_title="Settings Save Error", 
                error_message="An error occurred while saving your settings. Please try again."
            ), 500
    
    def run(self, host='127.0.0.1', port=42390, debug=False):
        """Run the Flask web server."""
        logger.info(f"Starting secure web UI on {host}:{port}")
        self.app.run(host=host, port=port, debug=debug)