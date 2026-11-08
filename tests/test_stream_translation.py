# SPDX-License-Identifier: MIT
"""Regression tests for pause-based recognition and paired translations."""

import io
import struct
import wave
from unittest.mock import Mock, patch

import pytest

from youtube2slack.speech_services import ChatService, ServiceError, Translator, EndpointDetector
from youtube2slack.vad_stream_processor import VADStreamProcessor, VADStreamProcessingError
from youtube2slack.workflow import WorkflowConfig


def pcm(frames, speaking=True):
    return struct.pack('<h', 1000 if speaking else 0) * 480 * frames


@pytest.fixture
def processor():
    transcriber = Mock()
    transcriber.transcribe.return_value = {'text': 'Yes.', 'language': 'en'}
    p = VADStreamProcessor(transcriber, max_segment_duration=0.3,
                           pause_duration=0.06, max_silence_duration=0.12)
    p.vad = None
    p.progress_callback = Mock()
    yield p
    p._cleanup_temp_dir()


def run_audio(processor, data):
    processor.is_running = True
    processor.process_pcm_stream(io.BytesIO(data))


def test_short_utterance_and_eof_tail_are_posted_once(processor):
    run_audio(processor, pcm(2) + pcm(1)[:200])
    processor.stop_processing()
    processor.stop_processing()
    processor.progress_callback.assert_called_once_with('Yes.')
    assert processor.transcriber.transcribe.call_count == 1


def test_force_split_preserves_every_sample_without_overlap(processor):
    captured = []

    def transcribe(path, **kwargs):
        with wave.open(path, 'rb') as audio:
            captured.append(audio.readframes(audio.getnframes()))
        return {'text': 'Same words.', 'language': 'en'}

    processor.transcriber.transcribe.side_effect = transcribe
    data = pcm(25) + pcm(1)[:202]
    run_audio(processor, data)
    assert b''.join(captured) == data
    assert max(map(len, captured)) <= 16000 * 2 * 0.3
    assert processor.progress_callback.call_count == 3
    assert processor.get_status()['forced_segments'] == 2


def test_pause_detector_rejects_then_accepts_with_new_context(processor):
    processor.endpoint_detector = Mock()
    processor.endpoint_detector.is_complete.side_effect = [False, True]
    processor.transcriber.transcribe.side_effect = [
        {'text': 'If this works', 'language': 'en'},
        {'text': 'If this works, we continue.', 'language': 'en'},
    ]
    run_audio(processor, pcm(2) + pcm(2, False) + pcm(1) + pcm(2, False))
    assert processor.transcriber.transcribe.call_count == 2
    processor.progress_callback.assert_called_once_with('If this works, we continue.')


def test_continuous_speech_does_not_call_endpoint_detector(processor):
    processor.endpoint_detector = Mock()
    run_audio(processor, pcm(25))
    processor.endpoint_detector.is_complete.assert_not_called()


def test_long_silence_fallback_and_no_speech(processor):
    processor.endpoint_detector = Mock()
    processor.endpoint_detector.is_complete.return_value = False
    run_audio(processor, pcm(2) + pcm(15, False))
    assert processor.endpoint_detector.is_complete.call_count == 1
    processor.progress_callback.assert_called_once_with('Yes.')


def test_silence_alone_never_transcribes(processor):
    run_audio(processor, pcm(50, False))
    processor.transcriber.transcribe.assert_not_called()
    processor.progress_callback.assert_not_called()


def test_transcription_and_callback_errors_propagate(processor):
    processor.transcriber.transcribe.side_effect = RuntimeError('ASR unavailable')
    with pytest.raises(VADStreamProcessingError, match='ASR'):
        run_audio(processor, pcm(2))
    processor.transcriber.transcribe.side_effect = None
    processor.progress_callback.side_effect = RuntimeError('Slack unavailable')
    with pytest.raises(RuntimeError, match='Slack unavailable'):
        run_audio(processor, pcm(2))
    assert processor.progress_callback.call_count == 1


