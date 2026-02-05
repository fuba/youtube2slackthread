"""Web UI templates for YouTube2SlackThread settings interface."""

# Base styles for all templates
BASE_STYLES = """
    body {
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        margin: 0;
        padding: 20px;
        min-height: 100vh;
    }
    .container {
        max-width: 800px;
        margin: 0 auto;
        background: white;
        border-radius: 12px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
        overflow: hidden;
    }
    .header {
        background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
        color: white;
        padding: 30px;
        text-align: center;
    }
    .header h1 {
        margin: 0;
        font-size: 28px;
        font-weight: 600;
    }
    .header p {
        margin: 8px 0 0;
        opacity: 0.9;
    }
    .content {
        padding: 30px;
    }
    .form-group {
        margin-bottom: 20px;
    }
    .form-group label {
        display: block;
        margin-bottom: 8px;
        font-weight: 500;
        color: #333;
    }
    .form-group input, .form-group select, .form-group textarea {
        width: 100%;
        padding: 12px;
        border: 2px solid #e1e5e9;
        border-radius: 6px;
        font-size: 14px;
        transition: border-color 0.3s ease;
        box-sizing: border-box;
    }
    .form-group input:focus, .form-group select:focus, .form-group textarea:focus {
        outline: none;
        border-color: #4facfe;
    }
    button {
        background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
        color: white;
        border: none;
        padding: 12px 24px;
        border-radius: 6px;
        font-size: 16px;
        font-weight: 500;
        cursor: pointer;
        transition: transform 0.2s ease;
        margin-right: 10px;
    }
    button:hover {
        transform: translateY(-1px);
    }
    .btn-danger {
        background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%);
    }
    .alert {
        padding: 15px;
        margin-bottom: 20px;
        border-radius: 4px;
    }
    .alert-success {
        background: #d4edda;
        border: 1px solid #c3e6cb;
        color: #155724;
    }
    .alert-error {
        background: #f8d7da;
        border: 1px solid #f5c6cb;
        color: #721c24;
    }
    .alert-info {
        background: #cce7ff;
        border: 1px solid #99d6ff;
        color: #004085;
    }
    .settings-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 20px;
    }
    @media (max-width: 600px) {
        .settings-grid {
            grid-template-columns: 1fr;
        }
    }
    .current-value {
        color: #666;
        font-style: italic;
        margin-top: 5px;
    }
    .security-note {
        background: #fff3cd;
        border: 1px solid #ffeaa7;
        color: #856404;
        padding: 15px;
        border-radius: 4px;
        margin-bottom: 20px;
    }
"""

ERROR_TEMPLATE = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{{{ title }}}} - YouTube2SlackThread</title>
    <style>
        {BASE_STYLES}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔧 {{{{ title }}}}</h1>
            <p>YouTube2SlackThread Settings</p>
        </div>
        
        <div class="content">
            <div style="text-align: center;">
                <h2>❌ {{{{ error_title }}}}</h2>
                <p>{{{{ error_message }}}}</p>
                
                <div style="margin-top: 30px;">
                    <p>To get a new settings page URL, send a DM to the YouTube2SlackThread bot:</p>
                    <code>/web-settings</code>
                </div>
            </div>
            
            <div style="margin-top: 40px; text-align: center; color: #666;">
                <p>🔒 This is a secure, temporary access page. The URL will expire automatically.</p>
            </div>
        </div>
    </div>
