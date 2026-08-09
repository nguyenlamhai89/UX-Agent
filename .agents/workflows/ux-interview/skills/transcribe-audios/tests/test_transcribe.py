import os
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts")))
import transcribe


def test_normalize_keyterms_and_timestamp():
    assert transcribe.normalize_keyterms(" ux, ,research ") == ["ux", "research"]
    assert transcribe.normalize_keyterms("") is None
    assert transcribe.format_timestamp(65.9) == "01:05"
    assert transcribe.DEFAULT_LANGUAGE_CODE == "vi"


def test_format_transcription_preserves_word_spacing():
    words = [SimpleNamespace(text="hello", speaker_id="a", start=0), SimpleNamespace(text="world", speaker_id="a", start=0.5)]
    result = transcribe.format_transcription(SimpleNamespace(words=words), "test.mp3")
    assert "hello world" in result
    assert "[00:00] [a]" in result


def test_format_transcription_rejects_empty_content():
    with pytest.raises(transcribe.TranscriptionError, match="no text") as error:
        transcribe.format_transcription(SimpleNamespace(words=[], text="  "), "test.mp3")
    assert error.value.code == "EMPTY_TRANSCRIPT"


def test_format_transcription_supports_audio_events_and_channel_index():
    words = [
        SimpleNamespace(text="(laughter)", type="audio_event", channel_index=0, start=1.2),
        SimpleNamespace(text="hello", type="word", channel_index=1, start=2.0),
    ]
    result = transcribe.format_transcription(SimpleNamespace(words=words), "test.mp4")
    assert "(laughter)" in result
    assert "[00:01] [speaker_0]" in result
    assert "[00:02] [speaker_1]" in result


def test_format_transcription_flattens_multichannel_response():
    response = SimpleNamespace(
        transcripts=[
            SimpleNamespace(words=[SimpleNamespace(text="first", start=2.0, speaker_id=None)]),
            SimpleNamespace(words=[SimpleNamespace(text="second", start=1.0, speaker_id=None)]),
        ]
    )
    result = transcribe.format_transcription(response, "test.wav")
    assert result.index("second") < result.index("first")
    assert "[speaker_1]" in result


@patch("transcribe.random.uniform", return_value=0)
@patch("transcribe.time.sleep")
@patch("transcribe.ElevenLabs")
def test_transcribe_retries_only_transient_errors(MockElevenLabs, mock_sleep, mock_jitter, tmp_path):
    instance = MockElevenLabs.return_value
    instance.speech_to_text.convert.side_effect = [Exception("connection timeout"), SimpleNamespace(words=[], text="done")]
    audio = tmp_path / "test.mp3"
    audio.write_bytes(b"audio")
    assert "done" in transcribe.transcribe_audio(str(audio), "key")
    mock_sleep.assert_called_once_with(1)


@patch("transcribe.ElevenLabs")
def test_transcribe_passes_current_stt_options(MockElevenLabs, tmp_path):
    instance = MockElevenLabs.return_value
    instance.speech_to_text.convert.return_value = SimpleNamespace(
        words=[SimpleNamespace(text="hello", speaker_id="speaker_0", start=0)]
    )
    audio = tmp_path / "test.mp3"
    audio.write_bytes(b"audio")
    transcribe.transcribe_audio(
        str(audio),
        "key",
        keyterms=["UX"],
        language_code="eng",
        tag_audio_events=True,
        num_speakers=2,
        diarization_threshold=0.22,
        timestamps_granularity="word",
    )
    kwargs = instance.speech_to_text.convert.call_args.kwargs
    assert kwargs["model_id"] == "scribe_v2"
    assert kwargs["tag_audio_events"] is True
    assert kwargs["language_code"] == "eng"
    assert kwargs["num_speakers"] == 2
    assert kwargs["diarization_threshold"] == 0.22
    assert kwargs["timestamps_granularity"] == "word"
    assert kwargs["diarize"] is True
    assert kwargs["no_verbatim"] is False


