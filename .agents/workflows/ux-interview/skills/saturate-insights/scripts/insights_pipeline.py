#!/usr/bin/env python3
"""Resumable controller for insight extraction, consolidation, and publication."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from insight_schema import (
    MappedTranscript,
    SchemaError,
    build_evidence_index,
    content_signature,
    derive_insights_data,
    file_signature,
    parse_mapped_transcript,
    render_participant_view,
    validate_extraction_candidate,
    validate_master_candidate,
)
from saturate_insights import MissingDependencyError, render_outputs


SCHEMA_VERSION = 2
RENDERER_VERSION = 1
DEFAULT_MAX_WORKERS = 4
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MAX_INSIGHTS_PER_BATCH = 100
RETRY_BACKOFF_SECONDS = [1, 2, 4, 8]
COMPLETE_STATUSES = {"cached", "validated"}
RETRYABLE_STATUSES = {"pending", "retry_pending"}


class PipelineError(RuntimeError):
    """Structured controller error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _utc_timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _interview_dir(mapped_file: str) -> str:
    return os.path.dirname(os.path.abspath(mapped_file))


def _manifest_path(mapped_file: str) -> str:
    return os.path.join(_interview_dir(mapped_file), "saturation-manifest.json")


def _state_dir(mapped_file: str) -> str:
    return os.path.join(_interview_dir(mapped_file), ".saturation")


def _atomic_write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise


def _atomic_write_json(path: str, data: Any) -> None:
    _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _load_json(path: str, *, code: str = "INVALID_JSON") -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise PipelineError(code, f"Required file not found: {path}")
    except json.JSONDecodeError as exc:
        raise PipelineError(code, f"Invalid JSON in {path}: {exc}") from exc


def _load_manifest(mapped_file: str) -> dict[str, Any] | None:
    path = _manifest_path(mapped_file)
    if not os.path.isfile(path):
        return None
    data = _load_json(path, code="INVALID_MANIFEST")
    if not isinstance(data, dict) or data.get("version") != 1:
        raise PipelineError("INVALID_MANIFEST", "Unsupported saturation manifest structure.")
    return data


