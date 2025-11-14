"""Production server entry point for YouTube2SlackThread."""

import os
import sys
import logging
from typing import Optional

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from youtube2slack.slack_server import create_slack_server


def setup_production_logging():
    """Setup production logging configuration."""
    # Create logs directory if it doesn't exist
    log_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(os.path.join(log_dir, 'youtube2slack.log')),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Set specific loggers
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)


def get_port() -> int:
    """Get port from environment or default."""
    return int(os.environ.get('PORT', '42389'))


def get_config_path() -> Optional[str]:
    """Get config path from environment."""
    return os.environ.get('CONFIG_PATH', 'config.yaml')


def validate_environment():
    """Validate required environment variables."""
    required_vars = ['SLACK_BOT_TOKEN', 'SLACK_SIGNING_SECRET']
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    
    if missing_vars:
        print("ERROR: Missing required environment variables:")
        for var in missing_vars:
            print(f"  - {var}")
        print("\nPlease set these environment variables and try again.")
        sys.exit(1)


def main():
    """Main entry point for production server."""
    try:
        # Setup logging
        setup_production_logging()
        logger = logging.getLogger(__name__)
        
        logger.info("Starting YouTube2SlackThread production server...")
        
        # Validate environment
        validate_environment()
        
        # Get configuration
        port = get_port()
        config_path = get_config_path()
        
        logger.info(f"Port: {port}")
        logger.info(f"Config path: {config_path}")
        
        # Create and run server
        server = create_slack_server(config_path=config_path, port=port)
        
        logger.info("✅ Server created successfully")
        logger.info(f"🚀 Starting server on port {port}")
        logger.info(f"📡 Webhook URL: http://0.0.0.0:{port}/slack/commands")
        logger.info("📊 Health check: http://0.0.0.0:{port}/health")
        
        # Run in production mode (not debug)
        server.run(debug=False)
        
    except Exception as e:
        logging.error(f"❌ Failed to start server: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()