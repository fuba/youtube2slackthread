# Cookie Setup Instructions

## How to Export YouTube Cookies from Your Browser

### Method 1: Using Browser Extension (Recommended)

1. Install "Get cookies.txt LOCALLY" extension:
   - Chrome: https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc
   - Firefox: https://addons.mozilla.org/addon/cookies-txt/

2. Visit YouTube and log in to your account

3. Click the extension icon and export cookies

4. Save the file as `cookies/youtube_cookies.txt` in this project

5. Update config.yaml:
   ```yaml
   youtube:
     cookies_file: "./cookies/youtube_cookies.txt"
   ```

### Method 2: Manual Export (Advanced)

1. Open Developer Tools (F12)
2. Go to Application/Storage tab
3. Find YouTube cookies
4. Export in Netscape format

## Testing

After setting up cookies, test with:
```bash
uv run yt-dlp --cookies ./cookies/youtube_cookies.txt -g "https://www.youtube.com/watch?v=YOUR_VIDEO_ID"
```

## Security Notes

- **NEVER commit cookies to version control**
- Cookies contain authentication information
- Add `cookies/` to `.gitignore`