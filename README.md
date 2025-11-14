# YouTube2Slack

Download YouTube videos, transcribe them using local Whisper, and post the transcriptions to Slack.

## Features

- Download YouTube videos using yt-dlp
- Transcribe audio using OpenAI's Whisper (local installation)
- Post transcriptions to Slack channels
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

Create a `config.yaml` file:

```yaml
# YouTube2Slack Configuration
youtube:
  download_dir: "./downloads"
  format: "best"
  keep_video: true

whisper:
  model: "medium"  # tiny, base, small, medium, large
  device: null  # cpu, cuda, or null for auto
  language: null  # auto-detect or specify (en, ja, etc.)

slack:
  webhook_url: "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
  channel: null  # optional channel override
  include_timestamps: false
  send_errors_to_slack: true
```

## Usage

### Basic Video Processing

```bash
# Single video
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

## Development

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=youtube2slack

# Format code
black src tests

# Type checking
mypy src
```

## License

CC0 - Creative Commons Zero