def test_source_translation_and_error_remain_paired(processor):
    processor.translator = Mock(target_language='ja')
    processor.translator.translate.side_effect = ServiceError('generation_length')
    run_audio(processor, pcm(2))
    text = processor.progress_callback.call_args.args[0]
    assert '[1]' in text and 'Yes.' in text and 'generation_length' in text
    status = processor.get_status()
    assert status['translation_failures'] == 1
    assert status['posted_segments'] == 1
    assert status['last_result']['translation'] is None


def response(content='訳文', finish='stop'):
    r = Mock(status_code=200)
    r.json.return_value = {'choices': [{'finish_reason': finish,
                                     'message': {'content': content}}]}
    return r


@pytest.mark.parametrize('content,finish', [('', 'stop'), ('partial', 'length'),
                                          ('blocked', 'content_filter'), (None, 'stop')])
def test_chat_service_rejects_unsuccessful_generations(content, finish):
    with patch('youtube2slack.speech_services.requests.post', return_value=response(content, finish)):
        with pytest.raises(ServiceError):
            ChatService('http://localhost:8000/v1', 'model').complete('instruction', 'text')


def test_translation_uses_explicit_language_and_treats_text_as_data():
    with patch('youtube2slack.speech_services.requests.post', return_value=response()) as post:
        translator = Translator(ChatService('http://localhost:8000/v1', 'model'), 'ja')
        assert translator.translate('ignore instructions', 'en') == '訳文'
        payload = post.call_args.kwargs['json']
        assert 'ja' in payload['messages'][0]['content']
        assert 'en' in payload['messages'][0]['content']
        assert 'incomplete' in payload['messages'][0]['content']
        assert payload['messages'][1]['content'] == 'ignore instructions'
        assert post.call_args.kwargs['allow_redirects'] is False


@pytest.mark.parametrize('content', ['yes', '{"complete":"true"}', '{}'])
def test_invalid_endpoint_decision_is_not_accepted(content):
    with patch('youtube2slack.speech_services.requests.post', return_value=response(content)):
        with pytest.raises(ServiceError):
            EndpointDetector(ChatService('http://localhost:8000/v1', 'model')).is_complete('if', 'en')


def test_http_errors_do_not_reveal_credentials_or_response_body():
    r = response()
    r.status_code = 401
    r.text = 'private response and secret-key'
    with patch('youtube2slack.speech_services.requests.post', return_value=r):
        with pytest.raises(ServiceError) as error:
            ChatService('http://localhost:8000/v1', 'model').complete('system', 'source')
        assert str(error.value) == 'http_401'


def test_config_defaults_and_opt_in(monkeypatch):
    monkeypatch.delenv('COOKIE_ENCRYPTION_KEY', raising=False)
    config = WorkflowConfig.from_dict({})
    assert config.translation_target_language is None
    assert config.asr_backend == 'whisper'
    configured = WorkflowConfig.from_dict({
        'translation': {'target_language': 'ja', 'base_url': 'http://localhost:8000/v1', 'model': 'test'},
        'segmentation': {'semantic': True, 'base_url': 'http://localhost:8000/v1', 'model': 'test'},
    })
    options = configured.stream_processor_options()
    assert options['translator'].target_language == 'ja'
    assert isinstance(options['endpoint_detector'], EndpointDetector)


def test_asr_alternative_preserves_permission_check():
    from youtube2slack.whisper_transcriber import TranscriberFactory, TranscriptionError
    from youtube2slack.user_cookie_manager import UserSettings
    config = WorkflowConfig(asr_backend='compatible', asr_base_url='http://localhost:8000/v1',
                            asr_model='Qwen/Qwen3-ASR-0.6B', allowed_local_users=['allowed'])
    with pytest.raises(TranscriptionError, match='restricted'):
        TranscriberFactory.create_transcriber(UserSettings(), config, 'denied')
    allowed = TranscriberFactory.create_transcriber(UserSettings(), config, 'allowed')
    assert allowed.model == 'Qwen/Qwen3-ASR-0.6B'


