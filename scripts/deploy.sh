#!/bin/bash

# YouTube2SlackThread Deployment Script
set -e

echo "🚀 YouTube2SlackThread Deployment Script"
echo "========================================"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [[ $EUID -eq 0 ]]; then
   print_error "This script should not be run as root"
   exit 1
fi

# Check if .env file exists
if [ ! -f ".env" ]; then
    print_warning ".env file not found. Creating from example..."
    if [ -f ".env.example" ]; then
        cp .env.example .env
        print_warning "Please edit .env file with your Slack credentials before continuing."
        exit 1
    else
        print_error ".env.example file not found. Please create .env manually."
        exit 1
    fi
fi

# Source environment variables
source .env

# Validate required environment variables
required_vars=("SLACK_BOT_TOKEN" "SLACK_SIGNING_SECRET")
for var in "${required_vars[@]}"; do
    if [ -z "${!var}" ]; then
        print_error "Environment variable $var is not set in .env file"
        exit 1
    fi
done

print_info "Environment variables validated ✅"

# Check if Docker is available
if command -v docker &> /dev/null && command -v docker-compose &> /dev/null; then
    print_info "Docker detected. Using Docker deployment..."
    
    # Build and start containers
    print_info "Building Docker containers..."
    docker-compose build
    
    print_info "Starting services..."
    docker-compose up -d
    
    # Wait for health check
    print_info "Waiting for health check..."
    sleep 10
    
    if curl -f http://localhost:3000/health &> /dev/null; then
        print_info "✅ Service is healthy!"
        print_info "🌐 Webhook URL: http://localhost/slack/commands"
        print_info "📊 Health check: http://localhost/health"
    else
        print_error "❌ Health check failed"
        print_info "Checking logs..."
        docker-compose logs youtube2slack
        exit 1
    fi
    
elif command -v python3 &> /dev/null; then
    print_info "Python detected. Using native deployment..."
    
    # Check if uv is installed
    if ! command -v uv &> /dev/null; then
        print_info "Installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        source $HOME/.local/bin/env
    fi
    
    # Install dependencies
    print_info "Installing dependencies..."
    uv pip install -e .
    
    # Create directories
    mkdir -p logs downloads
    
    # Start server
    print_info "Starting server..."
    export PYTHONPATH="./src:$PYTHONPATH"
    uv run python -m youtube2slack &
    SERVER_PID=$!
    
    # Wait for startup
    sleep 5
    
    # Check if server is running
    if curl -f http://localhost:3000/health &> /dev/null; then
        print_info "✅ Service is running!"
        print_info "🌐 Webhook URL: http://localhost:3000/slack/commands"
        print_info "📊 Health check: http://localhost:3000/health"
        print_info "🔧 Server PID: $SERVER_PID"
        
        # Save PID for later management
        echo $SERVER_PID > youtube2slack.pid
    else
        print_error "❌ Failed to start server"
        kill $SERVER_PID 2>/dev/null || true
        exit 1
    fi
    
else
    print_error "Neither Docker nor Python3 found. Please install one of them."
    exit 1
fi

print_info ""
print_info "🎉 Deployment completed successfully!"
print_info ""
print_info "Next steps:"
print_info "1. Configure your Slack app to use the webhook URL"
print_info "2. Test with: /youtube2thread https://youtube.com/watch?v=dQw4w9WgXcQ"
print_info "3. Monitor logs for any issues"
print_info ""
print_info "For production deployment, make sure to:"
print_info "- Set up SSL/TLS certificates"
print_info "- Configure a proper domain name"
print_info "- Set up monitoring and logging"
print_info "- Configure firewall rules"