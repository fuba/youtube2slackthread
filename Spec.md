# youtube2slack

slack の webhook url と youtube の url を入力すると youtube live の音声をリアルタイムでテキスト化したものを文ごとに投稿する CLI tool。

## 技術選定
- go でやる
- yt-dlp で youtube の映像、音声はダウンロードする. youtube live でも https://hitoshiarakawa.com/blogs/2024/2024-07-11_downloading-youtube-live-with-yudlp/ のようにして可能。
```
$ yt-dlp --live-from-start {YouTube Live の URL}
```
- 音声は whisper で処理する。
- --lang option で言語指定可能

