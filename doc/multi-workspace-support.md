# Multi-Workspace Support

youtube2slackthread now supports multiple Slack workspaces in a single deployment, sharing GPU/Whisper resources while isolating user data per workspace.

## Overview

- **Workspace Registration**: Database + Admin CLI (dynamic management)
- **Data Isolation**: User cookies and settings are isolated per workspace via `team_id`
- **Resource Sharing**: Single Whisper model shared across all workspaces
- **Backward Compatibility**: Existing single-workspace deployments continue to work unchanged

## Quick Start

### 1. Discover your workspace team_id

```bash
youtube2slack workspace discover
```

This will output your workspace's team_id using the current `SLACK_BOT_TOKEN`.

### 2. Migrate existing data (if you have existing user data)

```bash
youtube2slack workspace migrate --team-id T0123456789
```

This migrates existing user cookies and settings from the default team to the specified workspace.

### 3. (Optional) Add additional workspaces

```bash
youtube2slack workspace add \
  --team-id T0123456789 \
  --team-name "My Workspace" \
  --bot-token xoxb-... \
  --signing-secret ... \
  --app-token xapp-...  # Optional, for Socket Mode
```

## CLI Commands

### `youtube2slack workspace list`

List all registered workspaces.

```bash
youtube2slack workspace list
youtube2slack workspace list --all  # Include inactive workspaces
```

### `youtube2slack workspace add`

Add a new workspace.

```bash
youtube2slack workspace add \
  --team-id T0123456789 \
  --team-name "My Workspace" \
  --bot-token xoxb-... \
  --signing-secret ... \
  --app-token xapp-...
```

Options:
- `--team-id`: Slack team ID (required)
- `--team-name`: Human-readable team name (required)
- `--bot-token`: Slack Bot User OAuth Token (required)
- `--signing-secret`: Slack app signing secret (required)
- `--app-token`: Slack App-Level Token for Socket Mode (optional)

### `youtube2slack workspace remove`

Remove a workspace.

```bash
youtube2slack workspace remove --team-id T0123456789
youtube2slack workspace remove --team-id T0123456789 --force  # Skip confirmation
```

### `youtube2slack workspace migrate`

Migrate user data to a specific workspace.

```bash
youtube2slack workspace migrate --team-id T0123456789
youtube2slack workspace migrate --team-id T0123456789 --from-team-id T9876543210
```

### `youtube2slack workspace discover`

Discover team_id from current SLACK_BOT_TOKEN.

```bash
youtube2slack workspace discover
```

### `youtube2slack workspace activate/deactivate`

Activate or deactivate a workspace.

```bash
youtube2slack workspace activate --team-id T0123456789
youtube2slack workspace deactivate --team-id T0123456789
```

## Database Schema

### workspaces table

```sql
CREATE TABLE workspaces (
    team_id TEXT PRIMARY KEY,
    team_name TEXT NOT NULL,
    encrypted_bot_token BLOB NOT NULL,
    encrypted_app_token BLOB,
    encrypted_signing_secret BLOB NOT NULL,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### user_cookies table (updated)

```sql
CREATE TABLE user_cookies (
    team_id TEXT NOT NULL DEFAULT '_default_',
    user_id TEXT NOT NULL,
    encrypted_cookies BLOB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (team_id, user_id)
);
```

### user_settings table (updated)

```sql
CREATE TABLE user_settings (
    team_id TEXT NOT NULL DEFAULT '_default_',
    user_id TEXT NOT NULL,
    encrypted_settings BLOB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (team_id, user_id)
);
```

## Automatic Migration

When the server starts with an existing database (without team_id columns), it automatically:

1. Creates the `workspaces` table
2. Adds `team_id` column to `user_cookies` and `user_settings`
3. Sets `_default_` as the team_id for existing records
4. Creates indexes for faster lookups

To migrate to a real team_id, run:

```bash
youtube2slack workspace migrate --team-id <your_team_id>
```

## Architecture

### WorkspaceManager

Handles database operations for workspace configurations:
- CRUD operations for workspaces
- Encrypted storage of tokens and secrets
- Active/inactive workspace management

### WorkspaceRegistry

Runtime registry for Slack clients:
- Manages WebClient instances per workspace
- Handles Socket Mode connections for all workspaces
- Provides client lookup by team_id

## Backward Compatibility

- If no workspaces are registered in the database, the system falls back to environment variables (`SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_APP_TOKEN`)
- Single workspace mode continues to work unchanged
- The default team_id `_default_` is used when no team_id is specified

## Environment Variables

| Variable | Description |
|----------|-------------|
| `SLACK_BOT_TOKEN` | Slack Bot User OAuth Token (fallback for single-workspace mode) |
| `SLACK_SIGNING_SECRET` | Slack app signing secret (fallback for single-workspace mode) |
| `SLACK_APP_TOKEN` | Slack App-Level Token for Socket Mode (optional) |
| `COOKIE_ENCRYPTION_KEY` | Encryption key for storing sensitive data (required) |
| `USER_COOKIES_DB_PATH` | Path to SQLite database file (default: `user_cookies.db`) |
