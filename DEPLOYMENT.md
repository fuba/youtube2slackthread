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
   commands            # Handle slash commands
   files:read          # Read uploaded files (for cookie upload)
   im:history          # Read DM history
   im:read             # Access DM channels
   im:write            # Send DMs
   ```

3. **Install App to Workspace**
4. Copy the **Bot User OAuth Token** (starts with `xoxb-`)

### Setup Socket Mode (Required for File Uploads)
1. Go to "Socket Mode"
2. Enable Socket Mode
3. Generate an **App-Level Token** with `connections:write` scope
4. Copy the token (starts with `xapp-`)

### Setup Slash Commands
1. Go to "Slash Commands"
2. Create these commands:

| Command | Request URL | Description |
|---------|-------------|-------------|
| `/youtube2thread` | `https://your-domain.com/slack/commands` | Process YouTube video in thread |
| `/youtube2thread-status` | `https://your-domain.com/slack/commands` | Show system status |
| `/youtube2thread-stop` | `https://your-domain.com/slack/commands` | Stop active processing |

### Subscribe to Events
1. Go to "Event Subscriptions"
2. Enable Events
3. Subscribe to **Bot Events**:
   - `message.im` (for DM file uploads)

### Get App Credentials
- **Bot Token**: OAuth & Permissions → Bot User OAuth Token (`xoxb-...`)
- **App Token**: Basic Information → App-Level Tokens (`xapp-...`)
- **Signing Secret**: Basic Information → App Credentials → Signing Secret

## 2. Server Deployment Options

### Option A: Docker Deployment (Recommended)

#### Quick Start

```bash
# 1. Clone repository
git clone https://github.com/fuba/youtube2slackthread.git
cd youtube2slackthread

# 2. Create environment file
cp .env.example .env
# Edit .env with your Slack credentials

# 3. Generate encryption key
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# Add this to COOKIE_ENCRYPTION_KEY in .env

# 4. Create config file
cp config-example.yaml config.yaml
# Edit config.yaml as needed

# 5. Start with Docker Compose
# With GPU support:
docker compose up -d

# Without GPU (CPU-only):
docker compose -f docker-compose.cpu.yml up -d
```

#### Services
- **Slack Server**: `http://localhost:42389` - Handles slash commands
- **Web UI**: `http://localhost:42390` - User settings management

#### View Logs
```bash
docker compose logs -f slack-server
docker compose logs -f web-ui
```

### Option B: VPS/Cloud Server

#### Requirements
- Ubuntu/Debian server with public IP
- Domain name pointing to your server
- SSL certificate (Let's Encrypt)
- NVIDIA GPU (optional, for local Whisper)

#### Installation Steps

```bash
# 1. Server setup
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-pip python3-venv nginx certbot python3-certbot-nginx ffmpeg curl -y

# 2. Install uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# 3. Clone and setup application
git clone https://github.com/fuba/youtube2slackthread.git
cd youtube2slackthread
uv sync

# 4. Create production config
cp config-example.yaml config.yaml
cp .env.example .env
# Edit both files with your settings
```

#### Environment Setup

```bash
# Generate encryption key
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Edit .env file
nano .env
```

Required environment variables:
```bash
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_SIGNING_SECRET=your-signing-secret
SLACK_APP_TOKEN=xapp-your-app-token
COOKIE_ENCRYPTION_KEY=your-generated-key
```

#### Systemd Services

**Slack Server Service:**
```bash
sudo tee /etc/systemd/system/youtube2slack.service > /dev/null << 'EOF'
[Unit]
Description=YouTube2SlackThread Slack Server
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/youtube2slackthread
EnvironmentFile=/path/to/youtube2slackthread/.env
ExecStart=/home/your-user/.local/bin/uv run youtube2slack serve --port 42389
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
```

**Web UI Service:**
```bash
sudo tee /etc/systemd/system/youtube2slack-webui.service > /dev/null << 'EOF'
[Unit]
Description=YouTube2SlackThread Web UI
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/youtube2slackthread
EnvironmentFile=/path/to/youtube2slackthread/.env
ExecStart=/home/your-user/.local/bin/uv run youtube2slack web --host 0.0.0.0 --port 42390
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
```

**Enable and Start:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable youtube2slack youtube2slack-webui
sudo systemctl start youtube2slack youtube2slack-webui
sudo systemctl status youtube2slack youtube2slack-webui
```

#### Nginx Reverse Proxy

```bash
sudo tee /etc/nginx/sites-available/youtube2slack << 'EOF'
server {
    listen 80;
    server_name your-domain.com;

    # Slack commands endpoint
    location /slack/commands {
        proxy_pass http://127.0.0.1:42389;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # Health check
    location /health {
        proxy_pass http://127.0.0.1:42389;
        proxy_set_header Host $host;
    }

    # Web UI
    location /settings {
        proxy_pass http://127.0.0.1:42390;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

# Enable site
sudo ln -sf /etc/nginx/sites-available/youtube2slack /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Setup SSL with Let's Encrypt
sudo certbot --nginx -d your-domain.com
```

## 3. Configuration

### config.yaml

```yaml
youtube:
  download_dir: "./downloads"
  format: "best"
  keep_video: true

whisper:
  model: "medium"          # tiny, base, small, medium, large
  device: "cuda"           # cuda, cpu, or null for auto
  language: null           # null for auto-detect
  allowed_local_users:     # Restrict local Whisper to specific users
    - "U1234567890"        # Slack User IDs

slack:
  webhook_url: null
  channel: null
  include_timestamps: false
  send_errors_to_slack: true
```

### User Permissions

Control who can use local Whisper (GPU-intensive):
- Leave `allowed_local_users` empty to allow everyone
- Add specific Slack User IDs to restrict access
- Users not in the list will use OpenAI Whisper API (requires their own API key)

## 4. Monitoring

### Health Checks
- Slack Server: `curl http://localhost:42389/health`
- Web UI: `curl http://localhost:42390/`

### Logs
```bash
# Docker
docker compose logs -f

# Systemd
journalctl -u youtube2slack -f
journalctl -u youtube2slack-webui -f
```

## 5. Troubleshooting

### Common Issues

**"Cookie authentication failed"**
- User needs to upload fresh YouTube cookies via DM

**"Encryption key is required"**
- Set `COOKIE_ENCRYPTION_KEY` environment variable

**"Failed to authenticate with Slack"**
- Check `SLACK_BOT_TOKEN` is correct and starts with `xoxb-`

**GPU not detected**
- Ensure NVIDIA drivers and CUDA are installed
- For Docker, ensure nvidia-container-toolkit is installed

### Support
- Issues: https://github.com/fuba/youtube2slackthread/issues
