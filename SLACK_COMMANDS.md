# 📋 Slack Slash Commands設定ガイド

## 🎯 コマンド一覧

### 1. `/youtube2thread` - メインコマンド
YouTubeの動画URLを処理してSlackスレッドに転写テキストを投稿します。

**設定方法:**
1. https://api.slack.com/apps にアクセス
2. あなたのアプリを選択
3. 左メニューから「Slash Commands」
4. 「Create New Command」をクリック
5. 以下を入力：

```
Command: /youtube2thread
Request URL: https://youtube2thread.fuba.dev/slack/commands
Short Description: Process YouTube video in thread
Usage Hint: [YouTube URL]
Escape channels, users, and links: ✓
```

### 2. `/youtube2thread-status` - ステータス確認コマンド
システム状態とミドルウェアの設定を確認できます。

**設定方法:**
1. 「Slash Commands」ページで「Create New Command」
2. 以下を入力：

```
Command: /youtube2thread-status
Request URL: https://youtube2thread.fuba.dev/slack/commands
Short Description: Check YouTube2SlackThread system status
Usage Hint: (no parameters needed)
Escape channels, users, and links: ✓
```

### 3. `/youtube2thread-stop` - ストリーム停止コマンド
実行中のVADストリーム処理を停止できます。

**設定方法:**
1. 「Slash Commands」ページで「Create New Command」
2. 以下を入力：

```
Command: /youtube2thread-stop
Request URL: https://youtube2thread.fuba.dev/slack/commands
Short Description: Stop active VAD stream processing
Usage Hint: [optional stream ID]
Escape channels, users, and links: ✓
```

## 📊 ステータスコマンドの出力内容

`/youtube2thread-status` を実行すると以下の情報が表示されます：

### システム情報
- **Server Time** - サーバーの現在時刻
- **System** - OS情報（Linux/Windows/Mac）
- **Python** - Pythonバージョン
- **Active Threads** - 現在処理中の動画数

### パッケージバージョン
- **slack-sdk** - Slack SDK バージョン
- **flask** - Webサーバーバージョン
- **yt-dlp** - YouTube ダウンローダーバージョン
- **whisper** - 音声認識モデルバージョン

### Bot設定
- **Bot User** - 接続中のBot名とID
- **Default Channel** - デフォルトチャンネル
- **Server Port** - 使用ポート番号
- **Webhook URL** - 設定されているWebhook URL

## 🧪 動作確認手順

### 1. ステータス確認（まずこれを実行）
```
/youtube2thread-status
```

**期待される結果:**
- 🔧 YouTube2SlackThread Status のヘッダー
- システム情報の表示
- ✅ Status: All systems operational
- 🎬 Active VAD Streams リスト

### 2. VADストリーム処理テスト
```
/youtube2thread https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

**期待される結果:**
- 「🚀 Starting VAD stream processing...」メッセージ
- 新しいスレッドの作成
- リアルタイム音声認識結果の投稿

### 3. ストリーム停止テスト
```
/youtube2thread-stop
```

**期待される結果:**
- アクティブなストリーム全体の停止
- 「🛑 Stopped X active streams.」メッセージ

## 🔍 トラブルシューティング

### よくあるエラー

| エラー | 原因 | 解決方法 |
|--------|------|----------|
| `404 Not Found` | Request URL が間違っている | URL末尾が `/slack/commands` か確認 |
| `Invalid signature` | Signing Secret が不一致 | 環境変数 `SLACK_SIGNING_SECRET` を確認 |
| `Timeout` | サーバーの応答が遅い | サーバーのログを確認 |
| `Channel not found` | Bot がチャンネルに未招待 | `/invite @bot-name` でBot を招待 |

### ログ確認方法

```bash
# サーバーログの確認
tail -f logs/server_new.log

# エラーログのみ表示
grep ERROR logs/server_new.log
```

## 🎉 設定完了チェックリスト

- [ ] `/youtube2thread` コマンドを作成
- [ ] `/youtube2thread-status` コマンドを作成
- [ ] `/youtube2thread-stop` コマンドを作成
- [ ] Request URL を正しく設定（https://youtube2thread.fuba.dev/slack/commands）
- [ ] アプリを再インストール（reinstall your app）
- [ ] Bot をチャンネルに招待
- [ ] ステータスコマンドで動作確認
- [ ] 実際の動画URLでVAD処理テスト
- [ ] ストリーム停止コマンドの動作確認