# SPDX-License-Identifier: MIT
"""Replay a local recording through the production pipeline without Slack writes."""

import argparse
import json
import os
import sys
import time
import wave

from youtube2slack.user_cookie_manager import UserSettings
from youtube2slack.vad_stream_processor import VADStreamProcessor
from youtube2slack.whisper_transcriber import TranscriberFactory
from youtube2slack.workflow import WorkflowConfig


class AudioReplay:
    def __init__(self, audio, realtime):
        self.audio = audio
        self.realtime = realtime
        self.started = time.monotonic()
        self.samples = 0

    def read(self, size):
        data = self.audio.readframes(size // 2)
        self.samples += len(data) // 2
        if self.realtime:
            # Keep the original sample clock even when inference falls behind.
            delay = self.started + self.samples / 16000 - time.monotonic()
            if delay > 0:
                time.sleep(delay)
        return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio', help='16 kHz mono PCM16 WAV recording')
    parser.add_argument('--config', required=True)
    parser.add_argument('--user-id', required=True, help='User context for the existing ASR permission check')
    parser.add_argument('--output', required=True, help='New private JSONL file; includes source and translation')
    parser.add_argument('--realtime', action='store_true')
    args = parser.parse_args(argv)
    config = WorkflowConfig.from_yaml(args.config)
    # Evaluation uses configured models, without reading cookies or a user's stored API key.
    settings = UserSettings(whisper_model=config.whisper_model)
    transcriber = TranscriberFactory.create_transcriber(settings, config, args.user_id)
    with wave.open(args.audio, 'rb') as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
            parser.error('Input must be 16 kHz mono PCM16 WAV')
        duration = audio.getnframes() / 16000
        # Exclusive creation prevents replacing an earlier experiment.
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
            started = time.monotonic()

            def record(result):
                elapsed = time.monotonic() - started
                row = dict(result, event='segment', emitted_seconds=elapsed)
                if args.realtime:
                    row['end_to_emit_seconds'] = elapsed - result['end']
                output.write(json.dumps(row, ensure_ascii=False) + '\n')
                output.flush()

            processor = VADStreamProcessor(transcriber, result_callback=record,
                                           **config.stream_processor_options())
            processor.is_running = True
            failure = None
            try:
                processor.process_pcm_stream(AudioReplay(audio, args.realtime))
            except Exception:
                failure = 'processing_failed'
            finally:
                processor.is_running = False
                processor._cleanup_temp_dir()
            status = processor.get_status()
            failed = bool(failure or status['translation_failures'] or status['endpoint_failures'])
            summary = dict(event='summary', success=not failed, error=failure,
                           duration=duration, elapsed_seconds=time.monotonic() - started,
                           asr_backend=config.asr_backend,
                           asr_model=(config.asr_model if config.asr_backend == 'compatible'
                                      else config.whisper_model),
                           translation_model=config.translation_model,
                           target_language=config.translation_target_language,
                           segmentation_model=config.segmentation_model,
                           pause_duration=config.pause_duration,
                           max_silence_duration=config.max_silence_duration,
                           max_segment_duration=config.max_segment_duration,
                           semantic=config.semantic_segmentation, realtime=args.realtime,
                           **{key: status[key] for key in (
                               'asr_requests', 'asr_seconds', 'translation_failures',
                               'endpoint_failures', 'forced_segments', 'posted_segments')})
            output.write(json.dumps(summary) + '\n')
            print(json.dumps(summary))
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
