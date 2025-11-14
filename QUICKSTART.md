# ⚡ Quick Start Guide

## 🚀 最も簡単な方法（5分でセットアップ）

### 1. Slack Botトークンを取得

1. https://api.slack.com/apps にアクセス
2. "Create New App" → "From scratch"
3. "OAuth & Permissions" で以下のスコープを追加：
   - `chat:write`
   - `channels:read`
   - `commands`
4. "Install to Workspace"
5. **Bot User OAuth Token** をコピー (xoxb- で始まる)
6. **Signing Secret** をコピー (Basic Information > App Credentials)

### 2. 環境変数を設定

```bash
# .env ファイルを作成
cp .env.example .env

# 以下の値を編集
SLACK_BOT_TOKEN=xoxb-your-token-here
SLACK_SIGNING_SECRET=your-secret-here
SLACK_DEFAULT_CHANNEL=general
```

### 3. サーバーを起動

```bash
# 自動デプロイスクリプトを実行
./scripts/deploy.sh
```

または手動で：

```bash
# 依存関係をインストール
uv pip install -e .

# サーバーを起動
uv run python -m youtube2slack serve
```

### 4. Slack アプリを設定

1. Slack アプリの管理画面に戻る
2. "Slash Commands" → "Create New Command"
3. 以下を設定：
   - **Command**: `/youtube2thread`
   - **Request URL**: `https://your-domain.com/slack/commands`
   - **Description**: `Process YouTube video in thread`

### 5. テスト

Slackで以下を実行：
```
/youtube2thread https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

## 🐳 Dockerでの起動（推奨）

```bash
# 1. 環境変数を設定
cp .env.example .env
# .env を編集

# 2. Docker Composeで起動
docker-compose up -d

# 3. ヘルスチェック
curl http://localhost/health
```

## 🔧 本番環境での設定

### SSL証明書の設定

```bash
# Let's Encrypt証明書を取得
sudo certbot --nginx -d your-domain.com

# nginx設定でSSL部分をアンコメント
```

### Systemdサービス（Linux）

```bash
# サービスファイルを作成
sudo cp scripts/youtube2slack.service /etc/systemd/system/
sudo systemctl enable youtube2slack
sudo systemctl start youtube2slack
```

## 📱 使用方法

### CLI モード
```bash
# 動画を直接処理してスレッド作成
youtube2slack thread "https://youtube.com/watch?v=VIDEO_ID" --channel general

# サーバーモード開始
youtube2slack serve --port 3000
```

### Slack スラッシュコマンド
```
/youtube2thread https://youtube.com/watch?v=VIDEO_ID
```

## 🎯 動作確認

✅ **成功時の表示:**
- Slackに新しいスレッドが作成される
- 動画のタイトル、時間、言語が表示される
- 処理状況がリアルタイムで更新される
- 最終的に転写テキストが投稿される

❌ **失敗時のトラブルシューティング:**

| 問題 | 原因 | 解決方法 |
|------|------|----------|
| "SLACK_BOT_TOKEN is required" | 環境変数未設定 | `.env`ファイルを確認 |
| "Channel not found" | チャンネルにBotが未招待 | `/invite @your-bot-name` |
| "Invalid request signature" | Signing Secret間違い | Slack app設定を確認 |
| 404エラー | Webhook URL間違い | Request URLを確認 |

## 📋 チェックリスト

- [ ] Slack Botトークン取得済み
- [ ] `.env`ファイル設定済み  
- [ ] サーバーが起動している（ヘルスチェック通過）
- [ ] Slack アプリにSlash Command設定済み
- [ ] BotがSlackワークスペースにインストール済み
- [ ] Botが対象チャンネルに招待済み
- [ ] ドメイン・SSL設定済み（本番環境のみ）

## 🆘 サポート

- ログを確認: `docker-compose logs` または `tail -f logs/youtube2slack.log`
- ヘルスチェック: `curl http://localhost:3000/health`
- テスト実行: `uv run python -m pytest`

詳細は `DEPLOYMENT.md` と `README.md` を参照してください。