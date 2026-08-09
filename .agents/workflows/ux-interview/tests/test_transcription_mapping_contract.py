"""Contract tests for the `transcribe-audios` → `map-transcript` handoff."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
TRANSCRIBE_SCRIPTS = SKILLS_DIR / "transcribe-audios" / "scripts"
MAP_SCRIPTS = SKILLS_DIR / "map-transcript" / "scripts"
sys.path.insert(0, str(TRANSCRIBE_SCRIPTS))
sys.path.insert(0, str(MAP_SCRIPTS))

import transcribe  # noqa: E402
from mapping_pipeline import (  # noqa: E402
    finalize_pipeline,
    next_batch,
    prepare_pipeline,
    record_success,
)
from validate_mapping import parse_transcript_turns  # noqa: E402


QUESTIONNAIRE = """| # | Theme | Question | Observed Variable |
|---|---|---|---|
| 1 | Warm-up | Bạn tên gì? | Name |
"""


def _candidate(
    audio_name: str,
    timestamp: str,
    response: str,
    coverage_start: str | None = None,
) -> str:
    coverage_start = coverage_start or timestamp
    return f"""# Mapped Transcript

| # | Theme | Question | Observed Variable | An |
|---|---|---|---|---|
| 1 | Warm-up | Bạn tên gì? | Name | [{timestamp}] **<mark style=\"background-color: yellow;\">{response}</mark>** |

> **Mapping Summary**: Total rows: 1 | Answered: 1 | N/A: 0 | Transcript coverage: [{coverage_start}] to [{timestamp}]
"""


def _transcribe_with_words(root: Path, filename: str, words: list[SimpleNamespace]):
    audio = root / filename
    audio.write_bytes(b"audio")
    rendered = transcribe.format_transcription(
        SimpleNamespace(words=words), filename
    )
    with patch("transcribe.transcribe_audio", return_value=rendered):
        result = transcribe.process_file(str(audio), str(root), "test-key")
    assert result["status"] == "success"
    assert Path(result["metadata_file"]).is_file()
    return Path(result["output_file"]), rendered


def _map_candidate(
    root: Path,
    audio_name: str,
    timestamp: str,
    response: str,
    coverage_start: str | None = None,
):
    prepared = prepare_pipeline(str(root))
    assert prepared["counts"] == {"pending": 1}
    task = next_batch(str(root), now=10_000)["tasks"][0]
    assert task["audio_name"] == audio_name
    Path(task["candidate_file"]).write_text(
        _candidate(audio_name, timestamp, response, coverage_start), encoding="utf-8"
    )
    assert record_success(str(root), audio_name)["status"] == "validated"
    return finalize_pipeline(str(root))


def test_interview_handoff_maps_transcriber_format_and_multichannel_labels(tmp_path):
    interview = tmp_path / "Interview"
    interview.mkdir()
    (interview / "full-questionnaire.md").write_text(QUESTIONNAIRE, encoding="utf-8")
    output, rendered = _transcribe_with_words(
        tmp_path,
        "round-one.mp3",
        [
            SimpleNamespace(text="Bạn tên gì?", speaker_id="speaker_0", start=0),
            SimpleNamespace(text="Tôi là An.", speaker_id="speaker_1", start=5),
        ],
    )

    assert output.parent == interview
    assert "[speaker_0]" in rendered and "[speaker_1]" in rendered
    turns = parse_transcript_turns(rendered)
    assert [(turn.timestamp, turn.content) for turn in turns] == [
        ("[00:00]", "Bạn tên gì?"),
        ("[00:05]", "Tôi là An."),
    ]

    finalized = _map_candidate(
        tmp_path, "round-one", "00:05", "Tôi là An.", coverage_start="00:00"
    )
    assert finalized["status"] == "success"
    assert (interview / "mapped-transcript.md").is_file()


def test_direct_folder_handoff_accepts_timestamps_beyond_999_minutes(tmp_path):
    (tmp_path / "full-questionnaire.md").write_text(QUESTIONNAIRE, encoding="utf-8")
    output, rendered = _transcribe_with_words(
        tmp_path,
        "long-recording.mp3",
        [SimpleNamespace(text="Tôi là An.", speaker_id="speaker_1", start=60_000)],
    )

    assert output.parent == tmp_path
    assert "**[1000:00] [speaker_1]**" in rendered
    assert parse_transcript_turns(rendered)[0].timestamp == "[1000:00]"

    finalized = _map_candidate(tmp_path, "long-recording", "1000:00", "Tôi là An.")
    assert finalized["status"] == "success"
    assert (tmp_path / "mapping-manifest.json").is_file()
