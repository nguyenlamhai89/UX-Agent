#!/usr/bin/env python3
"""Validate per-interviewee mapped transcript files.

Validation is intentionally strict because the combined transcript is consumed by
downstream insight generation. A mapped file must preserve the questionnaire's
base columns exactly, contain one non-empty response per row, follow the response
formatting contract, and include an internally consistent Mapping Summary.

Usage:
    python3 validate_mapping.py QUESTIONNAIRE MAPPED [--transcript TRANSCRIPT] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Iterable


BASE_HEADERS = ["#", "Theme", "Question", "Observed Variable"]
TIMESTAMP_PATTERN = re.compile(r"\[(\d{1,3}):([0-5]\d)\]")
TRANSCRIPT_HEADING_PATTERN = re.compile(
    r"^\s*\*\*(\[\d{1,3}:[0-5]\d\])(?:\s+\[[^\]]+\])?\*\*"
    r"\s*(?:<br\s*/?>)?\s*$",
    re.IGNORECASE,
)
TRANSCRIPT_INLINE_PATTERN = re.compile(
    r"^\s*(\[\d{1,3}:[0-5]\d\])\s*(.*?)\s*$"
)
INLINE_SPEAKER_PATTERN = re.compile(r"^[^:\n]{1,80}:\s?(.*)$")
HIGHLIGHT_OPEN = '<mark style="background-color: yellow;">'
SUMMARY_PATTERN = re.compile(
    r"^> \*\*Mapping Summary\*\*: "
    r"Total rows: (\d+) \| Answered: (\d+) \| N/A: (\d+) \| "
    r"Transcript coverage: (\[\d{1,3}:[0-5]\d\]) to "
    r"(\[\d{1,3}:[0-5]\d\])$"
)


@dataclass
class ParsedTable:
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    row_widths: list[int] = field(default_factory=list)


@dataclass
class ValidationIssue:
    code: str
    message: str


@dataclass(frozen=True)
class TranscriptTurn:
    timestamp: str
    content: str


@dataclass
class ValidationResult:
    valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    alias: str | None = None
    total_rows: int = 0
    answered: int = 0
    not_applicable: int = 0
    coverage_start: str | None = None
    coverage_end: str | None = None
    transcript_timestamps: list[str] = field(default_factory=list)
    mapped_timestamps: list[str] = field(default_factory=list)
    unmapped_timestamps: list[str] = field(default_factory=list)
    overlapping_timestamps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["issues"] = [asdict(issue) for issue in self.issues]
        return payload


def parse_markdown_table(filepath: str) -> ParsedTable:
    """Read the first Markdown table without hiding malformed row widths."""
    table = ParsedTable()
    in_table = False
    separator_seen = False
    with open(filepath, "r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped.startswith("|"):
                if in_table and separator_seen:
                    break
                continue

            in_table = True
            raw = stripped[1:-1] if stripped.endswith("|") else stripped[1:]
            cells = [cell.strip() for cell in raw.split("|")]

            if not table.headers:
                table.headers = cells
                continue

            is_separator = all(
                cell.replace("-", "").replace(":", "").strip() == "" for cell in cells
            )
            if is_separator and not separator_seen:
                separator_seen = True
                continue

            table.rows.append(cells)
            table.row_widths.append(len(cells))

    return table


def extract_timestamps(text: str) -> list[str]:
    return [match.group(0) for match in TIMESTAMP_PATTERN.finditer(text)]


def timestamp_to_seconds(timestamp: str) -> int:
    match = TIMESTAMP_PATTERN.fullmatch(timestamp)
    if not match:
        raise ValueError(f"Invalid timestamp: {timestamp}")
    return int(match.group(1)) * 60 + int(match.group(2))


def _sorted_unique_timestamps(values: Iterable[str]) -> list[str]:
    return sorted(set(values), key=timestamp_to_seconds)


def _find_summary(filepath: str) -> re.Match[str] | None:
    with open(filepath, "r", encoding="utf-8") as handle:
        summaries = [
            SUMMARY_PATTERN.fullmatch(line.strip())
            for line in handle
            if line.strip().startswith("> **Mapping Summary**:")
        ]
    matches = [match for match in summaries if match is not None]
    return matches[0] if len(matches) == 1 else None


def _add_issue(issues: list[ValidationIssue], code: str, message: str) -> None:
    issues.append(ValidationIssue(code=code, message=message))


def _trim_blank_lines(lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def parse_transcript_turns(text: str) -> list[TranscriptTurn]:
    """Extract complete timestamped turns from supported transcript formats."""
    turns: list[TranscriptTurn] = []
    current_timestamp: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_timestamp, current_lines
        if current_timestamp is None:
            return
        content = "\n".join(_trim_blank_lines(current_lines))
        turns.append(TranscriptTurn(timestamp=current_timestamp, content=content))
        current_timestamp = None
        current_lines = []

    for line in text.splitlines():
        heading_match = TRANSCRIPT_HEADING_PATTERN.fullmatch(line)
        if heading_match:
            flush()
            current_timestamp = heading_match.group(1)
            continue

        inline_match = TRANSCRIPT_INLINE_PATTERN.fullmatch(line)
        if inline_match:
            flush()
            current_timestamp = inline_match.group(1)
            inline_content = inline_match.group(2)
            speaker_match = INLINE_SPEAKER_PATTERN.fullmatch(inline_content)
            current_lines = [
                speaker_match.group(1) if speaker_match else inline_content
            ]
            continue

        if current_timestamp is not None:
            current_lines.append(line)

    flush()
    return turns


def _decode_mapped_fragment(fragment: str) -> str:
    """Remove only output-format wrappers before exact source comparison."""
    value = re.sub(r"(?:\s*<br\s*/?>\s*)+$", "", fragment, flags=re.IGNORECASE)
    value = re.sub(r"^(?:\s*<br\s*/?>\s*)+", "", value, flags=re.IGNORECASE)
    value = value.replace(f"**{HIGHLIGHT_OPEN}", HIGHLIGHT_OPEN)
    value = value.replace("</mark>**", "</mark>")
    value = value.replace(HIGHLIGHT_OPEN, "").replace("</mark>", "")
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    return value.replace("&#124;", "|").strip()


def extract_mapped_fragments(response: str) -> list[TranscriptTurn]:
    """Split a response cell into complete timestamped source fragments."""
    matches = list(TIMESTAMP_PATTERN.finditer(response))
    fragments: list[TranscriptTurn] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(response)
        fragments.append(
            TranscriptTurn(
                timestamp=match.group(0),
                content=_decode_mapped_fragment(response[match.end() : end]),
            )
        )
    return fragments


def _validate_verbatim_response(
    issues: list[ValidationIssue],
    row_number: int,
    response: str,
    source_turns_by_timestamp: dict[str, set[str]],
) -> None:
    timestamp_matches = list(TIMESTAMP_PATTERN.finditer(response))
    if timestamp_matches and _decode_mapped_fragment(
        response[: timestamp_matches[0].start()]
    ):
        _add_issue(
            issues,
            "NON_VERBATIM_RESPONSE",
            f"Row {row_number} contains text outside a timestamped source turn.",
        )

    for fragment in extract_mapped_fragments(response):
        source_contents = source_turns_by_timestamp.get(fragment.timestamp)
        if source_contents is None:
            _add_issue(
                issues,
                "SOURCE_TIMESTAMP_NOT_FOUND",
                f"Row {row_number} uses {fragment.timestamp}, which is absent from the source transcript.",
            )
            continue
        if not fragment.content or fragment.content not in source_contents:
            _add_issue(
                issues,
                "NON_VERBATIM_RESPONSE",
                f"Row {row_number} at {fragment.timestamp} must copy one complete source turn "
                "exactly, including punctuation and line content; truncation and paraphrasing "
                "are not allowed.",
            )


def validate_mapping(
    questionnaire_path: str,
    mapped_file_path: str,
    transcript_path: str | None = None,
    *,
    require_highlight: bool = True,
) -> ValidationResult:
    """Validate structure, source fidelity, summary, and coverage."""
    issues: list[ValidationIssue] = []

    for label, path in (
        ("questionnaire", questionnaire_path),
        ("mapped file", mapped_file_path),
    ):
        if not os.path.isfile(path):
            _add_issue(issues, "READ_FAILURE", f"Missing {label}: {path}")

    if transcript_path and not os.path.isfile(transcript_path):
        _add_issue(issues, "READ_FAILURE", f"Missing transcript: {transcript_path}")

    if issues:
        return ValidationResult(valid=False, issues=issues)

    try:
        questionnaire = parse_markdown_table(questionnaire_path)
        mapped = parse_markdown_table(mapped_file_path)
    except UnicodeDecodeError as exc:
        return ValidationResult(
            valid=False,
            issues=[ValidationIssue("ENCODING_ERROR", str(exc))],
        )
    except PermissionError as exc:
        return ValidationResult(
            valid=False,
            issues=[ValidationIssue("PERMISSION_ERROR", str(exc))],
        )
    except OSError as exc:
        return ValidationResult(
            valid=False,
            issues=[ValidationIssue("READ_FAILURE", str(exc))],
        )

    if questionnaire.headers != BASE_HEADERS:
        _add_issue(
            issues,
            "INVALID_QUESTIONNAIRE_HEADER",
            f"Expected questionnaire header {BASE_HEADERS}, got {questionnaire.headers}.",
        )
    if not questionnaire.rows:
        _add_issue(issues, "EMPTY_QUESTIONNAIRE", "Questionnaire contains no rows.")
    if any(width != 4 for width in questionnaire.row_widths):
        _add_issue(
            issues,
            "MALFORMED_QUESTIONNAIRE_ROW",
            "Every questionnaire row must contain exactly four columns.",
        )

    duplicate_base_rows = [
        row
        for row, count in Counter(tuple(row) for row in questionnaire.rows).items()
        if count > 1
    ]
    if duplicate_base_rows:
        _add_issue(
            issues,
            "DUPLICATE_QUESTIONNAIRE_ROW",
            f"Duplicate questionnaire row keys: {duplicate_base_rows}.",
        )

    alias = mapped.headers[4].strip() if len(mapped.headers) == 5 else None
    if len(mapped.headers) != 5 or mapped.headers[:4] != BASE_HEADERS or not alias:
        _add_issue(
            issues,
            "INVALID_MAPPED_HEADER",
            "Mapped header must contain the four exact base columns and one non-empty alias.",
        )
    if any(width != 5 for width in mapped.row_widths):
        _add_issue(
            issues,
            "MALFORMED_MAPPED_ROW",
            "Every mapped row must contain exactly five columns; encode response pipes as &#124;.",
        )
    if len(mapped.rows) != len(questionnaire.rows):
        _add_issue(
            issues,
            "ROW_COUNT_MISMATCH",
            f"Expected {len(questionnaire.rows)} rows, got {len(mapped.rows)}.",
        )

    source_turns_by_timestamp: dict[str, set[str]] = {}
    if transcript_path:
        try:
            with open(transcript_path, "r", encoding="utf-8") as handle:
                transcript_text = handle.read()
            for turn in parse_transcript_turns(transcript_text):
                source_turns_by_timestamp.setdefault(turn.timestamp, set()).add(
                    turn.content
                )
        except UnicodeDecodeError as exc:
            _add_issue(issues, "ENCODING_ERROR", str(exc))
        except PermissionError as exc:
            _add_issue(issues, "PERMISSION_ERROR", str(exc))
        except OSError as exc:
            _add_issue(issues, "READ_FAILURE", str(exc))

    mapped_timestamps: list[str] = []
    answered = 0
    not_applicable = 0

    for index, base_row in enumerate(questionnaire.rows):
        if index >= len(mapped.rows):
            break
        mapped_row = mapped.rows[index]
        if len(base_row) != 4 or len(mapped_row) != 5:
            continue
        if mapped_row[:4] != base_row:
            _add_issue(
                issues,
                "ROW_IDENTITY_MISMATCH",
                f"Row {index + 1} does not exactly match the questionnaire row key and order.",
            )

        response = mapped_row[4].strip()
        if not response:
            _add_issue(
                issues,
                "EMPTY_RESPONSE",
                f"Row {index + 1} has an empty response; use N/A when unanswered.",
            )
            continue
        if response == "N/A":
            not_applicable += 1
            continue

        answered += 1
        response_timestamps = extract_timestamps(response)
        mapped_timestamps.extend(response_timestamps)
        if not response_timestamps:
            _add_issue(
                issues,
                "MISSING_RESPONSE_TIMESTAMP",
                f"Row {index + 1} is answered but contains no timestamp.",
            )
        elif transcript_path:
            _validate_verbatim_response(
                issues,
                index + 1,
                response,
                source_turns_by_timestamp,
            )
        if (
            require_highlight
            and '<mark style="background-color: yellow;">' not in response
        ):
            _add_issue(
                issues,
                "MISSING_CORE_HIGHLIGHT",
                f"Row {index + 1} is answered but has no yellow core-response highlight.",
            )

    summary = _find_summary(mapped_file_path)
    coverage_start = coverage_end = None
    if summary is None:
        _add_issue(
            issues,
            "INVALID_MAPPING_SUMMARY",
            "Exactly one Mapping Summary with the documented format is required.",
        )
    else:
        summary_total, summary_answered, summary_na = map(int, summary.group(1, 2, 3))
        coverage_start, coverage_end = summary.group(4, 5)
        if (summary_total, summary_answered, summary_na) != (
            len(mapped.rows),
            answered,
            not_applicable,
        ):
            _add_issue(
                issues,
                "SUMMARY_COUNT_MISMATCH",
                "Mapping Summary totals do not match the mapped table.",
            )

    transcript_timestamps: list[str] = []
    if transcript_path:
        transcript_timestamps = list(source_turns_by_timestamp)

        unique_source = _sorted_unique_timestamps(transcript_timestamps)
        if not unique_source:
            _add_issue(
                issues,
                "NO_TRANSCRIPT_TIMESTAMPS",
                "The source transcript contains no timestamps for coverage validation.",
            )
        if unique_source and coverage_start and coverage_end:
            expected_coverage = (unique_source[0], unique_source[-1])
            if (coverage_start, coverage_end) != expected_coverage:
                _add_issue(
                    issues,
                    "COVERAGE_MISMATCH",
                    f"Expected coverage {expected_coverage[0]} to {expected_coverage[1]}, "
                    f"got {coverage_start} to {coverage_end}.",
                )

    mapped_counts = Counter(mapped_timestamps)
    unique_source = _sorted_unique_timestamps(transcript_timestamps)
    unique_mapped = _sorted_unique_timestamps(mapped_timestamps)
    unmapped = [stamp for stamp in unique_source if stamp not in mapped_counts]
    overlapping = _sorted_unique_timestamps(
        stamp for stamp, count in mapped_counts.items() if count > 1
    )

    return ValidationResult(
        valid=not issues,
        issues=issues,
        alias=alias,
        total_rows=len(mapped.rows),
        answered=answered,
        not_applicable=not_applicable,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        transcript_timestamps=unique_source,
        mapped_timestamps=unique_mapped,
        unmapped_timestamps=unmapped,
        overlapping_timestamps=overlapping,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("questionnaire_path")
    parser.add_argument("mapped_file_path")
    parser.add_argument("--transcript", dest="transcript_path")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--allow-missing-highlight",
        action="store_true",
        help="Disable yellow-highlight validation for legacy fixtures.",
    )
    args = parser.parse_args()

    result = validate_mapping(
        args.questionnaire_path,
        args.mapped_file_path,
        args.transcript_path,
        require_highlight=not args.allow_missing_highlight,
    )
    if args.as_json:
        print(json.dumps(result.to_dict(), ensure_ascii=False))
    elif result.valid:
        print(
            "VALIDATION_PASSED: structure, verbatim source responses, summary, and coverage are valid."
        )
    else:
        for issue in result.issues:
            print(f"VALIDATION_FAILED [{issue.code}]: {issue.message}")
    raise SystemExit(0 if result.valid else 1)


if __name__ == "__main__":
    main()
