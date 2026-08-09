import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "scripts"))

import mapping_pipeline
from helpers import create_study, mapped_content, transcript_content, write_mapped
from mapping_pipeline import (
    PipelineError,
    cleanup_pipeline,
    finalize_pipeline,
    next_batch,
    pipeline_status,
    prepare_pipeline,
    record_failure,
    record_success,
)


def _write_candidates(tasks):
    for task in tasks:
        with open(task["candidate_file"], "w", encoding="utf-8") as handle:
            handle.write(mapped_content(task["audio_name"]))


def _run_all_tasks(root):
    while True:
        batch = next_batch(str(root), now=10_000)
        if not batch["tasks"]:
            break
        _write_candidates(batch["tasks"])
        for task in batch["tasks"]:
            result = record_success(str(root), task["audio_name"])
            assert result["status"] == "validated"


def test_prepare_and_next_batch_enforce_four_worker_limit(tmp_path):
    create_study(tmp_path, count=20)
    prepared = prepare_pipeline(str(tmp_path), max_workers=4)
    assert prepared["counts"] == {"pending": 20}
    batch = next_batch(str(tmp_path), now=10_000)
    assert batch["status"] == "ready"
    assert len(batch["tasks"]) == 4
    assert batch["max_workers"] == 4
    assert all(task["attempt"] == 1 for task in batch["tasks"])
    second_claim = next_batch(str(tmp_path), now=10_000)
    assert second_claim["status"] == "busy"
    assert second_claim["tasks"] == []


def test_prepare_rejects_malformed_questionnaire_row_width(tmp_path):
    interview = create_study(tmp_path, count=1)
    questionnaire = interview / "full-questionnaire.md"
    questionnaire.write_text(
        questionnaire.read_text(encoding="utf-8").replace(
            "| 1 | Warm-up | Please introduce yourself | Name |",
            "| 1 | Warm-up | Please introduce yourself | Name | unexpected |",
        ),
        encoding="utf-8",
    )
    with pytest.raises(PipelineError) as exc:
        prepare_pipeline(str(tmp_path))
    assert exc.value.code == "INVALID_QUESTIONNAIRE"


def test_pipeline_maps_six_users_and_generates_two_review_files(tmp_path):
    create_study(tmp_path, count=6)
    prepare_pipeline(str(tmp_path), max_workers=4, review_batch_size=5)
    _run_all_tasks(tmp_path)
    result = finalize_pipeline(str(tmp_path))
    assert result["status"] == "success"
    assert result["total_mapped"] == 6
    assert len(result["review_files"]) == 2
    assert os.path.isfile(result["combined_file"])
    prepared_again = prepare_pipeline(str(tmp_path))
    assert prepared_again["canonical_current"] is True
    assert prepared_again["counts"] == {"cached": 6}


def test_invalid_candidate_retries_and_preserves_last_valid_output(tmp_path):
    interview = create_study(tmp_path, count=1)
    final_path = write_mapped(interview, "user01")
    prepare_pipeline(str(tmp_path))
    finalize_pipeline(str(tmp_path))
    original = final_path.read_text(encoding="utf-8")

    transcript = interview / "transcript_user01.md"
    transcript.write_text(
        transcript_content("user01") + "\n[03:00] New detail", encoding="utf-8"
    )
    prepare_pipeline(str(tmp_path))
    task = next_batch(str(tmp_path), now=10_000)["tasks"][0]
    with open(task["candidate_file"], "w", encoding="utf-8") as handle:
        handle.write("# malformed candidate")
    result = record_success(str(tmp_path), "user01")
    assert result["status"] == "retry_pending"
    assert final_path.read_text(encoding="utf-8") == original


