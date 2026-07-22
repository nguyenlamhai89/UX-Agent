"""Schema, parsing, and grounding helpers for the insight pipeline."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BASE_HEADERS = ["#", "Theme", "Question", "Observed Variable"]
TIMESTAMP_RE = re.compile(r"\[(\d{2}:\d{2}(?::\d{2})?)\]")
PLAIN_TIMESTAMP_RE = re.compile(r"^\d{2}:\d{2}(?::\d{2})?$")
SEPARATOR_RE = re.compile(r"^:?-{3,}:?$")
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


class SchemaError(ValueError):
    """Raised when mapped, extraction, or consolidation data is invalid."""


@dataclass(frozen=True)
class MappedTranscript:
    """Validated canonical mapped transcript."""

    path: str
    headers: list[str]
    interviewees: list[str]
    rows: list[dict[str, Any]]


def file_signature(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Return a stable signature for a file without loading it all into memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = os.stat(path)
    return {
        "sha256": digest.hexdigest(),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _split_markdown_row(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        raise SchemaError("Every mapped-transcript table row must start and end with '|'.")
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(SEPARATOR_RE.fullmatch(cell) for cell in cells)


def parse_mapped_transcript(path: str | os.PathLike[str]) -> MappedTranscript:
    """Parse and strictly validate canonical ``mapped-transcript.md``."""
    resolved = os.path.abspath(os.fspath(path))
    if not os.path.isabs(os.fspath(path)):
        raise SchemaError("mapped_transcript_file must be an absolute path.")
    if os.path.basename(resolved) != "mapped-transcript.md":
        raise SchemaError("Input basename must be exactly 'mapped-transcript.md'.")
    if not os.path.isfile(resolved):
        raise SchemaError(f"Mapped transcript not found: {resolved}")

    try:
        content = Path(resolved).read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SchemaError("mapped-transcript.md must be valid UTF-8.") from exc

    if "# Mapped Transcript" not in content.splitlines():
        raise SchemaError("Missing exact '# Mapped Transcript' heading.")

    table_lines = [line for line in content.splitlines() if line.strip().startswith("|")]
    if len(table_lines) < 3:
        raise SchemaError("Mapped transcript must contain a header, separator, and data row.")

    headers = _split_markdown_row(table_lines[0])
    if headers[:4] != BASE_HEADERS:
        raise SchemaError(f"First four headers must be exactly {BASE_HEADERS}.")
    if len(headers) < 5:
        raise SchemaError("Mapped transcript must contain at least one interviewee column.")
    if len(set(headers[4:])) != len(headers[4:]) or any(not name for name in headers[4:]):
        raise SchemaError("Interviewee aliases must be non-empty and unique.")

    separator = _split_markdown_row(table_lines[1])
    if len(separator) != len(headers) or not _is_separator(separator):
        raise SchemaError("Mapped transcript separator width or format is invalid.")

    interviewees = headers[4:]
    rows: list[dict[str, Any]] = []
    seen_row_keys: set[tuple[str, str, str, str]] = set()
    for index, line in enumerate(table_lines[2:], start=1):
        cells = _split_markdown_row(line)
        if _is_separator(cells):
            raise SchemaError(f"Unexpected separator in data row {index}.")
        if len(cells) != len(headers):
            raise SchemaError(
                f"Mapped transcript row {index} has {len(cells)} cells; expected {len(headers)}."
            )
        key = tuple(cells[:4])
        if any(not value for value in key):
            raise SchemaError(f"Mapped transcript row {index} has an empty base cell.")
        if key in seen_row_keys:
            raise SchemaError(f"Duplicate mapped transcript row key at row {index}: {key}")
        seen_row_keys.add(key)
        responses: dict[str, str] = {}
        for alias, response in zip(interviewees, cells[4:]):
            if not response:
                raise SchemaError(f"Empty response for '{alias}' at row {index}.")
            if response != "N/A" and not TIMESTAMP_RE.search(response):
                raise SchemaError(
                    f"Non-N/A response for '{alias}' at row {index} lacks a timestamp."
                )
            responses[alias] = response
        rows.append({
            "question_number": key[0],
            "theme": key[1],
            "question": key[2],
            "observed_variable": key[3],
            "responses": responses,
        })

    return MappedTranscript(
        path=resolved,
        headers=headers,
        interviewees=interviewees,
        rows=rows,
    )


def render_participant_view(mapped: MappedTranscript, participant: str) -> str:
    """Render a deterministic five-column view from the canonical combined file."""
    if participant not in mapped.interviewees:
        raise SchemaError(f"Unknown interviewee: {participant}")
    lines = [
        "# Mapped Transcript Participant View",
        "",
        f"> Canonical source: `{mapped.path}`",
        f"> Interviewee: `{participant}`",
        "",
        "| " + " | ".join(BASE_HEADERS + [participant]) + " |",
        "| " + " | ".join(["---"] * 5) + " |",
    ]
    for row in mapped.rows:
        cells = [
            row["question_number"],
            row["theme"],
            row["question"],
            row["observed_variable"],
            row["responses"][participant],
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def content_signature(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def normalize_grounding_text(value: str) -> str:
    """Normalize mapped-cell markup while preserving the source words."""
    normalized = html.unescape(value)
    normalized = re.sub(r"<br\s*/?>", " ", normalized, flags=re.IGNORECASE)
    normalized = TAG_RE.sub("", normalized)
    normalized = normalized.replace("**", "").replace("__", "")
    return WHITESPACE_RE.sub(" ", normalized).strip()


def _require_non_empty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{path} must be a non-empty string.")
    return value.strip()


def _validate_insight_phrase(value: Any, path: str) -> str:
    insight = _require_non_empty_string(value, path)
    if "," not in insight:
        raise SchemaError(f"{path} must use the '<behavior/emotion>, <cause>' format.")
    behavior, cause = insight.split(",", 1)
    if not behavior.strip() or not cause.strip():
        raise SchemaError(f"{path} must include content on both sides of the comma.")
    return insight


def _row_index(mapped: MappedTranscript) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    return {
        (
            row["question_number"],
            row["theme"],
            row["question"],
            row["observed_variable"],
        ): row
        for row in mapped.rows
    }


def validate_extraction_candidate(
    candidate: Any,
    mapped: MappedTranscript,
    participant: str,
) -> dict[str, Any]:
    """Validate a participant extraction and ground every quote to the combined file."""
    if not isinstance(candidate, dict):
        raise SchemaError("Extraction candidate root must be an object.")
    if candidate.get("participant") != participant:
        raise SchemaError("Extraction candidate participant does not match its task.")
    insights = candidate.get("insights")
    if not isinstance(insights, list):
        raise SchemaError("Extraction candidate 'insights' must be a list.")

    rows = _row_index(mapped)
    local_ids: set[str] = set()
    evidence_ids: set[str] = set()
    validated_insights: list[dict[str, Any]] = []
    for insight_index, insight_data in enumerate(insights):
        prefix = f"insights[{insight_index}]"
        if not isinstance(insight_data, dict):
            raise SchemaError(f"{prefix} must be an object.")
        local_id = _require_non_empty_string(insight_data.get("local_id"), f"{prefix}.local_id")
        if local_id in local_ids:
            raise SchemaError(f"Duplicate local insight ID: {local_id}")
        local_ids.add(local_id)
        theme = _require_non_empty_string(insight_data.get("theme"), f"{prefix}.theme")
        insight = _validate_insight_phrase(insight_data.get("insight"), f"{prefix}.insight")
        evidence = insight_data.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise SchemaError(f"{prefix}.evidence must be a non-empty list.")

        validated_evidence: list[dict[str, Any]] = []
        for evidence_index, evidence_data in enumerate(evidence):
            evidence_prefix = f"{prefix}.evidence[{evidence_index}]"
            if not isinstance(evidence_data, dict):
                raise SchemaError(f"{evidence_prefix} must be an object.")
            row_key = tuple(
                _require_non_empty_string(evidence_data.get(field), f"{evidence_prefix}.{field}")
                for field in ("question_number", "theme", "question", "observed_variable")
            )
            row = rows.get(row_key)
            if row is None:
                raise SchemaError(f"{evidence_prefix} does not match a canonical mapped row.")
            response = row["responses"][participant]
            if response == "N/A":
                raise SchemaError(f"{evidence_prefix} cannot cite an N/A response.")
            timestamp = _require_non_empty_string(
                evidence_data.get("timestamp"), f"{evidence_prefix}.timestamp"
            ).strip("[]")
            if not PLAIN_TIMESTAMP_RE.fullmatch(timestamp):
                raise SchemaError(f"{evidence_prefix}.timestamp has an invalid format.")
            if f"[{timestamp}]" not in response:
                raise SchemaError(f"{evidence_prefix}.timestamp is absent from the mapped cell.")
            quote = _require_non_empty_string(evidence_data.get("quote"), f"{evidence_prefix}.quote")
            normalized_quote = normalize_grounding_text(quote)
            normalized_response = normalize_grounding_text(response)
            if normalized_quote not in normalized_response:
                raise SchemaError(f"{evidence_prefix}.quote is not grounded in the mapped cell.")
            evidence_seed = json.dumps(
                [participant, local_id, evidence_index, row_key, timestamp, normalized_quote],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            evidence_id = "ev-" + hashlib.sha256(evidence_seed.encode("utf-8")).hexdigest()[:16]
            if evidence_id in evidence_ids:
                raise SchemaError(f"Duplicate evidence: {evidence_id}")
            evidence_ids.add(evidence_id)
            validated_evidence.append({
                "evidence_id": evidence_id,
                "participant": participant,
                "question_number": row_key[0],
                "theme": row_key[1],
                "question": row_key[2],
                "observed_variable": row_key[3],
                "timestamp": timestamp,
                "quote": normalized_quote,
            })
        validated_insights.append({
            "local_id": local_id,
            "participant": participant,
            "theme": theme,
            "insight": insight,
            "evidence": validated_evidence,
            "evidence_ids": [item["evidence_id"] for item in validated_evidence],
        })

    return {"participant": participant, "insights": validated_insights}


def build_evidence_index(extractions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index grounded evidence across validated participant extractions."""
    evidence: dict[str, dict[str, Any]] = {}
    for extraction in extractions:
        for insight in extraction["insights"]:
            for item in insight["evidence"]:
                evidence_id = item["evidence_id"]
                if evidence_id in evidence:
                    raise SchemaError(f"Duplicate evidence ID across extractions: {evidence_id}")
                evidence[evidence_id] = item
    return evidence


