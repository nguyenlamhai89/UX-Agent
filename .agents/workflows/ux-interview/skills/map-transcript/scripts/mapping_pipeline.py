#!/usr/bin/env python3
"""Stateful controller for bounded, resumable transcript mapping.

The controller does not call an LLM. It prepares deterministic tasks for the
parent Antigravity agent, enforces a bounded batch size, validates candidate
outputs, preserves last-known-good mapped files, controls retries, and only
publishes the canonical combined output after every expected transcript passes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from chunk_transcript import chunk_transcript_file, cleanup_chunk_directory
from map_transcript import (
    PartialMappingError,
    extract_audio_name,
    extract_transcript_audio_name,
    find_mapped_transcripts,
    find_transcripts,
    merge_mapping_outputs,
)
from validate_mapping import BASE_HEADERS, parse_markdown_table, validate_mapping
from workspace_paths import (
    candidate_workspace_dirs,
    existing_manifest_path,
    manifest_path,
    resolve_workspace_dir,
)


DEFAULT_MAX_WORKERS = 4
MAX_ALLOWED_WORKERS = 8
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_REVIEW_BATCH_SIZE = 5
DEFAULT_MAX_TOKENS = 15_000
RETRYABLE_STATUSES = {"pending", "retry_pending"}
COMPLETE_STATUSES = {"cached", "validated"}


class PipelineError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def file_signature(path: str) -> dict:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    stat = os.stat(path)
    return {
        "sha256": digest.hexdigest(),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _manifest_path(folder_path: str, workspace_dir: str | None = None) -> str:
    return manifest_path(folder_path, workspace_dir)


def _load_manifest(folder_path: str) -> dict | None:
    path = existing_manifest_path(folder_path)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError("INVALID_MANIFEST", str(exc)) from exc
    if payload.get("version") != 1 or not isinstance(payload.get("entries"), dict):
        raise PipelineError(
            "INVALID_MANIFEST", "Unsupported mapping manifest structure."
        )
    return payload


def _atomic_write_json(path: str, payload: dict) -> None:
    directory = os.path.dirname(path)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise


def _save_manifest(folder_path: str, manifest: dict) -> None:
    manifest["updated_at"] = _utc_timestamp()
    workspace_dir = manifest.get("workspace_dir") or resolve_workspace_dir(folder_path)
    _atomic_write_json(_manifest_path(folder_path, workspace_dir), manifest)


def _validate_settings(
    max_workers: int,
    max_attempts: int,
    max_tokens: int,
    review_batch_size: int,
) -> None:
    if not 1 <= max_workers <= MAX_ALLOWED_WORKERS:
        raise PipelineError(
            "INVALID_INPUT",
            f"max_workers must be between 1 and {MAX_ALLOWED_WORKERS}.",
        )
    if not 1 <= max_attempts <= 5:
        raise PipelineError("INVALID_INPUT", "max_attempts must be between 1 and 5.")
    if max_tokens <= 0 or review_batch_size <= 0:
        raise PipelineError(
            "INVALID_INPUT",
            "max_tokens and review_batch_size must be greater than zero.",
        )


def _validate_questionnaire(path: str) -> None:
    table = parse_markdown_table(path)
    if table.headers != BASE_HEADERS or not table.rows:
        raise PipelineError(
            "INVALID_QUESTIONNAIRE",
            "full-questionnaire.md must contain the exact four-column questionnaire table.",
        )
    if any(width != 4 for width in table.row_widths):
        raise PipelineError(
            "INVALID_QUESTIONNAIRE",
            "Questionnaire rows must contain exactly four columns.",
        )


def _output_signatures_are_current(manifest: dict) -> bool:
    signatures = manifest.get("output_signatures")
    if not isinstance(signatures, dict) or not signatures:
        return False
    try:
        return all(
            os.path.isfile(path) and file_signature(path) == signature
            for path, signature in signatures.items()
        )
    except OSError:
        return False


def prepare_pipeline(
    folder_path: str,
    *,
    max_workers: int = DEFAULT_MAX_WORKERS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    review_batch_size: int = DEFAULT_REVIEW_BATCH_SIZE,
) -> dict:
    """Discover sources, validate cache entries, chunk pending inputs, and persist state."""
    _validate_settings(max_workers, max_attempts, max_tokens, review_batch_size)
    if not os.path.isdir(folder_path):
        raise PipelineError("INVALID_INPUT", f"Folder does not exist: {folder_path}")
    workspace_dir = resolve_workspace_dir(folder_path)
    if not os.path.isdir(workspace_dir):
        raise PipelineError(
            "INVALID_INPUT", f"Mapping directory does not exist: {workspace_dir}"
        )
    questionnaire_path = os.path.join(workspace_dir, "full-questionnaire.md")
    if not os.path.isfile(questionnaire_path):
        raise PipelineError(
            "NO_QUESTIONNAIRE", "full-questionnaire.md not found in the resolved mapping directory."
        )
    _validate_questionnaire(questionnaire_path)

    transcripts = find_transcripts(workspace_dir)
    if not transcripts:
        raise PipelineError(
            "NO_TRANSCRIPT_FILES", "No transcript_<audio_name>.md files found."
        )

    previous = _load_manifest(folder_path)
    previous_entries = previous.get("entries", {}) if previous else {}
    questionnaire_signature = file_signature(questionnaire_path)
    entries: dict[str, dict] = {}

    for transcript_path in transcripts:
        audio_name = extract_transcript_audio_name(transcript_path)
        if not audio_name:
            continue
        mapped_path = os.path.join(workspace_dir, f"mapped-transcript-{audio_name}.md")
        candidate_path = os.path.join(
            workspace_dir, f".mapped-transcript-{audio_name}.candidate.md"
        )
        source_signature = file_signature(transcript_path)
        previous_entry = previous_entries.get(audio_name, {})

        signatures_match = (
            previous_entry.get("source_signature") == source_signature
            and previous_entry.get("questionnaire_signature") == questionnaire_signature
        )
        validation = None
        current_mapped_signature = None
        if os.path.isfile(mapped_path):
            current_mapped_signature = file_signature(mapped_path)
            validation = validate_mapping(
                questionnaire_path,
                mapped_path,
                transcript_path,
            )

        legacy_fresh = False
        if validation and validation.valid and not previous_entry:
            mapped_mtime = os.stat(mapped_path).st_mtime_ns
            legacy_fresh = mapped_mtime >= max(
                source_signature["mtime_ns"],
                questionnaire_signature["mtime_ns"],
            )
        cache_valid = bool(
            validation
            and validation.valid
            and (signatures_match or legacy_fresh)
            and (
                not previous_entry.get("mapped_signature")
                or previous_entry.get("mapped_signature") == current_mapped_signature
            )
        )

        resume_retry = False
        if cache_valid:
            status = "cached"
            input_files = [transcript_path]
            cleanup_chunk_directory(workspace_dir, transcript_path)
            if os.path.exists(candidate_path):
                os.remove(candidate_path)
            attempts = 0
        else:
            status = "pending"
            resume_retry = signatures_match and previous_entry.get("status") in {
                "retry_pending",
                "running",
            }
            attempts = int(previous_entry.get("attempts", 0)) if resume_retry else 0
            chunk_paths = chunk_transcript_file(
                folder_path, transcript_path, max_tokens
            )
            input_files = chunk_paths or [transcript_path]
            if os.path.exists(candidate_path):
                os.remove(candidate_path)

        entries[audio_name] = {
            "audio_name": audio_name,
            "transcript_file": transcript_path,
            "mapped_file": mapped_path,
            "candidate_file": candidate_path,
            "input_files": input_files,
            "chunked": len(input_files) > 1 or input_files[0] != transcript_path,
            "status": status,
            "attempts": attempts,
            "max_attempts": max_attempts,
            "next_attempt_at": (
                float(previous_entry.get("next_attempt_at", 0.0))
                if resume_retry
                else 0.0
            ),
            "last_error": (previous_entry.get("last_error") if resume_retry else None),
            "source_signature": source_signature,
            "questionnaire_signature": questionnaire_signature,
            "validation": (
                validation.to_dict() if validation and validation.valid else None
            ),
            "mapped_signature": current_mapped_signature if cache_valid else None,
        }

    expected_names = set(entries)
    orphaned_outputs = []
    for mapped_path in find_mapped_transcripts(workspace_dir):
        audio_name = extract_audio_name(mapped_path)
        if audio_name and audio_name not in expected_names:
            orphaned_outputs.append(mapped_path)

    source_set = sorted(entries)
    previous_source_set = previous.get("source_set", []) if previous else []
    all_cached = all(entry["status"] == "cached" for entry in entries.values())
    canonical_path = os.path.join(workspace_dir, "mapped-transcript.md")
    canonical_current = bool(
        all_cached
        and os.path.isfile(canonical_path)
        and source_set == previous_source_set
        and previous
        and previous.get("status") == "success"
        and _output_signatures_are_current(previous)
    )

    manifest = {
        "version": 1,
        "created_at": (
            previous.get("created_at", _utc_timestamp())
            if previous
            else _utc_timestamp()
        ),
        "updated_at": _utc_timestamp(),
        "folder_path": os.path.abspath(folder_path),
        "workspace_dir": workspace_dir,
        "questionnaire_file": questionnaire_path,
        "questionnaire_signature": questionnaire_signature,
        "source_set": source_set,
        "settings": {
            "max_workers": max_workers,
            "max_attempts": max_attempts,
            "max_tokens": max_tokens,
            "review_batch_size": review_batch_size,
            "retry_backoff_seconds": [1, 2, 4, 8],
        },
        "status": "success" if canonical_current else "mapping",
        "canonical_current": canonical_current,
        "entries": entries,
        "orphaned_outputs": sorted(orphaned_outputs),
        "outputs": (
            previous.get("outputs", {}) if canonical_current and previous else {}
        ),
        "output_signatures": (
            previous.get("output_signatures", {})
            if canonical_current and previous
            else {}
        ),
    }
    _save_manifest(folder_path, manifest)
    return _public_status(manifest)


def _entry_task(entry: dict, questionnaire_file: str) -> dict:
    return {
        "audio_name": entry["audio_name"],
        "questionnaire_file": questionnaire_file,
        "transcript_file": entry["transcript_file"],
        "input_files": entry["input_files"],
        "chunked": entry["chunked"],
        "candidate_file": entry["candidate_file"],
        "attempt": entry["attempts"],
        "max_attempts": entry["max_attempts"],
        "last_error": entry.get("last_error"),
    }


def next_batch(folder_path: str, *, now: float | None = None) -> dict:
    """Claim at most max_workers ready tasks and increment attempt counters."""
    manifest = _load_manifest(folder_path)
    if not manifest:
        raise PipelineError("NO_MANIFEST", "Run prepare before requesting a batch.")
    current_time = time.time() if now is None else now
    max_workers = int(manifest["settings"]["max_workers"])
    ready: list[dict] = []
    wait_candidates: list[float] = []
    running_count = sum(
        entry["status"] == "running" for entry in manifest["entries"].values()
    )
    if running_count:
        return {
            "status": "busy",
            "tasks": [],
            "max_workers": max_workers,
            "running": running_count,
            "wait_seconds": 0.0,
        }

    for audio_name in sorted(manifest["entries"]):
        entry = manifest["entries"][audio_name]
        if entry["status"] not in RETRYABLE_STATUSES:
            continue
        if entry["attempts"] >= entry["max_attempts"]:
            entry["status"] = "failed"
            entry["last_error"] = {
                "code": "RETRY_EXHAUSTED",
                "message": "Maximum attempts reached.",
            }
            cleanup_chunk_directory(
                os.path.dirname(entry["transcript_file"]), entry["transcript_file"]
            )
            continue
        if float(entry.get("next_attempt_at", 0.0)) > current_time:
            wait_candidates.append(float(entry["next_attempt_at"]) - current_time)
            continue
        entry["status"] = "running"
        entry["attempts"] += 1
        ready.append(_entry_task(entry, manifest["questionnaire_file"]))
        if len(ready) == max_workers:
            break

    _save_manifest(folder_path, manifest)
    unfinished = [
        entry
        for entry in manifest["entries"].values()
        if entry["status"] not in COMPLETE_STATUSES | {"failed"}
    ]
    return {
        "status": "ready" if ready else ("waiting" if unfinished else "idle"),
        "tasks": ready,
        "max_workers": max_workers,
        "wait_seconds": (
            max(0.0, min(wait_candidates)) if wait_candidates and not ready else 0.0
        ),
    }


def _retry_delay(manifest: dict, attempts: int) -> int:
    schedule = manifest["settings"].get("retry_backoff_seconds", [1, 2, 4])
    return int(schedule[min(max(attempts - 1, 0), len(schedule) - 1)])


def _record_error(
    folder_path: str,
    manifest: dict,
    entry: dict,
    *,
    code: str,
    message: str,
    retryable: bool,
    now: float | None = None,
) -> dict:
    current_time = time.time() if now is None else now
    exhausted = entry["attempts"] >= entry["max_attempts"]
    entry["last_error"] = {"code": code, "message": message}
    if retryable and not exhausted:
        delay = _retry_delay(manifest, entry["attempts"])
        entry["status"] = "retry_pending"
        entry["next_attempt_at"] = current_time + delay
    else:
        delay = 0
        entry["status"] = "failed"
        entry["next_attempt_at"] = 0.0
        cleanup_chunk_directory(
            os.path.dirname(entry["transcript_file"]), entry["transcript_file"]
        )
    candidate = entry["candidate_file"]
    if os.path.exists(candidate):
        os.remove(candidate)
    _save_manifest(folder_path, manifest)
    return {
        "status": entry["status"],
        "audio_name": entry["audio_name"],
        "attempts": entry["attempts"],
        "max_attempts": entry["max_attempts"],
        "retry_after_seconds": delay,
        "error": entry["last_error"],
    }


def record_success(folder_path: str, audio_name: str) -> dict:
    """Validate a task candidate and atomically promote it on success."""
    manifest = _load_manifest(folder_path)
    if not manifest or audio_name not in manifest["entries"]:
        raise PipelineError("UNKNOWN_TASK", f"Unknown audio name: {audio_name}")
    entry = manifest["entries"][audio_name]
    if entry["status"] != "running":
        raise PipelineError("INVALID_STATE", f"Task {audio_name} is not running.")
    candidate = entry["candidate_file"]
    current_source_signature = file_signature(entry["transcript_file"])
    current_questionnaire_signature = file_signature(manifest["questionnaire_file"])
    if (
        current_source_signature != entry["source_signature"]
        or current_questionnaire_signature != entry["questionnaire_signature"]
    ):
        return _record_error(
            folder_path,
            manifest,
            entry,
            code="SOURCE_CHANGED_DURING_MAPPING",
            message="Transcript or questionnaire changed after this task was prepared.",
            retryable=False,
        )
    result = validate_mapping(
        manifest["questionnaire_file"],
        candidate,
        entry["transcript_file"],
    )
    if not result.valid:
        diagnostic = "; ".join(
            f"{issue.code}: {issue.message}" for issue in result.issues
        )
        return _record_error(
            folder_path,
            manifest,
            entry,
            code="VALIDATION_FAILED",
            message=diagnostic,
            retryable=True,
        )

    os.replace(candidate, entry["mapped_file"])
    entry["status"] = "validated"
    entry["next_attempt_at"] = 0.0
    entry["last_error"] = None
    entry["validation"] = result.to_dict()
    entry["source_signature"] = file_signature(entry["transcript_file"])
    entry["questionnaire_signature"] = file_signature(manifest["questionnaire_file"])
    entry["mapped_signature"] = file_signature(entry["mapped_file"])
    cleanup_chunk_directory(
        os.path.dirname(entry["transcript_file"]), entry["transcript_file"]
    )
    _save_manifest(folder_path, manifest)
    return {
        "status": "validated",
        "audio_name": audio_name,
        "mapped_file": entry["mapped_file"],
        "validation": entry["validation"],
    }


def record_failure(
    folder_path: str,
    audio_name: str,
    *,
    code: str,
    message: str,
    transient: bool,
) -> dict:
    manifest = _load_manifest(folder_path)
    if not manifest or audio_name not in manifest["entries"]:
        raise PipelineError("UNKNOWN_TASK", f"Unknown audio name: {audio_name}")
    entry = manifest["entries"][audio_name]
    if entry["status"] != "running":
        raise PipelineError("INVALID_STATE", f"Task {audio_name} is not running.")
    return _record_error(
        folder_path,
        manifest,
        entry,
        code=code,
        message=message,
        retryable=transient,
    )


def cleanup_pipeline(folder_path: str) -> dict:
    """Remove only controller-owned candidates and chunk directories."""
    removed: list[str] = []
    for workspace_dir in candidate_workspace_dirs(folder_path):
        for path in Path(workspace_dir).glob(".chunks_transcript_*"):
            if path.is_dir():
                shutil.rmtree(path)
                removed.append(str(path))
        for path in Path(workspace_dir).glob(".mapped-transcript-*.candidate.md"):
            if path.is_file():
                path.unlink()
                removed.append(str(path))
    return {"status": "success", "removed": sorted(removed)}


def finalize_pipeline(folder_path: str, *, allow_partial: bool = False) -> dict:
    manifest = _load_manifest(folder_path)
    if not manifest:
        raise PipelineError("NO_MANIFEST", "Run prepare before finalize.")
    incomplete = [
        {
            "audio_name": name,
            "status": entry["status"],
            "error": entry.get("last_error"),
        }
        for name, entry in sorted(manifest["entries"].items())
        if entry["status"] not in COMPLETE_STATUSES
    ]
    try:
        if incomplete and not allow_partial:
            manifest["status"] = "partial"
            manifest["canonical_current"] = False
            manifest["failures"] = incomplete
            _save_manifest(folder_path, manifest)
            return {
                "status": "partial",
                "code": "PARTIAL_MAPPING",
                "failures": incomplete,
                "canonical_file_updated": False,
            }

        result = merge_mapping_outputs(
            folder_path,
            allow_partial=allow_partial,
            review_batch_size=int(manifest["settings"]["review_batch_size"]),
            include_audio_names=(
                {
                    name
                    for name, entry in manifest["entries"].items()
                    if entry["status"] in COMPLETE_STATUSES
                }
                if allow_partial
                else None
            ),
        )
        manifest["status"] = result["status"]
        manifest["canonical_current"] = result["status"] == "success"
        manifest["outputs"] = result
        output_paths = [
            result["combined_file"],
            result["review_manifest"],
            *result["review_files"],
        ]
        manifest["output_signatures"] = {
            path: file_signature(path) for path in output_paths
        }
        manifest["failures"] = result["failures"]
        _save_manifest(folder_path, manifest)
        return result
    except PartialMappingError as exc:
        manifest["status"] = "partial"
        manifest["canonical_current"] = False
        manifest["failures"] = exc.failures
        _save_manifest(folder_path, manifest)
        return {
            "status": "partial",
            "code": "PARTIAL_MAPPING",
            "failures": exc.failures,
            "canonical_file_updated": False,
        }
    finally:
        cleanup_pipeline(folder_path)


def _public_status(manifest: dict) -> dict:
    counts: dict[str, int] = {}
    for entry in manifest["entries"].values():
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    return {
        "status": manifest["status"],
        "canonical_current": manifest["canonical_current"],
        "source_set": manifest["source_set"],
        "counts": counts,
        "orphaned_outputs": manifest.get("orphaned_outputs", []),
        "manifest_file": _manifest_path(
            manifest["folder_path"], manifest.get("workspace_dir")
        ),
    }


def pipeline_status(folder_path: str) -> dict:
    manifest = _load_manifest(folder_path)
    if not manifest:
        raise PipelineError("NO_MANIFEST", "No mapping manifest exists.")
    payload = _public_status(manifest)
    payload["entries"] = {
        name: {
            "status": entry["status"],
            "attempts": entry["attempts"],
            "max_attempts": entry["max_attempts"],
            "last_error": entry.get("last_error"),
        }
        for name, entry in sorted(manifest["entries"].items())
    }
    payload["outputs"] = manifest.get("outputs", {})
    return payload


def _print(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("folder_path")
    prepare_parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    prepare_parser.add_argument(
        "--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS
    )
    prepare_parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    prepare_parser.add_argument(
        "--review-batch-size", type=int, default=DEFAULT_REVIEW_BATCH_SIZE
    )

    batch_parser = subparsers.add_parser("next-batch")
    batch_parser.add_argument("folder_path")

    success_parser = subparsers.add_parser("record-success")
    success_parser.add_argument("folder_path")
    success_parser.add_argument("audio_name")

    failure_parser = subparsers.add_parser("record-failure")
    failure_parser.add_argument("folder_path")
    failure_parser.add_argument("audio_name")
    failure_parser.add_argument("--code", required=True)
    failure_parser.add_argument("--message", required=True)
    failure_parser.add_argument("--transient", action="store_true")

    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("folder_path")
    finalize_parser.add_argument("--allow-partial", action="store_true")

    cleanup_parser = subparsers.add_parser("cleanup")
    cleanup_parser.add_argument("folder_path")

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("folder_path")

    args = parser.parse_args()
    try:
        if args.command == "prepare":
            payload = prepare_pipeline(
                args.folder_path,
                max_workers=args.max_workers,
                max_attempts=args.max_attempts,
                max_tokens=args.max_tokens,
                review_batch_size=args.review_batch_size,
            )
        elif args.command == "next-batch":
            payload = next_batch(args.folder_path)
        elif args.command == "record-success":
            payload = record_success(args.folder_path, args.audio_name)
        elif args.command == "record-failure":
            payload = record_failure(
                args.folder_path,
                args.audio_name,
                code=args.code,
                message=args.message,
                transient=args.transient,
            )
        elif args.command == "finalize":
            payload = finalize_pipeline(
                args.folder_path, allow_partial=args.allow_partial
            )
        elif args.command == "cleanup":
            payload = cleanup_pipeline(args.folder_path)
        else:
            payload = pipeline_status(args.folder_path)
        _print(payload)
        if payload.get("status") == "partial":
            raise SystemExit(2)
    except PipelineError as exc:
        _print({"status": "error", "code": exc.code, "message": str(exc)})
        raise SystemExit(1)
    except PermissionError as exc:
        _print({"status": "error", "code": "PERMISSION_ERROR", "message": str(exc)})
        raise SystemExit(1)
    except UnicodeError as exc:
        _print({"status": "error", "code": "ENCODING_ERROR", "message": str(exc)})
        raise SystemExit(1)
    except OSError as exc:
        _print({"status": "error", "code": "WRITE_FAILURE", "message": str(exc)})
        raise SystemExit(1)


if __name__ == "__main__":
    main()