def test_transient_retry_uses_backoff_and_stops_after_max_attempts(
    tmp_path, monkeypatch
):
    create_study(tmp_path, count=1)
    prepare_pipeline(str(tmp_path), max_attempts=2)
    monkeypatch.setattr(mapping_pipeline.time, "time", lambda: 100.0)
    next_batch(str(tmp_path), now=100.0)
    first = record_failure(
        str(tmp_path),
        "user01",
        code="TRANSIENT_AI_ERROR",
        message="temporary",
        transient=True,
    )
    assert first["status"] == "retry_pending"
    assert first["retry_after_seconds"] == 1
    assert next_batch(str(tmp_path), now=100.5)["status"] == "waiting"
    assert len(next_batch(str(tmp_path), now=101.0)["tasks"]) == 1
    second = record_failure(
        str(tmp_path),
        "user01",
        code="TRANSIENT_AI_ERROR",
        message="still failing",
        transient=True,
    )
    assert second["status"] == "failed"
    assert second["retry_after_seconds"] == 0


def test_terminal_failure_is_not_retried(tmp_path):
    create_study(tmp_path, count=1)
    prepare_pipeline(str(tmp_path))
    next_batch(str(tmp_path), now=10_000)
    result = record_failure(
        str(tmp_path),
        "user01",
        code="TERMINAL_MAPPING_ERROR",
        message="invalid source",
        transient=False,
    )
    assert result["status"] == "failed"
    assert next_batch(str(tmp_path), now=10_000)["status"] == "idle"


def test_finalize_partial_does_not_update_canonical(tmp_path):
    interview = create_study(tmp_path, count=2)
    canonical = interview / "mapped-transcript.md"
    canonical.write_text("old canonical", encoding="utf-8")
    prepare_pipeline(str(tmp_path))
    batch = next_batch(str(tmp_path), now=10_000)
    first = batch["tasks"][0]
    with open(first["candidate_file"], "w", encoding="utf-8") as handle:
        handle.write(mapped_content(first["audio_name"]))
    record_success(str(tmp_path), first["audio_name"])
    result = finalize_pipeline(str(tmp_path))
    assert result["status"] == "partial"
    assert result["canonical_file_updated"] is False
    assert canonical.read_text(encoding="utf-8") == "old canonical"


def test_explicit_partial_excludes_stale_last_known_good_mapping(tmp_path):
    interview = create_study(tmp_path, count=2)
    write_mapped(interview, "user01")
    write_mapped(interview, "user02")
    prepare_pipeline(str(tmp_path))
    finalize_pipeline(str(tmp_path))
    canonical = interview / "mapped-transcript.md"
    canonical_review = interview / "mapped-transcript-review-01.md"
    canonical_review_before = canonical_review.read_text(encoding="utf-8")
    canonical_before = canonical.read_text(encoding="utf-8")

    transcript = interview / "transcript_user02.md"
    transcript.write_text(
        transcript_content("user02") + "\n[03:00] Changed", encoding="utf-8"
    )
    prepared = prepare_pipeline(str(tmp_path))
    assert prepared["counts"] == {"cached": 1, "pending": 1}
    partial = finalize_pipeline(str(tmp_path), allow_partial=True)
    assert partial["status"] == "partial"
    headers = open(partial["combined_file"], encoding="utf-8").read().splitlines()[2]
    assert "user01" in headers
    assert "user02" not in headers
    assert canonical.read_text(encoding="utf-8") == canonical_before
    assert canonical_review.read_text(encoding="utf-8") == canonical_review_before
    assert partial["review_files"][0].endswith("mapped-transcript-partial-review-01.md")


def test_added_and_removed_transcripts_invalidate_canonical(tmp_path):
    interview = create_study(tmp_path, count=2)
    prepare_pipeline(str(tmp_path))
    _run_all_tasks(tmp_path)
    finalize_pipeline(str(tmp_path))

    (interview / "transcript_user03.md").write_text(
        transcript_content("user03"),
        encoding="utf-8",
    )
    added = prepare_pipeline(str(tmp_path))
    assert added["canonical_current"] is False
    assert added["counts"] == {"cached": 2, "pending": 1}

    (interview / "transcript_user02.md").unlink()
    removed = prepare_pipeline(str(tmp_path))
    assert removed["canonical_current"] is False
    assert any(
        path.endswith("mapped-transcript-user02.md")
        for path in removed["orphaned_outputs"]
    )


