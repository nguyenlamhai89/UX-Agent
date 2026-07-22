import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts")))

import insights_pipeline
from insights_pipeline import (
    PipelineError,
    finalize_pipeline,
    next_batch,
    next_consolidation_batch,
    next_final_consolidation,
    pipeline_status,
    prepare_consolidation,
    prepare_final_consolidation,
    prepare_pipeline,
    record_consolidation_success,
    record_final_consolidation_success,
    record_success,
)
from saturation_test_helpers import (
    create_canonical,
    write_batch_candidate,
    write_extraction_candidate,
    write_final_candidate,
)


def _complete_extractions(mapped_file, *, now=10_000):
    batch_sizes = []
    while True:
        result = next_batch(str(mapped_file), now=now)
        if not result["tasks"]:
            break
        batch_sizes.append(len(result["tasks"]))
        for task in result["tasks"]:
            write_extraction_candidate(task)
            assert record_success(str(mapped_file), task["participant"])["status"] == "validated"
    return batch_sizes


def _complete_consolidation(mapped_file):
    prepared = prepare_consolidation(str(mapped_file))
    assert prepared["status"] == "ready"
    while True:
        result = next_consolidation_batch(str(mapped_file), now=10_000)
        if not result["tasks"]:
            break
        for task in result["tasks"]:
            write_batch_candidate(task)
            assert (
                record_consolidation_success(str(mapped_file), task["batch_id"])["status"]
                == "validated"
            )
    final = prepare_final_consolidation(str(mapped_file))
    if final.get("task_required"):
        task = next_final_consolidation(str(mapped_file), now=10_000)["task"]
        write_final_candidate(task)
        assert record_final_consolidation_success(str(mapped_file))["status"] == "validated"


def _run_full_pipeline(mapped_file, **prepare_kwargs):
    prepare_pipeline(str(mapped_file), **prepare_kwargs)
    _complete_extractions(mapped_file)
    _complete_consolidation(mapped_file)
    return finalize_pipeline(str(mapped_file))


def test_prepare_accepts_only_map_transcript_canonical_output(tmp_path):
    mapped_file = create_canonical(tmp_path)
    prepared = prepare_pipeline(str(mapped_file))
    assert prepared["input_file"] == str(mapped_file)
    assert prepared["counts"] == {"pending": 2}
    assert prepared["canonical_current"] is False


def test_prepare_rejects_missing_or_noncurrent_mapping_manifest(tmp_path):
    mapped_file = create_canonical(tmp_path)
    (mapped_file.parent / "mapping-manifest.json").unlink()
    with pytest.raises(PipelineError) as exc:
        prepare_pipeline(str(mapped_file))
    assert exc.value.code == "UPSTREAM_MANIFEST_MISSING"

    mapped_file = create_canonical(tmp_path)
    manifest_path = mapped_file.parent / "mapping-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["canonical_current"] = False
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PipelineError) as exc:
        prepare_pipeline(str(mapped_file))
    assert exc.value.code == "UPSTREAM_MAPPING_NOT_SUCCESS"


def test_extraction_batches_never_exceed_four(tmp_path):
    mapped_file = create_canonical(tmp_path, tuple(f"user{index:02d}" for index in range(1, 21)))
    prepare_pipeline(str(mapped_file), max_workers=4)
    assert _complete_extractions(mapped_file) == [4, 4, 4, 4, 4]


def test_invalid_grounding_retries_with_validator_diagnostic(tmp_path, monkeypatch):
    mapped_file = create_canonical(tmp_path, ("user01",))
    prepare_pipeline(str(mapped_file), max_attempts=2)
    monkeypatch.setattr(insights_pipeline.time, "time", lambda: 100.0)
    task = next_batch(str(mapped_file), now=100.0)["tasks"][0]
    candidate = {
        "participant": "user01",
        "insights": [
            {
                "local_id": "bad",
                "theme": "Product",
                "insight": "Frustrated with the workflow, because it fails",
                "evidence": [
                    {
                        "question_number": "2",
                        "theme": "Product",
                        "question": "What works?",
                        "observed_variable": "Value",
                        "timestamp": "00:15",
                        "quote": "Fabricated quote",
                    }
                ],
            }
        ],
    }
    Path(task["candidate_file"]).write_text(json.dumps(candidate), encoding="utf-8")
    result = record_success(str(mapped_file), "user01")
    assert result["status"] == "retry_pending"
    assert result["error"]["code"] == "EXTRACTION_VALIDATION_FAILED"
    assert "not grounded" in result["error"]["message"]
    assert next_batch(str(mapped_file), now=100.5)["status"] == "waiting"
    assert len(next_batch(str(mapped_file), now=101.0)["tasks"]) == 1


