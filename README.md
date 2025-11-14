# YouTube2SlackThread

Download YouTube videos, transcribe them using local Whisper, and post the transcriptions to Slack **with thread support**.

## 🆕 New Features

- **🧵 Slack Thread Support**: Each video gets its own dedicated thread
- **⚡ Slash Commands**: Use `/youtube2thread` to process videos from Slack
- **🤖 Slack Bot API**: Enhanced integration with proper Bot API (replaces webhook-only mode)
- **📱 Real-time Processing**: Background processing with live status updates in threads

## Core Features

- Download YouTube videos using yt-dlp
- Transcribe audio using OpenAI's Whisper (local installation)
- **🧵 Post transcriptions to Slack threads** (NEW!)
- **⚡ Slack slash command support** (NEW!)
- **Real-time live stream processing with VAD (Voice Activity Detection)**
- **Sentence-boundary detection for natural message splitting**
- Support for various video formats
- Progress tracking and logging
- Configuration file support
- CLI interface

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd youtube2slack

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -e .

# For development
pip install -e ".[dev]"
```

## Configuration

### 🆕 Bot API Configuration (Recommended)

For full thread support and slash commands, use Slack Bot API:

1. Create a Slack app at https://api.slack.com/apps
2. Add Bot Token Scopes: `chat:write`, `channels:read`, `commands`
3. Install app to your workspace
4. Set environment variables:

```bash
export SLACK_BOT_TOKEN="xoxb-your-bot-token"
export SLACK_SIGNING_SECRET="your-signing-secret"
export SLACK_DEFAULT_CHANNEL="general"  # optional
```

### Configuration File

Create a `config.yaml` file:

```yaml
# YouTube2SlackThread Configuration
youtube:
  download_dir: "./downloads"
  format: "best"
  keep_video: true

whisper:
  model: "medium"  # tiny, base, small, medium, large
  device: null  # cpu, cuda, or null for auto
  language: null  # auto-detect or specify (en, ja, etc.)

slack:
  # Legacy webhook mode (for backward compatibility)
  webhook_url: "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
  channel: null  # optional channel override
  include_timestamps: false
  send_errors_to_slack: true

# Bot API configuration is set via environment variables (see above)
```

## Usage

### 🆕 Slack Thread Mode (Recommended)

Process videos and create dedicated Slack threads:

```bash
# Process video and create thread in Slack
youtube2slack thread https://www.youtube.com/watch?v=VIDEO_ID --channel general

# With custom model and timestamps
youtube2slack thread https://www.youtube.com/watch?v=VIDEO_ID \
  --channel general \
  --whisper-model large \
  --include-timestamps
```

**Requirements for thread mode:**
- `SLACK_BOT_TOKEN` environment variable
- Bot must be invited to target channel

### 🆕 Slack Server Mode (Slash Commands)

Start server to handle slash commands:

```bash
# Start server for slash commands
youtube2slack serve --port 3000

# Configure your Slack app to use:
# Request URL: https://your-domain.com/slack/commands
# Command: /youtube2thread
```

**Usage in Slack:**
```
/youtube2thread https://www.youtube.com/watch?v=VIDEO_ID
```

### Legacy CLI Commands

```bash
# Single video (webhook mode)
youtube2slack process https://www.youtube.com/watch?v=VIDEO_ID

# With custom config
youtube2slack --config my-config.yaml process https://www.youtube.com/watch?v=VIDEO_ID

# Playlist
youtube2slack playlist https://www.youtube.com/playlist?list=PLAYLIST_ID
```

### Real-time Live Stream Processing (VAD)

**🎯 Recommended for live streams** - Uses Voice Activity Detection and sentence boundary detection:

```bash
# Process live YouTube stream with VAD
youtube2slack vad-stream https://www.youtube.com/live/STREAM_ID

# Advanced VAD settings
youtube2slack vad-stream https://www.youtube.com/live/STREAM_ID \
  --vad-aggressiveness 2 \
  --frame-duration 30 \
  --whisper-model large

# With custom Slack webhook
youtube2slack vad-stream https://www.youtube.com/live/STREAM_ID \
  --slack-webhook "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
```

**VAD Features:**
- ✅ No overlap or duplication
- ✅ Natural sentence boundaries (句読点で分割)
- ✅ Real-time processing without waiting for download
- ✅ Automatic speech/silence detection
- ✅ Continuous stream processing

### Legacy Stream Processing

```bash
# Simple chunked stream processing (may have overlaps)
youtube2slack stream https://www.youtube.com/live/STREAM_ID --chunk-duration 15
```

## Thread vs Webhook Mode

| Feature | Thread Mode (New) | Webhook Mode (Legacy) |
|---------|------------------|----------------------|
| **Organization** | ✅ Each video gets its own thread | ❌ All messages in channel |
| **Slash Commands** | ✅ `/youtube2thread` support | ❌ Not supported |
| **Real-time Updates** | ✅ Processing status updates | ❌ Only final result |
| **Setup** | Slack Bot API + environment variables | Simple webhook URL |
| **Recommended for** | Production use, team collaboration | Quick setup, personal use |

## Examples

### Complete Setup Example

1. **Set up Slack Bot:**
```bash
export SLACK_BOT_TOKEN="xoxb-1234567890-abcdef..."
export SLACK_SIGNING_SECRET="abc123def456..."
```

2. **Process a video with thread:**
```bash
youtube2slack thread "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --channel general
```

3. **Start slash command server:**
```bash
youtube2slack serve --port 3000
```

4. **Use slash command in Slack:**
```
/youtube2thread https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

### Thread Output Example

```
🧵 Thread in #general:
┌─ 🎥 Never Gonna Give You Up - Rick Astley
├─ 📊 Language: en | Duration: 03:32
├─ 🔗 View on YouTube
├─ ────────────────────────
├─ 🔄 Processing video...
├─ ⏳ Downloading video...
├─ ⏳ Transcribing video...
├─ 📝 Transcription:
├─ "We're no strangers to love..."
└─ ✅ Processing complete! Language detected: en
```

## Development

```bash
# Install with uv (recommended)
uv pip install -e ".[dev]"

# Run tests
uv run python -m pytest

# Run with coverage  
uv run python -m pytest --cov=youtube2slack

# Test specific modules
uv run python -m pytest tests/test_slack_bot.py -v
uv run python -m pytest tests/test_slack_server.py -v

# Format code
uv run black src tests

# Type checking
uv run mypy src
```

## API Reference

### CLI Commands

| Command | Description |
|---------|-------------|
| `youtube2slack thread <url>` | Process video and create Slack thread |
| `youtube2slack serve` | Start slash command server |
| `youtube2slack process <url>` | Legacy webhook mode processing |
| `youtube2slack vad-stream <url>` | Real-time VAD stream processing |
| `youtube2slack create-config` | Create sample config file |

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SLACK_BOT_TOKEN` | Yes (thread mode) | Bot User OAuth Token (xoxb-...) |
| `SLACK_SIGNING_SECRET` | Yes (server mode) | App signing secret for webhooks |
| `SLACK_APP_TOKEN` | Optional | App-Level Token for Socket Mode (xapp-...) |
| `SLACK_DEFAULT_CHANNEL` | Optional | Default channel name (without #) |

### Slack Bot Permissions

Required OAuth scopes for your Slack app:
- `chat:write` - Post messages and create threads
- `channels:read` - Read channel list to resolve channel names
- `commands` - Handle slash commands (if using server mode)

## License

CC0 - Creative Commons Zero