def test_source_change_during_running_task_requires_reprepare(tmp_path):
    interview = create_study(tmp_path, count=1)
    prepare_pipeline(str(tmp_path))
    task = next_batch(str(tmp_path), now=10_000)["tasks"][0]
    (interview / "transcript_user01.md").write_text(
        transcript_content("changed"),
        encoding="utf-8",
    )
    with open(task["candidate_file"], "w", encoding="utf-8") as handle:
        handle.write(mapped_content("user01"))
    result = record_success(str(tmp_path), "user01")
    assert result["status"] == "failed"
    assert result["error"]["code"] == "SOURCE_CHANGED_DURING_MAPPING"


def test_modified_individual_mapping_invalidates_cache(tmp_path):
    interview = create_study(tmp_path, count=1)
    prepare_pipeline(str(tmp_path))
    _run_all_tasks(tmp_path)
    finalize_pipeline(str(tmp_path))
    mapped = interview / "mapped-transcript-user01.md"
    mapped.write_text(
        mapped.read_text(encoding="utf-8").replace(
            "My name is user01", "My name is edited"
        ),
        encoding="utf-8",
    )
    prepared = prepare_pipeline(str(tmp_path))
    assert prepared["canonical_current"] is False
    assert prepared["counts"] == {"pending": 1}


def test_missing_review_output_invalidates_skip_but_not_mapped_cache(tmp_path):
    interview = create_study(tmp_path, count=1)
    prepare_pipeline(str(tmp_path))
    _run_all_tasks(tmp_path)
    finalize_pipeline(str(tmp_path))
    (interview / "mapped-transcript-review-01.md").unlink()
    prepared = prepare_pipeline(str(tmp_path))
    assert prepared["canonical_current"] is False
    assert prepared["counts"] == {"cached": 1}


def test_status_exposes_attempts_and_errors(tmp_path):
    create_study(tmp_path, count=1)
    prepare_pipeline(str(tmp_path))
    next_batch(str(tmp_path), now=10_000)
    record_failure(
        str(tmp_path),
        "user01",
        code="TERMINAL_MAPPING_ERROR",
        message="bad input",
        transient=False,
    )
    status = pipeline_status(str(tmp_path))
    assert status["entries"]["user01"]["attempts"] == 1
    assert status["entries"]["user01"]["last_error"]["code"] == "TERMINAL_MAPPING_ERROR"


def test_cleanup_removes_only_controller_artifacts(tmp_path):
    interview = create_study(tmp_path, count=1)
    candidate = interview / ".mapped-transcript-user01.candidate.md"
    candidate.write_text("candidate", encoding="utf-8")
    chunk = interview / ".chunks_transcript_user01"
    chunk.mkdir()
    keep = interview / "notes.md"
    keep.write_text("keep", encoding="utf-8")
    result = cleanup_pipeline(str(tmp_path))
    assert len(result["removed"]) == 2
    assert keep.exists()


def _run_controller_cli(*args):
    completed = subprocess.run(
        [sys.executable, str(Path(mapping_pipeline.__file__)), *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, json.loads(completed.stdout)


def test_controller_cli_reports_documented_state_errors(tmp_path):
    code, payload = _run_controller_cli("status", tmp_path)
    assert code == 1
    assert payload["code"] == "NO_MANIFEST"

    (tmp_path / "mapping-manifest.json").write_text("{not-json", encoding="utf-8")
    code, payload = _run_controller_cli("status", tmp_path)
    assert code == 1
    assert payload["code"] == "INVALID_MANIFEST"

    (tmp_path / "mapping-manifest.json").unlink()
    create_study(tmp_path, count=1)
    code, payload = _run_controller_cli("prepare", tmp_path)
    assert code == 0
    assert payload["counts"] == {"pending": 1}

    code, payload = _run_controller_cli("record-success", tmp_path, "missing-user")
    assert code == 1
    assert payload["code"] == "UNKNOWN_TASK"

    code, payload = _run_controller_cli("record-success", tmp_path, "user01")
    assert code == 1
    assert payload["code"] == "INVALID_STATE"