def validate_master_candidate(
    candidate: Any,
    evidence_index: dict[str, dict[str, Any]],
    expected_evidence_ids: set[str],
) -> dict[str, Any]:
    """Validate semantic groups while preventing unknown, missing, or duplicate evidence."""
    if not isinstance(candidate, dict):
        raise SchemaError("Consolidation candidate root must be an object.")
    groups = candidate.get("master_insights")
    if not isinstance(groups, list):
        raise SchemaError("Consolidation candidate 'master_insights' must be a list.")
    if expected_evidence_ids and not groups:
        raise SchemaError("Consolidation candidate cannot omit all expected evidence.")

    used: set[str] = set()
    validated: list[dict[str, Any]] = []
    for index, group in enumerate(groups):
        prefix = f"master_insights[{index}]"
        if not isinstance(group, dict):
            raise SchemaError(f"{prefix} must be an object.")
        theme = _require_non_empty_string(group.get("theme"), f"{prefix}.theme")
        insight = _validate_insight_phrase(group.get("insight"), f"{prefix}.insight")
        evidence_ids = group.get("evidence_ids")
        if not isinstance(evidence_ids, list) or not evidence_ids:
            raise SchemaError(f"{prefix}.evidence_ids must be a non-empty list.")
        normalized_ids: list[str] = []
        for raw_id in evidence_ids:
            evidence_id = _require_non_empty_string(raw_id, f"{prefix}.evidence_ids")
            if evidence_id not in expected_evidence_ids or evidence_id not in evidence_index:
                raise SchemaError(f"Unknown evidence ID: {evidence_id}")
            if evidence_id in used:
                raise SchemaError(f"Evidence ID appears in more than one group: {evidence_id}")
            used.add(evidence_id)
            normalized_ids.append(evidence_id)
        validated.append({
            "theme": theme,
            "insight": insight,
            "evidence_ids": normalized_ids,
        })

    missing = expected_evidence_ids - used
    if missing:
        raise SchemaError(f"Consolidation omitted evidence IDs: {sorted(missing)}")
    return {"master_insights": validated}


