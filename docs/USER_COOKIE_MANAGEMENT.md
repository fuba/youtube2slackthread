# User Cookie Management

This feature allows users to upload their YouTube cookies via Slack DM, enabling personalized access to age-restricted or member-only content.

## Overview

The User Cookie Management system allows:
- Users to upload their YouTube cookies via Slack DM
- Secure storage of cookies with encryption
- Per-user cookie isolation
- Automatic cookie selection based on the requesting user

## Setup

### 1. Environment Variables

Set the following environment variables:

```bash
# Required for user cookie management
export COOKIE_ENCRYPTION_KEY="your-secure-encryption-key"

# Required for Socket Mode file uploads
export SLACK_APP_TOKEN="xapp-1-your-app-token"
```

Generate a secure encryption key:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 2. Slack App Configuration

1. Enable Socket Mode in your Slack app:
   - Go to your app settings at https://api.slack.com/apps
   - Navigate to "Socket Mode" under Settings
   - Enable Socket Mode
   - Generate an App-Level Token with `connections:write` scope
   - Copy the token (starts with `xapp-`)

2. Enable File Upload Events:
   - Go to "Event Subscriptions" 
   - Subscribe to bot events:
     - `file_shared` - For file uploads
     - `message.im` - For direct messages
   - Save changes

3. Update OAuth Scopes:
   - Ensure your bot has these scopes:
     - `files:read` - To download uploaded files
     - `im:history` - To read DM history
     - `chat:write` - To send DM responses

### 3. Generate Encryption Key

Generate a secure encryption key:

```python
import secrets
key = secrets.token_urlsafe(32)
print(f"COOKIE_ENCRYPTION_KEY={key}")
```

## Usage

### For Users

1. **Get your YouTube cookies:**
   - Install a browser extension like "Get cookies.txt LOCALLY" 
   - Visit youtube.com and sign in
   - Export cookies in Netscape format

2. **Send cookies to the bot:**
   - Open a direct message with the YouTube2Slack bot
   - Upload your cookies.txt file
   - The bot will confirm if cookies were saved successfully

3. **Using your cookies:**
   - When you use `/youtube2thread`, the bot will automatically use your cookies
   - This enables access to:
     - Age-restricted videos
     - Member-only content
     - Videos requiring login

### For Administrators

The system stores encrypted cookies in a SQLite database:

- Database location: `user_cookies.db`
- Temporary files: `/tmp/youtube2slack_cookies/`
- Cookies are encrypted using Fernet symmetric encryption
- Each user's cookies are isolated

## Security Considerations

1. **Encryption**: All cookies are encrypted at rest using AES-256
2. **Isolation**: Users can only use their own cookies
3. **Validation**: Only YouTube-related cookies are stored
4. **Cleanup**: Temporary files are automatically deleted after use
5. **No logging**: Cookie values are never logged

## Troubleshooting

### "Cookie management system not available"
- Check that `COOKIE_ENCRYPTION_KEY` environment variable is set
- Verify the encryption key is valid

### "Invalid cookies file format"
- Ensure the file is in Netscape HTTP Cookie format
- Check that it contains YouTube cookies
- Try re-exporting from your browser

### File uploads not working
- Verify Socket Mode is enabled
- Check that `SLACK_APP_TOKEN` is set correctly
- Ensure bot has required OAuth scopes

## Managing User Cookies

To manage cookies via CLI:

```python
from youtube2slack.user_cookie_manager import UserCookieManager

# Initialize manager
manager = UserCookieManager()

# Check if user has cookies
if manager.has_cookies("U123456"):
    print("User has cookies stored")

# Delete user cookies
manager.delete_cookies("U123456")
```