@patch("transcribe.time.sleep")
@patch("transcribe.ElevenLabs")
def test_transcribe_does_not_retry_terminal_errors(MockElevenLabs, mock_sleep, tmp_path):
    instance = MockElevenLabs.return_value
    response = SimpleNamespace(status_code=401, headers={})
    instance.speech_to_text.convert.side_effect = SimpleNamespace(response=response, __str__=lambda self: "unauthorized")
    audio = tmp_path / "test.mp3"
    audio.write_bytes(b"audio")
    with pytest.raises(transcribe.TranscriptionError) as error:
        transcribe.transcribe_audio(str(audio), "key")
    assert error.value.code == "API_REQUEST_ERROR"
    mock_sleep.assert_not_called()


def test_process_file_replaces_invalid_transcript_atomically(tmp_path):
    interview = tmp_path / "Interview"
    interview.mkdir()
    audio = interview / "test.mp3"
    audio.write_bytes(b"audio")
    output = interview / "transcript_test.md"
    output.write_text("partial")
    with patch("transcribe.transcribe_audio", return_value="# INTERVIEW TRANSCRIPT: test.mp3\n\n**[00:00] [speaker_0]** <br>\ncontent"):
        result = transcribe.process_file(str(audio), str(tmp_path), "key")
    assert result["status"] == "success"
    assert output.read_text().endswith("content")
    assert not list(interview.glob("tmp*"))


def test_process_file_rejects_large_audio(tmp_path):
    interview = tmp_path / "Interview"
    interview.mkdir()
    audio = interview / "test.mp3"
    audio.write_bytes(b"audio")
    with patch("transcribe.os.path.getsize", return_value=2 * 1024 * 1024):
        result = transcribe.process_file(str(audio), str(tmp_path), "key", max_file_size_mb=1)
    assert result["error_code"] == "INPUT_TOO_LARGE"


@patch.dict(os.environ, {"ELEVENLABS_API_KEY": "key"})
@patch("transcribe.get_audio_files")
@patch("transcribe.process_file")
def test_main_sorts_results_and_reports_partial_failure(mock_process, mock_files, capsys, tmp_path):
    mock_files.return_value = ["/tmp/b.mp3", "/tmp/a.mp3"]
    mock_process.side_effect = [
        {"status": "success", "audio_file": "b.mp3", "output_file": "b.md"},
        {"status": "error", "audio_file": "a.mp3", "error_code": "API_REQUEST_ERROR", "error": "bad"},
    ]
    with patch.object(sys, "argv", ["transcribe.py", str(tmp_path), "--max-workers", "1"]):
        with pytest.raises(SystemExit) as error:
            transcribe.main()
    assert error.value.code == 1
    output = capsys.readouterr().out
    assert "PARTIAL_FAILURE" in output
    assert output.index("a.mp3") < output.index("b.mp3")


def test_process_file_returns_elevenlabs_error_without_secondary_provider(tmp_path):
    interview = tmp_path / "Interview"
    interview.mkdir()
    audio = interview / "test.mp3"
    audio.write_bytes(b"audio")
    with patch("transcribe.transcribe_audio", side_effect=transcribe.TranscriptionError("API_REQUEST_ERROR", "ElevenLabs failed", provider="elevenlabs", attempts=1)):
        result = transcribe.process_file(str(audio), str(tmp_path), "elevenlabs_key")
    assert result["status"] == "error"
    assert result["error_code"] == "API_REQUEST_ERROR"


def test_main_missing_elevenlabs_key_exits(capsys, tmp_path, monkeypatch):
    """Transcription requires an injected ELEVENLABS_API_KEY."""
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with patch.object(sys, "argv", ["transcribe.py", str(tmp_path)]):
        with pytest.raises(SystemExit) as error:
            transcribe.main()
    assert error.value.code == 1
    output = capsys.readouterr().out
    assert "MISSING_API_KEY" in output
    assert "ELEVENLABS_API_KEY is required" in output


