# 🚀 Quick Setup Guide for YouTube2SlackThread

## 📋 Prerequisites

- Python 3.8+
- FFmpeg (for video processing)
- Slack workspace with admin permissions

## 🔧 Step-by-Step Setup

### 1. Install YouTube2SlackThread

```bash
git clone <repository-url>
cd youtube2slackthread
uv pip install -e .
```

### 2. Create Slack App

1. **Go to https://api.slack.com/apps**
2. **Click "Create New App" → "From scratch"**
3. **Choose your workspace**

### 3. Configure Bot Permissions

1. **Go to "OAuth & Permissions"**
2. **Add Bot Token Scopes:**
   - `chat:write`
   - `channels:read` 
   - `commands` (if using slash commands)

3. **Click "Install to Workspace"**
4. **Copy the Bot User OAuth Token** (starts with `xoxb-`)

### 4. Set Environment Variables

```bash
export SLACK_BOT_TOKEN="xoxb-your-token-here"
export SLACK_SIGNING_SECRET="your-signing-secret-here"
```

### 5. Test Basic Functionality

```bash
# Test thread creation
youtube2slack thread "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --channel general
```

### 6. (Optional) Set up Slash Commands

1. **In your Slack app, go to "Slash Commands"**
2. **Create New Command:**
   - Command: `/youtube2thread`
   - Request URL: `https://your-domain.com/slack/commands`
   - Description: "Process YouTube video in thread"
   
3. **Start the server:**
```bash
youtube2slack serve --port 3000
```

4. **Make your server publicly accessible** (using ngrok, etc.)

## ✅ Verification

### Test Thread Mode
```bash
youtube2slack thread "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --channel general
```

You should see:
- ✅ A new thread created in #general
- ✅ Video header with title and metadata  
- ✅ Processing status updates
- ✅ Final transcription

### Test Slash Command
```
/youtube2thread https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

You should see:
- ✅ Immediate "Starting to process..." response
- ✅ Background processing starts
- ✅ Thread created automatically

## 🔍 Troubleshooting

### Common Issues

**❌ "SLACK_BOT_TOKEN environment variable is required"**
- Make sure you exported the bot token
- Check the token starts with `xoxb-`

**❌ "Channel not found"**  
- Ensure bot is invited to the channel
- Use channel name without `#` prefix

**❌ "Invalid request signature"**
- Check your `SLACK_SIGNING_SECRET`
- Ensure your webhook URL is correct

**❌ "Permission denied" errors**
- Verify bot has `chat:write` and `channels:read` scopes
- Re-install app to workspace if needed

### Debug Mode

```bash
# Enable verbose logging
youtube2slack --verbose thread <url> --channel general

# Check server logs
youtube2slack serve --debug
```

## 📚 Next Steps

- Configure `config.yaml` for custom settings
- Set up production deployment with proper HTTPS
- Explore VAD streaming for live content
- Add the bot to more channels

## ⚙️ Advanced Configuration

### Local Whisper Access Restriction

You can restrict local Whisper usage to specific users in `config.yaml`:

```yaml
whisper:
  model: "medium"
  device: "cuda"
  allowed_local_users:              # Slack User IDs allowed to use local Whisper
    - "U1234567890"                 # Replace with actual Slack User IDs
    - "U0987654321" 
  # If allowed_local_users is empty or null, all users can use local Whisper
  # If specified, only listed users can use local Whisper (others must use OpenAI API)
```

**To find Slack User IDs:**
1. Go to user's profile in Slack
2. Click "More" → "Copy member ID"
3. Add the ID to `allowed_local_users` list

**Note:** Users without local Whisper access must set up OpenAI API keys via DM:
```
/set-openai-key sk-your-api-key-here
```

## 🆘 Need Help?

- Check the main README.md for detailed documentation
- Run tests: `uv run python -m pytest`
- Enable debug logging with `--verbose` flag