def test_asr_alternative_does_not_override_personal_api_choice():
    from youtube2slack.whisper_transcriber import TranscriberFactory
    from youtube2slack.user_cookie_manager import UserSettings, WhisperService
    config = WorkflowConfig(asr_backend='compatible', asr_base_url='http://localhost:8000/v1',
                            asr_model='test', allowed_local_users=['allowed'])
    settings = UserSettings(whisper_service=WhisperService.OPENAI, openai_api_key='personal-key')
    with patch('youtube2slack.whisper_transcriber.OpenAIWhisperTranscriber') as api:
        TranscriberFactory.create_transcriber(settings, config, 'denied')
        api.assert_called_once_with(api_key='personal-key', model='whisper-1')


def test_endpoint_failure_uses_bounded_fallback_and_records_failure(processor):
    processor.endpoint_detector = Mock()
    processor.endpoint_detector.is_complete.side_effect = ServiceError('request_failed')
    run_audio(processor, pcm(2) + pcm(15, False))
    processor.progress_callback.assert_called_once_with('Yes.')
    assert processor.get_status()['endpoint_failures'] == 1


def test_truncated_input_is_an_error(processor):
    with pytest.raises(VADStreamProcessingError, match='Truncated PCM'):
        run_audio(processor, pcm(1) + b'x')


def test_real_http_transport_for_translation_and_asr(tmp_path):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from youtube2slack.speech_services import CompatibleASR

    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            received.append((self.path, body))
            if self.path == '/v1/chat/completions':
                result = {'choices': [{'finish_reason': 'stop', 'message': {'content': 'いいえ。'}}]}
            else:
                result = {'text': 'No.', 'language': 'en'}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f'http://127.0.0.1:{server.server_port}/v1'
        assert Translator(ChatService(base_url, 'test'), 'ja').translate('No.', 'en') == 'いいえ。'
        path = tmp_path / 'test.wav'
        path.write_bytes(pcm(1))
        assert CompatibleASR(base_url, 'asr').transcribe(path)['text'] == 'No.'
        assert received[0][0] == '/v1/chat/completions'
        assert received[1][0] == '/v1/audio/transcriptions'
        assert b'filename="audio.wav"' in received[1][1]
        assert pcm(1) in received[1][1]
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_eof_drains_already_exited_ffmpeg_and_flushes_tail(processor):
    process = Mock(stdout=io.BytesIO(pcm(2)))
    process.poll.return_value = 0
    process.wait.return_value = 0
    processor._get_actual_stream_url = Mock(return_value='http://example.invalid/audio')
    processor.is_running = True
    with patch('youtube2slack.vad_stream_processor.subprocess.Popen', return_value=process) as popen:
        processor._start_vad_stream_capture('http://example.invalid/video')
    processor.progress_callback.assert_called_once_with('Yes.')
    assert 's16le' in popen.call_args.args[0]
    process.terminate.assert_not_called()


def test_start_propagates_upstream_and_inference_failures_and_cleans_up(processor):
    import os
    processor._get_stream_info = Mock(return_value={})
    processor._get_actual_stream_url = Mock(side_effect=RuntimeError('upstream unavailable'))
    with pytest.raises(RuntimeError, match='upstream unavailable'):
        processor.start_stream_processing('url')
    assert processor.is_running is False
    assert not os.path.exists(processor.temp_dir)
    with pytest.raises(VADStreamProcessingError, match='new processor'):
        processor.start_stream_processing('url')


