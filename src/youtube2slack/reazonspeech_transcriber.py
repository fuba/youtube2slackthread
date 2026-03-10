"""ReazonSpeech K2 transcriber using sherpa-onnx."""

import os
import wave
import logging
import numpy as np
from typing import Dict, Optional, Any, Callable, List

import sherpa_onnx

from .whisper_transcriber import TranscriptionError, format_timestamp

logger = logging.getLogger(__name__)

# Default model directory name
DEFAULT_MODEL_DIR_NAME = "sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01"
MODEL_DOWNLOAD_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    "sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01.tar.bz2"
)
SILERO_VAD_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    "silero_vad.onnx"
)

SAMPLE_RATE = 16000


class ReazonSpeechTranscriber:
    """Transcribe audio using ReazonSpeech K2 via sherpa-onnx OfflineRecognizer."""

    def __init__(self, model_dir: str, num_threads: int = 2,
                 use_int8: bool = True):
        """Initialize the transcriber.

        Args:
            model_dir: Path to the extracted model directory
            num_threads: Number of CPU threads for inference
            use_int8: Use int8 quantized model for lower memory usage
        """
        self.model_dir = model_dir
        self.num_threads = num_threads
        self.use_int8 = use_int8

        suffix = ".int8" if use_int8 else ""

        encoder = os.path.join(model_dir, f"encoder-epoch-99-avg-1{suffix}.onnx")
        decoder = os.path.join(model_dir, f"decoder-epoch-99-avg-1{suffix}.onnx")
        joiner = os.path.join(model_dir, f"joiner-epoch-99-avg-1{suffix}.onnx")
        tokens = os.path.join(model_dir, "tokens.txt")

        logger.info(f"Loading ReazonSpeech K2 model from {model_dir} "
                     f"(int8={use_int8}, threads={num_threads})")

        try:
            self.recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=encoder,
                decoder=decoder,
                joiner=joiner,
                tokens=tokens,
                num_threads=num_threads,
                sample_rate=SAMPLE_RATE,
                feature_dim=80,
                decoding_method="greedy_search",
            )
        except Exception as e:
            raise TranscriptionError(f"Failed to load ReazonSpeech model: {e}")

        logger.info("ReazonSpeech K2 model loaded successfully")

    def transcribe(self, audio_path: str, language: Optional[str] = None,
                   include_timestamps: bool = True,
                   progress_callback: Optional[Callable[[float], None]] = None) -> Dict[str, Any]:
        """Transcribe audio file.

        Args:
            audio_path: Path to audio file (WAV 16kHz mono expected)
            language: Ignored (ReazonSpeech is Japanese-only)
            include_timestamps: Whether to include timestamp info
            progress_callback: Optional progress callback (not used)

        Returns:
            Dictionary with transcription results

        Raises:
            TranscriptionError: If transcription fails
        """
        if not os.path.exists(audio_path):
            raise TranscriptionError(f"Audio file not found: {audio_path}")

        try:
            samples = self._load_audio(audio_path)

            stream = self.recognizer.create_stream()
            stream.accept_waveform(SAMPLE_RATE, samples)
            self.recognizer.decode_stream(stream)

            text = stream.result.text.strip()

            duration = len(samples) / SAMPLE_RATE
            result = {
                "text": text,
                "language": "ja",
                "segments": [],
            }

            if include_timestamps and text:
                result["segments"].append({
                    "start": 0.0,
                    "end": duration,
                    "text": text,
                    "start_formatted": format_timestamp(0.0),
                    "end_formatted": format_timestamp(duration),
                })
                result["timing"] = {
                    "duration": duration,
                    "duration_formatted": format_timestamp(duration),
                }

            logger.info(f"Transcription completed: {text[:80]}...")
            return result

        except TranscriptionError:
            raise
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise TranscriptionError(f"Transcription failed: {e}")

    def _load_audio(self, audio_path: str) -> np.ndarray:
        """Load audio file as float32 numpy array.

        Handles WAV files directly. For other formats, uses ffmpeg.
        """
        ext = os.path.splitext(audio_path)[1].lower()

        if ext == ".wav":
            return self._load_wav(audio_path)
        else:
            return self._load_with_ffmpeg(audio_path)

    def _load_wav(self, wav_path: str) -> np.ndarray:
        """Load WAV file as float32 array."""
        with wave.open(wav_path, "rb") as wf:
            assert wf.getnchannels() == 1, "Expected mono audio"
            assert wf.getsampwidth() == 2, "Expected 16-bit audio"
            sr = wf.getframerate()
            frames = wf.readframes(wf.getnframes())

        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

        # Resample if necessary
        if sr != SAMPLE_RATE:
            logger.warning(f"Resampling from {sr}Hz to {SAMPLE_RATE}Hz")
            ratio = SAMPLE_RATE / sr
            new_length = int(len(samples) * ratio)
            indices = np.linspace(0, len(samples) - 1, new_length)
            samples = np.interp(indices, np.arange(len(samples)), samples).astype(np.float32)

        return samples

    def _load_with_ffmpeg(self, audio_path: str) -> np.ndarray:
        """Load audio using ffmpeg, outputting 16kHz mono PCM."""
        import subprocess

        cmd = [
            "ffmpeg", "-i", audio_path,
            "-vn", "-acodec", "pcm_s16le",
            "-ar", str(SAMPLE_RATE), "-ac", "1",
            "-f", "wav", "pipe:1",
        ]

        result = subprocess.run(cmd, capture_output=True, check=True)
        # Skip WAV header (44 bytes)
        pcm_data = result.stdout[44:]
        return np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0

    def get_model_info(self) -> Dict[str, Any]:
        """Get model information."""
        return {
            "model_name": "reazonspeech-k2",
            "device": "cpu",
            "service": "local",
            "num_threads": self.num_threads,
            "use_int8": self.use_int8,
            "model_dir": self.model_dir,
        }

    def get_available_models(self) -> List[str]:
        """Get list of available models."""
        return ["reazonspeech-k2-v2"]