@patch.dict(os.environ, {"ELEVENLABS_API_KEY": "key"})
@patch("transcribe.get_audio_files")
@patch("transcribe.ThreadPoolExecutor")
def test_main_handles_future_error(mock_executor_cls, mock_files, capsys, tmp_path):
    """When a thread pool executor future raises an unhandled exception, handle as FUTURE_ERROR."""
    mock_files.return_value = ["/tmp/corrupt.mp3"]
    mock_executor = MagicMock()
    mock_executor_cls.return_value.__enter__.return_value = mock_executor

    mock_future = MagicMock()
    mock_future.result.side_effect = RuntimeError("Worker thread crashed unexpectedly")
    mock_executor.submit.return_value = mock_future

    with patch.object(sys, "argv", ["transcribe.py", str(tmp_path), "--max-workers", "1"]):
        with patch("transcribe.wait", return_value=({mock_future}, set())):
            with pytest.raises(SystemExit) as error:
                transcribe.main()

    assert error.value.code == 1
    output = capsys.readouterr().out
    assert "FUTURE_ERROR" in output
    assert "Worker thread crashed unexpectedly" in output
    assert "corrupt.mp3" in output


def test_get_audio_files_uses_direct_folder_when_interview_is_empty(tmp_path):
    # Test Interview subfolder priority
    interview = tmp_path / "Interview"
    interview.mkdir()
    f1 = interview / "test1.m4a"
    f1.write_bytes(b"data")
    f2 = tmp_path / "test2.m4a"
    f2.write_bytes(b"data")

    files = transcribe.get_audio_files(str(tmp_path))
    assert files == [str(f1)]

    # Remove the Interview file to use audio directly in folder_path.
    f1.unlink()
    direct_files = transcribe.get_audio_files(str(tmp_path))
    assert direct_files == [str(f2)]


def test_get_audio_files_supports_documented_video_and_audio_extensions(tmp_path):
    interview = tmp_path / "Interview"
    interview.mkdir()
    (interview / "video.MP4").write_bytes(b"data")
    (interview / "recording.flac").write_bytes(b"data")
    (interview / "notes.txt").write_text("not audio")
    assert transcribe.get_audio_files(str(tmp_path)) == [
        str(interview / "recording.flac"),
        str(interview / "video.MP4"),
    ]


def test_is_valid_transcript_requires_named_header_and_completed_segment(tmp_path):
    transcript = tmp_path / "transcript_test.md"
    transcript.write_text("# INTERVIEW TRANSCRIPT: test.mp3", encoding="utf-8")
    assert not transcribe.is_valid_transcript(str(transcript), "test.mp3")

    transcript.write_text(
        "# INTERVIEW TRANSCRIPT: wrong.mp3\n\n**[00:00] [speaker_0]** <br>\ncontent\n",
        encoding="utf-8",
    )
    assert not transcribe.is_valid_transcript(str(transcript), "test.mp3")

    transcript.write_text(
        "# INTERVIEW TRANSCRIPT: test.mp3\n\n**[00:00] [speaker_0]** <br>\ncontent\n",
        encoding="utf-8",
    )
    assert transcribe.is_valid_transcript(str(transcript), "test.mp3")


def test_process_file_skips_only_current_fingerprinted_source(tmp_path):
    interview = tmp_path / "Interview"
    interview.mkdir()
    audio = interview / "test.mp3"
    audio.write_bytes(b"first audio")
    transcript = "# INTERVIEW TRANSCRIPT: test.mp3\n\n**[00:00] [speaker_0]** <br>\ncontent"

    with patch("transcribe.transcribe_audio", return_value=transcript):
        first = transcribe.process_file(str(audio), str(tmp_path), "key")
    assert first["status"] == "success"
    assert os.path.exists(first["metadata_file"])

    with patch("transcribe.transcribe_audio") as skipped_call:
        skipped = transcribe.process_file(str(audio), str(tmp_path), "key")
    assert skipped["status"] == "skipped"
    skipped_call.assert_not_called()

    audio.write_bytes(b"replacement audio with different size")
    with patch("transcribe.transcribe_audio", return_value=transcript) as refreshed_call:
        refreshed = transcribe.process_file(str(audio), str(tmp_path), "key")
    assert refreshed["status"] == "success"
    refreshed_call.assert_called_once()


