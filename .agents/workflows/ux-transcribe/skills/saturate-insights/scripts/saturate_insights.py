"""Deterministic renderer for validated saturation insight data.

This module does not extract or consolidate insights. ``insights_pipeline.py``
validates the canonical ``mapped-transcript.md``, grounds evidence, derives
statuses, and calls :func:`render_outputs` inside an atomic staging directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from insight_schema import SchemaError

try:
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker

    MATPLOTLIB_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised through monkeypatching
    MATPLOTLIB_AVAILABLE = False


VALID_STATUSES = {"new", "repeated", "absent"}


class MissingDependencyError(RuntimeError):
    """Raised when a required renderer dependency is unavailable."""


def load_insights(data_file: str | os.PathLike[str]) -> dict[str, Any]:
    """Load persistent validated insight data."""
    path = os.fspath(data_file)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Insight data file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid insight data JSON: {exc}") from exc


def _non_empty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{path} must be a non-empty string.")
    return value.strip()


def validate_schema(data: Any) -> None:
    """Validate the complete deterministic renderer input schema."""
    if not isinstance(data, dict):
        raise SchemaError("Insight data root must be an object.")
    if data.get("schema_version") != 2:
        raise SchemaError("Insight data schema_version must be 2.")
    _non_empty_string(data.get("input_file"), "input_file")
    signature = data.get("input_signature")
    if not isinstance(signature, dict) or not isinstance(signature.get("sha256"), str):
        raise SchemaError("input_signature must contain a sha256 value.")

    interviewees = data.get("interviewees")
    if not isinstance(interviewees, list) or not interviewees:
        raise SchemaError("interviewees must be a non-empty list.")
    normalized_interviewees = [
        _non_empty_string(value, f"interviewees[{index}]")
        for index, value in enumerate(interviewees)
    ]
    if len(set(normalized_interviewees)) != len(normalized_interviewees):
        raise SchemaError("interviewees must be unique.")

    master_insights = data.get("master_insights")
    if not isinstance(master_insights, list):
        raise SchemaError("master_insights must be a list.")
    seen_ids: set[int] = set()
    seen_evidence: set[str] = set()
    expected_participants = set(normalized_interviewees)
    for index, master in enumerate(master_insights):
        prefix = f"master_insights[{index}]"
        if not isinstance(master, dict):
            raise SchemaError(f"{prefix} must be an object.")
        insight_id = master.get("id")
        if not isinstance(insight_id, int) or isinstance(insight_id, bool) or insight_id <= 0:
            raise SchemaError(f"{prefix}.id must be a positive integer.")
        if insight_id in seen_ids:
            raise SchemaError(f"Duplicate master insight ID: {insight_id}")
        seen_ids.add(insight_id)
        _non_empty_string(master.get("theme"), f"{prefix}.theme")
        insight = _non_empty_string(master.get("insight"), f"{prefix}.insight")
        if "," not in insight:
            raise SchemaError(f"{prefix}.insight must contain behavior and cause.")
        evidence_ids = master.get("evidence_ids")
        if not isinstance(evidence_ids, list) or not evidence_ids:
            raise SchemaError(f"{prefix}.evidence_ids must be non-empty.")
        for evidence_id in evidence_ids:
            evidence_id = _non_empty_string(evidence_id, f"{prefix}.evidence_ids")
            if evidence_id in seen_evidence:
                raise SchemaError(f"Evidence is assigned more than once: {evidence_id}")
            seen_evidence.add(evidence_id)

        participant_entries = master.get("interviewees")
        if not isinstance(participant_entries, dict):
            raise SchemaError(f"{prefix}.interviewees must be an object.")
        if set(participant_entries) != expected_participants:
            raise SchemaError(f"{prefix}.interviewees must exactly match interviewees.")
        present_statuses: list[str] = []
        quote_ids: set[str] = set()
        for participant in normalized_interviewees:
            entry = participant_entries[participant]
            entry_prefix = f"{prefix}.interviewees[{participant!r}]"
            if not isinstance(entry, dict):
                raise SchemaError(f"{entry_prefix} must be an object.")
            status = entry.get("status")
            if status not in VALID_STATUSES:
                raise SchemaError(f"{entry_prefix}.status is invalid.")
            quotes = entry.get("quotes")
            if not isinstance(quotes, list):
                raise SchemaError(f"{entry_prefix}.quotes must be a list.")
            if status == "absent" and quotes:
                raise SchemaError(f"{entry_prefix} cannot have quotes when absent.")
            if status != "absent" and not quotes:
                raise SchemaError(f"{entry_prefix} requires grounded quotes.")
            if status != "absent":
                present_statuses.append(status)
            for quote_index, quote in enumerate(quotes):
                quote_prefix = f"{entry_prefix}.quotes[{quote_index}]"
                if not isinstance(quote, dict):
                    raise SchemaError(f"{quote_prefix} must be an object.")
                evidence_id = _non_empty_string(quote.get("evidence_id"), f"{quote_prefix}.evidence_id")
                if evidence_id in quote_ids:
                    raise SchemaError(f"Duplicate quote evidence in {prefix}: {evidence_id}")
                quote_ids.add(evidence_id)
                if quote.get("participant") != participant:
                    raise SchemaError(f"{quote_prefix}.participant does not match its entry.")
                for field in (
                    "question_number",
                    "theme",
                    "question",
                    "observed_variable",
                    "timestamp",
                    "quote",
                ):
                    _non_empty_string(quote.get(field), f"{quote_prefix}.{field}")
        if present_statuses.count("new") != 1:
            raise SchemaError(f"{prefix} must contain exactly one new participant.")
        if quote_ids != set(evidence_ids):
            raise SchemaError(f"{prefix} quote evidence must match evidence_ids exactly.")


def _escape_table_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")


def _safe_heading(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _sanitize_filename(value: str) -> str:
    safe = re.sub(r"[^\w\-]", "_", value, flags=re.UNICODE)
    return re.sub(r"_+", "_", safe).strip("_") or "interviewee"


def _individual_filenames(interviewees: list[str]) -> dict[str, str]:
    filenames: dict[str, str] = {}
    used: set[str] = set()
    for participant in interviewees:
        stem = _sanitize_filename(participant)
        filename = f"all-insights-{stem}.md"
        if filename.casefold() in used:
            suffix = hashlib.sha256(participant.encode("utf-8")).hexdigest()[:8]
            filename = f"all-insights-{stem}-{suffix}.md"
        used.add(filename.casefold())
        filenames[participant] = filename
    return filenames


def _quote_text(item: dict[str, Any]) -> str:
    return f"[{item['timestamp']}] {_escape_table_cell(item['quote'])}"


def generate_individual_report(participant: str, data: dict[str, Any]) -> str:
    """Render one interviewee report from deterministic master data."""
    lines = [
        f"# Insights — {_safe_heading(participant)}",
        "",
        "| # | Theme | Insight | Grounded Quotes |",
        "|---|---|---|---|",
    ]
    row_number = 0
    for master in data["master_insights"]:
        entry = master["interviewees"][participant]
        if entry["status"] == "absent":
            continue
        row_number += 1
        quotes = "<br><br>".join(_quote_text(item) for item in entry["quotes"])
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row_number),
                    _escape_table_cell(master["theme"]),
                    _escape_table_cell(master["insight"]),
                    quotes,
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def _new_counts(data: dict[str, Any]) -> dict[str, int]:
    return {
        participant: sum(
            1
            for master in data["master_insights"]
            if master["interviewees"][participant]["status"] == "new"
        )
        for participant in data["interviewees"]
    }


def generate_saturation_section(data: dict[str, Any], output_dir: str) -> tuple[str, str]:
    """Render the matrix Markdown and an order-preserving chart."""
    if not MATPLOTLIB_AVAILABLE:
        raise MissingDependencyError("matplotlib is required to generate saturation-chart.png")
    interviewees = data["interviewees"]
    status_symbols = {"new": "🔵", "repeated": "🌐", "absent": "⚪️"}
    lines = [
        "# Data Saturation Matrix",
        "",
        "| " + " | ".join(["Insight", *(_escape_table_cell(name) for name in interviewees)]) + " |",
        "| " + " | ".join(["---"] * (len(interviewees) + 1)) + " |",
    ]
    for master in data["master_insights"]:
        row = [_escape_table_cell(master["insight"])]
        row.extend(
            status_symbols[master["interviewees"][participant]["status"]]
            for participant in interviewees
        )
        lines.append("| " + " | ".join(row) + " |")
    counts = _new_counts(data)
    lines.append(
        "| "
        + " | ".join(["**🔵 New Insights**", *(str(counts[name]) for name in interviewees)])
        + " |"
    )
    lines.extend(["", "## Data Saturation Chart", "", "![Data Saturation Curve](saturation-chart.png)", ""])

    chart_path = os.path.join(output_dir, "saturation-chart.png")
    x_values = list(range(len(interviewees)))
    y_values = [counts[name] for name in interviewees]
    figure = None
    try:
        figure, axis = plt.subplots(figsize=(10, 6))
        axis.plot(x_values, y_values, marker="o", color="#2b8a3e", linewidth=3, markersize=8)
        axis.fill_between(x_values, y_values, color="#40c057", alpha=0.3)
        axis.set_title("Data Saturation Curve (Marginal New Insights)", fontsize=16, fontweight="bold", pad=20)
        axis.set_xlabel("Interview Sequence", fontsize=12, labelpad=10)
        axis.set_ylabel("New Findings Discovered", fontsize=12, labelpad=10)
        axis.set_xticks(x_values, interviewees, rotation=30, ha="right")
        axis.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
        axis.grid(axis="y", linestyle="--", alpha=0.7)
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        figure.tight_layout()
        figure.savefig(chart_path, dpi=300, bbox_inches="tight")
    finally:
        if figure is not None:
            plt.close(figure)
    return "\n".join(lines), chart_path


def generate_combined_report(data: dict[str, Any], saturation_section: str) -> str:
    """Render the complete canonical ``insights.md`` content."""
    lines = ["# Compiled Insights", "", "## Summary of Master Insights", ""]
    for master in data["master_insights"]:
        lines.append(
            f"- **{_safe_heading(master['theme'])}**: {_safe_heading(master['insight'])}"
        )
    lines.extend(["", "---", ""])
    for index, participant in enumerate(data["interviewees"]):
        lines.append(generate_individual_report(participant, data).rstrip())
        if index < len(data["interviewees"]) - 1:
            lines.extend(["", "---", ""])
    lines.extend(["", "---", "", saturation_section.rstrip(), ""])
    return "\n".join(lines)


def generate_review_manifest(data: dict[str, Any]) -> str:
    """Render an auditable quote-to-source manifest."""
    lines = [
        "# Insights Grounding Review Manifest",
        "",
        f"- Input: `{data['input_file']}`",
        f"- SHA-256: `{data['input_signature']['sha256']}`",
        f"- Interviewees: {len(data['interviewees'])}",
        f"- Master insights: {len(data['master_insights'])}",
        "",
        "| Evidence ID | Master Insight | Interviewee | Row | Timestamp | Quote | Grounded |",
        "|---|---|---|---|---|---|---|",
    ]
    for master in data["master_insights"]:
        for participant in data["interviewees"]:
            for item in master["interviewees"][participant]["quotes"]:
                row_label = f"{item['question_number']} · {item['observed_variable']}"
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            _escape_table_cell(item["evidence_id"]),
                            str(master["id"]),
                            _escape_table_cell(participant),
                            _escape_table_cell(row_label),
                            _escape_table_cell(item["timestamp"]),
                            _escape_table_cell(item["quote"]),
                            "✅",
                        ]
                    )
                    + " |"
                )
    lines.append("")
    return "\n".join(lines)


def _write_text(path: str, content: str) -> None:
    Path(path).write_text(content, encoding="utf-8")


def render_outputs(data: dict[str, Any], output_dir: str | os.PathLike[str]) -> list[str]:
    """Render every canonical artifact into an existing staging directory."""
    validate_schema(data)
    destination = os.path.abspath(os.fspath(output_dir))
    if not os.path.isdir(destination):
        raise ValueError(f"Output directory does not exist: {destination}")

    saturation_section, chart_path = generate_saturation_section(data, destination)
    filenames = _individual_filenames(data["interviewees"])
    output_paths: list[str] = []
    for participant in data["interviewees"]:
        path = os.path.join(destination, filenames[participant])
        _write_text(path, generate_individual_report(participant, data))
        output_paths.append(path)

    combined_path = os.path.join(destination, "insights.md")
    _write_text(combined_path, generate_combined_report(data, saturation_section))
    output_paths.append(combined_path)

    data_path = os.path.join(destination, "insights-data.json")
    with open(data_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    output_paths.append(data_path)

    review_path = os.path.join(destination, "insights-review-manifest.md")
    _write_text(review_path, generate_review_manifest(data))
    output_paths.extend([review_path, chart_path])
    return output_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Render validated saturation insight data.")
    parser.add_argument("data_file", help="Path to validated insights-data JSON.")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        data = load_insights(args.data_file)
        paths = render_outputs(data, args.output_dir)
        payload = {"status": "success", "output_files": [os.path.basename(path) for path in paths]}
        code = 0
    except MissingDependencyError as exc:
        payload = {"status": "error", "error_code": "MISSING_DEPENDENCY", "message": str(exc)}
        code = 1
    except (FileNotFoundError, ValueError, OSError) as exc:
        payload = {"status": "error", "error_code": "GENERATION_ERROR", "message": str(exc)}
        code = 1
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