</body>
</html>
"""

SETTINGS_TEMPLATE = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{{{ title }}}} - YouTube2SlackThread</title>
    <style>
        {BASE_STYLES}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔧 {{{{ title }}}}</h1>
            <p>YouTube2SlackThread Personal Settings</p>
        </div>
        
        <div class="content">
            {{% if messages %}}
                {{% for message in messages %}}
                    <div class="alert alert-{{{{ message.category }}}}">
                        {{{{ message.message }}}}
                    </div>
                {{% endfor %}}
            {{% endif %}}

            <div class="security-note">
                <strong>🔐 Security Notice:</strong> This page provides secure access to your personal YouTube2SlackThread settings. 
                Your API keys are encrypted and stored securely.
            </div>

            <form method="POST" enctype="multipart/form-data">
                <div class="settings-grid">
                    <div>
                        <div class="form-group">
                            <label for="whisper_service">Whisper Service</label>
                            <select name="whisper_service" id="whisper_service">
                                <option value="local" {{% if settings.whisper_service.value == 'local' %}}selected{{% endif %}}>
                                    🖥️ Local Whisper (Free)
                                </option>
                                <option value="openai" {{% if settings.whisper_service.value == 'openai' %}}selected{{% endif %}}>
                                    🤖 OpenAI API (Requires API Key)
                                </option>
                            </select>
                            <div class="current-value">
                                Current: {{{{ settings.whisper_service.value|title }}}}
                                {{% if not local_allowed and settings.whisper_service.value == 'local' %}}
                                    ⚠️ Local Whisper not permitted for your account
                                {{% endif %}}
                            </div>
                        </div>
                        
                        <div class="form-group">
                            <label for="whisper_model">Local Whisper Model</label>
                            <select name="whisper_model" id="whisper_model">
                                <option value="tiny" {{% if settings.whisper_model == 'tiny' %}}selected{{% endif %}}>Tiny (fastest, least accurate)</option>
                                <option value="base" {{% if settings.whisper_model == 'base' %}}selected{{% endif %}}>Base (balanced)</option>
                                <option value="small" {{% if settings.whisper_model == 'small' %}}selected{{% endif %}}>Small (good quality)</option>
                                <option value="medium" {{% if settings.whisper_model == 'medium' %}}selected{{% endif %}}>Medium (better quality)</option>
                                <option value="large" {{% if settings.whisper_model == 'large' %}}selected{{% endif %}}>Large (best quality, slowest)</option>
                            </select>
                            <div class="current-value">
                                Current: {{{{ settings.whisper_model|title }}}}
                            </div>
                        </div>
                        
                        <div class="form-group">
                            <label for="whisper_language">Language (optional)</label>
                            <select name="whisper_language" id="whisper_language">
                                <option value="" {{% if not settings.whisper_language %}}selected{{% endif %}}>Auto-detect</option>
                                <option value="en" {{% if settings.whisper_language == 'en' %}}selected{{% endif %}}>English</option>
                                <option value="ja" {{% if settings.whisper_language == 'ja' %}}selected{{% endif %}}>Japanese</option>
                                <option value="es" {{% if settings.whisper_language == 'es' %}}selected{{% endif %}}>Spanish</option>
                                <option value="fr" {{% if settings.whisper_language == 'fr' %}}selected{{% endif %}}>French</option>
                                <option value="de" {{% if settings.whisper_language == 'de' %}}selected{{% endif %}}>German</option>
                            </select>
                            <div class="current-value">
                                Current: {{{{ settings.whisper_language or 'Auto-detect' }}}}
                            </div>
                        </div>
                    </div>
                    
                    <div>
                        <div class="form-group">
                            <label for="openai_api_key">OpenAI API Key</label>
                            <input type="password" name="openai_api_key" id="openai_api_key" 
                                   placeholder="sk-..." autocomplete="new-password">
                            <div class="current-value">
                                {{% if has_openai_key %}}
                                    ✅ API key is set (leave empty to keep current)
                                {{% else %}}
                                    ❌ No API key configured
                                {{% endif %}}
                            </div>
                        </div>
                        
                        <div class="form-group">
                            <label>
                                <input type="checkbox" name="include_timestamps" 
                                       {{% if settings.include_timestamps %}}checked{{% endif %}}>
                                Include timestamps in transcripts
                            </label>
                        </div>
                        
                        <div class="form-group">
                            <label>YouTube Cookies Status</label>
                            <div class="current-value">
                                {{% if has_cookies %}}
                                    ✅ YouTube cookies are configured
                                {{% else %}}
                                    ❌ No YouTube cookies configured
                                {{% endif %}}
                            </div>
                        </div>

                        <div class="form-group">
                            <label for="cookies_file">Upload YouTube Cookies File</label>
                            <input type="file" id="cookies_file" name="cookies_file" accept=".txt">
                            <div class="hint">
                                Upload a Netscape HTTP Cookie file (cookies.txt) from your browser.
                                Use a browser extension like "Get cookies.txt LOCALLY" to export cookies.
                            </div>
                        </div>
                    </div>
                </div>

                <div style="margin-top: 30px;">
                    <button type="submit">💾 Save Settings</button>
                    <button type="button" class="btn-danger" onclick="deleteApiKey()">🗑️ Remove API Key</button>
                    {{% if has_cookies %}}
                    <button type="button" class="btn-danger" onclick="deleteCookies()">🍪 Remove Cookies</button>
                    {{% endif %}}
                </div>
            </form>
            
            <div style="margin-top: 40px; text-align: center; color: #666;">
                <p>🔒 This is a secure, temporary access page. The URL will expire automatically.</p>
            </div>
        </div>
    </div>
    
    <script>
    function deleteApiKey() {{
        if (confirm('Are you sure you want to remove your OpenAI API key?')) {{
            fetch(window.location.href, {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/x-www-form-urlencoded',
                }},
                body: 'delete_api_key=1'
            }}).then(response => {{
                if (response.ok) {{
                    window.location.reload();
                }}
            }});
        }}
    }}

    function deleteCookies() {{
        if (confirm('Are you sure you want to remove your YouTube cookies?')) {{
            fetch(window.location.href, {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/x-www-form-urlencoded',
                }},
                body: 'delete_cookies=1'
            }}).then(response => {{
                if (response.ok) {{
                    window.location.reload();
                }}
            }});
        }}
    }}

    // Auto-disable local whisper option if restricted
    document.addEventListener('DOMContentLoaded', function() {{
        const localAllowed = {{{{ local_allowed|tojson }}}};
        const serviceSelect = document.getElementById('whisper_service');
        
        if (!localAllowed) {{
            // If local is currently selected but not allowed, switch to OpenAI
            if (serviceSelect.value === 'local') {{
                serviceSelect.value = 'openai';
            }}
            // Disable local option
            const localOption = serviceSelect.querySelector('option[value="local"]');
            if (localOption) {{
                localOption.disabled = true;
                localOption.textContent += ' (Not Permitted)';
            }}
        }}
    }});
    </script>
</body>
</html>
"""