def test_partial_extraction_preserves_last_known_good_output(tmp_path):
    mapped_file = create_canonical(tmp_path)
    canonical = mapped_file.parent / "insights.md"
    canonical.write_text("old insights", encoding="utf-8")
    prepare_pipeline(str(mapped_file))
    batch = next_batch(str(mapped_file), now=10_000)
    first = batch["tasks"][0]
    write_extraction_candidate(first)
    record_success(str(mapped_file), first["participant"])
    result = prepare_consolidation(str(mapped_file))
    assert result["status"] == "partial"
    assert canonical.read_text(encoding="utf-8") == "old insights"


def test_full_pipeline_publishes_auditable_outputs_and_then_skips(tmp_path):
    mapped_file = create_canonical(tmp_path)
    result = _run_full_pipeline(mapped_file)
    assert result["status"] == "success"
    assert result["canonical_current"] is True
    assert result["interviewee_count"] == 2
    assert result["master_insight_count"] == 1
    assert {
        "insights.md",
        "insights-data.json",
        "insights-review-manifest.md",
        "saturation-chart.png",
        "all-insights-user01.md",
        "all-insights-user02.md",
    } == set(result["output_files"])
    data = json.loads((mapped_file.parent / "insights-data.json").read_text(encoding="utf-8"))
    entries = data["master_insights"][0]["interviewees"]
    assert entries["user01"]["status"] == "new"
    assert entries["user02"]["status"] == "repeated"
    prepared_again = prepare_pipeline(str(mapped_file))
    assert prepared_again["canonical_current"] is True
    assert prepared_again["counts"] == {"cached": 2}


def test_hierarchical_consolidation_requires_final_merge_for_multiple_batches(tmp_path):
    mapped_file = create_canonical(tmp_path)
    prepare_pipeline(str(mapped_file), max_insights_per_batch=1)
    _complete_extractions(mapped_file)
    assert prepare_consolidation(str(mapped_file))["batch_count"] == 2
    tasks = []
    while True:
        result = next_consolidation_batch(str(mapped_file), now=10_000)
        if not result["tasks"]:
            break
        tasks.extend(result["tasks"])
        for task in result["tasks"]:
            write_batch_candidate(task)
            record_consolidation_success(str(mapped_file), task["batch_id"])
    assert len(tasks) == 2
    final = prepare_final_consolidation(str(mapped_file))
    assert final["task_required"] is True
    task = next_final_consolidation(str(mapped_file), now=10_000)["task"]
    write_final_candidate(task)
    assert record_final_consolidation_success(str(mapped_file))["status"] == "validated"
    assert finalize_pipeline(str(mapped_file))["status"] == "success"


def test_changed_canonical_file_is_rejected_until_map_transcript_republishes(tmp_path):
    mapped_file = create_canonical(tmp_path)
    mapped_file.write_text(
        mapped_file.read_text(encoding="utf-8").replace("works for user01", "changed for user01"),
        encoding="utf-8",
    )
    with pytest.raises(PipelineError) as exc:
        prepare_pipeline(str(mapped_file))
    assert exc.value.code == "UPSTREAM_SIGNATURE_MISMATCH"


def test_status_exposes_attempts_and_grounding_failures(tmp_path, monkeypatch):
    mapped_file = create_canonical(tmp_path, ("user01",))
    prepare_pipeline(str(mapped_file))
    monkeypatch.setattr(insights_pipeline.time, "time", lambda: 100.0)
    task = next_batch(str(mapped_file), now=100.0)["tasks"][0]
    Path(task["candidate_file"]).write_text("{}", encoding="utf-8")
    record_success(str(mapped_file), "user01")
    status = pipeline_status(str(mapped_file))
    assert status["entries"]["user01"]["attempts"] == 1
    assert status["entries"]["user01"]["last_error"]["code"] == "EXTRACTION_VALIDATION_FAILED"


def test_atomic_promotion_rolls_back_existing_outputs(tmp_path, monkeypatch):
    interview = tmp_path / "Interview"
    staging = tmp_path / "staging"
    interview.mkdir()
    staging.mkdir()
    existing = interview / "insights.md"
    existing.write_text("old", encoding="utf-8")
    staged = staging / "insights.md"
    staged.write_text("new", encoding="utf-8")
    real_replace = insights_pipeline.os.replace
    calls = {"count": 0}

    def flaky_replace(source, destination):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("promotion failed")
        return real_replace(source, destination)

    monkeypatch.setattr(insights_pipeline.os, "replace", flaky_replace)
    with pytest.raises(OSError, match="promotion failed"):
        insights_pipeline._promote_outputs(
            [str(staged)], str(interview), [str(existing)]
        )
    assert existing.read_text(encoding="utf-8") == "old"
