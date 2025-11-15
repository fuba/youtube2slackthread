# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- **Smart Retry System**: Thread-based retry functionality for failed processing
  - Type `retry`, `restart`, `再開`, or `リトライ` in any thread to restart processing
  - Intelligent detection of already-running vs failed processes
  - Maintains original URL, user cookies, and configuration settings
  - User-friendly Japanese/English feedback messages

- **Smart Stop System**: Thread-based stop functionality for active processing
  - Type `stop`, `halt`, `停止`, or `ストップ` in any thread to stop processing
  - Safe processor shutdown with proper resource cleanup
  - Clear status feedback and suggestions for restart
  - Prevention of duplicate stop attempts

- **Enhanced Status Command**: Improved `/youtube2thread-status` command
  - Shows active streams vs running streams
  - Modern `importlib.metadata` for package version detection
  - Rich block-formatted status display in Socket Mode

### Improved
- **Thread Message Detection**: Socket Mode event handling for thread messages
- **Stream State Management**: Better tracking of processing state and errors
- **User Experience**: Clear emoji-based feedback for retry actions

### Fixed
- Deprecated `pkg_resources` warnings replaced with `importlib.metadata`
- Better error state tracking for failed streams

## [Previous Versions]

See git history for previous changes.