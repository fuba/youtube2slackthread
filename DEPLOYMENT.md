# 🚀 Production Deployment Guide

## 1. Slack App Setup

### Create Slack App
1. Go to https://api.slack.com/apps
2. Click "Create New App" → "From scratch"
3. App Name: `YouTube2SlackThread`
4. Choose your workspace

### Configure OAuth & Permissions
1. Go to "OAuth & Permissions"
2. Add **Bot Token Scopes**:
   ```
   chat:write          # Post messages and create threads
   channels:read       # Read channel information
   commands           # Handle slash commands
   ```

3. **Install App to Workspace**
4. Copy the **Bot User OAuth Token** (starts with `xoxb-`)

### Setup Slash Commands
1. Go to "Slash Commands"
2. Click "Create New Command"
3. Configure:
   - **Command**: `/youtube2thread`
   - **Request URL**: `https://your-domain.com/slack/commands`
   - **Short Description**: `Process YouTube video in thread`
   - **Usage Hint**: `https://youtube.com/watch?v=...`

### Get App Credentials
1. **Bot Token**: OAuth & Permissions → Bot User OAuth Token
2. **Signing Secret**: Basic Information → App Credentials → Signing Secret

## 2. Server Deployment Options

### Option A: VPS/Cloud Server (Recommended)

#### Requirements
- Ubuntu/Debian server with public IP
- Domain name pointing to your server
- SSL certificate (Let's Encrypt)

#### Installation Steps

```bash
# 1. Server setup
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-pip python3-venv nginx certbot python3-certbot-nginx ffmpeg -y

# 2. Create deployment user
sudo useradd -m -s /bin/bash youtube2slack
sudo usermod -aG sudo youtube2slack

# 3. Switch to deployment user
sudo su - youtube2slack

# 4. Install uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# 5. Clone and setup application
git clone <your-repo-url> youtube2slackthread
cd youtube2slackthread
uv pip install -e .

# 6. Create production config
cp config-example.yaml config.yaml
# Edit config.yaml with your settings
```

#### Environment Setup

```bash
# Create environment file
cat > /home/youtube2slack/youtube2slackthread/.env << EOF
SLACK_BOT_TOKEN=xoxb-your-bot-token-here
SLACK_SIGNING_SECRET=your-signing-secret-here
SLACK_DEFAULT_CHANNEL=general
PYTHONPATH=/home/youtube2slack/youtube2slackthread/src
EOF

# Set proper permissions
chmod 600 .env
```

#### Systemd Service

```bash
# Create systemd service
sudo tee /etc/systemd/system/youtube2slack.service > /dev/null << EOF
[Unit]
Description=YouTube2SlackThread Server
After=network.target

[Service]
Type=simple
User=youtube2slack
WorkingDirectory=/home/youtube2slack/youtube2slackthread
Environment=PATH=/home/youtube2slack/.local/bin:/usr/local/bin:/usr/bin:/bin
EnvironmentFile=/home/youtube2slack/youtube2slackthread/.env
ExecStart=/home/youtube2slack/.local/bin/uv run python -m youtube2slack.slack_server
ExecReload=/bin/kill -HUP \$MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable youtube2slack
sudo systemctl start youtube2slack
sudo systemctl status youtube2slack
```

#### Nginx Reverse Proxy

```bash
# Create nginx config
sudo tee /etc/nginx/sites-available/youtube2slack << EOF
server {
    listen 80;
    server_name your-domain.com;

    location /slack/commands {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout       60s;
        proxy_send_timeout          60s;
        proxy_read_timeout          60s;
    }

    location /health {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
EOF

# Enable site
sudo ln -s /etc/nginx/sites-available/youtube2slack /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Setup SSL with Let's Encrypt
sudo certbot --nginx -d your-domain.com
```

### Option B: Docker Deployment

#### Dockerfile

```dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \\
    ffmpeg \\
    git \\
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install uv

# Create app user
RUN useradd -m -u 1000 app
USER app
WORKDIR /app

# Copy application
COPY --chown=app:app . .

# Install dependencies
RUN uv pip install -e .

# Expose port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \\
  CMD curl -f http://localhost:3000/health || exit 1

# Run application
CMD ["uv", "run", "python", "-m", "youtube2slack.slack_server"]
```

#### Docker Compose

```yaml
version: '3.8'

services:
  youtube2slack:
    build: .
    ports:
      - "3000:3000"
    environment:
      - SLACK_BOT_TOKEN=${SLACK_BOT_TOKEN}
      - SLACK_SIGNING_SECRET=${SLACK_SIGNING_SECRET}
      - SLACK_DEFAULT_CHANNEL=${SLACK_DEFAULT_CHANNEL}
    volumes:
      - ./downloads:/app/downloads
      - ./logs:/app/logs
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./ssl:/etc/ssl
    depends_on:
      - youtube2slack
    restart: unless-stopped
```

### Option C: Railway/Heroku Deployment

#### railway.json (for Railway)

```json
{
  "build": {
    "builder": "nixpacks"
  },
  "deploy": {
    "startCommand": "uv run python -m youtube2slack.slack_server",
    "healthcheckPath": "/health",
    "healthcheckTimeout": 300
  }
}
```

#### Procfile (for Heroku)

```
web: uv run python -m youtube2slack.slack_server --port $PORT
```

## 3. Production Server Code

Create a production-ready server entry point: