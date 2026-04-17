# ReazonSpeech K2 + sherpa-onnx Integration

## Overview

Added ReazonSpeech K2 as an alternative transcription engine to OpenAI Whisper.
Uses sherpa-onnx for inference with Silero VAD for speech detection.

## Architecture

```
FFmpeg (16kHz PCM) → Silero VAD (32ms windows) → ReazonSpeech K2 OfflineRecognizer → Sentence Detection → Slack
```

- **Silero VAD**: Detects speech/silence boundaries with 512-sample (32ms) windows
- **ReazonSpeech K2**: Offline Transducer model (Zipformer + RNN-T), trained on 35,000 hours of Japanese audio
- **sherpa-onnx**: ONNX Runtime based inference, CPU-optimized

## Key Differences from Whisper Pipeline

| Aspect | Whisper (old) | ReazonSpeech (new) |
|--------|--------------|-------------------|
| VAD | webrtcvad (30ms frames) | Silero VAD (32ms windows) |
| Transcription | Whisper model (GPU recommended) | ReazonSpeech K2 (CPU optimized) |
| Model size | 74MB (base) - 1.5GB (large) | 154MB (int8) |
| GPU required | Recommended for medium+ | Not required |
| Japanese quality | Good (multilingual) | Excellent (Japanese-specialized) |
| Segment handling | Manual VAD → WAV file → transcribe | VAD auto-segments → direct array transcription |
| Threading | Separate capture + worker threads | Single thread (VAD + transcribe inline) |

## Configuration

```yaml
transcriber_engine: "reazonspeech"  # or "whisper"

reazonspeech:
  model_dir: "./models/sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01"
  vad_model: "./models/silero_vad.onnx"
  num_threads: 2
  use_int8: true
```

## Model Download

```bash
bash scripts/download_reazonspeech_model.sh ./models
```

Downloads:
- `sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01` (~680MB compressed, int8: 154MB)
- `silero_vad.onnx` (~629KB)

## Files Added/Modified

- `src/youtube2slack/reazonspeech_transcriber.py` - ReazonSpeech K2 transcriber class
- `src/youtube2slack/reazonspeech_stream_processor.py` - Silero VAD + ReazonSpeech streaming
- `src/youtube2slack/workflow.py` - Added reazonspeech config fields
- `src/youtube2slack/slack_server.py` - Unified stream processor factory method
- `tests/test_reazonspeech_transcriber.py` - Unit tests
- `scripts/download_reazonspeech_model.sh` - Model download script
- `pyproject.toml` - Added sherpa-onnx, onnxruntime dependencies
- `Dockerfile` - onnxruntime library linking, models directory
