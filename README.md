# YouTube2SlackThread

Real-time YouTube transcription to Slack threads using Voice Activity Detection and OpenAI Whisper.

## Features

- **🎯 Real-time transcription** of YouTube videos and live streams
- **🧵 Slack thread organization** - each video gets its own dedicated thread
- **⚡ Slash command support** - use `/youtube2thread` in Slack
- **🎤 Voice Activity Detection (VAD)** - natural sentence boundaries
- **🚀 CUDA acceleration** - GPU-powered Whisper transcription
- **🍪 YouTube authentication** - bypass bot detection with browser cookies

## Quick Start

### 1. Installation

```bash
git clone https://github.com/your-username/youtube2slackthread.git
cd youtube2slackthread
uv pip install -e .
```

### 2. Configuration

Create `config.yaml`:

```bash
uv run youtube2slack create-config
```

Edit the generated config:

```yaml
youtube:
  cookies_file: "./cookies/youtube_cookies.txt"

whisper:
  model: "medium"
  device: "cuda"  # or "cpu"

slack:
  # Set via environment variables
```

### 3. Setup Slack App

1. Create Slack app at https://api.slack.com/apps
2. Add scopes: `chat:write`, `channels:read`, `commands`
3. Set environment variables:

```bash
export SLACK_BOT_TOKEN="xoxb-your-token"
export SLACK_SIGNING_SECRET="your-secret"
```

### 4. Setup YouTube Cookies

1. Install browser extension: [Get cookies.txt LOCALLY](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
2. Visit YouTube and login
3. Export cookies to `cookies/youtube_cookies.txt`

### 5. Start Server

```bash
uv run youtube2slack serve --port 42389
```

Configure Slack slash command:
- Request URL: `https://your-domain.com/slack/commands`
- Command: `/youtube2thread`

## Usage

### Slash Command (Recommended)

In Slack:
```
/youtube2thread https://www.youtube.com/watch?v=VIDEO_ID
```

### CLI Commands

```bash
# Check status
/youtube2thread-status

# Stop processing
/youtube2thread-stop
```

## How It Works

1. **VAD Processing**: Detects voice activity in real-time
2. **Whisper Transcription**: Converts speech to text using GPU acceleration
3. **Sentence Boundary**: Splits text at natural breakpoints
4. **Slack Threads**: Posts each transcribed sentence to a dedicated thread

## System Requirements

- **GPU**: NVIDIA GPU with CUDA for optimal performance
- **Memory**: 4GB+ RAM for medium Whisper model
- **Network**: Stable connection for YouTube streaming

## Performance

- **CPU-only**: ~142% CPU usage (not recommended for real-time)
- **CUDA**: ~13% CPU usage, ~1GB GPU memory (recommended)
- **Latency**: ~2-3 seconds from speech to Slack post

## Configuration

### Whisper Models

| Model | Size | Speed | Quality |
|-------|------|-------|---------|
| `tiny` | 39MB | Fastest | Basic |
| `base` | 74MB | Fast | Good |
| `medium` | 769MB | Moderate | **Recommended** |
| `large` | 1550MB | Slow | Best |

### VAD Settings

```yaml
# Advanced VAD configuration (in code)
vad_aggressiveness: 2  # 0-3 (higher = more strict)
frame_duration_ms: 30  # 10, 20, or 30ms
```

## Troubleshooting

### YouTube Bot Detection

If you get "Sign in to confirm you're not a bot" errors:
1. Ensure `cookies/youtube_cookies.txt` exists
2. Re-export fresh cookies from your browser
3. Check logs for "Using cookies file" message

### CUDA Issues

```bash
# Check CUDA availability
nvidia-smi
uv run python -c "import torch; print(torch.cuda.is_available())"

# If CUDA unavailable, fall back to CPU
whisper:
  device: "cpu"
```

### Performance Issues

- Use CUDA for real-time processing
- Reduce model size for faster processing
- Check network bandwidth for live streams

## Development

```bash
# Install with development dependencies
uv pip install -e ".[dev]"

# Run with debug logging
uv run youtube2slack serve --verbose
```

## License

CC0 - Creative Commons Zero