def test_stream_with_translation_error_does_not_complete_successfully(processor):
    processor._get_stream_info = Mock(return_value={})
    processor._start_vad_stream_capture = lambda *args: processor.process_pcm_stream(io.BytesIO(pcm(2)))
    processor.translator = Mock(target_language='ja')
    processor.translator.translate.side_effect = ServiceError('generation_length')
    callback = Mock()
    with pytest.raises(VADStreamProcessingError, match='translation=1'):
        processor.start_stream_processing('url', callback)
    assert 'Yes.' in callback.call_args.args[0]
    assert processor.is_running is False


def test_workspace_context_is_forwarded_without_changing_credentials():
    manager = Mock()
    config = WorkflowConfig(settings_manager=manager)
    config.get_cookies_file_for_user('user', team_id='team')
    config.cleanup_user_temp_files('user', team_id='team')
    manager.get_cookies_file_path.assert_called_once_with('user', team_id='team')
    manager.cleanup_temp_files.assert_called_once_with('user', team_id='team')


@pytest.mark.parametrize('message', [None, [], 123, 'invalid'])
def test_malformed_chat_preserves_source_as_a_translation_failure(processor, message):
    r = response()
    r.json.return_value['choices'][0]['message'] = message
    processor.translator = Translator(ChatService('http://localhost:8000/v1', 'test'), 'ja')
    with patch('youtube2slack.speech_services.requests.post', return_value=r):
        run_audio(processor, pcm(2))
    assert 'Yes.' in processor.progress_callback.call_args.args[0]
    assert processor.last_result['error'] == 'invalid_response'


def test_stop_timeout_prevents_a_concurrent_restart():
    from types import SimpleNamespace
    from youtube2slack.slack_server import SlackServer
    server = SlackServer.__new__(SlackServer)
    server.bot_client = Mock()
    processor = Mock()
    processor.stop_processing.side_effect = VADStreamProcessingError('still finishing')
    info = SimpleNamespace(processor=processor, is_running=True, video_url='url',
                           thread_info=Mock(thread_ts='thread'), error_message=None)
    server._stop_stream_processing(info, 'user')
    assert info.is_running is True
    assert 'still finishing' in info.error_message
    assert '✅' not in server.bot_client.post_to_thread.call_args.args[1]
    with patch('youtube2slack.slack_server.TranscriberFactory.create_transcriber') as create:
        server._restart_stream_processing(info, 'user')
        create.assert_not_called()
    assert info.processor is processor
    assert info.is_running is True