def test_process_file_records_elevenlabs_metadata_only(tmp_path):
    interview = tmp_path / "Interview"
    interview.mkdir()
    audio = interview / "test.mp3"
    audio.write_bytes(b"audio")
    transcript = "# INTERVIEW TRANSCRIPT: test.mp3\n\n**[00:00] [speaker_0]** <br>\ncontent"

    with patch("transcribe.transcribe_audio", return_value=transcript):
        result = transcribe.process_file(str(audio), str(tmp_path), "key")

    metadata = transcribe.read_transcript_metadata(result["metadata_file"])
    assert result["provider"] == "elevenlabs"
    assert result["attempts"] == {"elevenlabs": 1}
    assert metadata["provider"] == "elevenlabs"
    assert metadata["attempts"] == {"elevenlabs": 1}
    assert "fallback_used" not in metadata


def test_main_validates_diarization_and_multichannel_conflicts(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "key")
    with patch.object(sys, "argv", ["transcribe.py", str(tmp_path), "--diarization-threshold", "0.09"]):
        with pytest.raises(SystemExit) as threshold_error:
            transcribe.main()
    assert threshold_error.value.code == 1
    assert "INVALID_INPUT" in capsys.readouterr().out

    with patch.object(sys, "argv", ["transcribe.py", str(tmp_path), "--use-multi-channel", "--num-speakers", "2"]):
        with pytest.raises(SystemExit) as conflict_error:
            transcribe.main()
    assert conflict_error.value.code == 1
    assert "INVALID_INPUT" in capsys.readouterr().out


def test_budget_preflight_uses_orchestrator_supplied_pricing(tmp_path):
    audio = tmp_path / "test.mp3"
    audio.write_bytes(b"audio")
    pricing_file = tmp_path / "pricing.json"
    pricing_file.write_text(
        '{"version": "2026-08-09", "providers": {"elevenlabs": {"usd_per_minute": 1.0}}}',
        encoding="utf-8",
    )

    with patch("transcribe.probe_media_duration_seconds", return_value=60):
        pricing, durations = transcribe.prepare_pricing_and_durations(
            [str(audio)], str(pricing_file), 1.0
        )
    assert pricing["version"] == "2026-08-09"
    assert durations[str(audio)] == 60

    with patch("transcribe.probe_media_duration_seconds", return_value=60):
        with pytest.raises(transcribe.TranscriptionError) as over_budget:
            transcribe.prepare_pricing_and_durations([str(audio)], str(pricing_file), 0.5)
    assert over_budget.value.code == "COST_BUDGET_EXCEEDED"


def test_bounded_batch_respects_aggregate_inflight_bytes(tmp_path):
    files = []
    for name in ("a.mp3", "b.mp3"):
        audio = tmp_path / name
        audio.write_bytes(b"audio")
        files.append(str(audio))

    args = SimpleNamespace(
        keyterms=None,
        max_workers=2,
        max_inflight_mb=2,
        max_file_size_mb=3,
        max_retries=1,
        language_code="vi",
        no_tag_audio_events=False,
        num_speakers=None,
        diarization_threshold=None,
        timestamps_granularity="word",
        use_multi_channel=False,
        multichannel_output_style="combined",
        source_fingerprint="stat",
        requests_per_minute=None,
    )
    active = 0
    maximum_active = 0
    lock = threading.Lock()

    def fake_process(path, *unused_args):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return {"status": "success", "audio_file": os.path.basename(path), "output_file": f"{path}.md"}

    sizes = {path: 2 * 1024 * 1024 for path in files}
    with patch("transcribe.os.path.getsize", side_effect=lambda path: sizes[path]):
        with patch("transcribe.process_file", side_effect=fake_process):
            results, errors = transcribe.run_bounded_batch(files, str(tmp_path), "key", args, None, {})
    assert not errors
    assert [result["audio_file"] for result in results] == ["a.mp3", "b.mp3"]
    assert maximum_active == 1
