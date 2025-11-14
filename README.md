# YouTube2Slack

Download YouTube videos, transcribe them using local Whisper, and post the transcriptions to Slack.

## Features

- Download YouTube videos using yt-dlp
- Transcribe audio using OpenAI's Whisper (local installation)
- Post transcriptions to Slack channels
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
whisper:
  model: "base"  # tiny, base, small, medium, large
  device: "cpu"  # cpu, cuda
  language: "auto"  # auto, en, ja, etc.

slack:
  webhook_url: "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
  channel: "#general"  # optional, override webhook default

download:
  output_dir: "./downloads"
  format: "best"  # best, bestaudio, etc.
  keep_video: false
```

## Usage

```bash
# Single video
youtube2slack https://www.youtube.com/watch?v=VIDEO_ID

# With custom config
youtube2slack --config my-config.yaml https://www.youtube.com/watch?v=VIDEO_ID

# Playlist
youtube2slack https://www.youtube.com/playlist?list=PLAYLIST_ID
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