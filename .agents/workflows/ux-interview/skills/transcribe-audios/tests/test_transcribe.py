import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts")))
import transcribe


def test_normalize_keyterms_and_timestamp():
    assert transcribe.normalize_keyterms(" ux, ,research ") == ["ux", "research"]
    assert transcribe.normalize_keyterms("") is None
    assert transcribe.format_timestamp(65.9) == "01:05"


def test_format_transcription_preserves_word_spacing():
    words = [SimpleNamespace(text="hello", speaker_id="a", start=0), SimpleNamespace(text="world", speaker_id="a", start=0.5)]
    result = transcribe.format_transcription(SimpleNamespace(words=words), "test.mp3")
    assert "hello world" in result
    assert "[00:00] [a]" in result


def test_format_transcription_rejects_empty_content():
    with pytest.raises(transcribe.TranscriptionError, match="no text") as error:
        transcribe.format_transcription(SimpleNamespace(words=[], text="  "), "test.mp3")
    assert error.value.code == "EMPTY_TRANSCRIPT"


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
    with patch("transcribe.transcribe_audio", return_value="# INTERVIEW TRANSCRIPT: test.mp3\n\ncontent"):
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


# --- Gemini Fallback Tests ---


def test_parse_gemini_response_standard_format():
    """Verify structured Gemini output is parsed into the correct transcript format."""
    text = "[00:00] Speaker 1: Hello, how are you?\n[00:05] Speaker 2: I'm fine, thanks."
    result = transcribe.parse_gemini_response(text, "test.mp3")
    assert "# INTERVIEW TRANSCRIPT: test.mp3" in result
    assert "Hello, how are you?" in result
    assert "[00:00] [Speaker 1]" in result
    assert "[00:05] [Speaker 2]" in result


def test_parse_gemini_response_fallback_unstructured():
    """When Gemini returns plain text without timestamps, wrap as single speaker."""
    result = transcribe.parse_gemini_response("This is just plain text without timestamps", "test.mp3")
    assert "[00:00] [Speaker 1]" in result
    assert "This is just plain text without timestamps" in result


def test_parse_gemini_response_rejects_empty():
    """Empty Gemini response raises EMPTY_TRANSCRIPT like ElevenLabs does."""
    with pytest.raises(transcribe.TranscriptionError, match="no text") as error:
        transcribe.parse_gemini_response("", "test.mp3")
    assert error.value.code == "EMPTY_TRANSCRIPT"


def test_process_file_falls_back_to_gemini(tmp_path):
    """When ElevenLabs fails and Gemini key is available, fall back to Gemini."""
    interview = tmp_path / "Interview"
    interview.mkdir()
    audio = interview / "test.mp3"
    audio.write_bytes(b"audio")
    with patch("transcribe.transcribe_audio", side_effect=transcribe.TranscriptionError("API_REQUEST_ERROR", "ElevenLabs failed")):
        with patch("transcribe.transcribe_audio_gemini", return_value="# INTERVIEW TRANSCRIPT: test.mp3\n\ncontent"):
            result = transcribe.process_file(str(audio), str(tmp_path), "elevenlabs_key", gemini_api_key="gemini_key")
    assert result["status"] == "success"
    assert (interview / "transcript_test.md").read_text().endswith("content")


def test_process_file_no_fallback_without_gemini_key(tmp_path):
    """When ElevenLabs fails and no Gemini key, error propagates normally."""
    interview = tmp_path / "Interview"
    interview.mkdir()
    audio = interview / "test.mp3"
    audio.write_bytes(b"audio")
    with patch("transcribe.transcribe_audio", side_effect=transcribe.TranscriptionError("API_REQUEST_ERROR", "ElevenLabs failed")):
        result = transcribe.process_file(str(audio), str(tmp_path), "elevenlabs_key")
    assert result["status"] == "error"
    assert result["error_code"] == "API_REQUEST_ERROR"


@patch("transcribe.random.uniform", return_value=0)
@patch("transcribe.time.sleep")
@patch("transcribe.google_genai")
def test_transcribe_audio_gemini_retries_transient(mock_genai, mock_sleep, mock_jitter, tmp_path):
    """Gemini retries on 503 transient errors and cleans up uploaded files."""
    mock_client = MagicMock()
    mock_genai.Client.return_value = mock_client
    mock_uploaded = MagicMock()
    mock_uploaded.name = "files/test123"
    mock_client.files.upload.return_value = mock_uploaded
    mock_client.models.generate_content.side_effect = [
        Exception("503 Service Unavailable"),
        MagicMock(text="[00:00] Speaker 1: Hello world"),
    ]
    audio = tmp_path / "test.mp3"
    audio.write_bytes(b"audio")
    result = transcribe.transcribe_audio_gemini(str(audio), "gemini_key")
    assert "Hello world" in result
    mock_sleep.assert_called_once_with(1)
    mock_client.files.delete.assert_called_once_with(name="files/test123")


def test_main_missing_both_keys_exits(capsys, tmp_path, monkeypatch):
    """When neither ELEVENLABS_API_KEY nor GEMINI_API_KEY is set, exit with MISSING_API_KEY."""
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with patch.object(sys, "argv", ["transcribe.py", str(tmp_path)]):
        with pytest.raises(SystemExit) as error:
            transcribe.main()
    assert error.value.code == 1
    output = capsys.readouterr().out
    assert "MISSING_API_KEY" in output
    assert "Neither" in output


@patch.dict(os.environ, {"GEMINI_API_KEY": "gemini_key"})
@patch("transcribe.get_audio_files")
@patch("transcribe.process_file")
def test_main_gemini_only_succeeds(mock_process, mock_files, capsys, tmp_path, monkeypatch):
    """When only GEMINI_API_KEY is set, main() runs successfully and passes the key correctly."""
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    mock_files.return_value = ["/tmp/test.mp3"]
    mock_process.return_value = {"status": "success", "audio_file": "test.mp3", "output_file": "test.md"}
    with patch.object(sys, "argv", ["transcribe.py", str(tmp_path), "--max-workers", "1"]):
        transcribe.main()
    output = capsys.readouterr().out
    assert "success" in output
    call_args = mock_process.call_args[0]
    assert call_args[2] is None  # elevenlabs_key should be None
    assert call_args[6] == "gemini_key"  # gemini_key should be passed