def derive_insights_data(
    mapped: MappedTranscript,
    master_candidate: dict[str, Any],
    evidence_index: dict[str, dict[str, Any]],
    input_signature: dict[str, Any],
) -> dict[str, Any]:
    """Derive participant statuses and output data deterministically."""
    master_insights: list[dict[str, Any]] = []
    for index, group in enumerate(master_candidate["master_insights"], start=1):
        by_participant: dict[str, list[dict[str, Any]]] = {
            participant: [] for participant in mapped.interviewees
        }
        for evidence_id in group["evidence_ids"]:
            item = evidence_index[evidence_id]
            by_participant[item["participant"]].append(item)
        first_present = next(
            (participant for participant in mapped.interviewees if by_participant[participant]),
            None,
        )
        participant_entries: dict[str, dict[str, Any]] = {}
        for participant in mapped.interviewees:
            quotes = by_participant[participant]
            status = (
                "absent"
                if not quotes
                else "new"
                if participant == first_present
                else "repeated"
            )
            participant_entries[participant] = {"status": status, "quotes": quotes}
        master_insights.append({
            "id": index,
            "theme": group["theme"],
            "insight": group["insight"],
            "evidence_ids": group["evidence_ids"],
            "interviewees": participant_entries,
        })

    return {
        "schema_version": 2,
        "input_file": mapped.path,
        "input_signature": input_signature,
        "interviewees": mapped.interviewees,
        "master_insights": master_insights,
    }