def _save_manifest(mapped_file: str, manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = _utc_timestamp()
    _atomic_write_json(_manifest_path(mapped_file), manifest)


def _validate_settings(max_workers: int, max_attempts: int, max_insights_per_batch: int) -> None:
    if max_workers < 1 or max_workers > 4:
        raise PipelineError("INVALID_INPUT", "max_workers must be between 1 and 4.")
    if max_attempts < 1:
        raise PipelineError("INVALID_INPUT", "max_attempts must be at least 1.")
    if max_insights_per_batch < 1:
        raise PipelineError("INVALID_INPUT", "max_insights_per_batch must be positive.")


def _verify_upstream_mapping(mapped_file: str) -> None:
    """Verify the adjacent map-transcript controller state without changing the public input."""
    manifest_path = os.path.join(_interview_dir(mapped_file), "mapping-manifest.json")
    if not os.path.isfile(manifest_path):
        raise PipelineError(
            "UPSTREAM_MANIFEST_MISSING",
            "mapping-manifest.json is required beside mapped-transcript.md.",
        )
    manifest = _load_json(manifest_path, code="UPSTREAM_MANIFEST_INVALID")
    if not isinstance(manifest, dict):
        raise PipelineError("UPSTREAM_MANIFEST_INVALID", "Mapping manifest root must be an object.")
    if manifest.get("status") != "success" or manifest.get("canonical_current") is not True:
        raise PipelineError(
            "UPSTREAM_MAPPING_NOT_SUCCESS",
            "map-transcript must have status=success and canonical_current=true.",
        )
    outputs = manifest.get("outputs")
    expected = os.path.abspath(mapped_file)
    if not isinstance(outputs, dict) or os.path.abspath(outputs.get("combined_file", "")) != expected:
        raise PipelineError(
            "UPSTREAM_OUTPUT_MISMATCH",
            "Mapping manifest does not identify this mapped-transcript.md as canonical.",
        )
    signatures = manifest.get("output_signatures")
    expected_signature = signatures.get(expected) if isinstance(signatures, dict) else None
    if expected_signature != file_signature(expected):
        raise PipelineError(
            "UPSTREAM_SIGNATURE_MISMATCH",
            "mapped-transcript.md no longer matches the signature published by map-transcript.",
        )


def _fingerprint(input_signature: dict[str, Any]) -> str:
    return content_signature(
        json.dumps(
            [input_signature["sha256"], SCHEMA_VERSION, RENDERER_VERSION],
            separators=(",", ":"),
        )
    )


def _safe_key(value: str) -> str:
    return content_signature(value)[:16]


def _outputs_are_current(outputs: Any) -> bool:
    if not isinstance(outputs, dict):
        return False
    files = outputs.get("files")
    signatures = outputs.get("signatures")
    if not isinstance(files, list) or not files or not isinstance(signatures, dict):
        return False
    try:
        return all(
            os.path.isfile(path) and signatures.get(path) == file_signature(path)
            for path in files
        )
    except OSError:
        return False


def _load_valid_cached_extraction(
    path: str,
    mapped: MappedTranscript,
    participant: str,
) -> bool:
    if not os.path.isfile(path):
        return False
    try:
        cached = _load_json(path)
        validate_extraction_candidate(cached, mapped, participant)
        return True
    except (PipelineError, SchemaError, TypeError):
        return False


def prepare_pipeline(
    mapped_file: str,
    *,
    max_workers: int = DEFAULT_MAX_WORKERS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    max_insights_per_batch: int = DEFAULT_MAX_INSIGHTS_PER_BATCH,
) -> dict[str, Any]:
    """Validate canonical input, build isolated views, and initialize resumable work."""
    _validate_settings(max_workers, max_attempts, max_insights_per_batch)
    try:
        mapped = parse_mapped_transcript(mapped_file)
    except SchemaError as exc:
        raise PipelineError("INVALID_MAPPED_TRANSCRIPT", str(exc)) from exc
    _verify_upstream_mapping(mapped.path)
    input_signature = file_signature(mapped.path)
    fingerprint = _fingerprint(input_signature)
    previous = _load_manifest(mapped.path)
    previous_entries = previous.get("entries", {}) if previous else {}
    state_dir = _state_dir(mapped.path)
    view_dir = os.path.join(state_dir, "views")
    candidate_dir = os.path.join(state_dir, "candidates")
    cache_dir = os.path.join(state_dir, "cache")
    for directory in (view_dir, candidate_dir, cache_dir):
        os.makedirs(directory, exist_ok=True)

    entries: dict[str, dict[str, Any]] = {}
    for index, participant in enumerate(mapped.interviewees, start=1):
        key = _safe_key(participant)
        view_content = render_participant_view(mapped, participant)
        view_signature = content_signature(view_content)
        view_file = os.path.join(view_dir, f"participant-{index:03d}-{key}.md")
        candidate_file = os.path.join(candidate_dir, f"extraction-{key}.json")
        extraction_file = os.path.join(cache_dir, f"extraction-{key}.json")
        _atomic_write_text(view_file, view_content)
        previous_entry = previous_entries.get(participant, {})
        cache_valid = bool(
            previous_entry.get("view_signature") == view_signature
            and _load_valid_cached_extraction(extraction_file, mapped, participant)
        )
        if os.path.exists(candidate_file):
            os.remove(candidate_file)
        entries[participant] = {
            "participant": participant,
            "order": index,
            "view_file": view_file,
            "view_signature": view_signature,
            "candidate_file": candidate_file,
            "extraction_file": extraction_file,
            "status": "cached" if cache_valid else "pending",
            "attempts": 0,
            "max_attempts": max_attempts,
            "next_attempt_at": 0.0,
            "last_error": None,
        }

    all_cached = all(entry["status"] == "cached" for entry in entries.values())
    canonical_current = bool(
        previous
        and previous.get("fingerprint") == fingerprint
        and previous.get("status") == "success"
        and all_cached
        and _outputs_are_current(previous.get("outputs"))
    )
    previous_outputs = previous.get("outputs", {}) if previous else {}
    manifest = {
        "version": 1,
        "schema_version": SCHEMA_VERSION,
        "renderer_version": RENDERER_VERSION,
        "created_at": previous.get("created_at", _utc_timestamp()) if previous else _utc_timestamp(),
        "updated_at": _utc_timestamp(),
        "mapped_transcript_file": mapped.path,
        "input_signature": input_signature,
        "fingerprint": fingerprint,
        "interviewees": mapped.interviewees,
        "settings": {
            "max_workers": max_workers,
            "max_attempts": max_attempts,
            "max_insights_per_batch": max_insights_per_batch,
            "retry_backoff_seconds": RETRY_BACKOFF_SECONDS,
        },
        "status": "success" if canonical_current else "extracting",
        "canonical_current": canonical_current,
        "entries": entries,
        "consolidation": previous.get("consolidation", {}) if canonical_current else {},
        "outputs": previous_outputs,
        "failures": [],
    }
    _save_manifest(mapped.path, manifest)
    return _public_status(manifest)


def _retry_delay(manifest: dict[str, Any], attempts: int) -> int:
    schedule = manifest["settings"].get("retry_backoff_seconds", RETRY_BACKOFF_SECONDS)
    return int(schedule[min(max(attempts - 1, 0), len(schedule) - 1)])


def _claim_entries(entries: dict[str, dict[str, Any]], max_workers: int, now: float) -> list[dict[str, Any]]:
    if any(entry["status"] == "running" for entry in entries.values()):
        return []
    ready: list[dict[str, Any]] = []
    for entry in sorted(entries.values(), key=lambda value: value.get("order", 0)):
        if entry["status"] not in RETRYABLE_STATUSES:
            continue
        if entry["attempts"] >= entry["max_attempts"]:
            entry["status"] = "failed"
            continue
        if float(entry.get("next_attempt_at", 0.0)) > now:
            continue
        entry["status"] = "running"
        entry["attempts"] += 1
        ready.append(entry)
        if len(ready) >= max_workers:
            break
    return ready


def next_batch(mapped_file: str, *, now: float | None = None) -> dict[str, Any]:
    manifest = _load_manifest(mapped_file)
    if not manifest:
        raise PipelineError("NO_MANIFEST", "Run prepare before next-batch.")
    timestamp = time.time() if now is None else now
    entries = manifest["entries"]
    already_running = any(entry["status"] == "running" for entry in entries.values())
    claimed = _claim_entries(entries, int(manifest["settings"]["max_workers"]), timestamp)
    _save_manifest(mapped_file, manifest)
    unfinished = any(entry["status"] not in COMPLETE_STATUSES | {"failed"} for entry in entries.values())
    status = "ready" if claimed else "busy" if already_running else "waiting" if unfinished else "idle"
    return {
        "status": status,
        "max_workers": manifest["settings"]["max_workers"],
        "tasks": [
            {
                "participant": entry["participant"],
                "input_file": entry["view_file"],
                "candidate_file": entry["candidate_file"],
                "attempt": entry["attempts"],
                "max_attempts": entry["max_attempts"],
                "last_error": entry.get("last_error"),
            }
            for entry in claimed
        ],
    }


def _record_failure(
    manifest: dict[str, Any],
    entry: dict[str, Any],
    *,
    code: str,
    message: str,
    transient: bool,
) -> dict[str, Any]:
    error = {"code": code, "message": message, "transient": transient}
    entry["last_error"] = error
    retry_after = 0
    if transient and entry["attempts"] < entry["max_attempts"]:
        retry_after = _retry_delay(manifest, entry["attempts"])
        entry["next_attempt_at"] = time.time() + retry_after
        entry["status"] = "retry_pending"
    else:
        entry["status"] = "failed"
    return {
        "status": entry["status"],
        "error": error,
        "retry_after_seconds": retry_after,
    }


def record_success(mapped_file: str, participant: str) -> dict[str, Any]:
    manifest = _load_manifest(mapped_file)
    if not manifest or participant not in manifest.get("entries", {}):
        raise PipelineError("UNKNOWN_TASK", f"Unknown extraction task: {participant}")
    entry = manifest["entries"][participant]
    if entry["status"] != "running":
        raise PipelineError("INVALID_TASK_STATE", f"Task is not running: {participant}")
    if file_signature(mapped_file) != manifest["input_signature"]:
        result = _record_failure(
            manifest,
            entry,
            code="UPSTREAM_CHANGED_DURING_EXTRACTION",
            message="mapped-transcript.md changed after prepare.",
            transient=False,
        )
        _save_manifest(mapped_file, manifest)
        return result
    try:
        mapped = parse_mapped_transcript(mapped_file)
        candidate = _load_json(entry["candidate_file"], code="INVALID_EXTRACTION_JSON")
        validated = validate_extraction_candidate(candidate, mapped, participant)
    except (PipelineError, SchemaError, TypeError) as exc:
        result = _record_failure(
            manifest,
            entry,
            code="EXTRACTION_VALIDATION_FAILED",
            message=str(exc),
            transient=True,
        )
        _save_manifest(mapped_file, manifest)
        return result
    _atomic_write_json(entry["extraction_file"], validated)
    entry["status"] = "validated"
    entry["last_error"] = None
    entry["next_attempt_at"] = 0.0
    if os.path.exists(entry["candidate_file"]):
        os.remove(entry["candidate_file"])
    _save_manifest(mapped_file, manifest)
    return {"status": "validated", "participant": participant}


def record_failure(
    mapped_file: str,
    participant: str,
    *,
    code: str,
    message: str,
    transient: bool,
) -> dict[str, Any]:
    manifest = _load_manifest(mapped_file)
    if not manifest or participant not in manifest.get("entries", {}):
        raise PipelineError("UNKNOWN_TASK", f"Unknown extraction task: {participant}")
    entry = manifest["entries"][participant]
    if entry["status"] != "running":
        raise PipelineError("INVALID_TASK_STATE", f"Task is not running: {participant}")
    result = _record_failure(
        manifest,
        entry,
        code=code,
        message=message,
        transient=transient,
    )
    _save_manifest(mapped_file, manifest)
    return result


def _load_extractions(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _load_json(entry["extraction_file"], code="MISSING_VALIDATED_EXTRACTION")
        for entry in sorted(manifest["entries"].values(), key=lambda value: value["order"])
    ]


def prepare_consolidation(mapped_file: str) -> dict[str, Any]:
    manifest = _load_manifest(mapped_file)
    if not manifest:
        raise PipelineError("NO_MANIFEST", "Run prepare before consolidation.")
    incomplete = [
        {"participant": name, "status": entry["status"], "error": entry.get("last_error")}
        for name, entry in manifest["entries"].items()
        if entry["status"] not in COMPLETE_STATUSES
    ]
    if incomplete:
        manifest["status"] = "partial"
        manifest["canonical_current"] = False
        manifest["failures"] = incomplete
        _save_manifest(mapped_file, manifest)
        return {"status": "partial", "code": "PARTIAL_EXTRACTION", "failures": incomplete}

    extractions = _load_extractions(manifest)
    local_insights = [insight for extraction in extractions for insight in extraction["insights"]]
    state_dir = os.path.join(_state_dir(mapped_file), "consolidation")
    os.makedirs(state_dir, exist_ok=True)
    max_per_batch = int(manifest["settings"]["max_insights_per_batch"])
    entries: dict[str, dict[str, Any]] = {}
    for offset in range(0, len(local_insights), max_per_batch):
        batch_number = offset // max_per_batch + 1
        batch_id = f"batch-{batch_number:03d}"
        items = local_insights[offset : offset + max_per_batch]
        expected_ids = [evidence_id for item in items for evidence_id in item["evidence_ids"]]
        input_file = os.path.join(state_dir, f"{batch_id}-input.json")
        candidate_file = os.path.join(state_dir, f"{batch_id}-candidate.json")
        validated_file = os.path.join(state_dir, f"{batch_id}-validated.json")
        _atomic_write_json(input_file, {"local_insights": items, "expected_evidence_ids": expected_ids})
        for removable in (candidate_file, validated_file):
            if os.path.exists(removable):
                os.remove(removable)
        entries[batch_id] = {
            "batch_id": batch_id,
            "order": batch_number,
            "input_file": input_file,
            "candidate_file": candidate_file,
            "validated_file": validated_file,
            "expected_evidence_ids": expected_ids,
            "status": "pending",
            "attempts": 0,
            "max_attempts": manifest["settings"]["max_attempts"],
            "next_attempt_at": 0.0,
            "last_error": None,
        }
    manifest["consolidation"] = {
        "stage": "batching" if entries else "empty",
        "entries": entries,
        "final": {},
    }
    manifest["status"] = "consolidating"
    manifest["failures"] = []
    _save_manifest(mapped_file, manifest)
    return {"status": "ready", "batch_count": len(entries), "local_insight_count": len(local_insights)}


def next_consolidation_batch(mapped_file: str, *, now: float | None = None) -> dict[str, Any]:
    manifest = _load_manifest(mapped_file)
    entries = manifest.get("consolidation", {}).get("entries", {}) if manifest else {}
    if not manifest or not isinstance(entries, dict):
        raise PipelineError("NO_CONSOLIDATION", "Run prepare-consolidation first.")
    timestamp = time.time() if now is None else now
    already_running = any(entry["status"] == "running" for entry in entries.values())
    claimed = _claim_entries(entries, int(manifest["settings"]["max_workers"]), timestamp)
    _save_manifest(mapped_file, manifest)
    unfinished = any(entry["status"] not in COMPLETE_STATUSES | {"failed"} for entry in entries.values())
    status = "ready" if claimed else "busy" if already_running else "waiting" if unfinished else "idle"
    return {
        "status": status,
        "tasks": [
            {
                "batch_id": entry["batch_id"],
                "input_file": entry["input_file"],
                "candidate_file": entry["candidate_file"],
                "attempt": entry["attempts"],
                "last_error": entry.get("last_error"),
            }
            for entry in claimed
        ],
    }


def _evidence_index_from_manifest(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return build_evidence_index(_load_extractions(manifest))


def record_consolidation_success(mapped_file: str, batch_id: str) -> dict[str, Any]:
    manifest = _load_manifest(mapped_file)
    entries = manifest.get("consolidation", {}).get("entries", {}) if manifest else {}
    if batch_id not in entries:
        raise PipelineError("UNKNOWN_TASK", f"Unknown consolidation batch: {batch_id}")
    entry = entries[batch_id]
    if entry["status"] != "running":
        raise PipelineError("INVALID_TASK_STATE", f"Batch is not running: {batch_id}")
    try:
        candidate = _load_json(entry["candidate_file"], code="INVALID_CONSOLIDATION_JSON")
        evidence_index = _evidence_index_from_manifest(manifest)
        validated = validate_master_candidate(
            candidate,
            evidence_index,
            set(entry["expected_evidence_ids"]),
        )
    except (PipelineError, SchemaError, TypeError) as exc:
        result = _record_failure(
            manifest,
            entry,
            code="CONSOLIDATION_VALIDATION_FAILED",
            message=str(exc),
            transient=True,
        )
        _save_manifest(mapped_file, manifest)
        return result
    _atomic_write_json(entry["validated_file"], validated)
    entry["status"] = "validated"
    entry["last_error"] = None
    if os.path.exists(entry["candidate_file"]):
        os.remove(entry["candidate_file"])
    _save_manifest(mapped_file, manifest)
    return {"status": "validated", "batch_id": batch_id}


def record_consolidation_failure(
    mapped_file: str,
    batch_id: str,
    *,
    code: str,
    message: str,
    transient: bool,
) -> dict[str, Any]:
    manifest = _load_manifest(mapped_file)
    entries = manifest.get("consolidation", {}).get("entries", {}) if manifest else {}
    if batch_id not in entries:
        raise PipelineError("UNKNOWN_TASK", f"Unknown consolidation batch: {batch_id}")
    entry = entries[batch_id]
    if entry["status"] != "running":
        raise PipelineError("INVALID_TASK_STATE", f"Batch is not running: {batch_id}")
    result = _record_failure(manifest, entry, code=code, message=message, transient=transient)
    _save_manifest(mapped_file, manifest)
    return result


def prepare_final_consolidation(mapped_file: str) -> dict[str, Any]:
    manifest = _load_manifest(mapped_file)
    consolidation = manifest.get("consolidation", {}) if manifest else {}
    entries = consolidation.get("entries", {})
    if not manifest or not isinstance(entries, dict):
        raise PipelineError("NO_CONSOLIDATION", "Run prepare-consolidation first.")
    incomplete = [entry["batch_id"] for entry in entries.values() if entry["status"] not in COMPLETE_STATUSES]
    if incomplete:
        return {"status": "partial", "code": "PARTIAL_CONSOLIDATION", "failures": incomplete}
    state_dir = os.path.join(_state_dir(mapped_file), "consolidation")
    evidence_index = _evidence_index_from_manifest(manifest)
    expected_ids = set(evidence_index)
    if not entries:
        final_validated = os.path.join(state_dir, "final-validated.json")
        _atomic_write_json(final_validated, {"master_insights": []})
        consolidation["final"] = {"status": "validated", "validated_file": final_validated}
        consolidation["stage"] = "finalized"
        _save_manifest(mapped_file, manifest)
        return {"status": "validated", "task": None}

    batch_groups: list[dict[str, Any]] = []
    for entry in sorted(entries.values(), key=lambda value: value["order"]):
        batch_groups.extend(_load_json(entry["validated_file"])["master_insights"])
    if len(entries) == 1:
        validated = validate_master_candidate(
            {"master_insights": batch_groups}, evidence_index, expected_ids
        )
        final_validated = os.path.join(state_dir, "final-validated.json")
        _atomic_write_json(final_validated, validated)
        consolidation["final"] = {"status": "validated", "validated_file": final_validated}
        consolidation["stage"] = "finalized"
        _save_manifest(mapped_file, manifest)
        return {"status": "validated", "task": None}

    final_input = os.path.join(state_dir, "final-input.json")
    final_candidate = os.path.join(state_dir, "final-candidate.json")
    final_validated = os.path.join(state_dir, "final-validated.json")
    _atomic_write_json(
        final_input,
        {"batch_master_insights": batch_groups, "expected_evidence_ids": sorted(expected_ids)},
    )
    for removable in (final_candidate, final_validated):
        if os.path.exists(removable):
            os.remove(removable)
    consolidation["final"] = {
        "status": "pending",
        "input_file": final_input,
        "candidate_file": final_candidate,
        "validated_file": final_validated,
        "attempts": 0,
        "max_attempts": manifest["settings"]["max_attempts"],
        "next_attempt_at": 0.0,
        "last_error": None,
    }
    consolidation["stage"] = "final"
    _save_manifest(mapped_file, manifest)
    return {"status": "ready", "task_required": True}


def next_final_consolidation(mapped_file: str, *, now: float | None = None) -> dict[str, Any]:
    manifest = _load_manifest(mapped_file)
    final = manifest.get("consolidation", {}).get("final", {}) if manifest else {}
    if not manifest or not final:
        raise PipelineError("NO_FINAL_CONSOLIDATION", "Run prepare-final-consolidation first.")
    if final.get("status") == "validated":
        return {"status": "idle", "task": None}
    timestamp = time.time() if now is None else now
    if final["status"] == "running":
        return {"status": "busy", "task": None}
    if final["status"] not in RETRYABLE_STATUSES:
        return {"status": "idle", "task": None}
    if final["attempts"] >= final["max_attempts"]:
        final["status"] = "failed"
        _save_manifest(mapped_file, manifest)
        return {"status": "idle", "task": None}
    if float(final.get("next_attempt_at", 0.0)) > timestamp:
        return {"status": "waiting", "task": None}
    final["status"] = "running"
    final["attempts"] += 1
    _save_manifest(mapped_file, manifest)
    return {
        "status": "ready",
        "task": {
            "input_file": final["input_file"],
            "candidate_file": final["candidate_file"],
            "attempt": final["attempts"],
            "last_error": final.get("last_error"),
        },
    }


def record_final_consolidation_success(mapped_file: str) -> dict[str, Any]:
    manifest = _load_manifest(mapped_file)
    final = manifest.get("consolidation", {}).get("final", {}) if manifest else {}
    if not manifest or final.get("status") != "running":
        raise PipelineError("INVALID_TASK_STATE", "Final consolidation is not running.")
    try:
        candidate = _load_json(final["candidate_file"], code="INVALID_CONSOLIDATION_JSON")
        evidence_index = _evidence_index_from_manifest(manifest)
        validated = validate_master_candidate(candidate, evidence_index, set(evidence_index))
    except (PipelineError, SchemaError, TypeError) as exc:
        result = _record_failure(
            manifest,
            final,
            code="FINAL_CONSOLIDATION_VALIDATION_FAILED",
            message=str(exc),
            transient=True,
        )
        _save_manifest(mapped_file, manifest)
        return result
    _atomic_write_json(final["validated_file"], validated)
    final["status"] = "validated"
    final["last_error"] = None
    manifest["consolidation"]["stage"] = "finalized"
    if os.path.exists(final["candidate_file"]):
        os.remove(final["candidate_file"])
    _save_manifest(mapped_file, manifest)
    return {"status": "validated"}


def record_final_consolidation_failure(
    mapped_file: str,
    *,
    code: str,
    message: str,
    transient: bool,
) -> dict[str, Any]:
    manifest = _load_manifest(mapped_file)
    final = manifest.get("consolidation", {}).get("final", {}) if manifest else {}
    if not manifest or final.get("status") != "running":
        raise PipelineError("INVALID_TASK_STATE", "Final consolidation is not running.")
    result = _record_failure(manifest, final, code=code, message=message, transient=transient)
    _save_manifest(mapped_file, manifest)
    return result


def _is_owned_output(path: str, interview_dir: str) -> bool:
    if os.path.dirname(os.path.abspath(path)) != os.path.abspath(interview_dir):
        return False
    name = os.path.basename(path)
    return name in {
        "insights.md",
        "insights-data.json",
        "insights-review-manifest.md",
        "saturation-chart.png",
    } or (name.startswith("all-insights-") and name.endswith(".md"))


def _promote_outputs(
    staged_paths: list[str],
    interview_dir: str,
    previous_files: list[str],
) -> list[str]:
    staged_by_name = {os.path.basename(path): path for path in staged_paths}
    target_paths = [os.path.join(interview_dir, name) for name in staged_by_name]
    previous_owned = [path for path in previous_files if _is_owned_output(path, interview_dir)]
    backup_dir = tempfile.mkdtemp(prefix=".saturation-backup-", dir=interview_dir)
    backed_up: list[tuple[str, str]] = []
    promoted: list[str] = []
    try:
        for index, path in enumerate(sorted(set(target_paths + previous_owned))):
            if os.path.isfile(path):
                backup = os.path.join(backup_dir, f"{index:04d}-{os.path.basename(path)}")
                os.replace(path, backup)
                backed_up.append((path, backup))
        for target in target_paths:
            os.replace(staged_by_name[os.path.basename(target)], target)
            promoted.append(target)
        shutil.rmtree(backup_dir)
        return target_paths
    except Exception:
        for path in promoted:
            if os.path.isfile(path):
                os.remove(path)
        for original, backup in backed_up:
            if os.path.isfile(backup):
                os.replace(backup, original)
        shutil.rmtree(backup_dir, ignore_errors=True)
        raise


def finalize_pipeline(mapped_file: str) -> dict[str, Any]:
    manifest = _load_manifest(mapped_file)
    if not manifest:
        raise PipelineError("NO_MANIFEST", "Run prepare before finalize.")
    final = manifest.get("consolidation", {}).get("final", {})
    if final.get("status") != "validated":
        manifest["status"] = "partial"
        manifest["canonical_current"] = False
        _save_manifest(mapped_file, manifest)
        return {
            "status": "partial",
            "code": "PARTIAL_CONSOLIDATION",
            "canonical_files_updated": False,
        }
    if file_signature(mapped_file) != manifest["input_signature"]:
        raise PipelineError(
            "UPSTREAM_CHANGED_DURING_CONSOLIDATION",
            "mapped-transcript.md changed after prepare; run prepare again.",
        )
    _verify_upstream_mapping(mapped_file)
    mapped = parse_mapped_transcript(mapped_file)
    evidence_index = _evidence_index_from_manifest(manifest)
    candidate = _load_json(final["validated_file"], code="MISSING_FINAL_CONSOLIDATION")
    validated = validate_master_candidate(candidate, evidence_index, set(evidence_index))
    data = derive_insights_data(mapped, validated, evidence_index, manifest["input_signature"])
    interview_dir = _interview_dir(mapped_file)
    staging_dir = tempfile.mkdtemp(prefix=".saturation-staging-", dir=interview_dir)
    try:
        staged_paths = render_outputs(data, staging_dir)
        if not all(os.path.isfile(path) and os.path.getsize(path) > 0 for path in staged_paths):
            raise PipelineError("OUTPUT_VALIDATION_ERROR", "One or more staged artifacts are missing or empty.")
        previous_files = manifest.get("outputs", {}).get("files", [])
        published = _promote_outputs(staged_paths, interview_dir, previous_files)
    except MissingDependencyError as exc:
        raise PipelineError("MISSING_DEPENDENCY", str(exc)) from exc
    except PipelineError:
        raise
    except Exception as exc:
        raise PipelineError("ATOMIC_PROMOTION_ERROR", str(exc)) from exc
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    outputs = {
        "files": published,
        "signatures": {path: file_signature(path) for path in published},
    }
    manifest["status"] = "success"
    manifest["canonical_current"] = True
    manifest["outputs"] = outputs
    manifest["failures"] = []
    manifest["summary"] = {
        "interviewee_count": len(mapped.interviewees),
        "master_insight_count": len(data["master_insights"]),
    }
    _save_manifest(mapped_file, manifest)
    cleanup_pipeline(mapped_file)
    return {
        "status": "success",
        "canonical_current": True,
        "input_file": os.path.abspath(mapped_file),
        "input_signature": manifest["input_signature"]["sha256"],
        "output_files": [os.path.basename(path) for path in published],
        "manifest_file": _manifest_path(mapped_file),
        "interviewee_count": len(mapped.interviewees),
        "master_insight_count": len(data["master_insights"]),
        "failures": [],
    }


def cleanup_pipeline(mapped_file: str) -> dict[str, Any]:
    """Remove only controller-owned ephemeral artifacts; keep validated caches."""
    interview_dir = _interview_dir(mapped_file)
    removed: list[str] = []
    for child in Path(interview_dir).iterdir() if os.path.isdir(interview_dir) else []:
        if child.is_dir() and (
            child.name.startswith(".saturation-staging-")
            or child.name.startswith(".saturation-backup-")
        ):
            shutil.rmtree(child)
            removed.append(str(child))
    state_dir = _state_dir(mapped_file)
    for name in ("views", "candidates"):
        path = os.path.join(state_dir, name)
        if os.path.isdir(path):
            shutil.rmtree(path)
            removed.append(path)
    consolidation_dir = os.path.join(state_dir, "consolidation")
    if os.path.isdir(consolidation_dir):
        for child in Path(consolidation_dir).glob("*-candidate.json"):
            child.unlink()
            removed.append(str(child))
    return {"status": "success", "removed": sorted(removed)}


def _public_status(manifest: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for entry in manifest["entries"].values():
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    return {
        "status": manifest["status"],
        "canonical_current": manifest["canonical_current"],
        "input_file": manifest["mapped_transcript_file"],
        "input_signature": manifest["input_signature"]["sha256"],
        "fingerprint": manifest["fingerprint"],
        "interviewees": manifest["interviewees"],
        "counts": counts,
        "manifest_file": _manifest_path(manifest["mapped_transcript_file"]),
        "outputs": manifest.get("outputs", {}),
    }


def pipeline_status(mapped_file: str) -> dict[str, Any]:
    manifest = _load_manifest(mapped_file)
    if not manifest:
        raise PipelineError("NO_MANIFEST", "No saturation manifest exists.")
    payload = _public_status(manifest)
    payload["entries"] = {
        participant: {
            "status": entry["status"],
            "attempts": entry["attempts"],
            "last_error": entry.get("last_error"),
        }
        for participant, entry in manifest["entries"].items()
    }
    payload["consolidation"] = manifest.get("consolidation", {})
    return payload


def _add_common_failure_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--code", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--transient", action="store_true")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("mapped_transcript_file")
    prepare.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    prepare.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    prepare.add_argument("--max-insights-per-batch", type=int, default=DEFAULT_MAX_INSIGHTS_PER_BATCH)
    for command in ("next-batch", "prepare-consolidation", "next-consolidation-batch", "prepare-final-consolidation", "next-final-consolidation", "record-final-consolidation-success", "finalize", "status", "cleanup"):
        subparser = commands.add_parser(command)
        subparser.add_argument("mapped_transcript_file")
    record = commands.add_parser("record-success")
    record.add_argument("mapped_transcript_file")
    record.add_argument("participant")
    failure = commands.add_parser("record-failure")
    failure.add_argument("mapped_transcript_file")
    failure.add_argument("participant")
    _add_common_failure_arguments(failure)
    consolidation = commands.add_parser("record-consolidation-success")
    consolidation.add_argument("mapped_transcript_file")
    consolidation.add_argument("batch_id")
    consolidation_failure = commands.add_parser("record-consolidation-failure")
    consolidation_failure.add_argument("mapped_transcript_file")
    consolidation_failure.add_argument("batch_id")
    _add_common_failure_arguments(consolidation_failure)
    final_failure = commands.add_parser("record-final-consolidation-failure")
    final_failure.add_argument("mapped_transcript_file")
    _add_common_failure_arguments(final_failure)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    mapped_file = args.mapped_transcript_file
    try:
        if args.command == "prepare":
            payload = prepare_pipeline(
                mapped_file,
                max_workers=args.max_workers,
                max_attempts=args.max_attempts,
                max_insights_per_batch=args.max_insights_per_batch,
            )
        elif args.command == "next-batch":
            payload = next_batch(mapped_file)
        elif args.command == "record-success":
            payload = record_success(mapped_file, args.participant)
        elif args.command == "record-failure":
            payload = record_failure(mapped_file, args.participant, code=args.code, message=args.message, transient=args.transient)
        elif args.command == "prepare-consolidation":
            payload = prepare_consolidation(mapped_file)
        elif args.command == "next-consolidation-batch":
            payload = next_consolidation_batch(mapped_file)
        elif args.command == "record-consolidation-success":
            payload = record_consolidation_success(mapped_file, args.batch_id)
        elif args.command == "record-consolidation-failure":
            payload = record_consolidation_failure(mapped_file, args.batch_id, code=args.code, message=args.message, transient=args.transient)
        elif args.command == "prepare-final-consolidation":
            payload = prepare_final_consolidation(mapped_file)
        elif args.command == "next-final-consolidation":
            payload = next_final_consolidation(mapped_file)
        elif args.command == "record-final-consolidation-success":
            payload = record_final_consolidation_success(mapped_file)
        elif args.command == "record-final-consolidation-failure":
            payload = record_final_consolidation_failure(mapped_file, code=args.code, message=args.message, transient=args.transient)
        elif args.command == "finalize":
            payload = finalize_pipeline(mapped_file)
        elif args.command == "status":
            payload = pipeline_status(mapped_file)
        else:
            payload = cleanup_pipeline(mapped_file)
        code = 2 if payload.get("status") == "partial" else 0
    except PipelineError as exc:
        payload = {"status": "error", "code": exc.code, "message": str(exc)}
        code = 1
    except PermissionError as exc:
        payload = {"status": "error", "code": "PERMISSION_ERROR", "message": str(exc)}
        code = 1
    except UnicodeError as exc:
        payload = {"status": "error", "code": "ENCODING_ERROR", "message": str(exc)}
        code = 1
    except OSError as exc:
        payload = {"status": "error", "code": "WRITE_FAILURE", "message": str(exc)}
        code = 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