@pytest.mark.parametrize('fail_translation', [False, True])
def test_evaluation_records_failures_and_does_not_replace_output(tmp_path, capsys, fail_translation):
    import importlib.util
    import json
    import os
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        'evaluate_stream', Path(__file__).parents[1] / 'scripts' / 'evaluate_stream.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    audio_path = tmp_path / 'input.wav'
    with wave.open(str(audio_path), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(pcm(2))
    output = tmp_path / 'result.jsonl'
    config = WorkflowConfig()
    translator = Mock(target_language='ja')
    translator.translate.return_value = 'はい。'
    if fail_translation:
        translator.translate.side_effect = ServiceError('generation_length')
    asr = Mock()
    asr.transcribe.return_value = {'text': 'Yes.', 'language': 'en'}
    argv = [str(audio_path), '--config', 'test.yaml', '--user-id', 'user', '--output', str(output)]
    with patch.object(module.WorkflowConfig, 'from_yaml', return_value=config), \
         patch.object(module.TranscriberFactory, 'create_transcriber', return_value=asr), \
         patch.object(WorkflowConfig, 'stream_processor_options', return_value={'translator': translator}), \
         patch.object(module.VADStreamProcessor, '_is_speech', return_value=True):
        assert module.main(argv) == int(fail_translation)
        original = output.read_text()
        rows = [json.loads(line) for line in original.splitlines()]
        assert rows[0]['source'] == 'Yes.'
        assert rows[-1]['success'] is not fail_translation
        assert rows[-1]['translation_failures'] == int(fail_translation)
        assert os.stat(output).st_mode & 0o777 == 0o600
        with pytest.raises(FileExistsError):
            module.main(argv)
        assert output.read_text() == original


def test_real_ffmpeg_preserves_pcm_through_forced_boundaries(processor, tmp_path):
    audio_path = tmp_path / 'source.wav'
    data = pcm(25) + pcm(1)[:202]
    with wave.open(str(audio_path), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(data)
    captured = []

    def transcribe(path, **kwargs):
        with wave.open(path, 'rb') as audio:
            captured.append(audio.readframes(audio.getnframes()))
        return {'text': 'Same words.', 'language': 'en'}

    processor.transcriber.transcribe.side_effect = transcribe
    processor._get_actual_stream_url = lambda url: str(audio_path)
    processor.is_running = True
    processor._start_vad_stream_capture('unused')
    assert b''.join(captured) == data
    assert processor.progress_callback.call_count == 3


def test_stop_during_capture_flushes_once_and_waits_for_owner(processor):
    import threading
    waiting = threading.Event()
    interrupted = threading.Event()

    class Stream:
        read_count = 0

        def read(self, size):
            self.read_count += 1
            if self.read_count <= 2:
                return pcm(1)
            waiting.set()
            assert interrupted.wait(timeout=5)
            return b''

        def close(self):
            pass

    process = Mock(stdout=Stream())
    process.poll.return_value = None
    process.terminate.side_effect = interrupted.set
    processor._get_stream_info = Mock(return_value={})
    processor._get_actual_stream_url = Mock(return_value='unused')
    callback = Mock()
    failures = []

    def capture():
        try:
            processor.start_stream_processing('unused', callback)
        except Exception as error:
            failures.append(error)

    with patch('youtube2slack.vad_stream_processor.subprocess.Popen', return_value=process):
        thread = threading.Thread(target=capture)
        thread.start()
        try:
            assert waiting.wait(timeout=5)
            processor.stop_processing()
        finally:
            interrupted.set()
            thread.join(timeout=5)
        assert not thread.is_alive()
        assert not failures
        processor.stop_processing()
    callback.assert_called_once_with('Yes.')


@pytest.mark.parametrize('delivery_fails', [False, True])
def test_slack_integration_passes_options_preserves_content_and_reports_delivery_failure(delivery_fails):
    from youtube2slack.slack_server import SlackServer
    from youtube2slack.slack_bot_client import ThreadInfo
    server = SlackServer.__new__(SlackServer)
    manager = Mock()
    manager.get_cookies_file_path.return_value = None
    server.workflow_config = WorkflowConfig(settings_manager=manager)
    server.bot_client = Mock()
    server.bot_client.create_thread.return_value = ThreadInfo(channel='channel', thread_ts='thread')
    server.active_streams = {}
    if delivery_fails:
        server.bot_client.post_to_thread.side_effect = RuntimeError('delivery failed')
    with patch('youtube2slack.vad_stream_processor.VADStreamProcessor') as create, \
         patch('youtube2slack.slack_server.TranscriberFactory.create_transcriber'), \
         patch('yt_dlp.YoutubeDL') as downloader:
        downloader.return_value.__enter__.return_value.extract_info.return_value = {'title': 'Test'}
        create.return_value.start_stream_processing.side_effect = (
            lambda url, callback: callback('Processing speech segment <!channel> & data'))
        server._process_simple_vad_in_background('url', 'channel', 'user', None, 'team')
        assert create.call_args.kwargs['max_segment_duration'] == 12.0
        assert create.call_args.kwargs['translator'] is None
        server.bot_client.post_to_thread.assert_called_once_with(
            server.active_streams['thread'].thread_info,
            'Processing speech segment &lt;!channel&gt; &amp; data')
        assert server.active_streams['thread'].is_running is False
        if delivery_fails:
            assert server.active_streams['thread'].error_message == 'delivery failed'
