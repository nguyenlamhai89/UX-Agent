#!/usr/bin/env python3
"""Validate and merge mapped transcripts into canonical and review outputs."""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import tempfile
from dataclasses import dataclass

from validate_mapping import (
    BASE_HEADERS,
    ValidationResult,
    parse_markdown_table as parse_table,
)
from validate_mapping import validate_mapping
from workspace_paths import resolve_workspace_dir


REVIEW_FILE_PATTERN = re.compile(r"mapped-transcript-(?:partial-)?review-\d+\.md$")


class PartialMappingError(ValueError):
    def __init__(self, failures: list[dict]):
        self.failures = failures
        super().__init__(
            f"Mapping is incomplete or invalid for {len(failures)} transcript(s)."
        )


@dataclass
class IntervieweeColumn:
    audio_name: str
    alias: str
    transcript_path: str
    mapped_path: str
    responses: list[str]
    validation: ValidationResult


def parse_markdown_table(filepath: str) -> tuple[list[str], list[list[str]]]:
    """Backward-compatible wrapper used by existing callers and tests."""
    table = parse_table(filepath)
    return table.headers, table.rows


def find_questionnaire(interview_dir: str) -> str | None:
    path = os.path.join(interview_dir, "full-questionnaire.md")
    return path if os.path.isfile(path) else None


def find_transcripts(interview_dir: str) -> list[str]:
    return sorted(glob.glob(os.path.join(interview_dir, "transcript_*.md")))


def find_mapped_transcripts(interview_dir: str) -> list[str]:
    """Find only per-interviewee mapped files, excluding generated views."""
    candidates = glob.glob(os.path.join(interview_dir, "mapped-transcript-*.md"))
    results: list[str] = []
    for path in candidates:
        basename = os.path.basename(path)
        if REVIEW_FILE_PATTERN.fullmatch(basename):
            continue
        if basename.endswith(".partial.md") or basename.endswith(".candidate.md"):
            continue
        results.append(path)
    return sorted(results)


def extract_audio_name(filepath: str) -> str | None:
    match = re.fullmatch(r"mapped-transcript-(.+)\.md", os.path.basename(filepath))
    if not match or match.group(1).startswith("review-"):
        return None
    return match.group(1)


def extract_transcript_audio_name(filepath: str) -> str | None:
    match = re.fullmatch(r"transcript_(.+)\.md", os.path.basename(filepath))
    return match.group(1) if match else None


def _atomic_write(path: str, content: str) -> None:
    directory = os.path.dirname(path)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise


def _render_table(base_rows: list[list[str]], columns: list[IntervieweeColumn]) -> str:
    headers = BASE_HEADERS + [column.alias for column in columns]
    lines = [
        "# Mapped Transcript",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row_index, base_row in enumerate(base_rows):
        row = list(base_row)
        row.extend(column.responses[row_index] for column in columns)
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return "\n".join(lines)


def _format_timestamp_ranges(missing: list[str], source: list[str]) -> str:
    if not missing:
        return "None"
    missing_set = set(missing)
    groups: list[list[str]] = []
    current: list[str] = []
    for timestamp in source:
        if timestamp in missing_set:
            current.append(timestamp)
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return ", ".join(
        group[0] if len(group) == 1 else f"{group[0]}–{group[-1]}" for group in groups
    )


def _render_review_manifest(columns: list[IntervieweeColumn], status: str) -> str:
    lines = [
        "# Mapping Review Manifest",
        "",
        f"> Status: **{status}** | Interviewees: **{len(columns)}**",
        "",
        "| Interviewee | Rows | Answered | N/A | Coverage | Unmapped timestamps | Overlapping timestamps |",
        "|---|---:|---:|---:|---|---|---|",
    ]
    for column in columns:
        result = column.validation
        coverage = f"{result.coverage_start} to {result.coverage_end}"
        unmapped = _format_timestamp_ranges(
            result.unmapped_timestamps,
            result.transcript_timestamps,
        )
        overlapping = ", ".join(result.overlapping_timestamps) or "None"
        lines.append(
            "| "
            + " | ".join(
                [
                    column.alias,
                    str(result.total_rows),
                    str(result.answered),
                    str(result.not_applicable),
                    coverage,
                    unmapped,
                    overlapping,
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def _collect_columns(
    folder_path: str,
    *,
    allow_partial: bool,
    include_audio_names: set[str] | None = None,
) -> tuple[list[list[str]], list[IntervieweeColumn], list[dict]]:
    workspace_dir = resolve_workspace_dir(folder_path)
    questionnaire_path = find_questionnaire(workspace_dir)
    if not questionnaire_path:
        raise FileNotFoundError(
            "full-questionnaire.md not found in the resolved mapping directory."
        )
    questionnaire = parse_table(questionnaire_path)
    if questionnaire.headers != BASE_HEADERS or not questionnaire.rows:
        raise ValueError("full-questionnaire.md has an invalid table structure.")

    transcripts = find_transcripts(workspace_dir)
    if not transcripts:
        raise ValueError(
            "No transcript_<audio_name>.md files found in the resolved mapping directory."
        )

    columns: list[IntervieweeColumn] = []
    failures: list[dict] = []
    aliases: set[str] = set()

    for transcript_path in transcripts:
        audio_name = extract_transcript_audio_name(transcript_path)
        if not audio_name:
            continue
        if include_audio_names is not None and audio_name not in include_audio_names:
            failures.append(
                {"audio_name": audio_name, "code": "INCOMPLETE_MAPPING", "issues": []}
            )
            continue
        mapped_path = os.path.join(workspace_dir, f"mapped-transcript-{audio_name}.md")
        if not os.path.isfile(mapped_path):
            failures.append(
                {"audio_name": audio_name, "code": "MISSING_MAPPED_FILE", "issues": []}
            )
            continue

        validation = validate_mapping(
            questionnaire_path,
            mapped_path,
            transcript_path,
        )
        if not validation.valid:
            failures.append(
                {
                    "audio_name": audio_name,
                    "code": "INVALID_MAPPED_FILE",
                    "issues": [issue.code for issue in validation.issues],
                }
            )
            continue
        alias = validation.alias or audio_name
        alias_key = " ".join(alias.lower().split())
        if alias_key in aliases:
            failures.append(
                {"audio_name": audio_name, "code": "DUPLICATE_ALIAS", "issues": [alias]}
            )
            continue
        aliases.add(alias_key)
        mapped = parse_table(mapped_path)
        columns.append(
            IntervieweeColumn(
                audio_name=audio_name,
                alias=alias,
                transcript_path=transcript_path,
                mapped_path=mapped_path,
                responses=[row[4] for row in mapped.rows],
                validation=validation,
            )
        )

    if failures and not allow_partial:
        raise PartialMappingError(failures)
    if not columns:
        raise PartialMappingError(failures or [{"code": "NO_VALID_MAPPED_FILES"}])
    return questionnaire.rows, columns, failures


def merge_mapping_outputs(
    folder_path: str,
    *,
    allow_partial: bool = False,
    review_batch_size: int = 5,
    include_audio_names: set[str] | None = None,
) -> dict:
    """Validate all expected users and generate canonical or explicit partial outputs."""
    if review_batch_size <= 0:
        raise ValueError("review_batch_size must be greater than zero")
    workspace_dir = resolve_workspace_dir(folder_path)
    base_rows, columns, failures = _collect_columns(
        folder_path,
        allow_partial=allow_partial,
        include_audio_names=include_audio_names,
    )
    status = "partial" if failures else "success"
    combined_name = (
        "mapped-transcript.partial.md" if failures else "mapped-transcript.md"
    )
    combined_path = os.path.join(workspace_dir, combined_name)
    review_prefix = (
        "mapped-transcript-partial-review" if failures else "mapped-transcript-review"
    )

    review_paths: list[str] = []
    for offset in range(0, len(columns), review_batch_size):
        batch = columns[offset : offset + review_batch_size]
        review_index = offset // review_batch_size + 1
        review_path = os.path.join(
            workspace_dir,
            f"{review_prefix}-{review_index:02d}.md",
        )
        _atomic_write(review_path, _render_table(base_rows, batch))
        review_paths.append(review_path)

    for existing in glob.glob(os.path.join(workspace_dir, f"{review_prefix}-*.md")):
        if existing not in review_paths and REVIEW_FILE_PATTERN.fullmatch(
            os.path.basename(existing)
        ):
            os.remove(existing)

    review_manifest_name = (
        "mapping-review-manifest.partial.md"
        if failures
        else "mapping-review-manifest.md"
    )
    review_manifest_path = os.path.join(workspace_dir, review_manifest_name)
    _atomic_write(review_manifest_path, _render_review_manifest(columns, status))
    _atomic_write(combined_path, _render_table(base_rows, columns))

    return {
        "status": status,
        "combined_file": combined_path,
        "review_files": review_paths,
        "review_manifest": review_manifest_path,
        "total_expected": len(find_transcripts(workspace_dir)),
        "total_mapped": len(columns),
        "failures": failures,
    }


def merge_mapped_transcripts(folder_path: str) -> str:
    """Backward-compatible strict merge returning the canonical path."""
    result = merge_mapping_outputs(folder_path)
    return result["combined_file"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder_path")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--review-batch-size", type=int, default=5)
    args = parser.parse_args()

    if not os.path.isdir(args.folder_path):
        print(json.dumps({"status": "error", "code": "INVALID_INPUT"}))
        raise SystemExit(1)
    try:
        result = merge_mapping_outputs(
            args.folder_path,
            allow_partial=args.allow_partial,
            review_batch_size=args.review_batch_size,
        )
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0 if result["status"] == "success" else 2)
    except PartialMappingError as exc:
        print(
            json.dumps(
                {
                    "status": "partial",
                    "code": "PARTIAL_MAPPING",
                    "failures": exc.failures,
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(2)
    except FileNotFoundError as exc:
        print(
            json.dumps(
                {"status": "error", "code": "NO_QUESTIONNAIRE", "message": str(exc)}
            )
        )
        raise SystemExit(1)
    except PermissionError as exc:
        print(
            json.dumps(
                {"status": "error", "code": "PERMISSION_ERROR", "message": str(exc)}
            )
        )
        raise SystemExit(1)
    except UnicodeError as exc:
        print(
            json.dumps(
                {"status": "error", "code": "ENCODING_ERROR", "message": str(exc)}
            )
        )
        raise SystemExit(1)
    except (OSError, ValueError) as exc:
        print(
            json.dumps({"status": "error", "code": "MERGE_ERROR", "message": str(exc)})
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
